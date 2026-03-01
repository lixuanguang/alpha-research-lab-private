"""Integration tests for polling pipeline execution."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors._types as connector_types
import apps.data_collector.pipeline as collector_pipeline
import pytest

import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.utils.ids as ids_utils


def _trade(trade_id: str, ts_event: datetime) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=100),
        "schema_version": 1,
        "price": Decimal("0.51"),
        "size": Decimal("3"),
        "side": event_models.TradeSide.BUY,
        "trade_id": trade_id,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


def _metadata_update(ts_event: datetime) -> event_models.CanonicalMetadataUpdate:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.METADATA_UPDATE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=100),
        "schema_version": 1,
        "fields_changed": {"status": "updated"},
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalMetadataUpdate.model_validate(payload)


class _StubTradeConnector(connector_polling.PollingConnector):
    def __init__(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        super().__init__(venue="kalshi", interval_seconds=30.0)
        self._events = events

    async def poll_once(self) -> connector_types.PollingBatch:
        return connector_types.PollingBatch(
            events=list(self._events),
            raw_payloads={},
        )


def test_polling_pipeline_writes_bronze_and_silver(tmp_path: Path) -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    connector = _StubTradeConnector([_trade("t1", now), _trade("t2", now + timedelta(seconds=1))])
    pipeline = collector_pipeline.PollingPipeline(
        connector=connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )

    run = asyncio.run(pipeline.execute())

    bronze_files = sorted((tmp_path / "bronze" / "trades").rglob("*.jsonl.gz"))
    silver_files = sorted((tmp_path / "silver" / "trades").rglob("*.parquet"))

    assert run.status == "completed"
    assert run.counts["events_raw"] == 2
    assert run.counts["events_silver"] == 2
    assert bronze_files
    assert silver_files


def test_polling_pipeline_handles_empty_response_without_crashing(tmp_path: Path) -> None:
    connector = _StubTradeConnector([])
    pipeline = collector_pipeline.PollingPipeline(
        connector=connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )

    run = asyncio.run(pipeline.execute())

    assert run.status == "completed"
    assert run.counts["events_raw"] == 0
    assert run.counts["events_silver"] == 0


def test_polling_pipeline_counts_only_persisted_silver_events(tmp_path: Path) -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    connector = _StubTradeConnector([_metadata_update(now)])
    pipeline = collector_pipeline.PollingPipeline(
        connector=connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )

    run = asyncio.run(pipeline.execute())

    assert run.status == "completed"
    assert run.counts["events_raw"] == 1
    assert run.counts["events_silver"] == 0
    assert run.counts["metadata_skipped"] == 1


@pytest.mark.perf
def test_polling_pipeline_single_cycle_meets_d3_latency_target(tmp_path: Path) -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    connector = _StubTradeConnector([_trade("t1", now), _trade("t2", now + timedelta(seconds=1))])
    pipeline = collector_pipeline.PollingPipeline(
        connector=connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )

    started = time.perf_counter()
    run = asyncio.run(pipeline.execute())
    elapsed = time.perf_counter() - started

    assert run.status == "completed"
    assert elapsed < 1.0
