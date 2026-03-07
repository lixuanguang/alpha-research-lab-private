"""Book streaming connector using pmxt watch_order_book."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import alpha_core.events.models as event_models
import apps.data_collector.connectors._lifecycle as connector_lifecycle
import apps.data_collector.connectors._streaming as connector_streaming
import apps.data_collector.connectors.heartbeat as connector_heartbeat
import apps.data_collector.connectors.reconnection as connector_reconnection


class BookWatchAdapter(Protocol):
    """Subset of a venue adapter needed by BookStreamConnector."""

    def venue_name(self) -> str: ...

    def watch_order_book(
        self, outcome_id: str
    ) -> AsyncIterator[event_models.CanonicalBookSnapshot]: ...

    def book_stream_capabilities(self) -> dict[str, bool]: ...


@dataclass(slots=True)
class BookStreamOptions:
    reconnect_backoff_base: float = 1.0
    reconnect_backoff_max: float = 60.0
    heartbeat_timeout: float = 120.0
    heartbeat_monitor: connector_heartbeat.HeartbeatMonitor | None = None
    emit_deltas: bool = True
    emit: connector_lifecycle.EmitCallback | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gap_marker(
    outcome_id: str, venue: str, ts: datetime, *, stream_capabilities: dict[str, bool]
) -> event_models.CanonicalMetadataUpdate:
    """Synthetic event marking a potential sequence break caused by reconnection."""
    return event_models.CanonicalMetadataUpdate.model_validate(
        {
            "instrument_id": outcome_id,
            "venue_id": venue,
            "ts_event": ts,
            "ts_record": ts,
            "ts_receive": ts,
            "sequence_id_capable": stream_capabilities["sequence_id"],
            "latency_metadata_capable": stream_capabilities["latency_metadata"],
            "is_reconnect_gap": True,
            "fields_changed": {
                "event": "reconnect_gap",
                "stream_capabilities": stream_capabilities,
            },
        }
    )


def _levels_as_dict(levels: list[event_models.PriceLevel]) -> dict[Decimal, Decimal]:
    return {level.price: level.size for level in levels}


def _compute_book_deltas(
    new_snap: event_models.CanonicalBookSnapshot,
    prev_snap: event_models.CanonicalBookSnapshot,
) -> list[event_models.CanonicalBookDelta]:
    """Derive incremental deltas by diffing two consecutive book snapshots.

    All returned deltas carry ``is_reconstructed=True`` and inherit
    ``ts_event``, ``ts_record``, ``ts_receive``, and ``sequence_id`` from
    the new snapshot so they are correctly positioned in the event timeline.
    """
    deltas: list[event_models.CanonicalBookDelta] = []

    sides: list[tuple[str, list[event_models.PriceLevel], list[event_models.PriceLevel]]] = [
        ("bid", new_snap.bids, prev_snap.bids),
        ("ask", new_snap.asks, prev_snap.asks),
    ]
    for side, new_levels, prev_levels in sides:
        new_d = _levels_as_dict(new_levels)
        prev_d = _levels_as_dict(prev_levels)
        for price in set(new_d) | set(prev_d):
            delta_size = new_d.get(price, Decimal("0")) - prev_d.get(price, Decimal("0"))
            if delta_size == Decimal("0"):
                continue
            side_literal = "bid" if side == "bid" else "ask"
            deltas.append(
                event_models.CanonicalBookDelta.model_validate(
                    {
                        "instrument_id": new_snap.instrument_id,
                        "venue_id": new_snap.venue_id,
                        "ts_event": new_snap.ts_event,
                        "ts_record": new_snap.ts_record,
                        "ts_exchange": new_snap.ts_exchange,
                        "ts_receive": new_snap.ts_receive,
                        "source_latency_ms": new_snap.source_latency_ms,
                        "sequence_id": new_snap.sequence_id,
                        "sequence_id_capable": new_snap.sequence_id_capable,
                        "latency_metadata_capable": new_snap.latency_metadata_capable,
                        "side": side_literal,
                        "price": price,
                        "delta_size": delta_size,
                        "reason": "add" if delta_size > 0 else "cancel",
                        "is_reconstructed": True,
                    }
                )
            )
    return deltas


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class BookStreamConnector(connector_streaming.OutcomeStreamingConnector):
    """Streams order book snapshots via an adapter's ``watch_order_book``.

    Design mirrors :class:`TradeStreamConnector` — one task per outcome, with
    exponential backoff reconnection when any task fails.

    Microstructure enrichment (D4 extension):
    - Each snapshot is stamped with ``ts_receive`` at local receipt time.
    - On reconnect, a gap-marker event (``is_reconnect_gap=True``) is emitted
      per outcome before the first real snapshot.
    - ``CanonicalBookDelta`` events are derived from consecutive snapshots for
      venues that do not provide native delta feeds (``is_reconstructed=True``).
      Previous snapshots are discarded after a reconnect to avoid spurious deltas.

    Args:
        adapter:                 Venue adapter providing ``watch_order_book``.
        outcome_ids:             Outcome identifiers to stream.
        reconnect_backoff_base:  Base backoff delay in seconds.
        reconnect_backoff_max:   Hard cap on backoff delay.
        heartbeat_timeout:       Seconds of silence before stale detection fires.
        heartbeat_monitor:       Optional shared monitor for recording beats.
        emit_deltas:             When True (default), emit reconstructed deltas
                                 alongside each snapshot.
        emit:                    Optional callback invoked with each event batch.
    """

    def __init__(
        self,
        adapter: BookWatchAdapter,
        *,
        outcome_ids: list[str],
        options: BookStreamOptions | None = None,
    ) -> None:
        resolved_options = options or BookStreamOptions()
        self._policy = connector_reconnection.ReconnectionPolicy(
            base=resolved_options.reconnect_backoff_base,
            max_delay=resolved_options.reconnect_backoff_max,
        )
        self._adapter = adapter
        self._heartbeat_monitor = resolved_options.heartbeat_monitor
        self._emit_deltas = resolved_options.emit_deltas
        self._stream_capabilities = _resolve_stream_capabilities(adapter)
        # Outcomes awaiting a gap-marker emit (populated on reconnect).
        self._pending_gaps: set[str] = set()
        self._session_count: int = 0
        # Previous snapshots per outcome for delta reconstruction.
        self._prev_snapshots: dict[str, event_models.CanonicalBookSnapshot] = {}

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
        if self._session_count > 1:
            # Flag gap markers for all outcomes and discard stale snapshots so
            # the first post-reconnect snapshot doesn't produce spurious deltas.
            self._pending_gaps = set(self._outcome_ids)
            self._prev_snapshots.clear()

    async def connect(self) -> None:
        """No-op: websocket lifecycle is managed inside the watch generator."""

    async def _stream_outcome(self, outcome_id: str) -> None:
        stream = self._adapter.watch_order_book(outcome_id)
        while not self._stop_event.is_set():
            ts_receive = datetime.now(UTC)
            try:
                snapshot = await self._next_stream_item(stream, outcome_id=outcome_id)
            except StopAsyncIteration:
                return
            if not isinstance(snapshot, event_models.CanonicalBookSnapshot):
                continue

            # Enrich with local receive timestamp.
            snapshot = snapshot.model_copy(
                update={
                    "ts_receive": ts_receive,
                    "sequence_id_capable": bool(
                        snapshot.sequence_id_capable or self._stream_capabilities["sequence_id"]
                    ),
                    "latency_metadata_capable": bool(
                        snapshot.latency_metadata_capable
                        or self._stream_capabilities["latency_metadata"]
                    ),
                }
            )

            # Emit gap marker before first real snapshot after a reconnect.
            if outcome_id in self._pending_gaps:
                self._pending_gaps.discard(outcome_id)
                gap = _make_gap_marker(
                    outcome_id,
                    venue=self.venue,
                    ts=ts_receive,
                    stream_capabilities=self._stream_capabilities,
                )
                await self._emit_events([gap])

            batch: list[event_models.CanonicalMarketEvent] = [snapshot]

            # Reconstruct deltas from consecutive snapshots when the venue
            # does not provide a native delta feed.
            if self._emit_deltas:
                prev = self._prev_snapshots.get(outcome_id)
                if prev is not None:
                    batch.extend(_compute_book_deltas(snapshot, prev))

            self._prev_snapshots[outcome_id] = snapshot
            self._record_events(batch)
            if self._heartbeat_monitor is not None:
                self._heartbeat_monitor.record_heartbeat(self.connector_id)
            await self._emit_events(batch)


__all__ = ["BookStreamConnector", "BookStreamOptions", "BookWatchAdapter", "_compute_book_deltas"]


def _resolve_stream_capabilities(adapter: object) -> dict[str, bool]:
    capabilities_fn = getattr(adapter, "book_stream_capabilities", None)
    if callable(capabilities_fn):
        value = capabilities_fn()
        if isinstance(value, dict):
            return {
                "sequence_id": bool(value.get("sequence_id", False)),
                "latency_metadata": bool(value.get("latency_metadata", False)),
                "native_book_deltas": bool(value.get("native_book_deltas", False)),
            }
    return {
        "sequence_id": False,
        "latency_metadata": False,
        "native_book_deltas": False,
    }
