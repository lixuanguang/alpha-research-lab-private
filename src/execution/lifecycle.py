"""Own portable intent lowering and exact spot order lifecycle transitions."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from fractions import Fraction
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from execution.records import MarketTouch, OrderEvent, OrderState, OrderStatus
from financial_units import DecimalGrid, Quantity
from risk import SpotLimits
from strategies import ExposureIntent, OrderIntent, QuoteIntent, TargetIntent


class SpotOrderLifecycle:
    """Share spot intent and lifecycle semantics across dedicated and shared accounts."""

    def __init__(self, limits: SpotLimits) -> None:
        """Bind declared fixture or reference-qualified spot mechanics."""
        limits.__post_init__()
        self.limits = limits

    def lower(
        self,
        intent: TargetIntent | ExposureIntent | OrderIntent | QuoteIntent,
        holding: Quantity,
        touch: MarketTouch | None,
    ) -> tuple[tuple[str, OrderIntent], ...]:
        """Lower target/exposure intent to one bounded IOC, retaining quote child legs.

        The IOC crosses the touch on its own side, a buy at the ask and a sell at
        the bid. Exposure converts to whole lots at the touch midpoint, as research
        simulation converts it.
        """
        if isinstance(intent, OrderIntent):
            return (("order", intent),)
        if isinstance(intent, QuoteIntent):
            return (("bid", intent.bid), ("ask", intent.ask))
        if touch is None or any(
            self.limits.price_reason(price) is not None for price in (touch.bid, touch.ask)
        ):
            raise ValueError("missing_or_invalid_reference_price")
        if isinstance(intent, ExposureIntent):
            if intent.exposure.currency != touch.ask.currency or intent.exposure.value < 0:
                raise ValueError("incompatible_exposure")
            units = Fraction(intent.exposure.value) / touch.midpoint()
            lot_count = units // Fraction(self.limits.lot.value)
            target = Quantity(
                value=DecimalGrid.exact_decimal(
                    Fraction(lot_count) * Fraction(self.limits.lot.value)
                ),
                dimension=self.limits.lot.dimension,
            )
        else:
            target = intent.quantity
        if target.dimension != holding.dimension:
            raise ValueError("incompatible_target_dimension")
        delta = target - holding
        if delta.value == 0:
            return ()
        side: Literal["buy", "sell"] = "buy" if delta.value > 0 else "sell"
        order = OrderIntent(
            side=side,
            quantity=Quantity(value=delta.value.copy_abs(), dimension=target.dimension),
            limit=touch.crossed_by(side),
            time_in_force="ioc",
        )
        return (("target", order),)

    def order_reason(self, intent: OrderIntent) -> str | None:
        """Apply selected reference grids or explicit fixture grids without authority."""
        if self.limits.specification_identity is not None:
            return self.limits.order_reason(intent.quantity, intent.limit)
        if intent.quantity.dimension != self.limits.lot.dimension:
            return "incompatible_quantity"
        if intent.quantity.value < self.limits.lot.value:
            return "minimum_order_quantity"
        if (Fraction(intent.quantity.value) / Fraction(self.limits.lot.value)).denominator != 1:
            return "off_lot_order"
        return self.limits.price_reason(intent.limit)

    def transition(
        self, order: OrderState, event: OrderEvent, *, last_fill_at: datetime | None = None
    ) -> OrderState:
        """Keep acknowledgement, acceptance, cancellation and fills separate."""
        if order.is_terminal:
            raise ValueError("terminal order cannot receive another economic transition")
        if event.kind == "request_ack":
            return replace(
                order,
                request_acknowledged=True,
                status=(
                    "request_ack" if order.status in ("intent", "request_ack") else order.status
                ),
            )
        if event.kind == "accepted":
            accepted_status = (
                order.status
                if order.status in ("cancel_requested", "cancel_ack")
                else "partial"
                if order.filled.value
                else "accepted"
            )
            return replace(order, accepted=True, status=accepted_status)
        if event.kind == "cancel_requested":
            if order.cancel_requested:
                raise ValueError("cancel request is already pending")
            if order.status == "unknown":
                # Only reconciliation resolves an unknown outcome; the request waits beside it.
                return replace(order, cancel_requested=True)
            return replace(order, cancel_requested=True, status="cancel_requested")
        if event.kind == "cancel_ack":
            if not order.cancel_requested:
                raise ValueError("cancel acknowledgement requires a cancel request")
            if order.status == "unknown":
                # Reconciliation, not the acknowledgement, resolves an unknown outcome.
                return replace(order, cancel_acknowledged=True)
            return replace(order, cancel_acknowledged=True, status="cancel_ack")
        if event.kind == "cancelled":
            if order.status == "intent":
                raise ValueError("cancellation requires an order outcome")
            return replace(order, status="cancelled")
        if event.kind == "cancelled_on_request":
            # The fact names its cause, so it must have a request to name. An unknown
            # outcome gives no evidence that the request took effect, so this fact
            # never ends one.
            if not order.cancel_requested or order.status == "unknown":
                raise ValueError("requested cancellation requires a pending cancel request")
            return replace(order, status="cancelled")
        if event.kind == "rejected":
            return replace(order, status="rejected")
        if event.kind == "unknown":
            return replace(order, status="unknown")
        if event.kind == "reconcile_open":
            if order.status != "unknown":
                raise ValueError("open reconciliation requires an unknown outcome")
            if order.cancel_acknowledged:
                return replace(order, accepted=True, status="cancel_ack")
            if order.cancel_requested:
                return replace(order, accepted=True, status="cancel_requested")
            return replace(
                order, accepted=True, status="partial" if order.filled.value else "accepted"
            )
        if event.kind in ("reconcile_cancelled", "reconcile_rejected"):
            if order.status != "unknown":
                raise ValueError("terminal reconciliation requires an unknown outcome")
            return replace(
                order, status="cancelled" if event.kind == "reconcile_cancelled" else "rejected"
            )
        if event.kind != "fill" or event.fill is None:
            raise ValueError("unsupported paper order transition")
        fill = event.fill
        expected_sign = 1 if order.intent.side == "buy" else -1
        if (
            fill.decision_at != order.decision_at
            or fill.filled_at > event.at
            or fill.quantity.dimension != order.intent.quantity.dimension
            or (fill.quantity.value <= 0 if expected_sign == 1 else fill.quantity.value >= 0)
            or fill.quantity.value.copy_abs() > order.remaining.value
            or fill.fee.currency != order.intent.limit.currency
            or fill.effective.currency != order.intent.limit.currency
            or fill.effective.per != order.intent.limit.per
            or (order.intent.side == "buy" and fill.effective.value > order.intent.limit.value)
            or (order.intent.side == "sell" and fill.effective.value < order.intent.limit.value)
            or (order.paid_fee + fill.fee).value > order.maximum_fee.value
        ):
            raise ValueError("fill exceeds order economics or limit")
        if fill.filled_at < (last_fill_at if last_fill_at is not None else order.decision_at):
            raise ValueError("fill is older than the posted account ledger")
        filled = order.filled + Quantity(
            value=fill.quantity.value.copy_abs(), dimension=order.filled.dimension
        )
        status: OrderStatus
        if filled.value == order.intent.quantity.value:
            status = "filled"
        elif order.status in ("unknown", "cancel_requested", "cancel_ack"):
            status = order.status
        else:
            status = "partial"
        return replace(
            order,
            status=status,
            accepted=True,
            filled=filled,
            paid_fee=order.paid_fee + fill.fee,
        )
