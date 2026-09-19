"""Synchronize compact Exchange L3 with a complete sequenced REST snapshot."""

from __future__ import annotations

# standard library imports
from decimal import localcontext

# project library imports
from configuration import CaptureConfig
from market_data.adapters.wire import Wire
from market_data.books import VisibleBook
from market_data.contracts import Order


class CoinbaseBook(VisibleBook):
    """Interpret the received schema and buffer a bounded snapshot bridge."""

    def __init__(self, config: CaptureConfig) -> None:
        """Start a fresh epoch without borrowing a previous connection's order state.

        Args:
            config: Validated native spot source selection and resource budgets.
        """
        super().__init__(config.max_orders)
        self.config = config
        self.schema: dict[str, list[str]] = {}
        self.pending: list[dict[str, object]] = []
        self.acknowledged = False
        self.source_time: str | None = None
        self._source_clock_ns: int | None = None
        self.snapshot_loaded = False
        self.snapshot_sequence = -1
        self.duplicates = 0

    def apply(self, raw: bytes, *, snapshot: bool = False) -> str:
        """Apply controls, schema, buffered stream updates or a REST snapshot atomically.

        Args:
            raw: Original received JSON bytes, before any numeric conversion.
            snapshot: Whether these bytes are the independently received REST L3 snapshot.

        Returns:
            Source-message classification for the applied boundary.

        Raises:
            ValueError: The source schema, identity, continuity or resource contract is invalid.
        """
        value = Wire.decode(raw)
        if snapshot:
            return self._snapshot(Wire.mapping(value))
        if isinstance(value, dict):
            return self._control(Wire.mapping(value))
        values = Wire.array(value)
        if not values:
            raise ValueError("empty Coinbase L3 message")
        kind = Wire.text(values[0])
        fields = self.schema.get(kind)
        if fields is None or len(fields) != len(values):
            raise ValueError("Coinbase L3 schema missing or incompatible")
        message = dict(zip(fields, values, strict=True))
        if message.get("product_id") != self.config.symbol:
            raise ValueError("Coinbase product mismatch")
        source_time = Wire.source_time(message.get("time"))
        if not self.snapshot_loaded:
            if len(self.pending) >= self.config.queue_capacity:
                raise ValueError("Coinbase snapshot bridge overflow")
            self.pending.append(message)
            return "buffered"
        return self._update(message, source_time=source_time)

    def _control(self, message: dict[str, object]) -> str:
        """Require the selected channel and retain its actual ordered field schema."""
        kind = message.get("type")
        if kind == "subscriptions":
            channels = [Wire.mapping(v) for v in Wire.array(message.get("channels"))]
            self.acknowledged = any(
                c.get("name") == "level3" and self.config.symbol in Wire.array(c.get("product_ids"))
                for c in channels
            )
            if not self.acknowledged:
                raise ValueError("Coinbase level3 subscription not acknowledged")
        elif kind == "level3":
            if self.schema:
                raise ValueError("Coinbase repeated schema requires fresh epoch")
            self.schema = {
                k: [Wire.text(f) for f in Wire.array(v)]
                for k, v in Wire.mapping(message.get("schema")).items()
            }
            for fields in self.schema.values():
                if len(set(fields)) != len(fields) or not {"type", "product_id", "sequence"} <= set(
                    fields
                ):
                    raise ValueError("incompatible Coinbase L3 schema")
        elif kind == "heartbeat":
            if message.get("product_id") != self.config.symbol:
                raise ValueError("heartbeat product mismatch")
            # Heartbeats sample product sequence; they do not advance lifecycle sequence.
            if self.ready and Wire.integer(message.get("sequence")) > (self.sequence or 0):
                raise ValueError("Coinbase heartbeat reveals missing lifecycle messages")
            return "heartbeat"
        else:
            raise ValueError("Coinbase unsupported control or subscription error")
        return "control"

    def _snapshot(self, message: dict[str, object]) -> str:
        """Install full depth, discard buffered <= snapshot, then require contiguous updates."""
        if not self.acknowledged or not self.schema or self.snapshot_loaded:
            raise ValueError("snapshot requires acknowledged schema in a fresh epoch")
        source_time = Wire.source_time(message.get("time"))
        self._validate_source_time(source_time)
        self.sequence = Wire.integer(message.get("sequence"))
        self.snapshot_sequence = self.sequence
        for side, field in (("buy", "bids"), ("sell", "asks")):
            for row in Wire.array(message.get(field)):
                entry = Wire.array(row)
                if len(entry) != 3:
                    raise ValueError("Coinbase snapshot requires L3 order IDs")
                order = Order(
                    Wire.text(entry[2]), side, Wire.decimal(entry[0]), Wire.decimal(entry[1])
                )
                if order.order_id in self.orders:
                    raise ValueError("duplicate Coinbase snapshot order")
                self.set(order)
        self.snapshot_loaded = True
        self._remember_source_time(source_time)
        for update in self.pending:
            self._update(update, source_time=Wire.source_time(update.get("time")))
        self.pending.clear()
        # A snapshot alone does not prove the WebSocket bridge.
        return "snapshot"

    def _update(self, message: dict[str, object], *, source_time: str | None) -> str:
        """Apply resting-order lifecycle; duplicates remain raw but never repeat mutations."""
        sequence = Wire.integer(message.get("sequence"))
        if not self.ready and sequence <= self.snapshot_sequence:
            return "snapshot_covered"
        if self.sequence is None or sequence != self.sequence + 1:
            if sequence == self.sequence:
                # Ambiguous repeats are not economic updates; invalidate and resnapshot.
                self.duplicates += 1
            raise ValueError("Coinbase sequence gap or duplicate requires resnapshot")
        self._validate_source_time(source_time)
        kind = message.get("type")
        if kind == "open":
            order_id = Wire.text(message.get("order_id"))
            if order_id in self.orders:
                raise ValueError("Coinbase open reuses resting order ID")
            self.set(
                Order(
                    order_id,
                    Wire.text(message.get("side")),
                    Wire.decimal(message.get("price")),
                    Wire.decimal(message.get("size")),
                )
            )
        elif kind == "done":
            self.remove(Wire.text(message.get("order_id")))
        elif kind in ("change", "match"):
            order_id = Wire.text(message.get("maker_order_id" if kind == "match" else "order_id"))
            previous = self.orders.get(order_id)
            if previous is None:
                if kind == "match":
                    raise ValueError("Coinbase match has no resting maker")
            else:
                price = Wire.decimal(message.get("price"))
                if price <= 0 or (kind == "match" and price != previous.price):
                    raise ValueError("Coinbase lifecycle price differs from resting maker")
                if kind == "match":
                    Wire.text(message.get("taker_order_id"))
                with localcontext() as context:
                    context.prec = 100
                    size = Wire.decimal(message.get("size"))
                    if size < 0 or (kind == "match" and size == 0):
                        raise ValueError("invalid Coinbase lifecycle size")
                    if kind == "match":
                        size = previous.size - size
                if size < 0:
                    raise ValueError("Coinbase match exceeds resting size")
                if size == 0:
                    self.remove(order_id)
                else:
                    self.set(Order(order_id, previous.side, price, size))
        elif kind != "noop":
            raise ValueError("unsupported Coinbase lifecycle")
        self.sequence, self.ready = sequence, True
        self._remember_source_time(source_time)
        return "update"

    def _validate_source_time(self, source_time: str | None) -> None:
        """Reject a supplied source clock that moves behind an applied message."""
        if source_time is not None and self._source_clock_ns is not None:
            if Wire.source_nanoseconds(source_time) < self._source_clock_ns:
                raise ValueError("Coinbase source time moved backwards")

    def _remember_source_time(self, source_time: str | None) -> None:
        """Retain exact supplied source text while clearing unknown current clocks."""
        if source_time is None:
            self.source_time = None
            return
        self._source_clock_ns = Wire.source_nanoseconds(source_time)
        self.source_time = source_time

    @property
    def source_ns(self) -> int | None:
        """Project the retained native clock to exact Unix nanoseconds.

        Returns:
            Original source instant, or None when absent.
        """
        if self.source_time is None:
            return None
        return Wire.source_nanoseconds(self.source_time)
