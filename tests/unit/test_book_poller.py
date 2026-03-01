"""Unit tests for book snapshot polling connector."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import apps.data_collector.connectors.book_poller as connector_book_poller

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.instruments.models as instrument_models
import alpha_core.utils.ids as ids_utils


def _book(ts_event: datetime) -> event_models.CanonicalBookSnapshot:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.BOOK_SNAPSHOT,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=100),
        "schema_version": 1,
        "bids": [{"price": Decimal("0.49"), "size": Decimal("10")}],
        "asks": [{"price": Decimal("0.51"), "size": Decimal("9")}],
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalBookSnapshot.model_validate(payload)


class _MockAdapter(adapters_base.VenueAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, event_models.CanonicalBookSnapshot] = {}
        self.failures: set[str] = set()
        self.delay_seconds = 0.0

    def venue_name(self) -> str:
        return "kalshi"

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        self.calls.append(outcome_id)
        if outcome_id in self.failures:
            raise RuntimeError("fetch failed")
        return self.responses[outcome_id]

    async def fetch_order_book_with_raw(
        self,
        outcome_id: str,
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        snapshot = await self.fetch_order_book(outcome_id)
        return snapshot, snapshot.model_dump(mode="json")

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return []

    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        del outcome_id, since, limit
        return []

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

    async def fetch_trades_with_raw(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        del outcome_id, since, limit
        return [], []

    async def fetch_ohlcv_with_raw(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        del outcome_id, resolution, limit
        return [], []


def test_book_poller_polls_all_outcomes() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {
        "kalshi:market-a:yes": _book(ts),
        "kalshi:market-b:yes": _book(ts + timedelta(seconds=1)),
    }
    poller = connector_book_poller.BookSnapshotPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes", "kalshi:market-b:yes"],
    )

    events = asyncio.run(poller.poll_once()).events

    assert len(events) == 2
    assert adapter.calls == ["kalshi:market-a:yes", "kalshi:market-b:yes"]


def test_book_poller_deduplicates_outcome_ids() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {"kalshi:market-a:yes": _book(ts)}
    poller = connector_book_poller.BookSnapshotPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes", "kalshi:market-a:yes"],
    )

    events = asyncio.run(poller.poll_once()).events

    assert len(events) == 1
    assert adapter.calls == ["kalshi:market-a:yes"]


def test_book_poller_handles_empty_outcomes() -> None:
    adapter = _MockAdapter()
    poller = connector_book_poller.BookSnapshotPoller(adapter, outcome_ids=[])

    events = asyncio.run(poller.poll_once()).events

    assert events == []


def test_book_poller_continues_on_per_outcome_errors() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {
        "kalshi:market-a:yes": _book(ts),
        "kalshi:market-b:yes": _book(ts + timedelta(seconds=1)),
    }
    adapter.failures.add("kalshi:market-b:yes")
    poller = connector_book_poller.BookSnapshotPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes", "kalshi:market-b:yes"],
    )

    events = asyncio.run(poller.poll_once()).events

    assert len(events) == 1
    assert poller.metrics().events_rejected == 1


def test_book_poller_marks_timeouts_as_rejections() -> None:
    adapter = _MockAdapter()
    adapter.delay_seconds = 0.05
    adapter.responses = {
        "kalshi:market-a:yes": _book(datetime(2026, 3, 1, 12, 0, tzinfo=UTC)),
    }
    poller = connector_book_poller.BookSnapshotPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        request_timeout_seconds=0.01,
    )

    batch = asyncio.run(poller.poll_once())

    assert batch.events == []
    assert poller.metrics().events_rejected == 1
    assert "timed out" in poller.metrics().errors[0]


def test_book_poller_includes_raw_payloads_in_batch() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {
        "kalshi:market-a:yes": _book(ts),
    }
    poller = connector_book_poller.BookSnapshotPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
    )

    batch = asyncio.run(poller.poll_once())

    assert len(batch.events) == 1
    assert "books" in batch.raw_payloads
    assert len(batch.raw_payloads["books"]) == 1
    assert batch.raw_payloads["books"][0]["outcome_id"] == "kalshi:market-a:yes"
