"""Venue connector factory — creates the right connectors from config."""

from __future__ import annotations

import alpha_core.adapters.base as adapters_base
import alpha_core.config.models as config_models
import alpha_core.instruments.master as instrument_master
import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors.book_poller as connector_book_poller
import apps.data_collector.connectors.market_refresh as connector_market_refresh
import apps.data_collector.connectors.ohlcv_poller as connector_ohlcv_poller
import apps.data_collector.connectors.trade_poller as connector_trade_poller


class VenueConnectorFactory:
    """Creates the right set of polling connectors for a venue based on config."""

    def __init__(self, settings: config_models.Settings) -> None:
        self._venue_map: dict[str, config_models.VenueConfig] = {
            vc.name: vc for vc in settings.venues
        }

    def create_poll_connectors(
        self,
        adapter: adapters_base.VenueAdapter,
        outcome_ids: list[str],
        *,
        request_timeout_seconds: float = 10.0,
    ) -> list[connector_polling.PollingConnector]:
        """Create polling connectors for the given adapter based on venue config.

        Always includes a MarketRefreshPoller.  Additional trade/OHLCV/book
        pollers are created when ``outcome_ids`` is non-empty and the venue
        collection mode includes polling (``"poll"`` or ``"both"``).

        Args:
            adapter: Venue adapter whose ``venue_name()`` is used to look up
                the collection config.
            outcome_ids: Canonical outcome ids to subscribe to.
            request_timeout_seconds: Per-request timeout forwarded to connectors.

        Returns:
            Ordered list of connectors ready to be registered with a scheduler.
        """
        venue_name = adapter.venue_name()
        venue_config = self._venue_map.get(venue_name)
        collection = (
            venue_config.collection if venue_config else config_models.CollectionConfig()
        )
        market_master = instrument_master.MarketMaster()

        connectors: list[connector_polling.PollingConnector] = [
            connector_market_refresh.MarketRefreshPoller(
                adapter,
                market_master,
                interval_seconds=collection.market_refresh_interval,
                request_timeout_seconds=request_timeout_seconds,
            )
        ]

        if outcome_ids and collection.mode in ("poll", "both"):
            connectors.extend(
                [
                    connector_trade_poller.TradePoller(
                        adapter,
                        outcome_ids=outcome_ids,
                        interval_seconds=collection.trade_poll_interval,
                        request_timeout_seconds=request_timeout_seconds,
                    ),
                    connector_ohlcv_poller.OHLCVPoller(
                        adapter,
                        outcome_ids=outcome_ids,
                        interval_seconds=collection.ohlcv_poll_interval,
                        request_timeout_seconds=request_timeout_seconds,
                    ),
                    connector_book_poller.BookSnapshotPoller(
                        adapter,
                        outcome_ids=outcome_ids,
                        interval_seconds=collection.book_poll_interval,
                        request_timeout_seconds=request_timeout_seconds,
                    ),
                ]
            )

        return connectors


__all__ = ["VenueConnectorFactory"]
