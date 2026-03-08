"""Replay-package manifest schema and store for deterministic research replay.

A **replay package** is a lightweight manifest that points at a set of
immutable data partitions in the silver layer and describes how to order and
combine them for deterministic backtesting and research replay.

Research runners (``build-dataset``, backtester replay) can consume a replay
package directly instead of scanning raw silver partitions — the manifest
guarantees window coverage, ordering policy, and event-count integrity before
any data is loaded.

Typical lifecycle
-----------------
1. Backfill run completes → :func:`build_replay_package` creates a manifest.
2. Manifest is persisted via :class:`ReplayPackageStore`.
3. Lineage run is updated with ``replay_package_id`` for traceability.
4. Research runner loads the manifest and issues partition-scoped DuckDB queries
   in the order dictated by ``ordering_policy``.

Schema version
--------------
``schema_version = 1``  — fields are additive; backwards compatibility ensured
while this field is ``1``.

Usage::

    store = ReplayPackageStore(settings.storage.base_path)
    manifest = build_replay_package(
        venue="polymarket",
        source_run_ids=["abc123"],
        window_start=start,
        window_end=end,
        instrument_ids=["p:mkt1:yes"],
        event_types=["trades"],
        partition_refs=[...],
        cursor_watermark_utc=end,
    )
    store.save(manifest)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.utils.time as time_utils

# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class ReplayOrderingPolicy(StrEnum):
    """Event-ordering policy applied when consuming a replay package.

    ``EVENT_TIME``
        Order strictly by ``ts_event``.  Deterministic when events have unique
        timestamps.  Default for most research use cases.
    ``RECORD_TIME``
        Order by ``ts_record`` (the time the event was received and stored).
        Useful for point-in-time correctness studies.
    ``HYBRID``
        Primary sort by ``ts_event``, secondary sort by ``ts_record`` to break
        ties.  Recommended for replay over live data.
    """

    EVENT_TIME = "event_time"
    RECORD_TIME = "record_time"
    HYBRID = "hybrid"


class ReplayPartitionRef(BaseModel):
    """Reference to a single Hive-partitioned data shard included in a package.

    Attributes
    ----------
    venue
        Normalized venue identifier (lowercase).
    event_type
        Data type: ``"trades"``, ``"ohlcv"``, ``"books"``, or ``"book_deltas"``.
    date
        Partition date in ``YYYY-MM-DD`` format.
    hour
        Optional hour partition (used by book/book-delta datasets).
        ``None`` for date-level partitions (trades, OHLCV).
    partition_path
        Relative path from the storage root to the Parquet directory or file.
    row_count
        Expected number of rows in this shard.  ``-1`` means unknown.
    """

    model_config = ConfigDict(extra="forbid")

    venue: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    date: str = Field(min_length=8, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")
    hour: str | None = None
    partition_path: str = Field(min_length=1)
    row_count: int = Field(default=-1, ge=-1)

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("event_type")
    @classmethod
    def _normalize_event_type(cls, v: str) -> str:
        return v.strip().lower()


class ReplayPackageManifest(BaseModel):
    """Manifest describing a deterministic, replay-ready event package.

    Attributes
    ----------
    package_id
        UUID-like identifier unique to this manifest.  Stored in the lineage
        run as ``replay_package_id``.
    created_at
        UTC timestamp when this manifest was created.
    venue
        Normalized venue identifier.
    source_run_ids
        IDs of the :class:`~alpha_core.storage.lineage.IngestionRun` records
        whose data is covered by this package.
    instrument_ids
        Canonical instrument IDs covered.  May be empty for venue-wide packages.
    window_start
        Inclusive window start (UTC).
    window_end
        Inclusive window end (UTC).
    event_types
        Event types covered (e.g. ``["trades", "ohlcv"]``).
    partitions
        Ordered list of partition references that together cover the window.
    ordering_policy
        Ordering policy to apply when consuming events from this package.
    total_event_count
        Sum of ``row_count`` across all partition refs.  ``-1`` when unknown.
    integrity_hash
        Deterministic SHA-256 fingerprint of the manifest's source_run_ids,
        window, event_types, and partition_path list.  Used to detect manifest
        corruption or accidental mutation.
    cursor_watermark_utc
        Watermark of the last event in the most recent source run.  Research
        runners can use this to anchor the next incremental pull.
    schema_version
        Schema version.  Increment when adding required fields.
    """

    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(min_length=1)
    created_at: datetime
    venue: str = Field(min_length=1)
    source_run_ids: list[str] = Field(min_length=1)
    instrument_ids: list[str] = Field(default_factory=list)
    window_start: datetime
    window_end: datetime
    event_types: list[str] = Field(min_length=1)
    partitions: list[ReplayPartitionRef] = Field(default_factory=list)
    ordering_policy: ReplayOrderingPolicy = ReplayOrderingPolicy.EVENT_TIME
    total_event_count: int = Field(default=-1, ge=-1)
    integrity_hash: str = Field(min_length=1)
    cursor_watermark_utc: datetime | None = None
    schema_version: Literal[1] = 1

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("event_types")
    @classmethod
    def _normalize_event_types(cls, v: list[str]) -> list[str]:
        return [et.strip().lower() for et in v]

    @field_validator("created_at", "window_start", "window_end", "cursor_watermark_utc")
    @classmethod
    def _normalize_utc(cls, v: datetime | None) -> datetime | None:
        return time_utils.ensure_utc(v) if v is not None else None


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------


def build_replay_package(
    *,
    venue: str,
    source_run_ids: list[str],
    window_start: datetime,
    window_end: datetime,
    event_types: list[str],
    instrument_ids: list[str] | None = None,
    partition_refs: list[ReplayPartitionRef] | None = None,
    ordering_policy: ReplayOrderingPolicy = ReplayOrderingPolicy.EVENT_TIME,
    cursor_watermark_utc: datetime | None = None,
    package_id: str | None = None,
) -> ReplayPackageManifest:
    """Construct a :class:`ReplayPackageManifest` with a computed integrity hash.

    The integrity hash is a SHA-256 digest of the canonical JSON representation
    of ``(venue, source_run_ids, window_start, window_end, event_types,
    partition_paths)``.  It is suitable for change detection but not
    cryptographic verification.

    Args:
        venue: Normalized venue identifier.
        source_run_ids: IDs of ingestion runs whose data is included.
        window_start: Inclusive window start (UTC).
        window_end: Inclusive window end (UTC).
        event_types: Event types covered.
        instrument_ids: Instrument IDs covered (optional, may be empty).
        partition_refs: Partition shard references included in this package.
        ordering_policy: Event ordering policy for consumers.
        cursor_watermark_utc: Watermark of the last event (from the source run).
        package_id: Optional explicit package ID; a UUID hex is generated when
            ``None``.

    Returns:
        A fully constructed :class:`ReplayPackageManifest`.
    """
    refs = list(partition_refs or [])
    effective_package_id = package_id or uuid.uuid4().hex
    total_count = sum(r.row_count for r in refs if r.row_count >= 0) if refs else -1
    hash_payload = json.dumps(
        {
            "venue": venue.strip().lower(),
            "source_run_ids": sorted(source_run_ids),
            "window_start": time_utils.ensure_utc(window_start).isoformat(),
            "window_end": time_utils.ensure_utc(window_end).isoformat(),
            "event_types": sorted(et.strip().lower() for et in event_types),
            "partition_paths": sorted(r.partition_path for r in refs),
        },
        sort_keys=True,
    )
    integrity_hash = hashlib.sha256(hash_payload.encode()).hexdigest()

    return ReplayPackageManifest(
        package_id=effective_package_id,
        created_at=datetime.now(tz=UTC),
        venue=venue,
        source_run_ids=list(source_run_ids),
        instrument_ids=list(instrument_ids or []),
        window_start=window_start,
        window_end=window_end,
        event_types=list(event_types),
        partitions=refs,
        ordering_policy=ordering_policy,
        total_event_count=total_count,
        integrity_hash=integrity_hash,
        cursor_watermark_utc=cursor_watermark_utc,
    )


def derive_partition_refs(
    storage_root: Path,
    venue: str,
    event_types: list[str],
    window_start: datetime,
    window_end: datetime,
) -> list[ReplayPartitionRef]:
    """Scan the silver layer to discover partitions that cover the window.

    Walks the Hive-partitioned silver directory for each event type and yields
    :class:`ReplayPartitionRef` objects whose ``date`` falls within the window.
    Partitions without a ``row_count`` are emitted with ``row_count = -1``.

    Args:
        storage_root: Base data lake root (``settings.storage.base_path``).
        venue: Normalized venue identifier.
        event_types: Event types to scan (``"trades"``, ``"ohlcv"``, ``"books"``).
        window_start: Inclusive start of the replay window.
        window_end: Inclusive end of the replay window.

    Returns:
        Sorted list of :class:`ReplayPartitionRef` within the window.
    """
    refs: list[ReplayPartitionRef] = []
    silver_root = storage_root / "silver"
    start_date = time_utils.ensure_utc(window_start).date()
    end_date = time_utils.ensure_utc(window_end).date()

    _DATASET_MAP: dict[str, str] = {
        "trades": "trades",
        "ohlcv": "ohlcv",
        "books": "books",
        "book_deltas": "book_deltas",
    }

    for event_type in event_types:
        dataset_name = _DATASET_MAP.get(event_type.lower(), event_type.lower())
        dataset_root = silver_root / dataset_name
        if not dataset_root.exists():
            continue
        # Hive layout: <dataset>/venue=<venue>/date=<YYYY-MM-DD>[/hour=<HH>]
        venue_dir = dataset_root / f"venue={venue.lower()}"
        if not venue_dir.exists():
            continue
        for date_dir in sorted(venue_dir.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.startswith("date="):
                continue
            date_str = date_dir.name.removeprefix("date=")
            try:
                import datetime as _dt

                date_val = _dt.date.fromisoformat(date_str)
            except ValueError:
                continue
            if not (start_date <= date_val <= end_date):
                continue
            # Check for hour sub-partitions (books, book_deltas).
            hour_dirs = [d for d in date_dir.iterdir() if d.is_dir() and d.name.startswith("hour=")]
            if hour_dirs:
                for hour_dir in sorted(hour_dirs):
                    hour_str = hour_dir.name.removeprefix("hour=")
                    refs.append(
                        ReplayPartitionRef(
                            venue=venue,
                            event_type=event_type,
                            date=date_str,
                            hour=hour_str,
                            partition_path=str(hour_dir.relative_to(storage_root)),
                        )
                    )
            else:
                refs.append(
                    ReplayPartitionRef(
                        venue=venue,
                        event_type=event_type,
                        date=date_str,
                        partition_path=str(date_dir.relative_to(storage_root)),
                    )
                )

    return refs


# ---------------------------------------------------------------------------
# Persistent store
# ---------------------------------------------------------------------------


class ReplayPackageStore:
    """Persists and retrieves :class:`ReplayPackageManifest` JSON files.

    Manifests are stored as::

        <storage_root>/_replay_packages/pkg_<package_id>.json

    The store is write-once for safety — calling :meth:`save` a second time
    with the same ``package_id`` raises :exc:`FileExistsError`.  Use
    ``overwrite=True`` to allow replacement (e.g. in tests).
    """

    def __init__(self, storage_root: Path) -> None:
        self._packages_root = storage_root / "_replay_packages"
        self._packages_root.mkdir(parents=True, exist_ok=True)

    def save(self, manifest: ReplayPackageManifest, *, overwrite: bool = False) -> Path:
        """Persist *manifest* to disk.

        Args:
            manifest: Fully constructed manifest.
            overwrite: When ``False`` (default), raises :exc:`FileExistsError`
                if a file with the same ``package_id`` already exists.

        Returns:
            Path to the persisted JSON file.
        """
        dest = self._package_path(manifest.package_id)
        if dest.exists() and not overwrite:
            raise FileExistsError(
                f"Replay package '{manifest.package_id}' already exists at {dest}. "
                "Pass overwrite=True to replace it."
            )
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        try:
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        return dest

    def get(self, package_id: str) -> ReplayPackageManifest | None:
        """Load and return the manifest for *package_id*, or ``None``."""
        path = self._package_path(package_id)
        if not path.exists():
            return None
        return ReplayPackageManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def delete(self, package_id: str) -> bool:
        """Delete the manifest for *package_id*.

        Returns ``True`` when a manifest was removed and ``False`` when it did
        not exist.
        """
        path = self._package_path(package_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list_packages(
        self,
        venue: str | None = None,
        since: datetime | None = None,
    ) -> list[ReplayPackageManifest]:
        """Return all manifests, optionally filtered by *venue* and *since*.

        Results are sorted by ``window_end`` descending (most recent first).
        """
        normalized_venue = venue.strip().lower() if venue is not None else None
        since_utc = time_utils.ensure_utc(since) if since is not None else None

        packages: list[ReplayPackageManifest] = []
        for path in sorted(self._packages_root.glob("pkg_*.json")):
            manifest = ReplayPackageManifest.model_validate_json(path.read_text(encoding="utf-8"))
            if normalized_venue is not None and manifest.venue != normalized_venue:
                continue
            if since_utc is not None and manifest.window_end < since_utc:
                continue
            packages.append(manifest)

        return sorted(packages, key=lambda m: m.window_end, reverse=True)

    def _package_path(self, package_id: str) -> Path:
        safe_id = package_id.strip().replace("/", "_").replace("..", "_")
        return self._packages_root / f"pkg_{safe_id}.json"


__all__ = [
    "ReplayOrderingPolicy",
    "ReplayPackageManifest",
    "ReplayPackageStore",
    "ReplayPartitionRef",
    "build_replay_package",
    "derive_partition_refs",
]
