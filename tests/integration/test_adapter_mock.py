"""Integration tests for mock pmxt adapter flows."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import alpha_core.adapters.pmxt_adapter as pmxt_adapter
import alpha_core.config.models as config_models
import alpha_core.events.quality as event_quality


class _FlowExchange:
    def __init__(self, *_: object, **__: object) -> None:
        self._markets: list[object] = [
            {
                "id": "us-pres-2028",
                "title": "Who wins 2028 election?",
                "outcomes": [
                    {"id": "yes", "label": "Yes"},
                    {"id": "no", "label": "No"},
                ],
                "status": "active",
            }
        ]
        self._trades: list[object] = [
            {
                "id": "trade-1",
                "timestamp": "2026-02-28T12:00:00Z",
                "price": "0.64",
                "size": "25",
                "side": "buy",
            },
            {
                "id": "trade-2",
                "timestamp": "2026-02-28T12:00:01Z",
                "price": "0.65",
                "size": "10",
                "side": "sell",
            },
        ]
        self._book = {
            "timestamp": "2026-02-28T12:00:01Z",
            "bids": [["0.63", "120"]],
            "asks": [["0.66", "95"]],
        }
        self._ohlcv: list[object] = [
            ["2026-02-28T12:00:00Z", "0.62", "0.66", "0.61", "0.65", "200"]
        ]

    def fetch_markets(self) -> list[object]:
        return self._markets

    def fetch_trades(self, *_: object, **__: object) -> list[object]:
        return self._trades

    def fetch_order_book(self, *_: object, **__: object) -> object:
        return self._book

    def fetch_ohlcv(self, *_: object, **__: object) -> list[object]:
        return self._ohlcv


def _install_mock_pmxt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pmxt_adapter, "pmxt_module", SimpleNamespace(Polymarket=_FlowExchange))


def test_adapter_flow_produces_quality_valid_events(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_pmxt(monkeypatch)
    adapter = pmxt_adapter.PmxtAdapter(
        "polymarket",
        config_models.VenueConfig(name="polymarket", exchange_class="Polymarket"),
    )

    markets = asyncio.run(adapter.fetch_markets())
    trades = asyncio.run(adapter.fetch_trades("polymarket:us-pres-2028:yes"))
    book = asyncio.run(adapter.fetch_order_book("polymarket:us-pres-2028:yes"))
    ohlcv = asyncio.run(adapter.fetch_ohlcv("polymarket:us-pres-2028:yes", resolution="1h"))

    checker = event_quality.EventQualityChecker()
    reports = [checker.check(event) for event in [*trades, book, *ohlcv]]

    assert len(markets) == 1
    assert markets[0].outcomes[0].canonical_id == "polymarket:us-pres-2028:yes"
    assert all(report.is_valid for report in reports)
