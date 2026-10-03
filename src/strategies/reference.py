"""Provide exact book-driven reference policies for bounded paper workloads."""

from __future__ import annotations

# standard library imports
import hashlib
import math
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import Currency, DecimalGrid, Price, Quantity
from research.observations import NumericField
from serialization import DomainCodec
from strategies.decisions import DecisionContext, DecisionTransition
from strategies.intents import OrderIntent, TargetIntent

# The opening clip bids this far through the ask: enough to stay marketable against a
# modeled adverse execution cost at any price level, inside a 500 bps deviation limit.
_OPENING_THROUGH = Fraction(200, 10_000)


class _ClipParameters:
    """Bind the exact spot clip, admitted tick and installed implementation of a policy."""

    fields = (
        NumericField(name="ask", units="quote/base"),
        NumericField(name="bid", units="quote/base"),
        NumericField(name="ask_size", units="base"),
    )

    def __init__(
        self,
        quantity: Quantity,
        currency: Currency,
        lot: Quantity,
        *,
        tick: Price,
        implementation: str,
    ) -> None:
        """Bind exact spot units, the admitted price tick and the installed implementation."""
        if (
            type(quantity) is not Quantity
            or type(currency) is not Currency
            or type(lot) is not Quantity
            or type(tick) is not Price
        ):
            raise TypeError("reference clip requires quantity, currency, lot and tick")
        quantity.model_copy()
        currency.model_copy()
        lot.model_copy()
        tick.model_copy()
        if (
            quantity.value <= 0
            or lot.value <= 0
            or tick.value <= 0
            or tick.currency != currency
            or tick.per != quantity.dimension
            or quantity.dimension != lot.dimension
            or Fraction(quantity.value) % Fraction(lot.value)
            or type(implementation) is not str
            or len(implementation) != 64
            or any(character not in "0123456789abcdef" for character in implementation)
        ):
            raise ValueError("invalid reference clip parameters")
        self.quantity, self.currency, self.lot, self.tick = quantity, currency, lot, tick
        self.implementation = implementation

    @property
    def identity(self) -> str:
        """Bind policy formula, exact parameters and installed implementation."""
        return hashlib.sha256(
            DomainCodec().encode_json(
                (
                    self.implementation,
                    type(self).__name__,
                    self.quantity,
                    self.currency,
                    self.lot,
                    self.tick,
                )
            )
        ).hexdigest()

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require the exact named two-sided book signature without prediction."""
        if fields != self.fields or prediction is not None:
            raise ValueError("reference clip requires the named book signature")

    def initial_state(self) -> bytes:
        """Start an independent decision count for each instance."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Reject foreign, negative or noncanonical counters."""
        if type(state) is not bytes or not state.isdigit() or str(int(state)).encode() != state:
            raise ValueError("invalid reference clip state")


class ReferenceClipPolicy(_ClipParameters):
    """Buy one fixed opening clip, then leave nonmarketable book interests.

    Prices scale with the price level: the opening clip bids 200 bps through the ask,
    rounded up onto the admitted tick grid, and later interests rest one tick below
    the best bid, or at it when the bid is a single tick.
    """

    @property
    def output(self) -> Literal["order"]:
        """Declare portable order intents for independent account admission."""
        return "order"

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Take the first displayed ask and place later bids at or below the touch."""
        context.__post_init__()
        self.validate_state(state)
        self.admit(
            context.features.fields,
            None if context.prediction is None else context.prediction.field,
        )
        ask, bid, _ = context.features.values
        if ask is None or bid is None:
            raise ValueError("reference clip requires an eligible two-sided book")
        ask_value = Fraction(int(ask.numerator), int(ask.denominator))
        bid_value = Fraction(int(bid.numerator), int(bid.denominator))
        if bid_value <= 0 or ask_value <= bid_value:
            raise ValueError("reference clip requires positive uncrossed prices")
        tick = Fraction(self.tick.value)
        if state == b"0":
            raw = math.ceil(ask_value * (1 + _OPENING_THROUGH) / tick) * tick
        else:
            raw = bid_value - tick if bid_value > tick else bid_value
        price = Price(
            value=DecimalGrid.exact_decimal(raw),
            currency=self.currency,
            per=self.quantity.dimension,
        )
        return DecisionTransition(
            intent=OrderIntent(
                side="buy",
                quantity=self._order_quantity(context),
                limit=price,
                time_in_force="gtc",
            ),
            state=str(int(state) + 1).encode(),
        )

    def _order_quantity(self, context: DecisionContext) -> Quantity:
        """Use the configured fixed clip for every retained interest."""
        return self.quantity


class LiquidityClipPolicy(ReferenceClipPolicy):
    """Scale a fixed clip to half the visible ask size in whole lots."""

    def _order_quantity(self, context: DecisionContext) -> Quantity:
        """Cap the clip at visible half-liquidity, retaining a one-lot minimum."""
        size = context.features.values[2]
        if size is None:
            raise ValueError("liquidity clip requires positive visible size")
        visible = Fraction(int(size.numerator), int(size.denominator))
        if visible <= 0:
            raise ValueError("liquidity clip requires positive visible size")
        lot = Fraction(self.lot.value)
        lots = max(1, (visible / 2) // lot)
        clipped = min(Fraction(self.quantity.value), lots * lot)
        return Quantity(
            value=DecimalGrid.exact_decimal(clipped),
            dimension=self.quantity.dimension,
        )


class TargetClipPolicy(_ClipParameters):
    """Hold one constant long clip as an absolute target position.

    The account lowers an unmet target to one immediate-or-cancel buy at the ask, so
    the position opens within a few selected books. Every later checkpoint then
    commits as ``target_matched`` without an order, including after a recovery that
    retains the position. This engineering workload makes no profitability claim.
    """

    @property
    def output(self) -> Literal["target"]:
        """Declare absolute target-position output."""
        return "target"

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Request the same target at every eligible two-sided book."""
        context.__post_init__()
        self.validate_state(state)
        self.admit(
            context.features.fields,
            None if context.prediction is None else context.prediction.field,
        )
        ask, bid, _ = context.features.values
        if ask is None or bid is None:
            raise ValueError("reference clip requires an eligible two-sided book")
        return DecisionTransition(
            intent=TargetIntent(quantity=self.quantity),
            state=str(int(state) + 1).encode(),
        )


type ReferencePolicyName = Literal["fixed_clip", "liquidity_clip", "target_clip"]


class ReferencePolicies:
    """Construct the explicitly named installed reference formulas."""

    @staticmethod
    def create(
        name: ReferencePolicyName,
        quantity: Quantity,
        currency: Currency,
        lot: Quantity,
        *,
        tick: Price,
        implementation: str,
    ) -> ReferenceClipPolicy | TargetClipPolicy:
        """Construct the explicitly named installed reference formula without fallback."""
        factories: dict[str, type[ReferenceClipPolicy] | type[TargetClipPolicy]] = {
            "fixed_clip": ReferenceClipPolicy,
            "liquidity_clip": LiquidityClipPolicy,
            "target_clip": TargetClipPolicy,
        }
        factory = factories.get(name)
        if factory is None:
            raise ValueError("unknown reference policy")
        return factory(quantity, currency, lot, tick=tick, implementation=implementation)
