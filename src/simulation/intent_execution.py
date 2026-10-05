"""Execute causal offline decision intents against bounded L2 liquidity."""

from __future__ import annotations

# standard library imports
import hashlib
import heapq
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import Fill, Ledger
from financial_units import DecimalGrid, ExactRatio, Price, Quantity
from market_data.contracts import BookObservation
from risk import SpotLimits
from serialization import DomainCodec
from simulation.costs import SpotCosts
from simulation.intent_contracts import (
    IntentCostModel,
    IntentDecisionOutcome,
    IntentMarket,
    IntentOrderOutcome,
    IntentSimulationResult,
    IntentSimulationSpec,
    LimitExecutionConfig,
)
from strategies import (
    DecisionRecord,
    ExposureIntent,
    OrderIntent,
    QuoteIntent,
    TargetIntent,
)


class SpotFeeModel:
    """Apply independent exact maker and taker SpotCosts with a stable identity."""

    def __init__(self, *, maker: SpotCosts, taker: SpotCosts) -> None:
        """Require maker execution at its resting limit and explicit taker costs."""
        maker.__post_init__()
        taker.__post_init__()
        if (
            maker.adverse.value != 0
            or maker.adverse.per != taker.adverse.per
            or maker.adverse.currency != taker.adverse.currency
        ):
            raise ValueError("maker costs must retain resting price and common units")
        self.maker = maker
        self.taker = taker

    @property
    def identity(self) -> str:
        """Bind both liquidity classes and the implementation version."""
        return hashlib.sha256(
            DomainCodec().encode_json(("spot-fee-model", self.maker, self.taker))
        ).hexdigest()

    def fill(
        self,
        identity: str,
        *,
        decision_at: datetime,
        filled_at: datetime,
        quantity: Quantity,
        reference: Price,
        liquidity: Literal["maker", "taker"],
    ) -> Fill:
        """Delegate exact rounding and signed adverse pricing to SpotCosts."""
        if liquidity == "maker":
            costs = self.maker
        elif liquidity == "taker":
            costs = self.taker
        else:
            raise ValueError("unknown intent liquidity class")
        return costs.fill(
            identity,
            decision_at=decision_at,
            filled_at=filled_at,
            quantity=quantity,
            reference=reference,
        )


class _Order:
    """Keep one locally mutable offline order until a complete terminal outcome."""

    def __init__(
        self, identity: str, decision_at: datetime, requested: OrderIntent, placed_at: datetime
    ) -> None:
        """Create an exact unfilled child at its modeled exchange arrival."""
        self.identity = identity
        self.decision_at = decision_at
        self.requested = requested
        self.placed_at = placed_at
        self.remaining = Fraction(requested.quantity.value)
        self.queue_ahead = Fraction(0)
        self.initial_queue = Fraction(0)
        self.fills: list[Fill] = []
        self.closed_at: datetime | None = None
        self.reason = "resting"
        self.status: Literal["filled", "partial", "canceled", "expired", "rejected"] = "canceled"

    def close(self, at: datetime, reason: str, *, expired: bool = False) -> None:
        """Close only once and classify partials separately from unfilled expiry."""
        if self.closed_at is not None:
            return
        self.closed_at = at
        self.reason = reason
        self.status = (
            "filled"
            if not self.remaining
            else "partial"
            if self.fills
            else "expired"
            if expired
            else "canceled"
        )

    def outcome(self) -> IntentOrderOutcome:
        """Freeze a complete child outcome with exact remaining and queue quantities."""
        if self.closed_at is None:
            raise ValueError("offline order remains open")
        return IntentOrderOutcome(
            identity=self.identity,
            decision_at=self.decision_at,
            requested=self.requested,
            placed_at=self.placed_at,
            closed_at=self.closed_at,
            status=self.status,
            reason=self.reason,
            fills=tuple(self.fills),
            canceled=Quantity(
                value=DecimalGrid.exact_decimal(self.remaining),
                dimension=self.requested.quantity.dimension,
            ),
            queue_ahead=Quantity(
                value=DecimalGrid.exact_decimal(self.initial_queue),
                dimension=self.requested.quantity.dimension,
            ),
        )


class _Schedule:
    """Order offline source and lifecycle phases without closure-owned state."""

    def __init__(self, end: datetime) -> None:
        """Bind the inclusive terminal event boundary and deterministic tie counter."""
        self._end = end
        self._serial = 0
        self._events: list[tuple[datetime, int, int, str, int]] = []

    def __bool__(self) -> bool:
        """Report whether any scheduled phase remains."""
        return bool(self._events)

    def add(self, at: datetime, priority: int, kind: str, index: int) -> None:
        """Retain a phase only if it can affect the bounded sample."""
        if at <= self._end:
            heapq.heappush(self._events, (at, priority, self._serial, kind, index))
            self._serial += 1

    def pop(self) -> tuple[datetime, str, int]:
        """Select the next stable time/phase/source ordered event."""
        at, _, _, kind, index = heapq.heappop(self._events)
        return at, kind, index


class LimitOrderExecution:
    """Model bounded L2 limit crossing and trade-depleted passive queues offline."""

    def __init__(self, config: LimitExecutionConfig) -> None:
        """Bind immutable timings, no-impact depth and explicit queue assumption."""
        config.__post_init__()
        self.config = config

    @property
    def identity(self) -> str:
        """Hash the complete model version and serialized assumptions."""
        return hashlib.sha256(
            DomainCodec().encode_json(("l2-limit-intent", self.config))
        ).hexdigest()

    def run(
        self,
        spec: IntentSimulationSpec,
        costs: IntentCostModel,
        ledger: Ledger,
        decisions: tuple[DecisionRecord, ...],
        market: tuple[IntentMarket, ...],
    ) -> IntentSimulationResult:
        """Step source, cancellation, expiry, trade, arrival and decisions causally."""
        if self.identity != spec.execution_identity or costs.identity != spec.cost_identity:
            raise ValueError("offline execution model identity mismatch")
        schedule = _Schedule(spec.end)
        for index, row in enumerate(market):
            schedule.add(row.available_at, 0, "market", index)
            if row.trades:
                schedule.add(row.available_at, 3, "trade", index)
        for index, decision in enumerate(decisions):
            schedule.add(decision.at, 5, "decision", index)
        active: list[_Order] = []
        all_orders: list[_Order] = []
        rejected: list[IntentOrderOutcome] = []
        plans: dict[int, tuple[DecisionRecord, datetime, bool]] = {}
        outcomes: dict[int, IntentDecisionOutcome] = {}
        last_book: IntentMarket | None = None
        consumed: dict[tuple[str, Decimal], Fraction] = {}
        codec = DomainCodec()
        while schedule:
            at, kind, index = schedule.pop()
            if at == spec.end and kind not in ("market", "cancel", "expiry"):
                continue
            if kind == "market":
                row = market[index]
                if row.book is not None:
                    if row.book.status == "degraded" and row.book.outcome in ("snapshot", "update"):
                        last_book = row
                        present = {("bid", price) for price, _ in row.book.bids} | {
                            ("ask", price) for price, _ in row.book.asks
                        }
                        consumed = {key: value for key, value in consumed.items() if key in present}
                    else:
                        last_book = None
                        for order in active:
                            order.close(at, "source_unavailable")
                        active = [order for order in active if order.closed_at is None]
                continue
            if kind == "cancel":
                previous_index = index
                for order in active:
                    if int(order.identity.split(":", maxsplit=1)[0]) <= previous_index:
                        order.close(at, "replaced")
                active = [order for order in active if order.closed_at is None]
                for plan_index, (decision, arrival, canceled) in tuple(plans.items()):
                    if plan_index <= previous_index and not canceled and arrival >= at:
                        plans[plan_index] = (decision, arrival, True)
                continue
            if kind == "expiry":
                all_orders[index].close(at, "lifetime_expired", expired=True)
                active = [order for order in active if order.closed_at is None]
                continue
            if kind == "trade":
                row = market[index]
                if row.source_at == spec.end:
                    continue
                for trade in row.trades:
                    for order in active:
                        if (
                            order.closed_at is not None
                            or row.source_at <= order.placed_at
                            or row.known_at < order.placed_at
                            or trade.price.value != order.requested.limit.value
                            or (order.requested.side == "buy") != (trade.aggressor == "sell")
                        ):
                            continue
                        available = Fraction(trade.quantity.value) * Fraction(
                            self.config.take_fraction
                        )
                        used_ahead = min(order.queue_ahead, available)
                        order.queue_ahead -= used_ahead
                        available -= used_ahead
                        self._post(spec, costs, ledger, order, trade.price, available, at, "maker")
                active = [order for order in active if order.closed_at is None]
                continue
            if kind == "arrival":
                plan = plans.get(index)
                if plan is None:
                    raise ValueError("missing offline intent plan")
                decision, _, canceled = plan
                if canceled:
                    outcomes[index] = IntentDecisionOutcome(
                        decision=decision, order_identities=(), reason="replaced_before_arrival"
                    )
                    continue
                if decision.intent is None:
                    outcomes[index] = IntentDecisionOutcome(
                        decision=decision, order_identities=(), reason="abstained"
                    )
                    continue
                book = self._fresh_book(last_book, at)
                if book is None:
                    outcomes[index] = IntentDecisionOutcome(
                        decision=decision, order_identities=(), reason="no_fresh_book_at_arrival"
                    )
                    continue
                try:
                    limits = spec.limits_at(at)
                except ValueError:
                    outcomes[index] = IntentDecisionOutcome(
                        decision=decision, order_identities=(), reason="order_reference_unavailable"
                    )
                    continue
                requests = self._requests(spec, decision, ledger, book, limits)
                if not requests:
                    outcomes[index] = IntentDecisionOutcome(
                        decision=decision, order_identities=(), reason="no_change"
                    )
                    continue
                children: list[str] = []
                for leg, request in enumerate(requests):
                    digest = hashlib.sha256(
                        codec.encode_json((spec.identity, decision, leg))
                    ).hexdigest()
                    identity = f"{index}:{leg}:{digest}"
                    children.append(identity)
                    rejection = self._admit(request, ledger, book, limits)
                    if rejection is not None:
                        rejected.append(
                            IntentOrderOutcome(
                                identity=identity,
                                decision_at=decision.at,
                                requested=request,
                                placed_at=None,
                                closed_at=at,
                                status="rejected",
                                reason=rejection,
                                fills=(),
                                canceled=request.quantity,
                                queue_ahead=Quantity(
                                    value=Decimal(0), dimension=request.quantity.dimension
                                ),
                            )
                        )
                        continue
                    order = _Order(identity, decision.at, request, at)
                    all_orders.append(order)
                    self._cross(spec, costs, ledger, order, book, consumed, at)
                    if order.remaining and request.time_in_force == "ioc":
                        order.close(at, "ioc_remainder")
                    elif order.remaining:
                        visible = next(
                            (
                                Fraction(level.size)
                                for price, level in (
                                    book.bids if request.side == "buy" else book.asks
                                )
                                if price == request.limit.value
                            ),
                            Fraction(0),
                        )
                        order.queue_ahead = visible * Fraction(self.config.queue_ahead_fraction)
                        order.initial_queue = order.queue_ahead
                        active.append(order)
                        expiry = at + timedelta(microseconds=self.config.lifetime_us)
                        schedule.add(expiry, 2, "expiry", len(all_orders) - 1)
                outcomes[index] = IntentDecisionOutcome(
                    decision=decision, order_identities=tuple(children), reason="submitted"
                )
                continue
            if kind == "decision":
                decision = decisions[index]
                has_outstanding_work = bool(active) or any(
                    plan_index < index and not canceled and arrival > at
                    for plan_index, (_, arrival, canceled) in plans.items()
                )
                cancellation = (
                    at + timedelta(microseconds=self.config.cancel_delay_us)
                    if has_outstanding_work
                    else at
                )
                if has_outstanding_work:
                    if cancellation == at:
                        for order in active:
                            order.close(at, "replaced")
                        active = [order for order in active if order.closed_at is None]
                        for plan_index, (older, arrival, canceled) in tuple(plans.items()):
                            if plan_index < index and not canceled and arrival >= at:
                                plans[plan_index] = (older, arrival, True)
                    else:
                        schedule.add(cancellation, 1, "cancel", index - 1)
                arrival = cancellation + timedelta(microseconds=self.config.entry_delay_us)
                plans[index] = (decision, arrival, False)
                if arrival < spec.end:
                    schedule.add(arrival, 4, "arrival", index)
                else:
                    outcomes[index] = IntentDecisionOutcome(
                        decision=decision, order_identities=(), reason="arrival_after_sample"
                    )
        for order in active:
            order.close(spec.end, "sample_end", expired=True)
        final_orders = tuple(order.outcome() for order in all_orders) + tuple(rejected)
        final_decisions = tuple(
            outcomes.get(
                index,
                IntentDecisionOutcome(
                    decision=decision, order_identities=(), reason="replaced_before_arrival"
                ),
            )
            for index, decision in enumerate(decisions)
        )
        terminal_book = self._fresh_book(last_book, spec.end)
        valuation = (
            None
            if terminal_book is None or not ledger.balance.holding.value
            else self._price(spec, max(price for price, _ in terminal_book.bids))
        )
        if ledger.balance.holding.value and valuation is None:
            raise ValueError("open intent holding requires a fresh terminal bid")
        mark = ledger.mark(valuation)
        return IntentSimulationResult(
            spec=spec,
            decisions=final_decisions,
            orders=final_orders,
            ledger=ledger.state,
            valuation_price=valuation,
            mark=mark,
            net_return=ExactRatio.from_fraction(
                Fraction(mark.net.value) / Fraction(spec.initial_cash.value)
            ),
            limitations=(
                "offline no-impact L2 book; depth and trades may be incomplete",
                "passive queue position is modeled from visible same-price size",
                "trade depletion is counted once; hidden liquidity and venue priority are unknown",
                "passive fills use source availability, so delayed trades may miss earlier fills",
                "entry/cancel delays are fixed; no venue acknowledgements or deployed OMS",
                "receipt-as-matching maps original receipt to modeled matching time;"
                " exchange-time fill fidelity is unproven"
                if any(row.clock_assumption == "receipt-as-matching" for row in market)
                else "source-and-knowledge clocks are supplied with each market input",
                "fixed SpotLimits are a declared synthetic reference when no history is selected"
                if spec.reference_history is None
                else "order grids resolve from then-valid, then-known reference history",
            ),
        )

    def _fresh_book(self, row: IntentMarket | None, at: datetime) -> BookObservation | None:
        """Select only a then-known valid book within its source-event age bound."""
        if (
            row is None
            or row.book is None
            or row.available_at > at
            or row.source_at > at
            or row.book.status != "degraded"
            or row.book.outcome not in ("snapshot", "update")
            or not row.book.bids
            or not row.book.asks
            or max(price for price, _ in row.book.bids) >= min(price for price, _ in row.book.asks)
            or at - row.source_at > timedelta(microseconds=self.config.max_book_age_us)
        ):
            return None
        return row.book

    @staticmethod
    def _price(spec: IntentSimulationSpec, value: Decimal) -> Price:
        """Bind one canonical native price to the account's exact dimensions."""
        tick = spec.limits.tick
        return Price(value=value, currency=tick.currency, per=tick.per)

    def _requests(
        self,
        spec: IntentSimulationSpec,
        decision: DecisionRecord,
        ledger: Ledger,
        book: BookObservation,
        limits: SpotLimits,
    ) -> tuple[OrderIntent, ...]:
        """Resolve target/exposure against current holdings or retain explicit orders."""
        intent = decision.intent
        if intent is None:
            raise ValueError("an abstention has no order requests")
        if type(intent) is OrderIntent:
            return (intent,)
        if type(intent) is QuoteIntent:
            return (intent.bid, intent.ask)
        if type(intent) is TargetIntent:
            target = intent.quantity
        elif type(intent) is ExposureIntent:
            if intent.exposure.currency != spec.initial_cash.currency or intent.exposure.value < 0:
                raise ValueError("unsupported intent exposure currency or short exposure")
            midpoint = (
                Fraction(max(price for price, _ in book.bids))
                + Fraction(min(price for price, _ in book.asks))
            ) / 2
            lot = Fraction(limits.lot.value)
            units = int((Fraction(intent.exposure.value) / midpoint) // lot)
            target = Quantity(
                value=DecimalGrid.exact_decimal(units * lot),
                dimension=limits.maximum.dimension,
            )
        else:
            raise TypeError("unsupported decision intent")
        reason = limits.target_reason(target, ledger.balance.holding, pending=False)
        if reason is not None:
            raise ValueError(f"intent target rejected: {reason}")
        delta = target - ledger.balance.holding
        if delta.value == 0:
            return ()
        side: Literal["buy", "sell"] = "buy" if delta.value > 0 else "sell"
        touch = (
            min(price for price, _ in book.asks)
            if side == "buy"
            else max(price for price, _ in book.bids)
        )
        return (
            OrderIntent(
                side=side,
                quantity=Quantity(value=abs(delta.value), dimension=delta.dimension),
                limit=self._price(spec, touch),
                time_in_force="ioc",
            ),
        )

    def _admit(
        self,
        request: OrderIntent,
        ledger: Ledger,
        book: BookObservation,
        limits: SpotLimits,
    ) -> str | None:
        """Apply canonical order grids and conservative spot inventory checks."""
        reason = limits.order_reason(request.quantity, request.limit)
        if reason is not None:
            return reason
        if request.side == "sell" and request.quantity.value > ledger.balance.holding.value:
            return "insufficient_holding"
        if request.side == "buy":
            gross = request.limit.amount(request.quantity)
            if gross.value > ledger.balance.cash.value:
                return "insufficient_cash"
        crossing = (
            request.limit.value >= min(price for price, _ in book.asks)
            if request.side == "buy"
            else request.limit.value <= max(price for price, _ in book.bids)
        )
        if request.time_in_force == "post-only" and crossing:
            return "post_only_crossing"
        return None

    def _cross(
        self,
        spec: IntentSimulationSpec,
        costs: IntentCostModel,
        ledger: Ledger,
        order: _Order,
        book: BookObservation,
        consumed: dict[tuple[str, Decimal], Fraction],
        at: datetime,
    ) -> None:
        """Walk displayed opposite depth only through the explicit limit price."""
        if order.requested.time_in_force == "post-only":
            return
        buying = order.requested.side == "buy"
        levels = sorted(book.asks if buying else book.bids, reverse=not buying)
        touch = levels[0][0]
        side = "ask" if buying else "bid"
        for price, level in levels:
            if (buying and price > order.requested.limit.value) or (
                not buying and price < order.requested.limit.value
            ):
                break
            available = max(
                Fraction(0),
                Fraction(level.size) * Fraction(self.config.take_fraction)
                - consumed.get((side, price), Fraction(0)),
            )
            filled = self._post(
                spec,
                costs,
                ledger,
                order,
                self._price(spec, price),
                available,
                at,
                "taker",
                reference=self._price(spec, touch),
            )
            consumed[(side, price)] = consumed.get((side, price), Fraction(0)) + filled
            if order.closed_at is not None:
                break

    def _post(
        self,
        spec: IntentSimulationSpec,
        costs: IntentCostModel,
        ledger: Ledger,
        order: _Order,
        price: Price,
        available: Fraction,
        at: datetime,
        liquidity: Literal["maker", "taker"],
        *,
        reference: Price | None = None,
    ) -> Fraction:
        """Find affordable whole lots and post each partial once through the ledger."""
        try:
            limits = spec.limits_at(at)
        except ValueError:
            order.close(at, "order_reference_unavailable")
            return Fraction(0)
        if limits.order_reason(order.requested.quantity, order.requested.limit) is not None:
            order.close(at, "order_reference_changed")
            return Fraction(0)
        lot = Fraction(limits.lot.value)
        maximum = int(min(order.remaining, available) // lot)
        if maximum <= 0:
            return Fraction(0)
        sign = 1 if order.requested.side == "buy" else -1
        low, high = 0, maximum
        while low < high:
            middle = (low + high + 1) // 2
            fill = self._candidate(
                costs, order, price, at, liquidity, middle, lot, reference=reference
            )
            limit_ok = (
                fill.effective.value <= order.requested.limit.value
                if sign > 0
                else fill.effective.value >= order.requested.limit.value
            )
            if (
                limit_ok
                and limits.fill_reason(
                    fill.quantity,
                    fill.effective,
                    fill.fee,
                    ledger.balance.cash,
                    ledger.balance.holding,
                )
                is None
            ):
                low = middle
            else:
                high = middle - 1
        if low == 0:
            return Fraction(0)
        fill = self._candidate(costs, order, price, at, liquidity, low, lot, reference=reference)
        ledger.apply(fill)
        order.fills.append(fill)
        consumed = low * lot
        order.remaining -= consumed
        if not order.remaining:
            order.close(at, "filled")
        return consumed

    @staticmethod
    def _candidate(
        costs: IntentCostModel,
        order: _Order,
        price: Price,
        at: datetime,
        liquidity: Literal["maker", "taker"],
        units: int,
        lot: Fraction,
        *,
        reference: Price | None,
    ) -> Fill:
        """Validate an injected cost model's exact child fill before any posting."""
        sign = 1 if order.requested.side == "buy" else -1
        quantity = Quantity(
            value=DecimalGrid.exact_decimal(sign * units * lot),
            dimension=order.requested.quantity.dimension,
        )
        identity = f"{order.identity}:fill:{len(order.fills)}"
        fill = costs.fill(
            identity,
            decision_at=order.decision_at,
            filled_at=at,
            quantity=quantity,
            reference=price,
            liquidity=liquidity,
        )
        if type(fill) is not Fill:
            raise TypeError("intent cost model requires exact accounting Fill")
        fill.__post_init__()
        if (
            fill.identity != identity
            or fill.decision_at != order.decision_at
            or fill.filled_at != at
            or fill.quantity != quantity
            or fill.reference != price
        ):
            raise ValueError("intent cost model returned a foreign fill")
        if reference is not None:
            fill = replace(fill, reference=reference)
            fill.__post_init__()
        return fill
