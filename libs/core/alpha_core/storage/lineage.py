"""Lineage models and persistence for ingestion runs."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.utils.time as time_utils

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class IngestionRun(BaseModel):
    """Run-level ingestion metadata for audit and lineage.

    Cursor fields (``cursor_type`` - ``resume_safe``) are populated when a
    run completes successfully.  They allow subsequent runs to resume from the
    last watermark without duplicate window drift.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    connector_type: Literal["polling", "streaming"]
    event_types: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
    status: Literal["running", "completed", "failed"] = "running"
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    schema_version: int = 2
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    # Bridge to downstream research/backtest runs that consumed this ingestion run.
    # A downstream run (dataset_build, feature_build, etc.) should set
    # ``RunManifest.parent_run_id`` to this ``run_id`` and then call
    # ``LineageStore.link_downstream_run`` to register the linkage here too,
    # giving bidirectional traceability at zero coupling cost.
    downstream_run_ids: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Incremental-sync cursor (LA-020)
    # ------------------------------------------------------------------
    # Populated when the run completes successfully.  Consumers can call
    # ``LineageStore.get_latest_cursor`` to retrieve the most recent
    # watermark and pass it to ``DataBridge.pull_incremental`` for
    # deterministic resume.
    cursor_type: str | None = None
    """Semantics of ``cursor_value``: ``ts_event``, ``trade_id``, or ``sequence``."""
    cursor_value: str | None = None
    """Opaque string representation of the cursor position."""
    cursor_watermark_utc: datetime | None = None
    """Authoritative UTC timestamp of the last event included in this run."""
    resume_safe: bool | None = None
    """``True`` when the cursor was persisted cleanly and resume is safe."""
    # Optional reference to the replay package emitted for this run.
    replay_package_id: str | None = None

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("`venue` must be non-empty")
        return cleaned

    @field_validator("event_types")
    @classmethod
    def _normalize_event_types(cls, value: list[str]) -> list[str]:
        unique_event_types: list[str] = []
        seen: set[str] = set()
        for event_type in value:
            cleaned = event_type.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique_event_types.append(cleaned)
        return unique_event_types

    @field_validator("counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        normalized_counts: dict[str, int] = {}
        for key, count in value.items():
            cleaned_key = key.strip()
            if not cleaned_key:
                raise ValueError("`counts` keys must be non-empty")
            if count < 0:
                raise ValueError("`counts` values must be >= 0")
            normalized_counts[cleaned_key] = count
        return normalized_counts

    @field_validator("started_at", "completed_at")
    @classmethod
    def _normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return time_utils.ensure_utc(value)


@dataclass(slots=True, frozen=True)
class StartRunOptions:
    event_types: list[str] | None = None
    schema_version: int = 2
    config_snapshot: dict[str, Any] | None = None
    run_id: str | None = None
    # Initial cursor to carry forward from a previous run (used for resume).
    cursor_type: str | None = None
    cursor_value: str | None = None
    cursor_watermark_utc: datetime | None = None


class LineageStore:
    """Tracks ingestion runs for auditability."""

    def __init__(self, storage_root: Path) -> None:
        self._runs_root = storage_root / "_lineage" / "runs"
        self._runs_root.mkdir(parents=True, exist_ok=True)

    def start_run(
        self,
        venue: str,
        connector_type: Literal["polling", "streaming"],
        *,
        options: StartRunOptions | None = None,
    ) -> IngestionRun:
        resolved_options = options or StartRunOptions()
        effective_run_id = _normalize_run_id(resolved_options.run_id or uuid.uuid4().hex)
        run = IngestionRun(
            run_id=effective_run_id,
            venue=venue,
            connector_type=connector_type,
            event_types=list(resolved_options.event_types or []),
            started_at=datetime.now(tz=UTC),
            completed_at=None,
            status="running",
            counts={},
            errors=[],
            schema_version=resolved_options.schema_version,
            config_snapshot=dict(resolved_options.config_snapshot or {}),
        )
        self._persist_run(run)
        return run

    def complete_run(
        self,
        run_id: str,
        counts: dict[str, int],
        errors: list[str] | None = None,
        *,
        cursor_type: str | None = None,
        cursor_value: str | None = None,
        cursor_watermark_utc: datetime | None = None,
        resume_safe: bool | None = None,
        replay_package_id: str | None = None,
    ) -> None:
        """Mark a run as completed, optionally persisting cursor and replay-package metadata.

        Args:
            run_id: Run to complete.  Must be in ``running`` status.
            counts: Event counts by category (e.g. ``{"trades": 500}``).
            errors: Non-fatal error messages accumulated during the run.
            cursor_type: Cursor semantics (``ts_event``, ``trade_id``, ``sequence``).
            cursor_value: Opaque string cursor position.
            cursor_watermark_utc: Authoritative UTC watermark of the last event seen.
            resume_safe: Whether the cursor is safe to use as a resume point.
            replay_package_id: ID of the replay package emitted for this run.
        """
        run = self._require_run(run_id)
        self._assert_running(run, transition="complete")
        updates: dict[str, object] = {
            "completed_at": datetime.now(tz=UTC),
            "status": "completed",
            "counts": dict(counts),
            "errors": list(errors or []),
        }
        if cursor_type is not None:
            updates["cursor_type"] = cursor_type
        if cursor_value is not None:
            updates["cursor_value"] = cursor_value
        if cursor_watermark_utc is not None:
            updates["cursor_watermark_utc"] = cursor_watermark_utc
        if resume_safe is not None:
            updates["resume_safe"] = resume_safe
        if replay_package_id is not None:
            updates["replay_package_id"] = replay_package_id
        completed = self._revalidated_run(run, **updates)
        self._persist_run(completed)

    def fail_run(self, run_id: str, error: str | list[str]) -> None:
        run = self._require_run(run_id)
        self._assert_running(run, transition="fail")
        existing_errors = list(run.errors)
        failure_errors = [error] if isinstance(error, str) else [item for item in error if item]
        if not failure_errors:
            failure_errors = ["unknown failure"]
        existing_errors.extend(failure_errors)
        failed = self._revalidated_run(
            run,
            completed_at=datetime.now(tz=UTC),
            status="failed",
            errors=existing_errors,
        )
        self._persist_run(failed)

    def get_run(self, run_id: str) -> IngestionRun | None:
        run_path = self._run_path(run_id)
        if not run_path.exists():
            return None
        return IngestionRun.model_validate_json(run_path.read_text(encoding="utf-8"))

    def link_downstream_run(self, ingestion_run_id: str, downstream_run_id: str) -> None:
        """Register *downstream_run_id* as a consumer of *ingestion_run_id*.

        Idempotent — calling with the same pair twice is safe.
        This provides bidirectional traceability: the downstream
        ``RunManifest.parent_run_id`` points forward to the ingestion run,
        and the ingestion run's ``downstream_run_ids`` list points forward to
        research/backtest runs that consumed it.
        """
        run = self._require_run(ingestion_run_id)
        if downstream_run_id in run.downstream_run_ids:
            return
        updated = self._revalidated_run(
            run, downstream_run_ids=[*run.downstream_run_ids, downstream_run_id]
        )
        self._persist_run(updated)

    def get_latest_cursor(
        self,
        venue: str,
        event_type: str | None = None,
    ) -> IngestionRun | None:
        """Return the most recent completed run for *venue* that has cursor metadata.

        If *event_type* is provided, only runs that include that event type
        are considered.  Returns ``None`` when no such run exists.

        This is the primary entry-point for resume logic:

        .. code-block:: python

            prior_run = lineage_store.get_latest_cursor("polymarket", "trades")
            if prior_run and prior_run.resume_safe:
                cursor = IncrementalCursor(
                    venue_name=prior_run.venue,
                    instrument_ids=[...],
                    cursor_watermark_utc=prior_run.cursor_watermark_utc,
                )
        """
        normalized_venue = venue.strip().lower()
        normalized_event_type = event_type.strip().lower() if event_type is not None else None
        candidates: list[IngestionRun] = []
        for run_path in sorted(self._runs_root.glob("run_*.json")):
            run = IngestionRun.model_validate_json(run_path.read_text(encoding="utf-8"))
            if run.venue != normalized_venue:
                continue
            if run.status != "completed":
                continue
            if run.cursor_watermark_utc is None:
                continue
            if normalized_event_type is not None and normalized_event_type not in run.event_types:
                continue
            candidates.append(run)
        if not candidates:
            return None
        return max(candidates, key=_cursor_watermark_key)

    def list_runs(
        self,
        venue: str | None = None,
        since: datetime | None = None,
    ) -> list[IngestionRun]:
        normalized_venue = venue.strip().lower() if venue is not None else None
        since_utc = time_utils.ensure_utc(since) if since is not None else None

        runs: list[IngestionRun] = []
        for run_path in sorted(self._runs_root.glob("run_*.json")):
            run = IngestionRun.model_validate_json(run_path.read_text(encoding="utf-8"))
            if normalized_venue is not None and run.venue != normalized_venue:
                continue
            if since_utc is not None and run.started_at < since_utc:
                continue
            runs.append(run)

        return sorted(runs, key=lambda run: run.started_at, reverse=True)

    def _require_run(self, run_id: str) -> IngestionRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return run

    def _persist_run(self, run: IngestionRun) -> None:
        destination = self._run_path(run.run_id)
        tmp_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        try:
            tmp_path.replace(destination)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _run_path(self, run_id: str) -> Path:
        safe_run_id = _normalize_run_id(run_id)
        return self._runs_root / f"run_{safe_run_id}.json"

    def _assert_running(self, run: IngestionRun, *, transition: str) -> None:
        if run.status == "running":
            return
        raise ValueError(
            f"Cannot {transition} run `{run.run_id}` with terminal status `{run.status}`"
        )

    def _revalidated_run(self, run: IngestionRun, **updates: object) -> IngestionRun:
        payload = run.model_dump(mode="python")
        payload.update(updates)
        return IngestionRun.model_validate(payload)


def _normalize_run_id(run_id: str) -> str:
    cleaned = run_id.strip()
    if not cleaned:
        raise ValueError("`run_id` must be non-empty")
    if _RUN_ID_RE.fullmatch(cleaned) is None:
        raise ValueError("`run_id` contains unsupported characters; use [A-Za-z0-9._-]")
    return cleaned


def _cursor_watermark_key(run: IngestionRun) -> datetime:
    if run.cursor_watermark_utc is None:
        raise ValueError("cursor watermark is required for latest-cursor comparisons")
    return run.cursor_watermark_utc


__all__ = ["IngestionRun", "LineageStore", "StartRunOptions"]

# Re-exported for callers that want the cursor shape without importing data_bridge.
# IngestionRun.cursor_* fields mirror IncrementalCursor from data_bridge.py.
