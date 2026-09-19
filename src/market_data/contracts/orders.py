"""Define exact order values shared by reconstruction and canonical observations."""

from __future__ import annotations

# standard library imports
from decimal import Decimal

# third party library imports
import msgspec

# project library imports


class Order(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """A visible resting order; no queue rank or simulated fill is inferred."""

    order_id: str
    side: str
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        """Reject invalid order identities, sides and nonpositive exact values."""
        if not self.order_id or self.side not in ("buy", "sell"):
            raise ValueError("invalid order identity or side")
        for value in (self.price, self.size):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError("orders require positive exact price and size")
