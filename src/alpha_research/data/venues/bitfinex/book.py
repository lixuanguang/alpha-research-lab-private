"""Apply sequenced Bitfinex R0 snapshots and individual order updates."""

from __future__ import annotations

# project library imports
from alpha_research.data.live.book import Order, VisibleBook, Wire
from alpha_research.data.live.config import CaptureConfig


class BitfinexBook(VisibleBook):
    """Track one acknowledged bounded raw-book channel within a connection epoch."""

    def __init__(self, config: CaptureConfig) -> None:
        """Bind native symbol/depth and start unsynchronized until the first snapshot.

        Args:
            config: Validated native spot source selection and resource budgets.
        """
        super().__init__(config.max_orders)
        self.config = config
        self.channel_id: int | None = None
        self.configured = False
        self.acknowledged = False
        self.source_time: str | None = None

    def apply(self, raw: bytes, *, snapshot: bool = False) -> str:
        """Validate one atomic source frame, returning control/snapshot/update/heartbeat.

        Raises:
            ValueError: Schema, subscription, continuity or order state is invalid.

        Args:
            raw: Original received JSON bytes, before any numeric conversion.
            snapshot: Whether these bytes are the independently received REST L3 snapshot.

        Returns:
            Source-message classification for the applied boundary.
        """
        if snapshot:
            raise ValueError("Bitfinex uses the WebSocket snapshot")
        value = Wire.decode(raw)
        if isinstance(value, dict):
            return self._control(Wire.mapping(value))
        frame = Wire.array(value)
        if len(frame) == 3 and frame[1] == "hb" and self.configured and self.channel_id is None:
            # A live heartbeat can race the subscribed acknowledgement. It proves
            # liveness only; snapshot admission still requires the matching ack.
            self.channel_id = Wire.integer(frame[0])
        if len(frame) != 3 or Wire.integer(frame[0]) != self.channel_id:
            raise ValueError("unacknowledged or malformed sequenced R0 frame")
        sequence = Wire.integer(frame[2])
        if self.sequence is not None and sequence != self.sequence + 1:
            raise ValueError("Bitfinex sequence gap or duplicate")
        self.sequence = sequence
        if frame[1] == "hb":
            return "heartbeat"
        if not self.acknowledged:
            raise ValueError("R0 market frame before subscription acknowledgement")
        entries = Wire.array(frame[1])
        if not self.ready:
            for entry in entries:
                self._update(Wire.array(entry), initial=True)
            self.ready = True
            return "snapshot"
        self._update(entries, initial=False)
        return "update"

    def _control(self, message: dict[str, object]) -> str:
        """Verify negotiation and server maintenance/reconnect notices."""
        event = message.get("event")
        if event == "conf":
            if message.get("status") != "OK" or message.get("flags") != 65536:
                raise ValueError("Bitfinex sequence configuration rejected")
            self.configured = True
        elif event == "subscribed":
            if not self.configured or any(
                (
                    message.get("channel") != "book",
                    message.get("symbol") != self.config.symbol,
                    message.get("prec") != "R0",
                    message.get("freq") != "F0",
                    str(message.get("len")) != str(self.config.depth),
                )
            ):
                raise ValueError("Bitfinex subscription mismatch")
            channel_id = Wire.integer(message.get("chanId"))
            if self.channel_id is not None and self.channel_id != channel_id:
                raise ValueError("Bitfinex heartbeat channel differs from acknowledgement")
            self.channel_id = channel_id
            self.acknowledged = True
        elif event == "info":
            if message.get("code") in (20051, 20060, 20061):
                raise ValueError("Bitfinex restart or maintenance requires fresh session")
            if "platform" in message and Wire.mapping(message["platform"]).get("status") != 1:
                raise ValueError("Bitfinex platform unavailable")
        else:
            raise ValueError("Bitfinex unsupported control or subscription error")
        return "control"

    def _update(self, entry: list[object], *, initial: bool) -> None:
        """Use price zero for removal and signed amount for side and absolute size."""
        if len(entry) != 3:
            raise ValueError("invalid R0 order tuple")
        order_id = str(Wire.integer(entry[0]))
        price, amount = Wire.decimal(entry[1]), Wire.decimal(entry[2])
        if price == 0:
            if initial or amount not in (-1, 1):
                raise ValueError("invalid R0 deletion")
            self.remove(order_id)
        else:
            if initial and order_id in self.orders:
                raise ValueError("duplicate R0 snapshot order")
            self.set(Order(order_id, "buy" if amount > 0 else "sell", price, amount.copy_abs()))
