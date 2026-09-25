"""Commit independent firm admission and exact account reconciliation atomically."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal, cast

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountSnapshot, AccountState, Fill
from configuration import AccountConfiguration
from execution.lifecycle import SpotOrderLifecycle
from execution.records import OrderDecision, OrderEvent, OrderState, StepCommit
from financial_units import DecimalGrid, Dimension, Money, Price, Quantity
from portfolio import PortfolioContext, ProRataAllocator
from risk import BudgetEngine, BudgetRequest, ExposureCommitment, SpotLimits
from serialization import DomainCodec, WireRecord
from strategies import ExposureIntent, OrderIntent, TargetIntent


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


class _SavedDecision(WireRecord, frozen=True):
    """Retain original request and outcome for restart-safe idempotent admission."""

    request: AccountDecision
    result: StepCommit


class _SavedEvent(WireRecord, frozen=True):
    """Bind normalized receipt identity to exact bytes and original outcome."""

    event: OrderEvent
    result: OrderState


class _Reconciliation(WireRecord, frozen=True):
    """Retain both matching and broken observation attempts."""

    observation: AccountObservation
    matched: bool


class _SavedPortfolioBatch(WireRecord, frozen=True):
    """Retain exact coordination input and outcome for transport retry."""

    batch: PortfolioBatch
    result: PortfolioCommit


class _SavedNetEvent(WireRecord, frozen=True):
    """Retain one physical event, parent result and child fill identities."""

    event: OrderEvent
    result: NetOrder
    child_fill_ids: tuple[str, ...]
    fee_only_ids: tuple[str, ...] = ()
    fee_allocations: tuple[NetFeeAllocation, ...] = ()


class _InstanceControl(WireRecord, frozen=True):
    """Retain a selective stop or restart clock even without outstanding orders."""

    instance_id: str
    at: datetime
    state: Literal["stopped", "running"]

    def __post_init__(self) -> None:
        """Require a known UTC control transition."""
        self._require_utc(self.at, field_name="instance control")
        if not self.instance_id or self.state not in ("stopped", "running"):
            raise ValueError("invalid instance control")


class _FirmState(WireRecord, frozen=True):
    """Persist the complete local transaction boundary in one SQLite document."""

    accounts: tuple[AccountView, ...]
    orders: tuple[TaggedOrder, ...] = ()
    quotes: tuple[AccountQuote, ...] = ()
    decisions: tuple[_SavedDecision, ...] = ()
    events: tuple[_SavedEvent, ...] = ()
    reconciliations: tuple[_Reconciliation, ...] = ()
    failed_events: tuple[OrderEvent, ...] = ()
    failed_postings: tuple[AccountPosting, ...] = ()
    portfolio_batches: tuple[_SavedPortfolioBatch, ...] = ()
    net_orders: tuple[NetOrder, ...] = ()
    net_events: tuple[_SavedNetEvent, ...] = ()
    failed_net_events: tuple[OrderEvent, ...] = ()
    stopped_instances: tuple[str, ...] = ()
    crossing_policy: str | None = None
    net_fee_corrections: tuple[NetFeeCorrection, ...] = ()
    instance_controls: tuple[_InstanceControl, ...] = ()
    residuals: tuple[PortfolioResidual, ...] = ()


class _AccountTransaction:
    """Own the staged state of a single serialized firm transaction."""

    def __init__(self, state: _FirmState) -> None:
        """Retain only this transaction's immutable state value."""
        self.state = state

    def account(self, account_id: str) -> AccountView:
        """Resolve a configured account without creating implicit authority."""
        for account in self.state.accounts:
            if account.ledger.account_id == account_id:
                return account
        raise ValueError("unknown account")

    def save_account(self, account: AccountView) -> None:
        """Replace one staged account without disturbing other accounts."""
        accounts: tuple[AccountView, ...] = tuple(
            account if item.ledger.account_id == account.ledger.account_id else item
            for item in self.state.accounts
        )
        self.state = replace(self.state, accounts=accounts)

    def order(self, order_id: str) -> TaggedOrder:
        """Resolve exact persisted order identity."""
        for tagged in self.state.orders:
            if tagged.order.identity == order_id:
                return tagged
        raise ValueError("unknown child order")

    def save_order(self, tagged: TaggedOrder) -> None:
        """Replace an existing tagged order preserving stable sequence."""
        orders: tuple[TaggedOrder, ...] = tuple(
            tagged if item.order.identity == tagged.order.identity else item
            for item in self.state.orders
        )
        self.state = replace(self.state, orders=orders)

    def net_order(self, order_id: str) -> NetOrder:
        """Resolve a physical order without confusing it with child ownership."""
        for parent in self.state.net_orders:
            if parent.order.identity == order_id:
                return parent
        raise ValueError("unknown physical order")

    def save_net_order(self, parent: NetOrder) -> None:
        """Replace one physical lifecycle and allocation snapshot in place."""
        net_orders: tuple[NetOrder, ...] = tuple(
            parent if item.order.identity == parent.order.identity else item
            for item in self.state.net_orders
        )
        self.state = replace(
            self.state,
            net_orders=net_orders,
        )


class AccountJournal:
    """Own shared paper/shadow admission, reservations, postings and safe recovery.

    Every writer reads and commits under the same SQLite BEGIN IMMEDIATE lock.
    No strategy can supply its own balance or release pending capacity. Unknown
    outcomes and cancel acknowledgements retain reservations. This local command
    service has no executable transport; a venue submitter's fencing is MR11.
    """

    def __init__(self, path: Path, config: AccountConfiguration) -> None:
        """Create or reopen a journal pinned to exact configuration bytes."""
        config.__post_init__()
        self.path, self.config = path, config
        self._codec = DomainCodec()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS firm (id INTEGER PRIMARY KEY CHECK(id=1), "
                "configuration BLOB NOT NULL, payload BLOB NOT NULL)"
            )
            row = cast(
                tuple[object, ...] | None,
                connection.execute("SELECT configuration FROM firm WHERE id=1").fetchone(),
            )
            payload = self._codec.encode_json(config)
            if row is None:
                connection.execute(
                    "INSERT INTO firm VALUES (1, ?, ?)",
                    (payload, self._codec.encode_json(self._initial())),
                )
            elif row[0] != payload:
                raise ValueError("account configuration or state schema differs")
            connection.commit()

    def accounts(self) -> tuple[AccountView, ...]:
        """Read account state, reconciliation cutoff and independent block reasons."""
        return self._read().accounts

    def orders(self) -> tuple[TaggedOrder, ...]:
        """Read tagged orders, including terminal and uncertain commitments."""
        return self._read().orders

    def net_orders(self) -> tuple[NetOrder, ...]:
        """Read physical portfolio orders with exact child allocation lineage."""
        return self._read().net_orders

    def portfolio_batch(self, identity: str) -> PortfolioBatch | None:
        """Read an original immutable batch for exact older transport retry checks."""
        for saved in self._read().portfolio_batches:
            if saved.batch.identity == identity:
                return saved.batch
        return None

    def portfolio_residuals(self, account_id: str) -> tuple[PortfolioResidual, ...]:
        """Read retained unroutable child quantities and their physical grid reasons."""
        state = self._read()
        if account_id not in {view.ledger.account_id for view in state.accounts}:
            raise ValueError("unknown account")
        return tuple(
            residual
            for residual in state.residuals
            if residual.account_id == account_id
            and any(
                child.order.identity == residual.child_order_id and not child.order.is_terminal
                for child in state.orders
            )
        )

    def stopped_instances(self) -> tuple[str, ...]:
        """Read durable selective stops independently of account blocks."""
        return self._read().stopped_instances

    def failed_net_events(self) -> tuple[OrderEvent, ...]:
        """Read rejected physical facts retained for diagnosis."""
        return self._read().failed_net_events

    def physical_open_orders(self, account_id: str) -> tuple[OrderState, ...]:
        """Expose only outstanding physical orders for an independent observation."""
        state = self._read()
        if account_id not in {view.ledger.account_id for view in state.accounts}:
            raise ValueError("unknown account")
        return (
            *(
                tagged.order
                for tagged in state.orders
                if tagged.account_id == account_id
                and tagged.context is None
                and not tagged.order.is_terminal
            ),
            *(
                parent.order
                for parent in state.net_orders
                if parent.account_id == account_id and not parent.order.is_terminal
            ),
        )

    def failed_events(self) -> tuple[OrderEvent, ...]:
        """Expose retained contradictory order facts for explicit correction and diagnosis."""
        return self._read().failed_events

    def failed_postings(self) -> tuple[AccountPosting, ...]:
        """Expose retained unpostable account facts without claiming they were applied."""
        return self._read().failed_postings

    def checkpoint(self, instance_id: str) -> bytes | None:
        """Restore the last admitted or rejected continuation for one instance."""
        for saved in reversed(self._read().decisions):
            if saved.request.instance_id == instance_id:
                return saved.request.checkpoint
        return None

    def block(self, account_id: str, reason: str) -> None:
        """Persist an independent stop; reconciliation cannot clear it."""
        if type(reason) is not str or not reason.strip():
            raise ValueError("block requires a visible reason")
        with self._write() as tx:
            tx.save_account(replace(tx.account(account_id), operator_block=reason))

    def observe(self, quote: AccountQuote) -> None:
        """Persist a monotonic actual valuation fact without admitting an order."""
        quote.__post_init__()
        with self._write() as tx:
            self._quote(tx, quote)

    def admit(self, request: AccountDecision) -> StepCommit:
        """Atomically reserve all child legs and checkpoint the resulting decision.

        Exact retries return their original result; conflicting bytes fail. Targets
        use only that instance's owned position. Compatible netting/allocation is
        deliberately absent; competing opposite orders are rejected.
        """
        request.__post_init__()
        with self._write() as tx:
            for saved in tx.state.decisions:
                if (saved.request.instance_id, saved.request.decision.identity) == (
                    request.instance_id,
                    request.decision.identity,
                ):
                    if saved.request != request:
                        raise ValueError("decision identity reused with different content")
                    return saved.result
            before = tx.state
            try:
                result = self._admit(tx, request)
            except ValueError as error:
                result = StepCommit(status="rejected", reason=str(error), orders=())
            if result.status == "rejected":
                tx.state = before
            decisions: tuple[_SavedDecision, ...] = (
                *tx.state.decisions,
                _SavedDecision(request=request, result=result),
            )
            tx.state = replace(tx.state, decisions=decisions)
            return result

    def coordinate(self, batch: PortfolioBatch) -> PortfolioCommit:
        """Admit gross strategy risk, cross by policy, then create physical orders.

        All child reservations, paired internal transfers, physical parents and
        retry evidence commit under the existing serialized firm transaction.
        A rejected batch leaves no partial economic or reservation effects.
        """
        batch.__post_init__()
        with self._write() as tx:
            for saved in tx.state.portfolio_batches:
                if saved.batch.identity == batch.identity:
                    if saved.batch != batch:
                        raise ValueError("portfolio batch identity reused with different content")
                    return saved.result
            before = tx.state
            children: list[TaggedOrder] = []
            persist_rejection = False
            try:
                if (
                    tx.state.crossing_policy is not None
                    and tx.state.crossing_policy != batch.crossing
                ):
                    raise ValueError("portfolio_crossing_policy_changed")
                for item in batch.decisions:
                    request = item.request
                    if any(
                        (saved.request.instance_id, saved.request.decision.identity)
                        == (request.instance_id, request.decision.identity)
                        for saved in tx.state.decisions
                    ):
                        raise ValueError("decision_already_admitted")
                    current_checkpoint = next(
                        (
                            saved.request.checkpoint
                            for saved in reversed(tx.state.decisions)
                            if saved.request.instance_id == request.instance_id
                        ),
                        b"",
                    )
                    if (
                        item.expected_checkpoint_sha256 is not None
                        and hashlib.sha256(current_checkpoint).hexdigest()
                        != item.expected_checkpoint_sha256
                    ):
                        raise ValueError("stale_strategy_checkpoint")
                persist_rejection = True
                if tx.state.crossing_policy is None:
                    tx.state = replace(tx.state, crossing_policy=batch.crossing)
                for item in batch.decisions:
                    request = item.request
                    step_commit = self._admit(
                        tx,
                        request,
                        context=item.context,
                        crossing_ids={child.order.identity for child in children}
                        if batch.crossing == "internal_at_quote"
                        else set(),
                    )
                    if step_commit.status != "committed":
                        raise ValueError(step_commit.reason)
                    children.extend(tx.order(order.identity) for order in step_commit.orders)
                for account_id in sorted({item.request.account_id for item in batch.decisions}):
                    self._reissue_safe(tx, account_id, batch.at)
                crossed = (
                    self._cross_internal(tx, batch, tuple(children))
                    if batch.crossing == "internal_at_quote"
                    else ()
                )
                parents: list[NetOrder] = []
                for account_id in sorted({item.request.account_id for item in batch.decisions}):
                    parents.extend(self._net_pending(tx, account_id, batch.at))
                committed_children = tuple(tx.order(child.order.identity) for child in children)
                affected_accounts = {item.request.account_id for item in batch.decisions}
                residuals = tuple(
                    item for item in tx.state.residuals if item.account_id in affected_accounts
                )
                portfolio_result = PortfolioCommit(
                    status="committed",
                    reason="reserved"
                    if parents
                    else "unroutable_residual"
                    if residuals
                    else "internal_cross"
                    if crossed
                    else "target_matched",
                    children=committed_children,
                    net_orders=tuple(parents),
                    internal_fill_ids=crossed,
                    residuals=residuals,
                )
                saved_decisions: tuple[_SavedDecision, ...] = tuple(
                    _SavedDecision(
                        request=item.request,
                        result=StepCommit(
                            status="committed",
                            reason="reserved"
                            if any(
                                child.instance_id == item.request.instance_id
                                and child.order.decision_identity == item.request.decision.identity
                                for child in children
                            )
                            else "target_matched",
                            orders=tuple(
                                child.order
                                for child in children
                                if child.instance_id == item.request.instance_id
                                and child.order.decision_identity == item.request.decision.identity
                            ),
                        ),
                    )
                    for item in batch.decisions
                )
                decisions: tuple[_SavedDecision, ...] = (
                    *tx.state.decisions,
                    *saved_decisions,
                )
                tx.state = replace(
                    tx.state,
                    decisions=decisions,
                )
            except ValueError as error:
                tx.state = before
                portfolio_result = PortfolioCommit(
                    status="rejected",
                    reason=str(error),
                    children=(),
                    net_orders=(),
                    internal_fill_ids=(),
                )
                if persist_rejection:
                    rejected_decisions: tuple[_SavedDecision, ...] = tuple(
                        _SavedDecision(
                            request=item.request,
                            result=StepCommit(
                                status="rejected",
                                reason=str(error),
                                orders=(),
                            ),
                        )
                        for item in batch.decisions
                    )
                    decisions = (*tx.state.decisions, *rejected_decisions)
                    tx.state = replace(tx.state, decisions=decisions)
            portfolio_batches: tuple[_SavedPortfolioBatch, ...] = (
                *tx.state.portfolio_batches,
                _SavedPortfolioBatch(batch=batch, result=portfolio_result),
            )
            tx.state = replace(
                tx.state,
                portfolio_batches=portfolio_batches,
            )
            return portfolio_result

    def apply_net_event(self, event: OrderEvent) -> NetOrder:
        """Apply one physical fact and all attributable strategy effects atomically."""
        event.__post_init__()
        failure: str | None = None
        result: NetOrder | None = None
        with self._write() as tx:
            for saved in tx.state.net_events:
                if saved.event.identity == event.identity:
                    if saved.event != event:
                        failure = "physical event identity reused with different content"
                        self._record_failed_net_event(tx, event)
                        break
                    return saved.result
            if failure is None:
                for saved in tx.state.net_events:
                    if (
                        event.fill is not None
                        and saved.event.fill is not None
                        and event.fill.identity == saved.event.fill.identity
                    ):
                        if event.order_id != saved.event.order_id or event.fill != saved.event.fill:
                            failure = "physical fill identity reused with different economics"
                            self._record_failed_net_event(tx, event)
                            break
                        return tx.net_order(event.order_id)
            if failure is None:
                parent = tx.net_order(event.order_id)
                before = tx.state
                try:
                    result, fill_ids, fee_ids, fee_allocations = self._net_event(tx, parent, event)
                except ValueError as error:
                    failure = str(error)
                    tx.state = before
                    self._record_failed_net_event(tx, event)
                    result = parent
                else:
                    net_events: tuple[_SavedNetEvent, ...] = (
                        *tx.state.net_events,
                        _SavedNetEvent(
                            event=event,
                            result=result,
                            child_fill_ids=fill_ids,
                            fee_only_ids=fee_ids,
                            fee_allocations=fee_allocations,
                        ),
                    )
                    tx.state = replace(
                        tx.state,
                        net_events=net_events,
                    )
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        if result is None:
            raise AssertionError("physical event completed without a result")
        return result

    def correct_net_fee(self, correction: NetFeeCorrection) -> NetOrder:
        """Revise one physical fill fee and its child postings in one transaction.

        The original source fill remains immutable. Each corrected child fee
        replaces its effective posting under the append-only AccountLedger,
        while the parent and child fee reservations change by exactly the same
        amount. New risk stays blocked until independent account reconciliation.
        """
        correction.__post_init__()
        with self._write() as tx:
            for saved in tx.state.net_fee_corrections:
                if saved.identity == correction.identity:
                    if saved != correction:
                        raise ValueError("physical fee correction identity reused")
                    source = next(
                        item
                        for item in tx.state.net_events
                        if item.event.fill is not None
                        and item.event.fill.identity == correction.physical_fill_id
                    )
                    return tx.net_order(source.event.order_id)
            source_index = next(
                (
                    index
                    for index, item in enumerate(tx.state.net_events)
                    if item.event.fill is not None
                    and item.event.fill.identity == correction.physical_fill_id
                ),
                None,
            )
            if source_index is None:
                raise ValueError("unknown physical fill")
            source = tx.state.net_events[source_index]
            fill = source.event.fill
            if fill is None:
                raise ValueError("physical fill is missing")
            parent = tx.net_order(source.event.order_id)
            account = tx.account(parent.account_id)
            if correction.known_at < max(fill.filled_at, self._account_time(tx, account)):
                raise ValueError("physical fee correction clock regressed")
            if correction.corrected_fee.currency != fill.fee.currency:
                raise ValueError("physical fee correction currency differs")
            if not source.fee_allocations:
                raise ValueError("physical fill lacks cost attribution")
            children = tuple(tx.order(item.child_order_id) for item in source.fee_allocations)
            capacities = tuple(
                (child.order.maximum_fee - child.order.paid_fee + item.amount).value
                for child, item in zip(children, source.fee_allocations, strict=True)
            )
            amounts = ProRataAllocator().split_capped(
                amount=correction.corrected_fee.value,
                capacities=tuple(
                    item.weight.value if item.weight is not None else capacity
                    for item, capacity in zip(source.fee_allocations, capacities, strict=True)
                ),
                identities=tuple(item.child_order_id for item in source.fee_allocations),
            )
            if any(value > capacity for value, capacity in zip(amounts, capacities, strict=True)):
                raise ValueError("corrected fee exceeds child reservation")
            ledger = AccountLedger(account.ledger)
            revised: list[NetFeeAllocation] = []
            for item, child, value in zip(source.fee_allocations, children, amounts, strict=True):
                posting_id = item.posting_id
                revision_id = item.revision_id
                if value != item.amount.value:
                    if posting_id is None:
                        if value:
                            posting_id = hashlib.sha256(
                                self._codec.encode_json(
                                    (
                                        "new-physical-fee-v1",
                                        correction.identity,
                                        fill.identity,
                                        item.child_order_id,
                                    )
                                )
                            ).hexdigest()
                            revision_id = posting_id
                            ledger.post(
                                AccountPosting(
                                    identity=posting_id,
                                    account_id=parent.account_id,
                                    instance_id=child.instance_id,
                                    order_id=child.order.identity,
                                    kind="fee",
                                    event_at=fill.filled_at,
                                    known_at=correction.known_at,
                                    cash=Money(
                                        value=value.copy_negate(), currency=fill.fee.currency
                                    ),
                                )
                            )
                    else:
                        next_revision_id = hashlib.sha256(
                            self._codec.encode_json(
                                ("physical-fee-revision-v1", correction.identity, posting_id)
                            )
                        ).hexdigest()
                        ledger.post(
                            AccountPosting(
                                identity=next_revision_id,
                                account_id=parent.account_id,
                                instance_id=child.instance_id,
                                order_id=child.order.identity,
                                kind="correction",
                                corrects=revision_id,
                                replacement_kind="fee" if value else None,
                                event_at=fill.filled_at,
                                known_at=correction.known_at,
                                cash=Money(value=value.copy_negate(), currency=fill.fee.currency),
                            )
                        )
                        revision_id = next_revision_id
                    updated_fee = (
                        child.order.paid_fee
                        - item.amount
                        + Money(value=value, currency=fill.fee.currency)
                    )
                    tx.save_order(replace(child, order=replace(child.order, paid_fee=updated_fee)))
                revised.append(
                    NetFeeAllocation(
                        child_order_id=item.child_order_id,
                        amount=Money(value=value, currency=fill.fee.currency),
                        posting_id=posting_id,
                        revision_id=revision_id,
                        weight=item.weight,
                    )
                )
            old_total = sum(
                (Fraction(item.amount.value) for item in source.fee_allocations), Fraction(0)
            )
            revised_paid = Money(
                value=DecimalGrid.exact_decimal(
                    Fraction(parent.order.paid_fee.value)
                    - old_total
                    + Fraction(correction.corrected_fee.value)
                ),
                currency=parent.order.paid_fee.currency,
            )
            updated_parent = replace(parent, order=replace(parent.order, paid_fee=revised_paid))
            tx.save_net_order(updated_parent)
            tx.save_account(replace(account, ledger=ledger.state, fault="posting_reconciliation"))
            revised_allocations: tuple[NetFeeAllocation, ...] = tuple(revised)
            net_events: tuple[_SavedNetEvent, ...] = tuple(
                replace(item, fee_allocations=revised_allocations)
                if index == source_index
                else item
                for index, item in enumerate(tx.state.net_events)
            )
            corrections: tuple[NetFeeCorrection, ...] = (
                *tx.state.net_fee_corrections,
                correction,
            )
            tx.state = replace(
                tx.state,
                net_events=net_events,
                net_fee_corrections=corrections,
            )
            return updated_parent

    def stop_instance(self, instance_id: str, at: datetime) -> tuple[NetOrder, ...]:
        """Fence one strategy and request cancellation of shared physical parents.

        Other children keep their gross reservations until the parent confirms a
        terminal outcome. A caller must route returned physical cancellation
        requests and later reconcile before reissuing unaffected residuals.
        """
        self._require_instance(instance_id)
        self._require_utc(at, field_name="strategy stop")
        with self._write() as tx:
            owner = self._instance_account(instance_id)
            if at < self._account_time(tx, tx.account(owner)):
                raise ValueError("strategy stop clock regressed")
            if instance_id in tx.state.stopped_instances:
                return tuple(
                    parent
                    for parent in tx.state.net_orders
                    if not parent.order.is_terminal
                    and any(
                        tx.order(allocation.child_order_id).instance_id == instance_id
                        for allocation in parent.allocations
                    )
                )
            stopped_instances: tuple[str, ...] = (*tx.state.stopped_instances, instance_id)
            controls: tuple[_InstanceControl, ...] = (
                *tx.state.instance_controls,
                _InstanceControl(instance_id=instance_id, at=at, state="stopped"),
            )
            tx.state = replace(
                tx.state, stopped_instances=stopped_instances, instance_controls=controls
            )
            affected: list[NetOrder] = []
            attached = {
                allocation.child_order_id
                for parent in tx.state.net_orders
                if not parent.order.is_terminal
                for allocation in parent.allocations
            }
            for parent in tx.state.net_orders:
                if parent.order.is_terminal or not any(
                    tx.order(allocation.child_order_id).instance_id == instance_id
                    for allocation in parent.allocations
                ):
                    continue
                updated = parent
                if not parent.order.cancel_requested:
                    request = OrderEvent(
                        identity=f"stop:{instance_id}:{parent.order.identity}",
                        order_id=parent.order.identity,
                        at=at,
                        kind="cancel_requested",
                    )
                    physical = SpotOrderLifecycle(
                        self._limits(parent.order.intent.limit)
                    ).transition(parent.order, request)
                    updated = replace(parent, order=physical)
                    tx.save_net_order(updated)
                    net_events = (
                        *tx.state.net_events,
                        _SavedNetEvent(event=request, result=updated, child_fill_ids=()),
                    )
                    tx.state = replace(
                        tx.state,
                        net_events=net_events,
                    )
                affected.append(updated)
            for child in tx.state.orders:
                if (
                    child.instance_id == instance_id
                    and not child.order.is_terminal
                    and child.order.identity not in attached
                ):
                    if child.context is not None:
                        tx.save_order(
                            replace(child, order=replace(child.order, status="cancelled"))
                        )
                    elif not child.order.cancel_requested:
                        request = OrderEvent(
                            identity=f"stop:{instance_id}:{child.order.identity}",
                            order_id=child.order.identity,
                            at=at,
                            kind="cancel_requested",
                        )
                        updated_order = SpotOrderLifecycle(
                            self._limits(child.order.intent.limit)
                        ).transition(child.order, request)
                        tx.save_order(replace(child, order=updated_order))
                        saved_events: tuple[_SavedEvent, ...] = (
                            *tx.state.events,
                            _SavedEvent(event=request, result=updated_order),
                        )
                        tx.state = replace(tx.state, events=saved_events)
            return tuple(affected)

    def restart_instance(self, instance_id: str, at: datetime) -> None:
        """Re-enable a stopped instance only after physical release and reconciliation."""
        self._require_instance(instance_id)
        self._require_utc(at, field_name="strategy restart")
        with self._write() as tx:
            if instance_id not in tx.state.stopped_instances:
                raise ValueError("instance is not stopped")
            account = tx.account(self._instance_account(instance_id))
            if (
                account.fault
                or account.operator_block
                or account.reconciled_at is None
                or account.reconciled_at < self._account_time(tx, account)
                or at < account.reconciled_at
                or any(
                    child.instance_id == instance_id and not child.order.is_terminal
                    for child in tx.state.orders
                )
            ):
                raise ValueError("instance_restart_requires_reconciliation")
            stopped_instances = tuple(
                saved for saved in tx.state.stopped_instances if saved != instance_id
            )
            controls = (
                *tx.state.instance_controls,
                _InstanceControl(instance_id=instance_id, at=at, state="running"),
            )
            tx.state = replace(
                tx.state, stopped_instances=stopped_instances, instance_controls=controls
            )

    def reissue_pending(self, account_id: str, at: datetime) -> tuple[NetOrder, ...]:
        """Create physical orders for unaffected residuals after a complete observation."""
        self._require_utc(at, field_name="physical reissue")
        with self._write() as tx:
            account = tx.account(account_id)
            if account.fault or account.operator_block or account.reconciled_at is None:
                raise ValueError("account_not_reconciled")
            if account.reconciled_at < self._account_time(tx, account):
                raise ValueError("reissue_requires_current_reconciliation")
            if at < self._account_time(tx, account):
                raise ValueError("physical reissue clock regressed")
            if any(
                parent.account_id == account_id and parent.order.status == "unknown"
                for parent in tx.state.net_orders
            ):
                raise ValueError("order_outcome_unknown")
            self._reissue_safe(tx, account_id, at)
            return self._net_pending(tx, account_id, at)

    def apply_event(self, event: OrderEvent) -> OrderState:
        """Post normalized order/fill facts once; contradictions durably block risk."""
        event.__post_init__()
        failure: str | None = None
        result: OrderState | None = None
        with self._write() as tx:
            for saved in tx.state.events:
                if saved.event.identity == event.identity:
                    if saved.event != event:
                        failure = "event identity reused with different content"
                        self._record_failed_event(tx, event)
                        break
                    return saved.result
            if failure is None:
                for saved in tx.state.events:
                    if (
                        event.fill is not None
                        and saved.event.fill is not None
                        and saved.event.fill.identity == event.fill.identity
                    ):
                        if event.order_id != saved.event.order_id or event.fill != saved.event.fill:
                            failure = "fill identity reused with different economics"
                            self._record_failed_event(tx, event)
                            break
                        return tx.order(event.order_id).order
            if failure is None:
                tagged = tx.order(event.order_id)
                if tagged.context is not None:
                    raise ValueError("portfolio child events require physical parent routing")
                if self.config.mode == "shadow" and event.fill is not None:
                    raise ValueError("shadow mode cannot post modeled fills")
                try:
                    result = self._event(tx, tagged, event)
                except ValueError as error:
                    failure = str(error)
                    self._record_failed_event(tx, event)
                    result = tagged.order
                else:
                    events: tuple[_SavedEvent, ...] = (
                        *tx.state.events,
                        _SavedEvent(event=event, result=result),
                    )
                    tx.state = replace(tx.state, events=events)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        if result is None:
            raise AssertionError("order event completed without a result")
        return result

    def post(self, posting: AccountPosting) -> AccountSnapshot:
        """Apply identified transfers, costs or explicit economic corrections.

        Fill postings use the same reserved order boundary as lifecycle events.
        An observed late fill or correction is retained without erasing the old
        fact and keeps new risk blocked until a complete independent reconciliation.
        """
        posting.__post_init__()
        if self.config.mode == "shadow" and posting.kind in ("fill", "correction"):
            raise ValueError("shadow mode cannot post modeled fill or correction")
        failure: str | None = None
        with self._write() as tx:
            account = tx.account(posting.account_id)
            before = tx.state
            ledger = AccountLedger(account.ledger)
            snapshot = ledger.snapshot()
            try:
                prior = next(
                    (p for p in ledger.state.postings if p.identity == posting.identity), None
                )
                if prior is None and posting.order_id is not None:
                    owner = tx.order(posting.order_id)
                    if owner.context is not None and posting.kind in ("fill", "fee"):
                        raise ValueError(
                            "portfolio child economics require physical parent routing"
                        )
                    if owner.context is not None and posting.kind == "correction":
                        target = next(
                            (
                                item
                                for item in ledger.state.postings
                                if item.identity == posting.corrects
                            ),
                            None,
                        )
                        if target is None or (
                            target.kind != "rebate" and target.replacement_kind != "rebate"
                        ):
                            raise ValueError("portfolio child correction requires physical lineage")
                if prior is None and posting.known_at < self._account_time(tx, account):
                    raise ValueError("posting knowledge precedes current account state")
                previous = ledger.state
                snapshot = ledger.post(posting)
                if previous == ledger.state:
                    return snapshot
                if posting.order_id is not None:
                    tagged = tx.order(posting.order_id)
                    if (tagged.account_id, tagged.instance_id) != (
                        posting.account_id,
                        posting.instance_id,
                    ):
                        raise ValueError("posting order ownership differs")
                    if (
                        posting.effective_kind == "fill"
                        and posting.event_at <= tagged.order.decision_at
                    ):
                        raise ValueError("fill must follow its decision")
                    corrected = self._posted_order(tagged.order, ledger)
                    tx.save_order(replace(tagged, order=corrected))
                elif posting.kind in ("fill", "fee", "rebate"):
                    raise ValueError("trading postings require a reserved order")
                tx.save_account(
                    replace(account, ledger=ledger.state, fault="posting_reconciliation")
                )
            except ValueError as error:
                failure = str(error)
                tx.state = before
                tx.save_account(replace(account, fault="posting_break"))
                failed: tuple[AccountPosting, ...] = (*tx.state.failed_postings, posting)
                tx.state = replace(tx.state, failed_postings=failed)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        return snapshot

    def reconcile(self, observation: AccountObservation) -> bool:
        """Compare all account and open-order facts, preserving operator stops.

        Missing/extra orders, altered cumulative fills, stale clocks, mismatched
        currency cash, positions, fees, rebates or transfers block new exposure.
        An unknown order must first receive explicit order reconciliation.
        """
        observation.__post_init__()
        with self._write() as tx:
            for saved in tx.state.reconciliations:
                if saved.observation.identity == observation.identity:
                    if saved.observation != observation:
                        raise ValueError("observation identity reused with different content")
                    return saved.matched
            account = tx.account(observation.snapshot.account_id)
            ledger = AccountLedger(account.ledger)
            latest = self._account_time(tx, account)
            orders = tuple(
                tagged.order
                for tagged in tx.state.orders
                if tagged.account_id == observation.snapshot.account_id
                and tagged.context is None
                and not tagged.order.is_terminal
            ) + tuple(
                parent.order
                for parent in tx.state.net_orders
                if parent.account_id == observation.snapshot.account_id
                and not parent.order.is_terminal
            )
            latest = max(latest, *(o.decision_at for o in orders)) if orders else latest
            matched = (
                observation.at >= latest
                and (account.reconciled_at is None or observation.at >= account.reconciled_at)
                and observation.snapshot == ledger.snapshot()
                and {o.identity: o for o in observation.open_orders}
                == {o.identity: o for o in orders}
                and not any(o.status == "unknown" for o in orders)
                and self._physical_attribution_matches(tx, account.ledger.account_id)
                and not any(
                    p.account_id == account.ledger.account_id
                    and p.identity
                    not in tuple(applied.identity for applied in account.ledger.postings)
                    for p in tx.state.failed_postings
                )
                and not any(
                    account.ledger.account_id in self._failed_event_account_ids(tx, failed)
                    and (
                        self._failed_event_conflicts_with_accepted_fact(tx, failed)
                        or (
                            failed.fill is not None
                            and failed.fill.identity
                            not in tuple(posting.identity for posting in account.ledger.postings)
                        )
                    )
                    for failed in tx.state.failed_events
                )
                and not any(
                    account.ledger.account_id in self._failed_net_event_account_ids(tx, failed)
                    for failed in tx.state.failed_net_events
                )
            )
            if matched:
                try:
                    self._funded(tx, account.ledger.account_id)
                except ValueError:
                    matched = False
            tx.save_account(
                replace(
                    account,
                    fault=None if matched else "account_break",
                    reconciled_at=observation.at if matched else account.reconciled_at,
                )
            )
            reconciliations: tuple[_Reconciliation, ...] = (
                *tx.state.reconciliations,
                _Reconciliation(observation=observation, matched=matched),
            )
            tx.state = replace(tx.state, reconciliations=reconciliations)
            return matched

    def _account_time(self, tx: _AccountTransaction, account: AccountView) -> datetime:
        """Return the latest knowledge clock whose state admission would consume."""
        account_id = account.ledger.account_id
        clocks = [self.config.opening_at]
        if account.reconciled_at is not None:
            clocks.append(account.reconciled_at)
        clocks.extend(p.known_at for p in account.ledger.postings)
        clocks.extend(t.order.decision_at for t in tx.state.orders if t.account_id == account_id)
        clocks.extend(
            saved.event.at
            for saved in tx.state.events
            if tx.order(saved.event.order_id).account_id == account_id
        )
        clocks.extend(
            event.at
            for event in tx.state.failed_events
            if account_id in self._failed_event_account_ids(tx, event)
        )
        clocks.extend(
            parent.order.decision_at
            for parent in tx.state.net_orders
            if parent.account_id == account_id
        )
        clocks.extend(
            saved.event.at
            for saved in tx.state.net_events
            if tx.net_order(saved.event.order_id).account_id == account_id
        )
        clocks.extend(
            event.at
            for event in tx.state.failed_net_events
            if account_id in self._failed_net_event_account_ids(tx, event)
        )
        clocks.extend(
            control.at
            for control in tx.state.instance_controls
            if self._instance_account(control.instance_id) == account_id
        )
        return max(clocks)

    @staticmethod
    def _record_failed_event(tx: _AccountTransaction, event: OrderEvent) -> None:
        """Retain one rejected direct fact and durably fence its account."""
        failed_events = tx.state.failed_events
        if event not in failed_events:
            failed_events = (*failed_events, event)
        for account_id in AccountJournal._failed_event_account_ids(tx, event):
            tx.save_account(replace(tx.account(account_id), fault="order_event_break"))
        tx.state = replace(tx.state, failed_events=failed_events)

    @staticmethod
    def _record_failed_net_event(tx: _AccountTransaction, event: OrderEvent) -> None:
        """Retain one rejected physical fact and durably fence its account."""
        failed_net_events = tx.state.failed_net_events
        if event not in failed_net_events:
            failed_net_events = (*failed_net_events, event)
        for account_id in AccountJournal._failed_net_event_account_ids(tx, event):
            tx.save_account(replace(tx.account(account_id), fault="physical_event_break"))
        tx.state = replace(tx.state, failed_net_events=failed_net_events)

    @staticmethod
    def _failed_event_account_ids(tx: _AccountTransaction, event: OrderEvent) -> tuple[str, ...]:
        """Resolve every account named by a rejected direct source fact."""
        account_ids: list[str] = []
        for saved in tx.state.events:
            if saved.event.identity == event.identity or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
            ):
                account_ids.append(tx.order(saved.event.order_id).account_id)
        try:
            account_ids.append(tx.order(event.order_id).account_id)
        except ValueError:
            if not account_ids:
                raise
        unique_account_ids: list[str] = []
        for account_id in account_ids:
            if account_id not in unique_account_ids:
                unique_account_ids.append(account_id)
        return tuple(unique_account_ids)

    @staticmethod
    def _failed_event_conflicts_with_accepted_fact(
        tx: _AccountTransaction, event: OrderEvent
    ) -> bool:
        """Identify a rejected fact that contradicts retained accepted source bytes."""
        return any(
            (saved.event.identity == event.identity and saved.event != event)
            or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
                and (event.order_id != saved.event.order_id or event.fill != saved.event.fill)
            )
            for saved in tx.state.events
        )

    @staticmethod
    def _failed_net_event_account_ids(
        tx: _AccountTransaction, event: OrderEvent
    ) -> tuple[str, ...]:
        """Resolve every account named by a rejected physical source fact."""
        account_ids: list[str] = []
        for saved in tx.state.net_events:
            if saved.event.identity == event.identity or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
            ):
                account_ids.append(tx.net_order(saved.event.order_id).account_id)
        try:
            account_ids.append(tx.net_order(event.order_id).account_id)
        except ValueError:
            if not account_ids:
                raise
        unique_account_ids: list[str] = []
        for account_id in account_ids:
            if account_id not in unique_account_ids:
                unique_account_ids.append(account_id)
        return tuple(unique_account_ids)

    def _require_instance(self, instance_id: str) -> None:
        """Reject unknown control targets without altering account state."""
        if not any(owner.instance_id == instance_id for owner in self.config.budgets.instances):
            raise ValueError("unknown instance")

    @staticmethod
    def _require_utc(at: datetime, *, field_name: str) -> None:
        """Require a caller-owned UTC control time without normalizing it."""
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise TypeError(f"{field_name} must be timezone-aware")
        if at.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must use UTC")

    def _instance_account(self, instance_id: str) -> str:
        """Resolve configured physical ownership for a strategy control."""
        for owner in self.config.budgets.instances:
            if owner.instance_id == instance_id:
                return owner.account_id
        raise ValueError("unknown instance")

    def _admit(
        self,
        tx: _AccountTransaction,
        request: AccountDecision,
        *,
        context: PortfolioContext | None = None,
        crossing_ids: set[str] | None = None,
    ) -> StepCommit:
        """Evaluate a decision against authoritative holdings and firm commitments."""
        account = tx.account(request.account_id)
        if account.operator_block or account.fault:
            raise ValueError(account.operator_block or account.fault or "account_blocked")
        if request.instance_id in tx.state.stopped_instances:
            raise ValueError("instance_stopped")
        if account.reconciled_at is None:
            raise ValueError("account_not_reconciled")
        if request.decision.at < max(self._account_time(tx, item) for item in tx.state.accounts):
            raise ValueError("decision_precedes_account_state")
        if any(
            t.account_id == request.account_id and t.order.status == "unknown"
            for t in tx.state.orders
        ) or any(
            parent.account_id == request.account_id and parent.order.status == "unknown"
            for parent in tx.state.net_orders
        ):
            raise ValueError("order_outcome_unknown")
        owner = next(
            (i for i in self.config.budgets.instances if i.instance_id == request.instance_id), None
        )
        if (
            owner is None
            or owner.account_id != request.account_id
            or request.quote.price.per.instrument_id not in owner.instruments
        ):
            raise ValueError("unauthorized_instance_or_instrument")
        if request.quote.at > request.decision.at:
            raise ValueError("future_quote")
        observed = next(
            (q for q in tx.state.quotes if q.price.per == request.quote.price.per), None
        )
        if observed != request.quote:
            raise ValueError("unobserved_quote")
        limits = self._limits(request.quote.price)
        ledger = AccountLedger(account.ledger)
        owned = ledger.snapshot(instance_id=request.instance_id)
        holding = next(
            (p for p in owned.positions if p.dimension == limits.lot.dimension),
            Quantity(value=Decimal(0), dimension=limits.lot.dimension),
        )
        lifecycle = SpotOrderLifecycle(limits)
        if isinstance(request.decision.intent, (TargetIntent, ExposureIntent)) and any(
            t.instance_id == request.instance_id and not t.order.is_terminal
            for t in tx.state.orders
        ):
            raise ValueError("pending_target")
        legs = lifecycle.lower(request.decision.intent, holding, request.quote.price)
        admitted: list[OrderState] = []
        for leg_name, intent in legs:
            reason = lifecycle.order_reason(intent)
            if reason is not None:
                raise ValueError(reason)
            commitments = self._commitments(tx, request.decision.at)
            reason = BudgetEngine().evaluate(
                self.config.budgets,
                BudgetRequest(
                    account_id=request.account_id,
                    instance_id=request.instance_id,
                    intent=intent,
                    decision_at=request.decision.at,
                    quote=request.quote.price,
                    quote_at=request.quote.at,
                    state_at=account.reconciled_at,
                    maximum_fee=request.maximum_fee,
                ),
                commitments,
            )
            if reason is not None:
                raise ValueError(reason)
            for tagged in tx.state.orders:
                order = tagged.order
                if (
                    tagged.account_id == request.account_id
                    and not order.is_terminal
                    and order.intent.quantity.dimension == intent.quantity.dimension
                    and order.intent.side != intent.side
                    and order.identity not in (crossing_ids or set())
                    and (
                        intent.limit.value >= order.intent.limit.value
                        if intent.side == "buy"
                        else intent.limit.value <= order.intent.limit.value
                    )
                ):
                    raise ValueError("self_trade_conflict")
            identity = hashlib.sha256(
                self._codec.encode_json(
                    (
                        "account-child-v1",
                        request.account_id,
                        request.instance_id,
                        request.decision.identity,
                        leg_name,
                    )
                )
            ).hexdigest()
            order = OrderState(
                identity=identity,
                decision_identity=request.decision.identity,
                decision_at=request.decision.at,
                intent=intent,
                status="intent",
                filled=Quantity(value=Decimal(0), dimension=intent.quantity.dimension),
                paid_fee=Money(value=Decimal(0), currency=intent.limit.currency),
                maximum_fee=request.maximum_fee,
            )
            orders: tuple[TaggedOrder, ...] = (
                *tx.state.orders,
                TaggedOrder(
                    account_id=request.account_id,
                    instance_id=request.instance_id,
                    order=order,
                    context=context,
                    quote=request.quote if context is not None else None,
                ),
            )
            tx.state = replace(tx.state, orders=orders)
            self._funded(tx, request.account_id)
            admitted.append(order)
        return StepCommit(
            status="committed",
            reason="reserved" if admitted else "target_matched",
            orders=tuple(admitted),
        )

    def _commitments(self, tx: _AccountTransaction, at: datetime) -> tuple[ExposureCommitment, ...]:
        """Count held positions and unresolved buys/fees without offsetting sell orders."""
        result: list[ExposureCommitment] = []
        currency = self.config.budgets.valuation_currency
        attached = {
            allocation.child_order_id
            for parent in tx.state.net_orders
            if not parent.order.is_terminal
            for allocation in parent.allocations
        }
        for owner in self.config.budgets.instances:
            account = tx.account(owner.account_id)
            ledger = AccountLedger(account.ledger)
            held = Money(value=Decimal(0), currency=currency)
            reserved = held
            positions = ledger.snapshot(instance_id=owner.instance_id).positions
            orders = tuple(
                t.order
                for t in tx.state.orders
                if t.instance_id == owner.instance_id
                and (not t.order.is_terminal or t.order.identity in attached)
            )
            if positions or orders:
                if account.fault or account.operator_block or account.reconciled_at is None:
                    raise ValueError("firm_account_unavailable")
                age = at - account.reconciled_at
                if (
                    age.days < 0
                    or age.days * 86_400_000_000 + age.seconds * 1_000_000 + age.microseconds
                    > self.config.budgets.max_state_age_us
                ):
                    raise ValueError("stale_firm_account")
            for position in positions:
                if position.value == 0:
                    continue
                quote = next(
                    (q for q in tx.state.quotes if q.price.per == position.dimension), None
                )
                if quote is None:
                    raise ValueError("missing_position_valuation")
                age = at - quote.at
                if (
                    age.days < 0
                    or age.days * 86_400_000_000 + age.seconds * 1_000_000 + age.microseconds
                    > self.config.budgets.max_quote_age_us
                ):
                    raise ValueError("stale_position_valuation")
                held += quote.price.amount(position)
            for order in orders:
                reserved += order.maximum_fee - order.paid_fee
                if order.intent.side == "buy" and not order.is_terminal:
                    reserved += order.intent.limit.amount(order.remaining)
            result.append(
                ExposureCommitment(
                    account_id=owner.account_id,
                    instance_id=owner.instance_id,
                    held_exposure=held,
                    reserved_exposure=reserved,
                )
            )
        return tuple(result)

    def _funded(self, tx: _AccountTransaction, account_id: str) -> None:
        """Require physical cash and both owned and account inventory for every pending leg."""
        ledger = AccountLedger(tx.account(account_id).ledger)
        snapshot = ledger.snapshot()
        cash = {m.currency: m for m in snapshot.cash}
        buys: dict[Dimension, Quantity] = {}
        sells: dict[tuple[str, Dimension], Quantity] = {}
        attached = {
            allocation.child_order_id
            for parent in tx.state.net_orders
            if not parent.order.is_terminal
            for allocation in parent.allocations
        }
        for tagged in tx.state.orders:
            order = tagged.order
            if tagged.account_id != account_id or (
                order.is_terminal and order.identity not in attached
            ):
                continue
            currency = order.maximum_fee.currency
            cash[currency] -= order.maximum_fee - order.paid_fee
            if order.is_terminal:
                continue
            dim = order.intent.quantity.dimension
            zero = Quantity(value=Decimal(0), dimension=dim)
            if order.intent.side == "buy":
                cash[currency] -= order.intent.limit.amount(order.remaining)
                buys[dim] = buys.get(dim, zero) + order.remaining
            else:
                key = (tagged.instance_id, dim)
                sells[key] = sells.get(key, zero) + order.remaining
        if any(m.value < 0 for m in cash.values()):
            raise ValueError("insufficient_cash")
        for (instance_id, dim), reserved in sells.items():
            position = next(
                (
                    p
                    for p in ledger.snapshot(instance_id=instance_id).positions
                    if p.dimension == dim
                ),
                None,
            )
            if position is None or position.value < reserved.value:
                raise ValueError("insufficient_owned_inventory")
        for limits in self.config.instruments:
            position = next(
                (p for p in snapshot.positions if p.dimension == limits.lot.dimension),
                Quantity(value=Decimal(0), dimension=limits.lot.dimension),
            )
            if (
                position
                + buys.get(
                    position.dimension, Quantity(value=Decimal(0), dimension=position.dimension)
                )
            ).value > limits.maximum.value:
                raise ValueError("holding_limit")

    def _reissue_safe(self, tx: _AccountTransaction, account_id: str, at: datetime) -> None:
        """Recheck gross capital, funding and fresh prices before another physical send."""
        self._funded(tx, account_id)
        commitments = self._commitments(tx, at)
        policy = self.config.budgets
        by_instance = {owner.instance_id: owner for owner in policy.instances}
        by_account = {account.account_id: account for account in policy.accounts}
        account_exposure: dict[str, Fraction] = {}
        firm_exposure = Fraction(0)
        for commitment in commitments:
            amount = Fraction(commitment.held_exposure.value) + Fraction(
                commitment.reserved_exposure.value
            )
            if amount > Fraction(by_instance[commitment.instance_id].maximum.value):
                raise ValueError("instance_limit")
            account_exposure[commitment.account_id] = (
                account_exposure.get(commitment.account_id, Fraction(0)) + amount
            )
            firm_exposure += amount
        if any(
            amount > Fraction(by_account[owner].maximum.value)
            for owner, amount in account_exposure.items()
        ):
            raise ValueError("account_limit")
        if firm_exposure > Fraction(policy.firm_maximum.value):
            raise ValueError("firm_limit")
        assigned = {
            item.child_order_id
            for parent in tx.state.net_orders
            if not parent.order.is_terminal
            for item in parent.allocations
        }
        for child in tx.state.orders:
            if (
                child.account_id != account_id
                or child.context is None
                or child.order.is_terminal
                or child.order.identity in assigned
            ):
                continue
            quote = next(
                (
                    item
                    for item in tx.state.quotes
                    if item.price.per == child.order.intent.quantity.dimension
                ),
                None,
            )
            if (
                quote is None
                or quote.at > at
                or at - quote.at > timedelta(microseconds=policy.max_quote_age_us)
            ):
                raise ValueError("stale_quote")
            reference = Fraction(quote.price.value)
            limit = Fraction(child.order.intent.limit.value)
            if abs(limit - reference) * 10_000 > reference * policy.max_price_deviation_bps:
                raise ValueError("price_deviation")

    def _cross_internal(
        self,
        tx: _AccountTransaction,
        batch: PortfolioBatch,
        children: tuple[TaggedOrder, ...],
    ) -> tuple[str, ...]:
        """Transfer owned spot inventory at the common quote under explicit policy."""
        fill_ids: list[str] = []
        buys = tuple(
            child
            for _, child in sorted(
                (child.order.identity, child)
                for child in children
                if child.order.intent.side == "buy"
            )
        )
        sells = tuple(
            child
            for _, child in sorted(
                (child.order.identity, child)
                for child in children
                if child.order.intent.side == "sell"
            )
        )
        for buy in buys:
            for sell in sells:
                current_buy = tx.order(buy.order.identity)
                current_sell = tx.order(sell.order.identity)
                bid = current_buy.order
                ask = current_sell.order
                if (
                    current_buy.account_id != current_sell.account_id
                    or bid.intent.quantity.dimension != ask.intent.quantity.dimension
                    or bid.remaining.value == 0
                    or ask.remaining.value == 0
                    or bid.intent.limit.value < ask.intent.limit.value
                ):
                    continue
                if (
                    current_buy.instance_id == current_sell.instance_id
                    or current_buy.context is None
                    or current_sell.context is None
                    or not current_buy.context.compatible_with(current_sell.context)
                    or current_buy.quote is None
                    or current_sell.quote is None
                    or current_buy.quote.price != current_sell.quote.price
                    or bid.intent.time_in_force == "post-only"
                    or ask.intent.time_in_force == "post-only"
                    or not ask.intent.limit.value
                    <= current_buy.quote.price.value
                    <= bid.intent.limit.value
                ):
                    raise ValueError("incompatible_crossing_scope")
                quantity = min(bid.remaining.value, ask.remaining.value)
                for child, signed in (
                    (current_sell, quantity.copy_negate()),
                    (current_buy, quantity),
                ):
                    order = child.order
                    quote = child.quote
                    if quote is None:
                        raise ValueError("missing_crossing_quote")
                    fill_id = hashlib.sha256(
                        self._codec.encode_json(
                            (
                                "internal-cross-v1",
                                batch.identity,
                                bid.identity,
                                ask.identity,
                                order.identity,
                            )
                        )
                    ).hexdigest()
                    fill = Fill(
                        identity=fill_id,
                        decision_at=order.decision_at,
                        filled_at=batch.at,
                        quantity=Quantity(value=signed, dimension=order.intent.quantity.dimension),
                        reference=quote.price,
                        effective=quote.price,
                        fee=Money(value=Decimal(0), currency=quote.price.currency),
                    )
                    event = OrderEvent(
                        identity=f"internal:{fill_id}",
                        order_id=order.identity,
                        at=batch.at,
                        kind="fill",
                        fill=fill,
                    )
                    result = self._event(tx, child, event)
                    saved_events: tuple[_SavedEvent, ...] = (
                        *tx.state.events,
                        _SavedEvent(event=event, result=result),
                    )
                    tx.state = replace(
                        tx.state,
                        events=saved_events,
                    )
                    fill_ids.append(fill_id)
        return tuple(fill_ids)

    def _net_pending(
        self, tx: _AccountTransaction, account_id: str, at: datetime
    ) -> tuple[NetOrder, ...]:
        """Group only unassigned compatible residual children into physical orders."""
        assigned = {
            allocation.child_order_id
            for parent in tx.state.net_orders
            if not parent.order.is_terminal
            for allocation in parent.allocations
        }
        pending = [
            child
            for child in tx.state.orders
            if child.account_id == account_id
            and child.context is not None
            and not child.order.is_terminal
            and child.order.remaining.value > 0
            and child.order.identity not in assigned
            and child.instance_id not in tx.state.stopped_instances
        ]
        parents: list[NetOrder] = []
        residuals: list[PortfolioResidual] = []
        while pending:
            first = pending.pop(0)
            if first.context is None or first.quote is None:
                raise ValueError("portfolio child lacks context")
            group = [first]
            group_notional = Fraction(first.order.intent.limit.value) * Fraction(
                first.order.remaining.value
            )
            for candidate in tuple(pending):
                next_notional = Fraction(candidate.order.intent.limit.value) * Fraction(
                    candidate.order.remaining.value
                )
                if (
                    candidate.context is not None
                    and candidate.quote == first.quote
                    and first.context.compatible_with(candidate.context)
                    and candidate.order.intent.side == first.order.intent.side
                    and candidate.order.intent.limit == first.order.intent.limit
                    and candidate.order.intent.time_in_force == first.order.intent.time_in_force
                    and group_notional + next_notional
                    <= Fraction(self.config.budgets.max_order_notional.value)
                ):
                    group.append(candidate)
                    group_notional += next_notional
                    pending.remove(candidate)
            if at <= max(child.order.decision_at for child in group):
                raise ValueError("physical order precedes child decision")
            intent = first.order.intent
            quantity = Quantity(
                value=DecimalGrid.exact_decimal(
                    sum((Fraction(child.order.remaining.value) for child in group), Fraction(0))
                ),
                dimension=intent.quantity.dimension,
            )
            physical_intent = OrderIntent(
                side=intent.side,
                quantity=quantity,
                limit=intent.limit,
                time_in_force=intent.time_in_force,
            )
            reason = SpotOrderLifecycle(self._limits(intent.limit)).order_reason(physical_intent)
            if reason is not None:
                residuals.extend(
                    PortfolioResidual(
                        account_id=child.account_id,
                        instance_id=child.instance_id,
                        child_order_id=child.order.identity,
                        remaining=child.order.remaining,
                        reason=reason,
                    )
                    for child in group
                )
                continue
            fee = Money(
                value=DecimalGrid.exact_decimal(
                    sum(
                        (
                            Fraction((child.order.maximum_fee - child.order.paid_fee).value)
                            for child in group
                        ),
                        Fraction(0),
                    )
                ),
                currency=intent.limit.currency,
            )
            parent_id = hashlib.sha256(
                self._codec.encode_json(
                    (
                        "physical-net-v1",
                        account_id,
                        at,
                        tuple(child.order.identity for child in group),
                    )
                )
            ).hexdigest()
            if any(parent.order.identity == parent_id for parent in tx.state.net_orders):
                raise ValueError("physical order identity was reused")
            physical = OrderState(
                identity=parent_id,
                decision_identity=parent_id,
                decision_at=at,
                intent=physical_intent,
                status="intent",
                filled=Quantity(value=Decimal(0), dimension=quantity.dimension),
                paid_fee=Money(value=Decimal(0), currency=fee.currency),
                maximum_fee=fee,
            )
            parent = NetOrder(
                account_id=account_id,
                order=physical,
                allocations=tuple(
                    NetAllocation(
                        child_order_id=child.order.identity,
                        quantity=child.order.remaining,
                        filled=Quantity(
                            value=Decimal(0), dimension=child.order.remaining.dimension
                        ),
                    )
                    for child in group
                ),
                context=first.context,
            )
            net_orders: tuple[NetOrder, ...] = (*tx.state.net_orders, parent)
            tx.state = replace(tx.state, net_orders=net_orders)
            parents.append(parent)
        saved_residuals: tuple[PortfolioResidual, ...] = (
            *(item for item in tx.state.residuals if item.account_id != account_id),
            *residuals,
        )
        tx.state = replace(tx.state, residuals=saved_residuals)
        return tuple(parents)

    def _net_event(
        self, tx: _AccountTransaction, parent: NetOrder, event: OrderEvent
    ) -> tuple[
        NetOrder,
        tuple[str, ...],
        tuple[str, ...],
        tuple[NetFeeAllocation, ...],
    ]:
        """Apply one parent lifecycle fact and conservatively attributed children."""
        account = tx.account(parent.account_id)
        if event.at < self._account_time(tx, account):
            raise ValueError("physical event knowledge precedes current account state")
        if self.config.mode == "shadow" and event.fill is not None:
            raise ValueError("shadow mode cannot post modeled fills")
        physical = SpotOrderLifecycle(self._limits(parent.order.intent.limit)).transition(
            parent.order, event
        )
        allocations = parent.allocations
        child_fill_ids: list[str] = []
        fee_only_ids: list[str] = []
        fee_allocations: list[NetFeeAllocation] = []
        if event.fill is not None:
            fill = event.fill
            allocator = ProRataAllocator()
            increments = allocator.increment(
                cumulative=physical.filled.value,
                weights=tuple(item.quantity.value for item in allocations),
                prior=tuple(item.filled.value for item in allocations),
                identities=tuple(item.child_order_id for item in allocations),
                quantum=DecimalGrid.exact_decimal(
                    Fraction(Fraction(fill.effective.value).denominator, 10**18)
                ),
            )
            children = tuple(tx.order(item.child_order_id) for item in allocations)
            fee_capacities = tuple(
                (child.order.maximum_fee - child.order.paid_fee).value for child in children
            )
            fee_parts = allocator.split_capped(
                amount=fill.fee.value,
                capacities=fee_capacities,
                identities=tuple(item.child_order_id for item in allocations),
            )
            revised: list[NetAllocation] = []
            for item, quantity, fee_part, fee_capacity in zip(
                allocations, increments, fee_parts, fee_capacities, strict=True
            ):
                child = tx.order(item.child_order_id)
                posting_id: str | None = None
                if quantity:
                    fill_id = hashlib.sha256(
                        self._codec.encode_json(
                            ("allocated-physical-fill-v1", fill.identity, child.order.identity)
                        )
                    ).hexdigest()
                    child_fill = Fill(
                        identity=fill_id,
                        decision_at=child.order.decision_at,
                        filled_at=fill.filled_at,
                        quantity=Quantity(
                            value=quantity
                            if child.order.intent.side == "buy"
                            else quantity.copy_negate(),
                            dimension=child.order.intent.quantity.dimension,
                        ),
                        reference=fill.reference,
                        effective=fill.effective,
                        fee=Money(value=fee_part, currency=fill.fee.currency),
                    )
                    child_event = OrderEvent(
                        identity=f"allocation:{fill_id}",
                        order_id=child.order.identity,
                        at=event.at,
                        kind="fill",
                        fill=child_fill,
                    )
                    child_result = self._event(tx, child, child_event)
                    saved_events: tuple[_SavedEvent, ...] = (
                        *tx.state.events,
                        _SavedEvent(event=child_event, result=child_result),
                    )
                    tx.state = replace(
                        tx.state,
                        events=saved_events,
                    )
                    child_fill_ids.append(fill_id)
                    if fee_part:
                        posting_id = f"fee:{fill_id}"
                elif fee_part:
                    fee_id = hashlib.sha256(
                        self._codec.encode_json(
                            ("allocated-physical-fee-v1", fill.identity, child.order.identity)
                        )
                    ).hexdigest()
                    ledger = AccountLedger(tx.account(parent.account_id).ledger)
                    ledger.post(
                        AccountPosting(
                            identity=fee_id,
                            account_id=parent.account_id,
                            instance_id=child.instance_id,
                            order_id=child.order.identity,
                            kind="fee",
                            event_at=fill.filled_at,
                            known_at=event.at,
                            cash=Money(value=fee_part.copy_negate(), currency=fill.fee.currency),
                        )
                    )
                    tx.save_account(replace(tx.account(parent.account_id), ledger=ledger.state))
                    tx.save_order(
                        replace(
                            child,
                            order=replace(
                                child.order,
                                paid_fee=child.order.paid_fee
                                + Money(value=fee_part, currency=fill.fee.currency),
                            ),
                        )
                    )
                    fee_only_ids.append(fee_id)
                    posting_id = fee_id
                fee_allocations.append(
                    NetFeeAllocation(
                        child_order_id=child.order.identity,
                        amount=Money(value=fee_part, currency=fill.fee.currency),
                        posting_id=posting_id,
                        revision_id=posting_id,
                        weight=Money(value=fee_capacity, currency=fill.fee.currency),
                    )
                )
                revised.append(
                    replace(
                        item,
                        filled=item.filled
                        + Quantity(value=quantity, dimension=item.quantity.dimension),
                    )
                )
            allocations = tuple(revised)
        updated_parent = replace(parent, order=physical, allocations=allocations)
        if physical.is_terminal:
            for allocation in allocations:
                child = tx.order(allocation.child_order_id)
                if child.instance_id in tx.state.stopped_instances and not child.order.is_terminal:
                    tx.save_order(replace(child, order=replace(child.order, status="cancelled")))
        tx.save_net_order(updated_parent)
        return (
            updated_parent,
            tuple(child_fill_ids),
            tuple(fee_only_ids),
            tuple(fee_allocations),
        )

    def _physical_attribution_matches(self, tx: _AccountTransaction, account_id: str) -> bool:
        """Compare every physical fill against effective child quantity, cash and fees."""
        effective = {
            posting.identity: posting
            for posting in AccountLedger(tx.account(account_id).ledger).effective_postings()
        }
        for saved in tx.state.net_events:
            if (
                saved.event.fill is None
                or tx.net_order(saved.event.order_id).account_id != account_id
            ):
                continue
            fill = saved.event.fill
            child_postings = tuple(effective.get(identity) for identity in saved.child_fill_ids)
            if not child_postings or any(
                posting is None or posting.kind != "fill" or posting.quantity is None
                for posting in child_postings
            ):
                return False
            signed = sum(
                (
                    Fraction(posting.quantity.value)
                    for posting in child_postings
                    if posting is not None and posting.quantity is not None
                ),
                Fraction(0),
            )
            cash = sum(
                (Fraction(posting.cash.value) for posting in child_postings if posting is not None),
                Fraction(0),
            )
            paid = Fraction(0)
            for allocation in saved.fee_allocations:
                posting = (
                    effective.get(allocation.posting_id)
                    if allocation.posting_id is not None
                    else None
                )
                if allocation.amount.value:
                    if (
                        posting is None
                        or posting.kind != "fee"
                        or posting.order_id != allocation.child_order_id
                        or -Fraction(posting.cash.value) != Fraction(allocation.amount.value)
                    ):
                        return False
                elif posting is not None:
                    return False
                paid += Fraction(allocation.amount.value)
            latest = next(
                (
                    correction
                    for correction in reversed(tx.state.net_fee_corrections)
                    if correction.physical_fill_id == fill.identity
                ),
                None,
            )
            expected_fee = latest.corrected_fee if latest is not None else fill.fee
            if (
                signed != Fraction(fill.quantity.value)
                or cash != -Fraction(fill.effective.value) * Fraction(fill.quantity.value)
                or paid != Fraction(expected_fee.value)
            ):
                return False
        for parent in tx.state.net_orders:
            if parent.account_id != account_id:
                continue
            attributed = sum(
                (
                    Fraction(allocation.amount.value)
                    for saved in tx.state.net_events
                    if saved.event.fill is not None
                    and saved.event.order_id == parent.order.identity
                    for allocation in saved.fee_allocations
                ),
                Fraction(0),
            )
            if attributed != Fraction(parent.order.paid_fee.value):
                return False
        return True

    def _event(self, tx: _AccountTransaction, tagged: TaggedOrder, event: OrderEvent) -> OrderState:
        """Share lifecycle semantics and commit fill/cost effects with order state."""
        account = tx.account(tagged.account_id)
        ledger = AccountLedger(account.ledger)
        if event.at < self._account_time(tx, account):
            raise ValueError("event knowledge precedes current account state")
        if event.fill is not None:
            fill = event.fill
            posting = AccountPosting(
                identity=fill.identity,
                account_id=tagged.account_id,
                instance_id=tagged.instance_id,
                order_id=tagged.order.identity,
                kind="fill",
                event_at=fill.filled_at,
                known_at=event.at,
                cash=Money(
                    value=fill.effective.amount(fill.quantity).value.copy_negate(),
                    currency=fill.fee.currency,
                ),
                quantity=fill.quantity,
                price=fill.effective,
            )
            old = next((p for p in ledger.state.postings if p.identity == fill.identity), None)
            if old is not None:
                if old != posting:
                    raise ValueError("fill identity reused with different economics")
                return tagged.order
        result = SpotOrderLifecycle(self._limits(tagged.order.intent.limit)).transition(
            tagged.order, event
        )
        if event.fill is not None:
            ledger.post(posting)
            if event.fill.fee.value:
                ledger.post(
                    AccountPosting(
                        identity=f"fee:{event.fill.identity}",
                        account_id=tagged.account_id,
                        instance_id=tagged.instance_id,
                        order_id=tagged.order.identity,
                        kind="fee",
                        event_at=event.fill.filled_at,
                        known_at=event.at,
                        cash=Money(
                            value=event.fill.fee.value.copy_negate(),
                            currency=event.fill.fee.currency,
                        ),
                    )
                )
            tx.save_account(replace(account, ledger=ledger.state))
        tx.save_order(replace(tagged, order=result))
        return result

    def _posted_order(self, order: OrderState, ledger: AccountLedger) -> OrderState:
        """Reconcile cumulative order economics after an append-only posting/correction."""
        filled = Quantity(value=Decimal(0), dimension=order.filled.dimension)
        fees = Money(value=Decimal(0), currency=order.paid_fee.currency)
        for posting in ledger.effective_postings():
            if posting.order_id != order.identity:
                continue
            if posting.kind == "fill":
                quantity, price = posting.quantity, posting.price
                if quantity is None or price is None:
                    raise ValueError("fill economics are missing")
                if (
                    quantity.dimension != order.filled.dimension
                    or (quantity.value < 0) != (order.intent.side == "sell")
                    or price.currency != order.intent.limit.currency
                    or (
                        price.value > order.intent.limit.value
                        if order.intent.side == "buy"
                        else price.value < order.intent.limit.value
                    )
                ):
                    raise ValueError("posted fill differs from reserved order")
                filled += Quantity(value=quantity.value.copy_abs(), dimension=quantity.dimension)
            elif posting.kind == "fee":
                if posting.cash.currency != fees.currency:
                    raise ValueError("order fee currency differs")
                fees -= posting.cash
        if filled.value > order.intent.quantity.value or fees.value > order.maximum_fee.value:
            raise ValueError("posted order exceeds quantity or fee reservation")
        status = "filled" if filled == order.intent.quantity else "unknown"
        return replace(order, filled=filled, paid_fee=fees, status=status)

    def _quote(self, tx: _AccountTransaction, quote: AccountQuote) -> None:
        """Keep per-instrument valuation time monotonic and reject conflicting clocks."""
        self._limits(quote.price)
        prior = next((q for q in tx.state.quotes if q.price.per == quote.price.per), None)
        if prior is not None and (quote.at < prior.at or (quote.at == prior.at and quote != prior)):
            raise ValueError("valuation clock regressed or changed")
        quotes: tuple[AccountQuote, ...] = (
            *(q for q in tx.state.quotes if q.price.per != quote.price.per),
            quote,
        )
        tx.state = replace(tx.state, quotes=quotes)

    def _limits(self, price: Price) -> SpotLimits:
        """Resolve supported instrument mechanics without implicit asset conversion."""
        for limits in self.config.instruments:
            if price.per == limits.lot.dimension and price.currency == limits.tick.currency:
                return limits
        raise ValueError("unknown instrument or valuation currency")

    def _initial(self) -> _FirmState:
        """Create explicit initial funding postings; require reconciliation before admission."""
        accounts: list[AccountView] = []
        for opening in self.config.accounts:
            ledger = AccountLedger(
                AccountState(
                    account_id=opening.account_id,
                    currencies=tuple(m.currency for m in opening.cash),
                )
            )
            for money in opening.cash:
                if money.value:
                    ledger.post(
                        AccountPosting(
                            identity=f"opening:{money.currency.code}",
                            account_id=opening.account_id,
                            kind="transfer",
                            event_at=self.config.opening_at,
                            known_at=self.config.opening_at,
                            cash=money,
                        )
                    )
            accounts.append(AccountView(ledger=ledger.state))
        return _FirmState(accounts=tuple(accounts))

    def _connect(self) -> sqlite3.Connection:
        """Open a durable bounded SQLite connection shared by all firm clients."""
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _read(self) -> _FirmState:
        """Read one atomic firm snapshot."""
        with closing(self._connect()) as connection:
            return self._load(connection)

    def _load(self, connection: sqlite3.Connection) -> _FirmState:
        """Decode the complete typed firm state, rejecting malformed storage."""
        row = cast(
            tuple[object, ...] | None,
            connection.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
        )
        if row is None or type(row[0]) is not bytes:
            raise ValueError("firm account state is missing or malformed")
        return self._codec.decode_json(row[0], _FirmState)

    @contextmanager
    def _write(self) -> Iterator[_AccountTransaction]:
        """Serialize read/check/write so concurrent clients cannot over-admit capacity."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                tx = _AccountTransaction(self._load(connection))
                yield tx
                connection.execute(
                    "UPDATE firm SET payload=? WHERE id=1", (self._codec.encode_json(tx.state),)
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
