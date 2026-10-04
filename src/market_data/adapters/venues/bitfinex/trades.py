"""Apply the sequenced Bitfinex public trades channel as a durable trade tape."""

from __future__ import annotations

# project library imports
from configuration import CaptureConfig
from market_data.adapters.wire import Wire
from market_data.books import TradeTape
from market_data.contracts import PublicTrade


class BitfinexTrades(TradeTape):
    """Validate one acknowledged trades channel with connection sequence numbers.

    The first channel message is the recent-trade snapshot. An execution (``te``)
    and its later confirmation (``tu``) carry the same trade ID, so whichever comes
    second is a duplicate. A signed amount gives the aggressor side.
    """

    def __init__(self, config: CaptureConfig) -> None:
        """Bind the native trading pair; synchronized from the first snapshot."""
        super().__init__()
        self.config = config
        self.channel_id: int | None = None
        self.configured = False
        self.acknowledged = False

    def apply(self, raw: bytes, *, snapshot: bool = False) -> str:
        """Validate one control, heartbeat, snapshot or trade frame.

        Raises:
            ValueError: Schema, subscription or sequence continuity is invalid.
        """
        if snapshot:
            raise ValueError("Bitfinex trades uses the WebSocket snapshot")
        value = Wire.decode(raw)
        if isinstance(value, dict):
            return self._control(Wire.mapping(value))
        frame = Wire.array(value)
        if len(frame) == 3 and frame[1] == "hb" and self.configured and self.channel_id is None:
            # A heartbeat can race the acknowledgement; it proves liveness only.
            self.channel_id = Wire.integer(frame[0])
        if len(frame) not in (3, 4) or Wire.integer(frame[0]) != self.channel_id:
            raise ValueError("unacknowledged or malformed sequenced trades frame")
        sequence = Wire.integer(frame[-1])
        if self.sequence is not None and sequence != self.sequence + 1:
            raise ValueError("Bitfinex sequence gap or duplicate")
        self.sequence = sequence
        if len(frame) == 3 and frame[1] == "hb":
            return "heartbeat"
        if not self.acknowledged:
            raise ValueError("trades frame before subscription acknowledgement")
        if len(frame) == 3:
            if self.ready:
                raise ValueError("repeated Bitfinex trades snapshot")
            self._admit(tuple(self._trade(entry) for entry in reversed(Wire.array(frame[1]))))
            self.ready = True
            return "snapshot"
        if frame[1] not in ("te", "tu") or not self.ready:
            raise ValueError("unsupported Bitfinex trades event")
        return "update" if self._admit((self._trade(frame[2]),)) else "duplicate"

    def _control(self, message: dict[str, object]) -> str:
        """Verify negotiation and server maintenance notices."""
        event = message.get("event")
        if event == "conf":
            if message.get("status") != "OK" or message.get("flags") != 65536:
                raise ValueError("Bitfinex sequence configuration rejected")
            self.configured = True
        elif event == "subscribed":
            if (
                not self.configured
                or message.get("channel") != "trades"
                or message.get("symbol") != self.config.symbol
            ):
                raise ValueError("Bitfinex trades subscription mismatch")
            channel_id = Wire.integer(message.get("chanId"))
            if self.channel_id is not None and self.channel_id != channel_id:
                raise ValueError("Bitfinex heartbeat channel differs from acknowledgement")
            self.channel_id = channel_id
            self.acknowledged = True
        elif event == "info":
            if "version" in message and (
                type(message["version"]) is not int or message["version"] != 2
            ):
                raise ValueError("unsupported Bitfinex WebSocket version")
            if message.get("code") in (20051, 20060, 20061):
                raise ValueError("Bitfinex restart or maintenance requires fresh session")
            if "platform" in message and Wire.mapping(message["platform"]).get("status") != 1:
                raise ValueError("Bitfinex platform unavailable")
        else:
            raise ValueError("Bitfinex unsupported control or subscription error")
        return "control"

    @staticmethod
    def _trade(value: object) -> PublicTrade:
        """Decode ``[ID, MTS, AMOUNT, PRICE]`` with the signed amount as aggressor side."""
        entry = Wire.array(value)
        if len(entry) != 4:
            raise ValueError("invalid Bitfinex trade tuple")
        amount = Wire.decimal(entry[2])
        if amount == 0:
            raise ValueError("zero Bitfinex trade amount")
        return PublicTrade(
            trade_id=str(Wire.integer(entry[0])),
            event_ms=Wire.integer(entry[1]),
            price=Wire.decimal(entry[3]),
            quantity=amount.copy_abs(),
            side="buy" if amount > 0 else "sell",
        )
