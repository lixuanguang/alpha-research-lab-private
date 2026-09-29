"""Reject unsupported targets and unaffordable executions independently of strategy logic."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction

# project library imports
from financial_units import Currency, Money, Price, Quantity, QuantityKind
from reference_data.catalogs import ReferenceHistory
from serialization import WireRecord


class SpotLimits(WireRecord, frozen=True):
    """Declare explicit product, grid, currency and unlevered holding limits."""

    maximum: Quantity
    lot: Quantity
    tick: Price
    product: str
    specification_identity: str | None = None
    minimum_order: Quantity | None = None

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
        if (self.specification_identity is None) != (self.minimum_order is None):
            raise ValueError("reference-driven limits require minimum size and version together")
        if self.specification_identity is not None and (
            type(self.specification_identity) is not str
            or len(self.specification_identity) != 64
            or any(c not in "0123456789abcdef" for c in self.specification_identity)
        ):
            raise ValueError("invalid spot reference identity")
        if self.minimum_order is not None:
            if type(self.minimum_order) is not Quantity:
                raise TypeError("minimum order must be a native quantity")
            self.minimum_order.model_copy()
            if self.minimum_order.dimension != self.lot.dimension or self.minimum_order.value <= 0:
                raise ValueError("minimum order uses invalid units or value")
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

    @classmethod
    def from_reference(
        cls,
        history: ReferenceHistory,
        *,
        maximum: Quantity,
        quote_currency: Currency,
        valid_at: datetime,
        known_at: datetime,
        max_age: timedelta,
    ) -> SpotLimits:
        """Resolve evidenced spot grids before order admission, without granting authority.

        The caller supplies its independent maximum exposure and currency definition.
        Unknown, stale, synthetic or incomplete venue rules fail instead of falling
        back to authored simulation assumptions. The selected version is retained.
        """
        maximum.model_copy()
        quote_currency.validate_currency()
        spec = history.require_order(
            maximum.dimension.instrument_id, valid_at=valid_at, known_at=known_at, max_age=max_age
        )
        if (
            spec.instrument.quote_currency != quote_currency.code
            or spec.quantity_step is None
            or spec.price_tick is None
            or spec.minimum_quantity is None
        ):
            raise ValueError("spot order reference units or rules are unavailable")
        return cls(
            maximum=maximum,
            lot=Quantity(value=spec.quantity_step, dimension=maximum.dimension),
            tick=Price(value=spec.price_tick, currency=quote_currency, per=maximum.dimension),
            product="spot",
            specification_identity=spec.identity,
            minimum_order=Quantity(value=spec.minimum_quantity, dimension=maximum.dimension),
        )

    def order_reason(self, quantity: Quantity, price: Price) -> str | None:
        """Validate positive submitted size and price against the resolved venue version.

        This checks grids and minimum order size only. Account authority, reservations,
        exposure and independent runtime limits must also admit any actual order.
        """
        self.__post_init__()
        quantity.model_copy()
        if self.minimum_order is None:
            return "unknown_order_specification"
        if quantity.dimension != self.lot.dimension:
            return "incompatible_quantity"
        if quantity.value < self.minimum_order.value:
            return "minimum_order_quantity"
        if (Fraction(quantity.value) / Fraction(self.lot.value)).denominator != 1:
            return "off_lot_order"
        return self.price_reason(price)

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
