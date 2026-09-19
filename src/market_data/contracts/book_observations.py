"""Admit bounded saved native book histories without granting causal or execution use."""

from __future__ import annotations

# standard library imports
import re
from decimal import Decimal

# third party library imports
import msgspec

# project library imports
from market_data.contracts.levels import Level
from market_data.contracts.orders import Order


class BookObservation(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Retain one whole message boundary; positions address the manifest's original raw object.

    Orders are native L3 identities; bid/ask entries are aggregate L2 levels. Empty
    state on a control or invalid boundary must not be interpreted as an empty book.
    Full visible state is retained on market boundaries for this bounded reference
    format. Unknown archive receipt/availability and sequence remain None.
    """

    position: int
    epoch: int | None
    received_ns: int | None
    source_time: str | None
    sequence: int | None
    outcome: str
    status: str
    reason: str
    state_identity: str
    orders: tuple[Order, ...] = ()
    bids: tuple[tuple[Decimal, Level], ...] = ()
    asks: tuple[tuple[Decimal, Level], ...] = ()
    transition_ns: int | None = None
    last_durable_ns: int | None = None

    def __post_init__(self) -> None:
        """Reject malformed coordinates, status, state identity and mixed representations."""
        if (
            any(
                value is not None and (type(value) is not int or value < 0)
                for value in (
                    self.position,
                    self.epoch,
                    self.received_ns,
                    self.sequence,
                    self.transition_ns,
                    self.last_durable_ns,
                )
            )
            or type(self.position) is not int
        ):
            raise ValueError("invalid book occurrence coordinates")
        if (
            self.status not in ("degraded", "stale", "recovering", "unavailable")
            or not isinstance(self.reason, str)
            or not self.reason
            or not isinstance(self.outcome, str)
            or not self.outcome
            or not isinstance(self.state_identity, str)
            or not re.fullmatch(r"[a-f0-9]{64}", self.state_identity)
            or (self.source_time is not None and not isinstance(self.source_time, str))
            or any(type(rows) is not tuple for rows in (self.orders, self.bids, self.asks))
            or (self.orders and (self.bids or self.asks))
        ):
            raise ValueError("invalid book state or quality scope")
        for order in self.orders:
            if type(order) is not Order:
                raise ValueError("book orders require native L3 records")
            order.__post_init__()
        for price, level in self.bids + self.asks:
            if type(price) is not Decimal or not price.is_finite() or price <= 0:
                raise ValueError("book levels require positive exact prices")
            if type(level) is not Level:
                raise ValueError("book levels require aggregate size and order count")
            level.__post_init__()
        if len({order.order_id for order in self.orders}) != len(self.orders) or any(
            len({price for price, _ in side}) != len(side) for side in (self.bids, self.asks)
        ):
            raise ValueError("duplicate native order or aggregate price in canonical state")
