"""Unit tests for OHLCV polling connector."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import apps.data_collector.connectors.ohlcv_poller as connector_ohlcv_poller

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.instruments.models as instrument_models
import alpha_core.utils.ids as ids_utils


def _candle(ts_event: datetime, resolution: str = "1h") -> event_models.CanonicalOHLCV:
    payload: dict[str, object] = {
        "instrument_id": "kalshi:market-a:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.OHLCV,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=100),
        "schema_version": 1,
        "open": Decimal("0.49"),
        "high": Decimal("0.51"),
        "low": Decimal("0.48"),
        "close": Decimal("0.50"),
        "volume": Decimal("10"),
        "resolution": resolution,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalOHLCV.model_validate(payload)


class _MockAdapter(adapters_base.VenueAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.responses: dict[str, list[event_models.CanonicalOHLCV]] = {}
        self.delay_seconds = 0.0

    def venue_name(self) -> str:
        return "kalshi"

    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        self.calls.append((outcome_id, resolution, limit))
        return self.responses.get(outcome_id, [])

    async def fetch_ohlcv_with_raw(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        candles = await self.fetch_ohlcv(outcome_id, resolution=resolution, limit=limit)
        return candles, [candle.model_dump(mode="json") for candle in candles]

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

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        raise NotImplementedError(f"book polling not implemented in test adapter: {outcome_id}")

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

    async def fetch_order_book_with_raw(
        self,
        outcome_id: str,
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        raise NotImplementedError(f"book polling not implemented in test adapter: {outcome_id}")


def test_ohlcv_poller_polls_outcomes_with_resolution() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    adapter.responses = {
        "kalshi:market-a:yes": [_candle(ts, "5m")],
        "kalshi:market-b:yes": [_candle(ts + timedelta(minutes=5), "5m")],
    }
    poller = connector_ohlcv_poller.OHLCVPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes", "kalshi:market-b:yes"],
        options=connector_ohlcv_poller.OHLCVPollerOptions(
            resolution="5m",
            limit_per_poll=55,
        ),
    )

    events = asyncio.run(poller.poll_once()).events

    assert len(events) == 2
    assert adapter.calls[0][1] == "5m"
    assert adapter.calls[0][2] == 55


def test_ohlcv_poller_handles_missing_data() -> None:
    adapter = _MockAdapter()
    poller = connector_ohlcv_poller.OHLCVPoller(adapter, outcome_ids=["kalshi:market-a:yes"])

    events = asyncio.run(poller.poll_once()).events

    assert events == []


def test_ohlcv_poller_deduplicates_outcomes_and_filters_old_candles() -> None:
    adapter = _MockAdapter()
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    candles = [_candle(ts, "1h"), _candle(ts + timedelta(hours=1), "1h")]
    adapter.responses = {"kalshi:market-a:yes": candles}
    poller = connector_ohlcv_poller.OHLCVPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes", "kalshi:market-a:yes"],
    )

    first = asyncio.run(poller.poll_once()).events
    second = asyncio.run(poller.poll_once()).events

    assert len(first) == 2
    assert second == []
    assert [call[0] for call in adapter.calls] == ["kalshi:market-a:yes", "kalshi:market-a:yes"]


def test_ohlcv_filter_new_candles_drops_misaligned_raw_payloads() -> None:
    adapter = _MockAdapter()
    poller = connector_ohlcv_poller.OHLCVPoller(adapter, outcome_ids=["kalshi:market-a:yes"])
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    candles = [_candle(ts), _candle(ts + timedelta(hours=1))]
    raw_payloads: list[dict[str, object]] = [{"row": 1}]

    filtered_candles, filtered_raw_payloads = poller._filter_new_candles(
        candles,
        raw_payloads,
        last_seen_ts=None,
    )

    assert len(filtered_candles) == 2
    assert filtered_raw_payloads == []


def test_ohlcv_poller_marks_timeouts_as_rejections() -> None:
    adapter = _MockAdapter()
    adapter.delay_seconds = 0.05
    poller = connector_ohlcv_poller.OHLCVPoller(
        adapter,
        outcome_ids=["kalshi:market-a:yes"],
        options=connector_ohlcv_poller.OHLCVPollerOptions(request_timeout_seconds=0.01),
    )

    batch = asyncio.run(poller.poll_once())

    assert batch.events == []
    assert poller.metrics().events_rejected == 1
    assert "timed out" in poller.metrics().errors[0]


def test_ohlcv_poller_rejects_invalid_limit() -> None:
    adapter = _MockAdapter()

    try:
        connector_ohlcv_poller.OHLCVPoller(
            adapter,
            outcome_ids=["x"],
            options=connector_ohlcv_poller.OHLCVPollerOptions(limit_per_poll=0),
        )
        raise AssertionError("Expected ValueError for invalid limit")
    except ValueError:
        pass
