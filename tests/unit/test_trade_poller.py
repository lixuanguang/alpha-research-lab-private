"""Unit tests for trade polling connector."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import apps.data_collector.connectors.trade_poller as connector_trade_poller

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.instruments.models as instrument_models
import alpha_core.utils.ids as ids_utils


def _trade(trade_id: str, ts_event: datetime) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=100),
        "schema_version": 1,
        "price": Decimal("0.50"),
        "size": Decimal("2"),
        "side": event_models.TradeSide.BUY,
        "trade_id": trade_id,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


class _MockAdapter(adapters_base.VenueAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime | None, int]] = []
        self.responses: dict[str, list[event_models.CanonicalTrade]] = {}
        self.delay_seconds = 0.0

    def venue_name(self) -> str:
        return "kalshi"

    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        self.calls.append((outcome_id, since, limit))
        return self.responses.get(outcome_id, [])

    async def fetch_trades_with_raw(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        trades = await self.fetch_trades(outcome_id, since=since, limit=limit)
        return trades, [trade.model_dump(mode="json") for trade in trades]

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return []

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        raise NotImplementedError(f"book polling not implemented in test adapter: {outcome_id}")

    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        del outcome_id, resolution, limit
        return []

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        return [], []

    async def fetch_order_book_with_raw(
        self,
        outcome_id: str,
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        raise NotImplementedError(f"book polling not implemented in test adapter: {outcome_id}")

    async def fetch_ohlcv_with_raw(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        del outcome_id, resolution, limit
        return [], []


def test_trade_poller_polls_all_outcomes_and_uses_limit() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {
        "kalshi:market-a:yes": [_trade("t1", ts)],
        "kalshi:market-b:yes": [_trade("t2", ts + timedelta(seconds=1))],
    }
    poller = connector_trade_poller.TradePoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes", "kalshi:market-b:yes"],
        limit_per_poll=42,
    )

    events = asyncio.run(poller.poll_once()).events
    trades = [event for event in events if isinstance(event, event_models.CanonicalTrade)]

    assert len(trades) == len(events)
    assert [trade.trade_id for trade in trades] == ["t1", "t2"]
    assert adapter.calls[0][2] == 42
    assert adapter.calls[1][2] == 42


def test_trade_poller_deduplicates_outcome_ids() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {"kalshi:market-a:yes": [_trade("t1", ts)]}
    poller = connector_trade_poller.TradePoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes", "kalshi:market-a:yes"],
    )

    events = asyncio.run(poller.poll_once()).events

    assert len(events) == 1
    assert len(adapter.calls) == 1


def test_trade_poller_deduplicates_trade_ids_across_polls() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {"kalshi:market-a:yes": [_trade("dup", ts)]}
    poller = connector_trade_poller.TradePoller(adapter, outcome_ids=["kalshi:market-a:yes"])

    first = asyncio.run(poller.poll_once()).events
    second = asyncio.run(poller.poll_once()).events

    assert len(first) == 1
    assert second == []


def test_trade_poller_passes_incremental_since_timestamp() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {"kalshi:market-a:yes": [_trade("t1", ts)]}
    poller = connector_trade_poller.TradePoller(adapter, outcome_ids=["kalshi:market-a:yes"])

    asyncio.run(poller.poll_once())
    asyncio.run(poller.poll_once())

    assert adapter.calls[0][1] is None
    assert adapter.calls[1][1] == ts


def test_trade_poller_handles_empty_outcomes() -> None:
    adapter = _MockAdapter()
    poller = connector_trade_poller.TradePoller(adapter, outcome_ids=[])

    events = asyncio.run(poller.poll_once()).events

    assert events == []
    assert adapter.calls == []


def test_trade_poller_marks_timeouts_as_rejections() -> None:
    adapter = _MockAdapter()
    adapter.delay_seconds = 0.05
    poller = connector_trade_poller.TradePoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        request_timeout_seconds=0.01,
    )

    batch = asyncio.run(poller.poll_once())

    assert batch.events == []
    assert poller.metrics().events_rejected == 1
    assert "timed out" in poller.metrics().errors[0]


def test_trade_poller_bounded_dedup_cache_allows_old_ids_after_eviction() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    poller = connector_trade_poller.TradePoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        max_seen_trade_ids=1,
    )

    adapter.responses = {"kalshi:market-a:yes": [_trade("t1", ts)]}
    first = asyncio.run(poller.poll_once()).events
    adapter.responses = {"kalshi:market-a:yes": [_trade("t2", ts + timedelta(seconds=1))]}
    second = asyncio.run(poller.poll_once()).events
    adapter.responses = {"kalshi:market-a:yes": [_trade("t1", ts + timedelta(seconds=2))]}
    third = asyncio.run(poller.poll_once()).events

    first_trades = [event for event in first if isinstance(event, event_models.CanonicalTrade)]
    second_trades = [event for event in second if isinstance(event, event_models.CanonicalTrade)]
    third_trades = [event for event in third if isinstance(event, event_models.CanonicalTrade)]

    assert len(first_trades) == len(first)
    assert len(second_trades) == len(second)
    assert len(third_trades) == len(third)
    assert [trade.trade_id for trade in first_trades] == ["t1"]
    assert [trade.trade_id for trade in second_trades] == ["t2"]
    assert [trade.trade_id for trade in third_trades] == ["t1"]
