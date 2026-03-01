"""Book streaming connector using pmxt watch_order_book."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

import alpha_core.events.models as event_models
import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.heartbeat as connector_heartbeat
import apps.data_collector.connectors.reconnection as connector_reconnection


class BookWatchAdapter(Protocol):
    """Subset of a venue adapter needed by BookStreamConnector."""

    def venue_name(self) -> str: ...

    def watch_order_book(
        self, outcome_id: str
    ) -> AsyncIterator[event_models.CanonicalBookSnapshot]: ...


class BookStreamConnector(connector_base.OutcomeStreamingConnector):
    """Streams order book snapshots via an adapter's ``watch_order_book``.

    Design mirrors :class:`TradeStreamConnector` — one task per outcome, with
    exponential backoff reconnection when any task fails.

    Args:
        adapter:                 Venue adapter providing ``watch_order_book``.
        outcome_ids:             Outcome identifiers to stream.
        reconnect_backoff_base:  Base backoff delay in seconds.
        reconnect_backoff_max:   Hard cap on backoff delay.
        heartbeat_timeout:       Seconds of silence before stale detection fires.
        heartbeat_monitor:       Optional shared monitor for recording beats.
        emit:                    Optional callback invoked with each snapshot batch.
    """

    def __init__(
        self,
        adapter: BookWatchAdapter,
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
        """No-op: websocket lifecycle is managed inside the watch generator."""

    async def _stream_outcome(self, outcome_id: str) -> None:
        stream = self._adapter.watch_order_book(outcome_id)
        while not self._stop_event.is_set():
            try:
                snapshot = await self._next_stream_item(stream, outcome_id=outcome_id)
            except StopAsyncIteration:
                return
            if not isinstance(snapshot, event_models.CanonicalBookSnapshot):
                continue
            self._record_events([snapshot])
            if self._heartbeat_monitor is not None:
                self._heartbeat_monitor.record_heartbeat(self.connector_id)
            await self._emit_events([snapshot], self._emit)


__all__ = ["BookStreamConnector", "BookWatchAdapter"]
