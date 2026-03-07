"""Unit tests for GoldDataset."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import alpha_core.research.dataset as dataset_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_END = _BASE + timedelta(days=30)

_TRADE_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string()),
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("price", pa.float64()),
        pa.field("size", pa.float64()),
    ]
)

_OHLCV_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string()),
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("open", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("resolution", pa.string()),
    ]
)

_UNIVERSE_SCHEMA = pa.schema(
    [
        pa.field("as_of", pa.timestamp("us", tz="UTC")),
        pa.field("instrument_id", pa.string()),
        pa.field("market_id", pa.string()),
        pa.field("venue", pa.string()),
    ]
)


def _write_dataset(tmp_path: Path) -> tuple[dataset_mod.DatasetManifest, Path]:
    dataset_dir = tmp_path / "gold" / "datasets" / "test_ds"
    dataset_dir.mkdir(parents=True)

    # Trades
    trade_table = pa.table(
        {
            "instrument_id": ["a:m:yes", "a:m:no", "b:x:yes"],
            "ts_event": [_BASE, _BASE + timedelta(hours=1), _BASE + timedelta(hours=2)],
            "price": [0.6, 0.4, 0.7],
            "size": [100.0, 50.0, 200.0],
        },
        schema=_TRADE_SCHEMA,
    )
    pq.write_table(trade_table, dataset_dir / "trades.parquet")

    # OHLCV
    ohlcv_table = pa.table(
        {
            "instrument_id": ["a:m:yes", "a:m:yes"],
            "ts_event": [_BASE, _BASE + timedelta(days=1)],
            "open": [0.59, 0.62],
            "close": [0.61, 0.63],
            "resolution": ["1d", "1d"],
        },
        schema=_OHLCV_SCHEMA,
    )
    pq.write_table(ohlcv_table, dataset_dir / "ohlcv.parquet")

    # Universe
    universe_table = pa.table(
        {
            "as_of": [_BASE, _BASE, _BASE + timedelta(days=1)],
            "instrument_id": ["a:m:yes", "a:m:no", "b:x:yes"],
            "market_id": ["a:m", "a:m", "b:x"],
            "venue": ["a", "a", "b"],
        },
        schema=_UNIVERSE_SCHEMA,
    )
    pq.write_table(universe_table, dataset_dir / "universe.parquet")

    config = dataset_mod.DatasetConfig(name="test_ds", start=_BASE, end=_END)
    manifest = dataset_mod.DatasetManifest(
        run_id="dataset_run_abc123",
        dataset_id="abc123",
        config=config,
        built_at=datetime.now(tz=UTC),
        row_counts={"trades": 3, "ohlcv": 2},
        instrument_count=3,
        date_range=(_BASE, _END),
        quality_summary={},
        schema_version=1,
    )
    (dataset_dir / "_meta.json").write_text(manifest.model_dump_json())
    return manifest, dataset_dir


class TestGoldDataset:
    def test_trades_returns_all_rows(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        table = ds.trades()
        assert table.num_rows == 3

    def test_trades_filter_by_instrument(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        table = ds.trades(instrument_id="a:m:yes")
        assert table.num_rows == 1
        assert table.column("instrument_id").to_pylist() == ["a:m:yes"]

    def test_trades_instrument_not_found_returns_empty(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        table = ds.trades(instrument_id="NONEXISTENT")
        assert table.num_rows == 0

    def test_ohlcv_filter_by_resolution(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        table = ds.ohlcv(resolution="1d")
        assert table.num_rows == 2
        table_wrong = ds.ohlcv(resolution="1h")
        assert table_wrong.num_rows == 0

    def test_books_missing_file_returns_empty(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        table = ds.books()
        assert table.num_rows == 0

    def test_universe_at_before_late_instrument(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        instruments = ds.universe_at(_BASE)
        assert instruments == ["a:m:yes", "a:m:no"]

    def test_universe_at_after_late_instrument(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        instruments = ds.universe_at(_BASE + timedelta(days=1))
        assert instruments == ["b:x:yes"]

    def test_instruments_returns_unique_ids(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        instruments = ds.instruments()
        assert len(instruments) == len(set(instruments))
        assert "a:m:yes" in instruments
        assert "b:x:yes" in instruments

    def test_date_range_returns_manifest_range(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        start, end = ds.date_range()
        assert start == _BASE
        assert end == _END

    def test_to_pandas_returns_dataframe(self, tmp_path: Path) -> None:
        import pandas as pd

        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        df = ds.to_pandas("trades")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3

    def test_manifest_property(self, tmp_path: Path) -> None:
        manifest, dataset_dir = _write_dataset(tmp_path)
        ds = dataset_mod.GoldDataset(manifest=manifest, dataset_dir=dataset_dir)
        assert ds.manifest.dataset_id == "abc123"
