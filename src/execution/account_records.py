"""Define stable wire records for shared account and portfolio execution."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from fractions import Fraction
from typing import Literal

# project library imports
from accounting import AccountSnapshot, AccountState, Fill
from configuration import PaperExecutionScenario
from execution.paper import PaperLiquidityState, PaperMarket
from execution.records import DroppedLeg, MarketTouch, OrderDecision, OrderEvent, OrderState
from financial_units import Currency, Dimension, Money, Price, Quantity
from portfolio import PortfolioContext
from serialization import DomainCodec, WireRecord


class AccountQuote(WireRecord, frozen=True):
    """Bind a positive valuation price to its actual UTC availability."""

    price: Price
    at: datetime

    def __post_init__(self) -> None:
        """Reject unpriced or naive valuation facts."""
        if type(self.price) is not Price:
            raise TypeError("account quote requires Price")
        self.price.model_copy()
        self._require_utc(self.at, field_name="quote availability")
        if self.price.value <= 0:
            raise ValueError("account quote must be positive")


class AccountPaperBinding(WireRecord, frozen=True):
    """Pin one venue and instrument matching scenario before account decisions."""

    account_id: str
    scenario: PaperExecutionScenario
    liquidity: PaperLiquidityState | None = None

    def __post_init__(self) -> None:
        """Require an identified account and validated immutable scenario."""
        if type(self.account_id) is not str or not self.account_id:
            raise ValueError("paper scenario requires an account")
        if type(self.scenario) is not PaperExecutionScenario:
            raise TypeError("paper binding requires PaperExecutionScenario")
        self.scenario.__post_init__()
        if self.liquidity is not None:
            if type(self.liquidity) is not PaperLiquidityState:
                raise TypeError("paper binding requires PaperLiquidityState")
            self.liquidity.__post_init__()
            if (
                self.liquidity.bid.price.per != self.scenario.adverse.per
                or self.liquidity.bid.price.currency != self.scenario.adverse.currency
                or self.liquidity.scenario_identity != self.scenario.identity
            ):
                raise ValueError("paper liquidity differs from bound scenario")


class AccountPaperTrace(WireRecord, frozen=True):
    """Retain exact public input, assumptions and attributed matching effects."""

    account_id: str
    market: PaperMarket
    scenario: PaperExecutionScenario
    input_sha256: str
    physical_events: tuple[OrderEvent, ...]
    child_fill_events: tuple[OrderEvent, ...]
    liquidity: PaperLiquidityState | None
    status: Literal["committed", "failed"] = "committed"
    reason: str = "matched"
    rejected_event: OrderEvent | None = None

    def __post_init__(self) -> None:
        """Keep a source quote and its effects attributable after restart."""
        if type(self.account_id) is not str or not self.account_id:
            raise ValueError("paper trace requires an account")
        if (
            type(self.market) is not PaperMarket
            or type(self.scenario) is not PaperExecutionScenario
        ):
            raise TypeError("paper trace requires market and scenario")
        self.market.__post_init__()
        self.scenario.__post_init__()
        if (
            type(self.input_sha256) is not str
            or self.input_sha256
            != hashlib.sha256(
                DomainCodec().encode_json((self.account_id, self.market, self.scenario))
            ).hexdigest()
            or type(self.physical_events) is not tuple
            or type(self.child_fill_events) is not tuple
            or self.status not in ("committed", "failed")
            or type(self.reason) is not str
            or not self.reason
        ):
            raise ValueError("invalid paper trace")
        if self.liquidity is not None:
            if type(self.liquidity) is not PaperLiquidityState:
                raise TypeError("paper trace requires PaperLiquidityState")
            self.liquidity.__post_init__()
            if self.liquidity.scenario_identity != self.scenario.identity:
                raise ValueError("paper trace liquidity scenario differs")
        if self.status == "committed" and (
            self.liquidity is None
            or self.liquidity.last_market_identity != self.market.identity
            or self.liquidity.last_market_at != self.market.at
        ):
            raise ValueError("committed paper trace lacks its liquidity cursor")
        for event in (*self.physical_events, *self.child_fill_events):
            if type(event) is not OrderEvent:
                raise TypeError("paper trace requires OrderEvent")
            event.__post_init__()
            if event.at != self.market.at:
                raise ValueError("paper event availability differs from source market")
        if any(event.fill is None for event in self.child_fill_events):
            raise ValueError("paper trace child events require fills")
        if self.status == "failed" and (self.physical_events or self.child_fill_events):
            raise ValueError("failed paper trace cannot claim committed economics")
        if (self.status == "failed") != (self.rejected_event is not None):
            raise ValueError("paper failure trace requires its rejected event")
        if self.rejected_event is not None:
            if type(self.rejected_event) is not OrderEvent:
                raise TypeError("paper rejection requires OrderEvent")
            self.rejected_event.__post_init__()
            if self.rejected_event.at != self.market.at:
                raise ValueError("paper rejection availability differs from source market")


class AccountPaperFill(WireRecord, frozen=True):
    """Expose a modeled fill under its final strategy and order owner."""

    instance_id: str
    order_id: str
    fill: Fill

    def __post_init__(self) -> None:
        """Keep source fill economics paired with an attributable owner."""
        if (
            type(self.instance_id) is not str
            or not self.instance_id
            or type(self.order_id) is not str
            or not self.order_id
            or type(self.fill) is not Fill
        ):
            raise ValueError("invalid attributed paper fill")
        self.fill.__post_init__()


class AccountPaperCost(WireRecord, frozen=True):
    """Link a current exact fee to its modeled child or physical source fill."""

    posting_id: str | None
    source_fill_id: str
    amount: Money

    def __post_init__(self) -> None:
        """Represent zero costs explicitly and retain an effective posting link."""
        if (
            (
                self.posting_id is not None
                and (type(self.posting_id) is not str or not self.posting_id)
            )
            or type(self.source_fill_id) is not str
            or not self.source_fill_id
            or type(self.amount) is not Money
        ):
            raise ValueError("invalid paper cost link")
        self.amount.model_copy()
        if self.posting_id is None and self.amount.value != 0:
            raise ValueError("unposted paper cost must be zero")


class AccountDecision(WireRecord, frozen=True):
    """Carry an attributable portable intent across independent account admission.

    ``quote`` is the account's valuation mark. A target or exposure intent also
    needs the ``touch`` it was decided on, since its order crosses the bid or ask.
    """

    account_id: str
    instance_id: str
    decision: OrderDecision
    quote: AccountQuote
    maximum_fee: Money
    checkpoint: bytes = b""
    touch: MarketTouch | None = None

    def __post_init__(self) -> None:
        """Validate ownership, exact economics and opaque candidate continuation."""
        if (
            type(self.account_id) is not str
            or not self.account_id
            or type(self.instance_id) is not str
            or not self.instance_id
            or type(self.checkpoint) is not bytes
        ):
            raise ValueError("account decision requires ownership and checkpoint bytes")
        if (
            type(self.decision) is not OrderDecision
            or type(self.quote) is not AccountQuote
            or type(self.maximum_fee) is not Money
        ):
            raise TypeError("account decision requires typed decision, quote and fee")
        self.decision.__post_init__()
        self.quote.__post_init__()
        self.maximum_fee.model_copy()
        if self.maximum_fee.value < 0:
            raise ValueError("account fee reserve cannot be negative")
        if self.touch is not None:
            if type(self.touch) is not MarketTouch:
                raise TypeError("account decision touch must be a MarketTouch")
            self.touch.__post_init__()
            if (
                self.touch.bid.per != self.quote.price.per
                or self.touch.bid.currency != self.quote.price.currency
            ):
                raise ValueError("account decision touch belongs to another market")
            if not self.touch.bid.value <= self.quote.price.value <= self.touch.ask.value:
                raise ValueError("account decision mark lies outside its touch")


class DecisionOutcome(WireRecord, frozen=True):
    """Summarize one saved decision's admission outcome for an operator read.

    ``dropped`` names the quote legs admission refused while the other leg was
    admitted; a rejected decision carries the reason its whole batch was refused.
    """

    account_id: str
    instance_id: str
    decision_identity: str
    decided_at: datetime
    status: Literal["committed", "rejected"]
    reason: str
    dropped: tuple[DroppedLeg, ...] = ()


class TaggedOrder(WireRecord, frozen=True):
    """Keep physical child order ownership independent of strategy callbacks."""

    account_id: str
    instance_id: str
    order: OrderState
    context: PortfolioContext | None = None
    quote: AccountQuote | None = None

    def __post_init__(self) -> None:
        """Require ownership for every reserved or posted order."""
        if (
            type(self.account_id) is not str
            or type(self.instance_id) is not str
            or not self.account_id
            or not self.instance_id
        ):
            raise ValueError("order requires account and instance")
        if type(self.order) is not OrderState:
            raise TypeError("tagged order requires OrderState")
        self.order.__post_init__()
        if (self.context is None) != (self.quote is None):
            raise ValueError("portfolio order needs context and quote together")
        if self.context is not None and self.quote is not None:
            self.context.__post_init__()
            self.quote.__post_init__()
            if self.quote.price.per != self.order.intent.quantity.dimension:
                raise ValueError("portfolio quote and order instrument differ")


class PortfolioDecision(WireRecord, frozen=True):
    """Bind one existing account admission request to complete portfolio lineage."""

    request: AccountDecision
    context: PortfolioContext
    expected_checkpoint_sha256: str | None = None

    def __post_init__(self) -> None:
        """Require independent budget request and bounded execution metadata."""
        if type(self.request) is not AccountDecision or type(self.context) is not PortfolioContext:
            raise TypeError("portfolio decision requires request and context")
        self.request.__post_init__()
        self.context.__post_init__()
        if self.expected_checkpoint_sha256 is not None and (
            type(self.expected_checkpoint_sha256) is not str
            or len(self.expected_checkpoint_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.expected_checkpoint_sha256
            )
        ):
            raise ValueError("invalid expected checkpoint digest")


class PortfolioBatch(WireRecord, frozen=True):
    """Identify one atomic pre-net admission and explicit internal crossing policy."""

    identity: str
    at: datetime
    decisions: tuple[PortfolioDecision, ...]
    crossing: str = "reject"
    schema_version: Literal["portfolio-batch"] = "portfolio-batch"

    def __post_init__(self) -> None:
        """Require immutable unique decisions and a later UTC coordination clock."""
        self._require_utc(self.at, field_name="portfolio coordination")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.decisions) is not tuple
            or not self.decisions
            or self.crossing not in ("reject", "internal_at_quote")
            or self.schema_version != "portfolio-batch"
        ):
            raise ValueError("invalid portfolio batch")
        keys: set[tuple[str, str]] = set()
        instances: set[str] = set()
        for decision in self.decisions:
            if type(decision) is not PortfolioDecision:
                raise TypeError("portfolio batch requires PortfolioDecision")
            decision.__post_init__()
            request = decision.request
            if request.decision.at >= self.at:
                raise ValueError("coordination must follow each decision")
            key = (request.instance_id, request.decision.identity)
            if key in keys:
                raise ValueError("portfolio batch repeats a decision")
            if request.instance_id in instances:
                raise ValueError("portfolio batch repeats an instance")
            keys.add(key)
            instances.add(request.instance_id)


class NetAllocation(WireRecord, frozen=True):
    """Retain a child order's fixed parent share and cumulative physical fills."""

    child_order_id: str
    quantity: Quantity
    filled: Quantity

    def __post_init__(self) -> None:
        """Keep allocated physical quantity within the original child share."""
        self.quantity.model_copy()
        self.filled.model_copy()
        if (
            type(self.child_order_id) is not str
            or not self.child_order_id
            or self.quantity.dimension != self.filled.dimension
            or self.quantity.value <= 0
            or not 0 <= self.filled.value <= self.quantity.value
        ):
            raise ValueError("invalid net allocation")


class NetOrder(WireRecord, frozen=True):
    """Represent one physical order with durable child and fill attribution."""

    account_id: str
    order: OrderState
    allocations: tuple[NetAllocation, ...]
    context: PortfolioContext
    allocation_version: Literal["pro-rata-exact"] = "pro-rata-exact"

    def __post_init__(self) -> None:
        """Reconcile every physical unit to one reserved strategy child."""
        self.order.__post_init__()
        self.context.__post_init__()
        if (
            type(self.account_id) is not str
            or not self.account_id
            or not self.allocations
            or self.allocation_version != "pro-rata-exact"
        ):
            raise ValueError("net order requires account and children")
        for allocation in self.allocations:
            allocation.__post_init__()
            if allocation.quantity.dimension != self.order.intent.quantity.dimension:
                raise ValueError("net allocation dimension differs")
        if (
            len({item.child_order_id for item in self.allocations}) != len(self.allocations)
            or sum((Fraction(item.quantity.value) for item in self.allocations), Fraction(0))
            != Fraction(self.order.intent.quantity.value)
            or sum((Fraction(item.filled.value) for item in self.allocations), Fraction(0))
            != Fraction(self.order.filled.value)
        ):
            raise ValueError("net allocations do not reconcile to physical order")


class PortfolioResidual(WireRecord, frozen=True):
    """Expose an unroutable residual without releasing its gross reservation."""

    account_id: str
    instance_id: str
    child_order_id: str
    remaining: Quantity
    reason: str

    def __post_init__(self) -> None:
        """Require owned exact positive quantity and a visible physical reason."""
        self.remaining.model_copy()
        if (
            not self.account_id
            or not self.instance_id
            or not self.child_order_id
            or not self.reason
            or self.remaining.value <= 0
        ):
            raise ValueError("invalid portfolio residual")


class PortfolioCommit(WireRecord, frozen=True):
    """Expose one atomic batch outcome and every external order to route."""

    status: str
    reason: str
    children: tuple[TaggedOrder, ...]
    net_orders: tuple[NetOrder, ...]
    internal_fill_ids: tuple[str, ...]
    residuals: tuple[PortfolioResidual, ...] = ()

    def __post_init__(self) -> None:
        """Keep rejected batches free of admitted orders and crossing effects."""
        if self.status not in ("committed", "rejected") or not self.reason:
            raise ValueError("invalid portfolio result")
        if self.status == "rejected" and (
            self.children or self.net_orders or self.internal_fill_ids or self.residuals
        ):
            raise ValueError("rejected portfolio batch has effects")
        for child in self.children:
            child.__post_init__()
        for parent in self.net_orders:
            parent.__post_init__()
        for residual in self.residuals:
            residual.__post_init__()


class NetFeeCorrection(WireRecord, frozen=True):
    """Revise an identified physical fill fee without rewriting the source fill."""

    identity: str
    physical_fill_id: str
    corrected_fee: Money
    known_at: datetime

    def __post_init__(self) -> None:
        """Require exact nonnegative fee and an identified UTC revision."""
        self._require_utc(self.known_at, field_name="physical fee correction")
        self.corrected_fee.model_copy()
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.physical_fill_id) is not str
            or not self.physical_fill_id
            or self.corrected_fee.value < 0
        ):
            raise ValueError("invalid physical fee correction")


class NetFeeAllocation(WireRecord, frozen=True):
    """Track one child's effective share and original ledger fee identity."""

    child_order_id: str
    amount: Money
    posting_id: str | None
    revision_id: str | None = None
    weight: Money | None = None

    def __post_init__(self) -> None:
        """Keep fee lineage exact and allow zero cost without a posting."""
        self.amount.model_copy()
        if self.weight is not None:
            self.weight.model_copy()
        if (
            type(self.child_order_id) is not str
            or not self.child_order_id
            or self.amount.value < 0
            or (
                self.posting_id is not None
                and (type(self.posting_id) is not str or not self.posting_id)
            )
            or (self.revision_id is None) != (self.posting_id is None)
            or (
                self.revision_id is not None
                and (type(self.revision_id) is not str or not self.revision_id)
            )
            or (
                self.weight is not None
                and (self.weight.currency != self.amount.currency or self.weight.value < 0)
            )
        ):
            raise ValueError("invalid physical fee allocation")


class AccountObservation(WireRecord, frozen=True):
    """Retain a complete independently supplied local account observation.

    Adapters must supply complete cash, positions, costs, transfer/fill identities
    and open-order cumulative state. An observation establishes only the declared
    local paper boundary; authenticated venue evidence remains adapter-owned.
    """

    identity: str
    at: datetime
    snapshot: AccountSnapshot
    open_orders: tuple[OrderState, ...]

    def __post_init__(self) -> None:
        """Refuse incomplete scope, duplicate order identities and non-UTC time."""
        self._require_utc(self.at, field_name="account observation")
        if type(self.snapshot) is not AccountSnapshot or type(self.open_orders) is not tuple:
            raise TypeError("observation requires snapshot and immutable orders")
        self.snapshot.__post_init__()
        if (
            type(self.identity) is not str
            or not self.identity
            or self.snapshot.instance_id is not None
        ):
            raise ValueError("reconciliation requires a whole-account observation")
        for order in self.open_orders:
            if type(order) is not OrderState:
                raise TypeError("observation requires OrderState")
            order.__post_init__()
            if order.is_terminal:
                raise ValueError("open-order observation contains a terminal order")
        if len({order.identity for order in self.open_orders}) != len(self.open_orders):
            raise ValueError("reconciliation repeats an order identity")


class NativeFill(WireRecord, frozen=True):
    """Carry one identified venue trade and its signed native asset charge.

    Positive fee means a charge; negative fee means a rebate. ``quantity`` is
    positive for a buy and negative for a sale. The caller resolves the venue
    order identity to the journal's physical order before constructing this fact.
    """

    identity: str
    order_id: str
    at: datetime
    filled_at: datetime
    quantity: Quantity
    price: Price
    fee: Money
    base_currency: Currency

    def __post_init__(self) -> None:
        """Require complete exact source economics and separate base/quote units."""
        self._require_utc(self.at, field_name="native fill knowledge")
        self._require_utc(self.filled_at, field_name="native fill event")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.order_id) is not str
            or not self.order_id
            or self.at < self.filled_at
        ):
            raise ValueError("invalid native fill identity or clocks")
        for value, kind in (
            (self.quantity, Quantity),
            (self.price, Price),
            (self.fee, Money),
            (self.base_currency, Currency),
        ):
            if type(value) is not kind:
                raise TypeError("native fill requires exact financial units")
            value.model_copy()
        if (
            self.quantity.value == 0
            or self.price.value <= 0
            or self.price.per != self.quantity.dimension
            or self.base_currency == self.price.currency
            or self.fee.currency not in (self.base_currency, self.price.currency)
        ):
            raise ValueError("native fill has incompatible base, quote or fee units")


class NativeFeeAllocation(WireRecord, frozen=True):
    """Bind one exact native fee or rebate share to a strategy child posting."""

    child_order_id: str
    amount: Money
    posting_id: str

    def __post_init__(self) -> None:
        """Keep source shares independently attributable through restart."""
        if (
            type(self.child_order_id) is not str
            or not self.child_order_id
            or type(self.posting_id) is not str
            or not self.posting_id
            or type(self.amount) is not Money
            or self.amount.value == 0
        ):
            raise ValueError("invalid native fee allocation")
        self.amount.model_copy()


class PhysicalAccountObservation(WireRecord, frozen=True):
    """Retain complete venue wallet totals and confirmed physical open orders.

    Fill and posting IDs are deliberately absent: a venue balance endpoint does
    not independently certify the journal's locally derived attribution IDs.
    """

    identity: str
    account_id: str
    at: datetime
    balances: tuple[Money, ...]
    instrument_currencies: tuple[tuple[Dimension, Currency], ...]
    open_orders: tuple[OrderState, ...]

    def __post_init__(self) -> None:
        """Reject ambiguous wallet units, mappings and physical order identities."""
        self._require_utc(self.at, field_name="physical account observation")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.account_id) is not str
            or not self.account_id
            or type(self.balances) is not tuple
            or type(self.instrument_currencies) is not tuple
            or type(self.open_orders) is not tuple
        ):
            raise ValueError("invalid physical observation")
        for balance in self.balances:
            if type(balance) is not Money:
                raise TypeError("wallet balance requires exact Money")
            balance.model_copy()
            if balance.value < 0:
                raise ValueError("physical spot wallet cannot be negative")
        if len({balance.currency for balance in self.balances}) != len(self.balances):
            raise ValueError("physical observation repeats a wallet currency")
        for dimension, currency in self.instrument_currencies:
            if type(dimension) is not Dimension or type(currency) is not Currency:
                raise TypeError("instrument currency mapping requires exact units")
            dimension.model_copy()
            currency.model_copy()
        if len({dimension for dimension, _ in self.instrument_currencies}) != len(
            self.instrument_currencies
        ):
            raise ValueError("physical observation repeats an instrument mapping")
        for order in self.open_orders:
            if type(order) is not OrderState:
                raise TypeError("physical observation requires OrderState")
            order.__post_init__()
            if order.is_terminal or order.status == "intent":
                raise ValueError("venue open order requires an actual physical state")
        if len({order.identity for order in self.open_orders}) != len(self.open_orders):
            raise ValueError("physical observation repeats an order identity")


type AccountPhase = Literal["running", "stopped", "faulted"]
type AccountControlKind = Literal["startup", "stop", "fault", "restart", "cancel"]


class AccountControl(WireRecord, frozen=True):
    """Identify one local paper-account operation and its recovery expectation."""

    identity: str
    account_id: str
    kind: AccountControlKind
    at: datetime
    reason: str = ""
    expected_control_identity: str | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous ownership, clocks, and recovery compare targets."""
        self._require_utc(self.at, field_name="account control")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.account_id) is not str
            or not self.account_id
            or self.kind not in ("startup", "stop", "fault", "restart", "cancel")
            or type(self.reason) is not str
            or (self.kind in ("stop", "fault") and not self.reason.strip())
            or (self.kind == "restart")
            != (
                type(self.expected_control_identity) is str and bool(self.expected_control_identity)
            )
        ):
            raise ValueError("invalid account control")


class AccountControlResult(WireRecord, frozen=True):
    """Retain the exact operation request and its durable local outcome."""

    request: AccountControl
    status: Literal["applied", "rejected"]
    phase: AccountPhase
    recovery_generation: int
    reason: str | None = None
    cancel_order_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Require a complete typed receipt without claiming terminal cancellation."""
        if type(self.request) is not AccountControl:
            raise TypeError("control result requires AccountControl")
        self.request.__post_init__()
        if (
            self.status not in ("applied", "rejected")
            or self.phase not in ("running", "stopped", "faulted")
            or type(self.recovery_generation) is not int
            or self.recovery_generation < 0
            or (self.status == "rejected") != (type(self.reason) is str and bool(self.reason))
            or type(self.cancel_order_ids) is not tuple
            or (self.request.kind != "cancel" and self.cancel_order_ids)
            or (self.status == "rejected" and self.cancel_order_ids)
            or any(type(order_id) is not str or not order_id for order_id in self.cancel_order_ids)
            or len(set(self.cancel_order_ids)) != len(self.cancel_order_ids)
        ):
            raise ValueError("invalid account control result")


class AccountView(WireRecord, frozen=True):
    """Expose authoritative local balances and independent admission blocks."""

    ledger: AccountState
    reconciled_at: datetime | None = None
    fault: str | None = None
    operator_block: str | None = None
    phase: AccountPhase = "running"
    recovery_generation: int = 0
    active_control_identity: str | None = None
    control_cutoff_at: datetime | None = None

    def __post_init__(self) -> None:
        """Require a typed ledger and separately attributable blocking state."""
        if type(self.ledger) is not AccountState:
            raise TypeError("account view requires AccountState")
        self.ledger.__post_init__()
        if self.reconciled_at is not None:
            self._require_utc(self.reconciled_at, field_name="reconciled at")
        for reason in (self.fault, self.operator_block):
            if reason is not None and (type(reason) is not str or not reason):
                raise ValueError("account block requires a reason")
        if (
            self.phase not in ("running", "stopped", "faulted")
            or type(self.recovery_generation) is not int
            or self.recovery_generation < 0
            or (self.active_control_identity is None) != (self.control_cutoff_at is None)
            or (self.phase == "running" and self.active_control_identity is not None)
            or (self.phase != "running" and self.active_control_identity is None)
            or (
                self.active_control_identity is not None
                and (
                    type(self.active_control_identity) is not str
                    or not self.active_control_identity
                )
            )
        ):
            raise ValueError("invalid account operating phase")
        if self.control_cutoff_at is not None:
            self._require_utc(self.control_cutoff_at, field_name="account control cutoff")
