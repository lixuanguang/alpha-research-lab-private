"""Commit independent firm admission and exact account reconciliation atomically."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountSnapshot, AccountState, Fill
from configuration import AccountConfiguration
from execution.account_admission import AccountAdmission
from execution.account_allocation import PhysicalAllocation
from execution.account_operations import AccountOperations
from execution.account_portfolio import PortfolioCoordinator
from execution.account_records import AccountControl as AccountControl
from execution.account_records import AccountControlKind as AccountControlKind
from execution.account_records import AccountControlResult as AccountControlResult
from execution.account_records import AccountDecision as AccountDecision
from execution.account_records import AccountObservation as AccountObservation
from execution.account_records import AccountPhase as AccountPhase
from execution.account_records import AccountQuote as AccountQuote
from execution.account_records import AccountView as AccountView
from execution.account_records import NativeFeeAllocation as NativeFeeAllocation
from execution.account_records import NativeFill as NativeFill
from execution.account_records import NetAllocation as NetAllocation
from execution.account_records import NetFeeAllocation as NetFeeAllocation
from execution.account_records import NetFeeCorrection as NetFeeCorrection
from execution.account_records import NetOrder as NetOrder
from execution.account_records import PhysicalAccountObservation as PhysicalAccountObservation
from execution.account_records import PortfolioBatch as PortfolioBatch
from execution.account_records import PortfolioCommit as PortfolioCommit
from execution.account_records import PortfolioDecision as PortfolioDecision
from execution.account_records import PortfolioResidual as PortfolioResidual
from execution.account_records import TaggedOrder as TaggedOrder
from execution.account_state import (
    AccountStateStore,
    _AccountTransaction,
    _SavedDecision,
    _SavedNativeFill,
)
from execution.records import OrderEvent, OrderState, StepCommit
from financial_units import DecimalGrid, Money, Quantity
from portfolio import ProRataAllocator
from serialization import DomainCodec


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
        self._store = AccountStateStore(path, config, self._codec)
        self._admission = AccountAdmission(config, self._codec)
        self._operations = AccountOperations(self._admission)
        self._allocation = PhysicalAllocation(config, self._codec, self._admission)
        self._portfolio = PortfolioCoordinator(config, self._codec, self._admission)

    def accounts(self) -> tuple[AccountView, ...]:
        """Read account state, reconciliation cutoff and independent block reasons."""
        return self._store.read().accounts

    @staticmethod
    def verify(
        path: Path,
        config: AccountConfiguration,
        *,
        storage: Literal["wal", "snapshot"] = "wal",
    ) -> tuple[AccountView, ...]:
        """Inspect a live WAL journal or an immutable standalone backup snapshot."""
        return AccountStateStore.verify(path, config, DomainCodec(), storage=storage)

    def controls(self, account_id: str | None = None) -> tuple[AccountControlResult, ...]:
        """Read original durable control outcomes in append order."""
        state = self._store.read()
        if account_id is not None and account_id not in {
            account.ledger.account_id for account in state.accounts
        }:
            raise ValueError("unknown account")
        return tuple(
            saved
            for saved in state.account_controls
            if account_id is None or saved.request.account_id == account_id
        )

    def orders(self) -> tuple[TaggedOrder, ...]:
        """Read tagged orders, including terminal and uncertain commitments."""
        return self._store.read().orders

    def net_orders(self) -> tuple[NetOrder, ...]:
        """Read physical portfolio orders with exact child allocation lineage."""
        return self._store.read().net_orders

    def portfolio_batch(self, identity: str) -> PortfolioBatch | None:
        """Read an original immutable batch for exact older transport retry checks."""
        for saved in self._store.read().portfolio_batches:
            if saved.batch.identity == identity:
                return saved.batch
        return None

    def portfolio_residuals(self, account_id: str) -> tuple[PortfolioResidual, ...]:
        """Read retained unroutable quantities and their physical grid reasons."""
        state = self._store.read()
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
        return self._store.read().stopped_instances

    def failed_net_events(self) -> tuple[OrderEvent, ...]:
        """Read rejected physical facts retained for diagnosis."""
        return self._store.read().failed_net_events

    def physical_open_orders(self, account_id: str) -> tuple[OrderState, ...]:
        """Expose only outstanding physical orders for an independent observation."""
        state = self._store.read()
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
        """Expose retained contradictory order facts for correction and diagnosis."""
        return self._store.read().failed_events

    def failed_postings(self) -> tuple[AccountPosting, ...]:
        """Expose retained unpostable account facts without claiming application."""
        return self._store.read().failed_postings

    def checkpoint(self, instance_id: str) -> bytes | None:
        """Restore the last admitted or rejected continuation for one instance."""
        for saved in reversed(self._store.read().decisions):
            if saved.request.instance_id == instance_id:
                return saved.request.checkpoint
        return None

    def block(self, account_id: str, reason: str) -> None:
        """Persist an independent stop; reconciliation cannot clear it."""
        if type(reason) is not str or not reason.strip():
            raise ValueError("block requires a visible reason")
        with self._store.write() as transaction:
            transaction.save_account(
                replace(transaction.account(account_id), operator_block=reason)
            )

    def invalidate_venue(self, account_id: str, reason: str) -> None:
        """Fence exposure after an unavailable or uncertain private venue read.

        A later complete physical observation can clear this recoverable fault.
        Operator stops remain independent and cannot be cleared by observation.
        """
        if self.config.mode != "venue_test":
            raise ValueError("venue invalidation requires venue_test mode")
        if type(reason) is not str or not reason.strip():
            raise ValueError("venue invalidation requires a visible reason")
        with self._store.write() as transaction:
            account = transaction.account(account_id)
            transaction.save_account(
                replace(account, fault=f"venue_unavailable:{reason}", reconciled_at=None)
            )

    def control(self, request: AccountControl) -> AccountControlResult:
        """Apply an identified local startup, stop, fault, restart or cancel."""
        request.__post_init__()
        with self._store.write() as transaction:
            return self._operations.apply(transaction, request)

    def observe(self, quote: AccountQuote) -> None:
        """Persist a monotonic actual valuation fact without admitting an order."""
        quote.__post_init__()
        with self._store.write() as transaction:
            self._admission.observe_quote(transaction, quote)

    def admit(self, request: AccountDecision) -> StepCommit:
        """Atomically reserve child legs and checkpoint the resulting decision."""
        request.__post_init__()
        with self._store.write() as transaction:
            for saved in transaction.state.decisions:
                if (saved.request.instance_id, saved.request.decision.identity) == (
                    request.instance_id,
                    request.decision.identity,
                ):
                    if saved.request != request:
                        raise ValueError("decision identity reused with different content")
                    return saved.result
            before = transaction.state
            try:
                result = self._admission.admit(transaction, request)
            except ValueError as error:
                result = StepCommit(status="rejected", reason=str(error), orders=())
            if result.status == "rejected":
                transaction.state = before
            decisions: tuple[_SavedDecision, ...] = (
                *transaction.state.decisions,
                _SavedDecision(request=request, result=result),
            )
            transaction.state = replace(transaction.state, decisions=decisions)
            return result

    def coordinate(self, batch: PortfolioBatch) -> PortfolioCommit:
        """Admit gross risk, cross by policy, and create physical orders atomically."""
        batch.__post_init__()
        with self._store.write() as transaction:
            return self._portfolio.coordinate(transaction, batch)

    def apply_net_event(self, event: OrderEvent) -> NetOrder:
        """Apply one physical fact and all attributable strategy effects atomically."""
        if self.config.mode == "venue_test" and event.fill is not None:
            raise ValueError("venue fills require apply_native_fill")
        event.__post_init__()
        with self._store.write() as transaction:
            result, failure = self._allocation.apply_event(transaction, event)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        if result is None:
            raise AssertionError("physical event completed without a result")
        return result

    def correct_net_fee(self, correction: NetFeeCorrection) -> NetOrder:
        """Revise one physical fill fee and its child postings in one transaction."""
        correction.__post_init__()
        with self._store.write() as transaction:
            return self._allocation.correct_fee(transaction, correction)

    def stop_instance(self, instance_id: str, at: datetime) -> tuple[NetOrder, ...]:
        """Fence one strategy and request cancellation of shared physical parents."""
        self._admission.require_instance(instance_id)
        self._admission.require_utc(at, field_name="strategy stop")
        with self._store.write() as transaction:
            return self._portfolio.stop_instance(transaction, instance_id, at)

    def restart_instance(self, instance_id: str, at: datetime) -> None:
        """Re-enable a stopped instance after physical release and reconciliation."""
        self._admission.require_instance(instance_id)
        self._admission.require_utc(at, field_name="strategy restart")
        with self._store.write() as transaction:
            self._portfolio.restart_instance(transaction, instance_id, at)

    def reissue_pending(self, account_id: str, at: datetime) -> tuple[NetOrder, ...]:
        """Create physical orders for unaffected residuals after observation."""
        self._admission.require_utc(at, field_name="physical reissue")
        with self._store.write() as transaction:
            return self._portfolio.reissue_pending(transaction, account_id, at)

    def apply_event(self, event: OrderEvent) -> OrderState:
        """Post normalized order and fill facts; durably block contradictions."""
        if self.config.mode == "venue_test" and event.fill is not None:
            raise ValueError("venue fills require apply_native_fill")
        event.__post_init__()
        with self._store.write() as transaction:
            result, failure = self._admission.apply_event(transaction, event)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        if result is None:
            raise AssertionError("order event completed without a result")
        return result

    def post(self, posting: AccountPosting) -> AccountSnapshot:
        """Apply identified transfers, costs, or explicit economic corrections."""
        posting.__post_init__()
        if self.config.mode == "shadow" and posting.kind in ("fill", "correction"):
            raise ValueError("shadow mode cannot post modeled fill or correction")
        with self._store.write() as transaction:
            snapshot, failure = self._admission.post(transaction, posting)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        return snapshot

    def reconcile(self, observation: AccountObservation) -> bool:
        """Compare all account and open-order facts while preserving operator stops."""
        observation.__post_init__()
        with self._store.write() as transaction:
            return self._admission.reconcile(transaction, observation, self._allocation)

    def apply_native_fill(self, request: NativeFill) -> OrderState | NetOrder:
        """Commit one venue trade, all attributed costs and the lifecycle atomically.

        A retry of identical source bytes is harmless. Conflicting or unpostable
        source facts retain a durable account fault and cannot be reconciled away.
        """
        request.__post_init__()
        if self.config.mode != "venue_test":
            raise ValueError("native fill requires venue_test mode")
        with self._store.write() as transaction:
            prior = next(
                (
                    item
                    for item in transaction.state.native_fills
                    if item.request.identity == request.identity
                ),
                None,
            )
            if prior is not None:
                if prior.request != request:
                    self._record_failed_native(transaction, request, prior.request.order_id)
                    failure = "native fill identity reused with different economics"
                else:
                    return self._physical_order(transaction, request.order_id)
            else:
                failure = None
            if failure is None:
                before = transaction.state
                try:
                    result, allocations = self._apply_native(transaction, request)
                except ValueError as error:
                    transaction.state = before
                    self._record_failed_native(transaction, request)
                    failure = str(error)
                else:
                    native_fills: tuple[_SavedNativeFill, ...] = (
                        *transaction.state.native_fills,
                        _SavedNativeFill(request=request, allocations=allocations),
                    )
                    transaction.state = replace(
                        transaction.state,
                        native_fills=native_fills,
                    )
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        return result

    def _apply_native(
        self, transaction: _AccountTransaction, request: NativeFill
    ) -> tuple[OrderState | NetOrder, tuple[NativeFeeAllocation, ...]]:
        """Stage existing physical lifecycle and separate native asset economics."""
        for prior in transaction.state.native_fills:
            other = prior.request
            if (
                other.quantity.dimension == request.quantity.dimension
                and other.base_currency != request.base_currency
            ):
                raise ValueError("native instrument base currency changed")
        physical = self._physical_order(transaction, request.order_id)
        order = physical.order if isinstance(physical, NetOrder) else physical
        event_fill = Fill(
            identity=request.identity,
            decision_at=order.decision_at,
            filled_at=request.filled_at,
            quantity=request.quantity,
            reference=request.price,
            effective=request.price,
            fee=(
                request.fee
                if request.fee.currency == request.price.currency and request.fee.value > 0
                else Money(value=Decimal(0), currency=request.price.currency)
            ),
        )
        event = OrderEvent(
            identity=f"native:{request.identity}",
            order_id=request.order_id,
            at=request.at,
            kind="fill",
            fill=event_fill,
        )
        if isinstance(physical, NetOrder):
            net_result, failure = self._allocation.apply_event(transaction, event)
            if failure is not None or net_result is None:
                raise ValueError(failure or "native physical fill failed")
            final: OrderState | NetOrder = net_result
        else:
            direct_result, failure = self._admission.apply_event(transaction, event)
            if failure is not None or direct_result is None:
                raise ValueError(failure or "native direct fill failed")
            final = direct_result
        allocations = self._post_native_cost(transaction, request, isinstance(physical, NetOrder))
        return final, allocations

    def _post_native_cost(
        self, transaction: _AccountTransaction, request: NativeFill, is_net: bool
    ) -> tuple[NativeFeeAllocation, ...]:
        """Post base inventory fees or rebates and quote rebates to owned children."""
        if request.fee.value == 0 or (
            request.fee.currency == request.price.currency and request.fee.value > 0
        ):
            return ()
        parent = transaction.net_order(request.order_id) if is_net else None
        account_id = (
            parent.account_id
            if parent is not None
            else transaction.order(request.order_id).account_id
        )
        account = transaction.account(account_id)
        ledger = AccountLedger(account.ledger)
        if (
            request.fee.currency == request.base_currency
            and request.base_currency not in ledger.state.currencies
        ):
            ledger = AccountLedger(
                AccountState(
                    account_id=account_id,
                    currencies=(*ledger.state.currencies, request.base_currency),
                    postings=ledger.state.postings,
                )
            )
        if parent is not None:
            source = next(
                item
                for item in reversed(transaction.state.net_events)
                if item.event.fill is not None and item.event.fill.identity == request.identity
            )
            effective = {item.identity: item for item in ledger.effective_postings()}
            child_list: list[tuple[str, Fraction]] = []
            for identity in source.child_fill_ids:
                posting = effective[identity]
                if posting.order_id is None or posting.quantity is None:
                    raise ValueError("native physical fill lacks child attribution")
                child_list.append((posting.order_id, abs(Fraction(posting.quantity.value))))
            children = tuple(child_list)
        else:
            children = ((request.order_id, abs(Fraction(request.quantity.value))),)
        if not children:
            raise ValueError("native fee lacks attributed fill quantity")
        child_ids = tuple(child_id for child_id, _ in children)
        amount = request.fee.value.copy_abs()
        if request.fee.value > 0:
            if request.fee.currency != request.base_currency:
                raise ValueError("quote fee must use ordinary fill cost path")
            capacities: list[Decimal] = []
            for child_id in child_ids:
                child = transaction.order(child_id)
                prior_native_cost = sum(
                    (
                        Fraction(allocation.amount.value) * Fraction(saved.request.price.value)
                        for saved in transaction.state.native_fills
                        if saved.request.fee.currency == saved.request.base_currency
                        for allocation in saved.allocations
                        if allocation.child_order_id == child_id and allocation.amount.value > 0
                    ),
                    Fraction(0),
                )
                reserve = (
                    Fraction((child.order.maximum_fee - child.order.paid_fee).value)
                    - prior_native_cost
                )
                if reserve < 0:
                    raise ValueError("native fees exceed child reservation")
                atoms = reserve * 10**18 // Fraction(request.price.value)
                capacities.append(DecimalGrid.exact_decimal(Fraction(atoms, 10**18)))
            portions = ProRataAllocator().split_capped(
                amount=amount,
                capacities=tuple(capacities),
                identities=child_ids,
            )
        else:
            portions = self._split_native_rebate(amount, children)
        allocations: list[NativeFeeAllocation] = []
        for child_id, portion in zip(child_ids, portions, strict=True):
            if not portion:
                continue
            child = transaction.order(child_id)
            signed = portion if request.fee.value > 0 else portion.copy_negate()
            posting_id = hashlib.sha256(
                self._codec.encode_json(("native-fee-v1", request.identity, child_id))
            ).hexdigest()
            cash_value = signed.copy_negate()
            ledger.post(
                AccountPosting(
                    identity=posting_id,
                    account_id=account_id,
                    instance_id=child.instance_id,
                    order_id=child_id,
                    kind="fee" if signed > 0 else "rebate",
                    event_at=request.filled_at,
                    known_at=request.at,
                    cash=Money(value=cash_value, currency=request.fee.currency),
                    asset_change=(
                        Quantity(value=cash_value, dimension=request.quantity.dimension)
                        if request.fee.currency == request.base_currency
                        else None
                    ),
                )
            )
            allocations.append(
                NativeFeeAllocation(
                    child_order_id=child_id,
                    amount=Money(value=signed, currency=request.fee.currency),
                    posting_id=posting_id,
                )
            )
        transaction.save_account(replace(account, ledger=ledger.state))
        return tuple(allocations)

    @staticmethod
    def _split_native_rebate(
        amount: Decimal, children: tuple[tuple[str, Fraction], ...]
    ) -> tuple[Decimal, ...]:
        """Allocate signed source rebate atoms by actual child fill quantity."""
        total_atoms = int(Fraction(amount) * 10**18)
        weight = sum((item[1] for item in children), Fraction(0))
        quotas = tuple(Fraction(total_atoms) * item[1] / weight for item in children)
        atoms = [quota.numerator // quota.denominator for quota in quotas]
        remaining = total_atoms - sum(atoms)
        priorities = sorted(
            (-(quotas[index] - atoms[index]), children[index][0], index)
            for index in range(len(children))
        )
        for _, _, index in priorities[:remaining]:
            atoms[index] += 1
        return tuple(DecimalGrid.exact_decimal(Fraction(value, 10**18)) for value in atoms)

    @staticmethod
    def _physical_order(transaction: _AccountTransaction, order_id: str) -> OrderState | NetOrder:
        """Resolve only a physical direct order or portfolio parent."""
        for parent in transaction.state.net_orders:
            if parent.order.identity == order_id:
                return parent
        for tagged in transaction.state.orders:
            if tagged.order.identity == order_id and tagged.context is None:
                return tagged.order
        raise ValueError("unknown physical order")

    def _record_failed_native(
        self,
        transaction: _AccountTransaction,
        request: NativeFill,
        prior_order_id: str | None = None,
    ) -> None:
        """Retain contradictory external trade bytes and fence any known owner."""
        failed = transaction.state.failed_native_fills
        if request not in failed:
            failed = (*failed, request)
        for order_id in (request.order_id, prior_order_id):
            if order_id is None:
                continue
            try:
                physical = self._physical_order(transaction, order_id)
            except ValueError:
                continue
            account_id = (
                physical.account_id
                if isinstance(physical, NetOrder)
                else transaction.order(order_id).account_id
            )
            account = transaction.account(account_id)
            transaction.save_account(replace(account, fault="native_fill_break"))
        transaction.state = replace(transaction.state, failed_native_fills=failed)

    def reconcile_venue(self, observation: PhysicalAccountObservation) -> bool:
        """Compare actual venue wallet totals and physical open orders."""
        observation.__post_init__()
        if self.config.mode != "venue_test":
            raise ValueError("physical reconciliation requires venue_test mode")
        with self._store.write() as transaction:
            return self._admission.reconcile_physical(transaction, observation, self._allocation)

    @contextmanager
    def execution_guard(
        self,
        account_id: str,
        order_id: str,
        at: datetime,
        *,
        cancel: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> Iterator[OrderState]:
        """Hold the journal write fence across one bounded physical dispatch.

        The caller commits uncertainty before entering and records the response
        after leaving. This fence prevents an account or strategy stop from racing
        the final send check; a cancellation remains available while stopped.
        """
        if self.config.mode != "venue_test":
            raise ValueError("execution guard requires venue_test mode")
        self._admission.require_utc(at, field_name="physical dispatch")
        with self._store.write() as transaction:
            if clock is not None:
                at = clock()
                self._admission.require_utc(at, field_name="physical dispatch")
            physical = self._physical_order(transaction, order_id)
            order = physical.order if isinstance(physical, NetOrder) else physical
            owner = (
                physical.account_id
                if isinstance(physical, NetOrder)
                else transaction.order(order_id).account_id
            )
            if owner != account_id or order.is_terminal:
                raise ValueError("dispatch order is not an open physical account order")
            if not cancel:
                account = transaction.account(account_id)
                if account.phase != "running" or account.fault or account.operator_block:
                    raise ValueError("account dispatch is blocked")
                if account.reconciled_at is None or at < account.reconciled_at:
                    raise ValueError("dispatch requires current reconciliation")
                if at < self._admission.account_time(transaction, account):
                    raise ValueError("dispatch precedes current account state")
                if isinstance(physical, NetOrder):
                    instance_ids = tuple(
                        transaction.order(item.child_order_id).instance_id
                        for item in physical.allocations
                    )
                else:
                    instance_ids = (transaction.order(order_id).instance_id,)
                if any(item in transaction.state.stopped_instances for item in instance_ids):
                    raise ValueError("strategy dispatch is stopped")
                if any(
                    tagged.account_id == account_id
                    and tagged.order.identity != order_id
                    and tagged.order.status == "unknown"
                    for tagged in transaction.state.orders
                ) or any(
                    parent.account_id == account_id
                    and parent.order.identity != order_id
                    and parent.order.status == "unknown"
                    for parent in transaction.state.net_orders
                ):
                    raise ValueError("another order outcome is unknown")
                quote = next(
                    (
                        item
                        for item in transaction.state.quotes
                        if item.price.per == order.intent.quantity.dimension
                    ),
                    None,
                )
                if (
                    quote is None
                    or quote.at > at
                    or at - quote.at > timedelta(microseconds=self.config.budgets.max_quote_age_us)
                ):
                    raise ValueError("dispatch quote is stale")
                reference = Fraction(quote.price.value)
                limit = Fraction(order.intent.limit.value)
                if (
                    abs(limit - reference) * 10_000
                    > reference * self.config.budgets.max_price_deviation_bps
                ):
                    raise ValueError("dispatch price deviation")
                self._admission.require_reissue_safe(transaction, account_id, at)
            yield order
