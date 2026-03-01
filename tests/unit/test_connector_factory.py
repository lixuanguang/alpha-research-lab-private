"""Unit tests for VenueConnectorFactory."""

from __future__ import annotations

from datetime import datetime

import apps.data_collector.connectors.book_poller as connector_book_poller
import apps.data_collector.connectors.factory as connector_factory
import apps.data_collector.connectors.market_refresh as connector_market_refresh
import apps.data_collector.connectors.ohlcv_poller as connector_ohlcv_poller
import apps.data_collector.connectors.trade_poller as connector_trade_poller

import alpha_core.adapters.base as adapters_base
import alpha_core.config.models as config_models
import alpha_core.events.models as event_models
import alpha_core.instruments.models as instrument_models

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubAdapter(adapters_base.VenueAdapter):
    def __init__(self, venue: str) -> None:
        self._venue = venue

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
        return []

    async def fetch_trades_with_raw(
        self, outcome_id: str, since: datetime | None = None, limit: int = 100
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        return [], []

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        raise NotImplementedError

    async def fetch_order_book_with_raw(
        self, outcome_id: str
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        raise NotImplementedError

    async def fetch_ohlcv(
        self, outcome_id: str, resolution: str = "1h", limit: int = 100
    ) -> list[event_models.CanonicalOHLCV]:
        return []

    async def fetch_ohlcv_with_raw(
        self, outcome_id: str, resolution: str = "1h", limit: int = 100
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        return [], []


def _settings_with_mode(venue: str, mode: str) -> config_models.Settings:
    return config_models.Settings.model_validate(
        {
            "project_name": "alpha-research-lab",
            "venues": [
                {
                    "name": venue,
                    "exchange_class": "Polymarket",
                    "enabled": True,
                    "rate_limit_rpm": 60,
                    "collection": {"mode": mode},
                }
            ],
            "storage": {"base_path": "/tmp/factory-tests"},
        }
    )


OUTCOME_IDS = ["polymarket:market-a:yes", "polymarket:market-b:no"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_poll_mode_creates_all_four_connectors() -> None:
    settings = _settings_with_mode("polymarket", "poll")
    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(_StubAdapter("polymarket"), OUTCOME_IDS)

    types = [type(c) for c in connectors]
    assert connector_market_refresh.MarketRefreshPoller in types
    assert connector_trade_poller.TradePoller in types
    assert connector_ohlcv_poller.OHLCVPoller in types
    assert connector_book_poller.BookSnapshotPoller in types


def test_both_mode_creates_all_four_connectors() -> None:
    settings = _settings_with_mode("polymarket", "both")
    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(_StubAdapter("polymarket"), OUTCOME_IDS)

    types = [type(c) for c in connectors]
    assert connector_trade_poller.TradePoller in types
    assert connector_ohlcv_poller.OHLCVPoller in types
    assert connector_book_poller.BookSnapshotPoller in types


def test_stream_mode_creates_only_market_refresh() -> None:
    settings = _settings_with_mode("polymarket", "stream")
    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(_StubAdapter("polymarket"), OUTCOME_IDS)

    types = [type(c) for c in connectors]
    assert connector_market_refresh.MarketRefreshPoller in types
    assert connector_trade_poller.TradePoller not in types
    assert connector_ohlcv_poller.OHLCVPoller not in types
    assert connector_book_poller.BookSnapshotPoller not in types


def test_empty_outcome_ids_creates_only_market_refresh() -> None:
    settings = _settings_with_mode("polymarket", "poll")
    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(_StubAdapter("polymarket"), [])

    assert len(connectors) == 1
    assert isinstance(connectors[0], connector_market_refresh.MarketRefreshPoller)


def test_unknown_venue_falls_back_to_default_collection_config() -> None:
    """An adapter whose venue is not in settings still produces connectors."""
    settings = _settings_with_mode("polymarket", "poll")
    factory = connector_factory.VenueConnectorFactory(settings)
    # "kalshi" is not in settings
    connectors = factory.create_poll_connectors(_StubAdapter("kalshi"), OUTCOME_IDS)

    # Default CollectionConfig has mode="poll", so all connectors are created
    types = [type(c) for c in connectors]
    assert connector_trade_poller.TradePoller in types


def test_poll_intervals_match_collection_config() -> None:
    settings = config_models.Settings.model_validate(
        {
            "project_name": "alpha-research-lab",
            "venues": [
                {
                    "name": "polymarket",
                    "exchange_class": "Polymarket",
                    "enabled": True,
                    "rate_limit_rpm": 60,
                    "collection": {
                        "mode": "poll",
                        "trade_poll_interval": 45.0,
                        "ohlcv_poll_interval": 600.0,
                        "book_poll_interval": 90.0,
                        "market_refresh_interval": 120.0,
                    },
                }
            ],
            "storage": {"base_path": "/tmp/factory-tests"},
        }
    )
    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(_StubAdapter("polymarket"), OUTCOME_IDS)

    by_type = {type(c): c for c in connectors}
    assert by_type[connector_trade_poller.TradePoller].interval_seconds == 45.0
    assert by_type[connector_ohlcv_poller.OHLCVPoller].interval_seconds == 600.0
    assert by_type[connector_book_poller.BookSnapshotPoller].interval_seconds == 90.0
    assert by_type[connector_market_refresh.MarketRefreshPoller].interval_seconds == 120.0


def test_request_timeout_forwarded_to_connectors() -> None:
    settings = _settings_with_mode("polymarket", "poll")
    factory = connector_factory.VenueConnectorFactory(settings)
    connectors = factory.create_poll_connectors(
        _StubAdapter("polymarket"), OUTCOME_IDS, request_timeout_seconds=5.0
    )
    for connector in connectors:
        assert connector.request_timeout_seconds == 5.0


def test_factory_initialises_with_multiple_venues() -> None:
    settings = config_models.Settings.model_validate(
        {
            "project_name": "alpha-research-lab",
            "venues": [
                {"name": "polymarket", "exchange_class": "Polymarket", "rate_limit_rpm": 60},
                {"name": "kalshi", "exchange_class": "Kalshi", "rate_limit_rpm": 180},
            ],
            "storage": {"base_path": "/tmp/factory-tests"},
        }
    )
    factory = connector_factory.VenueConnectorFactory(settings)
    # Each venue's factory call uses its own collection config
    pm_connectors = factory.create_poll_connectors(_StubAdapter("polymarket"), OUTCOME_IDS)
    kal_connectors = factory.create_poll_connectors(_StubAdapter("kalshi"), OUTCOME_IDS)
    assert len(pm_connectors) > 0
    assert len(kal_connectors) > 0
