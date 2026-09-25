"""Own account admission, direct lifecycle effects, and reconciliation rules."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountSnapshot
from configuration import AccountConfiguration
from execution.account_records import (
    AccountDecision,
    AccountObservation,
    AccountQuote,
    AccountView,
    TaggedOrder,
)
from execution.account_state import (
    _AccountTransaction,
    _Reconciliation,
    _SavedEvent,
)
from execution.lifecycle import SpotOrderLifecycle
from execution.records import OrderEvent, OrderState, StepCommit
from financial_units import Dimension, Money, Price, Quantity
from portfolio import PortfolioContext
from risk import BudgetEngine, BudgetRequest, ExposureCommitment, SpotLimits
from serialization import DomainCodec
from strategies import ExposureIntent, TargetIntent

if TYPE_CHECKING:
    # project library imports
    from execution.account_allocation import PhysicalAllocation


class AccountAdmission:
    """Evaluate authoritative risk and reconcile direct account effects."""

    def __init__(self, config: AccountConfiguration, codec: DomainCodec) -> None:
        """Bind immutable configuration and the journal's canonical codec."""
        self.config = config
        self.codec = codec

    def admit(
        self,
        transaction: _AccountTransaction,
        request: AccountDecision,
        *,
        context: PortfolioContext | None = None,
        crossing_ids: set[str] | None = None,
    ) -> StepCommit:
        """Evaluate a decision against authoritative holdings and firm commitments."""
        account = transaction.account(request.account_id)
        if account.operator_block or account.fault:
            raise ValueError(account.operator_block or account.fault or "account_blocked")
        if request.instance_id in transaction.state.stopped_instances:
            raise ValueError("instance_stopped")
        if account.reconciled_at is None:
            raise ValueError("account_not_reconciled")
        if request.decision.at < max(
            self.account_time(transaction, item) for item in transaction.state.accounts
        ):
            raise ValueError("decision_precedes_account_state")
        if any(
            tagged.account_id == request.account_id and tagged.order.status == "unknown"
            for tagged in transaction.state.orders
        ) or any(
            parent.account_id == request.account_id and parent.order.status == "unknown"
            for parent in transaction.state.net_orders
        ):
            raise ValueError("order_outcome_unknown")
        owner = next(
            (
                item
                for item in self.config.budgets.instances
                if item.instance_id == request.instance_id
            ),
            None,
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
            (
                quote
                for quote in transaction.state.quotes
                if quote.price.per == request.quote.price.per
            ),
            None,
        )
        if observed != request.quote:
            raise ValueError("unobserved_quote")
        limits = self.limits(request.quote.price)
        ledger = AccountLedger(account.ledger)
        owned = ledger.snapshot(instance_id=request.instance_id)
        holding = next(
            (
                position
                for position in owned.positions
                if position.dimension == limits.lot.dimension
            ),
            Quantity(value=Decimal(0), dimension=limits.lot.dimension),
        )
        lifecycle = SpotOrderLifecycle(limits)
        if isinstance(request.decision.intent, (TargetIntent, ExposureIntent)) and any(
            tagged.instance_id == request.instance_id and not tagged.order.is_terminal
            for tagged in transaction.state.orders
        ):
            raise ValueError("pending_target")
        legs = lifecycle.lower(request.decision.intent, holding, request.quote.price)
        admitted: list[OrderState] = []
        for leg_name, intent in legs:
            reason = lifecycle.order_reason(intent)
            if reason is not None:
                raise ValueError(reason)
            commitments = self.commitments(transaction, request.decision.at)
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
            for tagged in transaction.state.orders:
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
                self.codec.encode_json(
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
                *transaction.state.orders,
                TaggedOrder(
                    account_id=request.account_id,
                    instance_id=request.instance_id,
                    order=order,
                    context=context,
                    quote=request.quote if context is not None else None,
                ),
            )
            transaction.state = replace(transaction.state, orders=orders)
            self.require_funded(transaction, request.account_id)
            admitted.append(order)
        return StepCommit(
            status="committed",
            reason="reserved" if admitted else "target_matched",
            orders=tuple(admitted),
        )

    def apply_event(
        self, transaction: _AccountTransaction, event: OrderEvent
    ) -> tuple[OrderState | None, str | None]:
        """Apply a direct fact while retaining contradictory receipts for commit."""
        failure: str | None = None
        result: OrderState | None = None
        for saved in transaction.state.events:
            if saved.event.identity == event.identity:
                if saved.event != event:
                    failure = "event identity reused with different content"
                    self.record_failed_event(transaction, event)
                    break
                return saved.result, None
        if failure is None:
            for saved in transaction.state.events:
                if (
                    event.fill is not None
                    and saved.event.fill is not None
                    and saved.event.fill.identity == event.fill.identity
                ):
                    if event.order_id != saved.event.order_id or event.fill != saved.event.fill:
                        failure = "fill identity reused with different economics"
                        self.record_failed_event(transaction, event)
                        break
                    return transaction.order(event.order_id).order, None
        if failure is None:
            tagged = transaction.order(event.order_id)
            if tagged.context is not None:
                raise ValueError("portfolio child events require physical parent routing")
            if self.config.mode == "shadow" and event.fill is not None:
                raise ValueError("shadow mode cannot post modeled fills")
            try:
                result = self.apply_order_event(transaction, tagged, event)
            except ValueError as error:
                failure = str(error)
                self.record_failed_event(transaction, event)
                result = tagged.order
            else:
                events: tuple[_SavedEvent, ...] = (
                    *transaction.state.events,
                    _SavedEvent(event=event, result=result),
                )
                transaction.state = replace(transaction.state, events=events)
        return result, failure

    def post(
        self, transaction: _AccountTransaction, posting: AccountPosting
    ) -> tuple[AccountSnapshot, str | None]:
        """Apply an identified transfer, cost, or correction within staged state."""
        failure: str | None = None
        account = transaction.account(posting.account_id)
        before = transaction.state
        ledger = AccountLedger(account.ledger)
        snapshot = ledger.snapshot()
        try:
            prior = next(
                (item for item in ledger.state.postings if item.identity == posting.identity),
                None,
            )
            if prior is None and posting.order_id is not None:
                owner = transaction.order(posting.order_id)
                if owner.context is not None and posting.kind in ("fill", "fee"):
                    raise ValueError("portfolio child economics require physical parent routing")
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
            if prior is None and posting.known_at < self.account_time(transaction, account):
                raise ValueError("posting knowledge precedes current account state")
            previous = ledger.state
            snapshot = ledger.post(posting)
            if previous == ledger.state:
                return snapshot, None
            if posting.order_id is not None:
                tagged = transaction.order(posting.order_id)
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
                corrected = self.posted_order(tagged.order, ledger)
                transaction.save_order(replace(tagged, order=corrected))
            elif posting.kind in ("fill", "fee", "rebate"):
                raise ValueError("trading postings require a reserved order")
            transaction.save_account(
                replace(account, ledger=ledger.state, fault="posting_reconciliation")
            )
        except ValueError as error:
            failure = str(error)
            transaction.state = before
            transaction.save_account(replace(account, fault="posting_break"))
            failed: tuple[AccountPosting, ...] = (*transaction.state.failed_postings, posting)
            transaction.state = replace(transaction.state, failed_postings=failed)
        return snapshot, failure

    def reconcile(
        self,
        transaction: _AccountTransaction,
        observation: AccountObservation,
        allocation: PhysicalAllocation,
    ) -> bool:
        """Compare complete independent state and clear only fully resolved faults."""
        for saved in transaction.state.reconciliations:
            if saved.observation.identity == observation.identity:
                if saved.observation != observation:
                    raise ValueError("observation identity reused with different content")
                return saved.matched
        account = transaction.account(observation.snapshot.account_id)
        ledger = AccountLedger(account.ledger)
        latest = self.account_time(transaction, account)
        orders = tuple(
            tagged.order
            for tagged in transaction.state.orders
            if tagged.account_id == observation.snapshot.account_id
            and tagged.context is None
            and not tagged.order.is_terminal
        ) + tuple(
            parent.order
            for parent in transaction.state.net_orders
            if parent.account_id == observation.snapshot.account_id and not parent.order.is_terminal
        )
        latest = max(latest, *(order.decision_at for order in orders)) if orders else latest
        matched = (
            observation.at >= latest
            and (account.reconciled_at is None or observation.at >= account.reconciled_at)
            and observation.snapshot == ledger.snapshot()
            and {order.identity: order for order in observation.open_orders}
            == {order.identity: order for order in orders}
            and not any(order.status == "unknown" for order in orders)
            and allocation.physical_attribution_matches(transaction, account.ledger.account_id)
            and not any(
                posting.account_id == account.ledger.account_id
                and posting.identity
                not in tuple(applied.identity for applied in account.ledger.postings)
                for posting in transaction.state.failed_postings
            )
            and not any(
                account.ledger.account_id in self.failed_event_account_ids(transaction, failed)
                and (
                    self.failed_event_conflicts_with_accepted_fact(transaction, failed)
                    or (
                        failed.fill is not None
                        and failed.fill.identity
                        not in tuple(posting.identity for posting in account.ledger.postings)
                    )
                )
                for failed in transaction.state.failed_events
            )
            and not any(
                account.ledger.account_id in self.failed_net_event_account_ids(transaction, failed)
                for failed in transaction.state.failed_net_events
            )
        )
        if matched:
            try:
                self.require_funded(transaction, account.ledger.account_id)
            except ValueError:
                matched = False
        transaction.save_account(
            replace(
                account,
                fault=None if matched else "account_break",
                reconciled_at=observation.at if matched else account.reconciled_at,
            )
        )
        reconciliations: tuple[_Reconciliation, ...] = (
            *transaction.state.reconciliations,
            _Reconciliation(observation=observation, matched=matched),
        )
        transaction.state = replace(transaction.state, reconciliations=reconciliations)
        return matched

    def commitments(
        self, transaction: _AccountTransaction, at: datetime
    ) -> tuple[ExposureCommitment, ...]:
        """Count held positions and unresolved buys and fees without offsetting sells."""
        result: list[ExposureCommitment] = []
        currency = self.config.budgets.valuation_currency
        attached = {
            allocation.child_order_id
            for parent in transaction.state.net_orders
            if not parent.order.is_terminal
            for allocation in parent.allocations
        }
        for owner in self.config.budgets.instances:
            account = transaction.account(owner.account_id)
            ledger = AccountLedger(account.ledger)
            held = Money(value=Decimal(0), currency=currency)
            reserved = held
            positions = ledger.snapshot(instance_id=owner.instance_id).positions
            orders = tuple(
                tagged.order
                for tagged in transaction.state.orders
                if tagged.instance_id == owner.instance_id
                and (not tagged.order.is_terminal or tagged.order.identity in attached)
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
                    (
                        item
                        for item in transaction.state.quotes
                        if item.price.per == position.dimension
                    ),
                    None,
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

    def require_funded(self, transaction: _AccountTransaction, account_id: str) -> None:
        """Require physical cash and owned and account inventory for pending legs."""
        ledger = AccountLedger(transaction.account(account_id).ledger)
        snapshot = ledger.snapshot()
        cash = {money.currency: money for money in snapshot.cash}
        buys: dict[Dimension, Quantity] = {}
        sells: dict[tuple[str, Dimension], Quantity] = {}
        attached = {
            allocation.child_order_id
            for parent in transaction.state.net_orders
            if not parent.order.is_terminal
            for allocation in parent.allocations
        }
        for tagged in transaction.state.orders:
            order = tagged.order
            if tagged.account_id != account_id or (
                order.is_terminal and order.identity not in attached
            ):
                continue
            currency = order.maximum_fee.currency
            cash[currency] -= order.maximum_fee - order.paid_fee
            if order.is_terminal:
                continue
            dimension = order.intent.quantity.dimension
            zero = Quantity(value=Decimal(0), dimension=dimension)
            if order.intent.side == "buy":
                cash[currency] -= order.intent.limit.amount(order.remaining)
                buys[dimension] = buys.get(dimension, zero) + order.remaining
            else:
                key = (tagged.instance_id, dimension)
                sells[key] = sells.get(key, zero) + order.remaining
        if any(money.value < 0 for money in cash.values()):
            raise ValueError("insufficient_cash")
        for (instance_id, dimension), reserved in sells.items():
            position = next(
                (
                    item
                    for item in ledger.snapshot(instance_id=instance_id).positions
                    if item.dimension == dimension
                ),
                None,
            )
            if position is None or position.value < reserved.value:
                raise ValueError("insufficient_owned_inventory")
        for limits in self.config.instruments:
            position = next(
                (item for item in snapshot.positions if item.dimension == limits.lot.dimension),
                Quantity(value=Decimal(0), dimension=limits.lot.dimension),
            )
            if (
                position
                + buys.get(
                    position.dimension,
                    Quantity(value=Decimal(0), dimension=position.dimension),
                )
            ).value > limits.maximum.value:
                raise ValueError("holding_limit")

    def require_reissue_safe(
        self, transaction: _AccountTransaction, account_id: str, at: datetime
    ) -> None:
        """Recheck gross capital, funding, and fresh prices before a physical send."""
        self.require_funded(transaction, account_id)
        commitments = self.commitments(transaction, at)
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
            for parent in transaction.state.net_orders
            if not parent.order.is_terminal
            for item in parent.allocations
        }
        for child in transaction.state.orders:
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
                    for item in transaction.state.quotes
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

    def apply_order_event(
        self,
        transaction: _AccountTransaction,
        tagged: TaggedOrder,
        event: OrderEvent,
    ) -> OrderState:
        """Share lifecycle semantics and commit fill and cost effects with order state."""
        account = transaction.account(tagged.account_id)
        ledger = AccountLedger(account.ledger)
        if event.at < self.account_time(transaction, account):
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
            old = next(
                (item for item in ledger.state.postings if item.identity == fill.identity),
                None,
            )
            if old is not None:
                if old != posting:
                    raise ValueError("fill identity reused with different economics")
                return tagged.order
        result = SpotOrderLifecycle(self.limits(tagged.order.intent.limit)).transition(
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
            transaction.save_account(replace(account, ledger=ledger.state))
        transaction.save_order(replace(tagged, order=result))
        return result

    def posted_order(self, order: OrderState, ledger: AccountLedger) -> OrderState:
        """Reconcile cumulative order economics after an append-only correction."""
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

    def observe_quote(self, transaction: _AccountTransaction, quote: AccountQuote) -> None:
        """Keep valuation time monotonic and reject conflicting equal clocks."""
        self.limits(quote.price)
        prior = next(
            (item for item in transaction.state.quotes if item.price.per == quote.price.per),
            None,
        )
        if prior is not None and (quote.at < prior.at or (quote.at == prior.at and quote != prior)):
            raise ValueError("valuation clock regressed or changed")
        quotes: tuple[AccountQuote, ...] = (
            *(item for item in transaction.state.quotes if item.price.per != quote.price.per),
            quote,
        )
        transaction.state = replace(transaction.state, quotes=quotes)

    def account_time(self, transaction: _AccountTransaction, account: AccountView) -> datetime:
        """Return the latest knowledge clock whose state admission would consume."""
        account_id = account.ledger.account_id
        clocks = [self.config.opening_at]
        if account.reconciled_at is not None:
            clocks.append(account.reconciled_at)
        clocks.extend(posting.known_at for posting in account.ledger.postings)
        clocks.extend(
            tagged.order.decision_at
            for tagged in transaction.state.orders
            if tagged.account_id == account_id
        )
        clocks.extend(
            saved.event.at
            for saved in transaction.state.events
            if transaction.order(saved.event.order_id).account_id == account_id
        )
        clocks.extend(
            event.at
            for event in transaction.state.failed_events
            if account_id in self.failed_event_account_ids(transaction, event)
        )
        clocks.extend(
            parent.order.decision_at
            for parent in transaction.state.net_orders
            if parent.account_id == account_id
        )
        clocks.extend(
            saved.event.at
            for saved in transaction.state.net_events
            if transaction.net_order(saved.event.order_id).account_id == account_id
        )
        clocks.extend(
            event.at
            for event in transaction.state.failed_net_events
            if account_id in self.failed_net_event_account_ids(transaction, event)
        )
        clocks.extend(
            control.at
            for control in transaction.state.instance_controls
            if self.instance_account(control.instance_id) == account_id
        )
        return max(clocks)

    def record_failed_event(self, transaction: _AccountTransaction, event: OrderEvent) -> None:
        """Retain one rejected direct fact and durably fence its accounts."""
        failed_events = transaction.state.failed_events
        if event not in failed_events:
            failed_events = (*failed_events, event)
        for account_id in self.failed_event_account_ids(transaction, event):
            transaction.save_account(
                replace(transaction.account(account_id), fault="order_event_break")
            )
        transaction.state = replace(transaction.state, failed_events=failed_events)

    def failed_event_account_ids(
        self, transaction: _AccountTransaction, event: OrderEvent
    ) -> tuple[str, ...]:
        """Resolve every account named by a rejected direct source fact."""
        account_ids: list[str] = []
        for saved in transaction.state.events:
            if saved.event.identity == event.identity or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
            ):
                account_ids.append(transaction.order(saved.event.order_id).account_id)
        try:
            account_ids.append(transaction.order(event.order_id).account_id)
        except ValueError:
            if not account_ids:
                raise
        unique_account_ids: list[str] = []
        for account_id in account_ids:
            if account_id not in unique_account_ids:
                unique_account_ids.append(account_id)
        return tuple(unique_account_ids)

    def failed_event_conflicts_with_accepted_fact(
        self, transaction: _AccountTransaction, event: OrderEvent
    ) -> bool:
        """Identify a rejected fact that contradicts accepted source bytes."""
        return any(
            (saved.event.identity == event.identity and saved.event != event)
            or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
                and (event.order_id != saved.event.order_id or event.fill != saved.event.fill)
            )
            for saved in transaction.state.events
        )

    def failed_net_event_account_ids(
        self, transaction: _AccountTransaction, event: OrderEvent
    ) -> tuple[str, ...]:
        """Resolve every account named by a rejected physical source fact."""
        account_ids: list[str] = []
        for saved in transaction.state.net_events:
            if saved.event.identity == event.identity or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
            ):
                account_ids.append(transaction.net_order(saved.event.order_id).account_id)
        try:
            account_ids.append(transaction.net_order(event.order_id).account_id)
        except ValueError:
            if not account_ids:
                raise
        unique_account_ids: list[str] = []
        for account_id in account_ids:
            if account_id not in unique_account_ids:
                unique_account_ids.append(account_id)
        return tuple(unique_account_ids)

    def require_instance(self, instance_id: str) -> None:
        """Reject unknown control targets without altering account state."""
        if not any(owner.instance_id == instance_id for owner in self.config.budgets.instances):
            raise ValueError("unknown instance")

    def instance_account(self, instance_id: str) -> str:
        """Resolve configured physical ownership for a strategy control."""
        for owner in self.config.budgets.instances:
            if owner.instance_id == instance_id:
                return owner.account_id
        raise ValueError("unknown instance")

    def limits(self, price: Price) -> SpotLimits:
        """Resolve supported instrument mechanics without implicit conversion."""
        for limits in self.config.instruments:
            if price.per == limits.lot.dimension and price.currency == limits.tick.currency:
                return limits
        raise ValueError("unknown instrument or valuation currency")

    @staticmethod
    def require_utc(at: datetime, *, field_name: str) -> None:
        """Require a caller-owned UTC control time without normalizing it."""
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise TypeError(f"{field_name} must be timezone-aware")
        if at.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must use UTC")
