"""OHLCV polling connector implementation."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import cast

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.raw_payloads as connector_raw_payloads


class OHLCVPoller(connector_base.PollingConnector):
    """Polls fetch_ohlcv for configured outcomes at regular intervals."""

    def __init__(
        self,
        adapter: adapters_base.VenueAdapter,
        *,
        outcome_ids: list[str],
        resolution: str = "1h",
        interval_seconds: float = 300.0,
        request_timeout_seconds: float | None = 10.0,
        limit_per_poll: int = 100,
        max_seen_candle_keys: int = 100_000,
    ) -> None:
        if limit_per_poll <= 0:
            raise ValueError("`limit_per_poll` must be > 0")
        if max_seen_candle_keys <= 0:
            raise ValueError("`max_seen_candle_keys` must be > 0")
        self._adapter = adapter
        self._outcome_ids = connector_base.normalize_outcome_ids(outcome_ids)
        self._resolution = resolution
        self._limit_per_poll = limit_per_poll
        self._max_seen_candle_keys = max_seen_candle_keys
        self._last_ts_by_outcome: dict[str, datetime | None] = {
            outcome_id: None for outcome_id in self._outcome_ids
        }
        self._seen_candle_keys: set[tuple[str, str, datetime]] = set()
        self._seen_candle_order: deque[tuple[str, str, datetime]] = deque()
        super().__init__(
            venue=adapter.venue_name(),
            interval_seconds=interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )

    def event_types(self) -> list[str]:
        return ["ohlcv"]

    async def poll_once(self) -> connector_base.PollingBatch:
        if not self._outcome_ids:
            return connector_base.PollingBatch(events=[], raw_payloads={})

        aggregated: list[event_models.CanonicalOHLCV] = []
        raw_payloads_accumulated: list[dict[str, object]] = []
        for outcome_id in self._outcome_ids:
            try:
                candles, raw_payloads = await self._await_with_timeout(
                    self._adapter.fetch_ohlcv_with_raw(
                        outcome_id,
                        resolution=self._resolution,
                        limit=self._limit_per_poll,
                    ),
                    operation=f"fetch_ohlcv[{outcome_id}]",
                )
            except Exception as exc:
                self._record_poll_failure(scope="ohlcv", outcome_id=outcome_id, error=exc)
                continue

            normalized_raw_payloads = connector_raw_payloads.normalize_raw_payloads(
                raw_payloads,
                outcome_id=outcome_id,
            )
            last_seen_ts = self._last_ts_by_outcome[outcome_id]
            filtered_candles, filtered_raw_payloads = self._filter_new_candles(
                candles,
                normalized_raw_payloads,
                last_seen_ts=last_seen_ts,
            )
            if filtered_candles:
                self._last_ts_by_outcome[outcome_id] = max(
                    candle.ts_event for candle in filtered_candles
                )
                aggregated.extend(filtered_candles)
                raw_payloads_accumulated.extend(filtered_raw_payloads)

        aggregated.sort(key=lambda candle: (candle.ts_event, candle.instrument_id))
        return connector_base.PollingBatch(
            events=cast(list[event_models.CanonicalMarketEvent], aggregated),
            raw_payloads={"ohlcv": raw_payloads_accumulated} if raw_payloads_accumulated else {},
        )

    def _filter_new_candles(
        self,
        candles: list[event_models.CanonicalOHLCV],
        raw_payloads: list[dict[str, object]],
        *,
        last_seen_ts: datetime | None,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[dict[str, object]]]:
        accepted_candles: list[event_models.CanonicalOHLCV] = []
        accepted_raw_payloads: list[dict[str, object]] = []
        if len(raw_payloads) == len(candles):
            for candle, raw_payload in zip(candles, raw_payloads, strict=True):
                if not self._should_emit_candle(candle, last_seen_ts=last_seen_ts):
                    continue
                accepted_candles.append(candle)
                accepted_raw_payloads.append(raw_payload)
            return accepted_candles, accepted_raw_payloads

        for candle in candles:
            if not self._should_emit_candle(candle, last_seen_ts=last_seen_ts):
                continue
            accepted_candles.append(candle)
        if accepted_candles:
            accepted_raw_payloads = raw_payloads
        return accepted_candles, accepted_raw_payloads

    def _should_emit_candle(
        self,
        candle: event_models.CanonicalOHLCV,
        *,
        last_seen_ts: datetime | None,
    ) -> bool:
        if last_seen_ts is not None and candle.ts_event <= last_seen_ts:
            return False

        candle_key = (candle.instrument_id, candle.resolution, candle.ts_event)
        if candle_key in self._seen_candle_keys:
            return False

        self._seen_candle_keys.add(candle_key)
        self._seen_candle_order.append(candle_key)
        if len(self._seen_candle_order) > self._max_seen_candle_keys:
            oldest = self._seen_candle_order.popleft()
            self._seen_candle_keys.discard(oldest)
        return True


__all__ = ["OHLCVPoller"]
