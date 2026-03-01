"""Unit tests for pmxt adapter mapping behavior."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import alpha_core.adapters.pmxt_adapter as pmxt_adapter
import alpha_core.config.models as config_models
import alpha_core.events.models as event_models


class _MockExchange:
    def __init__(self, *_: object, **__: object) -> None:
        self._markets: list[object] = []
        self._trades: list[object] = []
        self._book: object = {}
        self._ohlcv: list[object] = []

    def fetch_markets(self) -> list[object]:
        return self._markets

    def fetch_trades(self, *_: object, **__: object) -> list[object]:
        return self._trades

    def fetch_order_book(self, *_: object, **__: object) -> object:
        return self._book

    def fetch_ohlcv(self, *_: object, **__: object) -> list[object]:
        return self._ohlcv


class _AsyncMockExchange(_MockExchange):
    async def fetch_markets(self) -> list[object]:
        return super().fetch_markets()

    async def fetch_trades(self, *args: object, **kwargs: object) -> list[object]:
        return super().fetch_trades(*args, **kwargs)

    async def fetch_order_book(self, *args: object, **kwargs: object) -> object:
        return super().fetch_order_book(*args, **kwargs)

    async def fetch_ohlcv(self, *args: object, **kwargs: object) -> list[object]:
        return super().fetch_ohlcv(*args, **kwargs)


def _install_mock_pmxt(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_module = SimpleNamespace(
        Kalshi=_MockExchange,
        KalshiDemo=_MockExchange,
        Polymarket=_MockExchange,
        Limitless=_MockExchange,
        Baozi=_MockExchange,
        Myriad=_MockExchange,
        Probable=_MockExchange,
    )
    monkeypatch.setattr(pmxt_adapter, "pmxt_module", mock_module)


def _install_async_mock_pmxt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pmxt_adapter, "pmxt_module", SimpleNamespace(Kalshi=_AsyncMockExchange))


def _config(name: str, exchange_class: str) -> config_models.VenueConfig:
    return config_models.VenueConfig(
        name=name,
        exchange_class=exchange_class,
        enabled=True,
        api_key_env=None,
        private_key_env=None,
        rate_limit_rpm=120,
    )


@pytest.mark.parametrize(
    ("venue_name", "exchange_class"),
    [
        ("kalshi", "Kalshi"),
        ("kalshidemo", "KalshiDemo"),
        ("polymarket", "Polymarket"),
        ("limitless", "Limitless"),
        ("baozi", "Baozi"),
        ("myriad", "Myriad"),
        ("probable", "Probable"),
    ],
)
def test_all_venues_are_instantiable_with_mock_exchange(
    monkeypatch: pytest.MonkeyPatch,
    venue_name: str,
    exchange_class: str,
) -> None:
    _install_mock_pmxt(monkeypatch)

    adapter = pmxt_adapter.PmxtAdapter(venue_name, _config(venue_name, exchange_class))

    assert adapter.venue_name() == venue_name


def test_exchange_class_mismatch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)

    with pytest.raises(ValueError, match="Config exchange class mismatch"):
        pmxt_adapter.PmxtAdapter("polymarket", _config("polymarket", "Kalshi"))


def test_fetch_markets_maps_vendor_payload_to_market_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("polymarket", _config("polymarket", "Polymarket"))

    exchange = _exchange(adapter)
    exchange._markets = [
        {
            "id": "us-pres-2028",
            "title": "Who wins 2028 election?",
            "description": "US election winner",
            "category": "politics",
            "tags": ["us", "election"],
            "outcomes": [
                {"id": "yes", "label": "Yes"},
                {"id": "no", "label": "No"},
            ],
            "status": "active",
            "volume": "1000.5",
            "liquidity": "900.1",
            "url": "https://example.com/markets/us-pres-2028",
            "resolution_date": "2028-11-08T00:00:00Z",
        }
    ]

    markets = asyncio.run(adapter.fetch_markets())

    assert len(markets) == 1
    assert markets[0].market_id == "us-pres-2028"
    assert markets[0].venue == "polymarket"
    assert markets[0].outcomes[0].canonical_id == "polymarket:us-pres-2028:yes"


def test_fetch_markets_handles_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))

    markets = asyncio.run(adapter.fetch_markets())

    assert markets == []


def test_fetch_markets_handles_missing_fields_with_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("myriad", _config("myriad", "Myriad"))
    exchange = _exchange(adapter)
    exchange._markets = [{"id": "market-1"}]

    markets = asyncio.run(adapter.fetch_markets())

    assert len(markets) == 1
    assert markets[0].title == "market-1"
    assert markets[0].outcomes[0].outcome_id == "outcome-0"


def test_fetch_trades_rejects_ambiguous_non_canonical_outcome_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    exchange._markets = [
        {
            "id": "market-a",
            "outcomes": [{"id": "yes", "label": "Yes"}],
        },
        {
            "id": "market-b",
            "outcomes": [{"id": "yes", "label": "Yes"}],
        },
    ]

    asyncio.run(adapter.fetch_markets())

    with pytest.raises(ValueError, match="Ambiguous non-canonical `outcome_id`"):
        asyncio.run(adapter.fetch_trades("yes"))


def test_fetch_trades_skips_null_price_trades(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("polymarket", _config("polymarket", "Polymarket"))
    exchange = _exchange(adapter)
    exchange._trades = [
        {
            "id": "trade-1",
            "timestamp": "2026-02-28T10:00:00Z",
            "price": None,
            "size": "10",
            "side": "buy",
        },
        {
            "id": "trade-2",
            "timestamp": "2026-02-28T10:00:01Z",
            "price": "0.61",
            "size": "3",
            "side": "sell",
        },
    ]

    with caplog.at_level(logging.WARNING):
        trades = asyncio.run(adapter.fetch_trades("polymarket:us-pres-2028:yes"))

    assert [trade.trade_id for trade in trades] == ["trade-2"]
    assert trades[0].price == Decimal("0.61")
    assert adapter.rejection_counters()["trades.invalid_payload"] == 1
    assert any("scope=trades" in record.getMessage() for record in caplog.records)


def test_trade_timestamp_mapping_uses_venue_time_and_record_time_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    expected_ts_event = datetime.now(tz=UTC).replace(microsecond=0)
    exchange._trades = [
        {
            "id": "trade-10",
            "timestamp": expected_ts_event.isoformat().replace("+00:00", "Z"),
            "price": "0.42",
            "size": "5",
            "side": "buy",
        }
    ]

    before = datetime.now(tz=UTC)
    trades = asyncio.run(adapter.fetch_trades("kalshi:market-x:yes"))
    after = datetime.now(tz=UTC)

    assert len(trades) == 1
    assert trades[0].ts_event == expected_ts_event
    assert before <= trades[0].ts_record <= after
    assert trades[0].ts_record >= trades[0].ts_event


def test_fetch_order_book_maps_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("limitless", _config("limitless", "Limitless"))
    exchange = _exchange(adapter)
    exchange._book = {
        "timestamp": "2026-02-28T09:00:00Z",
        "bids": [["0.49", "200"]],
        "asks": [{"price": "0.51", "size": "180"}],
    }

    book = asyncio.run(adapter.fetch_order_book("limitless:market-a:yes"))

    assert book.event_type == event_models.EventType.BOOK_SNAPSHOT
    assert book.bids[0].price == Decimal("0.49")
    assert book.asks[0].size == Decimal("180")


def test_fetch_order_book_skips_invalid_levels(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("polymarket", _config("polymarket", "Polymarket"))
    exchange = _exchange(adapter)
    exchange._book = {
        "timestamp": "2026-02-28T09:00:00Z",
        "bids": [["bad-price", "200"], ["0.48", "-10"], ["0.47", "20"]],
        "asks": [{"price": "0.53", "size": "50"}, {"price": None, "size": "10"}],
    }

    with caplog.at_level(logging.WARNING):
        book = asyncio.run(adapter.fetch_order_book("polymarket:market-a:yes"))

    assert [level.price for level in book.bids] == [Decimal("0.47")]
    assert [level.size for level in book.asks] == [Decimal("50")]
    counters = adapter.rejection_counters()
    assert counters["book.bids_invalid_level"] == 2
    assert counters["book.asks_invalid_level"] == 1
    assert any("scope=book" in record.getMessage() for record in caplog.records)
    assert any(
        "details={'asks_invalid_level': 1, 'bids_invalid_level': 2}" in record.getMessage()
        for record in caplog.records
    )


def test_fetch_order_book_handles_out_of_range_numeric_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("polymarket", _config("polymarket", "Polymarket"))
    exchange = _exchange(adapter)
    exchange._book = {
        "timestamp": 10**20,
        "bids": [["0.48", "20"]],
        "asks": [["0.52", "20"]],
    }

    book = asyncio.run(adapter.fetch_order_book("polymarket:market-a:yes"))

    assert book.ts_event == book.ts_record


def test_fetch_order_book_raises_on_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("polymarket", _config("polymarket", "Polymarket"))
    exchange = _exchange(adapter)
    exchange._book = {
        "timestamp": "2026-02-28T09:00:00Z",
        "bids": [["1.50", "20"]],
        "asks": [],
    }

    with pytest.raises(ValueError, match="Invalid order book payload"):
        asyncio.run(adapter.fetch_order_book("polymarket:market-a:yes"))
    assert adapter.rejection_counters()["book.invalid_payload"] == 1


def test_fetch_trades_skips_invalid_side_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    exchange._trades = [
        {
            "id": "trade-invalid",
            "timestamp": "2026-02-28T10:00:00Z",
            "price": "0.55",
            "size": "8",
            "side": "hold",
        },
        {
            "id": "trade-valid",
            "timestamp": "2026-02-28T10:00:01Z",
            "price": "0.56",
            "size": "2",
            "side": "buy",
        },
    ]

    trades = asyncio.run(adapter.fetch_trades("kalshi:market-a:yes"))

    assert [trade.trade_id for trade in trades] == ["trade-valid"]


def test_fetch_ohlcv_maps_vendor_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("myriad", _config("myriad", "Myriad"))
    exchange = _exchange(adapter)
    exchange._ohlcv = [["2026-02-28T10:00:00Z", "0.40", "0.62", "0.39", "0.51", "100"]]

    candles = asyncio.run(adapter.fetch_ohlcv("myriad:market-a:yes", resolution="1m"))

    assert len(candles) == 1
    assert candles[0].event_type == event_models.EventType.OHLCV
    assert candles[0].open == Decimal("0.40")
    assert candles[0].high == Decimal("0.62")
    assert candles[0].resolution == "1m"


def test_fetch_ohlcv_tracks_invalid_rows(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("myriad", _config("myriad", "Myriad"))
    exchange = _exchange(adapter)
    exchange._ohlcv = [
        ["2026-02-28T10:00:00Z", "0.40"],
        ["2026-02-28T10:00:00Z", "0.40", "0.62", "0.39", "0.51", "100"],
    ]

    with caplog.at_level(logging.WARNING):
        candles = asyncio.run(adapter.fetch_ohlcv("myriad:market-a:yes", resolution="1m"))

    assert len(candles) == 1
    assert adapter.rejection_counters()["ohlcv.invalid_payload"] == 1
    assert any("scope=ohlcv" in record.getMessage() for record in caplog.records)


def test_fetch_ohlcv_handles_out_of_range_numeric_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("myriad", _config("myriad", "Myriad"))
    exchange = _exchange(adapter)
    exchange._ohlcv = [[10**20, "0.40", "0.62", "0.39", "0.51", "100"]]

    candles = asyncio.run(adapter.fetch_ohlcv("myriad:market-a:yes", resolution="1m"))

    assert len(candles) == 1
    assert candles[0].ts_event == candles[0].ts_record


def test_fetch_markets_tracks_invalid_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    exchange._markets = [{"id": ""}, {"id": "market-ok"}]

    markets = asyncio.run(adapter.fetch_markets())

    assert len(markets) == 1
    assert adapter.rejection_counters()["markets.invalid_payload"] == 1


def test_rejection_counters_can_be_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    exchange._trades = [{"id": "x", "timestamp": "2026-02-28T10:00:00Z", "price": None, "size": 1}]

    asyncio.run(adapter.fetch_trades("kalshi:market-a:yes"))
    assert adapter.rejection_counters()["trades.invalid_payload"] == 1

    adapter.reset_rejection_counters()
    assert adapter.rejection_counters() == {}


def test_fetch_ohlcv_normalizes_unknown_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("baozi", _config("baozi", "Baozi"))
    exchange = _exchange(adapter)
    exchange._ohlcv = [["2026-02-28T10:00:00Z", "0.10", "0.20", "0.09", "0.15", "5"]]

    candles = asyncio.run(adapter.fetch_ohlcv("baozi:market-a:yes", resolution="2h"))

    assert len(candles) == 1
    assert candles[0].resolution == "1h"


def test_fetch_trades_normalizes_scaled_prices_when_price_scale_is_gt_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    exchange._trades = [
        {
            "id": "trade-1",
            "timestamp": "2026-02-28T10:00:00Z",
            "price": "65",
            "size": "10",
            "side": "buy",
        }
    ]

    adapter._quirks = type(
        "Quirks",
        (),
        {"price_scale": Decimal("100"), "side_aliases": {"buy": "buy", "sell": "sell"}},
    )()

    trades = asyncio.run(adapter.fetch_trades("kalshi:market-a:yes"))

    assert [trade.price for trade in trades] == [Decimal("0.65")]


def test_adapter_awaits_async_exchange_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_async_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    exchange._markets = [
        {
            "id": "market-a",
            "outcomes": [{"id": "yes", "label": "Yes"}],
        }
    ]
    exchange._trades = [
        {
            "id": "trade-1",
            "timestamp": "2026-02-28T10:00:00Z",
            "price": "0.55",
            "size": "10",
            "side": "buy",
        }
    ]
    exchange._book = {"timestamp": "2026-02-28T10:00:00Z", "bids": [["0.54", "1"]], "asks": []}
    exchange._ohlcv = [["2026-02-28T10:00:00Z", "0.5", "0.6", "0.4", "0.55", "1"]]

    markets = asyncio.run(adapter.fetch_markets())
    trades = asyncio.run(adapter.fetch_trades("kalshi:market-a:yes"))
    book = asyncio.run(adapter.fetch_order_book("kalshi:market-a:yes"))
    candles = asyncio.run(adapter.fetch_ohlcv("kalshi:market-a:yes"))

    assert len(markets) == 1
    assert len(trades) == 1
    assert len(book.bids) == 1
    assert len(candles) == 1


@pytest.mark.perf
def test_map_100_markets_under_200ms(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("polymarket", _config("polymarket", "Polymarket"))
    exchange = _exchange(adapter)
    exchange._markets = [
        {
            "id": f"market-{index}",
            "title": f"Synthetic market {index}",
            "outcomes": [
                {"id": "yes", "label": "Yes"},
                {"id": "no", "label": "No"},
            ],
            "status": "active",
        }
        for index in range(100)
    ]

    start = time.perf_counter()
    markets = asyncio.run(adapter.fetch_markets())
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(markets) == 100
    assert elapsed_ms < 200


@pytest.mark.perf
def test_map_1000_trades_under_100ms(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter("kalshi", _config("kalshi", "Kalshi"))
    exchange = _exchange(adapter)
    timestamp = datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    exchange._trades = [
        {
            "id": f"trade-{index}",
            "timestamp": timestamp,
            "price": "0.55",
            "size": "10",
            "side": "buy" if index % 2 == 0 else "sell",
        }
        for index in range(1000)
    ]

    start = time.perf_counter()
    trades = asyncio.run(adapter.fetch_trades("kalshi:synthetic-market:yes"))
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(trades) == 1000
    assert elapsed_ms < 100


def _exchange(adapter: pmxt_adapter.PmxtAdapter) -> _MockExchange:
    exchange = adapter._exchange
    if not isinstance(exchange, _MockExchange):
        raise TypeError("Unexpected exchange type")
    return exchange
