"""Unit tests for BookStreamConnector."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.book_stream as book_stream_mod

import alpha_core.events.models as event_models
import alpha_core.utils.ids as ids_utils

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _book(ts: datetime | None = None) -> event_models.CanonicalBookSnapshot:
    ts = ts or _NOW
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.BOOK_SNAPSHOT,
        "ts_event": ts,
        "ts_record": ts + timedelta(milliseconds=50),
        "schema_version": 1,
        "bids": [{"price": Decimal("0.49"), "size": Decimal("10")}],
        "asks": [{"price": Decimal("0.51"), "size": Decimal("9")}],
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalBookSnapshot.model_validate(payload)


class _MockAdapter:
    def __init__(self) -> None:
        self._venue = "kalshi"
        self.snapshots: dict[str, list[event_models.CanonicalBookSnapshot]] = {}

    def venue_name(self) -> str:
        return self._venue

    async def watch_order_book(
        self, outcome_id: str
    ) -> AsyncIterator[event_models.CanonicalBookSnapshot]:
        for snap in self.snapshots.get(outcome_id, []):
            yield snap


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[event_models.CanonicalMarketEvent] = []

    def __call__(self, events: list[event_models.CanonicalMarketEvent]) -> None:
        self.events.extend(events)


# ---------------------------------------------------------------------------
# Basic streaming
# ---------------------------------------------------------------------------


def test_stream_emits_snapshots() -> None:
    adapter = _MockAdapter()
    adapter.snapshots["kalshi:m:yes"] = [_book(), _book(_NOW + timedelta(seconds=1))]
    collector = _EventCollector()
    connector = book_stream_mod.BookStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
        emit=collector,
    )
    asyncio.run(connector.stream_loop())
    books = [e for e in collector.events if isinstance(e, event_models.CanonicalBookSnapshot)]
    assert len(books) == 2


def test_empty_outcome_ids_returns_after_stop() -> None:
    adapter = _MockAdapter()
    connector = book_stream_mod.BookStreamConnector(
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
    adapter.snapshots["kalshi:m:yes"] = [_book(), _book()]
    connector = book_stream_mod.BookStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    asyncio.run(connector.stream_loop())
    assert connector.metrics().events_received == 2


# ---------------------------------------------------------------------------
# Error handling / reconnection
# ---------------------------------------------------------------------------


def test_run_stream_reconnects_on_error() -> None:
    call_count = 0
    connector_ref: list[book_stream_mod.BookStreamConnector] = []

    class _FailOnceAdapter:
        def venue_name(self) -> str:
            return "kalshi"

        async def watch_order_book(
            self, outcome_id: str
        ) -> AsyncIterator[event_models.CanonicalBookSnapshot]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("dropped")
            yield _book()
            connector_ref[0]._stop_event.set()

    connector = book_stream_mod.BookStreamConnector(
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
    connector = book_stream_mod.BookStreamConnector(
        adapter,
        outcome_ids=[],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )

    async def _run() -> None:
        connector._stop_event.set()
        await connector._run_stream()

    asyncio.run(_run())
    assert connector.state == connector_base.ConnectorState.STOPPED


# ---------------------------------------------------------------------------
# Outcome ID normalisation
# ---------------------------------------------------------------------------


def test_duplicate_outcome_ids_normalised() -> None:
    adapter = _MockAdapter()
    connector = book_stream_mod.BookStreamConnector(
        adapter,
        outcome_ids=["id-a", "id-a", "id-b"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )
    assert connector._outcome_ids == ["id-a", "id-b"]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_and_stop() -> None:
    adapter = _MockAdapter()
    connector = book_stream_mod.BookStreamConnector(
        adapter,
        outcome_ids=["kalshi:m:yes"],
        reconnect_backoff_base=0.01,
        reconnect_backoff_max=0.05,
    )

    async def _run() -> None:
        await connector.start()
        await connector.stop()

    asyncio.run(_run())
    assert connector.state == connector_base.ConnectorState.STOPPED
