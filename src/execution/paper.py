"""Match suppressed spot orders against a declared finite top-of-book scenario."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

# project library imports
from accounting import Fill
from execution.journal import PaperOrderJournal
from execution.records import EventKind, OrderEvent, OrderState
from financial_units import DecimalGrid, Money, Price, Quantity, Rounding
from serialization import DomainCodec, WireRecord


class PaperMarket(WireRecord, frozen=True):
    """Carry an eligible received quote with independently bounded displayed liquidity.

    ``at`` is effective availability, not a fabricated exchange timestamp. One
    snapshot grants at most its displayed quantity per side to this dedicated
    account. This no-impact scenario models neither queue priority nor other
    participants' reactions and cannot establish venue fill fidelity.
    """

    identity: str
    at: datetime
    bid: Price
    ask: Price
    bid_quantity: Quantity
    ask_quantity: Quantity

    def __post_init__(self) -> None:
        """Require positive, uncrossed quotes and explicit compatible liquidity units."""
        self._require_utc(self.at, field_name="market availability")
        for value in (self.bid, self.ask, self.bid_quantity, self.ask_quantity):
            value.model_copy()
        if (
            type(self.identity) is not str
            or not self.identity
            or self.bid.value <= 0
            or self.ask.value <= self.bid.value
            or self.bid.currency != self.ask.currency
            or self.bid.per != self.ask.per
            or self.bid_quantity.dimension != self.bid.per
            or self.ask_quantity.dimension != self.bid.per
            or self.bid_quantity.value < 0
            or self.ask_quantity.value < 0
        ):
            raise ValueError("invalid paper market quote")


class PaperMatcher:
    """Generate identified paper facts without constructing a venue transport.

    Marketable GTC/IOC orders take displayed liquidity at the observed touch.
    Post-only orders reject if marketable at their first later quote; resting
    orders fill only when a subsequent touch crosses their limit. Cancellation
    completes at the next received quote. These conservative declared rules are
    deterministic software assumptions, not inferred exchange mechanics.
    """

    def __init__(self, journal: PaperOrderJournal, *, fee_rate: Decimal, lot: Quantity) -> None:
        """Bind exact fee rounding and lot size to an already fenced journal."""
        DecimalGrid.require_decimal(fee_rate)
        lot.model_copy()
        if not Decimal(0) <= fee_rate < Decimal(1) or lot.value <= 0:
            raise ValueError("invalid paper matching costs or lot")
        self._journal, self._fee_rate, self._lot = journal, fee_rate, lot

    def match(self, market: PaperMarket, *, epoch: int) -> None:
        """Apply a quote once per order, recovering a partly committed quote after restart.

        Already posted fills consume the same quote's liquidity on replay. Unknown
        outcomes remain reserved and require explicit reconciliation; matching
        cannot turn uncertainty into an automatic resend or an invented fill.
        """
        market.__post_init__()
        if market.bid.per != self._lot.dimension:
            raise ValueError("paper market belongs to another instrument")
        self._journal.claim_market(
            epoch=epoch,
            identity=market.identity,
            payload=DomainCodec().encode_json(market),
        )
        consumed_buy, consumed_sell = Fraction(0), Fraction(0)
        prior = self._journal.events()
        identities = {item.event.identity for item in prior}
        for item in prior:
            if item.event.identity == self._identity(market, item.order, "fill"):
                fill = item.event.fill
                if fill is not None:
                    if fill.quantity.value > 0:
                        consumed_buy += Fraction(fill.quantity.value)
                    else:
                        consumed_sell -= Fraction(fill.quantity.value)
        available = {
            "buy": max(Fraction(0), Fraction(market.ask_quantity.value) - consumed_buy),
            "sell": max(Fraction(0), Fraction(market.bid_quantity.value) - consumed_sell),
        }
        for order in self._journal.orders():
            if order.is_terminal or order.status == "unknown" or market.at <= order.decision_at:
                continue
            if order.status in ("cancel_requested", "cancel_ack"):
                self._event(market, order, "cancelled", epoch)
                continue
            touch = market.ask if order.intent.side == "buy" else market.bid
            crosses = (
                touch.value <= order.intent.limit.value
                if order.intent.side == "buy"
                else touch.value >= order.intent.limit.value
            )
            if not order.accepted:
                self._event(market, order, "request_ack", epoch)
                if order.intent.time_in_force == "post-only" and crosses:
                    self._event(market, order, "rejected", epoch)
                    continue
                self._event(market, order, "accepted", epoch)
            fill_id = self._identity(market, order, "fill")
            if crosses and fill_id not in identities:
                size = min(Fraction(order.remaining.value), available[order.intent.side])
                lots = size // Fraction(self._lot.value)
                size = lots * Fraction(self._lot.value)
                if size:
                    signed = size if order.intent.side == "buy" else -size
                    quantity = Quantity(
                        value=DecimalGrid.exact_decimal(signed), dimension=self._lot.dimension
                    )
                    fee = Money(
                        value=DecimalGrid.round_fraction(
                            size * Fraction(touch.value) * Fraction(self._fee_rate),
                            touch.currency.minor_unit,
                            Rounding.HALF_EVEN,
                        ),
                        currency=touch.currency,
                    )
                    fill = Fill(
                        identity=fill_id,
                        decision_at=order.decision_at,
                        filled_at=market.at,
                        quantity=quantity,
                        reference=touch,
                        effective=touch,
                        fee=fee,
                    )
                    self._journal.apply_event(
                        epoch=epoch,
                        event=OrderEvent(
                            identity=fill_id,
                            order_id=order.identity,
                            at=market.at,
                            kind="fill",
                            fill=fill,
                        ),
                    )
                    available[order.intent.side] -= size
            if order.intent.time_in_force == "ioc":
                current = next(o for o in self._journal.orders() if o.identity == order.identity)
                if not current.is_terminal:
                    self._event(market, order, "cancelled", epoch)

    def _event(self, market: PaperMarket, order: OrderState, kind: EventKind, epoch: int) -> None:
        """Append one deterministic non-fill matching observation."""
        if kind not in ("request_ack", "accepted", "rejected", "cancelled"):
            raise ValueError("unsupported matching event")
        self._journal.apply_event(
            epoch=epoch,
            event=OrderEvent(
                identity=self._identity(market, order, kind),
                order_id=order.identity,
                at=market.at,
                kind=kind,
            ),
        )

    @staticmethod
    def _identity(market: PaperMarket, order: OrderState, kind: str) -> str:
        """Bind effects to exact market bytes, order and event kind across retries."""
        return hashlib.sha256(DomainCodec().encode_json((market, order.identity, kind))).hexdigest()
