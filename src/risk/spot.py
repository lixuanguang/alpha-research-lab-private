"""Reject unsupported targets and unaffordable executions independently of strategy logic."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from fractions import Fraction

# project library imports
from financial_units import Money, Price, Quantity, QuantityKind
from serialization import WireRecord


class SpotLimits(WireRecord, frozen=True):
    """Declare explicit product, grid, currency and unlevered holding limits."""

    maximum: Quantity
    lot: Quantity
    tick: Price
    product: str

    def __post_init__(self) -> None:
        """Refuse unsupported mechanics and inconsistent or off-grid limits."""
        if (
            type(self.maximum) is not Quantity
            or type(self.lot) is not Quantity
            or type(self.tick) is not Price
        ):
            raise TypeError("spot limits require typed quantities and price")
        for item in (self.maximum, self.lot, self.tick):
            item.model_copy()
        if (
            self.product != "spot"
            or self.maximum.dimension.kind != QuantityKind.BASE_UNIT
            or self.maximum.dimension != self.lot.dimension
            or self.tick.per != self.lot.dimension
            or self.lot.value <= 0
            or self.tick.value <= 0
            or self.maximum.value <= 0
            or (Fraction(self.maximum.value) / Fraction(self.lot.value)).denominator != 1
        ):
            raise ValueError("only consistent cash-funded base-unit spot limits are supported")

    def target_reason(self, target: Quantity, holding: Quantity, *, pending: bool) -> str | None:
        """Check a requested target against authoritative holdings and pending reservations.

        Args:
            target: Strategy's desired absolute holding; never silently resized.
            holding: Actual posted position.
            pending: Whether the sole intent slot already reserves exposure.

        Returns:
            Stable rejection reason, or None if the target passes independent limits.
        """
        self.__post_init__()
        target.model_copy()
        holding.model_copy()
        if (
            target.dimension != self.maximum.dimension
            or holding.dimension != self.maximum.dimension
        ):
            return "incompatible_quantity"
        if pending:
            return "pending_intent"
        if target.value < 0 or target.value > self.maximum.value:
            return "holding_limit"
        if (Fraction(target.value) / Fraction(self.lot.value)).denominator != 1:
            return "off_lot_target"
        return None

    def price_reason(self, price: Price) -> str | None:
        """Validate an exact reference price on the selected tick and currency.

        Args:
            price: Candidate source price.

        Returns:
            Rejection reason, or None for a supported positive on-grid reference.
        """
        price.model_copy()
        if price.per != self.tick.per or price.currency != self.tick.currency:
            return "incompatible_price"
        if price.value <= 0 or (Fraction(price.value) / Fraction(self.tick.value)).denominator != 1:
            return "invalid_reference_price"
        return None

    def fill_reason(
        self, delta: Quantity, effective: Price, fee: Money, cash: Money, holding: Quantity
    ) -> str | None:
        """Recheck actual cost and exposure immediately before posting a complete fill.

        Args:
            delta: Signed full quantity change.
            effective: Adverse execution price.
            fee: Rounded nonnegative quote-currency charge.
            cash: Actual available cash; pending orders cannot borrow.
            holding: Actual holdings, excluding unfilled reservations.

        Returns:
            Stable rejection reason; no accounting state is mutated.
        """
        target = holding + delta
        reason = self.target_reason(target, holding, pending=False)
        if reason is not None:
            return reason
        if self.price_reason(effective) is not None or fee.value < Decimal(0):
            return "invalid_execution_cost"
        if cash.currency != self.tick.currency or fee.currency != self.tick.currency:
            return "incompatible_cash"
        if (cash - effective.amount(delta) - fee).value < 0:
            return "insufficient_cash"
        return None
