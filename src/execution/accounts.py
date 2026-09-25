"""Commit independent firm admission and exact account reconciliation atomically."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountSnapshot, AccountState
from configuration import AccountConfiguration
from execution.lifecycle import SpotOrderLifecycle
from execution.records import OrderDecision, OrderEvent, OrderState, StepCommit
from financial_units import Dimension, Money, Price, Quantity
from risk import BudgetEngine, BudgetRequest, ExposureCommitment, SpotLimits
from serialization import DomainCodec, WireRecord
from strategies import ExposureIntent, TargetIntent


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

    def apply_event(self, event: OrderEvent) -> OrderState:
        """Post normalized order/fill facts once; contradictions durably block risk."""
        event.__post_init__()
        failure: str | None = None
        with self._write() as tx:
            for saved in tx.state.events:
                if saved.event.identity == event.identity:
                    if saved.event != event:
                        raise ValueError("event identity reused with different content")
                    return saved.result
            tagged = tx.order(event.order_id)
            for saved in tx.state.events:
                if (
                    event.fill is not None
                    and saved.event.fill is not None
                    and saved.event.fill.identity == event.fill.identity
                ):
                    if event.order_id != saved.event.order_id or event.fill != saved.event.fill:
                        raise ValueError("fill identity reused with different economics")
                    return tagged.order
            if self.config.mode == "shadow" and event.fill is not None:
                raise ValueError("shadow mode cannot post modeled fills")
            account = tx.account(tagged.account_id)
            try:
                result = self._event(tx, tagged, event)
            except ValueError as error:
                failure = str(error)
                tx.save_account(replace(account, fault="order_event_break"))
                failed_events: tuple[OrderEvent, ...] = (*tx.state.failed_events, event)
                tx.state = replace(tx.state, failed_events=failed_events)
                result = tagged.order
            else:
                events: tuple[_SavedEvent, ...] = (
                    *tx.state.events,
                    _SavedEvent(event=event, result=result),
                )
                tx.state = replace(tx.state, events=events)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
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
                and not tagged.order.is_terminal
            )
            latest = max(latest, *(o.decision_at for o in orders)) if orders else latest
            matched = (
                observation.at >= latest
                and (account.reconciled_at is None or observation.at >= account.reconciled_at)
                and observation.snapshot == ledger.snapshot()
                and {o.identity: o for o in observation.open_orders}
                == {o.identity: o for o in orders}
                and not any(o.status == "unknown" for o in orders)
                and not any(
                    p.account_id == account.ledger.account_id
                    and p.identity
                    not in tuple(applied.identity for applied in account.ledger.postings)
                    for p in tx.state.failed_postings
                )
                and not any(
                    failed.fill is not None
                    and tx.order(failed.order_id).account_id == account.ledger.account_id
                    and failed.fill.identity
                    not in tuple(p.identity for p in account.ledger.postings)
                    for failed in tx.state.failed_events
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
            if tx.order(event.order_id).account_id == account_id
        )
        return max(clocks)

    def _admit(self, tx: _AccountTransaction, request: AccountDecision) -> StepCommit:
        """Evaluate a decision against authoritative holdings and firm commitments."""
        account = tx.account(request.account_id)
        if account.operator_block or account.fault:
            raise ValueError(account.operator_block or account.fault or "account_blocked")
        if account.reconciled_at is None:
            raise ValueError("account_not_reconciled")
        if request.decision.at < max(self._account_time(tx, item) for item in tx.state.accounts):
            raise ValueError("decision_precedes_account_state")
        if any(
            t.account_id == request.account_id and t.order.status == "unknown"
            for t in tx.state.orders
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
        for owner in self.config.budgets.instances:
            account = tx.account(owner.account_id)
            ledger = AccountLedger(account.ledger)
            held = Money(value=Decimal(0), currency=currency)
            reserved = held
            positions = ledger.snapshot(instance_id=owner.instance_id).positions
            orders = tuple(
                t.order
                for t in tx.state.orders
                if t.instance_id == owner.instance_id and not t.order.is_terminal
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
                if order.intent.side == "buy":
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
        for tagged in tx.state.orders:
            order = tagged.order
            if tagged.account_id != account_id or order.is_terminal:
                continue
            currency = order.maximum_fee.currency
            cash[currency] -= order.maximum_fee - order.paid_fee
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
