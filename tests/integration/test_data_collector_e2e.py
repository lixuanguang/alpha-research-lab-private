"""End-to-end integration smoke tests for the data collector."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import apps.data_collector.backfill as collector_backfill
import apps.data_collector.connectors.factory as connector_factory
import apps.data_collector.pipeline as collector_pipeline

import alpha_core.adapters.base as adapters_base
import alpha_core.config.models as config_models
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.instruments.models as instrument_models
import alpha_core.quality.gap_detector as gap_detector_mod
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_reader as parquet_reader_mod
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.utils.ids as ids_utils

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
OUTCOME_A = "polymarket:market-a:yes"
OUTCOME_B = "polymarket:market-b:no"


def _trade(trade_id: str, ts: datetime) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": OUTCOME_A,
        "venue_id": "polymarket",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts,
        "ts_record": ts + timedelta(milliseconds=50),
        "schema_version": 1,
        "price": Decimal("0.55"),
        "size": Decimal("10"),
        "side": event_models.TradeSide.BUY,
        "trade_id": trade_id,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


def _candle(ts: datetime) -> event_models.CanonicalOHLCV:
    payload: dict[str, object] = {
        "instrument_id": OUTCOME_A,
        "venue_id": "polymarket",
        "event_type": event_models.EventType.OHLCV,
        "ts_event": ts,
        "ts_record": ts + timedelta(seconds=1),
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


class _MockExchangeAdapter(adapters_base.VenueAdapter):
    """Full mock adapter returning configurable trade/OHLCV data."""

    def __init__(
        self,
        trades: list[event_models.CanonicalTrade] | None = None,
        candles: list[event_models.CanonicalOHLCV] | None = None,
    ) -> None:
        self._trades = trades or []
        self._candles = candles or []
        # Tracks how many times fetch_trades was called per outcome
        self.trades_call_count: dict[str, int] = {}

    def venue_name(self) -> str:
        return "polymarket"

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return []

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        return [], []

    async def fetch_trades(
        self, outcome_id: str, since: datetime | None = None, limit: int = 100
    ) -> list[event_models.CanonicalTrade]:
        count = self.trades_call_count.get(outcome_id, 0)
        self.trades_call_count[outcome_id] = count + 1
        # Return trades only on first call to simulate exhaustion
        if count == 0:
            return self._trades.copy()
        return []

    async def fetch_trades_with_raw(
        self, outcome_id: str, since: datetime | None = None, limit: int = 100
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
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
        return self._candles.copy()

    async def fetch_ohlcv_with_raw(
        self, outcome_id: str, resolution: str = "1h", limit: int = 100
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        candles = await self.fetch_ohlcv(outcome_id, resolution=resolution, limit=limit)
        return candles, [c.model_dump(mode="json") for c in candles]


def _settings(base_path: Path) -> config_models.Settings:
    return config_models.Settings.model_validate(
        {
            "project_name": "alpha-research-lab",
            "venues": [
                {
                    "name": "polymarket",
                    "exchange_class": "Polymarket",
                    "enabled": True,
                    "rate_limit_rpm": 60,
                    "collection": {"mode": "poll"},
                }
            ],
            "storage": {"base_path": str(base_path)},
        }
    )


def _make_manager(
    adapter: _MockExchangeAdapter, tmp_path: Path
) -> collector_backfill.BackfillManager:
    return collector_backfill.BackfillManager(
        adapter=adapter,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------


def test_poll_cycle_writes_bronze_and_silver(tmp_path: Path) -> None:
    """Full cycle: factory → connector → pipeline → bronze + silver files exist."""
    trades = [_trade(f"t{i}", NOW + timedelta(minutes=i)) for i in range(5)]
    adapter = _MockExchangeAdapter(trades=trades)
    settings = _settings(tmp_path)

    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(adapter, [OUTCOME_A])

    # Run the trade poller through a PollingPipeline
    trade_connector = next(
        c for c in connectors if hasattr(c, "_outcome_ids")
        and OUTCOME_A in getattr(c, "_outcome_ids", [])
        and "trade" in type(c).__name__.lower()
    )
    pipeline = collector_pipeline.PollingPipeline(
        connector=trade_connector,
        bronze_writer=storage_bronze.BronzeWriter(tmp_path),
        silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
        quality_checker=event_quality.EventQualityChecker(),
        lineage_store=storage_lineage.LineageStore(tmp_path),
    )
    run = asyncio.run(pipeline.execute())

    bronze_files = list((tmp_path / "bronze" / "trades").rglob("*.jsonl.gz"))
    silver_files = list((tmp_path / "silver" / "trades").rglob("*.parquet"))

    assert run.status == "completed"
    assert run.counts["events_raw"] == 5
    assert bronze_files
    assert silver_files


def test_backfill_produces_silver_data(tmp_path: Path) -> None:
    """BackfillManager.backfill_trades → silver Parquet file created."""
    start = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    end = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    trades = [_trade(f"t{i}", start + timedelta(minutes=i * 20)) for i in range(6)]
    adapter = _MockExchangeAdapter(trades=trades)

    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_trades([OUTCOME_A], start=start, end=end)
    )

    silver_files = list((tmp_path / "silver" / "trades").rglob("*.parquet"))
    assert result.events_stored == 6
    assert silver_files


def test_backfill_ohlcv_produces_silver_data(tmp_path: Path) -> None:
    """BackfillManager.backfill_ohlcv → silver OHLCV Parquet file created."""
    start = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 1, 4, 0, tzinfo=UTC)
    candles = [_candle(start + timedelta(hours=i)) for i in range(4)]
    adapter = _MockExchangeAdapter(candles=candles)

    manager = _make_manager(adapter, tmp_path)
    result = asyncio.run(
        manager.backfill_ohlcv([OUTCOME_A], resolution="1h", start=start, end=end)
    )

    silver_files = list((tmp_path / "silver" / "ohlcv").rglob("*.parquet"))
    assert result.events_stored == 4
    assert silver_files


def test_gap_detection_after_partial_backfill(tmp_path: Path) -> None:
    """Write partial data → detect gap in the middle of the window."""
    start = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
    # Trades only at hour 0 and hour 5 — large gap in the middle
    trades = [
        _trade("e", start),
        _trade("f", start + timedelta(hours=5)),
    ]
    adapter = _MockExchangeAdapter(trades=trades)
    manager = _make_manager(adapter, tmp_path)
    asyncio.run(manager.backfill_trades([OUTCOME_A], start=start, end=end))

    reader = parquet_reader_mod.ParquetEventReader(tmp_path)
    detector = gap_detector_mod.GapDetector(reader)
    gaps = detector.detect_trade_gaps(
        "polymarket", OUTCOME_A, start=start, end=end, max_gap_seconds=3600.0
    )
    assert len(gaps) >= 1
    assert all(g.duration_seconds > 3600 for g in gaps)


def test_gap_detection_and_fill(tmp_path: Path) -> None:
    """Write partial data → detect gaps → backfill → gaps are resolved."""
    start = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
    midpoint = datetime(2026, 3, 1, 3, 0, tzinfo=UTC)
    end = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)

    # Initial partial data: only first hour
    initial_trades = [_trade(f"i{i}", start + timedelta(minutes=i * 10)) for i in range(6)]
    adapter1 = _MockExchangeAdapter(trades=initial_trades)
    manager1 = _make_manager(adapter1, tmp_path)
    asyncio.run(manager1.backfill_trades([OUTCOME_A], start=start, end=midpoint))

    # Detect the gap
    reader = parquet_reader_mod.ParquetEventReader(tmp_path)
    detector = gap_detector_mod.GapDetector(reader)
    gaps = detector.detect_trade_gaps(
        "polymarket", OUTCOME_A, start=start, end=end, max_gap_seconds=3600.0
    )
    assert len(gaps) >= 1

    # Fill the gap: second adapter provides trades in the gap window
    fill_trades = [_trade(f"f{i}", midpoint + timedelta(minutes=i * 20)) for i in range(9)]
    adapter2 = _MockExchangeAdapter(trades=fill_trades)
    manager2 = _make_manager(adapter2, tmp_path)
    fill_results = asyncio.run(manager2.fill_gaps(gaps))

    assert all(r.event_type == "trades" for r in fill_results)
    # After fill, combined silver data should have events across full window
    table = reader.read_trades(venue="polymarket", start=start, end=end)
    total_rows = table.num_rows
    assert total_rows == len(initial_trades) + len(fill_trades)


def test_factory_poll_mode_connector_count(tmp_path: Path) -> None:
    """VenueConnectorFactory in poll mode creates 4 connectors for non-empty outcomes."""
    adapter = _MockExchangeAdapter()
    settings = _settings(tmp_path)
    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(adapter, [OUTCOME_A, OUTCOME_B])
    # MarketRefresh + Trade + OHLCV + Book = 4
    assert len(connectors) == 4


def test_backfill_lineage_persisted_after_success(tmp_path: Path) -> None:
    """Completed backfill run is persisted in the lineage store."""
    start = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    end = datetime(2026, 3, 1, 11, 0, tzinfo=UTC)
    trades = [_trade("x1", start + timedelta(minutes=10))]
    adapter = _MockExchangeAdapter(trades=trades)
    manager = _make_manager(adapter, tmp_path)

    result = asyncio.run(manager.backfill_trades([OUTCOME_A], start=start, end=end))

    store = storage_lineage.LineageStore(tmp_path)
    run = store.get_run(result.run_id)
    assert run is not None
    assert run.status == "completed"
    assert "events_raw" in run.counts
