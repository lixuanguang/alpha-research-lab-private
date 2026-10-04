"""Apply the OKX public spot trades channel as a durable trade tape."""

from __future__ import annotations

# project library imports
from market_data.adapters.wire import Wire
from market_data.books import TradeTape
from market_data.contracts import PublicTrade


class OKXTrades(TradeTape):
    """Validate one acknowledged OKX ``trades`` subscription and its pushed trades.

    The channel has no snapshot: the tape is synchronized from the acknowledgement,
    so trades before it are unknown. A pushed trade may aggregate fills at one price
    and side; its ID is the first fill's. The sequence is the high-water trade ID.
    """

    def __init__(self, symbol: str) -> None:
        """Bind the native spot instrument ID."""
        super().__init__()
        self.symbol = symbol
        self.acknowledged = False

    def apply(self, raw: bytes, *, snapshot: bool = False) -> str:
        """Validate an acknowledgement, heartbeat or trade push.

        Raises:
            ValueError: Identity, lifecycle or trade schema is invalid.
        """
        if snapshot:
            raise ValueError("OKX trades has no snapshot")
        if raw == b"pong":
            return "heartbeat"
        message = Wire.mapping(Wire.decode(raw))
        argument = Wire.mapping(message.get("arg"))
        if argument.get("channel") != "trades" or argument.get("instId") != self.symbol:
            raise ValueError("unexpected OKX trades subscription identity or service event")
        if message.get("event") == "subscribe":
            if self.acknowledged:
                raise ValueError("duplicate OKX trades acknowledgement")
            self.acknowledged = self.ready = True
            return "acknowledgement"
        if "event" in message or not self.acknowledged:
            raise ValueError("OKX error or unacknowledged trades")
        rows = Wire.array(message.get("data"))
        if not rows:
            raise ValueError("empty OKX trades push")
        trades: list[PublicTrade] = []
        for value in rows:
            row = Wire.mapping(value)
            side = row.get("side")
            if row.get("instId") != self.symbol or side not in ("buy", "sell"):
                raise ValueError("OKX trade identity or side mismatch")
            trades.append(
                PublicTrade(
                    trade_id=Wire.text(row.get("tradeId")),
                    event_ms=Wire.integer(row.get("ts")),
                    price=Wire.decimal(row.get("px")),
                    quantity=Wire.decimal(row.get("sz")),
                    side="buy" if side == "buy" else "sell",
                )
            )
        if not self._admit(tuple(trades)):
            return "duplicate"
        self.sequence = max(int(item.trade_id) for item in trades)
        return "update"
