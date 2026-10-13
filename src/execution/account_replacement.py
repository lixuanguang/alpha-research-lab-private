"""Resolve deferred paper replacements at their modeled arrival."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from typing import Literal, Protocol

# third party library imports
from msgspec.structs import replace

# project library imports
from configuration import AccountConfiguration
from execution.account_admission import AccountAdmission
from execution.account_allocation import PhysicalAllocation
from execution.account_portfolio import PortfolioCoordinator
from execution.account_records import (
    AccountDecision,
    AccountQuote,
    PortfolioBatch,
    PortfolioDecision,
    ReplacementDeadline,
    ReplacementEntry,
    ReplacementPlan,
)
from execution.account_state import AccountTransaction, SavedDecision
from execution.paper_authority import PaperAuthority
from execution.records import MarketTouch, OrderDecision, OrderEvent, StepCommit
from portfolio import PortfolioContext
from serialization import DomainCodec


class SendCheck(Protocol):
    """Check authority, deployment context and input currency before staging orders."""

    def __call__(
        self,
        transaction: AccountTransaction,
        request: AccountDecision,
        context: PortfolioContext | None,
        *,
        modelled: bool = False,
    ) -> None:
        """Raise ValueError when the request may not stage orders."""
        ...


class PaperReplacements:
    """Own when a deferred paper decision arrives, and with what account state.

    A plan's cancellation completes (it is released) once no order of its instance
    is live and its ``ready_at`` has passed: at that deadline, or at the account
    knowledge clock if that is later, since nothing may be dated before known
    account facts. It arrives one entry delay after its release, exactly once, and
    is resolved there as a new decision dated at its arrival: target and exposure
    quantities, price, funding, reservations, limits and authority all use the
    account and the latest book known at arrival, and quote freshness is judged
    then. Its orders may fill from their arrival; the entry delay is not applied
    again. The strategy is never evaluated again: the original decision stays
    committed as ``replacement_pending`` with the continuation it saved.

    Journal commands settle releases and arrivals oldest first, a release before an
    arrival at the same time. A book command settles those strictly before its clock,
    so a book at exactly the arrival is known to it and a later book is not; a
    decision command also settles those at its own time, so an arrival precedes a new
    decision at the same timestamp, as in research. Replay and
    restart reach the same outcomes from the same commands. While the account cannot
    admit new exposure for an operational reason, a plan waits at arrival and is
    admitted at the account clock once it can. A selective strategy stop withdraws
    that strategy's intent: its waiting plans end as ``withdrawn_by_instance_stop``
    and a restart does not revive them. An operator account cancel withdraws every
    waiting plan of the account the same way, as ``withdrawn_by_account_cancel``.
    """

    def __init__(
        self,
        config: AccountConfiguration,
        codec: DomainCodec,
        admission: AccountAdmission,
        allocation: PhysicalAllocation,
        portfolio: PortfolioCoordinator,
        require_send: SendCheck,
    ) -> None:
        """Reuse the journal's admission, allocation, portfolio and authority owners."""
        self.config, self.codec = config, codec
        self.admission, self.allocation, self.portfolio = admission, allocation, portfolio
        self.require_send = require_send

    def settle(
        self, transaction: AccountTransaction, before: datetime, *, deciding: bool = False
    ) -> None:
        """Release and resolve every plan whose clock is before ``before``.

        A book command settles only what is strictly earlier, so a book at an arrival's
        own time is matched first and known to it. A decision command, ``deciding``,
        also settles what is due exactly at its time: research processes an arrival
        before a new decision at the same timestamp.
        """
        failed: set[str] = set()
        while True:
            cancellation = self._next_cancellation(transaction, before, deciding, failed)
            due = self._next(transaction, before, deciding=deciding)
            if cancellation is not None and (due is None or cancellation[1] <= due[2]):
                self._cancel(transaction, *cancellation, failed)
            elif due is not None:
                kind, plan, at = due
                if kind == "release":
                    self._release(transaction, plan, at)
                else:
                    self._arrive(transaction, plan, at)
            else:
                break
        deadlines: tuple[ReplacementDeadline, ...] = tuple(
            item
            for item in transaction.state.replacement_deadlines
            if not self._ended(transaction, item.order_id)
        )
        if deadlines != transaction.state.replacement_deadlines:
            transaction.state = replace(transaction.state, replacement_deadlines=deadlines)
        entries: tuple[ReplacementEntry, ...] = tuple(
            item
            for item in transaction.state.replacement_entries
            if not self._ended(transaction, item.order_id)
        )
        if entries != transaction.state.replacement_entries:
            transaction.state = replace(transaction.state, replacement_entries=entries)

    @staticmethod
    def _ended(transaction: AccountTransaction, order_id: str) -> bool:
        """Report whether a strategy or physical order is terminal or gone."""
        child = transaction.find_order(order_id)
        if child is not None:
            return child.order.is_terminal
        parent = transaction.find_net_order(order_id)
        return parent is None or parent.order.is_terminal

    def withdraw(self, transaction: AccountTransaction, instance_id: str, at: datetime) -> None:
        """End a stopped strategy's waiting plans at ``at``, after settling those due before.

        Each withdrawal is retained beside the original decision. Orders already
        admitted keep their reservations until their own terminal outcomes.
        """
        self.settle(transaction, at)
        self._withdraw(
            transaction,
            tuple(
                plan
                for plan in transaction.state.replacement_plans
                if plan.request.instance_id == instance_id
            ),
            at,
            "withdrawn_by_instance_stop",
        )

    def withdraw_account(
        self, transaction: AccountTransaction, account_id: str, at: datetime
    ) -> tuple[str, ...]:
        """End every waiting plan of ``account_id`` at an operator account cancel.

        The caller has already settled what was due strictly before ``at``, so a plan
        due exactly at ``at`` is withdrawn rather than admitted. Each withdrawal is
        retained beside its original decision, and the original decision identities
        are returned in plan order.
        """
        withdrawn = tuple(
            plan
            for plan in transaction.state.replacement_plans
            if plan.request.account_id == account_id
        )
        self._withdraw(transaction, withdrawn, at, "withdrawn_by_account_cancel")
        return tuple(plan.request.decision.identity for plan in withdrawn)

    def _withdraw(
        self,
        transaction: AccountTransaction,
        withdrawn: tuple[ReplacementPlan, ...],
        at: datetime,
        reason: str,
    ) -> None:
        """Remove ``withdrawn`` from the head and retain each one's outcome as ``reason``."""
        if not withdrawn:
            return
        kept: tuple[ReplacementPlan, ...] = tuple(
            plan for plan in transaction.state.replacement_plans if plan not in withdrawn
        )
        transaction.state = replace(transaction.state, replacement_plans=kept)
        for plan in withdrawn:
            self._record(
                transaction,
                self._outcome(transaction, plan, at, plan.request.quote, plan.request.touch),
                "committed",
                reason,
            )

    def _next(
        self, transaction: AccountTransaction, before: datetime, *, deciding: bool
    ) -> tuple[Literal["release", "arrive"], ReplacementPlan, datetime] | None:
        """Return the earliest release or arrival due before ``before``, or at it if ``deciding``.

        Each instance's plans proceed in decision order: only its oldest waiting plan
        can be released or arrive, and it is released only once the instance's orders
        have all ended.
        """
        state = transaction.state
        if not state.replacement_plans:
            return None
        seen: set[str] = set()
        best: tuple[datetime, int, ReplacementPlan] | None = None
        for plan in state.replacement_plans:
            instance = plan.request.instance_id
            if instance in seen:
                continue
            seen.add(instance)
            if plan.released_at is None:
                if any(
                    tagged.instance_id == instance and not tagged.order.is_terminal
                    for tagged in state.orders
                ):
                    continue
                candidate = (self._clock(transaction, plan.ready_at), 0, plan)
            else:
                arrival = plan.released_at + timedelta(microseconds=plan.entry_delay_us)
                if self._withdrawn(plan):
                    candidate = (arrival, 1, plan)
                elif self._paused(transaction, plan):
                    continue
                else:
                    candidate = (self._clock(transaction, arrival), 1, plan)
            if (candidate[0] < before or (deciding and candidate[0] == before)) and (
                best is None or (candidate[0], candidate[1]) < (best[0], best[1])
            ):
                best = candidate
        if best is None:
            return None
        at, phase, plan = best
        return ("release" if phase == 0 else "arrive"), plan, at

    def _next_cancellation(
        self,
        transaction: AccountTransaction,
        before: datetime,
        deciding: bool,
        failed: set[str],
    ) -> tuple[str, datetime, datetime, bool, str] | None:
        """Return the earliest requested paper cancellation whose deadline has passed.

        A requested cancellation takes effect at its request plus the bound cancel
        delay, or at an earlier inherited deadline, whether or not a book arrives then.
        It is dated at that deadline, or at the account's knowledge if that is later.
        An unknown outcome is never ended by elapsed time, and a faulted account, which
        matches no book, ends nothing either. Returns the order, its effective time,
        deadline, whether it is a physical parent, and its account.
        """
        if self.config.mode != "paper":
            return None
        state = transaction.state
        best: tuple[str, datetime, datetime, bool, str] | None = None
        for binding in state.paper_bindings:
            account_id = binding.account_id
            instrument = binding.scenario.instrument_id
            pending: list[tuple[str, bool]] = [
                (tagged.order.identity, False)
                for tagged in state.orders
                if tagged.account_id == account_id
                and tagged.context is None
                and tagged.order.cancel_requested
                and not tagged.order.is_terminal
                and tagged.order.status != "unknown"
                and tagged.order.intent.quantity.dimension.instrument_id == instrument
            ] + [
                (parent.order.identity, True)
                for parent in state.net_orders
                if parent.account_id == account_id
                and parent.order.cancel_requested
                and not parent.order.is_terminal
                and parent.order.status != "unknown"
                and parent.order.intent.quantity.dimension.instrument_id == instrument
            ]
            pending = [item for item in pending if item[0] not in failed]
            account = transaction.account(account_id)
            if not pending or account.fault:
                continue
            identities = {order_id for order_id, _ in pending}
            requested: dict[str, datetime] = {}
            events: list[OrderEvent] = [saved.event for saved in state.events]
            events.extend(saved.event for saved in state.net_events)
            for event in events:
                if event.kind == "cancel_requested" and event.order_id in identities:
                    prior = requested.get(event.order_id)
                    requested[event.order_id] = event.at if prior is None else max(prior, event.at)
            inherited = {item.order_id: item.effective_at for item in state.replacement_deadlines}
            known = self.admission.account_time(transaction, account)
            delay = timedelta(microseconds=binding.scenario.cancel_delay_us)
            for order_id, net in pending:
                request = requested.get(order_id)
                if request is None:
                    continue
                deadline = request + delay
                floor = inherited.get(order_id)
                if floor is not None:
                    deadline = min(deadline, max(floor, request))
                at = max(deadline, known)
                if (at < before or (deciding and at == before)) and (
                    best is None or (at, order_id) < (best[1], best[0])
                ):
                    best = (order_id, at, deadline, net, account_id)
        return best

    def _cancel(
        self,
        transaction: AccountTransaction,
        order_id: str,
        at: datetime,
        deadline: datetime,
        net: bool,
        account_id: str,
        failed: set[str],
    ) -> None:
        """End a requested order at its deadline, retaining the fact before any release."""
        event = OrderEvent(
            identity=hashlib.sha256(
                self.codec.encode_json(
                    ("paper-cancellation-deadline", account_id, order_id, deadline)
                )
            ).hexdigest(),
            order_id=order_id,
            at=at,
            kind="cancelled_on_request",
        )
        before = transaction.state
        if net:
            _, failure = self.allocation.apply_event(transaction, event)
        else:
            _, refusal = self.admission.apply_event(transaction, event)
            failure = refusal
        if failure is None:
            return
        transaction.state = before
        if net:
            self.allocation.record_failed_event(transaction, event)
        else:
            self.admission.record_failed_event(transaction, event)
        failed.add(order_id)

    def _clock(self, transaction: AccountTransaction, due: datetime) -> datetime:
        """Date an event due at ``due`` no earlier than the account facts it follows.

        Another arrival's coordination clock does not postpone it; see
        ``AccountAdmission.decision_knowledge``.
        """
        return max(due, self.admission.decision_knowledge(transaction, due))

    @staticmethod
    def _withdrawn(plan: ReplacementPlan) -> bool:
        """Report whether a later decision's cancellation takes effect before arrival."""
        return (
            plan.released_at is not None
            and plan.superseded_at is not None
            and plan.released_at + timedelta(microseconds=plan.entry_delay_us) >= plan.superseded_at
        )

    @staticmethod
    def _paused(transaction: AccountTransaction, plan: ReplacementPlan) -> bool:
        """Report whether an account stop, block, fault or unknown outcome holds back exposure."""
        account_id = plan.request.account_id
        account = transaction.account(account_id)
        state = transaction.state
        return bool(
            account.phase != "running"
            or account.operator_block
            or account.fault
            or any(
                tagged.account_id == account_id and tagged.order.status == "unknown"
                for tagged in state.orders
            )
            or any(
                parent.account_id == account_id and parent.order.status == "unknown"
                for parent in state.net_orders
            )
        )

    @staticmethod
    def _release(transaction: AccountTransaction, plan: ReplacementPlan, at: datetime) -> None:
        """Record that the plan's replaced work ended at ``at``; it arrives an entry delay later."""
        plans: list[ReplacementPlan] = []
        for item in transaction.state.replacement_plans:
            if item is plan:
                item = replace(item, released_at=at)
            plans.append(item)
        staged: tuple[ReplacementPlan, ...] = tuple(plans)
        transaction.state = replace(transaction.state, replacement_plans=staged)

    def _arriving(
        self, transaction: AccountTransaction, at: datetime
    ) -> tuple[ReplacementPlan, ...]:
        """Return every instance's oldest plan arriving exactly at ``at``, in decision order.

        Plans arriving together are coordinated together, as the decisions that made
        them were, so netting, crossing and per-decision refusal keep their meaning.
        """
        seen: set[str] = set()
        arriving: list[ReplacementPlan] = []
        for plan in transaction.state.replacement_plans:
            instance = plan.request.instance_id
            if instance in seen:
                continue
            seen.add(instance)
            if plan.released_at is None:
                continue
            arrival = plan.released_at + timedelta(microseconds=plan.entry_delay_us)
            if self._withdrawn(plan):
                if arrival == at:
                    arriving.append(plan)
            elif not self._paused(transaction, plan) and self._clock(transaction, arrival) == at:
                arriving.append(plan)
        return tuple(arriving)

    def _arrive(self, transaction: AccountTransaction, plan: ReplacementPlan, at: datetime) -> None:
        """Resolve every plan arriving at ``at`` in decision order: withdraw, end or admit.

        Withdrawn plans, abstentions and plans without a fresh book are recorded alone.
        Consecutive portfolio plans are coordinated in one batch, so netting, crossing
        and per-decision refusal keep their meaning; a direct plan, admitted alone,
        first lets the batch before it reserve, so decision order decides capacity. A
        plan a later decision superseded is coordinated alone: its own cancellation and
        inherited deadline must not end, or extend, another strategy's netted order.
        """
        plans = self._arriving(transaction, at) or (plan,)
        remaining: tuple[ReplacementPlan, ...] = tuple(
            item for item in transaction.state.replacement_plans if item not in plans
        )
        transaction.state = replace(transaction.state, replacement_plans=remaining)
        batched: list[tuple[ReplacementPlan, AccountDecision]] = []
        for item in plans:
            original = item.request
            known = self._known(transaction, item, at)
            send = (
                self._outcome(transaction, item, at, original.quote, original.touch)
                if known is None
                else self._outcome(transaction, item, at, *known)
            )
            if self._withdrawn(item):
                # A later decision's cancellation takes effect before this plan arrives.
                self._record(transaction, send, "committed", "replaced_before_arrival")
            elif original.decision.intent is None:
                self._record(transaction, send, "committed", "no_intent")
            elif known is None:
                # Research records this as the decision's outcome, not an order refusal.
                self._record(transaction, send, "committed", "no_fresh_book_at_arrival")
            elif item.context is None:
                if batched:
                    self._coordinate(transaction, tuple(batched), at)
                    batched = []
                self._admit_direct(transaction, item, send, at)
            else:
                try:
                    self.require_send(transaction, send, item.context, modelled=True)
                except ValueError as error:
                    self._record(transaction, send, "rejected", str(error))
                    continue
                if item.superseded_at is None:
                    batched.append((item, send))
                    continue
                if batched:
                    self._coordinate(transaction, tuple(batched), at)
                    batched = []
                self._coordinate(transaction, ((item, send),), at)
        if batched:
            self._coordinate(transaction, tuple(batched), at)

    def _admit_direct(
        self,
        transaction: AccountTransaction,
        plan: ReplacementPlan,
        send: AccountDecision,
        at: datetime,
    ) -> None:
        """Admit one direct plan at its arrival, recording a refusal on its own."""
        before = transaction.state
        try:
            self.require_send(transaction, send, None, modelled=True)
            result = self.admission.admit(transaction, send, replacing=False)
            transaction.append_decisions(SavedDecision(request=send, result=result))
            PaperAuthority.require_limits(transaction, send.account_id)
        except ValueError as error:
            transaction.state = before
            self._record(transaction, send, "rejected", str(error))
            return
        self._entered(transaction, plan, send, at)

    def _coordinate(
        self,
        transaction: AccountTransaction,
        batched: tuple[tuple[ReplacementPlan, AccountDecision], ...],
        at: datetime,
    ) -> None:
        """Coordinate portfolio plans arriving together as one batch one microsecond later."""
        before = transaction.state
        try:
            self.portfolio.coordinate(
                transaction,
                PortfolioBatch(
                    identity=batched[0][1].decision.identity,
                    at=at + timedelta(microseconds=1),
                    decisions=tuple(
                        PortfolioDecision(request=send, context=plan.context)
                        for plan, send in batched
                        if plan.context is not None
                    ),
                    crossing=transaction.state.crossing_policy or "reject",
                ),
                replacing=False,
            )
            for account_id in sorted({send.account_id for _, send in batched}):
                PaperAuthority.require_limits(transaction, account_id)
        except ValueError as error:
            transaction.state = before
            for _, send in batched:
                self._record(transaction, send, "rejected", str(error))
            return
        for plan, send in batched:
            self._entered(transaction, plan, send, at)

    def _entered(
        self,
        transaction: AccountTransaction,
        plan: ReplacementPlan,
        send: AccountDecision,
        at: datetime,
    ) -> None:
        """Let an arrived plan's orders fill from its arrival; end a superseded one on time."""
        original = plan.request
        coordinated = at + timedelta(microseconds=1)
        children = {
            tagged.order.identity
            for tagged in transaction.state.orders
            if tagged.instance_id == original.instance_id
            and tagged.order.decision_identity == send.decision.identity
        }
        admitted = sorted(
            children
            | {
                parent.order.identity
                for parent in transaction.state.net_orders
                if any(item.child_order_id in children for item in parent.allocations)
            }
        )
        entries: tuple[ReplacementEntry, ...] = (
            *transaction.state.replacement_entries,
            *(
                ReplacementEntry(
                    order_id=order_id, entered_at=at, decision_identity=send.decision.identity
                )
                for order_id in admitted
                if not self._ended(transaction, order_id)
                and not any(
                    entry.order_id == order_id for entry in transaction.state.replacement_entries
                )
            ),
        )
        transaction.state = replace(transaction.state, replacement_entries=entries)
        if plan.superseded_at is not None and plan.superseded_by is not None:
            # It arrives before the later decision's cancellation, which then ends it at
            # that decision's original deadline. The request keeps its true clock.
            self.admission.request_instance_cancels(
                transaction,
                original.instance_id,
                coordinated,
                label=f"replace:{send.decision.identity}",
            )
            inherited: tuple[ReplacementDeadline, ...] = tuple(
                ReplacementDeadline(
                    order_id=order_id,
                    effective_at=plan.superseded_at,
                    decision_identity=plan.superseded_by,
                )
                for order_id in admitted
                if not self._ended(transaction, order_id)
            )
            recorded: tuple[ReplacementDeadline, ...] = (
                *transaction.state.replacement_deadlines,
                *inherited,
            )
            transaction.state = replace(transaction.state, replacement_deadlines=recorded)

    @staticmethod
    def arrival_identity(account_id: str, instance_id: str, decision_identity: str) -> str:
        """Name the outcome row a deferred decision is resolved under at its arrival.

        Every outcome of a waiting plan (admitted, refused, withdrawn or replaced) is
        saved under this identity, derived from the original decision's own.
        """
        return hashlib.sha256(
            DomainCodec().encode_json(
                ("paper-replacement-send", account_id, instance_id, decision_identity)
            )
        ).hexdigest()

    def _outcome(
        self,
        transaction: AccountTransaction,
        plan: ReplacementPlan,
        at: datetime,
        quote: AccountQuote,
        touch: MarketTouch | None,
    ) -> AccountDecision:
        """Date the plan's one outcome decision at ``at`` under its derived identity."""
        original = plan.request
        return AccountDecision(
            account_id=original.account_id,
            instance_id=original.instance_id,
            decision=OrderDecision(
                identity=self.arrival_identity(
                    original.account_id, original.instance_id, original.decision.identity
                ),
                at=at,
                intent=original.decision.intent,
            ),
            quote=quote,
            maximum_fee=original.maximum_fee,
            checkpoint=transaction.latest_checkpoint(original.instance_id) or b"",
            touch=touch,
        )

    def _known(
        self, transaction: AccountTransaction, plan: ReplacementPlan, at: datetime
    ) -> tuple[AccountQuote, MarketTouch | None] | None:
        """Return the valuation and touch known at ``at``, or None if none is fresh.

        The touch is the newest market known at ``at``: the latest matched book, or the
        decision's own touch when no book is newer than its quote, kept only while no
        newer quote has been observed. An account without a paper scenario has no
        books. Freshness is judged at ``at``.
        """
        request = plan.request
        state = transaction.state
        observed = next(
            (quote for quote in state.quotes if quote.price.per == request.quote.price.per), None
        )
        if observed is None or observed.at > at:
            return None
        instrument = request.quote.price.per.instrument_id
        bound = any(
            item.account_id == request.account_id and item.scenario.instrument_id == instrument
            for item in state.paper_bindings
        )
        trace = transaction.latest_trace(request.account_id, instrument) if bound else None
        if trace is not None and trace.market.at > at:
            return None
        if trace is not None and trace.market.at > request.quote.at:
            touch: MarketTouch | None = MarketTouch(bid=trace.market.bid, ask=trace.market.ask)
            oldest = min(observed.at, trace.market.at)
        else:
            # The decision's own quote and touch were known when it was decided.
            touch = request.touch if observed == request.quote else None
            oldest = (
                observed.at
                if touch is not None or trace is None
                else min(observed.at, trace.market.at)
            )
        if at - oldest > timedelta(microseconds=self.config.budgets.max_quote_age_us):
            return None
        return observed, touch

    @staticmethod
    def _record(
        transaction: AccountTransaction,
        send: AccountDecision,
        status: Literal["committed", "rejected"],
        reason: str,
    ) -> None:
        """Retain an arrival that admitted nothing, with why."""
        transaction.append_decisions(
            SavedDecision(
                request=send,
                result=StepCommit(status=status, reason=reason, orders=()),
            )
        )
