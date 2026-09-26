"""Context-independent finite decimal operations for native venue quantities."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from typing import cast

# project library imports
from execution.venues.contracts import VenueProtocolError


class VenueExactDecimal:
    """Subtract bounded decimal lexemes without ambient Decimal context rounding."""

    @staticmethod
    def difference(left: Decimal, right: Decimal) -> Decimal:
        """Construct an exact finite difference from aligned base-ten coefficients."""
        left_parts = left.as_tuple()
        right_parts = right.as_tuple()
        left_exponent = cast(object, left_parts.exponent)
        right_exponent = cast(object, right_parts.exponent)
        if (
            not isinstance(left_exponent, int)
            or not isinstance(right_exponent, int)
            or not -100 <= left_exponent <= 100
            or not -100 <= right_exponent <= 100
            or len(left_parts.digits) > 100
            or len(right_parts.digits) > 100
        ):
            raise VenueProtocolError("venue decimal exceeds exact arithmetic bound")
        left_exponent_int: int = left_exponent
        right_exponent_int: int = right_exponent
        exponent: int = min(left_exponent_int, right_exponent_int)
        left_coefficient = int("".join(str(digit) for digit in left_parts.digits))
        right_coefficient = int("".join(str(digit) for digit in right_parts.digits))
        if left_parts.sign:
            left_coefficient = -left_coefficient
        if right_parts.sign:
            right_coefficient = -right_coefficient
        left_scale = int("1" + "0" * (left_exponent_int - exponent))
        right_scale = int("1" + "0" * (right_exponent_int - exponent))
        coefficient = left_coefficient * left_scale - right_coefficient * right_scale
        digits = tuple(int(digit) for digit in str(abs(coefficient)))
        return Decimal((1 if coefficient < 0 else 0, digits, exponent))
