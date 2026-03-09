"""Unit tests for DatasetBuilder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import alpha_core.instruments.master as master_mod
import alpha_core.instruments.models as instrument_models
import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.dataset as dataset_mod
import alpha_core.research.dataset_builder as builder_mod
import alpha_core.research.dataset_builder_io as builder_io
import alpha_core.research.universe as universe_mod
import alpha_core.storage.parquet_reader as reader_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_END = _BASE + timedelta(days=3)


def _make_market(
    venue: str,
    market_id: str,
    outcome_ids: list[str],
    *,
    first_seen: datetime | None = None,
    last_updated: datetime | None = None,
    lifecycle: instrument_models.MarketLifecycle = instrument_models.MarketLifecycle.ACTIVE,
    resolution_date: datetime | None = None,
) -> instrument_models.MarketSpec:
    return instrument_models.MarketSpec(
        market_id=market_id,
        venue=venue,
        title=f"{venue}/{market_id}",
        outcomes=[
            instrument_models.OutcomeSpec(
                outcome_id=oid,
                label=oid.upper(),
                canonical_id=f"{venue}:{market_id}:{oid}",
            )
            for oid in outcome_ids
        ],
        first_seen=first_seen or (_BASE - timedelta(days=1)),
        last_updated=last_updated or _BASE,
        lifecycle=lifecycle,
        resolution_date=resolution_date,
    )


def _trade_table(instrument_ids: list[str], ts_events: list[datetime]) -> pa.Table:
    n = len(instrument_ids)
    assert len(ts_events) == n
    schema = pa.schema(
        [
            pa.field("event_id", pa.string()),
            pa.field("instrument_id", pa.string()),
            pa.field("venue_id", pa.string()),
            pa.field("event_type", pa.string()),
            pa.field("ts_event", pa.timestamp("us", tz="UTC")),
            pa.field("ts_record", pa.timestamp("us", tz="UTC")),
            pa.field("price", pa.float64()),
            pa.field("size", pa.float64()),
        ]
    )
    return pa.table(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "instrument_id": instrument_ids,
            "venue_id": [i.split(":")[0] for i in instrument_ids],
            "event_type": ["trade"] * n,
            "ts_event": ts_events,
            "ts_record": ts_events,  # record == event for test data
            "price": [0.5] * n,
            "size": [100.0] * n,
        },
        schema=schema,
    )


def _ohlcv_table(instrument_ids: list[str], ts_events: list[datetime]) -> pa.Table:
    n = len(instrument_ids)
    assert len(ts_events) == n
    schema = pa.schema(
        [
            pa.field("event_id", pa.string()),
            pa.field("instrument_id", pa.string()),
            pa.field("venue_id", pa.string()),
            pa.field("event_type", pa.string()),
            pa.field("ts_event", pa.timestamp("us", tz="UTC")),
            pa.field("ts_record", pa.timestamp("us", tz="UTC")),
            pa.field("open", pa.float64()),
            pa.field("high", pa.float64()),
            pa.field("low", pa.float64()),
            pa.field("close", pa.float64()),
            pa.field("volume", pa.float64()),
            pa.field("resolution", pa.string()),
        ]
    )
    return pa.table(
        {
            "event_id": [f"o{i}" for i in range(n)],
            "instrument_id": instrument_ids,
            "venue_id": [i.split(":")[0] for i in instrument_ids],
            "event_type": ["ohlcv"] * n,
            "ts_event": ts_events,
            "ts_record": ts_events,
            "open": [0.5] * n,
            "high": [0.6] * n,
            "low": [0.4] * n,
            "close": [0.55] * n,
            "volume": [100.0] * n,
            "resolution": ["1h"] * n,
        },
        schema=schema,
    )


def _make_builder(
    tmp_path: Path,
    master: master_mod.MarketMaster,
    trade_table: pa.Table | None = None,
) -> builder_mod.DatasetBuilder:
    mock_reader = MagicMock(spec=reader_mod.ParquetEventReader)
    mock_reader.read_trades.return_value = trade_table if trade_table is not None else pa.table({})
    mock_reader.read_ohlcv.return_value = pa.table({})
    mock_reader.read_books.return_value = pa.table({})

    mock_validator = MagicMock(spec=pv_mod.PartitionValidator)
    mock_gap = MagicMock(spec=gap_mod.GapDetector)
    mock_gap.detect_trade_gaps.return_value = []
    mock_gap.detect_book_gaps.return_value = []
    mock_gap.detect_ohlcv_gaps.return_value = []

    mgr = universe_mod.UniverseManager(master)
    return builder_mod.DatasetBuilder(
        reader=mock_reader,
        universe_mgr=mgr,
        quality_validator=mock_validator,
        gap_detector=mock_gap,
        storage_root=tmp_path,
    )


# ---------------------------------------------------------------------------
# DatasetConfig validation
# ---------------------------------------------------------------------------


class TestDatasetConfig:
    def test_default_event_types(self) -> None:
        config = dataset_mod.DatasetConfig(name="ds", start=_BASE, end=_END)
        assert "trades" in config.event_types
        assert "ohlcv" in config.event_types

    def test_custom_event_types(self) -> None:
        config = dataset_mod.DatasetConfig(name="ds", start=_BASE, end=_END, event_types=["trades"])
        assert config.event_types == ["trades"]

    @pytest.mark.parametrize("name", ["../escape", "nested/path", "nested\\path"])
    def test_name_rejects_path_like_values(self, name: str) -> None:
        with pytest.raises(ValueError, match=r"path separators|\.\."):
            dataset_mod.DatasetConfig(name=name, start=_BASE, end=_END)


# ---------------------------------------------------------------------------
# DatasetBuilder.build
# ---------------------------------------------------------------------------


class TestDatasetBuilderBuild:
    def test_build_creates_output_files(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes", "no"]))
        ts = [_BASE + timedelta(hours=i) for i in range(3)]
        table = _trade_table(["p:m1:yes", "p:m1:no", "p:m1:yes"], ts)
        builder = _make_builder(tmp_path, master, trade_table=table)
        config = dataset_mod.DatasetConfig(
            name="test_build",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        manifest = builder.build(config)
        dataset_dir = builder_io.dataset_directory(
            tmp_path / "gold" / "datasets",
            manifest.dataset_id,
        )
        assert (dataset_dir / "_meta.json").exists()
        assert (dataset_dir / "trades.parquet").exists()
        assert (dataset_dir / "universe.parquet").exists()
        assert (tmp_path / "runs").exists()

    def test_manifest_has_correct_fields(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        builder = _make_builder(tmp_path, master)
        config = dataset_mod.DatasetConfig(
            name="manifest_check",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        manifest = builder.build(config)
        assert isinstance(manifest.dataset_id, str)
        assert len(manifest.dataset_id) == 16
        assert manifest.config.name == "manifest_check"
        assert manifest.schema_version == 1

    def test_gold_event_tables_include_dataset_provenance_columns(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        ts = [_BASE + timedelta(hours=i) for i in range(2)]
        table = _trade_table(["p:m1:yes", "p:m1:yes"], ts)
        builder = _make_builder(tmp_path, master, trade_table=table)
        manifest = builder.build(
            dataset_mod.DatasetConfig(
                name="provenance",
                start=_BASE,
                end=_END,
                require_quality_pass=False,
            )
        )
        dataset_dir = builder_io.dataset_directory(
            tmp_path / "gold" / "datasets",
            manifest.dataset_id,
        )
        trades = pq.read_table(dataset_dir / "trades.parquet")
        assert "dataset_id" in trades.schema.names
        assert "gold_schema_version" in trades.schema.names
        assert set(trades.column("dataset_id").to_pylist()) == {manifest.dataset_id}

    def test_build_persists_run_manifest(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        builder = _make_builder(tmp_path, master)
        config = dataset_mod.DatasetConfig(
            name="run_manifest_check",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        built = builder.build(config)
        runs_root = tmp_path / "runs"
        run_dirs = [path for path in runs_root.iterdir() if path.is_dir()]
        assert run_dirs, "Expected at least one run directory"

        manifest_path = run_dirs[0] / "manifest.json"
        assert manifest_path.exists()
        run_manifest = manifest_path.read_text(encoding="utf-8")
        assert built.dataset_id in run_manifest

    def test_dataset_id_is_deterministic(self, tmp_path: Path) -> None:
        config = dataset_mod.DatasetConfig(
            name="det_test",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        id1 = builder_io.make_dataset_id(config)
        id2 = builder_io.make_dataset_id(config)
        assert id1 == id2

    def test_as_of_filter_applied_to_trades(self, tmp_path: Path) -> None:
        """Rows with ts_record > end should be filtered out."""
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))

        future_ts = _END + timedelta(days=5)
        normal_ts = _BASE + timedelta(hours=2)

        schema = pa.schema(
            [
                pa.field("event_id", pa.string()),
                pa.field("instrument_id", pa.string()),
                pa.field("venue_id", pa.string()),
                pa.field("event_type", pa.string()),
                pa.field("ts_event", pa.timestamp("us", tz="UTC")),
                pa.field("ts_record", pa.timestamp("us", tz="UTC")),
                pa.field("price", pa.float64()),
                pa.field("size", pa.float64()),
            ]
        )
        table = pa.table(
            {
                "event_id": ["e1", "e2"],
                "instrument_id": ["p:m1:yes", "p:m1:yes"],
                "venue_id": ["p", "p"],
                "event_type": ["trade", "trade"],
                "ts_event": [normal_ts, normal_ts],
                "ts_record": [normal_ts, future_ts],  # second row future-recorded
                "price": [0.6, 0.7],
                "size": [100.0, 50.0],
            },
            schema=schema,
        )
        builder = _make_builder(tmp_path, master, trade_table=table)
        config = dataset_mod.DatasetConfig(
            name="aof_test",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        manifest = builder.build(config)
        # Verify only 1 row in output
        gold_path = (
            builder_io.dataset_directory(tmp_path / "gold" / "datasets", manifest.dataset_id)
            / "trades.parquet"
        )
        result = pq.read_table(gold_path)
        assert result.num_rows == 1, "Future-recorded rows must be excluded by as-of filter"

    def test_late_arriving_rows_are_reordered_by_availability(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))

        late_event = _BASE + timedelta(hours=1)
        ontime_event = _BASE + timedelta(hours=2)
        table = pa.table(
            {
                "event_id": ["late", "ontime"],
                "instrument_id": ["p:m1:yes", "p:m1:yes"],
                "venue_id": ["p", "p"],
                "event_type": ["trade", "trade"],
                "ts_event": [late_event, ontime_event],
                "ts_record": [_BASE + timedelta(hours=3), ontime_event],
                "price": [0.10, 0.55],
                "size": [10.0, 11.0],
            }
        )
        builder = _make_builder(tmp_path, master, trade_table=table)
        config = dataset_mod.DatasetConfig(
            name="availability_ordering",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )

        manifest = builder.build(config)
        gold_path = (
            builder_io.dataset_directory(tmp_path / "gold" / "datasets", manifest.dataset_id)
            / "trades.parquet"
        )
        result = pq.read_table(gold_path)

        assert "ts_available" in result.schema.names
        assert result.column("ts_available").to_pylist() == sorted(
            result.column("ts_available").to_pylist()
        )
        assert result.column("ts_event").to_pylist() == [ontime_event, late_event]

    def test_rows_before_first_seen_are_excluded_point_in_time(self, tmp_path: Path) -> None:
        """Rows from before a market enters the universe must be excluded."""
        first_seen = _BASE + timedelta(days=1)
        master = master_mod.MarketMaster()
        master.register_market(
            _make_market(
                "p",
                "late_market",
                ["yes"],
                first_seen=first_seen,
                last_updated=first_seen,
            )
        )
        table = _trade_table(
            ["p:late_market:yes", "p:late_market:yes"],
            [_BASE + timedelta(hours=1), first_seen + timedelta(hours=1)],
        )
        builder = _make_builder(tmp_path, master, trade_table=table)
        config = dataset_mod.DatasetConfig(
            name="point_in_time_market_entry",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        manifest = builder.build(config)
        gold_path = (
            builder_io.dataset_directory(tmp_path / "gold" / "datasets", manifest.dataset_id)
            / "trades.parquet"
        )
        result = pq.read_table(gold_path)
        assert result.num_rows == 1
        assert result.column("ts_event").to_pylist() == [first_seen + timedelta(hours=1)]

    def test_late_recorded_trade_keeps_trade_time_universe_membership(self, tmp_path: Path) -> None:
        resolution_time = _BASE + timedelta(hours=12)
        master = master_mod.MarketMaster()
        master.register_market(
            _make_market(
                "p",
                "resolved_market",
                ["yes"],
                first_seen=_BASE - timedelta(days=1),
                last_updated=resolution_time,
                lifecycle=instrument_models.MarketLifecycle.RESOLVED,
                resolution_date=resolution_time,
            )
        )
        trade_table = pa.table(
            {
                "event_id": ["late_trade"],
                "instrument_id": ["p:resolved_market:yes"],
                "venue_id": ["p"],
                "event_type": ["trade"],
                "ts_event": [_BASE + timedelta(hours=1)],
                "ts_record": [_BASE + timedelta(days=2)],
                "price": [0.5],
                "size": [10.0],
            }
        )
        builder = _make_builder(tmp_path, master, trade_table=trade_table)
        config = dataset_mod.DatasetConfig(
            name="late_recorded_trade_membership",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )

        manifest = builder.build(config)
        gold_path = (
            builder_io.dataset_directory(tmp_path / "gold" / "datasets", manifest.dataset_id)
            / "trades.parquet"
        )
        result = pq.read_table(gold_path)
        assert result.num_rows == 1
        assert result.column("instrument_id").to_pylist() == ["p:resolved_market:yes"]

    def test_instruments_outside_universe_excluded(self, tmp_path: Path) -> None:
        """Instruments not in the universe snapshot should be stripped."""
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "known", ["yes"]))
        # "unknown:x:y" is not in the master
        ts = [_BASE + timedelta(hours=i) for i in range(2)]
        table = _trade_table(["p:known:yes", "unknown:x:y"], ts)
        builder = _make_builder(tmp_path, master, trade_table=table)
        config = dataset_mod.DatasetConfig(
            name="universe_filter",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        manifest = builder.build(config)
        gold_path = (
            builder_io.dataset_directory(tmp_path / "gold" / "datasets", manifest.dataset_id)
            / "trades.parquet"
        )
        result = pq.read_table(gold_path)
        ids = result.column("instrument_id").to_pylist()
        assert "unknown:x:y" not in ids

    def test_venue_filtered_build_scopes_universe_and_manifest(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "known", ["yes"]))
        master.register_market(_make_market("k", "known", ["yes"]))
        table = _trade_table(
            ["p:known:yes", "k:known:yes"],
            [_BASE + timedelta(hours=1), _BASE + timedelta(hours=2)],
        )
        builder = _make_builder(tmp_path, master, trade_table=table)
        config = dataset_mod.DatasetConfig(
            name="venue_scoped_dataset",
            start=_BASE,
            end=_END,
            venues=["p"],
            require_quality_pass=False,
        )

        manifest = builder.build(config)
        dataset = builder.load(manifest.dataset_id)

        assert manifest.instrument_count == 1
        assert dataset.instruments() == ["p:known:yes"]
        assert dataset.universe_at(_BASE) == ["p:known:yes"]

        gold_path = (
            builder_io.dataset_directory(tmp_path / "gold" / "datasets", manifest.dataset_id)
            / "trades.parquet"
        )
        result = pq.read_table(gold_path)
        assert result.column("instrument_id").to_pylist() == ["p:known:yes"]

    def test_quality_gate_raises_on_failure(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        builder = _make_builder(tmp_path, master)
        # Manually inject a quality violation into mock validator
        mock_report = MagicMock()
        mock_report.passed = False
        builder._quality_validator.validate_partition.return_value = mock_report  # type: ignore[attr-defined]

        config = dataset_mod.DatasetConfig(
            name="quality_gate",
            start=_BASE,
            end=_END,
            require_quality_pass=True,
            venues=["polymarket"],
        )
        with pytest.raises(builder_mod.DatasetBuildError):
            builder.build(config)

    def test_quality_gate_checks_discovered_venues_when_venues_are_unspecified(
        self, tmp_path: Path
    ) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        builder = _make_builder(tmp_path, master)

        mock_report = MagicMock()
        mock_report.passed = False
        builder._quality_validator.validate_partition.return_value = mock_report  # type: ignore[attr-defined]

        config = dataset_mod.DatasetConfig(
            name="quality_discovered_venues",
            start=_BASE,
            end=_END,
            event_types=["trades"],
            require_quality_pass=True,
        )
        with pytest.raises(builder_mod.DatasetBuildError):
            builder.build(config)

        assert builder._quality_validator.validate_partition.called  # type: ignore[attr-defined]

    def test_gap_check_raises_on_gaps(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))

        mock_reader = MagicMock(spec=reader_mod.ParquetEventReader)
        mock_reader.read_trades.return_value = pa.table({})
        mock_reader.read_ohlcv.return_value = pa.table({})
        mock_validator = MagicMock(spec=pv_mod.PartitionValidator)
        mock_gap = MagicMock(spec=gap_mod.GapDetector)

        # Inject a fake gap
        fake_gap = gap_mod.TimeGap(
            venue="p",
            outcome_id="p:m1:yes",
            gap_start=_BASE,
            gap_end=_BASE + timedelta(hours=6),
            duration_seconds=21600.0,
            event_type="trades",
        )
        mock_gap.detect_trade_gaps.return_value = [fake_gap]

        mgr = universe_mod.UniverseManager(master)
        bad_builder = builder_mod.DatasetBuilder(
            reader=mock_reader,
            universe_mgr=mgr,
            quality_validator=mock_validator,
            gap_detector=mock_gap,
            storage_root=tmp_path,
        )
        config = dataset_mod.DatasetConfig(
            name="gap_test",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
            require_gap_free=True,
        )
        with pytest.raises(builder_mod.DatasetBuildError, match="Gap check failed"):
            bad_builder.build(config)

    def test_book_gap_check_raises_on_gaps(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))

        mock_reader = MagicMock(spec=reader_mod.ParquetEventReader)
        mock_reader.read_trades.return_value = pa.table({})
        mock_reader.read_books.return_value = pa.table({})
        mock_reader.read_ohlcv.return_value = pa.table({})
        mock_validator = MagicMock(spec=pv_mod.PartitionValidator)
        mock_gap = MagicMock(spec=gap_mod.GapDetector)
        mock_gap.detect_trade_gaps.return_value = []
        mock_gap.detect_book_gaps.return_value = [
            gap_mod.TimeGap(
                venue="p",
                outcome_id="p:m1:yes",
                gap_start=_BASE,
                gap_end=_BASE + timedelta(hours=6),
                duration_seconds=21600.0,
                event_type="book",
            )
        ]

        bad_builder = builder_mod.DatasetBuilder(
            reader=mock_reader,
            universe_mgr=universe_mod.UniverseManager(master),
            quality_validator=mock_validator,
            gap_detector=mock_gap,
            storage_root=tmp_path,
        )
        config = dataset_mod.DatasetConfig(
            name="book_gap_test",
            start=_BASE,
            end=_END,
            event_types=["books"],
            require_quality_pass=False,
            require_gap_free=True,
        )
        with pytest.raises(builder_mod.DatasetBuildError, match="Gap check failed"):
            bad_builder.build(config)

    def test_gap_check_uses_observed_ohlcv_resolutions(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))

        mock_reader = MagicMock(spec=reader_mod.ParquetEventReader)
        mock_reader.read_trades.return_value = pa.table({})
        mock_reader.read_ohlcv.return_value = pa.table(
            {
                "instrument_id": ["p:m1:yes", "p:m1:yes"],
                "resolution": ["1h", "1d"],
            }
        )
        mock_validator = MagicMock(spec=pv_mod.PartitionValidator)
        mock_gap = MagicMock(spec=gap_mod.GapDetector)
        mock_gap.detect_trade_gaps.return_value = []
        mock_gap.detect_book_gaps.return_value = []
        mock_gap.detect_ohlcv_gaps.return_value = []

        builder = builder_mod.DatasetBuilder(
            reader=mock_reader,
            universe_mgr=universe_mod.UniverseManager(master),
            quality_validator=mock_validator,
            gap_detector=mock_gap,
            storage_root=tmp_path,
        )
        config = dataset_mod.DatasetConfig(
            name="ohlcv_gap_scan",
            start=_BASE,
            end=_END,
            event_types=["ohlcv"],
            require_quality_pass=False,
            require_gap_free=True,
        )
        builder.build(config)

        expected_calls = {
            ("p", "p:m1:yes", "1h"),
            ("p", "p:m1:yes", "1d"),
        }
        observed_calls = {
            (
                call.args[0],
                call.args[1],
                call.kwargs["resolution"],
            )
            for call in mock_gap.detect_ohlcv_gaps.call_args_list
        }
        assert observed_calls == expected_calls

    def test_small_ohlcv_gap_within_threshold_does_not_raise(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))

        mock_reader = MagicMock(spec=reader_mod.ParquetEventReader)
        mock_reader.read_trades.return_value = pa.table({})
        mock_reader.read_ohlcv.return_value = pa.table(
            {
                "instrument_id": ["p:m1:yes"],
                "resolution": ["1h"],
            }
        )
        mock_validator = MagicMock(spec=pv_mod.PartitionValidator)
        mock_gap = MagicMock(spec=gap_mod.GapDetector)
        mock_gap.detect_trade_gaps.return_value = []
        mock_gap.detect_book_gaps.return_value = []
        mock_gap.detect_ohlcv_gaps.return_value = [
            gap_mod.TimeGap(
                venue="p",
                outcome_id="p:m1:yes",
                gap_start=_BASE,
                gap_end=_BASE + timedelta(hours=1),
                duration_seconds=3600.0,
                event_type="ohlcv",
            )
        ]

        builder = builder_mod.DatasetBuilder(
            reader=mock_reader,
            universe_mgr=universe_mod.UniverseManager(master),
            quality_validator=mock_validator,
            gap_detector=mock_gap,
            storage_root=tmp_path,
        )
        config = dataset_mod.DatasetConfig(
            name="ohlcv_gap_threshold",
            start=_BASE,
            end=_END,
            event_types=["ohlcv"],
            require_quality_pass=False,
            require_gap_free=True,
            max_gap_hours=24.0,
        )
        builder.build(config)

    def test_distinct_dataset_ids_preserve_prior_snapshot_contents(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        ts = [_BASE + timedelta(hours=1)]
        builder = _make_builder(
            tmp_path,
            master,
            trade_table=_trade_table(["p:m1:yes"], ts),
        )
        builder._reader.read_ohlcv.return_value = _ohlcv_table(["p:m1:yes"], ts)  # type: ignore[attr-defined]

        initial_config = dataset_mod.DatasetConfig(
            name="stale_cleanup",
            start=_BASE,
            end=_END,
            event_types=["trades", "ohlcv"],
            require_quality_pass=False,
        )
        initial_manifest = builder.build(initial_config)

        initial_dir = builder_io.dataset_directory(
            tmp_path / "gold" / "datasets",
            initial_manifest.dataset_id,
        )
        assert (initial_dir / "ohlcv.parquet").exists()

        rebuild_config = dataset_mod.DatasetConfig(
            name="stale_cleanup",
            start=_BASE,
            end=_END,
            event_types=["trades"],
            require_quality_pass=False,
        )
        rebuilt_manifest = builder.build(rebuild_config)
        rebuilt_dir = builder_io.dataset_directory(
            tmp_path / "gold" / "datasets",
            rebuilt_manifest.dataset_id,
        )

        assert initial_manifest.dataset_id != rebuilt_manifest.dataset_id
        assert (initial_dir / "ohlcv.parquet").exists()
        assert (rebuilt_dir / "trades.parquet").exists()
        assert not (rebuilt_dir / "ohlcv.parquet").exists()

    def test_same_config_cannot_overwrite_existing_snapshot(self, tmp_path: Path) -> None:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        ts = [_BASE + timedelta(hours=1)]
        builder = _make_builder(
            tmp_path,
            master,
            trade_table=_trade_table(["p:m1:yes"], ts),
        )
        config = dataset_mod.DatasetConfig(
            name="immutable_snapshot",
            start=_BASE,
            end=_END,
            require_quality_pass=False,
        )
        builder.build(config)
        with pytest.raises(builder_mod.DatasetBuildError, match="immutable"):
            builder.build(config)


# ---------------------------------------------------------------------------
# DatasetBuilder.load / list_datasets
# ---------------------------------------------------------------------------


class TestDatasetBuilderLoadList:
    def _build_simple(self, tmp_path: Path, name: str) -> dataset_mod.DatasetManifest:
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        builder = _make_builder(tmp_path, master)
        config = dataset_mod.DatasetConfig(
            name=name, start=_BASE, end=_END, require_quality_pass=False
        )
        return builder.build(config)

    def test_load_by_name(self, tmp_path: Path) -> None:
        manifest = self._build_simple(tmp_path, "my_ds")
        builder = _make_builder(tmp_path, master_mod.MarketMaster())
        loaded = builder.load("my_ds")
        assert loaded.manifest.dataset_id == manifest.dataset_id

    def test_load_by_dataset_id(self, tmp_path: Path) -> None:
        manifest = self._build_simple(tmp_path, "id_ds")
        builder = _make_builder(tmp_path, master_mod.MarketMaster())
        loaded = builder.load(manifest.dataset_id)
        assert loaded.manifest.config.name == "id_ds"

    def test_load_by_name_raises_when_multiple_datasets_share_name(self, tmp_path: Path) -> None:
        self._build_simple(tmp_path, "shared_name")
        master = master_mod.MarketMaster()
        master.register_market(_make_market("p", "m1", ["yes"]))
        builder = _make_builder(tmp_path, master)
        builder.build(
            dataset_mod.DatasetConfig(
                name="shared_name",
                start=_BASE,
                end=_END,
                event_types=["trades"],
                require_quality_pass=False,
            )
        )
        builder = _make_builder(tmp_path, master_mod.MarketMaster())
        with pytest.raises(ValueError, match="ambiguous"):
            builder.load("shared_name")

    def test_load_unknown_raises_key_error(self, tmp_path: Path) -> None:
        builder = _make_builder(tmp_path, master_mod.MarketMaster())
        with pytest.raises(KeyError):
            builder.load("nonexistent_ds")

    def test_list_datasets_empty(self, tmp_path: Path) -> None:
        builder = _make_builder(tmp_path, master_mod.MarketMaster())
        assert builder.list_datasets() == []

    def test_list_datasets_returns_all(self, tmp_path: Path) -> None:
        for name in ("ds_a", "ds_b", "ds_c"):
            self._build_simple(tmp_path, name)
        builder = _make_builder(tmp_path, master_mod.MarketMaster())
        manifests = builder.list_datasets()
        names = {m.config.name for m in manifests}
        assert names == {"ds_a", "ds_b", "ds_c"}
