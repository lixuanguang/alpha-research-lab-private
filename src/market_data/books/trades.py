"""Apply native public trade streams through the common durable capture boundary."""

from __future__ import annotations

# standard library imports
import hashlib
from collections import deque
from decimal import Decimal

# project library imports
from market_data.contracts import Level, Order, PublicTrade
from serialization import DomainCodec


class TradeTape:
    """Hold one connection epoch's public trades with no visible depth.

    A tape is a native stream the capture runner journals, replays and checks for
    quality exactly as it does a book; it simply has no orders or levels. Each
    venue subclass validates its own frames and records the trades that the last
    message added. A trade repeated within the bounded recent window is applied
    once. The source time is the high-water trade time, so quality never treats an
    earlier trade as a clock regression.
    """

    recent_capacity = 4096

    def __init__(self) -> None:
        """Start an unsynchronized tape with no trades."""
        self.ready = False
        self.sequence: int | None = None
        self.source_time: str | None = None
        self.orders: dict[str, Order] = {}
        self.bids: dict[Decimal, Level] = {}
        self.asks: dict[Decimal, Level] = {}
        self.trades: tuple[PublicTrade, ...] = ()
        self.applied = 0
        self._recent: deque[str] = deque(maxlen=self.recent_capacity)
        self._seen: set[str] = set()
        self._fingerprint = 0
        self._codec = DomainCodec()

    @property
    def identity(self) -> str:
        """Hash the applied trades, synchronization and native sequence.

        Returns:
            Order-independent SHA-256 tape identity.
        """
        return hashlib.sha256(
            self._codec.encode_json((self._fingerprint, self.applied, self.sequence, self.ready))
        ).hexdigest()

    @property
    def source_ns(self) -> int | None:
        """Project the high-water trade time to Unix nanoseconds.

        Returns:
            Exact latest trade instant, or None before any trade.
        """
        return None if self.source_time is None else int(self.source_time) * 1_000_000

    def apply(self, raw: bytes, *, snapshot: bool = False) -> str:
        """Apply one native message; subclasses implement the venue protocol.

        Args:
            raw: Complete original native message.
            snapshot: Whether the message is an independently received REST snapshot.

        Returns:
            Native boundary classification.
        """
        raise NotImplementedError

    def counts(self, max_orders: int) -> dict[str, object]:
        """Report the trade representation without claiming depth.

        Args:
            max_orders: Configured resource ceiling, unused by a tape.

        Returns:
            Native representation, clock convention and applied trade count.
        """
        return {
            "representation": "trades",
            "orders": None,
            "levels": None,
            "max_levels": None,
            "trades": self.applied,
            "source_time_unit": "unix_milliseconds",
        }

    def _admit(self, trades: tuple[PublicTrade, ...]) -> tuple[PublicTrade, ...]:
        """Apply trades not already applied, returning those this message adds."""
        added: list[PublicTrade] = []
        for trade in trades:
            trade.__post_init__()
            if trade.trade_id in self._seen:
                continue
            if len(self._recent) == self._recent.maxlen:
                self._seen.discard(self._recent[0])
            self._recent.append(trade.trade_id)
            self._seen.add(trade.trade_id)
            added.append(trade)
            self.applied += 1
            self._fingerprint ^= int.from_bytes(
                hashlib.sha256(self._codec.encode_json(trade)).digest()
            )
            if self.source_time is None or trade.event_ms > int(self.source_time):
                self.source_time = str(trade.event_ms)
        self.trades = tuple(added)
        return self.trades
