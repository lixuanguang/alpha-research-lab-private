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
    AccountTransaction,
    SavedDecision,
    SavedPortfolioBatch,
    _InstanceControl,
    _SavedEvent,
)
from execution.lifecycle import SpotOrderLifecycle
from execution.records import DroppedLeg, OrderEvent, OrderState, StepCommit
from financial_units import DecimalGrid, Money, Quantity
from risk import BudgetEngine
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

    def coordinate(self, transaction: AccountTransaction, batch: PortfolioBatch) -> PortfolioCommit:
        """Admit risk, cross by policy, and create physical orders atomically."""
        saved = transaction.find_batch(batch.identity)
        if saved is not None:
            if saved.batch != batch:
                raise ValueError("portfolio batch identity reused with different content")
            return saved.result
        before = transaction.state
        children: list[TaggedOrder] = []
        dropped: dict[str, tuple[DroppedLeg, ...]] = {}
        persist_rejection = False
        try:
            if (
                transaction.state.crossing_policy is not None
                and transaction.state.crossing_policy != batch.crossing
            ):
                raise ValueError("portfolio_crossing_policy_changed")
            for item in batch.decisions:
                request = item.request
                if (
                    transaction.find_decision(request.instance_id, request.decision.identity)
                    is not None
                ):
                    raise ValueError("decision_already_admitted")
                current_checkpoint = transaction.latest_checkpoint(request.instance_id) or b""
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
                dropped[request.decision.identity] = step_commit.dropped
                children.extend(transaction.order(order.identity) for order in step_commit.orders)
            for account_id in sorted({item.request.account_id for item in batch.decisions}):
                self.admission.require_reissue_safe(transaction, account_id, batch.at)
            # Admission-time risk alone cannot authorize a later send of this batch's orders.
            for child in children:
                reason = self.admission.send_reason(transaction, child.order, batch.at)
                if reason is not None:
                    raise ValueError(reason)
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
            batch_ids = {child.order.identity for child in children}
            portfolio_result = PortfolioCommit(
                status="committed",
                reason="reserved"
                if parents
                else "unroutable_residual"
                if any(item.child_order_id in batch_ids for item in residuals)
                else "internal_cross"
                if crossed
                else "no_intent"
                if all(item.request.decision.intent is None for item in batch.decisions)
                else "target_matched",
                children=committed_children,
                net_orders=tuple(parents),
                internal_fill_ids=crossed,
                residuals=residuals,
            )
            saved_decisions: tuple[SavedDecision, ...] = tuple(
                SavedDecision(
                    request=item.request,
                    result=StepCommit(
                        status="committed",
                        reason="reserved"
                        if any(
                            child.instance_id == item.request.instance_id
                            and child.order.decision_identity == item.request.decision.identity
                            for child in children
                        )
                        else "no_intent"
                        if item.request.decision.intent is None
                        else "target_matched",
                        orders=tuple(
                            child.order
                            for child in children
                            if child.instance_id == item.request.instance_id
                            and child.order.decision_identity == item.request.decision.identity
                        ),
                        dropped=dropped.get(item.request.decision.identity, ()),
                    ),
                )
                for item in batch.decisions
            )
            transaction.append_decisions(*saved_decisions)
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
                rejected_decisions: tuple[SavedDecision, ...] = tuple(
                    SavedDecision(
                        request=item.request,
                        result=StepCommit(
                            status="rejected",
                            reason=str(error),
                            orders=(),
                        ),
                    )
                    for item in batch.decisions
                )
                transaction.append_decisions(*rejected_decisions)
        transaction.append_batch(SavedPortfolioBatch(batch=batch, result=portfolio_result))
        return portfolio_result

    def stop_instance(
        self, transaction: AccountTransaction, instance_id: str, at: datetime
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
        return self.admission.request_instance_cancels(
            transaction, instance_id, at, label=f"stop:{instance_id}"
        )

    def restart_instance(
        self, transaction: AccountTransaction, instance_id: str, at: datetime
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
        self, transaction: AccountTransaction, account_id: str, at: datetime
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
        transaction: AccountTransaction,
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
                                "internal-cross",
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

    def _exceeded_ceilings(
        self, transaction: AccountTransaction, at: datetime, buyers: set[str]
    ) -> dict[str, str]:
        """Name the ceiling each buying owner now exceeds at current marks."""
        if not buyers:
            return {}
        policy = self.config.budgets
        commitments = self.admission.commitments(transaction, at)
        engine = BudgetEngine()
        reason = engine.recheck(policy, commitments, ())
        if reason is not None:
            raise ValueError(reason)
        exceeded: dict[str, str] = {}
        for buyer in sorted(buyers):
            reason = engine.recheck(policy, commitments, (buyer,))
            if reason is not None:
                exceeded[buyer] = reason
        return exceeded

    def _net_pending(
        self, transaction: AccountTransaction, account_id: str, at: datetime
    ) -> tuple[NetOrder, ...]:
        """Group unassigned compatible children into physical orders.

        A child that cannot be sent now (a stale quote, a limit beyond the price
        bound, or a buy whose owner is over a ceiling at current marks) and a group
        that cannot form a valid physical lot stay reserved as visible
        ``PortfolioResidual`` values.
        """
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
        pending_ids = {child.order.identity for child in pending}
        replaced_parents = {
            parent.order.identity
            for parent in transaction.state.net_orders
            if parent.account_id == account_id
            and parent.order.is_terminal
            and any(allocation.child_order_id in pending_ids for allocation in parent.allocations)
        }
        if replaced_parents:
            # Coordination also reaches this method. It must not bypass the
            # explicit reissue command's reconciliation requirement after a stop.
            outcome_at = max(
                saved.event.at
                for saved in transaction.state.net_events
                if saved.event.order_id in replaced_parents
            )
            reconciled_at = transaction.account(account_id).reconciled_at
            if reconciled_at is None or reconciled_at < outcome_at:
                raise ValueError("reissue_requires_current_reconciliation")
        parents: list[NetOrder] = []
        # A child that cannot be sent now stays a visible, reserved residual and holds
        # back no other order: its quote is stale, its limit drifted beyond the price
        # bound, or it is a buy whose owner, account or the firm is over a ceiling.
        held: dict[str, str] = {}
        for child in pending:
            reason = self.admission.send_reason(transaction, child.order, at)
            if reason is not None:
                held[child.order.identity] = reason
        buys = tuple(
            child
            for child in pending
            if child.order.intent.side == "buy" and child.order.identity not in held
        )
        exceeded = self._exceeded_ceilings(transaction, at, {child.instance_id for child in buys})
        for child in buys:
            if child.instance_id in exceeded:
                held[child.order.identity] = exceeded[child.instance_id]
        residuals = [
            PortfolioResidual(
                account_id=child.account_id,
                instance_id=child.instance_id,
                child_order_id=child.order.identity,
                remaining=child.order.remaining,
                reason=held[child.order.identity],
            )
            for child in pending
            if child.order.identity in held
        ]
        pending = [child for child in pending if child.order.identity not in held]
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
                        "physical-net",
                        account_id,
                        at,
                        tuple(child.order.identity for child in group),
                    )
                )
            ).hexdigest()
            if transaction.find_net_order(parent_id) is not None:
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
