"""Coordinate portfolio batches, physical order formation, and instance controls."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import Fill
from configuration import AccountConfiguration
from execution.account_admission import AccountAdmission
from execution.account_records import (
    NetAllocation,
    NetOrder,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioResidual,
    TaggedOrder,
)
from execution.account_state import (
    _AccountTransaction,
    _InstanceControl,
    _SavedDecision,
    _SavedEvent,
    _SavedNetEvent,
    _SavedPortfolioBatch,
)
from execution.lifecycle import SpotOrderLifecycle
from execution.records import OrderEvent, OrderState, StepCommit
from financial_units import DecimalGrid, Money, Quantity
from serialization import DomainCodec
from strategies import OrderIntent


class PortfolioCoordinator:
    """Own atomic portfolio admission and lifecycle control of physical parents."""

    def __init__(
        self,
        config: AccountConfiguration,
        codec: DomainCodec,
        admission: AccountAdmission,
    ) -> None:
        """Bind the authoritative risk service and canonical identity codec."""
        self.config = config
        self.codec = codec
        self.admission = admission

    def coordinate(
        self, transaction: _AccountTransaction, batch: PortfolioBatch
    ) -> PortfolioCommit:
        """Admit risk, cross by policy, and create physical orders atomically."""
        for saved in transaction.state.portfolio_batches:
            if saved.batch.identity == batch.identity:
                if saved.batch != batch:
                    raise ValueError("portfolio batch identity reused with different content")
                return saved.result
        before = transaction.state
        children: list[TaggedOrder] = []
        persist_rejection = False
        try:
            if (
                transaction.state.crossing_policy is not None
                and transaction.state.crossing_policy != batch.crossing
            ):
                raise ValueError("portfolio_crossing_policy_changed")
            for item in batch.decisions:
                request = item.request
                if any(
                    (saved.request.instance_id, saved.request.decision.identity)
                    == (request.instance_id, request.decision.identity)
                    for saved in transaction.state.decisions
                ):
                    raise ValueError("decision_already_admitted")
                current_checkpoint = next(
                    (
                        saved.request.checkpoint
                        for saved in reversed(transaction.state.decisions)
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
            if transaction.state.crossing_policy is None:
                transaction.state = replace(transaction.state, crossing_policy=batch.crossing)
            for item in batch.decisions:
                request = item.request
                step_commit = self.admission.admit(
                    transaction,
                    request,
                    context=item.context,
                    crossing_ids={child.order.identity for child in children}
                    if batch.crossing == "internal_at_quote"
                    else set(),
                )
                if step_commit.status != "committed":
                    raise ValueError(step_commit.reason)
                children.extend(transaction.order(order.identity) for order in step_commit.orders)
            for account_id in sorted({item.request.account_id for item in batch.decisions}):
                self.admission.require_reissue_safe(transaction, account_id, batch.at)
            crossed = (
                self._cross_internal(transaction, batch, tuple(children))
                if batch.crossing == "internal_at_quote"
                else ()
            )
            parents: list[NetOrder] = []
            for account_id in sorted({item.request.account_id for item in batch.decisions}):
                parents.extend(self._net_pending(transaction, account_id, batch.at))
            committed_children = tuple(
                transaction.order(child.order.identity) for child in children
            )
            affected_accounts = {item.request.account_id for item in batch.decisions}
            residuals = tuple(
                item for item in transaction.state.residuals if item.account_id in affected_accounts
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
                *transaction.state.decisions,
                *saved_decisions,
            )
            transaction.state = replace(transaction.state, decisions=decisions)
        except ValueError as error:
            transaction.state = before
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
                decisions = (*transaction.state.decisions, *rejected_decisions)
                transaction.state = replace(transaction.state, decisions=decisions)
        portfolio_batches: tuple[_SavedPortfolioBatch, ...] = (
            *transaction.state.portfolio_batches,
            _SavedPortfolioBatch(batch=batch, result=portfolio_result),
        )
        transaction.state = replace(transaction.state, portfolio_batches=portfolio_batches)
        return portfolio_result

    def stop_instance(
        self, transaction: _AccountTransaction, instance_id: str, at: datetime
    ) -> tuple[NetOrder, ...]:
        """Fence one strategy and request cancellation of shared physical parents."""
        owner = self.admission.instance_account(instance_id)
        if at < self.admission.account_time(transaction, transaction.account(owner)):
            raise ValueError("strategy stop clock regressed")
        if instance_id in transaction.state.stopped_instances:
            return tuple(
                parent
                for parent in transaction.state.net_orders
                if not parent.order.is_terminal
                and any(
                    transaction.order(allocation.child_order_id).instance_id == instance_id
                    for allocation in parent.allocations
                )
            )
        stopped_instances: tuple[str, ...] = (
            *transaction.state.stopped_instances,
            instance_id,
        )
        controls: tuple[_InstanceControl, ...] = (
            *transaction.state.instance_controls,
            _InstanceControl(instance_id=instance_id, at=at, state="stopped"),
        )
        transaction.state = replace(
            transaction.state,
            stopped_instances=stopped_instances,
            instance_controls=controls,
        )
        affected: list[NetOrder] = []
        attached = {
            allocation.child_order_id
            for parent in transaction.state.net_orders
            if not parent.order.is_terminal
            for allocation in parent.allocations
        }
        for parent in transaction.state.net_orders:
            if parent.order.is_terminal or not any(
                transaction.order(allocation.child_order_id).instance_id == instance_id
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
                    self.admission.limits(parent.order.intent.limit)
                ).transition(parent.order, request)
                updated = replace(parent, order=physical)
                transaction.save_net_order(updated)
                net_events = (
                    *transaction.state.net_events,
                    _SavedNetEvent(event=request, result=updated, child_fill_ids=()),
                )
                transaction.state = replace(transaction.state, net_events=net_events)
            affected.append(updated)
        for child in transaction.state.orders:
            if (
                child.instance_id == instance_id
                and not child.order.is_terminal
                and child.order.identity not in attached
            ):
                if child.context is not None:
                    transaction.save_order(
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
                        self.admission.limits(child.order.intent.limit)
                    ).transition(child.order, request)
                    transaction.save_order(replace(child, order=updated_order))
                    saved_events: tuple[_SavedEvent, ...] = (
                        *transaction.state.events,
                        _SavedEvent(event=request, result=updated_order),
                    )
                    transaction.state = replace(transaction.state, events=saved_events)
        return tuple(affected)

    def restart_instance(
        self, transaction: _AccountTransaction, instance_id: str, at: datetime
    ) -> None:
        """Re-enable a stopped instance after physical release and reconciliation."""
        if instance_id not in transaction.state.stopped_instances:
            raise ValueError("instance is not stopped")
        account = transaction.account(self.admission.instance_account(instance_id))
        if (
            account.phase != "running"
            or account.fault
            or account.operator_block
            or account.reconciled_at is None
            or account.reconciled_at < self.admission.account_time(transaction, account)
            or at < account.reconciled_at
            or any(
                child.instance_id == instance_id and not child.order.is_terminal
                for child in transaction.state.orders
            )
        ):
            raise ValueError("instance_restart_requires_reconciliation")
        stopped_instances = tuple(
            saved for saved in transaction.state.stopped_instances if saved != instance_id
        )
        controls = (
            *transaction.state.instance_controls,
            _InstanceControl(instance_id=instance_id, at=at, state="running"),
        )
        transaction.state = replace(
            transaction.state,
            stopped_instances=stopped_instances,
            instance_controls=controls,
        )

    def reissue_pending(
        self, transaction: _AccountTransaction, account_id: str, at: datetime
    ) -> tuple[NetOrder, ...]:
        """Create physical orders for unaffected residuals after observation."""
        account = transaction.account(account_id)
        if (
            account.phase != "running"
            or account.fault
            or account.operator_block
            or account.reconciled_at is None
        ):
            raise ValueError("account_not_reconciled")
        if account.reconciled_at < self.admission.account_time(transaction, account):
            raise ValueError("reissue_requires_current_reconciliation")
        if at < self.admission.account_time(transaction, account):
            raise ValueError("physical reissue clock regressed")
        if any(
            parent.account_id == account_id and parent.order.status == "unknown"
            for parent in transaction.state.net_orders
        ):
            raise ValueError("order_outcome_unknown")
        self.admission.require_reissue_safe(transaction, account_id, at)
        return self._net_pending(transaction, account_id, at)

    def _cross_internal(
        self,
        transaction: _AccountTransaction,
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
                current_buy = transaction.order(buy.order.identity)
                current_sell = transaction.order(sell.order.identity)
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
                        self.codec.encode_json(
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
                        quantity=Quantity(
                            value=signed,
                            dimension=order.intent.quantity.dimension,
                        ),
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
                    result = self.admission.apply_order_event(transaction, child, event)
                    saved_events: tuple[_SavedEvent, ...] = (
                        *transaction.state.events,
                        _SavedEvent(event=event, result=result),
                    )
                    transaction.state = replace(transaction.state, events=saved_events)
                    fill_ids.append(fill_id)
        return tuple(fill_ids)

    def _net_pending(
        self, transaction: _AccountTransaction, account_id: str, at: datetime
    ) -> tuple[NetOrder, ...]:
        """Group only unassigned compatible residual children into physical orders."""
        assigned = {
            allocation.child_order_id
            for parent in transaction.state.net_orders
            if not parent.order.is_terminal
            for allocation in parent.allocations
        }
        pending = [
            child
            for child in transaction.state.orders
            if child.account_id == account_id
            and child.context is not None
            and not child.order.is_terminal
            and child.order.remaining.value > 0
            and child.order.identity not in assigned
            and child.instance_id not in transaction.state.stopped_instances
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
                    sum(
                        (Fraction(child.order.remaining.value) for child in group),
                        Fraction(0),
                    )
                ),
                dimension=intent.quantity.dimension,
            )
            physical_intent = OrderIntent(
                side=intent.side,
                quantity=quantity,
                limit=intent.limit,
                time_in_force=intent.time_in_force,
            )
            reason = SpotOrderLifecycle(self.admission.limits(intent.limit)).order_reason(
                physical_intent
            )
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
                self.codec.encode_json(
                    (
                        "physical-net-v1",
                        account_id,
                        at,
                        tuple(child.order.identity for child in group),
                    )
                )
            ).hexdigest()
            if any(parent.order.identity == parent_id for parent in transaction.state.net_orders):
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
                            value=Decimal(0),
                            dimension=child.order.remaining.dimension,
                        ),
                    )
                    for child in group
                ),
                context=first.context,
            )
            net_orders: tuple[NetOrder, ...] = (
                *transaction.state.net_orders,
                parent,
            )
            transaction.state = replace(transaction.state, net_orders=net_orders)
            parents.append(parent)
        saved_residuals: tuple[PortfolioResidual, ...] = (
            *(item for item in transaction.state.residuals if item.account_id != account_id),
            *residuals,
        )
        transaction.state = replace(transaction.state, residuals=saved_residuals)
        return tuple(parents)
