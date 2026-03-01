"""Unit tests for market refresh polling connector."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import apps.data_collector.connectors.market_refresh as connector_market_refresh
import pytest

import alpha_core.events.models as event_models
import alpha_core.instruments.master as instrument_master
import alpha_core.instruments.models as instrument_models


def _market(
    market_id: str,
    *,
    title: str = "Initial title",
    first_seen: datetime | None = None,
    last_updated: datetime | None = None,
) -> instrument_models.MarketSpec:
    now = datetime.now(tz=UTC)
    return instrument_models.MarketSpec.model_validate(
        {
            "market_id": market_id,
            "venue": "kalshi",
            "title": title,
            "description": "desc",
            "category": "politics",
            "tags": ["us"],
            "outcomes": [
                {
                    "outcome_id": "yes",
                    "label": "Yes",
                    "canonical_id": f"kalshi:{market_id}:yes",
                }
            ],
            "resolution_date": None,
            "lifecycle": instrument_models.MarketLifecycle.ACTIVE,
            "volume": "0",
            "liquidity": "0",
            "url": None,
            "first_seen": first_seen or now,
            "last_updated": last_updated or now,
        }
    )


class _MockAdapter:
    def __init__(
        self,
        markets: list[instrument_models.MarketSpec],
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        self._markets = markets
        self._delay_seconds = delay_seconds

    def venue_name(self) -> str:
        return "kalshi"

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return self._markets

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        markets = await self.fetch_markets()
        return markets, [market.model_dump(mode="json") for market in markets]


def test_market_refresh_registers_new_markets_and_emits_metadata_events() -> None:
    master = instrument_master.MarketMaster()
    poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([_market("market-a")]), master, interval_seconds=60.0
    )

    events = asyncio.run(poller.poll_once()).events

    stored = master.get_market("kalshi:market-a")
    assert stored is not None
    assert len(events) == 1
    assert events[0].event_type == event_models.EventType.METADATA_UPDATE


def test_market_refresh_marks_new_markets_in_metadata_payload() -> None:
    master = instrument_master.MarketMaster()
    poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([_market("market-a")]), master, interval_seconds=60.0
    )

    events = asyncio.run(poller.poll_once()).events

    assert len(events) == 1
    assert isinstance(events[0], event_models.CanonicalMetadataUpdate)
    assert events[0].fields_changed == {"status": "new_market"}


def test_market_refresh_ignores_unchanged_markets() -> None:
    market = _market("market-a")
    master = instrument_master.MarketMaster()
    poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([market]), master, interval_seconds=60.0
    )

    first_events = asyncio.run(poller.poll_once()).events
    second_events = asyncio.run(poller.poll_once()).events

    assert len(first_events) == 1
    assert second_events == []


def test_market_refresh_emits_event_for_changed_market() -> None:
    original = _market("market-a", title="Old title")
    updated = _market("market-a", title="New title")
    master = instrument_master.MarketMaster()

    first_poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([original]), master, interval_seconds=60.0
    )
    second_poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([updated]), master, interval_seconds=60.0
    )

    asyncio.run(first_poller.poll_once())
    events = asyncio.run(second_poller.poll_once()).events

    assert len(events) == 1
    changed = events[0]
    assert isinstance(changed, event_models.CanonicalMetadataUpdate)
    assert changed.fields_changed["previous"]["title"] == "Old title"
    assert changed.fields_changed["current"]["title"] == "New title"


def test_market_refresh_ignores_first_seen_and_last_updated_diff_only() -> None:
    original = _market(
        "market-a",
        first_seen=datetime(2026, 2, 1, tzinfo=UTC),
        last_updated=datetime(2026, 2, 1, tzinfo=UTC),
    )
    refreshed = _market(
        "market-a",
        first_seen=datetime(2026, 2, 2, tzinfo=UTC),
        last_updated=datetime(2026, 2, 2, tzinfo=UTC),
    )
    master = instrument_master.MarketMaster()

    first_poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([original]), master, interval_seconds=60.0
    )
    second_poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([refreshed]), master, interval_seconds=60.0
    )

    asyncio.run(first_poller.poll_once())
    events = asyncio.run(second_poller.poll_once()).events

    assert events == []


def test_market_refresh_times_out_slow_fetch_calls() -> None:
    master = instrument_master.MarketMaster()
    poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter([_market("market-a")], delay_seconds=0.05),
        master,
        interval_seconds=60.0,
        request_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError, match="fetch_markets"):
        asyncio.run(poller.poll_once())


@pytest.mark.perf
def test_market_refresh_cycle_meets_d1_latency_target() -> None:
    master = instrument_master.MarketMaster()
    markets = [_market(f"market-{index}") for index in range(100)]
    poller = connector_market_refresh.MarketRefreshPoller(
        _MockAdapter(markets),
        master,
        interval_seconds=60.0,
    )

    started = time.perf_counter()
    events = asyncio.run(poller.poll_once()).events
    elapsed = time.perf_counter() - started

    assert len(events) == 100
    assert elapsed < 5.0
