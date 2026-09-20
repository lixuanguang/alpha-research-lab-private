"""Calculate adverse execution prices and round each fee exactly once."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

# project library imports
from accounting import Fill
from financial_units import DecimalGrid, Money, Price, Quantity, Rounding
from serialization import WireRecord


class SpotCosts(WireRecord, frozen=True):
    """Separate the baseline's half-even fees from the independent half-up oracle."""

    adverse: Price
    fee_rate: Decimal
    rounding: Literal["half_even", "half_up"]

    def __post_init__(self) -> None:
        """Require explicit nonnegative bounded costs and a supported rounding convention."""
        if type(self.adverse) is not Price:
            raise TypeError("adverse cost must be a dimensioned price")
        self.adverse.model_copy()
        DecimalGrid.require_decimal(self.fee_rate)
        if (
            self.adverse.value < 0
            or not Decimal(0) <= self.fee_rate < Decimal(1)
            or self.rounding not in ("half_even", "half_up")
        ):
            raise ValueError("invalid spot cost convention")

    def fill(
        self,
        identity: str,
        *,
        decision_at: datetime,
        filled_at: datetime,
        quantity: Quantity,
        reference: Price,
    ) -> Fill:
        """Price a complete signed fill without making an affordability decision.

        Args:
            identity: Stable intent/fill identity, independent of batch size.
            decision_at: UTC target creation clock.
            filled_at: UTC execution clock, strictly later than decision.
            quantity: Signed quantity; zero is unsupported.
            reference: Then-eligible positive reference trade price.

        Returns:
            Exact notional-compatible effective price and one rounded fee.

        Raises:
            ValueError: Prices, units, timing or numerical representability are unsupported.
        """
        self.__post_init__()
        effective = reference + self.adverse if quantity.value > 0 else reference - self.adverse
        notional = effective.amount(quantity)
        raw_fee = abs(Fraction(notional.value)) * Fraction(self.fee_rate)
        quantum = reference.currency.minor_unit
        if self.rounding == "half_even":
            fee = DecimalGrid.round_fraction(raw_fee, quantum, Rounding.HALF_EVEN)
        else:
            scaled = raw_fee / Fraction(quantum)
            rounded = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
            fee = DecimalGrid.exact_decimal(rounded * Fraction(quantum))
        return Fill(
            identity=identity,
            decision_at=decision_at,
            filled_at=filled_at,
            quantity=quantity,
            reference=reference,
            effective=effective,
            fee=Money(value=fee, currency=reference.currency),
        )
