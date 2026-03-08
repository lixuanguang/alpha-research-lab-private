"""Unit tests for TradeStreamConnector."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
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


def _stream_options(
    *,
    heartbeat_monitor: heartbeat_mod.HeartbeatMonitor | None = None,
    heartbeat_timeout: float = 120.0,
    emit: Callable[[list[event_models.CanonicalMarketEvent]], None] | None = None,
) -> trade_stream_mod.TradeStreamOptions:
    return trade_stream_mod.TradeStreamOptions(
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
        heartbeat_timeout=heartbeat_timeout,
        heartbeat_monitor=heartbeat_monitor,
        emit=emit,
    )


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
        for yielded, batch in enumerate(self.batches.get(outcome_id, [])):
            if outcome_id in self.raise_on and yielded >= self.raise_on[outcome_id]:
                raise ConnectionError("stream dropped")
            yield batch


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
        options=_stream_options(emit=collector),
    )

    asyncio.run(connector.stream_loop())

    trade_ids = [e.trade_id for e in collector.events if isinstance(e, event_models.CanonicalTrade)]
    assert trade_ids == ["t1", "t2"]


def test_empty_outcome_ids_stream_loop_waits_for_stop() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=[],
        options=_stream_options(),
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
        options=_stream_options(),
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
        options=_stream_options(heartbeat_monitor=monitor),
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
        options=_stream_options(),
    )
    connector_ref.append(connector)
    asyncio.run(asyncio.wait_for(connector._run_stream(), timeout=2.0))
    assert connector.metrics().reconnect_count == 1


def test_stop_event_exits_run_stream() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=[],
        options=_stream_options(),
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
        options=_stream_options(),
    )
    assert connector._outcome_ids == ["id-a", "id-b"]


def test_empty_strings_stripped_from_outcome_ids() -> None:
    adapter = _MockAdapter()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["  ", "", "id-a"],
        options=_stream_options(),
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
        options=_stream_options(),
    )

    async def _run() -> None:
        await connector.start()
        await connector.stop()

    asyncio.run(_run())
    assert connector.state == connector_types.ConnectorState.STOPPED


# ---------------------------------------------------------------------------
# Microstructure — 11.1
# ---------------------------------------------------------------------------


def test_ts_receive_stamped_on_emitted_trades() -> None:
    """Every emitted trade must carry a non-None ts_receive (local receipt clock)."""
    adapter = _MockAdapter()
    adapter.batches["kalshi:m:yes"] = [[_trade("t1"), _trade("t2")]]
    collector = _EventCollector()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        options=_stream_options(emit=collector),
    )
    asyncio.run(connector.stream_loop())
    trades = [e for e in collector.events if isinstance(e, event_models.CanonicalTrade)]
    assert len(trades) == 2
    for t in trades:
        assert t.ts_receive is not None, "ts_receive must be stamped at receive time"
    # All trades in a batch share the same receive timestamp (sampled once per batch).
    assert trades[0].ts_receive == trades[1].ts_receive


def test_sequence_id_preserved_through_stream() -> None:
    """sequence_id set by the adapter must survive the ts_receive enrichment step."""
    adapter = _MockAdapter()
    ts = _NOW
    # Let the model auto-generate event_id (sequence_id is excluded from the hash).
    trade_with_seq = event_models.CanonicalTrade.model_validate(
        {
            "instrument_id": "kalshi:market-a:yes",
            "venue_id": "kalshi",
            "event_type": event_models.EventType.TRADE,
            "ts_event": ts,
            "ts_record": ts + timedelta(milliseconds=50),
            "schema_version": 1,
            "price": Decimal("0.50"),
            "size": Decimal("1"),
            "side": event_models.TradeSide.BUY,
            "trade_id": "seq-trade",
            "sequence_id": "1234567",
        }
    )
    adapter.batches["kalshi:m:yes"] = [[trade_with_seq]]
    collector = _EventCollector()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        options=_stream_options(emit=collector),
    )
    asyncio.run(connector.stream_loop())
    result = [e for e in collector.events if isinstance(e, event_models.CanonicalTrade)]
    assert len(result) == 1
    assert result[0].sequence_id == "1234567"


def test_gap_marker_not_emitted_on_initial_connection() -> None:
    """No gap marker on the very first connection; only on subsequent reconnects."""
    adapter = _MockAdapter()
    adapter.batches["kalshi:m:yes"] = [[_trade("t1")]]
    collector = _EventCollector()
    connector = trade_stream_mod.TradeStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        options=_stream_options(emit=collector),
    )
    asyncio.run(connector.stream_loop())
    markers = [e for e in collector.events if isinstance(e, event_models.CanonicalMetadataUpdate)]
    assert markers == []


def test_reconnect_emits_gap_marker_with_capabilities() -> None:
    """After a disconnect, a gap marker with capability flags is emitted per outcome."""
    call_count = 0
    connector_ref: list[trade_stream_mod.TradeStreamConnector] = []
    collector = _EventCollector()

    class _CapableFailOnceAdapter:
        def venue_name(self) -> str:
            return "kalshi"

        def trade_stream_capabilities(self) -> dict[str, bool]:
            return {"sequence_id": True, "latency_metadata": False}

        async def watch_trades(
            self, outcome_id: str
        ) -> AsyncIterator[list[event_models.CanonicalTrade]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("stream dropped")
            yield [_trade("t1")]
            connector_ref[0]._stop_event.set()

    connector = trade_stream_mod.TradeStreamConnector(
        _CapableFailOnceAdapter(),
        outcome_ids=["kalshi:m:yes"],
        options=_stream_options(emit=collector),
    )
    connector_ref.append(connector)
    asyncio.run(asyncio.wait_for(connector._run_stream(), timeout=2.0))

    markers = [e for e in collector.events if isinstance(e, event_models.CanonicalMetadataUpdate)]
    assert len(markers) == 1
    m = markers[0]
    assert m.is_reconnect_gap is True
    assert m.sequence_id_capable is True
    assert m.latency_metadata_capable is False
    assert m.fields_changed["stream_capabilities"]["sequence_id"] is True


def test_resolve_stream_capabilities_defaults_when_no_method() -> None:
    """Adapters without trade_stream_capabilities() default to all-False."""
    caps = trade_stream_mod._resolve_stream_capabilities(_MockAdapter())
    assert caps == {"sequence_id": False, "latency_metadata": False}


def test_resolve_stream_capabilities_reads_adapter_values() -> None:
    """_resolve_stream_capabilities returns the dict provided by the adapter."""

    class _SeqAdapter:
        def trade_stream_capabilities(self) -> dict[str, bool]:
            return {"sequence_id": True, "latency_metadata": True}

    caps = trade_stream_mod._resolve_stream_capabilities(_SeqAdapter())
    assert caps == {"sequence_id": True, "latency_metadata": True}
