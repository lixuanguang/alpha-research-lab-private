"""Order book snapshot polling connector implementation."""

from __future__ import annotations

from typing import cast

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads


class BookSnapshotPoller(connector_base.PollingConnector):
    """Polls fetch_order_book for configured outcomes."""

    def __init__(
        self,
        adapter: adapters_base.VenueAdapter,
        *,
        outcome_ids: list[str],
        interval_seconds: float = 60.0,
        request_timeout_seconds: float | None = 10.0,
    ) -> None:
        self._adapter = adapter
        self._outcome_ids = connector_base.normalize_outcome_ids(outcome_ids)
        super().__init__(
            venue=adapter.venue_name(),
            interval_seconds=interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )

    def event_types(self) -> list[str]:
        return ["books"]

    async def poll_once(self) -> connector_base.PollingBatch:
        if not self._outcome_ids:
            return connector_base.PollingBatch(events=[], raw_payloads={})

        snapshots: list[event_models.CanonicalBookSnapshot] = []
        raw_payloads_accumulated: list[dict[str, object]] = []
        for outcome_id in self._outcome_ids:
            try:
                snapshot, raw_payload = await self._await_with_timeout(
                    self._adapter.fetch_order_book_with_raw(outcome_id),
                    operation=f"fetch_order_book[{outcome_id}]",
                )
            except Exception as exc:
                self._record_poll_failure(scope="book", outcome_id=outcome_id, error=exc)
                continue

            snapshots.append(snapshot)
            raw_payloads_accumulated.extend(
                connector_raw_payloads.normalize_raw_payloads(
                    [raw_payload],
                    outcome_id=outcome_id,
                )
            )

        snapshots.sort(key=lambda snapshot: (snapshot.ts_event, snapshot.instrument_id))
        return connector_base.PollingBatch(
            events=cast(list[event_models.CanonicalMarketEvent], snapshots),
            raw_payloads={"books": raw_payloads_accumulated} if raw_payloads_accumulated else {},
        )


__all__ = ["BookSnapshotPoller"]
