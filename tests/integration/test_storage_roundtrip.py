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


# ---------------------------------------------------------------------------
# F6 Extension: book_deltas roundtrip
# ---------------------------------------------------------------------------


def _make_book_delta(
    *,
    delta_index: int,
    venue: str = "kalshi",
    ts_event: datetime,
    reason: str = "add",
    sequence_id: str | None = None,
    is_reconstructed: bool = False,
) -> event_models.CanonicalBookDelta:
    payload: dict[str, object] = {
        "instrument_id": f"{venue}:market-x:yes",
        "venue_id": venue,
        "event_type": event_models.EventType.BOOK_DELTA,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=5),
        "schema_version": 1,
        "side": "bid" if delta_index % 2 == 0 else "ask",
        "price": Decimal("0.50") + Decimal(delta_index % 10) / Decimal("100"),
        "delta_size": Decimal("3") + Decimal(delta_index % 4),
        "reason": reason,
        "sequence_id": sequence_id,
        "is_reconstructed": is_reconstructed,
    }
    exclude_fields = event_models.event_id_exclude_fields(event_models.EventType.BOOK_DELTA)
    payload["event_id"] = ids_utils.generate_event_id(
        {k: v for k, v in payload.items() if k not in exclude_fields and v is not None}
    )
    return event_models.CanonicalBookDelta.model_validate(payload)


def test_storage_roundtrip_book_deltas_parquet_reader_and_duckdb(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    ts_base = datetime(2026, 3, 3, 8, 0, tzinfo=UTC)
    deltas = [
        _make_book_delta(delta_index=i, ts_event=ts_base + timedelta(seconds=i)) for i in range(3)
    ]
    writer.write_book_deltas(deltas)

    table = reader.read_book_deltas(venue="kalshi")
    assert table.num_rows == 3
    assert set(table.column("reason").to_pylist()) == {"add"}

    analytics.register_silver("book_deltas")
    result = analytics.query("SELECT COUNT(*) AS n FROM silver_book_deltas")
    assert result.column("n").to_pylist() == [3]


def test_storage_roundtrip_book_deltas_empty_dataset_no_crash(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    writer.write_book_deltas([])

    table = reader.read_book_deltas()
    assert table.num_rows == 0

    analytics.register_silver("book_deltas")
    result = analytics.query("SELECT COUNT(*) AS n FROM silver_book_deltas")
    assert result.column("n").to_pylist() == [0]


def test_storage_roundtrip_book_deltas_is_reconstructed_flag_preserved(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)

    ts_base = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)
    native = _make_book_delta(delta_index=0, ts_event=ts_base)
    reconstructed = _make_book_delta(delta_index=1, ts_event=ts_base + timedelta(seconds=1))

    writer.write_book_deltas([native], is_reconstructed=False)
    writer.write_book_deltas([reconstructed], is_reconstructed=True)

    table = reader.read_book_deltas(venue="kalshi")
    flags = sorted(set(table.column("is_reconstructed").to_pylist()))
    assert flags == [False, True]


def test_storage_roundtrip_book_deltas_per_event_flag_respected(tmp_path: Path) -> None:
    """Per-event is_reconstructed on the model is persisted when the batch flag is False."""
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)

    ts_base = datetime(2026, 3, 3, 10, 0, tzinfo=UTC)
    native = _make_book_delta(delta_index=0, ts_event=ts_base)
    # is_reconstructed is set on the model itself, not via the batch kwarg
    reconstructed = _make_book_delta(
        delta_index=1, ts_event=ts_base + timedelta(seconds=1), is_reconstructed=True
    )

    writer.write_book_deltas([native, reconstructed])  # batch flag stays False

    table = reader.read_book_deltas(venue="kalshi")
    assert table.num_rows == 2
    flags = sorted(set(table.column("is_reconstructed").to_pylist()))
    assert flags == [False, True]


def test_storage_roundtrip_book_deltas_duckdb_filter_by_is_reconstructed(
    tmp_path: Path,
) -> None:
    """silver_book_deltas DuckDB view supports WHERE is_reconstructed filtering."""
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    ts_base = datetime(2026, 3, 3, 11, 0, tzinfo=UTC)
    native = _make_book_delta(delta_index=0, ts_event=ts_base)
    reconstructed = _make_book_delta(
        delta_index=1, ts_event=ts_base + timedelta(seconds=1), is_reconstructed=True
    )
    writer.write_book_deltas([native, reconstructed])

    analytics.register_silver("book_deltas")

    all_rows = analytics.query("SELECT COUNT(*) AS n FROM silver_book_deltas")
    assert all_rows.column("n").to_pylist() == [2]

    recon_rows = analytics.query(
        "SELECT COUNT(*) AS n FROM silver_book_deltas WHERE is_reconstructed = true"
    )
    assert recon_rows.column("n").to_pylist() == [1]

    native_rows = analytics.query(
        "SELECT COUNT(*) AS n FROM silver_book_deltas WHERE is_reconstructed = false"
    )
    assert native_rows.column("n").to_pylist() == [1]
