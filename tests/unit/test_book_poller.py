"""Unit tests for book snapshot polling connector."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import apps.data_collector.connectors.book_poller as connector_book_poller

import alpha_core.events.models as event_models
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


class _MockAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, event_models.CanonicalBookSnapshot] = {}
        self.failures: set[str] = set()

    def venue_name(self) -> str:
        return "kalshi"

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
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
