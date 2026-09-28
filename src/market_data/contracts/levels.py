"""Define exact aggregate levels shared by native and canonical book records."""

from __future__ import annotations

# standard library imports
from decimal import Decimal

# third party library imports
import msgspec

# project library imports


class Level(msgspec.Struct, frozen=True, forbid_unknown_fields=True, gc=False):
    """Exact aggregate size and reported order count at a native price level.

    Valid levels contain only exact Decimal and int values, which cannot form
    reference cycles. Reference counting releases these immutable leaves without
    repeatedly scanning every retained L2 snapshot for cycles. Adding references
    or accepting scalar subclasses requires revisiting this GC setting.
    """

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
