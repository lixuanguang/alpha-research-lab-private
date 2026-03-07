"""Market metadata refresh polling connector."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.instruments.master as instrument_master
import alpha_core.instruments.models as instrument_models
import alpha_core.instruments.symbology as instrument_symbology
import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors._types as connector_types
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads


class MarketRefreshPoller(connector_polling.PollingConnector):
    """Periodically fetches all markets and updates the MarketMaster."""

    def __init__(
        self,
        adapter: adapters_base.VenueAdapter,
        master: instrument_master.MarketMaster,
        snapshot_path: Path | None = None,
        interval_seconds: float = 300.0,
        request_timeout_seconds: float | None = 10.0,
    ) -> None:
        self._adapter = adapter
        self._master = master
        self._snapshot_path = snapshot_path
        super().__init__(
            venue=adapter.venue_name(),
            interval_seconds=interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )

    def event_types(self) -> list[str]:
        return ["metadata"]

    async def poll_once(self) -> connector_types.PollingBatch:
        markets, raw_payloads = await self._await_with_timeout(
            self._adapter.fetch_markets_with_raw(),
            operation="fetch_markets",
        )
        normalized_raw_payloads = connector_raw_payloads.normalize_raw_payloads(
            raw_payloads,
            outcome_id="market_metadata",
        )
        metadata_events: list[event_models.CanonicalMarketEvent] = []

        for market in markets:
            canonical_market_id = instrument_symbology.make_canonical_market_id(
                market.venue,
                market.market_id,
            )
            previous_market = self._master.get_market(canonical_market_id)
            self._master.register_market(market)

            if previous_market is None:
                metadata_events.append(
                    self._build_metadata_event(
                        canonical_market_id,
                        fields_changed={"status": "new_market"},
                    )
                )
                continue

            fields_changed = _market_fields_diff(previous_market, market)
            if fields_changed:
                metadata_events.append(
                    self._build_metadata_event(canonical_market_id, fields_changed=fields_changed)
                )

        if self._snapshot_path is not None:
            self._master.persist(self._snapshot_path)

        return connector_types.PollingBatch(
            events=metadata_events,
            raw_payloads=({"metadata": normalized_raw_payloads} if normalized_raw_payloads else {}),
        )

    def _build_metadata_event(
        self,
        instrument_id: str,
        *,
        fields_changed: dict[str, Any],
    ) -> event_models.CanonicalMetadataUpdate:
        now = datetime.now(tz=UTC)
        return event_models.CanonicalMetadataUpdate.model_validate(
            {
                "instrument_id": instrument_id,
                "venue_id": self.venue,
                "ts_event": now,
                "ts_record": now,
                "fields_changed": fields_changed,
            }
        )


def _market_fields_diff(
    previous: instrument_models.MarketSpec,
    current: instrument_models.MarketSpec,
) -> dict[str, Any]:
    previous_payload = previous.model_dump(mode="json", exclude={"first_seen", "last_updated"})
    current_payload = current.model_dump(mode="json", exclude={"first_seen", "last_updated"})
    if previous_payload == current_payload:
        return {}
    return {
        "previous": previous_payload,
        "current": current_payload,
    }
