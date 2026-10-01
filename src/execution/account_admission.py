"""Own account admission, direct lifecycle effects, and reconciliation rules."""

from __future__ import annotations

# standard library imports
import hashlib
import operator
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import compress
from typing import TYPE_CHECKING

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountSnapshot
from configuration import AccountConfiguration
from execution.account_records import (
    AccountControlResult,
    AccountDecision,
    AccountObservation,
    AccountQuote,
    AccountView,
    NativeFill,
    NetOrder,
    PhysicalAccountObservation,
    TaggedOrder,
)
from execution.account_state import (
    _AccountTransaction,
    _InstanceControl,
    _PhysicalReconciliation,
    _Reconciliation,
    _SavedEvent,
    _SavedNetEvent,
)
from execution.lifecycle import SpotOrderLifecycle
from execution.records import OrderEvent, OrderState, StepCommit
from financial_units import Dimension, Money, Price, Quantity
from portfolio import PortfolioContext
from risk import BudgetEngine, BudgetRequest, ExposureCommitment, SpotLimits
from serialization import DomainCodec
from strategies import ExposureIntent, OrderIntent, TargetIntent

if TYPE_CHECKING:
    # project library imports
    from execution.account_allocation import PhysicalAllocation


type _Clocks = tuple[tuple[str, datetime], ...]


def _replaced(kept: tuple[object, ...], items: tuple[object, ...]) -> Iterator[int]:
    """Yield the positions of ``kept`` whose item ``items`` holds a different object."""
    changed: Iterable[bool] = map(operator.is_not, kept, items)
    return compress(range(len(kept)), changed)


class _Owners:
    """Map order identities to their accounts, extending the map as orders append.

    An order keeps its identity and account when saved in place, so a new tuple
    that only appends, or replaces orders with the same identity and account,
    extends the same map. Any other change builds a new map.
    """

    def __init__(self) -> None:
        """Start with no orders."""
        self._orders: tuple[TaggedOrder | NetOrder, ...] = ()
        self.accounts: dict[str, str] = {}

    def of(self, orders: tuple[TaggedOrder, ...] | tuple[NetOrder, ...]) -> dict[str, str]:
        """Return the identity-to-account map of exactly these orders."""
        if orders is self._orders:
            return self.accounts
        kept = self._orders
        if len(orders) >= len(kept) and all(
            (kept[index].order.identity, kept[index].account_id)
            == (orders[index].order.identity, orders[index].account_id)
            for index in _replaced(kept, orders)
        ):
            appended = orders[len(kept) :]
        else:
            self.accounts, appended = {}, orders
        for item in appended:
            self.accounts[item.order.identity] = item.account_id
        self._orders = orders
        return self.accounts


class _Latest[T]:
    """Keep each account's latest clock over one history tuple, extending on appends.

    ``pairs`` gives the (account, clock) pairs one item contributes, given the
    ``context`` objects it depends on. A new tuple that keeps the cached items,
    or replaces some with items contributing the same pairs, and appends more
    folds only the appended items, while the context objects are unchanged.
    Anything else folds the whole tuple again.
    """

    def __init__(self) -> None:
        """Start with no items."""
        self._items: tuple[T, ...] = ()
        self._context: tuple[object, ...] = ()
        self._latest: dict[str, datetime] = {}

    def of(
        self,
        items: tuple[T, ...],
        pairs: Callable[[T], Iterable[tuple[str, datetime]]],
        context: tuple[object, ...] = (),
    ) -> dict[str, datetime]:
        """Return each account's latest clock contributed by exactly these items."""
        same_context = len(context) == len(self._context) and all(
            map(operator.is_, context, self._context)
        )
        if items is self._items and same_context:
            return self._latest
        kept = self._items
        if (
            same_context
            and len(items) >= len(kept)
            and all(
                tuple(pairs(kept[index])) == tuple(pairs(items[index]))
                for index in _replaced(kept, items)
            )
        ):
            latest, appended = dict(self._latest), items[len(kept) :]
        else:
            latest, appended = {}, items
        for item in appended:
            for account_id, at in pairs(item):
                prior = latest.get(account_id)
                if prior is None or at > prior:
                    latest[account_id] = at
        self._items, self._context, self._latest = items, context, latest
        return latest


class AccountAdmission:
    """Evaluate authoritative risk and reconcile direct account effects."""

    def __init__(self, config: AccountConfiguration, codec: DomainCodec) -> None:
        """Bind immutable configuration and the journal's canonical codec."""
        self.config = config
        self.codec = codec
        # Per-account latest history clocks, extended as states append; see _history_times.
        self._order_owners, self._net_owners = _Owners(), _Owners()
        self._order_clocks: _Latest[TaggedOrder] = _Latest()
        self._event_clocks: _Latest[_SavedEvent] = _Latest()
        self._failed_event_clocks: _Latest[OrderEvent] = _Latest()
        self._net_order_clocks: _Latest[NetOrder] = _Latest()
        self._net_event_clocks: _Latest[_SavedNetEvent] = _Latest()
        self._failed_net_event_clocks: _Latest[OrderEvent] = _Latest()
        self._failed_native_fill_clocks: _Latest[NativeFill] = _Latest()
        self._instance_control_clocks: _Latest[_InstanceControl] = _Latest()
        self._account_control_clocks: _Latest[AccountControlResult] = _Latest()

    def admit(
        self,
        transaction: _AccountTransaction,
        request: AccountDecision,
        *,
        context: PortfolioContext | None = None,
        crossing_ids: set[str] | None = None,
        protective: bool = False,
    ) -> StepCommit:
        """Evaluate a decision against authoritative holdings and firm commitments."""
        account = transaction.account(request.account_id)
        if protective:
            self._require_protective_sell(transaction, request, context, crossing_ids)
        if account.phase != "running" and not protective:
            raise ValueError("account_operationally_blocked")
        if account.operator_block or account.fault:
            raise ValueError(account.operator_block or account.fault or "account_blocked")
        if request.instance_id in transaction.state.stopped_instances and not protective:
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
            # A risk-reducing sell is never refused over fee sizing; a fee above
            # its reserve is posted from free cash instead. The paper model's own
            # half-even rounding bounds paper fees (and shadow, which mirrors paper
            # admission); a venue's unknown rounding keeps the per-lot bound.
            rate = self.config.fee_rate(intent.quantity.dimension.instrument_id)
            reserve = (
                rate.minimum_reserve
                if self.config.mode == "venue_test"
                else rate.paper_minimum_reserve
            )
            if not protective and Fraction(request.maximum_fee.value) < reserve(
                intent.quantity, intent.limit, limits.lot
            ):
                raise ValueError("fee_reserve_below_worst_case")
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
                        "account-child",
                        request.account_id,
                        request.instance_id,
                        request.decision.identity,
                        leg_name,
                    )
                )
            ).hexdigest()
            if transaction.find_order(identity) is not None:
                raise ValueError("order_identity_collision")
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

    def _require_protective_sell(
        self,
        transaction: _AccountTransaction,
        request: AccountDecision,
        context: PortfolioContext | None,
        crossing_ids: set[str] | None,
    ) -> None:
        """Bound every operational bypass to uncommitted owned spot inventory."""
        intent = request.decision.intent
        if self.config.mode != "paper":
            raise ValueError("protective_admission_requires_paper_mode")
        if (
            context is not None
            or crossing_ids is not None
            or type(intent) is not OrderIntent
            or intent.side != "sell"
            or intent.time_in_force != "ioc"
            or intent.quantity.dimension != request.quote.price.per
        ):
            raise ValueError("protective_admission_requires_direct_sell")
        owned = AccountLedger(transaction.account(request.account_id).ledger).snapshot(
            instance_id=request.instance_id
        )
        holding = next(
            (
                position
                for position in owned.positions
                if position.dimension == intent.quantity.dimension
            ),
            Quantity(value=Decimal(0), dimension=intent.quantity.dimension),
        )
        attached = {
            allocation.child_order_id
            for parent in transaction.state.net_orders
            if parent.account_id == request.account_id and not parent.order.is_terminal
            for allocation in parent.allocations
        }
        committed = sum(
            (
                tagged.order.remaining.value
                for tagged in transaction.state.orders
                if tagged.account_id == request.account_id
                and tagged.instance_id == request.instance_id
                and tagged.order.intent.side == "sell"
                and tagged.order.intent.quantity.dimension == intent.quantity.dimension
                and (not tagged.order.is_terminal or tagged.order.identity in attached)
            ),
            Decimal(0),
        )
        if intent.quantity.value + committed > holding.value:
            raise ValueError("reduction_exceeds_uncommitted_owned_inventory")

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
                and not self.failed_posting_matches_accepted_fact(account, posting)
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
                and not self.failed_net_event_matches_accepted_fact(transaction, failed)
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

    def reconcile_physical(
        self,
        transaction: _AccountTransaction,
        observation: PhysicalAccountObservation,
        allocation: PhysicalAllocation,
    ) -> bool:
        """Compare independently supplied venue wallet totals and physical orders.

        Wallet evidence has no local posting or strategy fill identifiers. Those
        stay a separate internal consistency check, never invented source facts.
        """
        for saved in transaction.state.physical_reconciliations:
            if saved.observation.identity == observation.identity:
                if saved.observation != observation:
                    raise ValueError("physical observation identity reused")
                return saved.matched
        account = transaction.account(observation.account_id)
        ledger = AccountLedger(account.ledger)
        snapshot = ledger.snapshot()
        authorized_instruments = {
            instrument_id
            for owner in self.config.budgets.instances
            if owner.account_id == observation.account_id
            for instrument_id in owner.instruments
        }
        expected_dimensions = {
            limits.lot.dimension
            for limits in self.config.instruments
            if limits.lot.dimension.instrument_id in authorized_instruments
        }
        mappings = dict(observation.instrument_currencies)
        if set(mappings) != expected_dimensions:
            raise ValueError("physical observation lacks configured instrument mapping")
        account_order_ids = {
            tagged.order.identity
            for tagged in transaction.state.orders
            if tagged.account_id == observation.account_id
        } | {
            parent.order.identity
            for parent in transaction.state.net_orders
            if parent.account_id == observation.account_id
        }
        for source in transaction.state.native_fills:
            request = source.request
            if (
                request.order_id in account_order_ids
                and request.base_currency != mappings[request.quantity.dimension]
            ):
                raise ValueError("physical observation changes a native base currency")
        accepted_native_ids = {
            source.request.identity
            for source in transaction.state.native_fills
            if source.request.order_id in account_order_ids
        }
        wallet: dict[object, Fraction] = {
            amount.currency: Fraction(amount.value) for amount in snapshot.cash
        }
        for position in snapshot.positions:
            currency = mappings[position.dimension]
            wallet[currency] = wallet.get(currency, Fraction(0)) + Fraction(position.value)
        observed = {amount.currency: Fraction(amount.value) for amount in observation.balances}
        expected_nonzero = {unit: value for unit, value in wallet.items() if value}
        observed_nonzero = {unit: value for unit, value in observed.items() if value}
        open_orders = (
            *(
                tagged.order
                for tagged in transaction.state.orders
                if tagged.account_id == observation.account_id
                and tagged.context is None
                and not tagged.order.is_terminal
                and tagged.order.status != "intent"
            ),
            *(
                parent.order
                for parent in transaction.state.net_orders
                if parent.account_id == observation.account_id
                and not parent.order.is_terminal
                and parent.order.status != "intent"
            ),
        )
        latest = self.account_time(transaction, account)
        matched = (
            observation.at >= latest
            and (account.reconciled_at is None or observation.at >= account.reconciled_at)
            and expected_nonzero == observed_nonzero
            and {order.identity: order for order in open_orders}
            == {order.identity: order for order in observation.open_orders}
            and not any(order.status == "unknown" for order in open_orders)
            and allocation.physical_attribution_matches(transaction, observation.account_id)
            and self._native_attribution_matches(transaction, observation.account_id)
            and not any(
                posting.account_id == observation.account_id
                and not self.failed_posting_matches_accepted_fact(account, posting)
                for posting in transaction.state.failed_postings
            )
            and not any(
                observation.account_id in self.failed_event_account_ids(transaction, event)
                and (
                    self.failed_event_conflicts_with_accepted_fact(transaction, event)
                    or (event.fill is not None and event.fill.identity not in snapshot.fill_ids)
                )
                for event in transaction.state.failed_events
            )
            and not any(
                observation.account_id in self.failed_net_event_account_ids(transaction, event)
                and not self.failed_net_event_matches_accepted_fact(transaction, event)
                for event in transaction.state.failed_net_events
            )
            and not any(
                fill.order_id in account_order_ids or fill.identity in accepted_native_ids
                for fill in transaction.state.failed_native_fills
            )
        )
        if matched:
            try:
                self.require_funded(transaction, observation.account_id)
            except ValueError:
                matched = False
        transaction.save_account(
            replace(
                account,
                fault=None if matched else "account_break",
                reconciled_at=observation.at if matched else account.reconciled_at,
            )
        )
        physical_reconciliations: tuple[_PhysicalReconciliation, ...] = (
            *transaction.state.physical_reconciliations,
            _PhysicalReconciliation(observation=observation, matched=matched),
        )
        transaction.state = replace(
            transaction.state,
            physical_reconciliations=physical_reconciliations,
        )
        return matched

    def _native_attribution_matches(
        self, transaction: _AccountTransaction, account_id: str
    ) -> bool:
        """Check every venue trade's native cost against effective owned postings."""
        effective = {
            posting.identity: posting
            for posting in AccountLedger(
                transaction.account(account_id).ledger
            ).effective_postings()
        }
        for saved in transaction.state.native_fills:
            request = saved.request
            tagged = transaction.find_order(request.order_id)
            parent = transaction.find_net_order(request.order_id)
            is_direct = tagged is not None and tagged.account_id == account_id
            is_net = parent is not None and parent.account_id == account_id
            if not is_direct and not is_net:
                continue
            sources: list[OrderEvent] = []
            for saved_event in transaction.state.events:
                if (
                    saved_event.event.fill is not None
                    and saved_event.event.fill.identity == request.identity
                ):
                    sources.append(saved_event.event)
            for saved_net_event in transaction.state.net_events:
                if (
                    saved_net_event.event.fill is not None
                    and saved_net_event.event.fill.identity == request.identity
                ):
                    sources.append(saved_net_event.event)
            if len(sources) != 1:
                return False
            source = sources[0]
            fill = source.fill
            if fill is None:
                return False
            expected_quote_fee = (
                request.fee.value
                if request.fee.currency == request.price.currency and request.fee.value > 0
                else 0
            )
            if (
                source.order_id != request.order_id
                or source.at != request.at
                or fill.filled_at != request.filled_at
                or fill.quantity != request.quantity
                or fill.effective != request.price
                or Fraction(fill.fee.value) != Fraction(expected_quote_fee)
            ):
                return False
            if request.fee.value > 0 and request.fee.currency == request.price.currency:
                if saved.allocations:
                    return False
                if is_direct:
                    posting = effective.get(f"fee:{request.identity}")
                    if (
                        posting is None
                        or posting.kind != "fee"
                        or posting.order_id != request.order_id
                        or posting.cash.currency != request.fee.currency
                        or Fraction(posting.cash.value) != -Fraction(request.fee.value)
                    ):
                        return False
                continue
            if request.fee.value == 0:
                if saved.allocations:
                    return False
                continue
            total = Fraction(0)
            for share in saved.allocations:
                posting = effective.get(share.posting_id)
                if (
                    posting is None
                    or posting.order_id != share.child_order_id
                    or posting.kind != ("fee" if share.amount.value > 0 else "rebate")
                    or posting.cash.currency != share.amount.currency
                    or Fraction(posting.cash.value) != -Fraction(share.amount.value)
                    or (posting.asset_change is not None)
                    != (request.fee.currency == request.base_currency)
                    or (
                        posting.asset_change is not None
                        and posting.asset_change.dimension != request.quantity.dimension
                    )
                ):
                    return False
                total += Fraction(share.amount.value)
            if total != Fraction(request.fee.value):
                return False
        return True

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
                if account.fault or account.reconciled_at is None:
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
        clocks = [
            self.config.opening_at,
            self._history_times(transaction).get(account.ledger.account_id, self.config.opening_at),
        ]
        if account.reconciled_at is not None:
            clocks.append(account.reconciled_at)
        postings = account.ledger.postings
        if postings:
            # Ledgers refuse a posting known before its predecessor, so the last is latest.
            clocks.append(postings[-1].known_at)
        return max(clocks)

    def _history_times(self, transaction: _AccountTransaction) -> dict[str, datetime]:
        """Return every account's latest firm-history clock for the transaction's state.

        Admission asks for account time many times per transaction, and once per
        account, while each step stages a new state that mostly appends history.
        Each history tuple therefore keeps its per-account latest clocks and folds
        only what a new state appended; see ``_Latest``.
        """
        state = transaction.state
        orders = self._order_owners.of(state.orders)
        parents = self._net_owners.of(state.net_orders)
        fields: tuple[dict[str, datetime], ...] = (
            self._order_clocks.of(state.orders, self._decision_clock),
            self._event_clocks.of(
                state.events,
                lambda saved: (
                    (
                        self._owner(orders, saved.event.order_id, "unknown child order"),
                        saved.event.at,
                    ),
                ),
                (orders,),
            ),
            self._failed_event_clocks.of(
                state.failed_events,
                lambda event: (
                    (account_id, event.at)
                    for account_id in self.failed_event_account_ids(transaction, event)
                ),
                (state.events, orders),
            ),
            self._net_order_clocks.of(state.net_orders, self._decision_clock),
            self._net_event_clocks.of(
                state.net_events,
                lambda saved: (
                    (
                        self._owner(parents, saved.event.order_id, "unknown physical order"),
                        saved.event.at,
                    ),
                ),
                (parents,),
            ),
            self._failed_net_event_clocks.of(
                state.failed_net_events,
                lambda event: (
                    (account_id, event.at)
                    for account_id in self.failed_net_event_account_ids(transaction, event)
                ),
                (state.net_events, parents),
            ),
            self._failed_native_fill_clocks.of(
                state.failed_native_fills,
                lambda fill: (
                    (owners[fill.order_id], fill.at)
                    for owners in (orders, parents)
                    if fill.order_id in owners
                ),
                (orders, parents),
            ),
            self._instance_control_clocks.of(
                state.instance_controls,
                lambda control: ((self.instance_account(control.instance_id), control.at),),
            ),
            self._account_control_clocks.of(
                state.account_controls,
                lambda control: (
                    ((control.request.account_id, control.request.at),)
                    if control.status == "applied"
                    else ()
                ),
            ),
        )
        latest: dict[str, datetime] = {}
        for field in fields:
            for account_id, at in field.items():
                prior = latest.get(account_id)
                if prior is None or at > prior:
                    latest[account_id] = at
        return latest

    @staticmethod
    def _decision_clock(item: TaggedOrder | NetOrder) -> _Clocks:
        """Return the account and decision clock an order contributes."""
        return ((item.account_id, item.order.decision_at),)

    @staticmethod
    def _owner(accounts: dict[str, str], order_id: str, missing: str) -> str:
        """Return an order's account from a prebuilt map, failing as the scan did."""
        owner = accounts.get(order_id)
        if owner is None:
            raise ValueError(missing)
        return owner

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

    def failed_posting_matches_accepted_fact(
        self, account: AccountView, posting: AccountPosting
    ) -> bool:
        """Identify a rejected posting whose exact bytes were later accepted."""
        encoded = self.codec.encode_json(posting)
        return any(
            self.codec.encode_json(applied) == encoded for applied in account.ledger.postings
        )

    def failed_net_event_matches_accepted_fact(
        self, transaction: _AccountTransaction, event: OrderEvent
    ) -> bool:
        """Identify a rejected physical fact later accepted without contradiction."""
        if any(
            (saved.event.identity == event.identity and saved.event != event)
            or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
                and (event.order_id != saved.event.order_id or event.fill != saved.event.fill)
            )
            for saved in transaction.state.net_events
        ):
            return False
        return any(
            saved.event == event
            or (
                event.fill is not None
                and saved.event.fill is not None
                and saved.event.fill.identity == event.fill.identity
                and saved.event.order_id == event.order_id
                and saved.event.fill == event.fill
            )
            for saved in transaction.state.net_events
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
