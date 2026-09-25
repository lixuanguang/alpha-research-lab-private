"""Simulate bounded offline decision intents against causal spot books and trades."""

from __future__ import annotations

# standard library imports
import hashlib
import heapq
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Protocol

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import Fill, Ledger, LedgerMark, LedgerState
from financial_units import DecimalGrid, ExactRatio, Money, Price, Quantity
from market_data.contracts import BookObservation
from reference_data.catalogs import ReferenceHistory
from research.observations import BookFeatures
from risk import SpotLimits
from serialization import DomainCodec, WireRecord
from simulation.costs import SpotCosts
from strategies import (
    DecisionRecord,
    ExposureIntent,
    OrderIntent,
    QuoteIntent,
    TargetIntent,
)


class IntentTrade(WireRecord, frozen=True):
    """Describe a source trade at one price with the aggressor's side."""

    price: Price
    quantity: Quantity
    aggressor: Literal["buy", "sell"]

    def __post_init__(self) -> None:
        """Require positive exact prices and sizes in matching units."""
        if type(self.price) is not Price or type(self.quantity) is not Quantity:
            raise TypeError("intent trade requires exact price and quantity")
        self.price.model_copy()
        self.quantity.model_copy()
        if (
            self.price.value <= 0
            or self.quantity.value <= 0
            or self.price.per != self.quantity.dimension
            or self.aggressor not in ("buy", "sell")
        ):
            raise ValueError("invalid intent trade")


class IntentMarket(WireRecord, frozen=True):
    """Bind canonical book state and trades to separate source and knowledge clocks."""

    identity: str
    source_identity: str
    instrument: str
    channel: Literal["l2"]
    source_at: datetime
    known_at: datetime
    book: BookObservation | None
    trades: tuple[IntentTrade, ...] = ()
    clock_assumption: Literal["source-and-knowledge", "receipt-as-matching-v1"] = (
        "source-and-knowledge"
    )

    def __post_init__(self) -> None:
        """Reject malformed provenance, clocks, canonical state and trade records."""
        self._require_utc(self.source_at, field_name="market source clock")
        self._require_utc(self.known_at, field_name="market knowledge clock")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.source_identity) is not str
            or not self.source_identity
            or type(self.instrument) is not str
            or not self.instrument
            or self.channel != "l2"
            or self.clock_assumption not in ("source-and-knowledge", "receipt-as-matching-v1")
            or type(self.trades) is not tuple
            or (self.book is None and not self.trades)
        ):
            raise ValueError("market input requires identity and book or trades")
        if self.book is not None:
            if type(self.book) is not BookObservation or self.book.orders:
                raise ValueError("intent market requires canonical aggregate L2 state")
            self.book.__post_init__()
            if self.clock_assumption == "source-and-knowledge":
                if BookFeatures.source_at(self.book) != self.source_at:
                    raise ValueError("canonical book source clock differs from market input")
            else:
                if self.book.received_ns is None:
                    raise ValueError("receipt-matching book requires original receipt clock")
                rounded_receipt = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                    microseconds=(self.book.received_ns + 999) // 1000
                )
                if self.source_at != rounded_receipt or self.known_at != rounded_receipt:
                    raise ValueError("receipt-matching clock differs from canonical receipt")
            if self.book.received_ns is not None:
                elapsed = self.known_at - datetime(1970, 1, 1, tzinfo=UTC)
                known_ns = (
                    (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
                ) * 1000
                if known_ns < self.book.received_ns:
                    raise ValueError("market knowledge precedes canonical book receipt")
        elif self.clock_assumption == "receipt-as-matching-v1":
            raise ValueError("receipt-matching trades require a canonical received book")
        for trade in self.trades:
            if type(trade) is not IntentTrade:
                raise TypeError("market trades require IntentTrade")
            trade.__post_init__()

    @property
    def available_at(self) -> datetime:
        """Return the first clock at which both event and knowledge are available."""
        return max(self.source_at, self.known_at)


class LimitExecutionConfig(WireRecord, frozen=True):
    """Declare bounded entry, cancellation, age, depth and L2 queue assumptions."""

    entry_delay_us: int
    cancel_delay_us: int
    lifetime_us: int
    max_book_age_us: int
    take_fraction: Decimal
    queue_ahead_fraction: Decimal

    def __post_init__(self) -> None:
        """Keep all timing positive where needed and fractions inside the unit interval."""
        for value in (
            self.entry_delay_us,
            self.cancel_delay_us,
            self.lifetime_us,
            self.max_book_age_us,
        ):
            if type(value) is not int or value < 0:
                raise ValueError("invalid intent execution timing")
        if self.entry_delay_us <= 0 or self.lifetime_us <= 0 or self.max_book_age_us <= 0:
            raise ValueError("entry, lifetime and book age require positive bounds")
        for fraction in (self.take_fraction, self.queue_ahead_fraction):
            DecimalGrid.require_decimal(fraction)
            if not Decimal(0) <= fraction <= Decimal(1):
                raise ValueError("execution fractions must lie inside [0, 1]")
        if self.take_fraction == 0:
            raise ValueError("zero depth participation cannot execute an intent")


class IntentSimulationSpec(WireRecord, frozen=True):
    """Bind one independent spot account, sample and injected model identities."""

    instance: str
    entity: str
    source_identity: str
    start: datetime
    end: datetime
    initial_cash: Money
    limits: SpotLimits
    execution_identity: str
    cost_identity: str
    reference_history: ReferenceHistory | None = None
    reference_max_age_us: int | None = None
    schema_version: str = "offline-intent-simulation-v1"

    def __post_init__(self) -> None:
        """Require a finite UTC study window and exact single-instrument cash account."""
        self._require_utc(self.start, field_name="intent sample start")
        self._require_utc(self.end, field_name="intent sample end")
        if (
            any(
                type(value) is not str or not value
                for value in (
                    self.instance,
                    self.entity,
                    self.source_identity,
                    self.execution_identity,
                    self.cost_identity,
                )
            )
            or self.schema_version != "offline-intent-simulation-v1"
        ):
            raise ValueError("intent simulation requires complete versioned identities")
        if type(self.initial_cash) is not Money or type(self.limits) is not SpotLimits:
            raise TypeError("intent simulation requires exact cash and SpotLimits")
        self.initial_cash.model_copy()
        self.limits.__post_init__()
        if (self.reference_history is None) != (self.reference_max_age_us is None):
            raise ValueError("versioned order reference and maximum age must be selected together")
        if self.reference_history is not None:
            if type(self.reference_history) is not ReferenceHistory:
                raise TypeError("intent order reference requires ReferenceHistory")
            self.reference_history.__post_init__()
        if self.reference_max_age_us is not None and (
            type(self.reference_max_age_us) is not int or self.reference_max_age_us <= 0
        ):
            raise ValueError("order reference maximum age must be positive")
        if (
            self.start >= self.end
            or self.initial_cash.value <= 0
            or self.initial_cash.currency != self.limits.tick.currency
            or self.entity != str(self.limits.maximum.dimension.instrument_id)
        ):
            raise ValueError("incompatible intent sample, instrument or capital")

    @property
    def identity(self) -> str:
        """Hash every resolved economic input without paths or wall clocks."""
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def limits_at(self, at: datetime) -> SpotLimits:
        """Resolve then-valid, then-known venue grids or the declared fixed fixture."""
        self._require_utc(at, field_name="order reference clock")
        if not self.start <= at <= self.end:
            raise ValueError("order reference clock outside simulation sample")
        if self.reference_history is None:
            return self.limits
        if self.reference_max_age_us is None:
            raise ValueError("versioned order reference maximum age is absent")
        return SpotLimits.from_reference(
            self.reference_history,
            maximum=self.limits.maximum,
            quote_currency=self.initial_cash.currency,
            valid_at=at,
            known_at=at,
            max_age=timedelta(microseconds=self.reference_max_age_us),
        )


class IntentCostModel(Protocol):
    """Price an identified maker or taker fill without owning risk or accounting."""

    @property
    def identity(self) -> str:
        """Pin the complete versioned cost assumptions."""
        ...

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
        """Return an exact signed fill with the declared fee and adverse price."""
        ...


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
            DomainCodec().encode_json(("spot-fee-model-v1", self.maker, self.taker))
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


class IntentOrderOutcome(WireRecord, frozen=True):
    """Retain one offline child order's complete fill and cancellation lifecycle."""

    identity: str
    decision_at: datetime
    requested: OrderIntent
    placed_at: datetime | None
    closed_at: datetime
    status: Literal["filled", "partial", "canceled", "expired", "rejected"]
    reason: str
    fills: tuple[Fill, ...]
    canceled: Quantity
    queue_ahead: Quantity

    def __post_init__(self) -> None:
        """Reconcile exact submitted, filled and unfilled base units."""
        self._require_utc(self.decision_at, field_name="order decision")
        self._require_utc(self.closed_at, field_name="order close")
        if self.placed_at is not None:
            self._require_utc(self.placed_at, field_name="order placement")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.requested) is not OrderIntent
            or type(self.fills) is not tuple
            or type(self.canceled) is not Quantity
            or type(self.queue_ahead) is not Quantity
            or type(self.reason) is not str
            or not self.reason
            or self.closed_at < self.decision_at
            or (
                self.placed_at is not None
                and not self.decision_at < self.placed_at <= self.closed_at
            )
        ):
            raise ValueError("invalid offline order outcome")
        self.requested.__post_init__()
        self.canceled.model_copy()
        self.queue_ahead.model_copy()
        if (
            self.canceled.dimension != self.requested.quantity.dimension
            or self.queue_ahead.dimension != self.requested.quantity.dimension
            or self.canceled.value < 0
            or self.queue_ahead.value < 0
        ):
            raise ValueError("offline order sizes have incompatible units")
        filled = Fraction(0)
        for fill in self.fills:
            if type(fill) is not Fill:
                raise TypeError("offline order requires exact Fill records")
            fill.__post_init__()
            if (
                fill.decision_at != self.decision_at
                or fill.quantity.dimension != self.requested.quantity.dimension
                or (fill.quantity.value > 0) != (self.requested.side == "buy")
                or self.placed_at is None
                or fill.filled_at < self.placed_at
                or fill.filled_at > self.closed_at
            ):
                raise ValueError("offline fill differs from its order")
            filled += abs(Fraction(fill.quantity.value))
        if filled + Fraction(self.canceled.value) != Fraction(self.requested.quantity.value):
            raise ValueError("offline order quantity does not reconcile")
        expected = "filled" if not self.canceled.value else "partial" if self.fills else None
        if self.status == "filled" and expected != "filled":
            raise ValueError("filled order retains unfilled quantity")
        if self.status == "partial" and expected != "partial":
            raise ValueError("partial order has no fill or remainder")
        if self.status in ("rejected", "canceled", "expired") and self.fills:
            raise ValueError("unfilled status cannot hide a prior fill")


class IntentDecisionOutcome(WireRecord, frozen=True):
    """Retain each strategy decision, including no-trade and rejected outcomes."""

    decision: DecisionRecord
    order_identities: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        """Require a typed original decision and stable child identities."""
        if type(self.decision) is not DecisionRecord or not self.reason:
            raise ValueError("invalid offline decision outcome")
        self.decision.__post_init__()
        if type(self.order_identities) is not tuple or any(
            type(value) is not str or not value for value in self.order_identities
        ):
            raise ValueError("invalid decision child identities")


class IntentSimulationResult(WireRecord, frozen=True):
    """Retain auditable offline orders, exact postings and a reconstructed terminal mark."""

    spec: IntentSimulationSpec
    decisions: tuple[IntentDecisionOutcome, ...]
    orders: tuple[IntentOrderOutcome, ...]
    ledger: LedgerState
    valuation_price: Price | None
    mark: LedgerMark
    net_return: ExactRatio
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject forged mark, return, child identity or posting attribution."""
        self.spec.__post_init__()
        self.ledger.__post_init__()
        self.mark.__post_init__()
        self.net_return.__post_init__()
        if (
            self.ledger.initial_cash != self.spec.initial_cash
            or self.ledger.dimension != self.spec.limits.maximum.dimension
            or type(self.decisions) is not tuple
            or type(self.orders) is not tuple
            or type(self.limitations) is not tuple
            or not self.limitations
        ):
            raise ValueError("intent result has incompatible account or trace")
        identities: set[str] = set()
        listed_fills: dict[str, Fill] = {}
        for outcome in self.orders:
            outcome.__post_init__()
            if outcome.identity in identities or outcome.closed_at > self.spec.end:
                raise ValueError("duplicate or post-terminal offline order")
            identities.add(outcome.identity)
            for fill in outcome.fills:
                if fill.identity in listed_fills:
                    raise ValueError("duplicate offline fill")
                listed_fills[fill.identity] = fill
        linked: dict[str, datetime] = {}
        for decision in self.decisions:
            decision.__post_init__()
            if decision.decision.at < self.spec.start or decision.decision.at >= self.spec.end:
                raise ValueError("decision outside result sample")
            if any(identity not in identities for identity in decision.order_identities):
                raise ValueError("decision names an absent child order")
            for identity in decision.order_identities:
                if identity in linked:
                    raise ValueError("offline order belongs to more than one decision")
                linked[identity] = decision.decision.at
        if set(linked) != identities or any(
            order.decision_at != linked[order.identity] for order in self.orders
        ):
            raise ValueError("offline order lacks its original decision")
        if listed_fills != {fill.identity: fill for fill in self.ledger.fills}:
            raise ValueError("offline orders and ledger postings differ")
        if self.valuation_price is not None:
            self.valuation_price.model_copy()
            if self.spec.limits_at(self.spec.end).price_reason(self.valuation_price) is not None:
                raise ValueError("invalid terminal valuation price")
        if Ledger(self.ledger).mark(self.valuation_price) != self.mark:
            raise ValueError("terminal mark does not match exact ledger")
        expected = ExactRatio.from_fraction(
            Fraction(self.mark.net.value) / Fraction(self.spec.initial_cash.value)
        )
        if expected != self.net_return:
            raise ValueError("terminal return does not match exact NAV")


class IntentExecutionModel(Protocol):
    """Consume causal decisions and market inputs with an injected exact cost model."""

    @property
    def identity(self) -> str:
        """Pin the complete implementation and execution assumptions."""
        ...

    def run(
        self,
        spec: IntentSimulationSpec,
        costs: IntentCostModel,
        ledger: Ledger,
        decisions: tuple[DecisionRecord, ...],
        market: tuple[IntentMarket, ...],
    ) -> IntentSimulationResult:
        """Return exact offline lifecycle and terminal economics."""
        ...


class IntentSimulation:
    """Validate explicit compatible collaborators and invoke one offline model."""

    def __init__(
        self,
        spec: IntentSimulationSpec,
        execution: IntentExecutionModel,
        costs: IntentCostModel,
        ledger: Ledger,
    ) -> None:
        """Bind independently selected account, execution and cost implementations."""
        spec.__post_init__()
        if (
            execution.identity != spec.execution_identity
            or costs.identity != spec.cost_identity
            or ledger.state.initial_cash != spec.initial_cash
            or ledger.state.dimension != spec.limits.maximum.dimension
            or ledger.state.fills
        ):
            raise ValueError("intent simulation collaborator identity or account mismatch")
        self.spec, self.execution, self.costs, self.ledger = spec, execution, costs, ledger

    def run(
        self,
        decisions: tuple[DecisionRecord, ...],
        market: tuple[IntentMarket, ...],
    ) -> IntentSimulationResult:
        """Require selected immutable inputs, then delegate to the injected model."""
        if type(decisions) is not tuple or type(market) is not tuple:
            raise TypeError("offline intent inputs require immutable tuples")
        previous: datetime | None = None
        for decision in decisions:
            if type(decision) is not DecisionRecord:
                raise TypeError("offline input requires DecisionRecord")
            decision.__post_init__()
            if (
                decision.instance != self.spec.instance
                or decision.entity != self.spec.entity
                or not self.spec.start <= decision.at < self.spec.end
                or (previous is not None and decision.at <= previous)
            ):
                raise ValueError("decision identity, sample or chronological order mismatch")
            previous = decision.at
        seen: set[str] = set()
        previous_market: tuple[datetime, datetime] | None = None
        for row in market:
            if type(row) is not IntentMarket:
                raise TypeError("offline market input requires IntentMarket")
            row.__post_init__()
            if (
                row.source_identity != self.spec.source_identity
                or row.instrument != self.spec.entity
                or row.channel != "l2"
                or row.identity in seen
                or not self.spec.start <= row.source_at <= self.spec.end
                or row.available_at > self.spec.end
                or (row.source_at == self.spec.end and row.trades)
                or (
                    previous_market is not None
                    and (row.available_at, row.source_at) < previous_market
                )
            ):
                raise ValueError("market identity, availability or sample order mismatch")
            seen.add(row.identity)
            previous_market = (row.available_at, row.source_at)
            for trade in row.trades:
                if (
                    trade.quantity.dimension != self.spec.limits.maximum.dimension
                    or trade.price.currency != self.spec.initial_cash.currency
                    or trade.price.per != self.spec.limits.maximum.dimension
                ):
                    raise ValueError("market trade instrument or quote currency mismatch")
        result = self.execution.run(self.spec, self.costs, self.ledger, decisions, market)
        if type(result) is not IntentSimulationResult:
            raise TypeError("execution model requires IntentSimulationResult")
        result.__post_init__()
        if (
            result.spec != self.spec
            or tuple(outcome.decision for outcome in result.decisions) != decisions
            or result.ledger != self.ledger.state
        ):
            raise ValueError("execution result differs from injected sample, decisions or ledger")
        return result


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
            DomainCodec().encode_json(("l2-limit-intent-v2", self.config))
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
                "receipt-as-matching-v1 maps original receipt to modeled matching time;"
                " exchange-time fill fidelity is unproven"
                if any(row.clock_assumption == "receipt-as-matching-v1" for row in market)
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
