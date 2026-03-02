"""DatasetBuilder — assembles silver Parquet into gold-tier research datasets."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.as_of as as_of_mod
import alpha_core.research.dataset as dataset_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.research.universe as universe_mod
import alpha_core.storage.conventions as storage_conventions
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.utils.time as time_utils

# ---------------------------------------------------------------------------
# Universe Parquet schema
# ---------------------------------------------------------------------------

_UNIVERSE_SCHEMA = pa.schema(
    [
        pa.field("as_of", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("market_id", pa.string(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
    ]
)


class DatasetBuildError(RuntimeError):
    """Raised when a dataset build cannot proceed due to data quality issues."""


class DatasetBuilder:
    """Assembles silver → gold datasets with strict look-ahead protection.

    Build steps (see :meth:`build`)
    --------------------------------
    1. Generate universe time series for *[start, end]*.
    2. Optionally validate quality of required silver partitions.
    3. Optionally check for gaps in required time windows.
    4. Load silver data for *[start, end]*.
    5. Apply as-of join discipline — filter by ``ts_record <= ts_event``
       so only information available at record time is retained.
    6. Write gold Parquet files + ``universe.parquet`` + ``_meta.json``.
    """

    def __init__(
        self,
        reader: parquet_reader_mod.ParquetEventReader,
        universe_mgr: universe_mod.UniverseManager,
        quality_validator: pv_mod.PartitionValidator,
        gap_detector: gap_mod.GapDetector,
        storage_root: Path,
    ) -> None:
        self._reader = reader
        self._universe_mgr = universe_mgr
        self._quality_validator = quality_validator
        self._gap_detector = gap_detector
        self._storage_root = storage_root
        self._gold_root = storage_root / storage_conventions.StorageTier.GOLD / "datasets"

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def build(self, config: dataset_mod.DatasetConfig) -> dataset_mod.DatasetManifest:
        """Build a gold dataset from silver data.

        Steps
        -----
        1. Generate universe snapshots for *[start, end]*.
        2. Validate quality if ``config.require_quality_pass`` is True.
        3. Check gaps if ``config.require_gap_free`` is True.
        4. Load silver event tables within the date range.
        5. Filter each table by ``ts_record <= ts_event`` (as-of discipline).
        6. Filter to instruments present in the union of universe snapshots.
        7. Write `trades.parquet`, `ohlcv.parquet`, `books.parquet`,
           `universe.parquet`, and `_meta.json` under the dataset directory.

        Returns:
            :class:`DatasetManifest` describing the completed build.

        Raises:
            DatasetBuildError: On quality failures or gap violations.
        """
        start_utc = time_utils.ensure_utc(config.start)
        end_utc = time_utils.ensure_utc(config.end)
        run_context = run_context_mod.make_run_context(
            "dataset_build",
            config_payload=config.model_dump(mode="json"),
        )

        # --- Step 1: Universe snapshots ---
        snapshots = self._universe_mgr.time_series(start_utc, end_utc, frequency="1d")
        all_instruments: set[str] = set()
        for snap in snapshots:
            all_instruments.update(snap.instruments)

        # --- Step 2: Quality validation ---
        quality_summary: dict[str, Any] = {"checked": False}
        if config.require_quality_pass:
            quality_summary = self._validate_quality(config, start_utc, end_utc)

        # --- Step 3: Gap detection ---
        if config.require_gap_free:
            self._check_gaps(config, all_instruments, start_utc, end_utc)

        # --- Step 4: Load silver data ---
        venues = config.venues
        raw_tables: dict[str, pa.Table] = {}

        for event_type in config.event_types:
            if event_type == "trades":
                table = self._reader.read_trades(start=start_utc, end=end_utc)
            elif event_type == "ohlcv":
                table = self._reader.read_ohlcv(start=start_utc, end=end_utc)
            elif event_type == "books":
                table = self._reader.read_books(start=start_utc, end=end_utc)
            else:
                continue

            # Venue filter
            if venues and "venue_id" in table.schema.names:
                mask = pc.is_in(
                    table.column("venue_id"),
                    value_set=pa.array([v.lower() for v in venues]),
                )
                table = table.filter(mask)

            raw_tables[event_type] = table

        # --- Step 5: As-of join — strip any rows recorded after the build cutoff ---
        aof_tables: dict[str, pa.Table] = {}
        for event_type, table in raw_tables.items():
            if "ts_record" in table.schema.names and "ts_event" in table.schema.names:
                # Keep only rows with ts_record <= end_utc to guarantee point-in-time
                # visibility for the full dataset build window.
                table = as_of_mod.as_of_filter(table, as_of_column="ts_record", cutoff=end_utc)
            aof_tables[event_type] = table

        # --- Step 6: Filter to universe instruments ---
        gold_tables: dict[str, pa.Table] = {}
        for event_type, table in aof_tables.items():
            if all_instruments and "instrument_id" in table.schema.names:
                mask = pc.is_in(
                    table.column("instrument_id"),
                    value_set=pa.array(sorted(all_instruments)),
                )
                table = table.filter(mask)
            gold_tables[event_type] = table

        # --- Step 7: Write output ---
        dataset_id = _make_dataset_id(config)
        dataset_dir = self._gold_root / config.name
        dataset_dir.mkdir(parents=True, exist_ok=True)

        row_counts: dict[str, int] = {}
        for event_type, table in gold_tables.items():
            path = dataset_dir / f"{event_type}.parquet"
            pq.write_table(table, path, compression="zstd")
            row_counts[event_type] = table.num_rows

        # Write universe snapshot table
        universe_rows: list[dict[str, object]] = []
        for snap in snapshots:
            venue_id_map = _build_venue_map(snap)
            for instr_id in snap.instruments:
                venue = venue_id_map.get(instr_id, "unknown")
                market_id = _market_for_instrument(instr_id)
                universe_rows.append(
                    {
                        "as_of": snap.as_of,
                        "instrument_id": instr_id,
                        "market_id": market_id,
                        "venue": venue,
                    }
                )

        universe_table = pa.Table.from_pylist(universe_rows, schema=_UNIVERSE_SCHEMA)
        pq.write_table(universe_table, dataset_dir / "universe.parquet", compression="zstd")

        manifest = dataset_mod.DatasetManifest(
            dataset_id=dataset_id,
            config=config,
            built_at=datetime.now(tz=UTC),
            row_counts=row_counts,
            instrument_count=len(all_instruments),
            date_range=(start_utc, end_utc),
            quality_summary=quality_summary,
            schema_version=1,
        )

        meta_path = dataset_dir / "_meta.json"
        meta_path.write_text(manifest.model_dump_json(indent=2))

        completed_context = run_context_mod.close_run_context(run_context)
        run_root = artifact_paths.run_root(self._storage_root, completed_context.run_id)
        run_root.mkdir(parents=True, exist_ok=True)

        config_path = artifact_paths.run_config_path(self._storage_root, completed_context.run_id)
        config_path.write_text(
            json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        artifact_map = {
            "dataset_meta": str(meta_path),
            "dataset_dir": str(dataset_dir),
            "universe": str(dataset_dir / "universe.parquet"),
        }
        artifacts_path = artifact_paths.run_artifacts_path(
            self._storage_root, completed_context.run_id
        )
        artifacts_path.write_text(
            json.dumps(artifact_map, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        run_manifest = manifest_mod.RunManifest(
            run=completed_context,
            dataset_id=dataset_id,
            artifacts=artifact_map,
            parent_run_id=None,
        )
        manifest_mod.write_run_manifest(
            artifact_paths.run_manifest_path(self._storage_root, completed_context.run_id),
            run_manifest,
        )

        return manifest

    def load(self, dataset_id: str) -> dataset_mod.GoldDataset:
        """Load a previously built gold dataset by *dataset_id* or name.

        *dataset_id* is matched against both the hash ID and the dataset
        directory name (``config.name``).
        """
        if not self._gold_root.exists() or not self._gold_root.is_dir():
            raise KeyError(f"No gold dataset found with id or name '{dataset_id}'")

        for candidate_dir in sorted(self._gold_root.iterdir()):
            meta_path = candidate_dir / "_meta.json"
            if not meta_path.exists():
                continue
            manifest = dataset_mod.DatasetManifest.model_validate_json(meta_path.read_text())
            if manifest.dataset_id == dataset_id or manifest.config.name == dataset_id:
                return dataset_mod.GoldDataset(manifest=manifest, dataset_dir=candidate_dir)

        raise KeyError(f"No gold dataset found with id or name '{dataset_id}'")

    def list_datasets(self) -> list[dataset_mod.DatasetManifest]:
        """Return metadata for all built gold datasets, sorted by build time."""
        if not self._gold_root.exists() or not self._gold_root.is_dir():
            return []

        manifests: list[dataset_mod.DatasetManifest] = []
        for candidate_dir in self._gold_root.iterdir():
            meta_path = candidate_dir / "_meta.json"
            if meta_path.exists():
                try:
                    manifests.append(
                        dataset_mod.DatasetManifest.model_validate_json(meta_path.read_text())
                    )
                except (OSError, ValueError):
                    pass

        return sorted(manifests, key=lambda m: m.built_at)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_quality(
        self,
        config: dataset_mod.DatasetConfig,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Run quality suites over required partitions; raise on failure."""
        from datetime import timedelta

        summary: dict[str, Any] = {"checked": True, "partitions": [], "failed": []}

        current = start.date()
        end_date = end.date()

        while current <= end_date:
            date_str = current.isoformat()
            for event_type in config.event_types:
                if event_type not in ("trades", "ohlcv", "books"):
                    continue

                venues_to_check: list[str | None] = (
                    [v.lower() for v in config.venues] if config.venues else [None]
                )
                for venue in venues_to_check:
                    if venue is None:
                        continue
                    try:
                        report = self._quality_validator.validate_partition(
                            event_type, venue, date_str
                        )
                        summary["partitions"].append(
                            {
                                "event_type": event_type,
                                "venue": venue,
                                "date": date_str,
                                "passed": report.passed,
                            }
                        )
                        if not report.passed:
                            summary["failed"].append(
                                {"event_type": event_type, "venue": venue, "date": date_str}
                            )
                    except FileNotFoundError:
                        pass  # Missing partition — not a quality failure per se

            current += timedelta(days=1)

        if summary["failed"] and config.require_quality_pass:
            raise DatasetBuildError(
                f"Quality gate blocked {len(summary['failed'])} partition(s): "
                f"{summary['failed'][:3]}..."
            )

        return summary

    def _check_gaps(
        self,
        config: dataset_mod.DatasetConfig,
        instruments: set[str],
        start: datetime,
        end: datetime,
    ) -> None:
        """Detect gaps exceeding ``config.max_gap_hours``; raise if any found."""
        max_gap_seconds = config.max_gap_hours * 3600.0

        if config.venues:
            venues_to_check = [v.lower() for v in config.venues]
        else:
            venues_to_check = list(
                {instr.split(":")[0] for instr in instruments if ":" in instr}
            )

        gaps_found: list[gap_mod.TimeGap] = []
        for venue in venues_to_check:
            venue_instruments = [
                instr for instr in instruments if instr.startswith(f"{venue}:")
            ]
            for instr_id in venue_instruments:
                gaps = self._gap_detector.detect_trade_gaps(
                    venue,
                    instr_id,
                    start=start,
                    end=end,
                    max_gap_seconds=max_gap_seconds,
                )
                gaps_found.extend(gaps)

        if gaps_found:
            raise DatasetBuildError(
                f"Gap check failed: {len(gaps_found)} gap(s) exceeding "
                f"{config.max_gap_hours}h found.  First gap: {gaps_found[0]}"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dataset_id(config: dataset_mod.DatasetConfig) -> str:
    """Deterministic SHA-256 hash of the serialised config."""
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _build_venue_map(snap: universe_mod.UniverseSnapshot) -> dict[str, str]:
    """Map instrument_id → venue using the first component of the canonical ID."""
    result: dict[str, str] = {}
    for instr_id in snap.instruments:
        parts = instr_id.split(":")
        result[instr_id] = parts[0] if parts else "unknown"
    return result


def _market_for_instrument(instrument_id: str) -> str:
    """Derive the canonical market ID from a canonical outcome ID.

    Canonical outcome IDs have the form ``{venue}:{market_id}:{outcome_id}``.
    """
    parts = instrument_id.rsplit(":", 1)
    return parts[0] if len(parts) == 2 else instrument_id


__all__ = ["DatasetBuildError", "DatasetBuilder"]
