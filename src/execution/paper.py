"""Match suppressed spot orders against a declared finite top-of-book scenario."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction

# project library imports
from accounting import Fill
from configuration import PaperExecutionScenario
from execution.journal import PaperOrderJournal
from execution.records import EventKind, OrderEvent, OrderState
from financial_units import DecimalGrid, Money, Price, Quantity, Rounding
from serialization import DomainCodec, WireRecord


class PaperMarket(WireRecord, frozen=True):
    """Carry an eligible received quote with independently bounded displayed liquidity.

    ``at`` is effective availability, not a fabricated exchange timestamp. One
    snapshot grants at most its displayed quantity per side to the selected
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


class PaperTouchLiquidity(WireRecord, frozen=True):
    """Retain a conservative no-impact debt at one observed touch price."""

    price: Price
    displayed_peak: Quantity
    consumed: Quantity

    def __post_init__(self) -> None:
        """Keep cumulative modeled taking within the displayed peak's units."""
        self.price.model_copy()
        self.displayed_peak.model_copy()
        self.consumed.model_copy()
        if (
            self.price.per != self.displayed_peak.dimension
            or self.displayed_peak.dimension != self.consumed.dimension
            or self.displayed_peak.value < 0
            or not 0 <= self.consumed.value <= self.displayed_peak.value
        ):
            raise ValueError("invalid paper touch liquidity")


class PaperLiquidityState(WireRecord, frozen=True):
    """Pin both touch debts and the last fully applied market identity."""

    bid: PaperTouchLiquidity
    ask: PaperTouchLiquidity
    scenario_identity: str
    last_market_identity: str
    last_market_at: datetime

    def __post_init__(self) -> None:
        """Require a complete same-instrument pair of finite touch overlays."""
        self.bid.__post_init__()
        self.ask.__post_init__()
        self._require_utc(self.last_market_at, field_name="last paper market")
        if (
            type(self.last_market_identity) is not str
            or not self.last_market_identity
            or type(self.scenario_identity) is not str
            or len(self.scenario_identity) != 64
            or self.bid.price.per != self.ask.price.per
            or self.bid.price.currency != self.ask.price.currency
        ):
            raise ValueError("invalid paper liquidity state")


class PaperMatchProjection(WireRecord, frozen=True):
    """Return complete deterministic paper facts and successor liquidity debt."""

    events: tuple[OrderEvent, ...]
    liquidity: PaperLiquidityState

    def __post_init__(self) -> None:
        """Keep the pure projection suitable for one journal transaction."""
        if type(self.events) is not tuple:
            raise TypeError("paper match events must be immutable")
        for event in self.events:
            event.__post_init__()
        self.liquidity.__post_init__()


class PaperFeeSchedule:
    """Price modeled paper fees and bound each fill by its order's fee reservation.

    A modeled fee is ``size * price * fee_rate``, rounded half-even to the quote
    currency's minor unit separately on each fill. A fill never charges more than
    the order's remaining reserve, measured both exactly and after rounding, so a
    split fill cannot round a fee under the reserve's bound. This keeps modeled
    economics within what admission reserved, including sells that fill above
    their limit and fees that round up on every partial fill.
    """

    def __init__(self, fee_rate: Decimal) -> None:
        """Bind one validated proportional fee rate."""
        DecimalGrid.require_decimal(fee_rate)
        if not Decimal(0) <= fee_rate < Decimal(1):
            raise ValueError("invalid paper fee rate")
        self.fee_rate = fee_rate

    def fee(self, size: Fraction, price: Price) -> Money:
        """Charge one fill of ``size`` base units at ``price`` on its currency grid."""
        return Money(
            value=DecimalGrid.round_fraction(
                size * Fraction(price.value) * Fraction(self.fee_rate),
                price.currency.minor_unit,
                Rounding.HALF_EVEN,
            ),
            currency=price.currency,
        )

    def affordable(
        self, order: OrderState, size: Fraction, price: Price, lot: Fraction
    ) -> Fraction:
        """Return the largest whole-lot size up to ``size`` that the fee reserve pays."""
        reserve = Fraction(order.maximum_fee.value) - Fraction(order.paid_fee.value)
        lots = size // lot
        if reserve < 0 or lots <= 0:
            return Fraction(0)
        if self._fits(reserve, lots * lot, price):
            return lots * lot
        # Fees never fall as size grows, so bisect for the largest affordable count.
        low, high = 0, lots
        while high - low > 1:
            middle = (low + high) // 2
            if self._fits(reserve, middle * lot, price):
                low = middle
            else:
                high = middle
        return low * lot

    def _fits(self, reserve: Fraction, size: Fraction, price: Price) -> bool:
        """Require both the exact and the rounded fee to stay within the reserve."""
        exact = size * Fraction(price.value) * Fraction(self.fee_rate)
        return exact <= reserve and Fraction(self.fee(size, price).value) <= reserve


class PaperMatchEvaluator:
    """Project one authored spot scenario without mutating either account journal.

    Entry and cancel delays select the first subsequently delivered quote at or
    after their respective modeled eligibility times. A quote's availability is
    the local knowledge clock; this model does not invent an exchange or response
    clock. Repeated equal-price updates cannot replenish previously consumed
    displayed size. A different touch price starts a new conservative segment.
    """

    def __init__(self, scenario: PaperExecutionScenario, *, lot: Quantity, tick: Price) -> None:
        """Bind one complete cost, delay and quantity-grid scenario."""
        scenario.__post_init__()
        lot.model_copy()
        tick.model_copy()
        if (
            lot.value <= 0
            or tick.value <= 0
            or lot.dimension.instrument_id != scenario.instrument_id
            or tick.per != lot.dimension
            or tick.currency != scenario.adverse.currency
            or (Fraction(scenario.adverse.value) / Fraction(tick.value)).denominator != 1
        ):
            raise ValueError("paper matcher scenario and lot differ")
        self.scenario, self.lot, self.tick = scenario, lot, tick
        self.fees = PaperFeeSchedule(scenario.fee_rate)
        self._codec = DomainCodec()
        # The identity hashes the whole scenario; compute it once, not per effect.
        self._scenario_identity = scenario.identity

    def project(
        self,
        market: PaperMarket,
        *,
        account_id: str,
        orders: tuple[OrderState, ...],
        prior_events: tuple[OrderEvent, ...],
        liquidity: PaperLiquidityState | None = None,
    ) -> PaperMatchProjection:
        """Price each eligible physical order once in stable admission order.

        ``prior_events`` includes an interrupted quote's already posted facts.
        The returned successor belongs in the same transaction as its events;
        callers must claim exact quote bytes before publishing either effect.
        """
        market.__post_init__()
        if (
            type(account_id) is not str
            or not account_id
            or market.bid.per != self.lot.dimension
            or market.bid.currency != self.scenario.adverse.currency
            or not self._on_tick(market.bid)
            or not self._on_tick(market.ask)
            or type(orders) is not tuple
            or type(prior_events) is not tuple
        ):
            raise ValueError("paper market, account or scenario differs")
        for order in orders:
            order.__post_init__()
            if (
                order.intent.quantity.dimension != self.lot.dimension
                or not self._on_tick(order.intent.limit)
                or (Fraction(order.intent.quantity.value) / Fraction(self.lot.value)).denominator
                != 1
            ):
                raise ValueError("paper physical order differs from the selected spot grid")
        if len({order.identity for order in orders}) != len(orders):
            raise ValueError("paper physical orders repeat an identity")
        for event in prior_events:
            event.__post_init__()
        if liquidity is not None:
            liquidity.__post_init__()
            if liquidity.bid.price.per != self.lot.dimension:
                raise ValueError("paper liquidity belongs to another instrument")
            if liquidity.scenario_identity != self._scenario_identity:
                raise ValueError("paper liquidity belongs to another execution scenario")
            if market.at < liquidity.last_market_at:
                raise ValueError("paper market availability regressed")
            if liquidity.last_market_identity == market.identity:
                return PaperMatchProjection(events=(), liquidity=liquidity)
        bid = self._touch(
            market.bid, market.bid_quantity, None if liquidity is None else liquidity.bid
        )
        ask = self._touch(
            market.ask, market.ask_quantity, None if liquidity is None else liquidity.ask
        )
        existing_ids = {event.identity for event in prior_events}
        prior_buy, prior_sell = Fraction(0), Fraction(0)
        for order in orders:
            fill_id = self._identity(account_id, market, order, "fill")
            previous = next((event for event in prior_events if event.identity == fill_id), None)
            if previous is None or previous.fill is None:
                continue
            size = abs(Fraction(previous.fill.quantity.value))
            if order.intent.side == "buy":
                prior_buy += size
            else:
                prior_sell += size
        remaining = {
            "buy": min(
                Fraction(market.ask_quantity.value) * Fraction(self.scenario.take_fraction),
                max(
                    Fraction(0),
                    Fraction(ask.displayed_peak.value) * Fraction(self.scenario.take_fraction)
                    - Fraction(ask.consumed.value)
                    - prior_buy,
                ),
            ),
            "sell": min(
                Fraction(market.bid_quantity.value) * Fraction(self.scenario.take_fraction),
                max(
                    Fraction(0),
                    Fraction(bid.displayed_peak.value) * Fraction(self.scenario.take_fraction)
                    - Fraction(bid.consumed.value)
                    - prior_sell,
                ),
            ),
        }
        new_buy, new_sell = Fraction(0), Fraction(0)
        projected: list[OrderEvent] = []
        for order in orders:
            if order.is_terminal or order.status == "unknown" or market.at <= order.decision_at:
                continue
            cancellation = self._cancel_time(order, prior_events)
            if cancellation is not None and market.at >= cancellation + timedelta(
                microseconds=self.scenario.cancel_delay_us
            ):
                self._append(projected, existing_ids, account_id, market, order, "cancelled")
                continue
            if market.at < order.decision_at + timedelta(microseconds=self.scenario.entry_delay_us):
                continue
            touch = market.ask if order.intent.side == "buy" else market.bid
            crosses = (
                touch.value <= order.intent.limit.value
                if order.intent.side == "buy"
                else touch.value >= order.intent.limit.value
            )
            if not order.accepted:
                self._append(projected, existing_ids, account_id, market, order, "request_ack")
                if order.intent.time_in_force == "post-only" and crosses:
                    self._append(projected, existing_ids, account_id, market, order, "rejected")
                    continue
                self._append(projected, existing_ids, account_id, market, order, "accepted")
            effective = (
                touch + self.scenario.adverse
                if order.intent.side == "buy"
                else touch - self.scenario.adverse
            )
            filled_this_order = Fraction(0)
            within_limit = (
                effective.value <= order.intent.limit.value
                if order.intent.side == "buy"
                else effective.value >= order.intent.limit.value
            )
            fill_id = self._identity(account_id, market, order, "fill")
            if crosses and within_limit and effective.value > 0 and fill_id not in existing_ids:
                size = self.fees.affordable(
                    order,
                    min(Fraction(order.remaining.value), remaining[order.intent.side]),
                    effective,
                    Fraction(self.lot.value),
                )
                if size:
                    quantity = Quantity(
                        value=DecimalGrid.exact_decimal(
                            size if order.intent.side == "buy" else -size
                        ),
                        dimension=self.lot.dimension,
                    )
                    fee = self.fees.fee(size, effective)
                    projected.append(
                        OrderEvent(
                            identity=fill_id,
                            order_id=order.identity,
                            at=market.at,
                            kind="fill",
                            fill=Fill(
                                identity=fill_id,
                                decision_at=order.decision_at,
                                filled_at=market.at,
                                quantity=quantity,
                                reference=touch,
                                effective=effective,
                                fee=fee,
                            ),
                        )
                    )
                    existing_ids.add(fill_id)
                    remaining[order.intent.side] -= size
                    filled_this_order = size
                    if order.intent.side == "buy":
                        new_buy += size
                    else:
                        new_sell += size
            if order.intent.time_in_force == "ioc" and (
                Fraction(order.remaining.value) > filled_this_order
            ):
                self._append(projected, existing_ids, account_id, market, order, "cancelled")
        successor = PaperLiquidityState(
            bid=PaperTouchLiquidity(
                price=bid.price,
                displayed_peak=bid.displayed_peak,
                consumed=Quantity(
                    value=DecimalGrid.exact_decimal(
                        Fraction(bid.consumed.value) + prior_sell + new_sell
                    ),
                    dimension=self.lot.dimension,
                ),
            ),
            ask=PaperTouchLiquidity(
                price=ask.price,
                displayed_peak=ask.displayed_peak,
                consumed=Quantity(
                    value=DecimalGrid.exact_decimal(
                        Fraction(ask.consumed.value) + prior_buy + new_buy
                    ),
                    dimension=self.lot.dimension,
                ),
            ),
            scenario_identity=self._scenario_identity,
            last_market_identity=market.identity,
            last_market_at=market.at,
        )
        return PaperMatchProjection(events=tuple(projected), liquidity=successor)

    @staticmethod
    def _touch(
        price: Price, quantity: Quantity, previous: PaperTouchLiquidity | None
    ) -> PaperTouchLiquidity:
        """Keep displayed capacity conservative until the touch price disappears."""
        if previous is None or previous.price != price:
            return PaperTouchLiquidity(
                price=price,
                displayed_peak=quantity,
                consumed=Quantity(value=Decimal(0), dimension=quantity.dimension),
            )
        return PaperTouchLiquidity(
            price=price,
            displayed_peak=Quantity(
                value=max(previous.displayed_peak.value, quantity.value),
                dimension=quantity.dimension,
            ),
            consumed=previous.consumed,
        )

    def _on_tick(self, price: Price) -> bool:
        """Refuse an authored or native quote outside the admitted price grid."""
        return (
            price.currency == self.tick.currency
            and price.per == self.tick.per
            and (Fraction(price.value) / Fraction(self.tick.value)).denominator == 1
        )

    @staticmethod
    def _cancel_time(order: OrderState, prior_events: tuple[OrderEvent, ...]) -> datetime | None:
        """Find the original request clock without inferring success from an acknowledgement."""
        if not order.cancel_requested:
            return None
        requests = tuple(
            event.at
            for event in prior_events
            if event.order_id == order.identity and event.kind == "cancel_requested"
        )
        if not requests:
            raise ValueError("paper cancellation lacks its original request fact")
        return max(requests)

    def _append(
        self,
        projected: list[OrderEvent],
        existing_ids: set[str],
        account_id: str,
        market: PaperMarket,
        order: OrderState,
        kind: EventKind,
    ) -> None:
        """Append a deterministic lifecycle fact once under its account and scenario."""
        identity = self._identity(account_id, market, order, kind)
        if identity in existing_ids:
            return
        projected.append(
            OrderEvent(identity=identity, order_id=order.identity, at=market.at, kind=kind)
        )
        existing_ids.add(identity)

    def _identity(self, account_id: str, market: PaperMarket, order: OrderState, kind: str) -> str:
        """Bind one effect to account, authored scenario, market and physical order."""
        return hashlib.sha256(
            self._codec.encode_json(
                (
                    "paper-match",
                    account_id,
                    self._scenario_identity,
                    market.identity,
                    order.identity,
                    kind,
                )
            )
        ).hexdigest()


class PaperMatcher:
    """Generate identified paper facts without constructing a venue transport.

    Marketable GTC/IOC orders take displayed liquidity at the observed touch.
    Post-only orders reject if marketable at their first later quote; resting
    orders fill only when a subsequent touch crosses their limit. The selected
    versioned scenario applies its explicit delays, adverse cost and take
    fraction. These conservative declared rules are deterministic software
    assumptions, not inferred exchange mechanics.
    """

    def __init__(
        self,
        journal: PaperOrderJournal,
        *,
        fee_rate: Decimal,
        lot: Quantity,
        scenario: PaperExecutionScenario,
    ) -> None:
        """Bind exact fee rounding, lot size and scenario to an already fenced journal."""
        DecimalGrid.require_decimal(fee_rate)
        lot.model_copy()
        if not Decimal(0) <= fee_rate < Decimal(1) or lot.value <= 0:
            raise ValueError("invalid paper matching costs or lot")
        scenario.__post_init__()
        if scenario.fee_rate != fee_rate or scenario.instrument_id != lot.dimension.instrument_id:
            raise ValueError("paper matcher and authored scenario differ")
        self._journal, self._lot, self._scenario = journal, lot, scenario

    def match(self, market: PaperMarket, *, epoch: int) -> None:
        """Claim a quote and apply its modeled effects in one journal transaction.

        Unknown outcomes remain reserved and require explicit reconciliation;
        matching cannot turn uncertainty into an automatic resend or an invented fill.
        """
        market.__post_init__()
        if market.bid.per != self._lot.dimension:
            raise ValueError("paper market belongs to another instrument")
        self._journal.match_scenario_market(epoch=epoch, market=market, scenario=self._scenario)
