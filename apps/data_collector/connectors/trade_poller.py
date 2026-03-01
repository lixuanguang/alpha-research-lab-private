"""Trade polling connector implementation."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import cast

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors._types as connector_types
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads


class TradePoller(connector_polling.PollingConnector):
    """Polls fetch_trades for configured outcomes at regular intervals."""

    def __init__(
        self,
        adapter: adapters_base.VenueAdapter,
        *,
        outcome_ids: list[str],
        interval_seconds: float = 30.0,
        request_timeout_seconds: float | None = 10.0,
        limit_per_poll: int = 100,
        max_seen_trade_ids: int = 100_000,
    ) -> None:
        if limit_per_poll <= 0:
            raise ValueError("`limit_per_poll` must be > 0")
        if max_seen_trade_ids <= 0:
            raise ValueError("`max_seen_trade_ids` must be > 0")
        self._adapter = adapter
        self._outcome_ids = connector_types.normalize_outcome_ids(outcome_ids)
        self._limit_per_poll = limit_per_poll
        self._max_seen_trade_ids = max_seen_trade_ids
        self._since_by_outcome: dict[str, datetime | None] = {
            outcome_id: None for outcome_id in self._outcome_ids
        }
        self._seen_trade_keys: set[tuple[str, str]] = set()
        self._seen_trade_order: deque[tuple[str, str]] = deque()
        super().__init__(
            venue=adapter.venue_name(),
            interval_seconds=interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )

    def event_types(self) -> list[str]:
        return ["trades"]

    async def poll_once(self) -> connector_types.PollingBatch:
        if not self._outcome_ids:
            return connector_types.PollingBatch(events=[], raw_payloads={})

        aggregated: list[event_models.CanonicalTrade] = []
        raw_payloads_accumulated: list[dict[str, object]] = []
        for outcome_id in self._outcome_ids:
            since = self._since_by_outcome.get(outcome_id)
            try:
                trades, raw_payloads = await self._await_with_timeout(
                    self._adapter.fetch_trades_with_raw(
                        outcome_id,
                        since=since,
                        limit=self._limit_per_poll,
                    ),
                    operation=f"fetch_trades[{outcome_id}]",
                )
            except Exception as exc:
                self._record_poll_failure(scope="trade", outcome_id=outcome_id, error=exc)
                continue

            raw_payloads_accumulated.extend(
                connector_raw_payloads.normalize_raw_payloads(
                    raw_payloads,
                    outcome_id=outcome_id,
                )
            )
            if trades:
                self._since_by_outcome[outcome_id] = max(trade.ts_event for trade in trades)

            for trade in trades:
                if not self._track_trade(trade):
                    continue
                aggregated.append(trade)

        aggregated.sort(key=lambda trade: (trade.ts_event, trade.trade_id))
        return connector_types.PollingBatch(
            events=cast(list[event_models.CanonicalMarketEvent], aggregated),
            raw_payloads={"trades": raw_payloads_accumulated} if raw_payloads_accumulated else {},
        )

    def _track_trade(self, trade: event_models.CanonicalTrade) -> bool:
        trade_key = (trade.instrument_id, trade.trade_id)
        if trade_key in self._seen_trade_keys:
            return False

        self._seen_trade_keys.add(trade_key)
        self._seen_trade_order.append(trade_key)
        if len(self._seen_trade_order) > self._max_seen_trade_ids:
            oldest = self._seen_trade_order.popleft()
            self._seen_trade_keys.discard(oldest)
        return True


__all__ = ["TradePoller"]
