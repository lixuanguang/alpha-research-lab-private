"""Commit independent firm admission and exact account reconciliation atomically."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from pathlib import Path

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountPosting, AccountSnapshot
from configuration import AccountConfiguration
from execution.account_admission import AccountAdmission
from execution.account_allocation import PhysicalAllocation
from execution.account_portfolio import PortfolioCoordinator
from execution.account_records import AccountDecision as AccountDecision
from execution.account_records import AccountObservation as AccountObservation
from execution.account_records import AccountQuote as AccountQuote
from execution.account_records import AccountView as AccountView
from execution.account_records import NetAllocation as NetAllocation
from execution.account_records import NetFeeAllocation as NetFeeAllocation
from execution.account_records import NetFeeCorrection as NetFeeCorrection
from execution.account_records import NetOrder as NetOrder
from execution.account_records import PortfolioBatch as PortfolioBatch
from execution.account_records import PortfolioCommit as PortfolioCommit
from execution.account_records import PortfolioDecision as PortfolioDecision
from execution.account_records import PortfolioResidual as PortfolioResidual
from execution.account_records import TaggedOrder as TaggedOrder
from execution.account_state import AccountStateStore, _SavedDecision
from execution.records import OrderEvent, OrderState, StepCommit
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
        self._allocation = PhysicalAllocation(config, self._codec, self._admission)
        self._portfolio = PortfolioCoordinator(config, self._codec, self._admission)

    def accounts(self) -> tuple[AccountView, ...]:
        """Read account state, reconciliation cutoff and independent block reasons."""
        return self._store.read().accounts

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
