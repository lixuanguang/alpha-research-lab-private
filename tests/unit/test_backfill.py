"""Unit tests for BackfillManager and BackfillResult."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import apps.data_collector.backfill as collector_backfill
import pytest

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.instruments.models as instrument_models
import alpha_core.quality.gap_detector as quality_gap_detector
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.utils.ids as ids_utils

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trade(trade_id: str, ts_event: datetime) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": "polymarket:market-a:yes",
        "venue_id": "polymarket",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=50),
        "schema_version": 1,
        "price": Decimal("0.55"),
        "size": Decimal("10"),
        "side": event_models.TradeSide.BUY,
        "trade_id": trade_id,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


def _candle(ts_event: datetime) -> event_models.CanonicalOHLCV:
    payload: dict[str, object] = {
        "instrument_id": "polymarket:market-a:yes",
        "venue_id": "polymarket",
        "event_type": event_models.EventType.OHLCV,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(seconds=1),
        "schema_version": 1,
        "open": Decimal("0.50"),
        "high": Decimal("0.60"),
        "low": Decimal("0.45"),
        "close": Decimal("0.55"),
        "volume": Decimal("100"),
        "resolution": "1h",
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalOHLCV.model_validate(payload)


class _MockAdapter(adapters_base.VenueAdapter):
    """Programmatic mock that returns pre-configured responses."""

    def __init__(self, venue: str = "polymarket") -> None:
        self._venue = venue
        self.trade_pages: dict[str, list[list[event_models.CanonicalTrade]]] = {}
        self.ohlcv_responses: dict[str, list[event_models.CanonicalOHLCV]] = {}
        self.fetch_trades_calls: list[tuple[str, object, int]] = []
        self.fetch_ohlcv_calls: list[tuple[str, str, int]] = []

    def venue_name(self) -> str:
        return self._venue

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return []

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        return [], []

    async def fetch_trades(
        self, outcome_id: str, since: datetime | None = None, limit: int = 100
    ) -> list[event_models.CanonicalTrade]:
        pages = self.trade_pages.get(outcome_id, [])
        if not pages:
            return []
        # Pop and return next page
        return pages.pop(0)

    async def fetch_trades_with_raw(
        self, outcome_id: str, since: datetime | None = None, limit: int = 100
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        self.fetch_trades_calls.append((outcome_id, since, limit))
        trades = await self.fetch_trades(outcome_id, since=since, limit=limit)
        return trades, [t.model_dump(mode="json") for t in trades]

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        raise NotImplementedError

    async def fetch_order_book_with_raw(
        self, outcome_id: str
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        raise NotImplementedError

    async def fetch_ohlcv(
        self, outcome_id: str, resolution: str = "1h", limit: int = 100
    ) -> list[event_models.CanonicalOHLCV]:
        return self.ohlcv_responses.get(outcome_id, [])

    async def fetch_ohlcv_with_raw(
        self, outcome_id: str, resolution: str = "1h", limit: int = 100
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        self.fetch_ohlcv_calls.append((outcome_id, resolution, limit))
        candles = await self.fetch_ohlcv(outcome_id, resolution=resolution, limit=limit)
        return candles, [c.model_dump(mode="json") for c in candles]


def _make_manager(
    adapter: _MockAdapter, tmp_path: Path
) -> collector_backfill.BackfillManager:
    return collector_backfill.BackfillManager(
        adapter=adapter,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )


START = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
END = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# BackfillResult model
# ---------------------------------------------------------------------------


def test_backfill_result_model_fields() -> None:
    result = collector_backfill.BackfillResult(
        venue="polymarket",
        event_type="trades",
        outcome_ids=["polymarket:market-a:yes"],
        window_start=START,
        window_end=END,
        events_fetched=10,
        events_stored=9,
        events_rejected=1,
        duration_seconds=1.23,
        run_id="run-abc",
    )
    assert result.events_fetched == 10
    assert result.events_rejected == 1


# ---------------------------------------------------------------------------
# backfill_trades
# ---------------------------------------------------------------------------


def test_backfill_trades_single_page_stores_silver(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    outcome_id = "polymarket:market-a:yes"
    trades = [_trade(f"t{i}", START + timedelta(minutes=i)) for i in range(5)]
    adapter.trade_pages[outcome_id] = [trades]

    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_trades([outcome_id], start=START, end=END)
    )

    assert result.events_fetched == 5
    assert result.events_stored == 5
    assert result.events_rejected == 0
    silver_files = list((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert silver_files


def test_backfill_trades_paginates_until_window_end(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    outcome_id = "polymarket:market-a:yes"
    # Page 1: 3 trades in window ; Page 2: 3 trades, last one past end
    page1 = [_trade(f"t{i}", START + timedelta(minutes=i * 10)) for i in range(3)]
    page2 = [_trade(f"t{i+3}", START + timedelta(hours=i + 1)) for i in range(3)]
    adapter.trade_pages[outcome_id] = [page1, page2]

    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_trades([outcome_id], start=START, end=END, batch_size=3)
    )

    assert result.events_fetched >= 3


def test_backfill_trades_empty_response_returns_zero_counts(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_trades(["polymarket:x:yes"], start=START, end=END)
    )
    assert result.events_fetched == 0
    assert result.events_stored == 0


def test_backfill_trades_multiple_outcome_ids(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    oid_a = "polymarket:market-a:yes"
    oid_b = "polymarket:market-b:yes"
    adapter.trade_pages[oid_a] = [[_trade("ta1", START + timedelta(minutes=1))]]
    adapter.trade_pages[oid_b] = [[_trade("tb1", START + timedelta(minutes=2))]]

    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_trades([oid_a, oid_b], start=START, end=END)
    )
    assert result.events_fetched == 2
    assert result.events_stored == 2


def test_backfill_trades_invalid_window_raises(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    manager = _make_manager(adapter, tmp_path)
    with pytest.raises(ValueError, match=r"end.*after.*start"):
        asyncio.run(
            manager.backfill_trades(
                ["polymarket:x:yes"], start=END, end=START
            )
        )


def test_backfill_trades_invalid_batch_size_raises(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    manager = _make_manager(adapter, tmp_path)
    with pytest.raises(ValueError, match="batch_size"):
        asyncio.run(
            manager.backfill_trades(["polymarket:x:yes"], start=START, end=END, batch_size=0)
        )


def test_backfill_trades_records_lineage_run(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    outcome_id = "polymarket:market-a:yes"
    adapter.trade_pages[outcome_id] = [[_trade("t1", START + timedelta(minutes=5))]]

    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_trades([outcome_id], start=START, end=END)
    )

    store = storage_lineage.LineageStore(tmp_path)
    run = store.get_run(result.run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.venue == "polymarket"


# ---------------------------------------------------------------------------
# backfill_ohlcv
# ---------------------------------------------------------------------------


def test_backfill_ohlcv_stores_candles_in_window(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    outcome_id = "polymarket:market-a:yes"
    candles_in = [_candle(START + timedelta(hours=i)) for i in range(2)]
    candle_out = _candle(END + timedelta(hours=1))  # outside window
    adapter.ohlcv_responses[outcome_id] = [*candles_in, candle_out]

    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_ohlcv([outcome_id], resolution="1h", start=START, end=END)
    )
    assert result.events_fetched == 2
    assert result.events_stored == 2


def test_backfill_ohlcv_invalid_resolution_raises(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    manager = _make_manager(adapter, tmp_path)
    with pytest.raises(ValueError, match="resolution"):
        asyncio.run(
            manager.backfill_ohlcv(["polymarket:x:yes"], resolution="2h", start=START, end=END)
        )


def test_backfill_ohlcv_limit_calculation_applies_resolution(tmp_path: Path) -> None:
    """Verify the limit passed to the adapter grows with window size."""
    adapter = _MockAdapter()
    outcome_id = "polymarket:market-a:yes"
    adapter.ohlcv_responses[outcome_id] = []

    manager = _make_manager(adapter, tmp_path)
    # 2-hour window at 1h resolution → limit ≥ 2
    asyncio.run(manager.backfill_ohlcv([outcome_id], resolution="1h", start=START, end=END))

    assert adapter.fetch_ohlcv_calls
    _, _, limit = adapter.fetch_ohlcv_calls[0]
    assert limit >= 2


# ---------------------------------------------------------------------------
# fill_gaps
# ---------------------------------------------------------------------------


def test_fill_gaps_dispatches_to_backfill_trades(tmp_path: Path) -> None:
    adapter = _MockAdapter()
    outcome_id = "polymarket:market-a:yes"
    # No data — backfill returns 0 events
    gap = quality_gap_detector.TimeGap(
        venue="polymarket",
        outcome_id=outcome_id,
        gap_start=START,
        gap_end=END,
        duration_seconds=7200.0,
        event_type="trade",
    )
    manager = _make_manager(adapter, tmp_path)
    results = asyncio.run(manager.fill_gaps([gap]))

    assert len(results) == 1
    assert results[0].event_type == "trades"
