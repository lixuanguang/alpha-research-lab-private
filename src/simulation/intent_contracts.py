"""Define exact contracts for bounded offline decision-intent simulation."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from accounting import Fill, Ledger, LedgerMark, LedgerState
from financial_units import DecimalGrid, ExactRatio, Money, Price, Quantity
from market_data.contracts import BookObservation
from reference_data.catalogs import ReferenceHistory
from research.observations import BookFeatures
from risk import SpotLimits
from serialization import DomainCodec, WireRecord
from strategies import DecisionRecord, OrderIntent


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
