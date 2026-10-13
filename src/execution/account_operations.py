"""Apply durable local account controls without releasing unresolved exposure."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta
from typing import Protocol

# third party library imports
from msgspec.structs import replace

# project library imports
from execution.account_admission import AccountAdmission
from execution.account_records import (
    AccountControl,
    AccountControlResult,
    AccountPhase,
    AccountView,
    PortfolioResidual,
)
from execution.account_state import AccountTransaction, _SavedEvent, _SavedNetEvent
from execution.lifecycle import SpotOrderLifecycle
from execution.records import OrderEvent, OrderState


class PlanWithdrawal(Protocol):
    """End an account's waiting paper plans at an operator cancel."""

    def __call__(
        self, transaction: AccountTransaction, account_id: str, at: datetime
    ) -> tuple[str, ...]:
        """Withdraw the plans and return their original decision identities."""
        ...


class AccountOperations:
    """Own account phase transitions and local cancel-request persistence.

    An operator account cancel withdraws the account's working intent and leaves
    its phase unchanged. It requests cancellation of every outstanding physical
    order, withdraws every waiting paper plan, and ends every unsent strategy
    order, releasing its reservation. A strategy order attached to a live physical
    order is marked for cancellation and keeps its reservation until that order's
    own outcome ends it, so it is never reissued as a residual. Holdings are
    untouched, and a later strategy decision may create new intent under the usual
    admission checks.
    """

    def __init__(self, admission: AccountAdmission, withdraw_plans: PlanWithdrawal) -> None:
        """Bind the journal's account and budget checks and its paper plan owner."""
        self.admission = admission
        self.withdraw_plans = withdraw_plans

    def apply(
        self, transaction: AccountTransaction, request: AccountControl
    ) -> AccountControlResult:
        """Persist an exact idempotent request and its original outcome."""
        request.__post_init__()
        saved = self.saved(transaction, request)
        if saved is not None:
            return saved
        account = transaction.account(request.account_id)
        before = transaction.state
        try:
            result = self._apply(transaction, request, account)
        except ValueError as error:
            transaction.state = before
            result = AccountControlResult(
                request=request,
                status="rejected",
                phase=account.phase,
                recovery_generation=account.recovery_generation,
                reason=str(error),
                withdrawn_decision_ids=(),
                withdrawn_order_ids=(),
            )
        controls: tuple[AccountControlResult, ...] = (*transaction.state.account_controls, result)
        transaction.state = replace(
            transaction.state,
            account_controls=controls,
        )
        return result

    @staticmethod
    def saved(
        transaction: AccountTransaction, request: AccountControl
    ) -> AccountControlResult | None:
        """Return an exact retry's original outcome, or None for a new identity.

        Raises:
            ValueError: The identity was already used with different content.
        """
        for saved in transaction.state.account_controls:
            if saved.request.identity == request.identity:
                if saved.request != request:
                    raise ValueError("account control identity reused with different content")
                return saved
        return None

    def _apply(
        self, transaction: AccountTransaction, request: AccountControl, account: AccountView
    ) -> AccountControlResult:
        """Check account-local clock and commit one permitted phase transition."""
        if request.at < self.admission.account_time(transaction, account):
            raise ValueError("account_control_clock_regressed")
        if request.kind in ("stop", "fault"):
            phase: AccountPhase = "stopped" if request.kind == "stop" else "faulted"
            transaction.save_account(
                replace(
                    account,
                    phase=phase,
                    active_control_identity=request.identity,
                    control_cutoff_at=request.at,
                )
            )
            return AccountControlResult(
                request=request,
                status="applied",
                phase=phase,
                recovery_generation=account.recovery_generation,
                withdrawn_decision_ids=(),
                withdrawn_order_ids=(),
            )
        if request.kind == "cancel":
            decisions = self.withdraw_plans(transaction, request.account_id, request.at)
            targets = self._request_cancellation(transaction, request)
            withdrawn = self._withdraw_strategy_orders(transaction, request.account_id)
            return AccountControlResult(
                request=request,
                status="applied",
                phase=account.phase,
                recovery_generation=account.recovery_generation,
                cancel_order_ids=targets,
                withdrawn_decision_ids=decisions,
                withdrawn_order_ids=withdrawn,
            )
        self._require_recovery_ready(transaction, request, account)
        generation = account.recovery_generation + 1
        transaction.save_account(
            replace(
                account,
                phase="running",
                recovery_generation=generation,
                active_control_identity=None,
                control_cutoff_at=None,
            )
        )
        return AccountControlResult(
            request=request,
            status="applied",
            phase="running",
            recovery_generation=generation,
            withdrawn_decision_ids=(),
            withdrawn_order_ids=(),
        )

    def _require_recovery_ready(
        self, transaction: AccountTransaction, request: AccountControl, account: AccountView
    ) -> None:
        """Require a new complete observation and fresh independent safety inputs."""
        if request.kind == "startup":
            if account.phase != "running" or account.active_control_identity is not None:
                raise ValueError("startup_requires_unused_account_controls")
            if any(
                saved.request.account_id == request.account_id and saved.status == "applied"
                for saved in transaction.state.account_controls
            ):
                raise ValueError("startup_requires_unused_account_controls")
            cutoff = self.admission.config.opening_at
        else:
            if (
                account.phase not in ("stopped", "faulted")
                or request.expected_control_identity != account.active_control_identity
                or account.control_cutoff_at is None
            ):
                raise ValueError("stale_account_restart_control")
            cutoff = account.control_cutoff_at
        if account.operator_block or account.fault:
            raise ValueError("account_blocked")
        reconciled_at = account.reconciled_at
        if (
            reconciled_at is None
            or reconciled_at <= cutoff
            or reconciled_at > request.at
            or reconciled_at < self.admission.account_time(transaction, account)
            or request.at - reconciled_at
            > timedelta(microseconds=self.admission.config.budgets.max_state_age_us)
            or not any(
                saved.matched
                and saved.observation.snapshot.account_id == request.account_id
                and saved.observation.at == reconciled_at
                and saved.observation.at > cutoff
                for saved in transaction.state.reconciliations
            )
        ):
            raise ValueError("account_recovery_requires_fresh_reconciliation")
        if self.has_unresolved_orders(transaction, request.account_id):
            raise ValueError("account_recovery_has_unresolved_order_outcome")
        for owner in self.admission.config.budgets.instances:
            if owner.account_id != request.account_id:
                continue
            for instrument in owner.instruments:
                quote = next(
                    (
                        item
                        for item in transaction.state.quotes
                        if item.price.per.instrument_id == instrument
                    ),
                    None,
                )
                if (
                    quote is None
                    or quote.at <= cutoff
                    or quote.at > request.at
                    or request.at - quote.at
                    > timedelta(microseconds=self.admission.config.budgets.max_quote_age_us)
                ):
                    raise ValueError("account_recovery_requires_fresh_quote")
        self.admission.require_reissue_safe(transaction, request.account_id, request.at)

    @classmethod
    def has_unresolved_orders(cls, transaction: AccountTransaction, account_id: str) -> bool:
        """Identify physical outcomes that must settle before replacing their owner."""
        return any(
            cls._unresolved_order(tagged.order, physical=tagged.context is None)
            for tagged in transaction.state.orders
            if tagged.account_id == account_id
        ) or any(
            cls._unresolved_order(parent.order, physical=True)
            for parent in transaction.state.net_orders
            if parent.account_id == account_id
        )

    @staticmethod
    def _unresolved_order(order: OrderState, *, physical: bool) -> bool:
        """Keep unknown sends and unconfirmed cancellation separate from open orders."""
        return not order.is_terminal and (
            order.status in ("unknown", "cancel_requested", "cancel_ack")
            or order.cancel_requested
            or (physical and not order.accepted)
        )

    def _request_cancellation(
        self, transaction: AccountTransaction, request: AccountControl
    ) -> tuple[str, ...]:
        """Record requests for outstanding physical orders without terminal claims."""
        targets: list[str] = []
        for tagged in transaction.state.orders:
            order = tagged.order
            if tagged.account_id != request.account_id or tagged.context is not None:
                continue
            if order.is_terminal:
                continue
            targets.append(order.identity)
            if order.cancel_requested:
                continue
            event = OrderEvent(
                identity=f"account-control:{request.identity}:{order.identity}",
                order_id=order.identity,
                at=request.at,
                kind="cancel_requested",
            )
            updated = self._cancel_order(order, event)
            transaction.save_order(replace(tagged, order=updated))
            events: tuple[_SavedEvent, ...] = (
                *transaction.state.events,
                _SavedEvent(event=event, result=updated),
            )
            transaction.state = replace(
                transaction.state,
                events=events,
            )
        for parent in transaction.state.net_orders:
            order = parent.order
            if parent.account_id != request.account_id or order.is_terminal:
                continue
            targets.append(order.identity)
            if order.cancel_requested:
                continue
            event = OrderEvent(
                identity=f"account-control:{request.identity}:{order.identity}",
                order_id=order.identity,
                at=request.at,
                kind="cancel_requested",
            )
            updated = self._cancel_order(order, event)
            net_order = replace(parent, order=updated)
            transaction.save_net_order(net_order)
            net_events: tuple[_SavedNetEvent, ...] = (
                *transaction.state.net_events,
                _SavedNetEvent(event=event, result=net_order, child_fill_ids=()),
            )
            transaction.state = replace(
                transaction.state,
                net_events=net_events,
            )
        return tuple(targets)

    @staticmethod
    def _withdraw_strategy_orders(
        transaction: AccountTransaction, account_id: str
    ) -> tuple[str, ...]:
        """End unsent strategy orders and mark attached ones to end with their parent.

        Unsent means not allocated to any nonterminal physical order, whether or not a
        residual record names it: ``residuals`` is only the visible subset. Ending one
        releases its reservation. An attached order keeps its reservation; marking it
        makes its parent's terminal outcome end it instead of leaving it to reissue,
        whether that outcome is a requested cancellation, a fill or a reconciled
        unknown.
        """
        attached = {
            allocation.child_order_id
            for parent in transaction.state.net_orders
            if parent.account_id == account_id and not parent.order.is_terminal
            for allocation in parent.allocations
        }
        withdrawn: list[str] = []
        for child in transaction.state.orders:
            if child.account_id != account_id or child.context is None or child.order.is_terminal:
                continue
            if child.order.identity in attached:
                if not child.order.cancel_requested:
                    transaction.save_order(
                        replace(child, order=replace(child.order, cancel_requested=True))
                    )
                continue
            transaction.save_order(replace(child, order=replace(child.order, status="cancelled")))
            withdrawn.append(child.order.identity)
        ended = set(withdrawn)
        residuals: tuple[PortfolioResidual, ...] = tuple(
            item for item in transaction.state.residuals if item.child_order_id not in ended
        )
        if residuals != transaction.state.residuals:
            transaction.state = replace(transaction.state, residuals=residuals)
        return tuple(withdrawn)

    def _cancel_order(self, order: OrderState, event: OrderEvent) -> OrderState:
        """Record a local cancel request through the shared spot lifecycle."""
        return SpotOrderLifecycle(self.admission.limits(order.intent.limit)).transition(
            order, event
        )
