"""Allocate physical account events and costs to reserved strategy children."""

from __future__ import annotations

# standard library imports
import hashlib
from fractions import Fraction

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, Fill
from configuration import AccountConfiguration
from execution.account_admission import AccountAdmission
from execution.account_records import NetAllocation, NetFeeAllocation, NetFeeCorrection, NetOrder
from execution.account_state import _AccountTransaction, _SavedEvent, _SavedNetEvent
from execution.lifecycle import SpotOrderLifecycle
from execution.records import OrderEvent
from financial_units import DecimalGrid, Money, Quantity
from portfolio import ProRataAllocator
from serialization import DomainCodec


class PhysicalAllocation:
    """Own physical lifecycle attribution and append-only fee revisions."""

    def __init__(
        self,
        config: AccountConfiguration,
        codec: DomainCodec,
        admission: AccountAdmission,
    ) -> None:
        """Bind account rules shared with child lifecycle and reconciliation."""
        self.config = config
        self.codec = codec
        self.admission = admission

    def apply_event(
        self, transaction: _AccountTransaction, event: OrderEvent
    ) -> tuple[NetOrder | None, str | None]:
        """Apply one physical fact while durably retaining rejected conflicts."""
        failure: str | None = None
        result: NetOrder | None = None
        for saved in transaction.state.net_events:
            if saved.event.identity == event.identity:
                if saved.event != event:
                    failure = "physical event identity reused with different content"
                    self.record_failed_event(transaction, event)
                    break
                return saved.result, None
        if failure is None:
            for saved in transaction.state.net_events:
                if (
                    event.fill is not None
                    and saved.event.fill is not None
                    and event.fill.identity == saved.event.fill.identity
                ):
                    if event.order_id != saved.event.order_id or event.fill != saved.event.fill:
                        failure = "physical fill identity reused with different economics"
                        self.record_failed_event(transaction, event)
                        break
                    return transaction.net_order(event.order_id), None
        if failure is None:
            parent = transaction.net_order(event.order_id)
            before = transaction.state
            try:
                result, fill_ids, fee_ids, fee_allocations = self._apply_attribution(
                    transaction, parent, event
                )
            except ValueError as error:
                failure = str(error)
                transaction.state = before
                self.record_failed_event(transaction, event)
                result = parent
            else:
                net_events: tuple[_SavedNetEvent, ...] = (
                    *transaction.state.net_events,
                    _SavedNetEvent(
                        event=event,
                        result=result,
                        child_fill_ids=fill_ids,
                        fee_only_ids=fee_ids,
                        fee_allocations=fee_allocations,
                    ),
                )
                transaction.state = replace(transaction.state, net_events=net_events)
        return result, failure

    def correct_fee(
        self, transaction: _AccountTransaction, correction: NetFeeCorrection
    ) -> NetOrder:
        """Revise one physical fill fee and its child postings atomically."""
        for saved in transaction.state.net_fee_corrections:
            if saved.identity == correction.identity:
                if saved != correction:
                    raise ValueError("physical fee correction identity reused")
                source = next(
                    item
                    for item in transaction.state.net_events
                    if item.event.fill is not None
                    and item.event.fill.identity == correction.physical_fill_id
                )
                return transaction.net_order(source.event.order_id)
        source_index = next(
            (
                index
                for index, item in enumerate(transaction.state.net_events)
                if item.event.fill is not None
                and item.event.fill.identity == correction.physical_fill_id
            ),
            None,
        )
        if source_index is None:
            raise ValueError("unknown physical fill")
        source = transaction.state.net_events[source_index]
        fill = source.event.fill
        if fill is None:
            raise ValueError("physical fill is missing")
        parent = transaction.net_order(source.event.order_id)
        account = transaction.account(parent.account_id)
        if correction.known_at < max(
            fill.filled_at, self.admission.account_time(transaction, account)
        ):
            raise ValueError("physical fee correction clock regressed")
        if correction.corrected_fee.currency != fill.fee.currency:
            raise ValueError("physical fee correction currency differs")
        if not source.fee_allocations:
            raise ValueError("physical fill lacks cost attribution")
        children = tuple(transaction.order(item.child_order_id) for item in source.fee_allocations)
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
                            self.codec.encode_json(
                                (
                                    "new-physical-fee",
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
                                cash=Money(value=value.copy_negate(), currency=fill.fee.currency),
                            )
                        )
                else:
                    next_revision_id = hashlib.sha256(
                        self.codec.encode_json(
                            ("physical-fee-revision", correction.identity, posting_id)
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
                transaction.save_order(
                    replace(child, order=replace(child.order, paid_fee=updated_fee))
                )
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
        transaction.save_net_order(updated_parent)
        transaction.save_account(
            replace(account, ledger=ledger.state, fault="posting_reconciliation")
        )
        revised_allocations: tuple[NetFeeAllocation, ...] = tuple(revised)
        net_events: tuple[_SavedNetEvent, ...] = tuple(
            replace(item, fee_allocations=revised_allocations) if index == source_index else item
            for index, item in enumerate(transaction.state.net_events)
        )
        corrections: tuple[NetFeeCorrection, ...] = (
            *transaction.state.net_fee_corrections,
            correction,
        )
        transaction.state = replace(
            transaction.state,
            net_events=net_events,
            net_fee_corrections=corrections,
        )
        return updated_parent

    def physical_attribution_matches(
        self, transaction: _AccountTransaction, account_id: str
    ) -> bool:
        """Compare physical fills against effective child quantity, cash, and fees."""
        effective = {
            posting.identity: posting
            for posting in AccountLedger(
                transaction.account(account_id).ledger
            ).effective_postings()
        }
        for saved in transaction.state.net_events:
            if (
                saved.event.fill is None
                or transaction.net_order(saved.event.order_id).account_id != account_id
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
                    for correction in reversed(transaction.state.net_fee_corrections)
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
        for parent in transaction.state.net_orders:
            if parent.account_id != account_id:
                continue
            attributed = sum(
                (
                    Fraction(allocation.amount.value)
                    for saved in transaction.state.net_events
                    if saved.event.fill is not None
                    and saved.event.order_id == parent.order.identity
                    for allocation in saved.fee_allocations
                ),
                Fraction(0),
            )
            if attributed != Fraction(parent.order.paid_fee.value):
                return False
        return True

    def record_failed_event(self, transaction: _AccountTransaction, event: OrderEvent) -> None:
        """Retain one rejected physical fact and durably fence its accounts."""
        failed_net_events = transaction.state.failed_net_events
        if event not in failed_net_events:
            failed_net_events = (*failed_net_events, event)
        for account_id in self.admission.failed_net_event_account_ids(transaction, event):
            transaction.save_account(
                replace(transaction.account(account_id), fault="physical_event_break")
            )
        transaction.state = replace(transaction.state, failed_net_events=failed_net_events)

    def _apply_attribution(
        self, transaction: _AccountTransaction, parent: NetOrder, event: OrderEvent
    ) -> tuple[
        NetOrder,
        tuple[str, ...],
        tuple[str, ...],
        tuple[NetFeeAllocation, ...],
    ]:
        """Apply one parent lifecycle fact and conservatively attributed children."""
        account = transaction.account(parent.account_id)
        if event.at < self.admission.account_time(transaction, account):
            raise ValueError("physical event knowledge precedes current account state")
        if self.config.mode == "shadow" and event.fill is not None:
            raise ValueError("shadow mode cannot post modeled fills")
        physical = SpotOrderLifecycle(self.admission.limits(parent.order.intent.limit)).transition(
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
            children = tuple(transaction.order(item.child_order_id) for item in allocations)
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
                child = transaction.order(item.child_order_id)
                posting_id: str | None = None
                if quantity:
                    fill_id = hashlib.sha256(
                        self.codec.encode_json(
                            ("allocated-physical-fill", fill.identity, child.order.identity)
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
                    child_result = self.admission.apply_order_event(transaction, child, child_event)
                    saved_events: tuple[_SavedEvent, ...] = (
                        *transaction.state.events,
                        _SavedEvent(event=child_event, result=child_result),
                    )
                    transaction.state = replace(transaction.state, events=saved_events)
                    child_fill_ids.append(fill_id)
                    if fee_part:
                        posting_id = f"fee:{fill_id}"
                elif fee_part:
                    fee_id = hashlib.sha256(
                        self.codec.encode_json(
                            ("allocated-physical-fee", fill.identity, child.order.identity)
                        )
                    ).hexdigest()
                    ledger = AccountLedger(transaction.account(parent.account_id).ledger)
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
                    transaction.save_account(
                        replace(transaction.account(parent.account_id), ledger=ledger.state)
                    )
                    transaction.save_order(
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
                child = transaction.order(allocation.child_order_id)
                if (
                    child.instance_id in transaction.state.stopped_instances
                    and not child.order.is_terminal
                ):
                    transaction.save_order(
                        replace(child, order=replace(child.order, status="cancelled"))
                    )
        transaction.save_net_order(updated_parent)
        return (
            updated_parent,
            tuple(child_fill_ids),
            tuple(fee_only_ids),
            tuple(fee_allocations),
        )
