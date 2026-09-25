"""Define stable wire records for shared account and portfolio execution."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from fractions import Fraction
from typing import Literal

# project library imports
from accounting import AccountSnapshot, AccountState
from execution.records import OrderDecision, OrderState
from financial_units import Money, Price, Quantity
from portfolio import PortfolioContext
from serialization import WireRecord


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


class AccountDecision(WireRecord, frozen=True):
    """Carry an attributable portable intent across independent account admission."""

    account_id: str
    instance_id: str
    decision: OrderDecision
    quote: AccountQuote
    maximum_fee: Money
    checkpoint: bytes = b""

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
    schema_version: Literal["portfolio-batch-v1"] = "portfolio-batch-v1"

    def __post_init__(self) -> None:
        """Require immutable unique decisions and a later UTC coordination clock."""
        self._require_utc(self.at, field_name="portfolio coordination")
        if (
            type(self.identity) is not str
            or not self.identity
            or type(self.decisions) is not tuple
            or not self.decisions
            or self.crossing not in ("reject", "internal_at_quote")
            or self.schema_version != "portfolio-batch-v1"
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
    allocation_version: Literal["pro-rata-exact-v1"] = "pro-rata-exact-v1"

    def __post_init__(self) -> None:
        """Reconcile every physical unit to one reserved strategy child."""
        self.order.__post_init__()
        self.context.__post_init__()
        if (
            type(self.account_id) is not str
            or not self.account_id
            or not self.allocations
            or self.allocation_version != "pro-rata-exact-v1"
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


class AccountView(WireRecord, frozen=True):
    """Expose authoritative local balances and independent admission blocks."""

    ledger: AccountState
    reconciled_at: datetime | None = None
    fault: str | None = None
    operator_block: str | None = None

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
