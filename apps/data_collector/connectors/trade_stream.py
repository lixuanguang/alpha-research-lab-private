"""Trade streaming connector using pmxt watch_trades."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import alpha_core.events.models as event_models
import apps.data_collector.connectors._lifecycle as connector_lifecycle
import apps.data_collector.connectors._streaming as connector_streaming
import apps.data_collector.connectors.heartbeat as connector_heartbeat
import apps.data_collector.connectors.reconnection as connector_reconnection


class TradeWatchAdapter(Protocol):
    """Subset of a venue adapter needed by TradeStreamConnector."""

    def venue_name(self) -> str: ...

    def watch_trades(self, outcome_id: str) -> AsyncIterator[list[event_models.CanonicalTrade]]: ...


@dataclass(slots=True)
class TradeStreamOptions:
    reconnect_backoff_base: float = 1.0
    reconnect_backoff_max: float = 60.0
    heartbeat_timeout: float = 120.0
    heartbeat_monitor: connector_heartbeat.HeartbeatMonitor | None = None
    emit: connector_lifecycle.EmitCallback | None = None


def _make_gap_marker(
    outcome_id: str, venue: str, ts: datetime
) -> event_models.CanonicalMetadataUpdate:
    """Synthetic event marking a potential sequence break caused by reconnection."""
    return event_models.CanonicalMetadataUpdate.model_validate(
        {
            "instrument_id": outcome_id,
            "venue_id": venue,
            "ts_event": ts,
            "ts_record": ts,
            "ts_receive": ts,
            "is_reconnect_gap": True,
            "fields_changed": {"event": "reconnect_gap"},
        }
    )


class TradeStreamConnector(connector_streaming.OutcomeStreamingConnector):
    """Streams trades via an adapter's ``watch_trades`` with auto-reconnect.

    Each outcome_id is streamed in its own asyncio Task inside ``stream_loop``.
    If any outcome's stream raises, the whole loop exits and the outer reconnect
    policy retries with exponential backoff.

    Microstructure enrichment (D4 extension):
    - Each event is stamped with ``ts_receive`` at local receipt time.
    - On reconnect, a synthetic gap-marker (``is_reconnect_gap=True``) is emitted
      per outcome before the first real batch, flagging potential sequence breaks.

    Args:
        adapter:                 Venue adapter providing ``watch_trades``.
        outcome_ids:             Outcome identifiers to stream.
        reconnect_backoff_base:  Base backoff delay in seconds.
        reconnect_backoff_max:   Hard cap on backoff delay.
        heartbeat_timeout:       Seconds of silence before stale detection fires.
        heartbeat_monitor:       Optional shared monitor to record beats into.
        emit:                    Optional callback invoked with each normalised batch.
    """

    def __init__(
        self,
        adapter: TradeWatchAdapter,
        *,
        outcome_ids: list[str],
        options: TradeStreamOptions | None = None,
    ) -> None:
        resolved_options = options or TradeStreamOptions()
        self._policy = connector_reconnection.ReconnectionPolicy(
            base=resolved_options.reconnect_backoff_base,
            max_delay=resolved_options.reconnect_backoff_max,
        )
        self._adapter = adapter
        self._heartbeat_monitor = resolved_options.heartbeat_monitor
        # Outcomes currently awaiting a gap-marker emit (set on reconnect).
        self._pending_gaps: set[str] = set()
        self._session_count: int = 0  # incremented each time _on_reset fires

        super().__init__(
            venue=adapter.venue_name(),
            options=connector_streaming.OutcomeStreamOptions(
                outcome_ids=outcome_ids,
                heartbeat_timeout=resolved_options.heartbeat_timeout,
                next_reconnect_delay=self._policy.next_delay,
                on_reconnect_reset=self._on_reset,
            ),
            emit=resolved_options.emit,
        )

    def _on_reset(self) -> None:
        """Called at the start of every connect/reconnect cycle."""
        self._policy.reset()
        self._session_count += 1
        # Only flag gaps on reconnects, not on the initial connection.
        if self._session_count > 1:
            self._pending_gaps = set(self._outcome_ids)

    async def connect(self) -> None:
        """No-op: pmxt manages websocket lifecycle inside the watch generator."""

    async def _stream_outcome(self, outcome_id: str) -> None:
        stream = self._adapter.watch_trades(outcome_id)
        while not self._stop_event.is_set():
            ts_receive = datetime.now(UTC)
            try:
                batch = await self._next_stream_item(stream, outcome_id=outcome_id)
            except StopAsyncIteration:
                return
            if not batch:
                continue

            # Emit gap marker before first real batch after a reconnect.
            if outcome_id in self._pending_gaps:
                self._pending_gaps.discard(outcome_id)
                gap = _make_gap_marker(outcome_id, venue=self.venue, ts=ts_receive)
                await self._emit_events([gap])

            # Enrich each event with local receive timestamp.
            enriched: list[event_models.CanonicalMarketEvent] = [
                e.model_copy(update={"ts_receive": ts_receive}) for e in batch
            ]
            self._record_events(enriched)
            if self._heartbeat_monitor is not None:
                self._heartbeat_monitor.record_heartbeat(self.connector_id)
            await self._emit_events(enriched)


__all__ = ["TradeStreamConnector", "TradeStreamOptions", "TradeWatchAdapter"]
