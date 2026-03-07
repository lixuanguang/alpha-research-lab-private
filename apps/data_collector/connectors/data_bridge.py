"""Provider-neutral data-bridge contract and adapter implementation.

The :class:`DataBridgeProtocol` defines the single interface that dataset
builders, replay tools, and research pipelines use to pull historical or live
data from any supported venue.  Concrete venues are accessed through a
:class:`ConnectorDataBridge` that wraps the existing :class:`VenueAdapter`
stack — keeping all connector-specific branching inside the bridge and out
of the consuming code.

Contract methods
----------------
``capabilities()``
    Declare which data shapes and transport modes the provider supports.
``pull_snapshot(window)``
    Fetch a deterministic slice of historical events for a set of instruments
    and event types in a time window.
``pull_incremental(cursor)``
    Fetch all events that arrived after a cursor position — for resumable sync.
``stream_subscribe(topics)``
    Return an async iterator of live events for the requested topics.

Error model
-----------
:exc:`UnsupportedCapabilityError` is raised with a deterministic ``capability``
field so callers can catch specific unsupported operations and fall back
gracefully (e.g. switch from streaming to polling).

Usage::

    bridge = ConnectorDataBridge(my_venue_adapter)
    caps = bridge.capabilities()
    if caps.trades:
        events = await bridge.pull_snapshot(SnapshotWindow(
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
            instrument_ids=["p:mkt1:yes", "p:mkt1:no"],
            event_types=[EventType.TRADE, EventType.OHLCV],
        ))
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
from apps.data_collector.connectors.capabilities import VenueCapabilities

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotWindow:
    """Parameters for a deterministic historical data slice.

    Attributes
    ----------
    start
        Inclusive window start (UTC).
    end
        Inclusive window end (UTC).
    instrument_ids
        Canonical instrument IDs to fetch (empty = no data returned).
    event_types
        Event types to fetch.  Defaults to ``[TRADE]`` when empty.
    ohlcv_resolution
        Resolution used when ``OHLCV`` is in *event_types*.
    limit_per_instrument
        Max events per instrument per event type (passed to the adapter).
    """

    start: datetime
    end: datetime
    instrument_ids: list[str] = field(default_factory=list)
    event_types: list[event_models.EventType] = field(
        default_factory=lambda: [event_models.EventType.TRADE]
    )
    ohlcv_resolution: str = "1h"
    limit_per_instrument: int = 500


@dataclass(frozen=True)
class IncrementalCursor:
    """Cursor position for resumable incremental data sync.

    Attributes
    ----------
    venue_name
        Venue this cursor belongs to.
    instrument_ids
        Instruments in scope for this cursor.
    cursor_type
        Semantics of *cursor_value*: ``ts_event`` (ISO-8601 UTC timestamp),
        ``trade_id`` (venue trade identifier), or ``sequence`` (monotonic int).
    cursor_value
        Opaque string representation of the cursor position.
    cursor_watermark_utc
        Authoritative UTC timestamp of the last event seen.  Used as the
        ``since`` argument for adapter calls regardless of ``cursor_type``.
    resume_safe
        ``True`` when the cursor was persisted cleanly and resume is safe.
        ``False`` when the previous run was interrupted; callers may want
        to add overlap margin before replaying.
    """

    venue_name: str
    instrument_ids: list[str]
    cursor_type: str = "ts_event"  # "ts_event" | "trade_id" | "sequence"
    cursor_value: str = ""
    cursor_watermark_utc: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=UTC))
    resume_safe: bool = True


@dataclass(frozen=True)
class StreamTopic:
    """A single live-streaming subscription topic.

    Attributes
    ----------
    instrument_id
        Canonical instrument ID to subscribe to.
    event_type
        Event type to stream (``TRADE``, ``BOOK_SNAPSHOT``, or ``BOOK_DELTA``).
    """

    instrument_id: str
    event_type: event_models.EventType = event_models.EventType.TRADE


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------


class UnsupportedCapabilityError(RuntimeError):
    """Raised when a bridge method requires a capability the venue lacks.

    Attributes
    ----------
    capability
        Name of the unsupported capability (e.g. ``"streaming_trades"``).
    venue_name
        Venue that does not support the capability.
    """

    def __init__(self, capability: str, venue_name: str) -> None:
        self.capability = capability
        self.venue_name = venue_name
        super().__init__(
            f"Venue '{venue_name}' does not support capability '{capability}'. "
            "Check VenueCapabilities before calling this method."
        )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DataBridgeProtocol(Protocol):
    """Provider-neutral data access interface.

    Implementors expose a single surface for all data-pull and streaming
    modes.  Consumers check :meth:`capabilities` before calling methods to
    avoid :exc:`UnsupportedCapabilityError`.
    """

    @property
    def venue_name(self) -> str:
        """Normalized venue identifier."""
        ...

    def capabilities(self) -> VenueCapabilities:
        """Return typed capability declarations for this provider."""
        ...

    async def pull_snapshot(
        self, window: SnapshotWindow
    ) -> list[event_models.CanonicalMarketEvent]:
        """Fetch a historical event slice for all instruments in *window*.

        Events are returned in ascending *ts_event* order across all
        instrument IDs and event types.  The result is bounded by
        ``window.start`` and ``window.end`` using ``ts_event``.

        Raises :exc:`UnsupportedCapabilityError` for a requested event type
        the venue does not support.
        """
        ...

    async def pull_incremental(
        self, cursor: IncrementalCursor
    ) -> tuple[list[event_models.CanonicalMarketEvent], IncrementalCursor]:
        """Fetch all events that arrived after *cursor*.

        Returns a tuple of ``(new_events, updated_cursor)`` so the caller can
        persist the cursor and resume on the next call.  When no new events
        are available, returns ``([], cursor)`` with the same cursor unchanged.

        Raises :exc:`UnsupportedCapabilityError` when trades are not supported.
        """
        ...

    def stream_subscribe(
        self, topics: list[StreamTopic]
    ) -> AsyncIterator[event_models.CanonicalMarketEvent]:
        """Return an async iterator of live events for *topics*.

        Raises :exc:`UnsupportedCapabilityError` when no streaming channels
        are declared in :meth:`capabilities`.
        """
        ...


@runtime_checkable
class HistoricalBookSnapshotAdapter(Protocol):
    async def fetch_order_book_snapshot_at(
        self,
        outcome_id: str,
        *,
        as_of: datetime,
    ) -> event_models.CanonicalBookSnapshot:
        """Fetch the latest historical book snapshot at or before *as_of*."""


@runtime_checkable
class HistoricalOHLCVAdapter(Protocol):
    async def fetch_ohlcv_window(
        self,
        outcome_id: str,
        *,
        start: datetime,
        end: datetime,
        resolution: str,
        limit: int,
    ) -> list[event_models.CanonicalOHLCV]:
        """Fetch historical OHLCV bars bounded to *start* / *end*."""


# ---------------------------------------------------------------------------
# Concrete adapter
# ---------------------------------------------------------------------------


class ConnectorDataBridge:
    """DataBridge adapter over the existing :class:`VenueAdapter` stack.

    Wraps a :class:`~alpha_core.adapters.base.VenueAdapter` and exposes the
    DataBridgeProtocol interface.  Streaming (``stream_subscribe``) is
    supported when the underlying adapter exposes ``watch_trades`` or
    ``watch_order_book`` methods (duck-typed).

    Capabilities are declared at construction time; pass *capabilities_override*
    to supply the full declaration (e.g. when the adapter is known to expose
    book deltas or sequence IDs).
    """

    def __init__(
        self,
        adapter: adapters_base.VenueAdapter,
        *,
        capabilities_override: VenueCapabilities | None = None,
    ) -> None:
        self._adapter = adapter
        self._capabilities = capabilities_override or _infer_capabilities(adapter)

    # ------------------------------------------------------------------
    # DataBridgeProtocol
    # ------------------------------------------------------------------

    @property
    def venue_name(self) -> str:
        return self._adapter.venue_name()

    def capabilities(self) -> VenueCapabilities:
        return self._capabilities

    async def pull_snapshot(
        self, window: SnapshotWindow
    ) -> list[event_models.CanonicalMarketEvent]:
        """Fetch historical events from the adapter for all instruments in *window*."""
        caps = self._capabilities
        events: list[event_models.CanonicalMarketEvent] = []
        event_types = window.event_types or [event_models.EventType.TRADE]

        for event_type in event_types:
            if event_type == event_models.EventType.TRADE:
                _require(caps.trades, "trades", caps.venue_name)
                for iid in window.instrument_ids:
                    events.extend(
                        await _fetch_trades_in_window(
                            self._adapter,
                            instrument_id=iid,
                            window=window,
                        )
                    )

            elif event_type == event_models.EventType.BOOK_SNAPSHOT:
                _require(caps.book_snapshots, "book_snapshots", caps.venue_name)
                book_adapter = _require_historical_book_adapter(self._adapter, caps)
                for iid in window.instrument_ids:
                    book = await book_adapter.fetch_order_book_snapshot_at(
                        iid,
                        as_of=window.end,
                    )
                    if window.start <= book.ts_event <= window.end:
                        events.append(book)

            elif event_type == event_models.EventType.OHLCV:
                _require(
                    caps.supports_ohlcv(window.ohlcv_resolution),
                    f"ohlcv_resolutions['{window.ohlcv_resolution}']",
                    caps.venue_name,
                )
                ohlcv_adapter = _require_historical_ohlcv_adapter(self._adapter, caps)
                for iid in window.instrument_ids:
                    fetched = await ohlcv_adapter.fetch_ohlcv_window(
                        iid,
                        start=window.start,
                        end=window.end,
                        resolution=window.ohlcv_resolution,
                        limit=window.limit_per_instrument,
                    )
                    events.extend(_keep_in_window(fetched, window))

            else:
                raise UnsupportedCapabilityError(str(event_type), caps.venue_name)

        events.sort(key=lambda e: e.ts_event)
        return events

    async def pull_incremental(
        self, cursor: IncrementalCursor
    ) -> tuple[list[event_models.CanonicalMarketEvent], IncrementalCursor]:
        """Fetch trade events that arrived after *cursor.cursor_watermark_utc*."""
        caps = self._capabilities
        _require(caps.trades, "trades", caps.venue_name)

        since = cursor.cursor_watermark_utc
        new_events: list[event_models.CanonicalMarketEvent] = []

        for iid in cursor.instrument_ids:
            fetched = await self._adapter.fetch_trades(iid, since=since)
            new_events.extend(fetched)

        new_events.sort(key=lambda e: e.ts_event)

        if not new_events:
            return [], cursor

        new_watermark = max(e.ts_event for e in new_events)
        updated_cursor = IncrementalCursor(
            venue_name=cursor.venue_name,
            instrument_ids=cursor.instrument_ids,
            cursor_type=cursor.cursor_type,
            cursor_value=new_watermark.isoformat(),
            cursor_watermark_utc=new_watermark,
            resume_safe=True,
        )
        return new_events, updated_cursor

    def stream_subscribe(
        self, topics: list[StreamTopic]
    ) -> AsyncIterator[event_models.CanonicalMarketEvent]:
        """Return an async iterator of live events for *topics*.

        Delegates to ``watch_trades`` / ``watch_order_book`` on the underlying
        adapter when available.  Raises :exc:`UnsupportedCapabilityError` when
        neither streaming channel is declared.
        """
        caps = self._capabilities
        if not caps.supports_streaming():
            raise UnsupportedCapabilityError("streaming", caps.venue_name)
        return _merge_stream(self._adapter, topics, caps)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require(condition: bool, capability: str, venue_name: str) -> None:
    """Raise :exc:`UnsupportedCapabilityError` when *condition* is False."""
    if not condition:
        raise UnsupportedCapabilityError(capability, venue_name)


def _keep_in_window(
    events: Sequence[event_models.CanonicalMarketEvent],
    window: SnapshotWindow,
) -> list[event_models.CanonicalMarketEvent]:
    """Filter to events whose *ts_event* falls within [window.start, window.end]."""
    return [e for e in events if window.start <= e.ts_event <= window.end]


def _infer_capabilities(adapter: adapters_base.VenueAdapter) -> VenueCapabilities:
    """Build a best-effort capability declaration by duck-typing the adapter."""
    historical_ohlcv = isinstance(adapter, HistoricalOHLCVAdapter)
    return VenueCapabilities(
        venue_name=adapter.venue_name(),
        trades=True,
        book_snapshots=isinstance(adapter, HistoricalBookSnapshotAdapter),
        book_deltas=False,
        ohlcv_resolutions=(["1m", "5m", "15m", "1h", "4h", "1d"] if historical_ohlcv else []),
        streaming_trades=callable(getattr(adapter, "watch_trades", None)),
        streaming_books=callable(getattr(adapter, "watch_order_book", None)),
        sequence_id_capable=False,
        latency_metadata_capable=False,
    )


def _require_historical_book_adapter(
    adapter: adapters_base.VenueAdapter,
    caps: VenueCapabilities,
) -> HistoricalBookSnapshotAdapter:
    _require(isinstance(adapter, HistoricalBookSnapshotAdapter), "book_snapshots", caps.venue_name)
    return cast(HistoricalBookSnapshotAdapter, adapter)


def _require_historical_ohlcv_adapter(
    adapter: adapters_base.VenueAdapter,
    caps: VenueCapabilities,
) -> HistoricalOHLCVAdapter:
    capability = "ohlcv_resolutions"
    _require(isinstance(adapter, HistoricalOHLCVAdapter), capability, caps.venue_name)
    return cast(HistoricalOHLCVAdapter, adapter)


async def _fetch_trades_in_window(
    adapter: adapters_base.VenueAdapter,
    *,
    instrument_id: str,
    window: SnapshotWindow,
) -> list[event_models.CanonicalTrade]:
    cursor = window.start
    stalled_iterations = 0
    seen_trade_keys: set[tuple[str, str]] = set()
    collected: list[event_models.CanonicalTrade] = []

    while True:
        fetched = await adapter.fetch_trades(
            instrument_id,
            since=cursor,
            limit=window.limit_per_instrument,
        )
        if not fetched:
            break

        new_rows = 0
        for trade in fetched:
            if not (window.start <= trade.ts_event <= window.end):
                continue
            trade_key = (trade.instrument_id, trade.trade_id)
            if trade_key in seen_trade_keys:
                continue
            seen_trade_keys.add(trade_key)
            collected.append(trade)
            new_rows += 1

        max_ts = max(trade.ts_event for trade in fetched)
        if max_ts > window.end or len(fetched) < window.limit_per_instrument:
            break
        if max_ts < cursor:
            raise RuntimeError(
                "Trade snapshot pagination regressed cursor timestamp; "
                "aborting to avoid silent historical data loss."
            )
        if max_ts == cursor and new_rows == 0:
            stalled_iterations += 1
            if stalled_iterations >= 2:
                raise RuntimeError(
                    "Trade snapshot pagination stalled at a single timestamp; "
                    "venue pagination is ambiguous."
                )
        else:
            stalled_iterations = 0
        cursor = max_ts

    return collected


async def _merge_stream(
    adapter: Any,
    topics: list[StreamTopic],
    caps: VenueCapabilities,
) -> AsyncIterator[event_models.CanonicalMarketEvent]:
    """Interleave event streams for all requested topics into a single iterator.

    For each topic, delegates to ``watch_trades`` or ``watch_order_book`` on
    the adapter (duck-typed).  Topics whose required capability is missing are
    silently skipped (the caller should validate capabilities first).

    Yields :class:`~alpha_core.events.models.CanonicalMarketEvent` in arrival
    order across all topics.
    """
    queue: asyncio.Queue[event_models.CanonicalMarketEvent | None] = asyncio.Queue()
    tasks: list[asyncio.Task[None]] = []

    async def _drain_trade_stream(instrument_id: str) -> None:
        watch_fn = getattr(adapter, "watch_trades", None)
        if not callable(watch_fn):
            return
        async for batch in watch_fn(instrument_id):
            for event in batch:
                await queue.put(event)

    async def _drain_book_stream(instrument_id: str) -> None:
        watch_fn = getattr(adapter, "watch_order_book", None)
        if not callable(watch_fn):
            return
        async for batch in watch_fn(instrument_id):
            for event in batch:
                await queue.put(event)

    for topic in topics:
        if topic.event_type == event_models.EventType.TRADE and caps.streaming_trades:
            tasks.append(asyncio.create_task(_drain_trade_stream(topic.instrument_id)))
        elif (
            topic.event_type
            in (event_models.EventType.BOOK_SNAPSHOT, event_models.EventType.BOOK_DELTA)
            and caps.streaming_books
        ):
            tasks.append(asyncio.create_task(_drain_book_stream(topic.instrument_id)))

    async def _sentinel_when_done() -> None:
        try:
            await asyncio.gather(*tasks)
        finally:
            await queue.put(None)

    sentinel_task = asyncio.create_task(_sentinel_when_done())

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    await sentinel_task


__all__ = [
    "ConnectorDataBridge",
    "DataBridgeProtocol",
    "IncrementalCursor",
    "SnapshotWindow",
    "StreamTopic",
    "UnsupportedCapabilityError",
]
