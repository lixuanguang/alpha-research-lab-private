"""Dataset-ready handoff manifest for Research Plane consumption.

A **handoff manifest** is the contract that signals the Data Plane has finished
collecting and validating a time window and that Research Plane tools (dataset
builders, backtester replay) can safely consume it.

Lifecycle
---------
1. Ingestion run completes and lineage run is in ``completed`` status.
2. Caller assembles ``SuiteReport`` results and ``TimeGap`` lists.
3. :func:`check_gating_rules` validates the three gate conditions.
4. :func:`build_handoff_manifest` creates the manifest.
5. ``HandoffManifestStore.save(manifest)`` persists it to ``_lineage/handoffs/``.
6. ``LineageStore.mark_dataset_ready(run_id, handoff_manifest_path=path)`` links
   the manifest back to the ingestion lineage record.

Gate conditions (§12.2)
-----------------------
- Quality checks pass for required event types in target window.
- No disallowed gaps for the declared policy.
- All referenced lineage run statuses are terminal ``completed``.

Schema version
--------------
``schema_version = 1`` — fields are additive; backwards compatibility ensured
while this field is ``1``.

Usage::

    result = check_gating_rules(
        runs=[ingestion_run],
        suite_reports=reports,
        gaps=gaps,
        required_event_types=["trades", "ohlcv"],
        allow_gaps=False,
    )
    if result.passed:
        manifest = build_handoff_manifest(
            venue="kalshi",
            source_run_ids=[ingestion_run.run_id],
            window_start=start,
            window_end=end,
            event_types=["trades", "ohlcv"],
            quality_status=result.quality_status,
            gap_status=result.gap_status,
            watermarks=result.watermarks,
            partition_refs=["silver/trades/venue=kalshi/date=2026-03-01"],
        )
        path = store.save(manifest)
        lineage_store.mark_dataset_ready(ingestion_run.run_id, handoff_manifest_path=str(path))
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.utils.time as time_utils

# ---------------------------------------------------------------------------
# Sub-models (mirror §12.2 JSON fields)
# ---------------------------------------------------------------------------


class QualityStatus(BaseModel):
    """Quality gate result for the handoff window."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    failed_suites: list[str] = Field(default_factory=list)


class GapStatus(BaseModel):
    """Gap-coverage result for the handoff window."""

    model_config = ConfigDict(extra="forbid")

    gap_free: bool
    max_gap_hours: float = Field(ge=0.0)


class WatermarkInfo(BaseModel):
    """High-water marks for the handoff window."""

    model_config = ConfigDict(extra="forbid")

    max_ts_event: datetime | None = None
    max_ts_record: datetime | None = None

    @field_validator("max_ts_event", "max_ts_record")
    @classmethod
    def _normalize_utc(cls, v: datetime | None) -> datetime | None:
        return time_utils.ensure_utc(v) if v is not None else None


# ---------------------------------------------------------------------------
# Manifest model
# ---------------------------------------------------------------------------


class DatasetHandoffManifest(BaseModel):
    """Deterministic manifest signalling a time window is ready for research consumption.

    Attributes
    ----------
    handoff_id
        Unique identifier for this manifest (auto-generated when not supplied).
        Convention: ``{YYYYMMDDTHHMMSSZ}_{venue}_{event_types_joined}``.
    source_run_ids
        IDs of the :class:`~alpha_core.storage.lineage.IngestionRun` records
        whose data is covered by this window.
    venue
        Normalized venue identifier (lowercase).
    window_start_utc
        Inclusive start of the covered time window (UTC).
    window_end_utc
        Inclusive end of the covered time window (UTC).
    event_types
        Event types covered (e.g. ``["trades", "books", "ohlcv"]``).
    quality_status
        Aggregate quality gate result across all covered event types.
    gap_status
        Gap-coverage result — whether the window is gap-free under the
        declared policy.
    watermarks
        High-water marks across all source runs.
    partition_refs
        Relative paths (from storage root) of the silver partitions covered.
    schema_version
        Schema version.  Additive changes keep this at ``1``.
    """

    model_config = ConfigDict(extra="forbid")

    handoff_id: str = Field(min_length=1)
    source_run_ids: list[str] = Field(min_length=1)
    venue: str = Field(min_length=1)
    window_start_utc: datetime
    window_end_utc: datetime
    event_types: list[str] = Field(min_length=1)
    quality_status: QualityStatus
    gap_status: GapStatus
    watermarks: WatermarkInfo
    partition_refs: list[str] = Field(default_factory=list)
    schema_version: Literal[1] = 1

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("event_types")
    @classmethod
    def _normalize_event_types(cls, v: list[str]) -> list[str]:
        return [et.strip().lower() for et in v]

    @field_validator("window_start_utc", "window_end_utc")
    @classmethod
    def _normalize_utc(cls, v: datetime) -> datetime:
        return time_utils.ensure_utc(v)

    def is_dataset_ready(self) -> bool:
        """Return True when all gate conditions are satisfied."""
        return self.quality_status.passed and self.gap_status.gap_free


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


class GatedHandoffResult(BaseModel):
    """Output of :func:`check_gating_rules`."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    gate_errors: list[str] = Field(default_factory=list)
    quality_status: QualityStatus
    gap_status: GapStatus
    watermarks: WatermarkInfo


def check_gating_rules(
    *,
    runs: list[object],
    suite_reports: list[object],
    gaps: list[object],
    required_event_types: list[str],
    allow_gaps: bool = False,
) -> GatedHandoffResult:
    """Validate the three §12.2 gate conditions.

    This function is deliberately typed with ``object`` for the collection
    elements to avoid circular imports at call sites — callers pass
    :class:`~alpha_core.storage.lineage.IngestionRun`,
    :class:`~alpha_core.quality.base.SuiteReport`, and
    :class:`~alpha_core.quality.gap_detector.TimeGap` instances directly.
    Duck-typed attribute access is used throughout.

    Args:
        runs: Lineage ``IngestionRun`` instances that must all be ``completed``.
        suite_reports: ``SuiteReport`` instances covering the target window.
        gaps: ``TimeGap`` instances detected in the target window.
        required_event_types: Event types that must have passing quality reports.
        allow_gaps: When ``True``, gaps are logged but do not block the gate.

    Returns:
        A :class:`GatedHandoffResult` with ``passed=True`` iff all gates clear.
    """
    errors: list[str] = []
    normalized_required = {et.strip().lower() for et in required_event_types}

    # Gate 1 — all lineage runs must be terminal `completed`
    for run in runs:
        status = getattr(run, "status", None)
        run_id = getattr(run, "run_id", "<unknown>")
        if status != "completed":
            errors.append(f"Run `{run_id}` is not completed (status={status!r})")

    # Gate 2 — quality checks must pass for required event types
    covered_event_types: set[str] = set()
    failed_suites: list[str] = []
    for report in suite_reports:
        suite_name: str = getattr(report, "suite_name", "")
        passed: bool = getattr(report, "passed", False)
        # Map suite_name to event_type: "silver_trades" → "trades"
        event_type = suite_name.removeprefix("silver_").split("_")[0]
        covered_event_types.add(event_type)
        if not passed:
            failed_suites.append(suite_name)
            errors.append(f"Quality suite `{suite_name}` did not pass")

    missing = normalized_required - covered_event_types
    for et in sorted(missing):
        errors.append(f"No quality report found for required event type `{et}`")

    quality_passed = not failed_suites and not missing
    quality_status = QualityStatus(passed=quality_passed, failed_suites=failed_suites)

    # Gate 3 — gap policy
    max_gap_hours = 0.0
    if gaps:
        max_gap_seconds = max(getattr(g, "duration_seconds", 0.0) for g in gaps)
        max_gap_hours = max_gap_seconds / 3600.0
        if not allow_gaps:
            errors.append(f"{len(gaps)} gap(s) detected; max gap {max_gap_hours:.2f}h")

    gap_status = GapStatus(
        gap_free=not bool(gaps),
        max_gap_hours=round(max_gap_hours, 6),
    )

    # Watermarks — take the maximum across all completed runs
    max_ts_event: datetime | None = None
    max_ts_record: datetime | None = None
    for run in runs:
        wm = getattr(run, "cursor_watermark_utc", None)
        if wm is not None:
            wm_utc = time_utils.ensure_utc(wm)
            if max_ts_event is None or wm_utc > max_ts_event:
                max_ts_event = wm_utc
    watermarks = WatermarkInfo(
        max_ts_event=max_ts_event,
        max_ts_record=max_ts_record,
    )

    return GatedHandoffResult(
        passed=len(errors) == 0,
        gate_errors=errors,
        quality_status=quality_status,
        gap_status=gap_status,
        watermarks=watermarks,
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_handoff_manifest(
    *,
    venue: str,
    source_run_ids: list[str],
    window_start: datetime,
    window_end: datetime,
    event_types: list[str],
    quality_status: QualityStatus,
    gap_status: GapStatus,
    watermarks: WatermarkInfo,
    partition_refs: list[str] | None = None,
    handoff_id: str | None = None,
) -> DatasetHandoffManifest:
    """Build a :class:`DatasetHandoffManifest` from the provided components.

    Args:
        venue: Venue name (normalized to lowercase).
        source_run_ids: IDs of the ingestion runs that produced the data.
        window_start: Inclusive window start (UTC).
        window_end: Inclusive window end (UTC).
        event_types: Event types covered (e.g. ``["trades", "ohlcv"]``).
        quality_status: Output of quality gate evaluation.
        gap_status: Output of gap gate evaluation.
        watermarks: High-water marks for the window.
        partition_refs: Optional silver partition paths covered.
        handoff_id: Override for the manifest ID.  Auto-generated when omitted.

    Returns:
        A constructed :class:`DatasetHandoffManifest`.
    """
    start_utc = time_utils.ensure_utc(window_start)
    effective_id = handoff_id or _generate_handoff_id(
        venue=venue.strip().lower(),
        event_types=event_types,
        window_start=start_utc,
    )
    return DatasetHandoffManifest(
        handoff_id=effective_id,
        source_run_ids=list(source_run_ids),
        venue=venue,
        window_start_utc=start_utc,
        window_end_utc=time_utils.ensure_utc(window_end),
        event_types=list(event_types),
        quality_status=quality_status,
        gap_status=gap_status,
        watermarks=watermarks,
        partition_refs=list(partition_refs or []),
    )


def _generate_handoff_id(
    *,
    venue: str,
    event_types: list[str],
    window_start: datetime,
) -> str:
    ts = window_start.strftime("%Y%m%dT%H%M%SZ")
    et_tag = "_".join(sorted(et.lower() for et in event_types)) or "unknown"
    suffix = uuid.uuid4().hex[:8]
    return f"{ts}_{venue}_{et_tag}_{suffix}"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class HandoffManifestStore:
    """Persist and retrieve dataset-ready handoff manifests.

    Manifests are stored as JSON files under
    ``{storage_root}/_lineage/handoffs/{handoff_id}.json``.

    Args:
        storage_root: Root of the data lake (same root passed to
            :class:`~alpha_core.storage.lineage.LineageStore`).
    """

    def __init__(self, storage_root: Path) -> None:
        self._handoffs_root = storage_root / "_lineage" / "handoffs"
        self._handoffs_root.mkdir(parents=True, exist_ok=True)

    def save(self, manifest: DatasetHandoffManifest) -> Path:
        """Persist a manifest and return its file path.

        The write is atomic: content is written to a temporary file and then
        renamed over the destination, matching the lineage store pattern.

        Args:
            manifest: Manifest to persist.

        Returns:
            Path to the written JSON file.
        """
        destination = self._manifest_path(manifest.handoff_id)
        tmp_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        try:
            tmp_path.replace(destination)
        finally:
            tmp_path.unlink(missing_ok=True)
        return destination

    def load(self, handoff_id: str) -> DatasetHandoffManifest | None:
        """Load a manifest by ID.  Returns ``None`` if not found.

        Args:
            handoff_id: Manifest ID to look up.
        """
        path = self._manifest_path(handoff_id)
        if not path.exists():
            return None
        return DatasetHandoffManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def list_manifests(
        self,
        venue: str | None = None,
        *,
        dataset_ready_only: bool = False,
    ) -> list[DatasetHandoffManifest]:
        """Return all stored manifests, newest first.

        Args:
            venue: Filter by venue (case-insensitive). ``None`` returns all.
            dataset_ready_only: When ``True``, only return manifests where
                both quality and gap gates passed
                (i.e. :meth:`DatasetHandoffManifest.is_dataset_ready`).
        """
        normalized_venue = venue.strip().lower() if venue is not None else None
        manifests: list[DatasetHandoffManifest] = []
        for path in sorted(self._handoffs_root.glob("*.json")):
            manifest = DatasetHandoffManifest.model_validate_json(path.read_text(encoding="utf-8"))
            if normalized_venue is not None and manifest.venue != normalized_venue:
                continue
            if dataset_ready_only and not manifest.is_dataset_ready():
                continue
            manifests.append(manifest)

        return sorted(manifests, key=lambda m: m.window_start_utc, reverse=True)

    def _manifest_path(self, handoff_id: str) -> Path:
        # Sanitise to prevent directory traversal
        safe_id = handoff_id.strip().replace("/", "_").replace("..", "_")
        return self._handoffs_root / f"{safe_id}.json"


__all__ = [
    "DatasetHandoffManifest",
    "GapStatus",
    "GatedHandoffResult",
    "HandoffManifestStore",
    "QualityStatus",
    "WatermarkInfo",
    "build_handoff_manifest",
    "check_gating_rules",
]
