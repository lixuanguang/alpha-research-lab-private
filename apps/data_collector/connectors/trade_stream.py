"""Trade streaming connector using pmxt watch_trades."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, cast

import alpha_core.events.models as event_models
import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.heartbeat as connector_heartbeat
import apps.data_collector.connectors.reconnection as connector_reconnection


class TradeWatchAdapter(Protocol):
    """Subset of a venue adapter needed by TradeStreamConnector."""

    def venue_name(self) -> str: ...

    def watch_trades(
        self, outcome_id: str
    ) -> AsyncIterator[list[event_models.CanonicalTrade]]: ...


class TradeStreamConnector(connector_base.OutcomeStreamingConnector):
    """Streams trades via an adapter's ``watch_trades`` with auto-reconnect.

    Each outcome_id is streamed in its own asyncio Task inside ``stream_loop``.
    If any outcome's stream raises, the whole loop exits and the outer reconnect
    policy retries with exponential backoff.

    Args:
        adapter:                 Venue adapter providing ``watch_trades``.
        outcome_ids:             Outcome identifiers to stream.
        reconnect_backoff_base:  Base backoff delay in seconds.
        reconnect_backoff_max:   Hard cap on backoff delay.
        heartbeat_timeout:       Seconds of silence before the connector is
                                 considered stale by a HeartbeatMonitor.
        heartbeat_monitor:       Optional shared monitor to record beats into.
        emit:                    Optional callback invoked with each normalised batch.
    """

    def __init__(
        self,
        adapter: TradeWatchAdapter,
        *,
        outcome_ids: list[str],
        reconnect_backoff_base: float = 1.0,
        reconnect_backoff_max: float = 60.0,
        heartbeat_timeout: float = 120.0,
        heartbeat_monitor: connector_heartbeat.HeartbeatMonitor | None = None,
        emit: connector_base.EmitCallback | None = None,
    ) -> None:
        self._policy = connector_reconnection.ReconnectionPolicy(
            base=reconnect_backoff_base,
            max_delay=reconnect_backoff_max,
        )
        self._adapter = adapter
        self._heartbeat_monitor = heartbeat_monitor
        super().__init__(
            venue=adapter.venue_name(),
            outcome_ids=outcome_ids,
            heartbeat_timeout=heartbeat_timeout,
            next_reconnect_delay=self._policy.next_delay,
            on_reconnect_reset=self._policy.reset,
            emit=emit,
        )

    async def connect(self) -> None:
        """No-op: pmxt manages websocket lifecycle inside the watch generator."""

    async def _stream_outcome(self, outcome_id: str) -> None:
        stream = self._adapter.watch_trades(outcome_id)
        while not self._stop_event.is_set():
            try:
                batch = await self._next_stream_item(stream, outcome_id=outcome_id)
            except StopAsyncIteration:
                return
            if not batch:
                continue

            events = cast(list[event_models.CanonicalMarketEvent], list(batch))
            if not events:
                continue
            self._record_events(events)
            if self._heartbeat_monitor is not None:
                self._heartbeat_monitor.record_heartbeat(self.connector_id)
            await self._emit_events(events, self._emit)


__all__ = ["TradeStreamConnector", "TradeWatchAdapter"]
