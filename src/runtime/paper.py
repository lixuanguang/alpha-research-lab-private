"""Supervise candidate clocks and callbacks over the durable non-executable OMS."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from typing import Literal

# project library imports
from accounting import Ledger
from configuration import PaperConfiguration
from execution import (
    OrderDecision,
    OrderEvent,
    PaperMarket,
    PaperMatcher,
    PaperOrderJournal,
    StepCommit,
)
from financial_units import Money, Price, Quantity
from research.observations import DecisionInputs, DecisionSource
from runtime.candidates import CandidateCheckpoint, CandidateSession, CandidateStep, LoadedCandidate
from runtime.feature_feed import CandidateFeatureFeed
from serialization import DomainCodec, WireRecord
from strategies import ExposureIntent, StrategyEvent, TargetIntent


class PaperCheckpoint(WireRecord, frozen=True):
    """Bind candidate state, market eligibility and callback cursor to one operating scenario."""

    binding_identity: str
    candidate: CandidateCheckpoint
    last_at: datetime
    market: PaperMarket | None
    order_sequence: int
    blocked: str | None
    schema_version: Literal["paper-checkpoint-v1"] = "paper-checkpoint-v1"

    def __post_init__(self) -> None:
        """Reject incompatible state, future markets and invalid event cursors."""
        self._require_utc(self.last_at, field_name="runtime event")
        self.candidate.__post_init__()
        if (
            self.schema_version != "paper-checkpoint-v1"
            or len(self.binding_identity) != 64
            or type(self.order_sequence) is not int
            or self.order_sequence < 0
            or (self.blocked is not None and not self.blocked)
            or (
                self.candidate.policy.last_at is not None
                and self.candidate.policy.last_at > self.last_at
            )
        ):
            raise ValueError("invalid paper continuation")
        if self.market is not None:
            self.market.__post_init__()
            if self.market.at > self.last_at:
                raise ValueError("paper checkpoint includes a future market")


class PaperFaultEvidence(WireRecord, frozen=True):
    """Retain the observed fault clock separately from its safe callback clock."""

    event: StrategyEvent
    observed_at: datetime
    schema_version: Literal["paper-fault-v1"] = "paper-fault-v1"

    def __post_init__(self) -> None:
        """Require an identified fault and an original UTC observation time."""
        self.event.__post_init__()
        self._require_utc(self.observed_at, field_name="observed paper fault")
        if self.schema_version != "paper-fault-v1" or self.event.kind != "fault":
            raise ValueError("invalid paper fault evidence")


class PaperCandidateRuntime:
    """Own one dedicated account's fenced candidate lifecycle and durable decisions.

    Call ``open`` before events and ``release`` in a finally block. Exceptions
    propagate to the supervising application; no failed persistence is reported
    as success. State is staged in fresh candidate sessions and becomes current
    only after the journal commits. Market and feature outages suppress new
    decisions; cancel and order reconciliation remain independently reachable.
    """

    def __init__(
        self,
        loaded: LoadedCandidate,
        config: PaperConfiguration,
        journal: PaperOrderJournal,
        *,
        source: DecisionSource | None = None,
        features: CandidateFeatureFeed | None = None,
    ) -> None:
        """Admit explicit collaborators and source signatures before reading input or state."""
        config.__post_init__()
        if (
            loaded.manifest.product != "spot"
            or str(config.maximum.dimension.instrument_id) != loaded.deployment.entity
            or loaded.manifest.state.on_restart != "restore"
            or journal.binding_identity != self.binding(loaded, config)
            or journal.account != config.account
            or journal.instance != loaded.deployment.instance
            or journal.mode != config.mode
        ):
            raise ValueError("paper account, candidate, state or journal binding differs")
        if loaded.deployment.input_mode == "source":
            if (
                source is None
                or features is not None
                or source.identity != loaded.deployment.source_identity
                or source.requirements != loaded.manifest.inputs
            ):
                raise ValueError("paper source differs from admitted candidate binding")
        elif source is not None or features is None:
            raise ValueError("paper serving requires the explicit candidate feature feed")
        self.loaded, self.config, self.journal = loaded, config, journal
        self._source, self._features = source, features
        self._codec = DomainCodec()
        self._matcher = PaperMatcher(
            journal,
            fee_rate=config.fee_rate,
            lot=config.lot,
            scenario=config.execution,
        )
        self._state: PaperCheckpoint | None = None
        self._epoch: int | None = None

    @staticmethod
    def binding(loaded: LoadedCandidate, config: PaperConfiguration) -> str:
        """Pin candidate, deployment, resolved capabilities and independent account limits."""
        return hashlib.sha256(
            DomainCodec().encode_json((loaded.identity, config.identity))
        ).hexdigest()

    def open(self, *, owner: str, at: datetime) -> None:
        """Claim sole ownership, recover durable state and replay pending order callbacks.

        Restart preserves open reservations. The local paper ledger reconstructs
        from identified fills; unknown orders stay blocked until explicit order
        reconciliation. A failed callback or incompatible checkpoint releases the
        process fence and leaves the last durable continuation intact.
        """
        if self._epoch is not None:
            raise ValueError("paper runtime is already open")
        PaperCheckpoint._require_utc(at, field_name="runtime startup")
        self._epoch = self.journal.claim(owner)
        try:
            saved = self.journal.checkpoint()
            if saved is None:
                self._state = PaperCheckpoint(
                    binding_identity=self.binding(self.loaded, self.config),
                    candidate=CandidateSession(self.loaded).checkpoint(),
                    last_at=at,
                    market=None,
                    order_sequence=0,
                    blocked=None,
                )
            else:
                self._state = self._codec.decode_json(saved, PaperCheckpoint)
                if self._state.binding_identity != self.binding(self.loaded, self.config):
                    raise ValueError("paper checkpoint binding differs")
                CandidateSession(self.loaded, self._state.candidate)
            Ledger(self.journal.ledger_state())
            # A quote may have durable partial matching effects without its
            # final candidate callback/checkpoint. Complete its original bytes
            # before recovery advances availability to the new process clock.
            for _, payload in self.journal.unfinished_markets():
                self.market(self._codec.decode_json(payload, PaperMarket))
            self._drain_orders()
            self._lifecycle(
                StrategyEvent(
                    identity=f"start:{self._epoch}",
                    kind="start" if saved is None else "recovery",
                    at=at,
                    reason="paper-start" if saved is None else "paper-journal-reconciled",
                )
            )
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        """Release the process fence without canceling or discarding unresolved orders."""
        if self._epoch is not None:
            self.journal.release(self._epoch)
            self._epoch = None

    def checkpoint(self) -> PaperCheckpoint:
        """Return the last successfully persisted continuation for inspection."""
        return self._current()

    def market(self, market: PaperMarket) -> None:
        """Deliver a received quote, settle modeled paper effects and checkpoint callbacks."""
        market.__post_init__()
        payload = self._codec.encode_json(market)
        identity = f"market:{market.identity}"
        if self.journal.has_step(identity, payload):
            return
        self._admit_time(market.at)
        if market.bid.per != self.config.maximum.dimension:
            raise ValueError("paper market instrument differs from its account")
        if self.config.execution is None or self.config.mode == "shadow":
            self.journal.claim_market(
                epoch=self._fence(), identity=market.identity, payload=payload
            )
        if self.config.mode == "paper":
            self._matcher.match(market, epoch=self._fence())
        self._drain_orders()
        state = self._current()
        session = CandidateSession(self.loaded, state.candidate)
        event = StrategyEvent(
            identity=identity,
            kind="market",
            at=market.at,
            reason="received-quote",
            source_identity=market.identity,
        )
        session.handle_event(event)
        self._persist(identity, payload, session, market.at, market=market, result=event)

    def input_delivery(self, *, identity: str, at: datetime, payload: bytes) -> None:
        """Retain the actual delivered source envelope before any dependent decision.

        Applications use this for the original capture and local availability
        facts needed to reproduce a live-input run. It grants no quote eligibility
        and performs no matching; ``market`` independently admits eligible quotes.
        """
        step_id = f"input:{identity}"
        if self.journal.has_step(step_id, payload):
            return
        self._admit_time(at)
        session = CandidateSession(self.loaded, self._current().candidate)
        event = StrategyEvent(
            identity=step_id,
            kind="market",
            at=at,
            reason="durable-input-delivery",
            source_identity=hashlib.sha256(payload).hexdigest(),
        )
        session.handle_event(event)
        self._persist(step_id, payload, session, at, result=event)

    def timer(self, *, identity: str, at: datetime) -> tuple[CandidateStep, StepCommit]:
        """Evaluate one explicit cadence tick and atomically journal its candidate and intents.

        A repeated event identity reopens the original result. To retry a paused
        cutoff after inputs recover, supply a new event identity at that same
        cutoff. A successful cutoff cannot be evaluated twice. Source values and
        their actual provenance remain in the journal's input bytes.
        """
        step_id = f"timer:{identity}"
        saved = self.journal.step(step_id)
        if saved is not None:
            step = self._codec.decode_json(saved.result_bytes, CandidateStep)
            if step.at != at:
                raise ValueError("timer identity reused at another cutoff")
            return step, saved.commit
        self._admit_time(at)
        self._drain_orders()
        state = self._current()
        session = CandidateSession(self.loaded, state.candidate)
        session.admit_cutoff(at)
        inputs: DecisionInputs | None = None
        reason = self._pause_reason(at)
        if reason is None and self._source is not None:
            inputs = self._source.read(self.loaded.deployment.entity, at)
            if inputs.entity != self.loaded.deployment.entity or inputs.decision_at != at:
                raise ValueError("paper source returned another entity or cutoff")
            if any(row.value is None for row in inputs.observations):
                reason = "input-unavailable"
        if reason is not None:
            step = session.pause(at, reason)
        else:
            session.handle_event(
                StrategyEvent(
                    identity=step_id,
                    kind="timer",
                    at=at,
                    reason="candidate-cadence",
                )
            )
            if inputs is not None:
                step = session.evaluate_inputs(inputs)
            elif self._features is not None:
                step = self._features.evaluate(session, at)
            else:
                raise ValueError("paper runtime has no admitted input")
            if step.status == "paused":
                session = CandidateSession(self.loaded, state.candidate)
                step = session.pause(at, step.reason)
        decision = (
            None
            if step.decision is None
            else OrderDecision(
                identity=hashlib.sha256(self._codec.encode_json(step.decision)).hexdigest(),
                at=at,
                intent=step.decision.intent,
            )
        )
        result = self._persist(
            step_id,
            self._codec.encode_json((at, inputs, state.market)),
            session,
            at,
            result=step,
            decision=decision,
            reference=self._reference(decision),
        )
        return step, result

    def order(self, event: OrderEvent) -> None:
        """Persist an observed order fact before delivering order/account callbacks."""
        self.journal.apply_event(epoch=self._fence(), event=event)
        self._drain_orders()

    def block(self, *, identity: str, at: datetime, reason: str) -> None:
        """Persist a visible block on new decisions without claiming cancellation or flattening."""
        event = StrategyEvent(identity=f"block:{identity}", kind="fault", at=at, reason=reason)
        self._lifecycle(event, blocked=reason)

    def fault(self, *, identity: str, at: datetime, reason: str) -> None:
        """Durably block a failed run before its owner releases the process fence.

        The observed fault clock may differ from the continuation clock. Deliver
        its callback at the current continuation clock so the policy never sees
        time move backward and an interrupted claimed quote remains replayable.
        The original failure remains the application's responsibility to report.
        """
        PaperCheckpoint._require_utc(at, field_name="paper fault")
        if type(identity) is not str or not identity or type(reason) is not str or not reason:
            raise ValueError("paper fault requires an identity and visible reason")
        self._fence()
        current = self._current()
        saved = self.journal.step(f"guard:fault:{identity}")
        if saved is not None:
            prior = self._codec.decode_json(saved.input_bytes, PaperFaultEvidence)
            if prior.event.reason != reason:
                raise ValueError("paper fault identity reused for another reason")
            return
        effective_at = current.last_at
        event = StrategyEvent(
            identity=f"fault:{identity}", kind="fault", at=effective_at, reason=reason
        )
        self._lifecycle(
            event,
            blocked=reason,
            evidence=PaperFaultEvidence(event=event, observed_at=at),
        )

    def reconcile(
        self,
        *,
        identity: str,
        at: datetime,
        cash: Money,
        holding: Quantity,
        open_order_ids: tuple[str, ...],
    ) -> bool:
        """Compare an independent paper account observation before reopening operation.

        This checks the software account, not a physical venue. Unknown outcomes
        require their separately identified order reconciliation first.
        """
        if any(order.status == "unknown" for order in self.journal.orders()):
            raise ValueError("unresolved orders block paper reconciliation")
        matched = self.journal.reconcile_account(
            epoch=self._fence(),
            expected_cash=cash,
            expected_holding=holding,
            open_order_ids=open_order_ids,
        )
        self._drain_orders()
        event = StrategyEvent(
            identity=f"reconcile:{identity}",
            kind="account",
            at=at,
            reason="local-paper-account-reconciled" if matched else "paper-account-break",
            cash=cash,
            holding=holding,
        )
        current_block = self._current().blocked
        self._lifecycle(
            event,
            blocked=None if matched else current_block or "paper-account-break",
            clear_block=matched and current_block == "paper-account-break",
        )
        return matched

    def resume(
        self,
        *,
        identity: str,
        at: datetime,
        expected_checkpoint: PaperCheckpoint,
        cash: Money,
        holding: Quantity,
        open_order_ids: tuple[str, ...],
    ) -> bool:
        """Explicitly clear a candidate block after fresh independent account reconciliation.

        A caller must name the exact blocked continuation it inspected. Unknown
        outcomes and unconfirmed order or cancel requests need identified order
        facts before this operation; known accepted/partial open orders remain
        reserved and must appear in the independent account observation.
        """
        if type(identity) is not str or not identity:
            raise ValueError("paper resume requires an identity")
        expected_checkpoint.__post_init__()
        current = self._current()
        if current != expected_checkpoint:
            raise ValueError("paper resume expected checkpoint differs")
        if current.blocked is None:
            raise ValueError("paper resume requires a candidate block")
        PaperCheckpoint._require_utc(at, field_name="paper resume")
        if at <= current.last_at:
            raise ValueError("paper resume requires a fresh reconciliation clock")
        if any(
            order.status in ("intent", "request_ack", "cancel_requested", "cancel_ack", "unknown")
            or (not order.is_terminal and order.cancel_requested)
            for order in self.journal.orders()
        ):
            raise ValueError("unresolved order outcome blocks paper resume")
        if not self.reconcile(
            identity=f"resume:{identity}",
            at=at,
            cash=cash,
            holding=holding,
            open_order_ids=open_order_ids,
        ):
            return False
        if self.journal.blocked_reason() is not None:
            raise ValueError("paper account remains blocked after reconciliation")
        self._lifecycle(
            StrategyEvent(
                identity=f"resume:{identity}",
                kind="recovery",
                at=at,
                reason="paper-operator-resume",
            ),
            clear_block=True,
        )
        return True

    def cancel(self, *, identity: str, order_id: str, at: datetime) -> None:
        """Request cancellation independently of candidate health; retain pending exposure."""
        self.journal.request_cancel(
            epoch=self._fence(),
            order_id=order_id,
            event_id=identity,
            at=at,
        )
        self._drain_orders()

    def stop(self, *, identity: str, at: datetime) -> None:
        """Checkpoint a lifecycle stop and block new decisions; orders remain attributable."""
        self._lifecycle(
            StrategyEvent(identity=f"stop:{identity}", kind="stop", at=at, reason="operator-stop"),
            blocked="operator-stop",
        )

    def _drain_orders(self) -> None:
        """Replay every persisted but uncheckpointed order effect exactly once into policy state."""
        for item in self.journal.events(after_sequence=self._current().order_sequence):
            state = self._current()
            # Late exchange facts retain their original event clock in the journal;
            # callback availability cannot run the supervised clock backward.
            at = max(item.event.at, state.last_at)
            session = CandidateSession(self.loaded, state.candidate)
            event = StrategyEvent(
                identity=f"order:{item.sequence}",
                kind="order",
                at=at,
                reason=item.event.kind,
                order_id=item.order.identity,
                order_status=item.order.status,
            )
            session.handle_event(event)
            if item.event.fill is not None:
                balance = item.balance
                session.handle_event(
                    StrategyEvent(
                        identity=f"account:{item.sequence}",
                        kind="account",
                        at=at,
                        reason="identified-paper-fill",
                        cash=balance.cash,
                        holding=balance.holding,
                    )
                )
            self._persist(
                event.identity,
                self._codec.encode_json(item),
                session,
                at,
                result=event,
                order_sequence=item.sequence,
            )

    def _lifecycle(
        self,
        event: StrategyEvent,
        *,
        blocked: str | None = None,
        clear_block: bool = False,
        evidence: PaperFaultEvidence | None = None,
    ) -> None:
        """Persist one lifecycle callback and its independent operating state."""
        if evidence is not None and evidence.event != event:
            raise ValueError("paper fault evidence differs from its callback")
        payload = self._codec.encode_json(event if evidence is None else evidence)
        if self.journal.has_step(event.identity, payload):
            return
        guard_id = f"guard:{event.identity}"
        if blocked is not None and self.journal.has_step(guard_id, payload):
            # A prior attempt already persisted the hard block. Its callback
            # cannot be re-evaluated against policy state from a later event.
            return
        self._admit_time(event.at)
        if blocked is not None:
            # Hard block first: a failing strategy callback cannot disable the
            # independent stop path or let a restart resume new decisions.
            self._persist(
                guard_id,
                payload,
                CandidateSession(self.loaded, self._current().candidate),
                event.at,
                result=event,
                blocked=blocked,
            )
        session = CandidateSession(self.loaded, self._current().candidate)
        session.handle_event(event)
        self._persist(
            event.identity,
            payload,
            session,
            event.at,
            result=event,
            blocked=blocked,
            clear_block=clear_block,
        )

    def _persist(
        self,
        identity: str,
        payload: bytes,
        session: CandidateSession,
        at: datetime,
        *,
        result: CandidateStep | StrategyEvent,
        decision: OrderDecision | None = None,
        reference: Price | None = None,
        market: PaperMarket | None = None,
        order_sequence: int | None = None,
        blocked: str | None = None,
        clear_block: bool = False,
    ) -> StepCommit:
        """Publish policy continuation with the corresponding intent and risk outcome."""
        prior = self._current()
        successor = PaperCheckpoint(
            binding_identity=prior.binding_identity,
            candidate=session.checkpoint(),
            last_at=at,
            market=prior.market if market is None else market,
            order_sequence=prior.order_sequence if order_sequence is None else order_sequence,
            blocked=None if clear_block else blocked or prior.blocked,
        )
        committed = self.journal.commit_step(
            epoch=self._fence(),
            step_id=identity,
            checkpoint=self._codec.encode_json(successor),
            decision=decision,
            reference=reference,
            maximum_fee=self.config.maximum_fee,
            input_bytes=payload,
            result_bytes=self._codec.encode_json(result),
        )
        self._state = successor
        return committed

    def _pause_reason(self, at: datetime) -> str | None:
        """Apply hard operational checks independently of feature or policy behavior."""
        state = self._current()
        if state.blocked:
            return state.blocked
        if self.journal.blocked_reason() is not None:
            return self.journal.blocked_reason()
        if any(order.status == "unknown" for order in self.journal.orders()):
            return "order-outcome-unknown"
        if state.market is None or at - state.market.at > timedelta(
            microseconds=self.config.market_max_age_us
        ):
            return "market-unavailable"
        return None

    def _reference(self, decision: OrderDecision | None) -> Price | None:
        """Select a side-aware current touch for target/exposure conversion."""
        market = self._current().market
        if decision is None or market is None:
            return None
        intent = decision.intent
        holding = self.journal.ledger_balance().holding
        selling = isinstance(intent, TargetIntent) and intent.quantity.value < holding.value
        if isinstance(intent, ExposureIntent):
            selling = intent.exposure.value < market.bid.amount(holding).value
        return market.bid if selling else market.ask

    def _admit_time(self, at: datetime) -> None:
        """Refuse clock regression before any candidate or market effect."""
        PaperCheckpoint._require_utc(at, field_name="runtime event")
        if at < self._current().last_at:
            raise ValueError("paper runtime clock regressed")
        self._fence()

    def _current(self) -> PaperCheckpoint:
        """Require a loaded continuation rather than implicit startup."""
        if self._state is None:
            raise ValueError("paper runtime is not open")
        return self._state

    def _fence(self) -> int:
        """Require explicit sole ownership for each write path."""
        if self._epoch is None:
            raise ValueError("paper runtime has no execution fence")
        return self._epoch
