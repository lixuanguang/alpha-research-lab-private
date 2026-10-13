"""Commit independent firm admission and exact account reconciliation atomically."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal, NamedTuple

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountSnapshot, AccountState, Fill
from configuration import (
    AccountConfiguration,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
)
from execution.account_admission import AccountAdmission
from execution.account_allocation import PhysicalAllocation
from execution.account_commands import AccountExecutionRequest, AccountExecutionResult
from execution.account_operations import AccountOperations
from execution.account_paper import AccountPaperMatching
from execution.account_portfolio import PortfolioCoordinator
from execution.account_records import AccountControl as AccountControl
from execution.account_records import AccountControlKind as AccountControlKind
from execution.account_records import AccountControlResult as AccountControlResult
from execution.account_records import AccountDecision as AccountDecision
from execution.account_records import AccountObservation as AccountObservation
from execution.account_records import AccountPaperCost as AccountPaperCost
from execution.account_records import AccountPaperFill as AccountPaperFill
from execution.account_records import AccountPaperTrace as AccountPaperTrace
from execution.account_records import AccountPhase as AccountPhase
from execution.account_records import AccountQuote as AccountQuote
from execution.account_records import AccountStatus as AccountStatus
from execution.account_records import AccountView as AccountView
from execution.account_records import DecisionOutcome as DecisionOutcome
from execution.account_records import HistoryDigest as HistoryDigest
from execution.account_records import NativeFeeAllocation as NativeFeeAllocation
from execution.account_records import NativeFill as NativeFill
from execution.account_records import NetAllocation as NetAllocation
from execution.account_records import NetFeeAllocation as NetFeeAllocation
from execution.account_records import NetFeeCorrection as NetFeeCorrection
from execution.account_records import NetOrder as NetOrder
from execution.account_records import PaperMarketOutcome as PaperMarketOutcome
from execution.account_records import PaperTracePage as PaperTracePage
from execution.account_records import PhysicalAccountObservation as PhysicalAccountObservation
from execution.account_records import PortfolioBatch as PortfolioBatch
from execution.account_records import PortfolioCommit as PortfolioCommit
from execution.account_records import PortfolioDecision as PortfolioDecision
from execution.account_records import PortfolioResidual as PortfolioResidual
from execution.account_records import TaggedOrder as TaggedOrder
from execution.account_reduction import (
    AccountReduction,
    PaperReductionRequest,
    PaperReductionResult,
)
from execution.account_replacement import PaperReplacements
from execution.account_state import (
    AccountStateStore,
    AccountTransaction,
    DispatchLease,
    FirmState,
    SavedDecision,
    _AccountSnapshot,
    _SavedNativeFill,
)
from execution.paper import PaperMarket
from execution.paper_authority import PaperActivation, PaperAuthority, PaperOwner
from execution.records import OrderEvent, OrderState, StepCommit
from financial_units import DecimalGrid, Dimension, Money, Quantity
from portfolio import PortfolioContext, ProRataAllocator
from serialization import DomainCodec, DurableDirectory


class DispatchPermit(NamedTuple):
    """The order a guard admitted, and the lease its send runs under (None for a cancel).

    ``send_by`` and ``deadline`` are absolute values of the holder process's
    monotonic ``clock``, so a wall-clock step cannot move them. The send must
    start by ``send_by`` and the transport must end by ``deadline``.
    """

    order: OrderState
    lease: DispatchLease | None
    send_by: float | None
    deadline: float | None
    clock: Callable[[], float]

    def require_sendable(self) -> None:
        """Refuse to start a send whose remaining lease could not cover the transport.

        Call immediately before the send.

        Raises:
            ValueError: The send window after arming has passed.
        """
        if self.send_by is not None and self.clock() > self.send_by:
            raise ValueError("dispatch lease send window passed")


class AccountHistory:
    """Look up one stopped journal's committed batches and decisions, read-only."""

    def __init__(self, snapshot: _AccountSnapshot) -> None:
        """Bind one read-only snapshot of the journal's committed history."""
        self._snapshot = snapshot

    def batch(self, identity: str) -> PortfolioBatch | None:
        """Return the committed portfolio batch with this identity, if any."""
        saved = self._snapshot.find_batch(identity)
        return None if saved is None else saved.batch

    def decision(self, instance_id: str, decision_identity: str) -> SavedDecision | None:
        """Return the saved decision of an instance with this identity, if any."""
        return self._snapshot.find_decision(instance_id, decision_identity)

    def digests(self) -> tuple[HistoryDigest, HistoryDigest, HistoryDigest]:
        """Return the committed decision, batch and trace histories' counts and hash chains.

        Each chain extends with every committed row, so equal digests read the same
        committed history and any later commit changes at least one of them.
        """
        snapshot = self._snapshot
        return snapshot.decision_history, snapshot.batch_history, snapshot.trace_history


class AccountJournal:
    """Own shared paper/shadow admission, reservations, postings and safe recovery.

    Every writer reads and commits under the same SQLite BEGIN IMMEDIATE lock.
    No strategy can supply its own balance or release pending capacity. Unknown
    outcomes and cancel acknowledgements retain reservations. This local command
    service has no executable transport; a venue submitter fences itself.
    """

    def __init__(
        self,
        path: Path,
        config: AccountConfiguration,
        *,
        paper_owner: PaperOwner | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Create or reopen a journal pinned to exact configuration bytes."""
        config.__post_init__()
        self.path, self.config = path, config
        self.paper_owner, self._clock = paper_owner, clock
        # Dispatch leases time sends on this holder-local clock, never the wall clock.
        self._monotonic: Callable[[], float] = time.monotonic
        self._codec = DomainCodec()
        self._store = AccountStateStore(path, config, self._codec)
        self._admission = AccountAdmission(config, self._codec)
        self._allocation = PhysicalAllocation(config, self._codec, self._admission)
        self._portfolio = PortfolioCoordinator(config, self._codec, self._admission)
        self._replacements = PaperReplacements(
            config,
            self._codec,
            self._admission,
            self._allocation,
            self._portfolio,
            self._require_send,
        )
        self._operations = AccountOperations(self._admission, self._replacements.withdraw_account)
        self._paper = AccountPaperMatching(
            config,
            self._store,
            self._codec,
            self._admission,
            self._allocation,
            self._replacements,
            owner=paper_owner,
            clock=self._now,
        )

    def close(self) -> None:
        """Close the journal's SQLite connection now; a later call opens another.

        The journal otherwise keeps one connection for its life, closed when it is
        collected. Close a briefly opened journal before moving its files.
        """
        self._store.close()

    def _now(self) -> datetime:
        """Read current UTC at every economic boundary, independently of event time."""
        at = datetime.now(UTC) if self._clock is None else self._clock()
        PaperDeployment._require_utc(at, field_name="paper operation")
        return at

    def _require_send(
        self,
        transaction: AccountTransaction,
        request: AccountDecision,
        context: PortfolioContext | None,
        *,
        modelled: bool = False,
    ) -> None:
        """Check paper authority, deployment context and current input before staging orders.

        A ``modelled`` request is a replacement arriving at its own modelled time, which a
        command may process later: its quote's age is judged at that arrival, not at the
        processing clock, so a late command neither revives nor discards it.
        """
        PaperAuthority.require_decision(transaction, request, self.paper_owner, now=self._now())
        activation = PaperAuthority.find(transaction, request.account_id)
        if (
            context is not None
            and activation is not None
            and (
                context.authority_scope != activation.deployment.submission_authority
                or context.venue
                != activation.deployment.scope_for(request.instance_id).scenario.venue
                or not any(
                    strategy.instance_id == request.instance_id
                    and strategy.model_identity == context.model_revision
                    for strategy in activation.deployment.strategies
                )
            )
        ):
            raise ValueError("paper_deployment_context_differs")
        self._require_current_input(transaction, request, modelled=modelled)

    def _require_current_input(
        self, transaction: AccountTransaction, request: AccountDecision, *, modelled: bool = False
    ) -> None:
        """Reject stale/future operational data even when historical event clocks agree."""
        if PaperAuthority.find(transaction, request.account_id) is None:
            return
        now = self._now()
        reference = request.decision.at if modelled else now
        if (
            request.decision.at > now
            or request.quote.at > now
            or reference - request.quote.at
            > timedelta(microseconds=self.config.budgets.max_quote_age_us)
        ):
            raise ValueError("paper_input_stale_or_future")

    def paper_restore_quarantined(self) -> bool:
        """Expose whether this workspace is a historical recovery copy."""
        return self._store.read().paper_restore_quarantine

    def paper_activations(self) -> tuple[PaperActivation, ...]:
        """Inspect deployment and durable authority without granting a worker lease."""
        return self._store.read().paper_activations

    def install_paper(self, deployment: PaperDeployment) -> None:
        """Pin disabled paper identity and stop exposure before any explicit grant.

        Existing economic facts are preserved. A different manifest cannot replace
        a bound account, including during code rollback; use its declared compatible
        release set and exact state/configuration bindings.
        """
        deployment.__post_init__()
        deployment.require_configuration(self.config)
        with self._store.write() as transaction:
            if transaction.state.paper_restore_quarantine:
                raise ValueError("paper_restore_requires_current_retained_journal")
            existing = PaperAuthority.find(transaction, deployment.account_id)
            if existing is not None:
                if existing.deployment != deployment:
                    raise ValueError("paper_deployment_incompatible")
                return
            for scenario in deployment.scenarios:
                self._paper.bind_transaction(transaction, deployment.account_id, scenario)
            now = self._now()
            result = self._operations.apply(
                transaction,
                AccountControl(
                    identity=f"paper-deployment:{deployment.identity}",
                    account_id=deployment.account_id,
                    kind="stop",
                    at=now,
                    reason="disabled_paper_deployment",
                ),
            )
            if result.status != "applied":
                raise ValueError(result.reason or "paper deployment stop failed")
            PaperAuthority.save(
                transaction,
                PaperActivation(
                    deployment=deployment,
                    changed_at=now,
                ),
            )

    def authorize_paper(self, authorization: PaperAuthorization) -> None:
        """Retain an explicit grant without starting a worker or clearing a stop."""
        authorization.__post_init__()
        with self._store.write() as transaction:
            activation = next(
                (
                    item
                    for item in transaction.state.paper_activations
                    if item.deployment.identity == authorization.deployment_sha256
                ),
                None,
            )
            if activation is None:
                raise ValueError("paper_deployment_absent_or_mismatched")
            if authorization.identity in activation.revoked:
                raise ValueError("paper_authorization_revoked")
            if activation.authorization == authorization:
                return
            if any(item.identity == authorization.identity for item in activation.authorizations):
                raise ValueError("paper_authorization_identity_reused")
            if (
                activation.authorization is not None
                and transaction.account(activation.deployment.account_id).phase == "running"
            ):
                raise ValueError("paper_reauthorization_requires_stop")
            if activation.authorization is not None and self._operations.has_unresolved_orders(
                transaction, activation.deployment.account_id
            ):
                raise ValueError("paper_reauthorization_requires_settled_order_outcomes")
            activation.deployment.require_authorization(authorization)
            history: tuple[PaperAuthorization, ...] = (*activation.authorizations, authorization)
            candidate = replace(
                activation,
                authorization=authorization,
                authorizations=history,
                owner=None,
                changed_at=self._now(),
            )
            candidate.require_authority(self._now())
            PaperAuthority.save(transaction, candidate)

    def revoke_paper(self, account_id: str, authorization_id: str, at: datetime) -> None:
        """Revoke new exposure durably while preserving cancellations and reductions."""
        PaperDeployment._require_utc(at, field_name="paper revocation")
        with self._stop_write(account_id=account_id) as transaction:
            activation = PaperAuthority.find(transaction, account_id)
            if (
                activation is None
                or activation.authorization is None
                or activation.authorization.identity != authorization_id
            ):
                raise ValueError("paper_authorization_absent_or_mismatched")
            if authorization_id in activation.revoked:
                return
            if at < activation.changed_at or at > self._now():
                raise ValueError("paper_revocation_clock_invalid")
            revoked: tuple[str, ...] = (*activation.revoked, authorization_id)
            PaperAuthority.save(
                transaction,
                replace(
                    activation,
                    revoked=revoked,
                    changed_at=at,
                ),
            )

    def claim_paper(
        self,
        account_id: str,
        owner_id: str,
        release_identity: str,
        control: AccountControl,
    ) -> PaperOwner:
        """Reconcile/restart and issue one durable replacement generation atomically."""
        control.__post_init__()
        with self._store.write() as transaction:
            now = self._now()
            if control.at > now or now - control.at > timedelta(
                microseconds=self.config.budgets.max_quote_age_us
            ):
                raise ValueError("paper_recovery_clock_stale_or_future")
            return PaperAuthority.claim(
                transaction,
                account_id=account_id,
                owner_id=owner_id,
                release_identity=release_identity,
                control=control,
                operations=self._operations,
                now=self._now(),
            )

    def reduce_paper(self, request: PaperReductionRequest) -> PaperReductionResult:
        """Request bounded attributable reduction; matching alone can report a fill."""
        request.__post_init__()
        with self._store.write() as transaction:
            if transaction.state.paper_restore_quarantine:
                raise ValueError("paper_restore_requires_current_retained_journal")
            now = self._now()
            if self.paper_owner is not None:
                activation = PaperAuthority.require_owner(
                    transaction,
                    request.account_id,
                    self.paper_owner,
                    at=now,
                    new_exposure=False,
                )
                if activation is not None and request.instance_id not in {
                    item.instance_id for item in activation.deployment.strategies
                }:
                    raise ValueError("paper_authorization_scope_differs")
            admission_at = (
                now if PaperAuthority.find(transaction, request.account_id) is not None else None
            )
            return AccountReduction(self._admission).apply(
                transaction, request, admission_at=admission_at
            )

    def paper_reductions(self) -> tuple[PaperReductionResult, ...]:
        """Read immutable reduction requests/results without claiming completion."""
        return self._store.read().paper_reductions

    def quarantine_paper_restore(self) -> None:
        """Keep restored managed snapshots inspectable but never automatically resumable.

        The supported recovery boundary resumes the latest retained journal. A
        historical workspace copy cannot independently establish that no later
        fills occurred, so it cannot issue an owner or accept economic mutations.
        """
        with self._store.write() as transaction:
            transaction.state = replace(transaction.state, paper_restore_quarantine=True)

    def accounts(self) -> tuple[AccountView, ...]:
        """Read account state, reconciliation cutoff and independent block reasons."""
        return self._store.read().accounts

    def account_statuses(self) -> tuple[AccountStatus, ...]:
        """Read each account's operating phase and blocks without its ledger."""
        return tuple(account.status() for account in self._store.read().accounts)

    def result_snapshot(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Project a typed response, reading state only for requested inspection fields."""
        if request.projection == "operation":
            return AccountExecutionResult(accounts=(), orders=())
        request.__post_init__()
        with self._store.snapshot() as snapshot:
            return self._project(request, snapshot)

    def _project(
        self, request: AccountExecutionRequest, snapshot: _AccountSnapshot
    ) -> AccountExecutionResult:
        """Project one inspection from a single consistent snapshot."""
        state = snapshot.state
        if request.projection == "valuation":
            if request.query_instrument is None:
                raise ValueError("valuation projection requires only an instrument query")
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                valuation=self._valuation(state, request.query_instrument),
            )
        if request.projection == "market_trace":
            if request.account_id is None or request.query_market is None:
                raise ValueError("market trace requires account and market identities")
            trace = self._paper.trace(request.account_id, request.query_market, snapshot=snapshot)
            return AccountExecutionResult(
                accounts=(), orders=(), paper_traces=() if trace is None else (trace,)
            )
        selected_accounts = (
            tuple(
                account
                for account in state.accounts
                if account.ledger.account_id == request.account_id
            )
            if request.action == "inspect" and request.account_id is not None
            else state.accounts
        )
        if not selected_accounts:
            raise ValueError("unknown account")
        selected_ids = {account.ledger.account_id for account in selected_accounts}
        if request.projection == "reconciliation":
            # One snapshot answers the facts and their clock, so they cannot tear.
            (account,) = selected_accounts
            transaction = AccountTransaction(snapshot.state, snapshot.tables)
            return AccountExecutionResult(
                accounts=selected_accounts,
                orders=tuple(
                    tagged
                    for tagged in state.orders
                    if tagged.account_id == account.ledger.account_id
                    and tagged.context is None
                    and not tagged.order.is_terminal
                ),
                net_orders=tuple(
                    parent
                    for parent in state.net_orders
                    if parent.account_id == account.ledger.account_id
                    and not parent.order.is_terminal
                ),
                known_at=self._admission.knowledge_at(transaction, account),
            )
        if request.projection == "accounts":
            return AccountExecutionResult(accounts=state.accounts, orders=())
        if request.projection == "statuses":
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                account_statuses=tuple(account.status() for account in selected_accounts),
            )
        if request.projection == "orders":
            return AccountExecutionResult(accounts=(), orders=state.orders)
        if request.projection == "net_orders":
            return AccountExecutionResult(accounts=(), orders=(), net_orders=state.net_orders)
        if request.projection == "checkpoint":
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                checkpoint=(
                    snapshot.latest_checkpoint(request.query_instance)
                    if request.query_instance is not None
                    else None
                ),
            )
        if request.projection == "saved_batch":
            # The batch's retained outcome rides in ``portfolio``, so an operator can
            # read why a coordinated decision was admitted or refused.
            saved = (
                snapshot.find_batch(request.query_batch)
                if request.query_batch is not None
                else None
            )
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                saved_batch=None if saved is None else saved.batch,
                portfolio=None if saved is None else saved.result,
            )
        if request.projection == "paper_activations":
            return AccountExecutionResult(
                accounts=(), orders=(), paper_activations=state.paper_activations
            )
        if request.projection == "quarantine":
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                paper_restore_quarantined=state.paper_restore_quarantine,
            )
        if request.projection == "trace_history":
            return AccountExecutionResult(
                accounts=(), orders=(), paper_trace_history=snapshot.trace_history
            )
        if request.projection == "traces":
            page = self._trace_page(
                snapshot,
                request.account_id,
                -1 if request.query_after is None else request.query_after,
            )
            return AccountExecutionResult(accounts=(), orders=(), paper_trace_page=page)
        if request.projection == "facts":
            report_facts = tuple(
                self._paper.report_facts(account.ledger.account_id, snapshot=snapshot)
                for account in selected_accounts
            )
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                paper_fills=tuple(fill for fills, _ in report_facts for fill in fills),
                paper_costs=tuple(cost for _, costs in report_facts for cost in costs),
            )
        if request.projection == "decisions":
            # One compact outcome per saved decision, so an operator reads every
            # refusal and dropped leg in one call.
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                decision_outcomes=tuple(
                    DecisionOutcome(
                        account_id=saved.request.account_id,
                        instance_id=saved.request.instance_id,
                        decision_identity=saved.request.decision.identity,
                        decided_at=saved.request.decision.at,
                        status=saved.result.status,
                        reason=saved.result.reason,
                        dropped=saved.result.dropped,
                    )
                    for saved in snapshot.iter_decisions()
                    if saved.request.account_id in selected_ids
                ),
            )
        active_children = {
            child.order.identity for child in state.orders if not child.order.is_terminal
        }
        if request.projection == "residuals":
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                residuals=tuple(
                    residual
                    for residual in state.residuals
                    if residual.child_order_id in active_children
                ),
            )
        if request.projection == "reductions":
            return AccountExecutionResult(
                accounts=(),
                orders=(),
                paper_reductions=tuple(
                    item
                    for item in state.paper_reductions
                    if item.request.account_id in selected_ids
                ),
            )
        report_facts = (
            tuple(
                self._paper.report_facts(account.ledger.account_id, snapshot=snapshot)
                for account in selected_accounts
            )
            if request.action == "inspect"
            else ()
        )
        return AccountExecutionResult(
            accounts=state.accounts,
            orders=state.orders,
            net_orders=state.net_orders,
            residuals=tuple(
                residual
                for residual in state.residuals
                if residual.child_order_id in active_children
            ),
            stopped_instances=state.stopped_instances,
            failed_net_events=state.failed_net_events,
            failed_events=state.failed_events,
            failed_postings=state.failed_postings,
            controls=state.account_controls,
            journal_path=str(self.path),
            paper_activations=state.paper_activations,
            paper_restore_quarantined=state.paper_restore_quarantine,
            # The trace history only grows, so inspection states its length and chain;
            # monitoring needs only each instrument's newest trace clock.
            paper_traces=(
                tuple(
                    trace
                    for account in selected_accounts
                    for trace in self._latest_traces(snapshot, account.ledger.account_id)
                )
                if request.projection == "monitoring"
                else ()
            ),
            paper_trace_history=snapshot.trace_history if request.action == "inspect" else None,
            paper_reductions=tuple(
                item for item in state.paper_reductions if item.request.account_id in selected_ids
            ),
            paper_fills=tuple(fill for fills, _ in report_facts for fill in fills),
            paper_costs=tuple(cost for _, costs in report_facts for cost in costs),
            checkpoint=(
                snapshot.latest_checkpoint(request.query_instance)
                if request.query_instance is not None
                else None
            ),
            saved_batch=self._saved_batch(snapshot, request.query_batch),
        )

    @staticmethod
    def _saved_batch(snapshot: _AccountSnapshot, identity: str | None) -> PortfolioBatch | None:
        """Resolve an optional retained batch query in one snapshot."""
        saved = snapshot.find_batch(identity) if identity is not None else None
        return saved.batch if saved is not None else None

    @staticmethod
    @contextmanager
    def read_history(path: Path, config: AccountConfiguration) -> Iterator[AccountHistory]:
        """Read a stopped journal's committed batches and decisions without writing.

        The journal is pinned to exact configuration bytes, the current layout and the
        current head format, as ``verify`` pins it.
        """
        with AccountStateStore.read_history(path, config, DomainCodec()) as snapshot:
            yield AccountHistory(snapshot)

    @staticmethod
    def arrival_identity(account_id: str, instance_id: str, decision_identity: str) -> str:
        """Name the outcome row a deferred paper decision is resolved under at arrival."""
        return PaperReplacements.arrival_identity(account_id, instance_id, decision_identity)

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
        with self._store.snapshot() as snapshot:
            return self._saved_batch(snapshot, identity)

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

    def bind_paper_scenario(self, account_id: str, scenario: PaperExecutionScenario) -> None:
        """Pin one declared venue/instrument profile before paper order admission."""
        self._paper.bind(account_id, scenario)

    def apply_public_market(
        self, account_id: str, market: PaperMarket, scenario: PaperExecutionScenario
    ) -> PaperMarketOutcome:
        """Observe one eligible book and match it in paper mode, in one fenced transaction.

        An exact retry returns the saved outcome without any write; see
        ``AccountPaperMatching.apply``.
        """
        return self._paper.apply(account_id, market, scenario)

    def advance_paper(self, at: datetime) -> None:
        """Settle modelled paper lifecycle events due strictly before ``at``, without input.

        A quiet market cannot extend a requested cancellation, a reservation or a
        replacement's release and arrival: every cancellation, release and arrival
        dated before ``at`` takes effect at its own modelled time. Nothing is matched,
        observed or decided, and with nothing due nothing is written.
        """
        self._admission.require_utc(at, field_name="paper clock")
        with self._store.write() as transaction:
            if self.paper_owner is not None:
                PaperAuthority.require_owner(
                    transaction,
                    self.paper_owner.account_id,
                    self.paper_owner,
                    at=self._now(),
                    new_exposure=False,
                )
            self._replacements.settle(transaction, at)

    def paper_trace_page(self, account_id: str | None = None, *, after: int = -1) -> PaperTracePage:
        """Read one bounded page of committed traces after a position; see ``PaperTracePage``.

        Args:
            account_id: One account's traces, or every account's when ``None``.
            after: The journal-wide position to read after; -1 reads from the start.

        Raises:
            ValueError: The account is unknown or the position is outside the history.
        """
        with self._store.snapshot() as snapshot:
            return self._trace_page(snapshot, account_id, after)

    def iter_paper_traces(
        self, account_id: str | None = None, *, after: int = -1
    ) -> Iterator[AccountPaperTrace]:
        """Yield committed traces after a position in commit order, one bounded page at a time.

        History is only appended, so pages read from successive snapshots join into
        an exact prefix of the latest history; memory stays bounded by one page.
        """
        while True:
            page = self.paper_trace_page(account_id, after=after)
            yield from page.traces
            if page.next_after is None:
                return
            after = page.next_after

    def latest_paper_traces(self, account_id: str) -> tuple[AccountPaperTrace, ...]:
        """Read the newest committed trace of each instrument bound to the account."""
        with self._store.snapshot() as snapshot:
            return self._latest_traces(snapshot, account_id)

    def paper_trace_history(self) -> HistoryDigest:
        """Read the committed trace history's count and hash chain."""
        with self._store.snapshot() as snapshot:
            return snapshot.trace_history

    def export_paper_traces(self, destination: Path, account_id: str | None = None) -> int:
        """Durably publish committed traces as one JSON array, checked against the head.

        The file holds exactly the codec's encoding of the tuple of those traces, built
        from their stored bytes in bounded memory while every row of the history is
        checked against the head's hash chain; see ``_HistoryTables.export_traces``.
        It is written beside ``destination``, synchronized and renamed into place, so
        a failure leaves no partial file.

        Returns:
            The number of traces written.

        Raises:
            ValueError: The account is unknown, the destination exists, or the stored
                history differs from the head.
        """
        if not destination.is_absolute() or destination.exists():
            raise ValueError("paper trace export requires an absent absolute destination")
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with self._store.snapshot() as snapshot:
                self._require_account(snapshot, account_id)
                with staging.open("xb") as stream:
                    written = snapshot.export_traces(account_id, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.rename(staging, destination)
        finally:
            staging.unlink(missing_ok=True)
        DurableDirectory.sync(destination.parent)
        return written

    def _trace_page(
        self, snapshot: _AccountSnapshot, account_id: str | None, after: int
    ) -> PaperTracePage:
        """Read one bounded page of committed traces from one snapshot."""
        self._require_account(snapshot, account_id)
        history = snapshot.trace_history
        if type(after) is not int or not -1 <= after < history.count:
            raise ValueError("paper trace position is outside the committed history")
        rows, more = snapshot.trace_page(
            account_id, after, PaperTracePage.maximum, PaperTracePage.maximum_bytes
        )
        return PaperTracePage(
            after=after,
            traces=tuple(trace for _, trace in rows),
            next_after=rows[-1][0] if more else None,
            history=history,
        )

    def _latest_traces(
        self, snapshot: _AccountSnapshot, account_id: str
    ) -> tuple[AccountPaperTrace, ...]:
        """Read the newest committed trace of each instrument bound to the account."""
        self._require_account(snapshot, account_id)
        latest = (
            snapshot.latest_trace(account_id, binding.scenario.instrument_id)
            for binding in snapshot.state.paper_bindings
            if binding.account_id == account_id
        )
        return tuple(trace for trace in latest if trace is not None)

    @staticmethod
    def _require_account(snapshot: _AccountSnapshot, account_id: str | None) -> None:
        """Refuse an account the journal does not hold; ``None`` names every account."""
        if account_id is not None and account_id not in {
            account.ledger.account_id for account in snapshot.state.accounts
        }:
            raise ValueError("unknown account")

    def paper_trace(self, account_id: str, market_identity: str) -> AccountPaperTrace | None:
        """Read the account's trace of one market identity, if it applied that market."""
        return self._paper.trace(account_id, market_identity)

    def valuation(self, instrument: Dimension) -> AccountQuote | None:
        """Read the latest observed valuation quote of one instrument, if any."""
        return self._valuation(self._store.read(), instrument)

    @staticmethod
    def _valuation(state: FirmState, instrument: Dimension) -> AccountQuote | None:
        """Select the one retained valuation quote of an instrument."""
        return next((quote for quote in state.quotes if quote.price.per == instrument), None)

    def paper_report_facts(
        self, account_id: str
    ) -> tuple[tuple[AccountPaperFill, ...], tuple[AccountPaperCost, ...]]:
        """Read modeled strategy fills and effective correction-aware cost links."""
        return self._paper.report_facts(account_id)

    def failed_events(self) -> tuple[OrderEvent, ...]:
        """Expose retained contradictory order facts for correction and diagnosis."""
        return self._store.read().failed_events

    def failed_postings(self) -> tuple[AccountPosting, ...]:
        """Expose retained unpostable account facts without claiming application."""
        return self._store.read().failed_postings

    def checkpoint(self, instance_id: str) -> bytes | None:
        """Restore the last admitted or rejected continuation for one instance."""
        with self._store.snapshot() as snapshot:
            return snapshot.latest_checkpoint(instance_id)

    def block(self, account_id: str, reason: str) -> None:
        """Persist an independent stop; reconciliation cannot clear it."""
        if type(reason) is not str or not reason.strip():
            raise ValueError("block requires a visible reason")
        with self._stop_write(account_id=account_id) as transaction:
            if self.paper_owner is not None:
                PaperAuthority.require_owner(
                    transaction, account_id, self.paper_owner, at=self._now(), new_exposure=False
                )
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
        with self._stop_write(account_id=account_id) as transaction:
            account = transaction.account(account_id)
            transaction.save_account(
                replace(account, fault=f"venue_unavailable:{reason}", reconciled_at=None)
            )

    def control(self, request: AccountControl) -> AccountControlResult:
        """Apply an identified local startup, stop, fault, restart or cancel."""
        request.__post_init__()
        with self._stop_write(account_id=request.account_id) as transaction:
            if self.paper_owner is not None:
                PaperAuthority.require_owner(
                    transaction,
                    request.account_id,
                    self.paper_owner,
                    at=self._now(),
                    new_exposure=False,
                )
            if (
                request.kind in ("startup", "restart")
                and PaperAuthority.find(transaction, request.account_id) is not None
            ):
                raise ValueError("managed_paper_restart_requires_owner_claim")
            # An exact retry returns its original outcome before anything settles, so a
            # retried cancel cannot withdraw intent decided after it.
            saved = self._operations.saved(transaction, request)
            if saved is not None:
                return saved
            self._replacements.settle(transaction, request.at)
            return self._operations.apply(transaction, request)

    def observe(self, quote: AccountQuote) -> None:
        """Persist a monotonic actual valuation fact without admitting an order.

        Paper lifecycle events due strictly before the quote are settled first, on the
        quotes known then, so a later observation never informs an earlier arrival.
        """
        quote.__post_init__()
        with self._store.write() as transaction:
            if self.paper_owner is not None:
                PaperAuthority.require_owner(
                    transaction,
                    self.paper_owner.account_id,
                    self.paper_owner,
                    at=self._now(),
                    new_exposure=False,
                )
            self._replacements.settle(transaction, quote.at)
            self._admission.observe_quote(transaction, quote)

    def admit(self, request: AccountDecision) -> StepCommit:
        """Atomically reserve child legs and checkpoint the resulting decision.

        An exact retry needs only the current owner, generation, retained journal and
        a non-regressed clock: it returns the saved result with no write, even after
        its inputs aged or exposure authority ended. New content takes every check.
        """
        request.__post_init__()
        with self._store.write() as transaction:
            PaperAuthority.require_owner(
                transaction,
                request.account_id,
                self.paper_owner,
                at=self._now(),
                new_exposure=False,
            )
            saved = transaction.find_decision(request.instance_id, request.decision.identity)
            if saved is not None:
                if saved.request != request:
                    raise ValueError("decision identity reused with different content")
                return saved.result
            self._replacements.settle(transaction, request.decision.at, deciding=True)
            self._require_send(transaction, request, None)
            before = transaction.state
            try:
                result = self._admission.admit(transaction, request)
                PaperAuthority.require_limits(transaction, request.account_id)
            except ValueError as error:
                result = StepCommit(status="rejected", reason=str(error), orders=())
            if result.status == "rejected":
                transaction.state = before
            transaction.append_decisions(SavedDecision(request=request, result=result))
            return result

    def coordinate(self, batch: PortfolioBatch) -> PortfolioCommit:
        """Admit gross risk, cross by policy, and create physical orders atomically.

        An exact retry of the whole batch, every decision and context included, needs
        only the current owner of each named account: it returns the saved result with
        no write, as `admit` does. New content takes every check.
        """
        batch.__post_init__()
        if self.config.mode == "shadow" and batch.crossing == "internal_at_quote":
            raise ValueError("shadow mode cannot internally match orders")
        with self._store.write() as transaction:
            now = self._now()
            for account_id in sorted({item.request.account_id for item in batch.decisions}):
                PaperAuthority.require_owner(
                    transaction, account_id, self.paper_owner, at=now, new_exposure=False
                )
            saved = transaction.find_batch(batch.identity)
            if saved is not None:
                if saved.batch != batch:
                    raise ValueError("portfolio batch identity reused with different content")
                return saved.result
            self._replacements.settle(
                transaction,
                min(item.request.decision.at for item in batch.decisions),
                deciding=True,
            )
            for item in batch.decisions:
                self._require_send(transaction, item.request, item.context)
            before = transaction.state
            result = self._portfolio.coordinate(transaction, batch)
            try:
                for account_id in {item.request.account_id for item in batch.decisions}:
                    PaperAuthority.require_limits(transaction, account_id)
            except ValueError:
                transaction.state = before
                raise
            return result

    def apply_net_event(self, event: OrderEvent) -> NetOrder:
        """Apply one physical fact and all attributable strategy effects atomically.

        Children outlive their physical parent only on ``cancelled_on_request``.
        A ``venue_test`` account refuses that kind: a venue's terminal cancellation
        does not establish that our request caused it, so it arrives as
        ``cancelled`` and ends the remaining children.
        """
        self._require_venue_evidence(event)
        event.__post_init__()
        with self._store.write() as transaction:
            if transaction.state.paper_activations:
                parent = transaction.net_order(event.order_id)
                now = self._now()
                activation = PaperAuthority.require_owner(
                    transaction,
                    parent.account_id,
                    self.paper_owner,
                    at=now,
                    new_exposure=False,
                )
                if activation is not None and not self._allow_shadow_unsent_rejection(
                    transaction, parent, event, activation, now
                ):
                    raise ValueError("managed_paper_events_require_public_matching")
            self._replacements.settle(transaction, event.at)
            result, failure = self._allocation.apply_event(transaction, event)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        if result is None:
            raise AssertionError("physical event completed without a result")
        return result

    def _allow_shadow_unsent_rejection(
        self,
        transaction: AccountTransaction,
        parent: NetOrder,
        event: OrderEvent,
        activation: PaperActivation,
        now: datetime,
    ) -> bool:
        """Settle only unsent shadow reservations after an explicit account stop."""
        order = parent.order
        if (
            self.config.mode != "shadow"
            or activation.deployment.submission_authority != "shadow"
            or event.kind != "rejected"
            or event.fill is not None
            or event.at > now
            or order.accepted
            or order.request_acknowledged
            or order.cancel_acknowledged
            or order.filled.value != 0
            or order.paid_fee.value != 0
        ):
            return False
        if order.status == "rejected":
            return any(saved.event == event for saved in transaction.state.net_events)
        return transaction.account(parent.account_id).phase in (
            "stopped",
            "faulted",
        ) and order.status in ("intent", "cancel_requested")

    def _require_venue_evidence(self, event: OrderEvent) -> None:
        """Refuse facts a test venue's evidence cannot support, before any effect.

        Venue fills arrive with native costs through ``apply_native_fill``. A venue
        reports a terminal cancellation without the cause our request would need,
        and acknowledging a cancel only accepts the request, so no venue fact is a
        requested cancellation that took effect.
        """
        if self.config.mode != "venue_test":
            return
        if event.fill is not None:
            raise ValueError("venue fills require apply_native_fill")
        if event.kind == "cancelled_on_request":
            raise ValueError("venue cancellations carry no requested-cancellation cause")

    def correct_net_fee(self, correction: NetFeeCorrection) -> NetOrder:
        """Revise one physical fill fee and its child postings in one transaction."""
        correction.__post_init__()
        with self._store.write() as transaction:
            source = next(
                (
                    saved.event
                    for saved in transaction.state.net_events
                    if saved.event.fill is not None
                    and saved.event.fill.identity == correction.physical_fill_id
                ),
                None,
            )
            if source is not None:
                PaperAuthority.require_owner(
                    transaction,
                    transaction.net_order(source.order_id).account_id,
                    self.paper_owner,
                    at=self._now(),
                    new_exposure=False,
                )
            return self._allocation.correct_fee(transaction, correction)

    def stop_instance(self, instance_id: str, at: datetime) -> tuple[NetOrder, ...]:
        """Fence one strategy and request cancellation of shared physical parents."""
        self._admission.require_instance(instance_id)
        self._admission.require_utc(at, field_name="strategy stop")
        with self._stop_write(instance_id=instance_id) as transaction:
            if self.paper_owner is not None:
                account_id = next(
                    item.account_id
                    for item in self.config.budgets.instances
                    if item.instance_id == instance_id
                )
                activation = PaperAuthority.require_owner(
                    transaction, account_id, self.paper_owner, at=self._now(), new_exposure=False
                )
                if activation is not None and instance_id not in {
                    item.instance_id for item in activation.deployment.strategies
                }:
                    raise ValueError("paper_authorization_scope_differs")
            self._replacements.withdraw(transaction, instance_id, at)
            return self._portfolio.stop_instance(transaction, instance_id, at)

    def restart_instance(self, instance_id: str, at: datetime) -> None:
        """Re-enable a stopped instance after physical release and reconciliation."""
        self._admission.require_instance(instance_id)
        self._admission.require_utc(at, field_name="strategy restart")
        with self._store.write() as transaction:
            account_id = next(
                item.account_id
                for item in self.config.budgets.instances
                if item.instance_id == instance_id
            )
            activation = PaperAuthority.require_owner(
                transaction, account_id, self.paper_owner, at=self._now(), new_exposure=True
            )
            if activation is not None and instance_id not in {
                item.instance_id for item in activation.deployment.strategies
            }:
                raise ValueError("paper_authorization_scope_differs")
            self._replacements.settle(transaction, at)
            self._portfolio.restart_instance(transaction, instance_id, at)

    def reissue_pending(self, account_id: str, at: datetime) -> tuple[NetOrder, ...]:
        """Create physical orders for unaffected residuals after observation."""
        self._admission.require_utc(at, field_name="physical reissue")
        with self._store.write() as transaction:
            PaperAuthority.require_owner(
                transaction, account_id, self.paper_owner, at=self._now(), new_exposure=True
            )
            self._replacements.settle(transaction, at)
            return self._portfolio.reissue_pending(transaction, account_id, at)

    def apply_event(self, event: OrderEvent) -> OrderState:
        """Post normalized order and fill facts; durably block contradictions."""
        self._require_venue_evidence(event)
        event.__post_init__()
        with self._store.write() as transaction:
            if transaction.state.paper_activations:
                PaperAuthority.require_owner(
                    transaction,
                    transaction.order(event.order_id).account_id,
                    self.paper_owner,
                    at=self._now(),
                    new_exposure=False,
                )
            if (
                transaction.state.paper_activations
                and PaperAuthority.find(transaction, transaction.order(event.order_id).account_id)
                is not None
            ):
                raise ValueError("managed_paper_events_require_public_matching")
            self._replacements.settle(transaction, event.at)
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
            PaperAuthority.require_owner(
                transaction,
                posting.account_id,
                self.paper_owner,
                at=self._now(),
                new_exposure=False,
            )
            if PaperAuthority.find(transaction, posting.account_id) is not None:
                raise ValueError("managed_paper_postings_require_public_matching")
            self._replacements.settle(transaction, posting.known_at)
            snapshot, failure = self._admission.post(transaction, posting)
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        return snapshot

    def reconcile(self, observation: AccountObservation) -> bool:
        """Compare all account and open-order facts while preserving operator stops."""
        observation.__post_init__()
        with self._store.write() as transaction:
            if self.paper_owner is not None:
                PaperAuthority.require_owner(
                    transaction,
                    observation.snapshot.account_id,
                    self.paper_owner,
                    at=self._now(),
                    new_exposure=False,
                )
            self._replacements.settle(transaction, observation.at)
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
        self, transaction: AccountTransaction, request: NativeFill
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
        grew = self._cover_native_fee(transaction, request, physical)
        if grew:
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
        if grew:
            account_id = (
                physical.account_id
                if isinstance(physical, NetOrder)
                else transaction.order(request.order_id).account_id
            )
            try:
                self._admission.require_funded(transaction, account_id)
            except ValueError as error:
                if str(error) != "insufficient_cash":
                    raise
                # The fill stands; new exposure waits for independent funding.
                account = transaction.account(account_id)
                transaction.save_account(replace(account, fault="native_fee_overage_uncovered"))
        return final, allocations

    def _post_native_cost(
        self, transaction: AccountTransaction, request: NativeFill, is_net: bool
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
                reserve = Fraction(
                    (child.order.maximum_fee - child.order.paid_fee).value
                ) - self._prior_native_cost(transaction, child_id)
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
                self._codec.encode_json(("native-fee", request.identity, child_id))
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
    def _prior_native_cost(transaction: AccountTransaction, child_id: str) -> Fraction:
        """Return the quote value of base-currency native fees an order already bore."""
        return sum(
            (
                Fraction(allocation.amount.value) * Fraction(saved.request.price.value)
                for saved in transaction.state.native_fills
                if saved.request.fee.currency == saved.request.base_currency
                for allocation in saved.allocations
                if allocation.child_order_id == child_id and allocation.amount.value > 0
            ),
            Fraction(0),
        )

    def _cover_native_fee(
        self, transaction: AccountTransaction, request: NativeFill, physical: OrderState | NetOrder
    ) -> bool:
        """Raise fee reserves to cover a native fee the venue has already charged.

        A sell filling above its limit can cost more than the reserve admission
        sized at the limit. The venue's fill is a fact, so the reserves of the
        physical order and of the children bearing it grow by the shortfall
        (split by allocated quantity, rounded up to the minor unit); the posting
        then pays the excess from free cash. Rebates and fees within the reserve
        change nothing.

        Returns:
            Whether any reserve grew.
        """
        if request.fee.value <= 0:
            return False
        if request.fee.currency == request.price.currency:
            cost, quote_fee = Fraction(request.fee.value), True
        elif request.fee.currency == request.base_currency:
            cost = Fraction(request.fee.value) * Fraction(request.price.value)
            quote_fee = False
        else:
            return False
        if isinstance(physical, NetOrder):
            targets = tuple(
                (item.child_order_id, Fraction(item.quantity.value))
                for item in physical.allocations
            )
        else:
            targets = ((physical.identity, Fraction(1)),)
        available = Fraction(0)
        for child_id, _ in targets:
            child = transaction.order(child_id).order
            capacity = Fraction((child.maximum_fee - child.paid_fee).value)
            if not quote_fee:
                capacity -= self._prior_native_cost(transaction, child_id)
            available += max(capacity, Fraction(0))
        if isinstance(physical, NetOrder) and quote_fee:
            parent = physical.order
            available = min(available, Fraction((parent.maximum_fee - parent.paid_fee).value))
        shortfall = cost - available
        if shortfall <= 0:
            return False
        minor = Fraction(request.price.currency.minor_unit)
        weight = sum((item[1] for item in targets), Fraction(0))
        grown = Fraction(0)
        for child_id, share in targets:
            quantum = shortfall * share / weight / minor
            growth = (quantum.numerator + quantum.denominator - 1) // quantum.denominator * minor
            tagged = transaction.order(child_id)
            order = tagged.order
            transaction.save_order(
                replace(
                    tagged,
                    order=replace(
                        order,
                        maximum_fee=order.maximum_fee
                        + Money(
                            value=DecimalGrid.exact_decimal(growth),
                            currency=order.maximum_fee.currency,
                        ),
                    ),
                )
            )
            grown += growth
        if isinstance(physical, NetOrder):
            parent = physical.order
            transaction.save_net_order(
                replace(
                    physical,
                    order=replace(
                        parent,
                        maximum_fee=parent.maximum_fee
                        + Money(
                            value=DecimalGrid.exact_decimal(grown),
                            currency=parent.maximum_fee.currency,
                        ),
                    ),
                )
            )
        return True

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
    def _physical_order(transaction: AccountTransaction, order_id: str) -> OrderState | NetOrder:
        """Resolve only a physical direct order or portfolio parent."""
        parent = transaction.find_net_order(order_id)
        if parent is not None:
            return parent
        tagged = transaction.find_order(order_id)
        if tagged is not None and tagged.context is None:
            return tagged.order
        raise ValueError("unknown physical order")

    def _record_failed_native(
        self,
        transaction: AccountTransaction,
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

    # Stop-type writers poll for a held lease this often, outside any transaction.
    _LEASE_POLL_SECONDS = 0.02
    # A stop waits at most this long for live leases; it outlasts any lease's send.
    _STOP_WAIT_SECONDS = 35.0
    # The transport must end this long before its lease, as a safety margin.
    _DISPATCH_MARGIN = timedelta(seconds=5)

    def _lease_lock(self, holder: str) -> Path:
        """Return the lock file whose OS lock marks this holder's lease as live."""
        return self.path.with_name(f"{self.path.name}.lease-{holder}")

    def _hold_lease(self, holder: str) -> int:
        """Create and lock a holder's lock file; the kernel frees it if the holder dies."""
        descriptor = os.open(self._lease_lock(holder), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(descriptor)
            self._lease_lock(holder).unlink(missing_ok=True)
            raise
        return descriptor

    def _free_lease(self, holder: str, descriptor: int) -> None:
        """Remove the lock file first, so a lease row left behind reads as ended."""
        try:
            self._lease_lock(holder).unlink(missing_ok=True)
        finally:
            os.close(descriptor)

    def _lease_live(self, holder: str) -> bool:
        """Report whether a holder still holds its lock (a released lease has no file)."""
        try:
            descriptor = os.open(self._lease_lock(holder), os.O_RDWR)
        except FileNotFoundError:
            return False
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(descriptor)
        return False

    def _drop_ended_leases(self, transaction: AccountTransaction) -> None:
        """Delete leases whose holder released or died; their sends have ended."""
        for lease in transaction.leases():
            if not self._lease_live(lease.holder):
                transaction.release_lease(lease.order_id, lease.holder)
                self._lease_lock(lease.holder).unlink(missing_ok=True)

    @contextmanager
    def _stop_write(
        self, *, account_id: str | None = None, instance_id: str | None = None
    ) -> Iterator[AccountTransaction]:
        """Open a stop-type write once no live dispatch lease covers its scope.

        A live lease means a send whose final checks preceded this stop may still
        be pending, so the stop waits (outside any transaction) until the lease is
        released or its holder dies, and removes ended leases when it commits.

        Raises:
            ValueError: A live lease outlasted the stop's bounded wait; nothing is
                committed, because the send under it may still reach the venue.
        """
        give_up = self._monotonic() + self._STOP_WAIT_SECONDS
        while True:
            with self._store.write() as transaction:
                self._drop_ended_leases(transaction)
                if not transaction.lease_held(account_id=account_id, instance_id=instance_id):
                    yield transaction
                    return
            if self._monotonic() >= give_up:
                raise ValueError("dispatch in progress; stop not committed")
            time.sleep(self._LEASE_POLL_SECONDS)

    @contextmanager
    def execution_guard(
        self,
        account_id: str,
        order_id: str,
        at: datetime,
        *,
        cancel: bool = False,
        clock: Callable[[], datetime] | None = None,
        lease: timedelta = timedelta(seconds=30),
        send_window: timedelta = timedelta(seconds=10),
    ) -> Iterator[DispatchPermit]:
        """Commit the final dispatch checks, then send with no journal transaction open.

        A submission arms a ``DispatchLease`` in the same short transaction as its
        final checks. Stop-type writers for the account or its instances wait for
        the lease, so a stop either commits before arming (arming then refuses) or
        after release. The lease lives while this process holds its OS lock, so a
        sender that dies frees it at once and no clock expires a live one. On the
        monotonic clock, the send must start within ``send_window`` of arming and
        the transport must end by the permit's deadline, a safety margin before
        ``lease`` ends; a stop waits at most ``_STOP_WAIT_SECONDS``. A cancellation
        checks the order in a short transaction and holds no lease: it remains
        available while stopped and a stop never waits for it.
        """
        if self.config.mode != "venue_test":
            raise ValueError("execution guard requires venue_test mode")
        self._admission.require_utc(at, field_name="physical dispatch")
        if (
            not timedelta(0) < send_window < lease - self._DISPATCH_MARGIN
            or lease.total_seconds() >= self._STOP_WAIT_SECONDS
        ):
            raise ValueError("dispatch lease must outlast its send window and fit a stop's wait")
        holder = uuid.uuid4().hex
        armed: DispatchLease | None = None
        lock: int | None = None
        armed_monotonic = 0.0
        try:
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
                        or at - quote.at
                        > timedelta(microseconds=self.config.budgets.max_quote_age_us)
                    ):
                        raise ValueError("dispatch quote is stale")
                    reference = Fraction(quote.price.value)
                    limit = Fraction(order.intent.limit.value)
                    if (
                        abs(limit - reference) * 10_000
                        > reference * self.config.budgets.max_price_deviation_bps
                    ):
                        raise ValueError("dispatch price deviation")
                    self._admission.require_reissue_safe(
                        transaction,
                        account_id,
                        at,
                        buyers=instance_ids if order.intent.side == "buy" else (),
                    )
                    self._drop_ended_leases(transaction)
                    if transaction.lease_held(account_id=account_id):
                        raise ValueError("another dispatch is in progress")
                    # The OS lock precedes the committed row, so a live row is never lockless.
                    lock = self._hold_lease(holder)
                    armed_monotonic = self._monotonic()
                    armed = DispatchLease(
                        order_id=order_id,
                        account_id=account_id,
                        instance_ids=instance_ids,
                        holder=holder,
                        armed_at=self._now(),
                    )
                    transaction.arm_lease(armed)
        except BaseException:
            if lock is not None:
                self._free_lease(holder, lock)
            raise
        if armed is None or lock is None:
            yield DispatchPermit(order, None, None, None, self._monotonic)
            return
        failure: BaseException | None = None
        try:
            yield DispatchPermit(
                order,
                armed,
                armed_monotonic + send_window.total_seconds(),
                armed_monotonic + (lease - self._DISPATCH_MARGIN).total_seconds(),
                self._monotonic,
            )
        except BaseException as error:
            failure = error
            raise
        finally:
            # Best effort: a lock timeout here must not replace the send's outcome.
            # Freeing the OS lock regardless ends the lease for every stop.
            try:
                with self._store.write() as transaction:
                    transaction.release_lease(order_id, holder)
            except sqlite3.Error as error:
                if failure is not None:
                    failure.add_note(f"dispatch lease release failed: {error}")
            finally:
                self._free_lease(holder, lock)
