"""Define exact aggregate levels shared by native and canonical book records."""

from __future__ import annotations

# standard library imports
from decimal import Decimal

# third party library imports
import msgspec

# project library imports


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
