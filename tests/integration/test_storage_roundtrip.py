"""Integration tests for Parquet write/read and DuckDB analytics round-trip."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

if os.getenv("ALPHA_REQUIRE_DUCKDB") == "1":
    import duckdb  # type: ignore[import-not-found,unused-ignore]  # noqa: F401
else:
    pytest.importorskip("duckdb")

import alpha_core.events.models as event_models
import alpha_core.storage.duckdb_layer as duckdb_layer
import alpha_core.storage.parquet_reader as parquet_reader
import alpha_core.storage.parquet_writer as parquet_writer
import alpha_core.utils.ids as ids_utils


def _make_trade(*, trade_index: int, ts_event: datetime) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-x:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=500),
        "schema_version": 1,
        "price": Decimal("0.55") + Decimal(trade_index) / Decimal("1000"),
        "size": Decimal("5"),
        "side": event_models.TradeSide.BUY,
        "trade_id": f"trade-{trade_index}",
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


def _make_book(*, ts_event: datetime) -> event_models.CanonicalBookSnapshot:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-x:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.BOOK_SNAPSHOT,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=500),
        "schema_version": 1,
        "bids": [{"price": "0.54", "size": "10"}],
        "asks": [{"price": "0.56", "size": "8"}],
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalBookSnapshot.model_validate(payload)


def _make_ohlcv(
    *,
    ts_event: datetime,
    resolution: str = "1h",
) -> event_models.CanonicalOHLCV:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-x:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.OHLCV,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=500),
        "schema_version": 1,
        "open": Decimal("0.50"),
        "high": Decimal("0.58"),
        "low": Decimal("0.49"),
        "close": Decimal("0.55"),
        "volume": Decimal("200"),
        "resolution": resolution,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalOHLCV.model_validate(payload)


def test_storage_roundtrip_parquet_reader_and_duckdb(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    ts_base = datetime(2026, 2, 28, 9, 0, tzinfo=UTC)
    trades = [
        _make_trade(trade_index=index, ts_event=ts_base + timedelta(seconds=index))
        for index in range(6)
    ]
    writer.write_trades(trades)

    parquet_table = reader.read_trades(venue="kalshi", start=None, end=None)
    assert parquet_table.num_rows == 6

    analytics.register_silver("trades")
    duck_table = analytics.query(
        "SELECT trade_id, ts_event, ts_record FROM silver_trades ORDER BY trade_id"
    )

    assert duck_table.num_rows == 6
    assert duck_table.column("trade_id").to_pylist() == [f"trade-{index}" for index in range(6)]

    ts_events = duck_table.column("ts_event").to_pylist()
    ts_records = duck_table.column("ts_record").to_pylist()
    assert all(
        ts_event <= ts_record for ts_event, ts_record in zip(ts_events, ts_records, strict=True)
    )


def test_storage_roundtrip_empty_dataset_no_crash(tmp_path: Path) -> None:
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    analytics.register_silver("trades")
    table = analytics.query("SELECT COUNT(*) AS row_count FROM silver_trades")

    assert table.num_rows == 1
    assert table.column("row_count").to_pylist() == [0]


def test_duckdb_registers_books_and_ohlcv_views(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    ts_base = datetime(2026, 2, 28, 11, 0, tzinfo=UTC)
    writer.write_books([_make_book(ts_event=ts_base), _make_book(ts_event=ts_base)])
    writer.write_ohlcv([_make_ohlcv(ts_event=ts_base), _make_ohlcv(ts_event=ts_base)])

    analytics.register_silver("books")
    analytics.register_silver("ohlcv")

    books_count = analytics.query("SELECT COUNT(*) AS row_count FROM silver_books")
    ohlcv_count = analytics.query("SELECT COUNT(*) AS row_count FROM silver_ohlcv")

    assert books_count.column("row_count").to_pylist() == [2]
    assert ohlcv_count.column("row_count").to_pylist() == [2]


def test_storage_roundtrip_books_and_ohlcv_reader_paths(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)

    ts_base = datetime(2026, 2, 28, 11, 0, tzinfo=UTC)
    writer.write_books(
        [
            _make_book(ts_event=ts_base),
            _make_book(ts_event=ts_base + timedelta(hours=1)),
        ]
    )
    writer.write_ohlcv(
        [
            _make_ohlcv(ts_event=ts_base),
            _make_ohlcv(ts_event=ts_base + timedelta(days=1)),
        ]
    )

    books = reader.read_books(
        venue="kalshi",
        start=ts_base - timedelta(minutes=1),
        end=ts_base + timedelta(minutes=1),
    )
    candles = reader.read_ohlcv(
        venue="kalshi",
        resolution="1h",
        start=ts_base - timedelta(minutes=1),
        end=ts_base + timedelta(days=2),
    )

    assert books.num_rows == 1
    assert candles.num_rows == 2


def test_storage_roundtrip_books_duckdb_preserves_bitemporal_order(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    ts_base = datetime(2026, 2, 28, 12, 0, tzinfo=UTC)
    writer.write_books(
        [
            _make_book(ts_event=ts_base),
            _make_book(ts_event=ts_base + timedelta(minutes=1)),
        ]
    )

    analytics.register_silver("books")
    table = analytics.query("SELECT ts_event, ts_record FROM silver_books ORDER BY ts_event")

    assert table.num_rows == 2
    ts_events = table.column("ts_event").to_pylist()
    ts_records = table.column("ts_record").to_pylist()
    assert all(
        ts_event <= ts_record for ts_event, ts_record in zip(ts_events, ts_records, strict=True)
    )


def test_storage_roundtrip_ohlcv_duckdb_filters_resolution(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    ts_base = datetime(2026, 2, 28, 12, 0, tzinfo=UTC)
    writer.write_ohlcv(
        [
            _make_ohlcv(ts_event=ts_base, resolution="1h"),
            _make_ohlcv(ts_event=ts_base + timedelta(hours=1), resolution="1h"),
            _make_ohlcv(ts_event=ts_base, resolution="5m"),
        ]
    )

    analytics.register_silver("ohlcv")
    table = analytics.query(
        "SELECT resolution, COUNT(*) AS row_count "
        "FROM silver_ohlcv GROUP BY resolution ORDER BY resolution"
    )

    assert table.column("resolution").to_pylist() == ["1h", "5m"]
    assert table.column("row_count").to_pylist() == [2, 1]


def test_duckdb_query_rejects_non_read_only_sql(tmp_path: Path) -> None:
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    with pytest.raises(ValueError, match="Only read-only queries are allowed"):
        analytics.query("CREATE TABLE forbidden_table (id INTEGER)")


def test_duckdb_query_rejects_unregistered_relations(tmp_path: Path) -> None:
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    with pytest.raises(ValueError, match="registered silver views"):
        analytics.query("SELECT * FROM non_registered_source")


def test_duckdb_query_rejects_table_functions(tmp_path: Path) -> None:
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    with pytest.raises(ValueError, match="Table functions are not allowed"):
        analytics.query("SELECT * FROM read_parquet('/tmp/arbitrary.parquet')")
