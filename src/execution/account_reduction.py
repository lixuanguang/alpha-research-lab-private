"""Reserve bounded attributable paper sells after independent account safety checks."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from execution.account_records import AccountDecision, AccountQuote
from execution.records import OrderDecision, OrderState
from financial_units import Money, Price, Quantity
from serialization import WireRecord
from strategies import OrderIntent

if TYPE_CHECKING:
    # project library imports
    from execution.account_admission import AccountAdmission
    from execution.account_state import _AccountTransaction


class PaperReductionRequest(WireRecord, frozen=True):
    """Request one owned spot sale at an explicit minimum execution price."""

    identity: str
    account_id: str
    instance_id: str
    quantity: Quantity
    quote: AccountQuote
    limit: Price
    maximum_fee: Money
    at: datetime

    def __post_init__(self) -> None:
        """Validate exact ownership, units, fee cap and UTC request time."""
        self._require_utc(self.at, field_name="paper reduction")
        if any(
            type(value) is not str or not value
            for value in (self.identity, self.account_id, self.instance_id)
        ):
            raise ValueError("paper reduction requires identities and ownership")
        if (
            type(self.quantity) is not Quantity
            or type(self.quote) is not AccountQuote
            or type(self.limit) is not Price
            or type(self.maximum_fee) is not Money
        ):
            raise TypeError("paper reduction requires quantity, quote, limit and fee")
        self.quantity.model_copy()
        self.quote.__post_init__()
        self.limit.model_copy()
        self.maximum_fee.model_copy()
        if (
            self.quantity.value <= 0
            or self.limit.value <= 0
            or self.quantity.dimension != self.quote.price.per
            or self.quantity.dimension != self.limit.per
            or self.quote.price.currency != self.limit.currency
            or self.maximum_fee.currency != self.limit.currency
            or self.maximum_fee.value < 0
        ):
            raise ValueError("paper reduction has incompatible or unbounded economics")


class PaperReductionResult(WireRecord, frozen=True):
    """Retain the original reservation result; acceptance does not claim a fill."""

    request: PaperReductionRequest
    status: Literal["accepted", "rejected"]
    reason: str
    orders: tuple[OrderState, ...]

    def __post_init__(self) -> None:
        """Keep a rejected request effect-free and an accepted one attributable."""
        if type(self.request) is not PaperReductionRequest or type(self.orders) is not tuple:
            raise TypeError("paper reduction result requires request and orders")
        self.request.__post_init__()
        if (
            self.status not in ("accepted", "rejected")
            or type(self.reason) is not str
            or not self.reason
            or (self.status == "rejected" and self.orders)
            or (self.status == "accepted" and len(self.orders) != 1)
        ):
            raise ValueError("invalid paper reduction result")
        for order in self.orders:
            if type(order) is not OrderState:
                raise TypeError("paper reduction result requires OrderState")
            order.__post_init__()
            if (
                order.intent.side != "sell"
                or order.intent.quantity != self.request.quantity
                or order.intent.limit != self.request.limit
                or order.intent.time_in_force != "ioc"
                or order.decision_at != self.request.at
                or order.maximum_fee != self.request.maximum_fee
                or order.status != "intent"
                or order.filled.value != 0
            ):
                raise ValueError("paper reduction result differs from request")


class AccountReduction:
    """Own idempotent, direct paper reductions inside the firm transaction."""

    def __init__(self, admission: AccountAdmission) -> None:
        """Reuse the journal's independent account and budget admission."""
        self.admission = admission

    def apply(
        self,
        transaction: _AccountTransaction,
        request: PaperReductionRequest,
        *,
        admission_at: datetime | None = None,
    ) -> PaperReductionResult:
        """Persist the exact original outcome, without simulating a fill."""
        request.__post_init__()
        for saved in transaction.state.paper_reductions:
            if saved.request.identity == request.identity:
                if saved.request != request:
                    raise ValueError("paper reduction identity reused with different content")
                return saved
        if admission_at is not None and (
            request.at > admission_at
            or admission_at - request.at
            > timedelta(microseconds=self.admission.config.budgets.max_quote_age_us)
        ):
            raise ValueError("paper_reduction_stale_or_future")
        transaction.account(request.account_id)
        before = transaction.state
        try:
            order = self._reserve(transaction, request, admission_at=admission_at or request.at)
        except ValueError as error:
            transaction.state = before
            result = PaperReductionResult(
                request=request, status="rejected", reason=str(error), orders=()
            )
        else:
            result = PaperReductionResult(
                request=request, status="accepted", reason="reserved", orders=(order,)
            )
        reductions: tuple[PaperReductionResult, ...] = (
            *transaction.state.paper_reductions,
            result,
        )
        transaction.state = replace(transaction.state, paper_reductions=reductions)
        return result

    def _reserve(
        self,
        transaction: _AccountTransaction,
        request: PaperReductionRequest,
        *,
        admission_at: datetime,
    ) -> OrderState:
        """Require causal inputs that remain fresh at actual admission."""
        if self.admission.config.mode != "paper":
            raise ValueError("paper_reduction_requires_paper_mode")
        account = transaction.account(request.account_id)
        if account.fault is not None:
            raise ValueError("economic_reconciliation_fault")
        if account.operator_block is not None:
            raise ValueError("account_operator_blocked")
        if account.reconciled_at is None:
            raise ValueError("account_not_reconciled")
        if self._has_uncertain_outcome(transaction, request.account_id):
            raise ValueError("order_outcome_uncertain")
        latest = self.admission.account_time(transaction, account)
        if request.at < latest:
            raise ValueError("reduction_precedes_account_state")
        if account.reconciled_at < latest:
            raise ValueError("account_reconciliation_stale")
        if not any(
            saved.matched
            and saved.observation.snapshot.account_id == request.account_id
            and saved.observation.at == account.reconciled_at
            for saved in transaction.state.reconciliations
        ):
            raise ValueError("account_not_reconciled")
        if admission_at - account.reconciled_at > timedelta(
            microseconds=self.admission.config.budgets.max_state_age_us
        ):
            raise ValueError("stale_state")
        if request.quote.at > request.at:
            raise ValueError("future_quote")
        if admission_at - request.quote.at > timedelta(
            microseconds=self.admission.config.budgets.max_quote_age_us
        ):
            raise ValueError("stale_quote")
        observed = next(
            (
                quote
                for quote in transaction.state.quotes
                if quote.price.per == request.quantity.dimension
            ),
            None,
        )
        if observed != request.quote:
            raise ValueError("unobserved_quote")
        bindings = tuple(
            binding
            for binding in transaction.state.paper_bindings
            if binding.account_id == request.account_id
            and binding.scenario.instrument_id == request.quantity.dimension.instrument_id
        )
        if len(bindings) != 1:
            raise ValueError("paper_market_disconnected")
        last_trace = next(
            (
                item
                for item in transaction.iter_traces(request.account_id, newest_first=True)
                if item.scenario == bindings[0].scenario
            ),
            None,
        )
        if last_trace is None or last_trace.status != "committed":
            raise ValueError("paper_market_disconnected")
        market_at = last_trace.market.at
        if market_at > request.at:
            raise ValueError("future_paper_market")
        if admission_at - market_at > timedelta(
            microseconds=self.admission.config.budgets.max_quote_age_us
        ):
            raise ValueError("stale_paper_market")
        identity = hashlib.sha256(
            self.admission.codec.encode_json(("paper-reduction", request.identity))
        ).hexdigest()
        decision = AccountDecision(
            account_id=request.account_id,
            instance_id=request.instance_id,
            decision=OrderDecision(
                identity=identity,
                at=request.at,
                intent=OrderIntent(
                    side="sell",
                    quantity=request.quantity,
                    limit=request.limit,
                    time_in_force="ioc",
                ),
            ),
            quote=request.quote,
            maximum_fee=request.maximum_fee,
        )
        commitment = self.admission.admit(transaction, decision, protective=True)
        if len(commitment.orders) != 1:
            raise ValueError("paper_reduction_requires_one_order")
        return commitment.orders[0]

    @staticmethod
    def _has_uncertain_outcome(transaction: _AccountTransaction, account_id: str) -> bool:
        """Refuse unknown sends and unfinished cancellation on any physical order."""
        orders = (
            *(
                tagged.order
                for tagged in transaction.state.orders
                if tagged.account_id == account_id
            ),
            *(
                parent.order
                for parent in transaction.state.net_orders
                if parent.account_id == account_id
            ),
        )
        return any(
            not order.is_terminal
            and (
                order.status in ("unknown", "request_ack", "cancel_requested", "cancel_ack")
                or order.cancel_requested
            )
            for order in orders
        )
