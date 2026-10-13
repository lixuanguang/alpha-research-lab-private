"""Match public paper quotes inside the authoritative shared account transaction."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger, EffectiveAccountPosting
from configuration import AccountConfiguration, PaperExecutionScenario
from execution.account_admission import AccountAdmission
from execution.account_allocation import PhysicalAllocation
from execution.account_records import (
    AccountPaperBinding,
    AccountPaperCost,
    AccountPaperFill,
    AccountPaperTrace,
    AccountQuote,
    PaperMarketOutcome,
)
from execution.account_replacement import PaperReplacements
from execution.account_state import AccountStateStore, AccountTransaction, _AccountSnapshot
from execution.paper import PaperMarket, PaperMatchEvaluator
from execution.paper_authority import PaperAuthority, PaperOwner
from execution.records import OrderEvent, OrderState
from financial_units import Money
from risk import SpotLimits
from serialization import DomainCodec


class AccountPaperMatching:
    """Stage one finite public snapshot with direct and net account effects."""

    def __init__(
        self,
        config: AccountConfiguration,
        store: AccountStateStore,
        codec: DomainCodec,
        admission: AccountAdmission,
        allocation: PhysicalAllocation,
        replacements: PaperReplacements,
        *,
        owner: PaperOwner | None,
        clock: Callable[[], datetime],
    ) -> None:
        """Reuse the account's serialized risk, attribution and replacement owners."""
        self.config = config
        self.store = store
        self.codec = codec
        self.admission = admission
        self.allocation = allocation
        self.replacements = replacements
        self.owner, self.clock = owner, clock
        # Per account: last committed fill-bearing trace sequence read, its child fill
        # events and physical fill identities. Committed traces only grow, by sequence.
        self._trace_facts: dict[str, tuple[int, tuple[OrderEvent, ...], frozenset[str]]] = {}

    def bind(self, account_id: str, scenario: PaperExecutionScenario) -> None:
        """Pin a venue/instrument scenario before its first account order."""
        with self.store.write() as transaction:
            if self.owner is not None:
                PaperAuthority.require_owner(
                    transaction,
                    account_id,
                    self.owner,
                    at=self.clock(),
                    new_exposure=False,
                )
            self.bind_transaction(transaction, account_id, scenario)

    def bind_transaction(
        self,
        transaction: AccountTransaction,
        account_id: str,
        scenario: PaperExecutionScenario,
    ) -> None:
        """Stage immutable matching assumptions together with a disabled deployment."""
        self._require_binding_mode()
        scenario.__post_init__()
        limits = self._limits(scenario)
        if scenario.adverse.per != limits.lot.dimension:
            raise ValueError("paper adverse price instrument differs")
        PaperMatchEvaluator(scenario, lot=limits.lot, tick=limits.tick)
        transaction.account(account_id)
        existing = self._binding(transaction, account_id, scenario)
        if existing is not None:
            if existing.scenario != scenario:
                raise ValueError("paper scenario changed after binding")
            return
        has_direct_orders = any(
            item.account_id == account_id
            and item.order.intent.quantity.dimension.instrument_id == scenario.instrument_id
            for item in transaction.state.orders
        )
        has_net_orders = any(
            item.account_id == account_id
            and item.order.intent.quantity.dimension.instrument_id == scenario.instrument_id
            for item in transaction.state.net_orders
        )
        if has_direct_orders or has_net_orders:
            raise ValueError("paper scenario must be bound before order admission")
        bindings: tuple[AccountPaperBinding, ...] = (
            *transaction.state.paper_bindings,
            AccountPaperBinding(account_id=account_id, scenario=scenario),
        )
        transaction.state = replace(
            transaction.state,
            paper_bindings=bindings,
        )

    def trace(
        self, account_id: str, market_identity: str, *, snapshot: _AccountSnapshot | None = None
    ) -> AccountPaperTrace | None:
        """Read the account's committed or failed trace of one market identity, if any."""
        if (
            type(account_id) is not str
            or not account_id
            or type(market_identity) is not str
            or not market_identity
        ):
            raise ValueError("paper trace lookup requires account and market identities")
        if snapshot is None:
            with self.store.snapshot() as fresh:
                return self.trace(account_id, market_identity, snapshot=fresh)
        if account_id not in {account.ledger.account_id for account in snapshot.state.accounts}:
            raise ValueError("unknown account")
        return snapshot.find_trace(market_identity, account_id=account_id)

    def apply(
        self, account_id: str, market: PaperMarket, scenario: PaperExecutionScenario
    ) -> PaperMarketOutcome:
        """Observe one eligible book's ask as valuation and match it, in one transaction.

        Under the owner fence and the bound scenario, the market identity is resolved
        against the whole committed history before any effect. A market this account
        already applied is an exact retry: it returns the saved outcome and writes
        nothing, so valuation, liquidity, accounting and checkpoints are unchanged.
        The same identity with other input, in any account, is refused. Only a new
        market is observed and, in paper mode, matched. Shadow mode keeps no trace and
        only observes; observing the identical quote at the valuation's clock again
        changes nothing, and any other quote at or before it is refused.

        Raises:
            ValueError: The owner, scenario, identity, clock or freshness is refused,
                or the book's modeled effect was refused; that failure is committed as
                the market's trace first, and an exact retry raises it again.
        """
        self._require_binding_mode()
        market.__post_init__()
        scenario.__post_init__()
        limits = self._limits(scenario)
        if market.bid.per != limits.lot.dimension:
            raise ValueError("paper market instrument differs from scenario")
        valuation = AccountQuote(price=market.ask, at=market.at)
        trace: AccountPaperTrace | None = None
        failure: str | None = None
        with self.store.write() as transaction:
            activation = PaperAuthority.require_owner(
                transaction, account_id, self.owner, at=self.clock(), new_exposure=False
            )
            if activation is not None and scenario not in activation.deployment.scenarios:
                raise ValueError("paper_scenario_incompatible")
            transaction.account(account_id)
            binding = self._binding(transaction, account_id, scenario)
            if binding is None:
                raise ValueError("paper scenario is not bound")
            if binding.scenario != scenario:
                raise ValueError("paper scenario changed after binding")
            if self.config.mode == "shadow":
                self.admission.observe_quote(transaction, valuation)
            else:
                trace = self._saved_trace(transaction, account_id, market, scenario)
                if trace is None:
                    if activation is not None:
                        now = self.clock()
                        if market.at > now or now - market.at > timedelta(
                            microseconds=self.config.budgets.max_quote_age_us
                        ):
                            raise ValueError("paper_market_stale_or_future")
                    # A replacement due before this book is sent first, so the book
                    # can fill it. Matching never reads valuation, so the effects are
                    # the same in either order; matching first keeps its ordering
                    # refusals first.
                    self.replacements.settle(transaction, market.at)
                    trace, failure = self._match_new(transaction, account_id, binding, market)
                    self.admission.observe_quote(transaction, valuation)
                elif trace.status == "failed":
                    failure = trace.reason
        if failure is not None:
            raise ValueError(f"account blocked: {failure}")
        return PaperMarketOutcome(
            account_id=account_id,
            market_identity=market.identity,
            trace_sha256=(
                None if trace is None else hashlib.sha256(self.codec.encode_json(trace)).hexdigest()
            ),
        )

    @staticmethod
    def _saved_trace(
        transaction: AccountTransaction,
        account_id: str,
        market: PaperMarket,
        scenario: PaperExecutionScenario,
    ) -> AccountPaperTrace | None:
        """Resolve a market identity against all history before any new effect.

        Every trace of one venue market identity holds the same input bytes, so a
        reused identity with other input is refused wherever it was first applied.
        """
        prior = transaction.find_trace(
            market.identity, venue=scenario.venue, instrument_id=scenario.instrument_id
        )
        if prior is None:
            return None
        if prior.market != market:
            raise ValueError("paper market identity reused with different input")
        saved = (
            prior
            if prior.account_id == account_id
            else transaction.find_trace(
                market.identity,
                account_id=account_id,
                venue=scenario.venue,
                instrument_id=scenario.instrument_id,
            )
        )
        if saved is not None and saved.scenario != scenario:
            raise ValueError("paper scenario changed after binding")
        return saved

    def _committed_trace_facts(
        self, account_id: str, snapshot: _AccountSnapshot
    ) -> tuple[tuple[OrderEvent, ...], frozenset[str]]:
        """Collect committed traces' child fill events and physical fill identities.

        Only fill-bearing traces carry these facts, and the journal indexes them, so a
        cold read decodes those traces alone, never the whole trace history. Each call
        then decodes only fill-bearing traces committed since the previous one. Traces
        staged in a write transaction follow, in commit order.
        """
        # Sequences start at zero, so nothing has been read before -1.
        last, known, seen = self._trace_facts.get(account_id, (-1, (), frozenset()))
        events, identities = list(known), set(seen)
        for sequence, trace in snapshot.iter_committed_filled_traces_after(account_id, last):
            self._add_trace_facts(trace, events, identities)
            last = sequence
        self._trace_facts[account_id] = (last, tuple(events), frozenset(identities))
        for trace in snapshot.state.paper_traces:
            if trace.account_id == account_id:
                self._add_trace_facts(trace, events, identities)
        return tuple(events), frozenset(identities)

    @staticmethod
    def _add_trace_facts(
        trace: AccountPaperTrace, events: list[OrderEvent], identities: set[str]
    ) -> None:
        """Add one committed trace's child fill events and physical fill identities."""
        if not trace.filled:
            return
        events.extend(trace.child_fill_events)
        identities.update(
            event.fill.identity for event in trace.physical_events if event.fill is not None
        )

    def report_facts(
        self, account_id: str, *, snapshot: _AccountSnapshot | None = None
    ) -> tuple[tuple[AccountPaperFill, ...], tuple[AccountPaperCost, ...]]:
        """Project current owned fills and effective cost links from retained facts."""
        if snapshot is None:
            with self.store.snapshot() as fresh:
                return self.report_facts(account_id, snapshot=fresh)
        state = snapshot.state
        account = next(
            (item for item in state.accounts if item.ledger.account_id == account_id), None
        )
        if account is None:
            raise ValueError("unknown account")
        effective = {
            posting.identity: posting
            for posting in AccountLedger(account.ledger).effective_postings()
        }
        trace_events, physical_fill_ids = self._committed_trace_facts(account_id, snapshot)
        orders = {item.order.identity: item for item in state.orders}
        fills: list[AccountPaperFill] = []
        for event in trace_events:
            fill = event.fill
            if fill is None:
                raise AssertionError("paper trace child fill is missing")
            tagged = orders.get(event.order_id)
            posted = effective.get(fill.identity)
            if (
                tagged is None
                or tagged.account_id != account_id
                or posted is None
                or posted.kind != "fill"
                or posted.quantity != fill.quantity
                or posted.price != fill.effective
            ):
                raise ValueError("modeled paper fill differs from effective account posting")
            fills.append(
                AccountPaperFill(
                    instance_id=tagged.instance_id,
                    order_id=event.order_id,
                    fill=fill,
                )
            )
        costs: list[AccountPaperCost] = []
        linked_fills: set[str] = set()
        fill_orders = {
            item.event.fill.identity: item.event.order_id
            for item in state.events
            if item.event.fill is not None
        }
        for saved in state.net_events:
            physical_fill = saved.event.fill
            if physical_fill is None or physical_fill.identity not in physical_fill_ids:
                continue
            child_by_order = {
                fill_orders[fill_id]: fill_id
                for fill_id in saved.child_fill_ids
                if fill_id in fill_orders
            }
            for allocation in saved.fee_allocations:
                source_id = child_by_order.get(allocation.child_order_id, physical_fill.identity)
                if allocation.posting_id is None and source_id == physical_fill.identity:
                    continue
                if source_id in child_by_order.values():
                    linked_fills.add(source_id)
                costs.append(
                    self._cost(effective, allocation.posting_id, source_id, physical_fill.fee)
                )
        for item in fills:
            fill = item.fill
            if fill.identity in linked_fills:
                continue
            direct_cost_id = f"fee:{fill.identity}"
            costs.append(self._cost(effective, direct_cost_id, fill.identity, fill.fee))
        return tuple(fills), tuple(costs)

    def _match_new(
        self,
        transaction: AccountTransaction,
        account_id: str,
        binding: AccountPaperBinding,
        market: PaperMarket,
    ) -> tuple[AccountPaperTrace, str | None]:
        """Apply a never-seen quote or retain one rejected modeled economic fact."""
        scenario = binding.scenario
        latest_at = transaction.latest_trace_market_at(account_id, scenario.instrument_id)
        if latest_at is not None and market.at < latest_at:
            raise ValueError("paper market availability regressed")
        account_view = transaction.account(account_id)
        if account_view.fault is not None:
            raise ValueError("paper account is faulted")
        if account_view.reconciled_at is None:
            raise ValueError("paper account requires an opening reconciliation")
        if market.at < self.admission.account_time(transaction, account_view):
            raise ValueError("paper market precedes current account knowledge")
        # Only open orders can match. A market without a trace has no posted
        # facts yet (traces commit with their effects), so terminal orders and
        # their history cannot change this projection and are not re-validated.
        direct = tuple(
            item.order
            for item in transaction.state.orders
            if item.account_id == account_id
            and item.context is None
            and not item.order.is_terminal
            and item.order.intent.quantity.dimension.instrument_id == scenario.instrument_id
        )
        net = tuple(
            item.order
            for item in transaction.state.net_orders
            if item.account_id == account_id
            and not item.order.is_terminal
            and item.order.intent.quantity.dimension.instrument_id == scenario.instrument_id
        )
        if any(
            item.context.venue.casefold() != scenario.venue
            for item in transaction.state.net_orders
            if item.account_id == account_id
            and item.order.intent.quantity.dimension.instrument_id == scenario.instrument_id
        ):
            raise ValueError("paper physical order venue differs from scenario")
        ordered: list[OrderState] = [*direct, *net]
        ordered.sort(key=self._order_sort_key)
        orders: tuple[OrderState, ...] = tuple(ordered)
        net_ids = {item.identity for item in net}
        order_ids = {item.identity for item in orders}
        event_history: list[OrderEvent] = [
            item.event for item in transaction.state.events if item.event.order_id in order_ids
        ]
        event_history.extend(
            item.event for item in transaction.state.net_events if item.event.order_id in order_ids
        )
        event_history.sort(key=self._event_sort_key)
        prior_events: tuple[OrderEvent, ...] = tuple(event_history)
        limits = self._limits(scenario)
        projection = PaperMatchEvaluator(scenario, lot=limits.lot, tick=limits.tick).project(
            market,
            account_id=account_id,
            orders=orders,
            prior_events=prior_events,
            liquidity=binding.liquidity,
            cancel_deadlines={
                item.order_id: item.effective_at
                for item in transaction.state.replacement_deadlines
                if item.order_id in order_ids
            },
            entry_times={
                item.order_id: item.entered_at
                for item in transaction.state.replacement_entries
                if item.order_id in order_ids
            },
        )
        before = transaction.state
        start_event_count = len(before.events)
        failure: str | None = None
        failed_event: OrderEvent | None = None
        for event in projection.events:
            if event.order_id in net_ids:
                _, failure = self.allocation.apply_event(transaction, event)
            else:
                _, failure = self.admission.apply_event(transaction, event)
            if failure is not None:
                failed_event = event
                break
        if failure is not None and failed_event is not None:
            transaction.state = before
            if failed_event.order_id in net_ids:
                self.allocation.record_failed_event(transaction, failed_event)
            else:
                self.admission.record_failed_event(transaction, failed_event)
            physical_events: tuple[OrderEvent, ...] = ()
            child_events: tuple[OrderEvent, ...] = ()
            liquidity = binding.liquidity
        else:
            physical_events = projection.events
            child_events = tuple(
                saved.event
                for saved in transaction.state.events[start_event_count:]
                if saved.event.fill is not None
            )
            liquidity = projection.liquidity
            bindings = tuple(
                replace(item, liquidity=liquidity) if item == binding else item
                for item in transaction.state.paper_bindings
            )
            transaction.state = replace(transaction.state, paper_bindings=bindings)
        trace = AccountPaperTrace(
            account_id=account_id,
            market=market,
            scenario=scenario,
            input_sha256=hashlib.sha256(
                self.codec.encode_json((account_id, market, scenario))
            ).hexdigest(),
            physical_events=physical_events,
            child_fill_events=child_events,
            liquidity=liquidity,
            status="failed" if failure is not None else "committed",
            reason=failure if failure is not None else "matched",
            rejected_event=failed_event,
        )
        transaction.append_trace(trace)
        return trace, failure

    @staticmethod
    def _cost(
        effective: dict[str, EffectiveAccountPosting],
        posting_id: str | None,
        source_fill_id: str,
        original: Money,
    ) -> AccountPaperCost:
        """Resolve a corrected fee by its stable posting identity."""
        if posting_id is not None and posting_id in effective:
            posting = effective[posting_id]
            if posting.kind != "fee":
                raise ValueError("paper fee source differs from effective posting")
            return AccountPaperCost(
                posting_id=posting_id,
                source_fill_id=source_fill_id,
                amount=Money(
                    value=posting.cash.value.copy_negate(), currency=posting.cash.currency
                ),
            )
        return AccountPaperCost(
            posting_id=None,
            source_fill_id=source_fill_id,
            amount=Money(value=Decimal(0), currency=original.currency),
        )

    def _binding(
        self,
        transaction: AccountTransaction,
        account_id: str,
        scenario: PaperExecutionScenario,
    ) -> AccountPaperBinding | None:
        """Find the one pinned profile for this account and instrument."""
        return next(
            (
                item
                for item in transaction.state.paper_bindings
                if item.account_id == account_id
                and item.scenario.instrument_id == scenario.instrument_id
            ),
            None,
        )

    @staticmethod
    def _order_sort_key(order: OrderState) -> tuple[datetime, str]:
        """Prioritize older admitted physical orders with stable identity ties."""
        return order.decision_at, order.identity

    @staticmethod
    def _event_sort_key(event: OrderEvent) -> tuple[datetime, str]:
        """Replay physical observations in one deterministic knowledge order."""
        return event.at, event.identity

    def _limits(self, scenario: PaperExecutionScenario) -> SpotLimits:
        """Require an instrument configured under the independent risk authority."""
        limits = next(
            (
                item
                for item in self.config.instruments
                if item.maximum.dimension.instrument_id == scenario.instrument_id
            ),
            None,
        )
        if limits is None:
            raise ValueError("paper scenario instrument is not configured")
        # Admission sized every reserve for the configured worst case.
        if scenario.fee_rate > self.config.fee_rate(scenario.instrument_id).rate:
            raise ValueError("paper scenario fee rate exceeds the configured worst case")
        return limits

    def _require_binding_mode(self) -> None:
        """Allow immutable source assumptions for paper and non-filling shadow."""
        if self.config.mode not in ("paper", "shadow"):
            raise ValueError("paper scenario requires paper or shadow account mode")
