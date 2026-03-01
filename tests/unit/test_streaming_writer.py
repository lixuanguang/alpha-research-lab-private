"""Unit tests for buffered streaming Parquet writer."""

from __future__ import annotations

import atexit
import gc
import time
import weakref
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import alpha_core.events.models as event_models
import alpha_core.storage.parquet_writer as parquet_writer
import alpha_core.storage.streaming_writer as streaming_writer
import alpha_core.utils.ids as ids_utils


def _trade(index: int) -> event_models.CanonicalTrade:
    ts_event = datetime(2026, 3, 1, 10, 0, tzinfo=UTC) + timedelta(seconds=index)
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=100),
        "schema_version": 1,
        "price": Decimal("0.51"),
        "size": Decimal("2"),
        "side": event_models.TradeSide.BUY,
        "trade_id": f"trade-{index}",
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


def _book(index: int) -> event_models.CanonicalBookSnapshot:
    ts_event = datetime(2026, 3, 1, 10, 0, tzinfo=UTC) + timedelta(seconds=index)
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.BOOK_SNAPSHOT,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=100),
        "schema_version": 1,
        "bids": [{"price": "0.50", "size": "10"}],
        "asks": [{"price": "0.52", "size": "8"}],
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalBookSnapshot.model_validate(payload)


def test_flush_returns_empty_mapping_for_empty_buffer(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(parquet_writer.ParquetEventWriter(tmp_path))

    assert writer.flush() == {}


def test_buffer_flushes_when_size_threshold_is_hit(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(
        parquet_writer.ParquetEventWriter(tmp_path),
        max_buffer_size=2,
        max_buffer_age_seconds=60.0,
    )

    writer.append(_trade(1))
    writer.append(_trade(2))

    trade_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert trade_files


def test_buffer_flushes_when_age_threshold_is_hit(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(
        parquet_writer.ParquetEventWriter(tmp_path),
        max_buffer_size=10,
        max_buffer_age_seconds=0.01,
    )

    writer.append(_trade(1))
    time.sleep(0.02)
    writer.append(_trade(2))

    trade_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert trade_files


def test_buffer_flushes_on_age_threshold_without_additional_appends(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(
        parquet_writer.ParquetEventWriter(tmp_path),
        max_buffer_size=100,
        max_buffer_age_seconds=0.02,
    )

    writer.append(_trade(1))
    time.sleep(0.05)

    trade_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert trade_files
    assert writer.flush() == {}


def test_first_append_does_not_flush_due_to_idle_time_since_init(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(
        parquet_writer.ParquetEventWriter(tmp_path),
        max_buffer_size=2,
        max_buffer_age_seconds=0.01,
    )

    time.sleep(0.02)
    writer.append(_trade(1))

    trade_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert trade_files == []

    writer.append(_trade(2))
    trade_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert trade_files


def test_close_flushes_remaining_events(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(
        parquet_writer.ParquetEventWriter(tmp_path),
        max_buffer_size=100,
        max_buffer_age_seconds=60.0,
    )

    writer.append(_book(1))
    writer.close()

    book_files = sorted((tmp_path / "silver" / "books").rglob("*.parquet"))
    assert book_files


def test_flush_failure_retains_buffer_for_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_writer = parquet_writer.ParquetEventWriter(tmp_path)
    writer = streaming_writer.StreamingParquetWriter(
        base_writer,
        max_buffer_size=10,
        max_buffer_age_seconds=60.0,
    )
    writer.append(_trade(1))
    writer.append(_trade(2))

    original_write_trades = base_writer.write_trades

    def _raise_once(_: list[event_models.CanonicalTrade]) -> Path:
        raise RuntimeError("disk full")

    monkeypatch.setattr(base_writer, "write_trades", _raise_once)
    with pytest.raises(RuntimeError, match="disk full"):
        writer.flush()

    monkeypatch.setattr(base_writer, "write_trades", original_write_trades)
    output = writer.flush()
    assert output["trades"].name == "trades"
    trade_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert trade_files


def test_background_flush_error_is_surface_on_next_append(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_writer = parquet_writer.ParquetEventWriter(tmp_path)
    writer = streaming_writer.StreamingParquetWriter(
        base_writer,
        max_buffer_size=100,
        max_buffer_age_seconds=0.01,
    )
    writer.append(_trade(1))

    def _always_raise(_: list[event_models.CanonicalTrade]) -> Path:
        raise RuntimeError("io error")

    monkeypatch.setattr(base_writer, "write_trades", _always_raise)
    time.sleep(0.03)

    with pytest.raises(RuntimeError, match="Background flush failed"):
        writer.append(_trade(2))


def test_background_flush_retries_without_new_append_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_writer = parquet_writer.ParquetEventWriter(tmp_path)
    writer = streaming_writer.StreamingParquetWriter(
        base_writer,
        max_buffer_size=100,
        max_buffer_age_seconds=0.01,
    )
    writer.append(_trade(1))

    original_write_trades = base_writer.write_trades
    calls = {"count": 0}

    def _fail_once_then_succeed(events: list[event_models.CanonicalTrade]) -> Path:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient io")
        return original_write_trades(events)

    monkeypatch.setattr(base_writer, "write_trades", _fail_once_then_succeed)
    time.sleep(0.06)

    trade_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert trade_files
    assert calls["count"] >= 2
    writer.append(_trade(2))


def test_atexit_hook_does_not_keep_writer_alive(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(parquet_writer.ParquetEventWriter(tmp_path))
    callback = writer._atexit_callback
    writer_ref = weakref.ref(writer)
    del writer
    gc.collect()

    assert writer_ref() is None
    if callback is not None:
        atexit.unregister(callback)


def test_append_after_close_raises(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(parquet_writer.ParquetEventWriter(tmp_path))
    writer.close()

    with pytest.raises(RuntimeError, match="closed"):
        writer.append(_trade(1))


def test_append_rejects_unsupported_event_types(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(parquet_writer.ParquetEventWriter(tmp_path))
    now = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    metadata_event = event_models.CanonicalMetadataUpdate.model_validate(
        {
            "instrument_id": "kalshi:market-a",
            "venue_id": "kalshi",
            "ts_event": now,
            "ts_record": now,
            "fields_changed": {"status": "active"},
        }
    )

    with pytest.raises(TypeError, match="Unsupported event type"):
        writer.append(metadata_event)


@pytest.mark.perf
def test_streaming_writer_flush_meets_d2_latency_target(tmp_path: Path) -> None:
    writer = streaming_writer.StreamingParquetWriter(
        parquet_writer.ParquetEventWriter(tmp_path),
        max_buffer_size=10_000,
        max_buffer_age_seconds=60.0,
    )
    for index in range(200):
        writer.append(_trade(index))

    start = time.perf_counter()
    output = writer.flush()
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert output["trades"].name == "trades"
    assert elapsed_ms < 200
