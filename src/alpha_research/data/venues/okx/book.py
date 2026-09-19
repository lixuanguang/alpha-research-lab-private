"""Reconstruct bounded OKX price levels without inventing individual order identities."""

from __future__ import annotations

# standard library imports
import hashlib
from decimal import Decimal

# third party library imports
import msgspec

# project library imports
from alpha_research.data.live.book import Wire
from alpha_research.serialization import DomainCodec


class Level(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Exact aggregate size and reported order count at a native price level."""

    size: Decimal
    order_count: int

    def __post_init__(self) -> None:
        """Keep retained aggregate levels positive, finite and exactly counted."""
        if (
            type(self.size) is not Decimal
            or not self.size.is_finite()
            or self.size <= 0
            or type(self.order_count) is not int
            or self.order_count <= 0
        ):
            raise ValueError("aggregate levels require positive exact size and order count")


class OKXBook:
    """Maintain the best 400 levels per side; aggregate counts establish no queue priority."""

    def __init__(self, symbol: str) -> None:
        """Start an unsynchronized native instrument book.

        Args:
            symbol: Selected native spot instrument ID.
        """
        self.symbol = symbol
        self.bids: dict[Decimal, Level] = {}
        self.asks: dict[Decimal, Level] = {}
        self.ready = False
        self.acknowledged = False
        self.sequence: int | None = None
        self.source_time: str | None = None
        self._last_source_ms: int | None = None
        self.sequence_resets = 0
        self._fingerprint = 0
        self._codec = DomainCodec()

    @property
    def identity(self) -> str:
        """Hash exact bounded state, synchronization and the supplied sequence.

        Returns:
            Order-independent SHA-256 state identity.
        """
        return hashlib.sha256(
            self._codec.encode_json(
                (self._fingerprint, len(self.bids), len(self.asks), self.sequence, self.ready)
            )
        ).hexdigest()

    def apply(self, raw: bytes, *, snapshot: bool = False) -> str:
        """Validate a live acknowledgement, heartbeat or sequenced native book frame.

        Args:
            raw: Exact received WebSocket message bytes.
            snapshot: Reserved for REST snapshot records, unsupported by this feed.

        Returns:
            Acknowledgement, snapshot, update or heartbeat classification.

        Raises:
            ValueError: Identity, lifecycle, schema or sequence continuity fails.
        """
        if snapshot:
            raise ValueError("OKX books synchronizes with its WebSocket snapshot")
        if raw == b"pong":
            return "heartbeat"
        message = Wire.mapping(Wire.decode(raw))
        argument = Wire.mapping(message.get("arg"))
        if argument.get("channel") != "books" or argument.get("instId") != self.symbol:
            raise ValueError("unexpected OKX subscription identity or service event")
        if message.get("event") == "subscribe":
            if self.acknowledged:
                raise ValueError("duplicate OKX subscription acknowledgement")
            self.acknowledged = True
            return "acknowledgement"
        if "event" in message or not self.acknowledged:
            raise ValueError("OKX error or unacknowledged data")
        rows = Wire.array(message.get("data"))
        if len(rows) != 1:
            raise ValueError("expected one OKX book per message")
        row = Wire.mapping(rows[0])
        sequence = Wire.integer(row.get("seqId"))
        previous = row.get("prevSeqId")
        action = message.get("action")
        if action == "snapshot":
            if self.ready or type(previous) is not int or previous != -1:
                raise ValueError("unexpected OKX snapshot boundary")
        elif action == "update":
            if not self.ready or Wire.integer(previous) != self.sequence:
                raise ValueError("OKX sequence gap")
            if sequence == self.sequence and (row.get("asks") != [] or row.get("bids") != []):
                raise ValueError("unchanged OKX sequence with nonempty update")
        else:
            raise ValueError("unknown OKX book action")
        self._merge(row, action=action, width=4)
        if self.sequence is not None and sequence < self.sequence:
            self.sequence_resets += 1
        unchanged = action == "update" and sequence == self.sequence
        self.sequence = sequence
        return "heartbeat" if unchanged else action

    def apply_archive(self, raw: bytes) -> str:
        """Apply native archive rows, preserving missing sequence and receipt clocks.

        Args:
            raw: Original newline-delimited archive row with three-value price levels.

        Returns:
            Snapshot or update classification.

        Raises:
            ValueError: A row is malformed, changes identity or precedes synchronization.
        """
        row = Wire.mapping(Wire.decode(raw))
        if row.get("instId") != self.symbol or "seqId" in row or "prevSeqId" in row:
            raise ValueError("unsupported OKX archive identity or sequence schema")
        action = row.get("action")
        if action not in ("snapshot", "update") or not isinstance(action, str):
            raise ValueError("unknown OKX archive action")
        if action == "update" and not self.ready:
            raise ValueError("OKX archive update before snapshot")
        self._merge(row, action=action, width=3)
        return action

    def _merge(self, row: dict[str, object], *, action: str, width: int) -> None:
        """Merge absolute sizes, trimming visible depth; consumers invalidate rejected frames."""
        timestamp = row.get("ts")
        source_time = None if timestamp in (None, "") else Wire.text(timestamp)
        current = None if source_time is None else Wire.integer(source_time)
        if current is not None:
            if current > 253402300799999:
                raise ValueError("OKX timestamp outside supported UTC range")
            if self._last_source_ms is not None and current < self._last_source_ms:
                raise ValueError("OKX source time moved backwards")
        bids = {} if action == "snapshot" else self.bids.copy()
        asks = {} if action == "snapshot" else self.asks.copy()
        fingerprint = 0 if action == "snapshot" else self._fingerprint
        for side, levels in (("bids", bids), ("asks", asks)):
            entries = Wire.array(row.get(side))
            if len(entries) > 800 or (action == "snapshot" and len(entries) > 400):
                raise ValueError("OKX message exceeds bounded depth")
            seen: set[Decimal] = set()
            for value in entries:
                entry = Wire.array(value)
                if len(entry) != width or (width == 4 and entry[2] != "0"):
                    raise ValueError("unsupported OKX price-level schema")
                price, size = Wire.decimal(entry[0]), Wire.decimal(entry[1])
                count = Wire.integer(entry[-1])
                if price <= 0 or size < 0 or (size == 0) != (count == 0) or price in seen:
                    raise ValueError("invalid or repeated OKX aggregate price level")
                if action == "snapshot" and size == 0:
                    raise ValueError("zero-sized OKX snapshot level")
                seen.add(price)
                previous = levels.pop(price, None)
                if previous is not None:
                    fingerprint ^= self._hash(side, price, previous)
                if size:
                    level = Level(size, count)
                    levels[price] = level
                    fingerprint ^= self._hash(side, price, level)
            for price in sorted(levels, reverse=side == "bids")[400:]:
                fingerprint ^= self._hash(side, price, levels.pop(price))
        self.bids, self.asks, self._fingerprint = bids, asks, fingerprint
        self.source_time = source_time
        if current is not None:
            self._last_source_ms = current
        self.ready = True

    def _hash(self, side: str, price: Decimal, level: Level) -> int:
        """Hash one price level without rounding its exact source decimals."""
        canonical = (
            side,
            price.as_integer_ratio(),
            level.size.as_integer_ratio(),
            level.order_count,
        )
        return int.from_bytes(hashlib.sha256(self._codec.encode_json(canonical)).digest())
