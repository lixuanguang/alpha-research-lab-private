"""Integration tests for PartitionValidator — write silver data then validate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import alpha_core.events.models as event_models
import alpha_core.quality.partition_validator as quality_partition_validator
import alpha_core.quality.suites.book_quality as quality_book
import alpha_core.quality.suites.ohlcv_quality as quality_ohlcv
import alpha_core.quality.suites.trade_quality as quality_trade
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.storage.parquet_writer as parquet_writer_mod
import alpha_core.utils.ids as ids_utils

_DATE = "2026-03-01"
_TS_BASE = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)

_StoragePair = tuple[parquet_writer_mod.ParquetEventWriter, parquet_reader_mod.ParquetEventReader]


def _make_trade(i: int) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-1:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": _TS_BASE + timedelta(seconds=i * 60),
        "ts_record": _TS_BASE + timedelta(seconds=i * 60 + 1),
        "schema_version": 1,
        "price": Decimal("0.50"),
        "size": Decimal("1"),
        "side": event_models.TradeSide.BUY,
        "trade_id": f"t-{i}",
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


def _make_book(i: int) -> event_models.CanonicalBookSnapshot:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-1:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.BOOK_SNAPSHOT,
        "ts_event": _TS_BASE + timedelta(seconds=i * 60),
        "ts_record": _TS_BASE + timedelta(seconds=i * 60 + 1),
        "schema_version": 1,
        "bids": [{"price": "0.49", "size": "10"}],
        "asks": [{"price": "0.51", "size": "8"}],
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalBookSnapshot.model_validate(payload)


def _make_ohlcv(i: int) -> event_models.CanonicalOHLCV:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-1:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.OHLCV,
        "ts_event": _TS_BASE + timedelta(hours=i),
        "ts_record": _TS_BASE + timedelta(hours=i, seconds=1),
        "schema_version": 1,
        "open": Decimal("0.50"),
        "high": Decimal("0.58"),
        "low": Decimal("0.44"),
        "close": Decimal("0.55"),
        "volume": Decimal("200"),
        "resolution": "1h",
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalOHLCV.model_validate(payload)


@pytest.fixture()
def storage(
    tmp_path: Path,
) -> tuple[parquet_writer_mod.ParquetEventWriter, parquet_reader_mod.ParquetEventReader]:
    writer = parquet_writer_mod.ParquetEventWriter(tmp_path)
    reader = parquet_reader_mod.ParquetEventReader(tmp_path)
    return writer, reader


def _make_validator(
    reader: parquet_reader_mod.ParquetEventReader,
) -> quality_partition_validator.PartitionValidator:
    return quality_partition_validator.PartitionValidator(
        reader=reader,
        suites={
            "trades": quality_trade.TRADE_SUITE,
            "books": quality_book.BOOK_SUITE,
            "ohlcv": quality_ohlcv.OHLCV_SUITE,
        },
    )


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------


def test_trade_partition_passes_validation(storage: _StoragePair) -> None:
    writer, reader = storage
    trades = [_make_trade(i) for i in range(10)]
    writer.write_trades(trades)

    validator = _make_validator(reader)
    report = validator.validate_partition("trades", "kalshi", _DATE)
    assert report.passed is True
    assert report.row_count == 10
    assert report.partition_info["venue"] == "kalshi"


def test_trade_partition_fails_on_duplicate_trade_ids(storage: _StoragePair) -> None:
    """Write trades, then validate a synthetic table with duplicates."""
    _, _reader = storage
    # Use the TRADE_SUITE directly with a bad table (no writer involvement)
    from datetime import timedelta

    import pyarrow as pa

    n = 3
    now = datetime.now(UTC)
    ts_type = pa.timestamp("us", tz="UTC")
    tbl = pa.table(
        {
            "event_id": pa.array(["e1", "e2", "e3"]),
            "instrument_id": pa.array(["kalshi:m1:yes"] * n),
            "price": pa.array([0.5] * n, type=pa.float64()),
            "size": pa.array([1.0] * n, type=pa.float64()),
            "trade_id": pa.array(["dup", "dup", "dup"]),  # duplicates
            "ts_event": pa.array([now - timedelta(minutes=5)] * n, type=ts_type),
            "ts_record": pa.array([now - timedelta(minutes=4)] * n, type=ts_type),
        }
    )
    report = quality_trade.TRADE_SUITE.validate(
        tbl,
        partition_info={"venue": "kalshi", "date": _DATE},
    )
    assert report.passed is False


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------


def test_book_partition_passes_validation(storage: _StoragePair) -> None:
    writer, reader = storage
    books = [_make_book(i) for i in range(5)]
    writer.write_books(books)

    validator = _make_validator(reader)
    report = validator.validate_partition("books", "kalshi", _DATE)
    assert report.passed is True


# ---------------------------------------------------------------------------
# OHLCV
# ---------------------------------------------------------------------------


def test_ohlcv_partition_passes_validation(storage: _StoragePair) -> None:
    writer, reader = storage
    candles = [_make_ohlcv(i) for i in range(3)]
    writer.write_ohlcv(candles)

    validator = _make_validator(reader)
    report = validator.validate_partition("ohlcv", "kalshi", _DATE, resolution="1h")
    assert report.passed is True
    assert report.row_count == 3


# ---------------------------------------------------------------------------
# validate_all_recent
# ---------------------------------------------------------------------------


def test_validate_all_recent(storage: _StoragePair) -> None:
    writer, reader = storage
    writer.write_trades([_make_trade(i) for i in range(3)])
    writer.write_ohlcv([_make_ohlcv(i) for i in range(2)])

    validator = _make_validator(reader)
    since = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    reports = validator.validate_all_recent(since)
    event_types = {r.suite_name for r in reports}
    assert "silver_trades" in event_types
    assert "silver_ohlcv" in event_types


def test_validate_partition_unknown_event_type_raises(storage: _StoragePair) -> None:
    _, reader = storage
    validator = _make_validator(reader)
    with pytest.raises(KeyError, match="unknown_type"):
        validator.validate_partition("unknown_type", "kalshi", _DATE)


def test_partition_validator_defaults_include_microstructure_for_books_and_deltas(
    tmp_path: Path,
) -> None:
    writer = parquet_writer_mod.ParquetEventWriter(tmp_path)
    reader = parquet_reader_mod.ParquetEventReader(tmp_path)
    writer.write_books([_make_book(0), _make_book(1)])

    delta_payload = {
        "instrument_id": "kalshi:market-1:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.BOOK_DELTA,
        "ts_event": _TS_BASE,
        "ts_record": _TS_BASE + timedelta(milliseconds=5),
        "schema_version": 1,
        "side": "bid",
        "price": Decimal("0.49"),
        "delta_size": Decimal("1"),
        "reason": "add",
        "is_reconstructed": True,
    }
    writer.write_book_deltas([event_models.CanonicalBookDelta.model_validate(delta_payload)])

    validator = quality_partition_validator.PartitionValidator.from_defaults(reader)
    book_report = validator.validate_partition("books", "kalshi", _DATE)
    delta_report = validator.validate_partition("book_deltas", "kalshi", _DATE)

    assert book_report.suite_name == "silver_books_with_microstructure"
    assert delta_report.suite_name == "silver_book_deltas_microstructure"
