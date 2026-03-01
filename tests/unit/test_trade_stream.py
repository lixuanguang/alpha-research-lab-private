"""Unit tests for TradeStreamConnector."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import apps.data_collector.connectors._types as connector_types
import apps.data_collector.connectors.heartbeat as heartbeat_mod
import apps.data_collector.connectors.trade_stream as trade_stream_mod

import alpha_core.events.models as event_models
import alpha_core.utils.ids as ids_utils

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _trade(trade_id: str = "t1", ts: datetime | None = None) -> event_models.CanonicalTrade:
    ts = ts or _NOW
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts,
        "ts_record": ts + timedelta(milliseconds=50),
        "schema_version": 1,
        "price": Decimal("0.50"),
        "size": Decimal("1"),
        "side": event_models.TradeSide.BUY,
        "trade_id": trade_id,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


class _MockAdapter:
    """Mock adapter with controllable async generator behaviour."""

    def __init__(self) -> None:
        self._venue = "kalshi"
        self.batches: dict[str, list[list[event_models.CanonicalTrade]]] = {}
        self.call_counts: dict[str, int] = {}
        self.raise_on: dict[str, int] = {}  # outcome_id → raise after N yields

    def venue_name(self) -> str:
        return self._venue

    async def watch_trades(
        self, outcome_id: str
    ) -> AsyncIterator[list[event_models.CanonicalTrade]]:
        self.call_counts[outcome_id] = self.call_counts.get(outcome_id, 0) + 1
        yielded = 0
        for batch in self.batches.get(outcome_id, []):
            if outcome_id in self.raise_on and yielded >= self.raise_on[outcome_id]:
                raise ConnectionError("stream dropped")
            yield batch
            yielded += 1


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[event_models.CanonicalMarketEvent] = []

    def __call__(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        self.events.extend(events)


# ---------------------------------------------------------------------------
# Basic streaming
# ---------------------------------------------------------------------------


def test_stream_yields_batches_to_emit() -> None:
    adapter = _MockAdapter()
    adapter.batches["kalshi:market-a:yes"] = [[_trade("t1")], [_trade("t2")]]
    collector = _EventCollector()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
        emit=collector,
    )

    asyncio.run(connector.stream_loop())

    trade_ids = [e.trade_id for e in collector.events if isinstance(e, event_models.CanonicalTrade)]
    assert trade_ids == ["t1", "t2"]


def test_empty_outcome_ids_stream_loop_waits_for_stop() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=[],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )

    async def _run() -> None:
        connector._stop_event.set()
        await connector.stream_loop()

    asyncio.run(_run())


def test_metrics_updated_after_stream() -> None:
    adapter = _MockAdapter()
    adapter.batches["kalshi:market-a:yes"] = [[_trade("t1"), _trade("t2")]]
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    asyncio.run(connector.stream_loop())
    assert connector.metrics().events_received == 2


# ---------------------------------------------------------------------------
# Heartbeat monitor
# ---------------------------------------------------------------------------


def test_heartbeat_recorded_per_batch() -> None:
    clock: list[float] = [0.0]
    monitor = heartbeat_mod.HeartbeatMonitor(timeout_seconds=30.0, time_func=lambda: clock[0])
    adapter = _MockAdapter()
    adapter.batches["kalshi:m:yes"] = [[_trade("t1")]]
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        heartbeat_monitor=monitor,
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    asyncio.run(connector.stream_loop())
    assert connector.connector_id in monitor.tracked()


# ---------------------------------------------------------------------------
# Reconnection via _run_stream
# ---------------------------------------------------------------------------


def test_run_stream_reconnects_on_error() -> None:
    """Adapter raises on first call; second call yields and stops cleanly."""
    call_count = 0
    connector_ref: list[trade_stream_mod.TradeStreamConnector] = []

    class _FailOnceAdapter:
        def venue_name(self) -> str:
            return "kalshi"

        async def watch_trades(
            self, outcome_id: str
        ) -> AsyncIterator[list[event_models.CanonicalTrade]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("first call fails")
            yield [_trade("t1")]
            # Stop the connector so _run_stream exits after this success.
            connector_ref[0]._stop_event.set()

    connector = trade_stream_mod.TradeStreamConnector(
        _FailOnceAdapter(),
        outcome_ids=["kalshi:m:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    connector_ref.append(connector)
    asyncio.run(asyncio.wait_for(connector._run_stream(), timeout=2.0))
    assert connector.metrics().reconnect_count == 1


def test_stop_event_exits_run_stream() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=[],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )

    async def _run() -> None:
        connector._stop_event.set()
        await connector._run_stream()

    asyncio.run(_run())
    assert connector.state == connector_types.ConnectorState.STOPPED


# ---------------------------------------------------------------------------
# Duplicate / empty outcomes normalised
# ---------------------------------------------------------------------------


def test_duplicate_outcome_ids_normalised() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["  id-a  ", "id-a", "id-b"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    assert connector._outcome_ids == ["id-a", "id-b"]


def test_empty_strings_stripped_from_outcome_ids() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["  ", "", "id-a"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    assert connector._outcome_ids == ["id-a"]


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


def test_start_and_stop() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )

    async def _run() -> None:
        await connector.start()
        await connector.stop()

    asyncio.run(_run())
    assert connector.state == connector_types.ConnectorState.STOPPED
