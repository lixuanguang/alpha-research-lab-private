"""Select native public book or trades subscriptions for a capture connection."""

from __future__ import annotations

# standard library imports
import time

# project library imports
from configuration import CaptureConfig
from market_data.adapters.venues.coinbase import (
    CoinbaseAccessError,
    CoinbaseBook,
    CoinbaseCredentials,
)
from market_data.books import NativeBook


class VenueSubscriptions:
    """Bind native subscribe messages and Coinbase snapshot negotiation."""

    def __init__(self, credentials: CoinbaseCredentials | None = None) -> None:
        """Retain optional read-only Exchange signing capability privately."""
        self._credentials = credentials

    def __call__(self, config: CaptureConfig) -> tuple[dict[str, object], ...]:
        """Construct the selected venue's fresh per-connection subscribe messages."""
        config.__post_init__()
        if config.channel == "trades":
            if config.venue == "bitfinex":
                return (
                    {"event": "conf", "flags": 65536},
                    {"event": "subscribe", "channel": "trades", "symbol": config.symbol},
                )
            return ({"op": "subscribe", "args": [{"channel": "trades", "instId": config.symbol}]},)
        if config.venue == "bitfinex":
            return (
                {"event": "conf", "flags": 65536},
                {
                    "event": "subscribe",
                    "channel": "book",
                    "symbol": config.symbol,
                    "prec": "R0",
                    "freq": "F0",
                    "len": str(config.depth),
                },
            )
        if config.venue == "okx":
            return ({"op": "subscribe", "args": [{"channel": "books", "instId": config.symbol}]},)
        if self._credentials is None:
            raise CoinbaseAccessError("missing Exchange credentials")
        return (self._credentials.subscription(config.symbol, str(int(time.time()))),)

    @staticmethod
    def needs_snapshot(book: NativeBook) -> bool:
        """Request Coinbase REST L3 only after validated channel/schema acknowledgement."""
        return isinstance(book, CoinbaseBook) and book.acknowledged and bool(book.schema)
