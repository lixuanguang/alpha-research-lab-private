"""Integration tests for StreamingPipeline."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import apps.data_collector.connectors.trade_stream as trade_stream_mod
import apps.data_collector.streaming_pipeline as streaming_pipeline_mod

import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.storage.streaming_writer as storage_streaming
import alpha_core.utils.ids as ids_utils

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _trade(trade_id: str, ts: datetime | None = None) -> event_models.CanonicalTrade:
    ts = ts or _NOW
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts,
        "ts_record": ts + timedelta(milliseconds=100),
        "schema_version": 1,
        "price": Decimal("0.51"),
        "size": Decimal("2"),
        "side": event_models.TradeSide.BUY,
        "trade_id": trade_id,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


class _FiniteAdapter:
    """Mock adapter that yields a fixed set of batches then stops the connector."""

    def __init__(self, batches: list[list[event_models.CanonicalTrade]]) -> None:
        self._batches = batches
        self.connector: trade_stream_mod.TradeStreamConnector | None = None

    def venue_name(self) -> str:
        return "kalshi"

    async def watch_trades(
        self, outcome_id: str
    ) -> AsyncIterator[list[event_models.CanonicalTrade]]:
        for batch in self._batches:
            yield batch
        # Signal the connector to stop after exhausting batches.
        if self.connector is not None:
            self.connector._stop_event.set()


class _BlockingAdapter:
    """Mock adapter that never emits data and blocks until cancelled."""

    def venue_name(self) -> str:
        return "kalshi"

    async def watch_trades(
        self, outcome_id: str
    ) -> AsyncIterator[list[event_models.CanonicalTrade]]:
        while True:
            await asyncio.sleep(60.0)
            yield []


class _FailingStreamingWriter:
    """Minimal writer that fails append to test fatal pipeline behavior."""

    def append(self, event: event_models.CanonicalMarketEvent) -> None:
        raise RuntimeError(f"forced append failure for {event.event_id}")

    def close(self) -> dict[str, Path]:
        return {}


def _make_pipeline(
    tmp_path: Path,
    batches: list[list[event_models.CanonicalTrade]],
) -> tuple[trade_stream_mod.TradeStreamConnector, streaming_pipeline_mod.StreamingPipeline]:
    adapter = _FiniteAdapter(batches)
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    adapter.connector = connector

    silver_writer = storage_parquet.ParquetEventWriter(tmp_path)
    streaming_writer = storage_streaming.StreamingParquetWriter(
        silver_writer,
        max_buffer_size=10_000,
        max_buffer_age_seconds=60.0,
    )
    pipeline = streaming_pipeline_mod.StreamingPipeline(
        connector=connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        streaming_writer=streaming_writer,
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )
    return connector, pipeline


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_streaming_pipeline_writes_bronze_and_silver(tmp_path: Path) -> None:
    trades = [_trade(f"t{i}", _NOW + timedelta(seconds=i)) for i in range(5)]
    batches = [[trades[0], trades[1]], [trades[2], trades[3], trades[4]]]
    _, pipeline = _make_pipeline(tmp_path, batches)

    run = asyncio.run(asyncio.wait_for(pipeline.run(), timeout=5.0))

    bronze_files = sorted((tmp_path / "bronze" / "trades").rglob("*.jsonl.gz"))
    silver_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))

    assert run.status == "completed"
    assert run.counts["events_raw"] == 5
    assert run.counts["events_silver"] == 5
    assert bronze_files, "bronze files should be written"
    assert silver_files, "silver files should be written"


def test_streaming_pipeline_empty_batches_no_crash(tmp_path: Path) -> None:
    _, pipeline = _make_pipeline(tmp_path, [])

    run = asyncio.run(asyncio.wait_for(pipeline.run(), timeout=5.0))

    assert run.status == "completed"
    assert run.counts.get("events_raw", 0) == 0


def test_streaming_pipeline_buffer_rotation_on_large_batch(tmp_path: Path) -> None:
    """A buffer with max_buffer_size=5 should rotate (flush) when exceeded."""
    adapter = _FiniteAdapter(
        [[_trade(f"t{i}", _NOW + timedelta(seconds=i)) for i in range(10)]]
    )
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    adapter.connector = connector

    silver_writer = storage_parquet.ParquetEventWriter(tmp_path)
    streaming_writer = storage_streaming.StreamingParquetWriter(
        silver_writer,
        max_buffer_size=5,       # Small buffer → triggers flush during the 10-event batch
        max_buffer_age_seconds=60.0,
    )
    pipeline = streaming_pipeline_mod.StreamingPipeline(
        connector=connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        streaming_writer=streaming_writer,
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )

    run = asyncio.run(asyncio.wait_for(pipeline.run(), timeout=5.0))

    silver_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert run.counts["events_raw"] == 10
    assert silver_files


def test_streaming_pipeline_lineage_run_persisted(tmp_path: Path) -> None:
    trades = [_trade("t1")]
    _, pipeline = _make_pipeline(tmp_path, [trades])

    run = asyncio.run(asyncio.wait_for(pipeline.run(), timeout=5.0))

    lineage_store = storage_lineage.LineageStore(tmp_path)
    runs = lineage_store.list_runs(venue="kalshi", since=None)
    assert any(r.run_id == run.run_id for r in runs)
    assert run.status == "completed"
    assert run.connector_type == "streaming"


def test_streaming_pipeline_fails_run_when_silver_append_fails(tmp_path: Path) -> None:
    trades = [[_trade("t1")]]
    adapter = _FiniteAdapter(trades)
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    adapter.connector = connector

    pipeline = streaming_pipeline_mod.StreamingPipeline(
        connector=connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        streaming_writer=_FailingStreamingWriter(),  # type: ignore[arg-type]
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )

    run = asyncio.run(asyncio.wait_for(pipeline.run(), timeout=5.0))

    assert run.status == "failed"
    assert any("streaming writer error" in error for error in run.errors)


def test_streaming_pipeline_cancelled_run_is_marked_failed(tmp_path: Path) -> None:
    async def _run_cancel() -> storage_lineage.IngestionRun:
        adapter = _BlockingAdapter()
        connector = trade_stream_mod.TradeStreamConnector(
            adapter,
            outcome_ids=["kalshi:market-a:yes"],
            reconnect_backoff_base=0.01,
            reconnect_backoff_max=0.05,
            heartbeat_timeout=120.0,
        )
        pipeline = streaming_pipeline_mod.StreamingPipeline(
            connector=connector,
            bronze_writer=storage_bronze.BronzeWriter(tmp_path),
            streaming_writer=storage_streaming.StreamingParquetWriter(
                storage_parquet.ParquetEventWriter(tmp_path),
                max_buffer_size=10_000,
                max_buffer_age_seconds=60.0,
            ),
            quality_checker=event_quality.EventQualityChecker(),
            lineage_store=storage_lineage.LineageStore(tmp_path),
        )
        task = asyncio.create_task(pipeline.run())
        await asyncio.sleep(0.05)
        task.cancel()
        return await task

    run = asyncio.run(asyncio.wait_for(_run_cancel(), timeout=5.0))

    assert run.status == "failed"
    assert any("cancelled" in error for error in run.errors)
