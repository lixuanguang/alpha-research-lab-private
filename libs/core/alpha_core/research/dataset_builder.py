"""DatasetBuilder — assembles silver Parquet into gold-tier research datasets."""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.as_of as as_of_mod
import alpha_core.research.dataset as dataset_mod
import alpha_core.research.dataset_builder_io as dataset_builder_io
import alpha_core.research.run_context as run_context_mod
import alpha_core.research.universe as universe_mod
import alpha_core.storage.conventions as storage_conventions
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.utils.time as time_utils


class DatasetBuildError(RuntimeError):
    """Raised when a dataset build cannot proceed due to data quality issues."""


class DatasetBuilder:
    """Assembles silver → gold datasets with strict look-ahead protection.

    Build steps (see :meth:`build`)
    --------------------------------
    1. Generate universe change-point snapshots for *[start, end]*.
    2. Optionally validate quality of required silver partitions.
    3. Optionally check for gaps in required time windows.
    4. Load silver data for *[start, end]*.
    5. Apply as-of join discipline — filter by ``ts_record <= build_end``
       so only information recorded by the dataset cutoff is retained.
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

    def build(
        self,
        config: dataset_mod.DatasetConfig,
        *,
        config_payload: dict[str, Any] | None = None,
    ) -> dataset_mod.DatasetManifest:
        """Build a gold dataset from silver data.

        Steps
        -----
        1. Generate universe change-point snapshots for *[start, end]*.
        2. Validate quality if ``config.require_quality_pass`` is True.
        3. Check gaps if ``config.require_gap_free`` is True.
        4. Load silver event tables within the date range.
        5. Filter each table by ``ts_record <= config.end`` (as-of discipline).
        6. Filter each row to instruments present in the point-in-time universe
           at that row's ``ts_event``.
        7. Write `trades.parquet`, `ohlcv.parquet`, `books.parquet`,
           `universe.parquet`, and `_meta.json` under the dataset directory.

        Returns:
            :class:`DatasetManifest` describing the completed build.

        Raises:
            DatasetBuildError: On quality failures or gap violations.
        """
        start_utc = time_utils.ensure_utc(config.start)
        end_utc = time_utils.ensure_utc(config.end)
        effective_config_payload = (
            config_payload if config_payload is not None else config.model_dump(mode="json")
        )
        run_context = run_context_mod.make_run_context(
            "dataset_build",
            config_payload=effective_config_payload,
        )
        dataset_id = dataset_builder_io.make_dataset_id(config)
        dataset_dir = dataset_builder_io.dataset_directory(self._gold_root, dataset_id)
        if dataset_dir.exists():
            raise DatasetBuildError(
                f"Dataset snapshot '{dataset_id}' already exists at {dataset_dir}. "
                "Dataset IDs are immutable; change the dataset config to create a new snapshot."
            )

        snapshots, all_instruments = self._build_universe_snapshots(config, start_utc, end_utc)
        quality_summary = self._run_quality_and_gap_checks(
            config=config,
            start_utc=start_utc,
            end_utc=end_utc,
            all_instruments=all_instruments,
        )
        gold_tables = self._build_gold_tables(
            config=config,
            start_utc=start_utc,
            end_utc=end_utc,
            snapshots=snapshots,
        )
        try:
            outputs = dataset_builder_io.write_dataset_outputs(
                gold_root=self._gold_root,
                spec=dataset_builder_io.DatasetOutputSpec(
                    config=config,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    snapshots=snapshots,
                    gold_tables=gold_tables,
                    quality_summary=quality_summary,
                    instrument_count=len(all_instruments),
                )
            )
        except FileExistsError as exc:
            raise DatasetBuildError(str(exc)) from exc
        dataset_builder_io.persist_build_artifacts(
            storage_root=self._storage_root,
            config_payload=effective_config_payload,
            run_context=run_context,
            outputs=outputs,
        )
        return outputs.manifest

    def _build_universe_snapshots(
        self,
        config: dataset_mod.DatasetConfig,
        start_utc: datetime,
        end_utc: datetime,
    ) -> tuple[list[universe_mod.UniverseSnapshot], set[str]]:
        change_points = self._universe_mgr.change_points(start_utc, end_utc)
        snapshots = [
            _scope_snapshot_to_venues(
                self._universe_mgr.snapshot_at(point),
                venues=config.venues,
            )
            for point in change_points
        ]
        all_instruments: set[str] = set()
        for snapshot in snapshots:
            all_instruments.update(snapshot.instruments)
        return snapshots, all_instruments

    def _run_quality_and_gap_checks(
        self,
        *,
        config: dataset_mod.DatasetConfig,
        start_utc: datetime,
        end_utc: datetime,
        all_instruments: set[str],
    ) -> dict[str, Any]:
        quality_summary: dict[str, Any] = {"checked": False}
        if config.require_quality_pass:
            quality_summary = self._validate_quality(
                config=config,
                start=start_utc,
                end=end_utc,
                all_instruments=all_instruments,
            )
        if config.require_gap_free:
            self._check_gaps(config, all_instruments, start_utc, end_utc)
        return quality_summary

    def _build_gold_tables(
        self,
        *,
        config: dataset_mod.DatasetConfig,
        start_utc: datetime,
        end_utc: datetime,
        snapshots: list[universe_mod.UniverseSnapshot],
    ) -> dict[str, pa.Table]:
        raw_tables = self._load_raw_tables(config, start_utc=start_utc, end_utc=end_utc)
        if _tables_have_rows(raw_tables) and not _snapshots_have_instruments(snapshots):
            raise DatasetBuildError(
                "No point-in-time universe was available for the requested window. "
                "Persist an instrument master at "
                f"{self._storage_root / 'instruments.parquet'} before building datasets."
            )
        as_of_tables = self._apply_as_of_filters(raw_tables, cutoff=end_utc)
        return self._filter_tables_by_point_in_time_universe(as_of_tables, snapshots=snapshots)

    def _load_raw_tables(
        self,
        config: dataset_mod.DatasetConfig,
        *,
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[str, pa.Table]:
        raw_tables: dict[str, pa.Table] = {}
        normalized_venues = [venue.lower() for venue in (config.venues or [])]
        for event_type in config.event_types:
            table = self._read_raw_event_table(event_type, start_utc=start_utc, end_utc=end_utc)
            if table is None:
                continue
            raw_tables[event_type] = _filter_table_by_venues(table, venues=normalized_venues)
        return raw_tables

    def _read_raw_event_table(
        self,
        event_type: str,
        *,
        start_utc: datetime,
        end_utc: datetime,
    ) -> pa.Table | None:
        if event_type == "trades":
            return self._reader.read_trades(start=start_utc, end=end_utc)
        if event_type == "ohlcv":
            return self._reader.read_ohlcv(start=start_utc, end=end_utc)
        if event_type == "books":
            return self._reader.read_books(start=start_utc, end=end_utc)
        return None

    def _apply_as_of_filters(
        self,
        tables: dict[str, pa.Table],
        *,
        cutoff: datetime,
    ) -> dict[str, pa.Table]:
        filtered: dict[str, pa.Table] = {}
        for event_type, table in tables.items():
            if "ts_record" in table.schema.names and "ts_event" in table.schema.names:
                table = as_of_mod.as_of_filter(table, as_of_column="ts_record", cutoff=cutoff)
            filtered[event_type] = table
        return filtered

    def _filter_tables_by_point_in_time_universe(
        self,
        tables: dict[str, pa.Table],
        *,
        snapshots: list[universe_mod.UniverseSnapshot],
    ) -> dict[str, pa.Table]:
        filtered: dict[str, pa.Table] = {}
        for event_type, table in tables.items():
            filtered[event_type] = _filter_table_by_universe_snapshots(table, snapshots=snapshots)
        return filtered

    def load(self, dataset_id: str) -> dataset_mod.GoldDataset:
        """Load a previously built gold dataset by *dataset_id* or name.

        *dataset_id* is matched against both the hash ID and the dataset
        directory name (``config.name``).
        """
        return dataset_builder_io.load_dataset(self._gold_root, dataset_id)

    def list_datasets(self) -> list[dataset_mod.DatasetManifest]:
        """Return metadata for all built gold datasets, sorted by build time."""
        return dataset_builder_io.list_datasets(self._gold_root)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_quality(
        self,
        *,
        config: dataset_mod.DatasetConfig,
        start: datetime,
        end: datetime,
        all_instruments: set[str],
    ) -> dict[str, Any]:
        """Run quality suites over required partitions; raise on failure."""
        summary: dict[str, Any] = {"checked": True, "partitions": [], "failed": []}
        venues_to_check = _quality_venues(config=config, all_instruments=all_instruments)
        if not venues_to_check:
            return summary

        current = start.date()
        end_date = end.date()

        while current <= end_date:
            date_str = current.isoformat()
            for event_type in config.event_types:
                if event_type not in ("trades", "ohlcv", "books"):
                    continue

                for venue in venues_to_check:
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
            venues_to_check = list({instr.split(":")[0] for instr in instruments if ":" in instr})

        gaps_found: list[gap_mod.TimeGap] = []
        for venue in venues_to_check:
            venue_instruments = [instr for instr in instruments if instr.startswith(f"{venue}:")]
            if "trades" in config.event_types:
                for instr_id in venue_instruments:
                    gaps_found.extend(
                        self._gap_detector.detect_trade_gaps(
                            venue,
                            instr_id,
                            start=start,
                            end=end,
                            max_gap_seconds=max_gap_seconds,
                        )
                    )
            if "ohlcv" in config.event_types:
                for instr_id, resolution in _ohlcv_gap_targets(
                    reader=self._reader,
                    venue=venue,
                    instruments=venue_instruments,
                    start=start,
                    end=end,
                ):
                    ohlcv_gaps = self._gap_detector.detect_ohlcv_gaps(
                            venue,
                            instr_id,
                            resolution=resolution,
                            start=start,
                            end=end,
                        )
                    gaps_found.extend(
                        _gaps_exceeding_threshold(ohlcv_gaps, max_gap_seconds=max_gap_seconds)
                    )

        if gaps_found:
            raise DatasetBuildError(
                f"Gap check failed: {len(gaps_found)} gap(s) exceeding "
                f"{config.max_gap_hours}h found.  First gap: {gaps_found[0]}"
            )


def _filter_table_by_venues(table: pa.Table, *, venues: list[str]) -> pa.Table:
    if not venues or "venue_id" not in table.schema.names:
        return table
    mask = pc.is_in(table.column("venue_id"), value_set=pa.array(venues))
    return table.filter(mask)


def _scope_snapshot_to_venues(
    snapshot: universe_mod.UniverseSnapshot,
    *,
    venues: list[str] | None,
) -> universe_mod.UniverseSnapshot:
    if not venues:
        return snapshot

    allowed_venues = set(venues)
    instruments = [
        instrument_id
        for instrument_id in snapshot.instruments
        if _identifier_venue(instrument_id) in allowed_venues
    ]
    markets = [
        market_id
        for market_id in snapshot.markets
        if _identifier_venue(market_id) in allowed_venues
    ]
    venue_breakdown = {
        venue: count
        for venue, count in snapshot.venue_breakdown.items()
        if venue in allowed_venues
    }
    filters_applied = dict(snapshot.filters_applied)
    filters_applied["venues"] = list(venues)
    return snapshot.model_copy(
        update={
            "instruments": instruments,
            "markets": markets,
            "venue_breakdown": venue_breakdown,
            "filters_applied": filters_applied,
        }
    )


def _identifier_venue(identifier: str) -> str | None:
    venue, separator, _rest = identifier.partition(":")
    if not separator:
        return None
    normalized = venue.strip().lower()
    return normalized or None


def _filter_table_by_universe_snapshots(
    table: pa.Table,
    *,
    snapshots: list[universe_mod.UniverseSnapshot],
) -> pa.Table:
    required_columns = {"instrument_id", "ts_event"}
    if table.num_rows == 0 or not required_columns.issubset(table.schema.names):
        return table

    snapshot_times = [snapshot.as_of for snapshot in snapshots]
    memberships = [frozenset(snapshot.instruments) for snapshot in snapshots]
    instrument_column = table.column("instrument_id")
    event_time_column = table.column("ts_event")

    mask_values: list[bool] = []
    for row_index in range(table.num_rows):
        instrument_id = instrument_column[row_index].as_py()
        event_time = event_time_column[row_index].as_py()
        if not isinstance(instrument_id, str) or event_time is None:
            mask_values.append(False)
            continue

        event_time_utc = time_utils.ensure_utc(event_time)
        snapshot_index = bisect_right(snapshot_times, event_time_utc) - 1
        if snapshot_index < 0:
            mask_values.append(False)
            continue
        mask_values.append(instrument_id in memberships[snapshot_index])

    return table.filter(pa.array(mask_values, type=pa.bool_()))


def _snapshots_have_instruments(snapshots: list[universe_mod.UniverseSnapshot]) -> bool:
    return any(snapshot.instruments for snapshot in snapshots)


def _tables_have_rows(tables: dict[str, pa.Table]) -> bool:
    return any(table.num_rows > 0 for table in tables.values())


def _quality_venues(
    *,
    config: dataset_mod.DatasetConfig,
    all_instruments: set[str],
) -> list[str]:
    if config.venues:
        return [venue.lower() for venue in config.venues]

    discovered_venues = {
        instrument_id.split(":", 1)[0].strip().lower()
        for instrument_id in all_instruments
        if ":" in instrument_id
    }
    return sorted(venue for venue in discovered_venues if venue)


def _ohlcv_gap_targets(
    *,
    reader: parquet_reader_mod.ParquetEventReader,
    venue: str,
    instruments: list[str],
    start: datetime,
    end: datetime,
) -> list[tuple[str, str]]:
    if not instruments:
        return []
    table = reader.read_ohlcv(venue=venue, start=start, end=end)
    required_columns = {"instrument_id", "resolution"}
    if table.num_rows == 0 or not required_columns.issubset(table.schema.names):
        return []

    instrument_set = set(instruments)
    targets: set[tuple[str, str]] = set()
    instrument_column = table.column("instrument_id")
    resolution_column = table.column("resolution")
    for row_index in range(table.num_rows):
        instrument_id = instrument_column[row_index].as_py()
        resolution = resolution_column[row_index].as_py()
        if (
            isinstance(instrument_id, str)
            and instrument_id in instrument_set
            and isinstance(resolution, str)
            and resolution.strip()
        ):
            targets.add((instrument_id, resolution.strip()))
    return sorted(targets)


def _gaps_exceeding_threshold(
    gaps: list[gap_mod.TimeGap],
    *,
    max_gap_seconds: float,
) -> list[gap_mod.TimeGap]:
    if not gaps:
        return []

    ordered = sorted(
        gaps,
        key=lambda gap: (gap.venue, gap.outcome_id, gap.event_type, gap.gap_start, gap.gap_end),
    )
    oversized: list[gap_mod.TimeGap] = []
    current = ordered[0]

    for gap in ordered[1:]:
        same_identity = (
            gap.venue == current.venue
            and gap.outcome_id == current.outcome_id
            and gap.event_type == current.event_type
        )
        if same_identity and gap.gap_start <= current.gap_end:
            merged_end = gap.gap_end if gap.gap_end > current.gap_end else current.gap_end
            current = current.model_copy(
                update={
                    "gap_end": merged_end,
                    "duration_seconds": (merged_end - current.gap_start).total_seconds(),
                }
            )
            continue

        if current.duration_seconds > max_gap_seconds:
            oversized.append(current)
        current = gap

    if current.duration_seconds > max_gap_seconds:
        oversized.append(current)
    return oversized


__all__ = ["DatasetBuildError", "DatasetBuilder"]
