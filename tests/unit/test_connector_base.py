"""Unit tests for connector lifecycle base abstractions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.metrics as connector_metrics
import pytest

import alpha_core.events.models as event_models


def _metadata_event(instrument_id: str = "kalshi:market-a") -> event_models.CanonicalMetadataUpdate:
    now = datetime.now(tz=UTC)
    return event_models.CanonicalMetadataUpdate.model_validate(
        {
            "instrument_id": instrument_id,
            "venue_id": "kalshi",
            "ts_event": now,
            "ts_record": now,
            "fields_changed": {"status": "updated"},
        }
    )


class _FinitePollingConnector(connector_base.PollingConnector):
    def __init__(self, emit: object = None) -> None:
        super().__init__(venue="kalshi", interval_seconds=0.01, emit=emit)
        self.poll_calls = 0

    async def poll_once(self) -> connector_base.PollingBatch:
        self.poll_calls += 1
        self._stop_event.set()
        return connector_base.PollingBatch(
            events=[_metadata_event()],
            raw_payloads={},
        )


class _FailingPollingConnector(connector_base.PollingConnector):
    def __init__(self) -> None:
        super().__init__(venue="kalshi", interval_seconds=0.01)

    async def poll_once(self) -> connector_base.PollingBatch:
        raise RuntimeError("poll failed")


class _ReconnectingStreamingConnector(connector_base.StreamingConnector):
    def __init__(self) -> None:
        super().__init__(venue="kalshi")
        self.connect_attempts = 0

    async def connect(self) -> None:
        self.connect_attempts += 1
        if self.connect_attempts == 1:
            raise RuntimeError("connection dropped")

    async def stream_loop(self) -> None:
        self._record_events([_metadata_event()])
        self._stop_event.set()


class _SimplePollingConnector(connector_base.PollingConnector):
    async def poll_once(self) -> connector_base.PollingBatch:
        return connector_base.PollingBatch(events=[], raw_payloads={})


class _SyncCollector:
    def __init__(self) -> None:
        self.events: list[event_models.CanonicalMarketEvent] = []

    def __call__(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        self.events.extend(events)


class _AsyncCollector:
    def __init__(self) -> None:
        self.events: list[event_models.CanonicalMarketEvent] = []

    async def __call__(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        await asyncio.sleep(0)
        self.events.extend(events)


async def _start_sleep_stop(
    connector: connector_base.BaseConnector,
    *,
    sleep_seconds: float,
    start_calls: int = 1,
    stop: bool = True,
) -> None:
    for _ in range(start_calls):
        await connector.start()
    await asyncio.sleep(sleep_seconds)
    if stop:
        await connector.stop()


def test_connector_metrics_default_values() -> None:
    metrics = connector_metrics.ConnectorMetrics()

    assert metrics.events_received == 0
    assert metrics.events_normalised == 0
    assert metrics.events_rejected == 0
    assert metrics.last_event_ts is None
    assert metrics.uptime_seconds == 0.0
    assert metrics.reconnect_count == 0
    assert metrics.errors == []


def test_polling_connector_start_and_stop_updates_state_and_metrics() -> None:
    connector = _FinitePollingConnector()
    asyncio.run(_start_sleep_stop(connector, sleep_seconds=0.02))

    snapshot = connector.metrics()
    assert connector.poll_calls >= 1
    assert connector.state == "stopped"
    assert snapshot.events_received == 1
    assert snapshot.events_normalised == 1
    assert snapshot.last_event_ts is not None
    assert snapshot.uptime_seconds > 0


def test_polling_connector_start_is_idempotent() -> None:
    connector = _FinitePollingConnector()
    asyncio.run(_start_sleep_stop(connector, sleep_seconds=0.02, start_calls=2))

    assert connector.poll_calls >= 1


def test_polling_connector_records_errors() -> None:
    connector = _FailingPollingConnector()
    asyncio.run(_start_sleep_stop(connector, sleep_seconds=0.02, stop=False))

    assert connector.state == "error"
    assert any("poll failed" in error for error in connector.metrics().errors)
    assert connector.metrics().events_rejected == 1


def test_streaming_connector_reconnects_after_error() -> None:
    connector = _ReconnectingStreamingConnector()
    asyncio.run(_start_sleep_stop(connector, sleep_seconds=1.1))

    snapshot = connector.metrics()
    assert connector.connect_attempts >= 2
    assert snapshot.reconnect_count >= 1
    assert snapshot.events_received == 1


def test_metrics_snapshot_does_not_expose_internal_error_list() -> None:
    connector = _FinitePollingConnector()
    connector._metrics.errors.append("initial")

    snapshot = connector.metrics()
    snapshot.errors.append("external-mutation")

    assert connector.metrics().errors == ["initial"]


def test_polling_connector_requires_positive_interval() -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        _SimplePollingConnector(venue="kalshi", interval_seconds=0.0)


def test_polling_connector_emits_events_via_sync_callback() -> None:
    collector = _SyncCollector()
    connector = _FinitePollingConnector(emit=collector)
    asyncio.run(_start_sleep_stop(connector, sleep_seconds=0.02))
    assert len(collector.events) == 1


def test_polling_connector_emits_events_via_async_callback() -> None:
    collector = _AsyncCollector()
    connector = _FinitePollingConnector(emit=collector)
    asyncio.run(_start_sleep_stop(connector, sleep_seconds=0.02))
    assert len(collector.events) == 1


def test_polling_connector_stop_without_start_sets_stopped_state() -> None:
    connector = _FinitePollingConnector()
    asyncio.run(connector.stop())
    assert connector.state == "stopped"
