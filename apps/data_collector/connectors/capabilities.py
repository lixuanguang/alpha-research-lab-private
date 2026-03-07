"""Typed venue capability model for the data-bridge contract.

:class:`VenueCapabilities` declares what a provider can supply so callers
can make explicit decisions about which bridge methods to invoke rather than
discovering unsupported operations at runtime.

Each field maps to a named bridge capability.  Absent support is represented
by ``False`` / empty list, never by ``None`` — this makes capability checks
unambiguous and avoids accidental truthiness bugs.

Usage::

    caps = bridge.capabilities()
    if not caps.trades:
        raise UnsupportedCapabilityError("trades", bridge.venue_name)
    if "1h" not in caps.ohlcv_resolutions:
        raise UnsupportedCapabilityError("ohlcv_resolutions['1h']", bridge.venue_name)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Default OHLCV resolutions if the venue does not declare them explicitly.
# Based on the resolutions the VenueAdapter interface supports.
_DEFAULT_OHLCV_RESOLUTIONS: list[str] = ["1m", "5m", "15m", "1h", "4h", "1d"]


class VenueCapabilities(BaseModel):
    """Explicit capability declarations for a venue data provider.

    Fields
    ------
    venue_name
        Normalized venue identifier (matches ``VenueAdapter.venue_name()``).
    trades
        Provider can serve trade events via ``pull_snapshot`` / ``pull_incremental``.
    book_snapshots
        Provider can serve order-book snapshots.
    book_deltas
        Provider can serve native order-book delta events (not synthetically
        computed from successive snapshots).
    ohlcv_resolutions
        Supported OHLCV bar resolution strings (e.g. ``"1h"``, ``"1d"``).
        Empty list means OHLCV is not supported.
    streaming_trades
        Provider supports live trade streaming via ``stream_subscribe``.
    streaming_books
        Provider supports live book streaming via ``stream_subscribe``.
    metadata_cadence_seconds
        Approximate cadence at which market metadata (instrument list) is
        refreshed.  ``0`` or negative means metadata is static / on-demand
        only.
    sequence_id_capable
        Provider emits reliable monotonic sequence IDs on trade/book events.
    latency_metadata_capable
        Provider attaches exchange and receive timestamps for latency profiling.
    """

    model_config = ConfigDict(extra="forbid")

    venue_name: str
    trades: bool = True
    book_snapshots: bool = True
    book_deltas: bool = False
    ohlcv_resolutions: list[str] = Field(default_factory=lambda: list(_DEFAULT_OHLCV_RESOLUTIONS))
    streaming_trades: bool = False
    streaming_books: bool = False
    metadata_cadence_seconds: float = 0.0
    sequence_id_capable: bool = False
    latency_metadata_capable: bool = False

    def supports_ohlcv(self, resolution: str) -> bool:
        """Return ``True`` when *resolution* is in the declared OHLCV resolutions."""
        return resolution in self.ohlcv_resolutions

    def supports_streaming(self) -> bool:
        """Return ``True`` when at least one streaming channel is supported."""
        return self.streaming_trades or self.streaming_books


__all__ = ["VenueCapabilities"]
