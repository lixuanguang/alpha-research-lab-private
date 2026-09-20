"""Advance a bounded spot economy through the shared chronological replay phases."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from fractions import Fraction
from typing import ClassVar

# project library imports
from accounting import Fill, Ledger, LedgerBalance, LedgerMark, LedgerState
from financial_units import ExactRatio, Money, Quantity
from market_data.query import InputBinding, PointEvent
from market_data.replay import ReplayCursor, ReplayPhase
from research.observations import Observation, Observations, ObservationState
from risk import SpotLimits
from serialization import DomainCodec, WireRecord
from simulation.costs import SpotCosts
from strategies import TargetRule


class BacktestSpec(WireRecord, frozen=True):
    """Bind explicit single-instance spot assumptions without deployment authority."""

    instance: str
    binding: InputBinding
    start: datetime
    end: datetime
    initial_cash: Money
    quantity: Quantity
    limits: SpotLimits
    costs: SpotCosts
    rule: str
    cadence_seconds: int
    delay_seconds: int
    max_age_seconds: int
    schema_version: str = "spot-backtest-v1"

    def __post_init__(self) -> None:
        """Reject unsupported products, timing, grids and unbounded decision schedules."""
        self._require_utc(self.start, field_name="start")
        self._require_utc(self.end, field_name="end")
        if (
            self.schema_version != "spot-backtest-v1"
            or type(self.instance) is not str
            or not self.instance
            or type(self.rule) is not str
            or not self.rule
        ):
            raise ValueError("backtest requires versioned instance and rule")
        if type(self.limits) is not SpotLimits or type(self.costs) is not SpotCosts:
            raise TypeError("backtest requires independent limits and costs")
        self.limits.__post_init__()
        self.costs.__post_init__()
        if type(self.initial_cash) is not Money or type(self.quantity) is not Quantity:
            raise TypeError("backtest requires exact capital and quantity")
        self.initial_cash.model_copy()
        self.quantity.model_copy()
        if (
            type(self.binding) is not tuple
            or len(self.binding) != 3
            or any(
                type(value) is not str or not value for value in (self.binding[0], self.binding[1])
            )
            or self.binding[2] != self.quantity.dimension.instrument_id
            or self.initial_cash.currency != self.limits.tick.currency
            or self.initial_cash.value < 0
            or self.quantity.value <= 0
            or self.limits.target_reason(self.quantity, self.quantity, pending=False) is not None
            or self.costs.adverse.per != self.limits.tick.per
            or self.costs.adverse.currency != self.limits.tick.currency
            or any(
                type(value) is not int or value <= 0
                for value in (self.cadence_seconds, self.delay_seconds, self.max_age_seconds)
            )
            or self.delay_seconds >= self.cadence_seconds
            or not timedelta(0)
            < self.end - self.start
            <= timedelta(seconds=self.cadence_seconds * 1024)
        ):
            raise ValueError("incompatible spot backtest selection, timing or dimensions")

    @property
    def identity(self) -> str:
        """Hash the complete resolved economic assumptions.

        Returns:
            Semantic SHA-256 without output paths or execution clocks.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class PendingIntent(WireRecord, frozen=True):
    """Reserve the sole pending target and its actual-holdings delta until strict expiry."""

    identity: str
    decision_at: datetime
    expires_at: datetime
    target: Quantity
    delta: Quantity
    reserved_cash: Money

    def __post_init__(self) -> None:
        """Require a positive horizon, exact exposure and nonnegative estimated cash reservation."""
        self._require_utc(self.decision_at, field_name="decision_at")
        self._require_utc(self.expires_at, field_name="expires_at")
        if (
            type(self.identity) is not str
            or not self.identity
            or self.expires_at <= self.decision_at
        ):
            raise ValueError("invalid intent identity or expiry")
        if (
            type(self.target) is not Quantity
            or type(self.delta) is not Quantity
            or type(self.reserved_cash) is not Money
        ):
            raise TypeError("pending intent requires exact financial values")
        for value in (self.target, self.delta, self.reserved_cash):
            value.model_copy()
        if (
            self.target.dimension != self.delta.dimension
            or self.delta.value == 0
            or self.reserved_cash.value < 0
        ):
            raise ValueError("invalid pending intent reservation")


class EconomicEvent(WireRecord, frozen=True):
    """Retain an observable decision, intent outcome, fill or valuation with exact balances."""

    at: datetime
    phase: ReplayPhase
    reason: str
    balance: LedgerBalance
    observation: Observation | None = None
    target: Quantity | None = None
    return_ratio: ExactRatio | None = None
    fill: Fill | None = None
    mark: LedgerMark | None = None
    intent: PendingIntent | None = None

    def __post_init__(self) -> None:
        """Reject invalid trace clocks and unsupported phase labels."""
        self._require_utc(self.at, field_name="at")
        if (
            self.phase not in ("source", "expiry", "fill", "decision", "mark")
            or type(self.reason) is not str
            or not self.reason
        ):
            raise ValueError("invalid economic trace event")
        if type(self.balance) is not LedgerBalance:
            raise TypeError("economic trace requires exact ledger balance")
        self.balance.__post_init__()
        if self.mark is not None:
            self.mark.__post_init__()
        if self.target is not None:
            self.target.model_copy()
        for value in (self.observation, self.fill, self.intent, self.return_ratio):
            if value is not None:
                value.__post_init__()


class EconomicState(WireRecord, frozen=True):
    """Retain the complete consumer state that a source cursor cannot supply."""

    clock: datetime
    next_decision: datetime
    observations: ObservationState
    ledger: LedgerState
    pending: PendingIntent | None
    trace: tuple[EconomicEvent, ...]

    def __post_init__(self) -> None:
        """Reject incomplete schedules, unavailable state and inconsistent applied-fill traces."""
        self._require_utc(self.clock, field_name="clock")
        self._require_utc(self.next_decision, field_name="next_decision")
        self.observations.__post_init__()
        self.ledger.__post_init__()
        if self.next_decision < self.clock or type(self.trace) is not tuple:
            raise ValueError("incomplete economic schedule or trace")
        if (
            any(point.known_at > self.clock for point in self.observations.points)
            or any(
                observation.closed_at > self.clock for observation in self.observations.completed
            )
            or any(known > self.clock for _, known in self.observations.gaps)
        ):
            raise ValueError("checkpoint includes unavailable observation state")
        if self.pending is not None:
            self.pending.__post_init__()
            if not self.pending.decision_at <= self.clock < self.pending.expires_at:
                raise ValueError("checkpoint contains an inactive pending intent")
        previous: datetime | None = None
        applied: list[Fill] = []
        for event in self.trace:
            event.__post_init__()
            if event.at > self.clock or (previous is not None and event.at < previous):
                raise ValueError("checkpoint trace is out of order")
            previous = event.at
            if event.fill is not None:
                applied.append(event.fill)
        if tuple(applied) != self.ledger.fills:
            raise ValueError("checkpoint ledger differs from applied-fill trace")


class EconomicCheckpoint(WireRecord, frozen=True):
    """Pair complete consumer state with a completed replay cursor and byte-integrity digest."""

    spec_identity: str
    cursor: ReplayCursor
    state: EconomicState
    state_sha256: str
    schema_version: str = "economic-checkpoint-v1"

    def __post_init__(self) -> None:
        """Reject altered, incompatible or partial completed-step state."""
        self.cursor.__post_init__()
        self.state.__post_init__()
        if (
            self.schema_version != "economic-checkpoint-v1"
            or self.state.clock != self.cursor.clock
            or self.state_sha256
            != hashlib.sha256(DomainCodec().encode_json(self.state)).hexdigest()
        ):
            raise ValueError("incomplete or corrupt economic checkpoint")


class EconomicResult(WireRecord, frozen=True):
    """Retain exact terminal economics and explicit synthetic/exploratory limitations."""

    spec: BacktestSpec
    checkpoint: EconomicCheckpoint
    terminal: LedgerMark
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require completed terminal state and a reproducible final ledger mark."""
        self.spec.__post_init__()
        self.checkpoint.__post_init__()
        if (
            self.checkpoint.cursor.clock != self.spec.end
            or self.checkpoint.state.pending is not None
            or self.checkpoint.spec_identity != self.spec.identity
        ):
            raise ValueError("economic result is not complete")
        if not self.checkpoint.state.trace or self.checkpoint.state.trace[-1].mark != self.terminal:
            raise ValueError("terminal mark differs from retained trace")


class SpotSimulation:
    """Own phase-driven economic transitions with injected observations, rule, limits and ledger."""

    _codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self,
        spec: BacktestSpec,
        observations: Observations,
        rule: TargetRule,
        ledger: Ledger,
        *,
        state: EconomicState | None = None,
    ) -> None:
        """Bind one isolated consumer and validate any complete economic restart.

        Args:
            spec: Resolved immutable single-instance assumptions.
            observations: Selected input's admitted and frozen state.
            rule: Deterministic versioned target operation, with no risk authority.
            ledger: Independent exact accounting state.
            state: Complete prior consumer state, or None.

        Raises:
            ValueError: Collaborators or checkpoint disagree with resolved assumptions.
        """
        spec.__post_init__()
        if (
            rule.identity != spec.rule
            or observations.binding != spec.binding
            or ledger.state.initial_cash != spec.initial_cash
            or ledger.state.dimension != spec.quantity.dimension
        ):
            raise ValueError("simulation collaborators differ from resolved assumptions")
        self.spec, self.observations, self.rule, self.ledger = spec, observations, rule, ledger
        self._cadence = timedelta(seconds=spec.cadence_seconds)
        self._delay = timedelta(seconds=spec.delay_seconds)
        self._clock = spec.start
        self._next_decision = min(spec.start + self._cadence, spec.end)
        self._pending: PendingIntent | None = None
        self._trace: list[EconomicEvent] = []
        self._mark_due = False
        if state is not None:
            state.__post_init__()
            if (
                state.ledger != ledger.state
                or state.observations != observations.state
                or not spec.start <= state.clock <= spec.end
            ):
                raise ValueError("incompatible restored economic state")
            expected = min(
                spec.start + self._cadence * (len(state.observations.completed) + 1), spec.end
            )
            if state.next_decision != expected or (
                state.clock < spec.end and state.next_decision <= state.clock
            ):
                raise ValueError("checkpoint lacks complete decision schedule")
            self._clock, self._next_decision = state.clock, state.next_decision
            self._pending, self._trace = state.pending, list(state.trace)

    @property
    def scheduled_at(self) -> datetime:
        """Select the earliest outstanding decision, expiry, future-event fill or terminal.

        Returns:
            Next explicit UTC wakeup for the shared chronological iterator.
        """
        clocks = [self._next_decision, self.spec.end]
        if self._pending is not None:
            clocks.append(self._pending.expires_at)
            clock = self.observations.next_fill_clock(
                self._pending.decision_at, self._delay, self._clock
            )
            if clock is not None:
                clocks.append(clock)
        return min(clocks)

    def consume(self, phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Apply one scheduler-owned phase without processing future information early.

        Args:
            phase: Shared source, expiry, fill, decision and mark phase.
            instant: Current UTC simulation clock.
            item: Source event only during source admission.

        Raises:
            ValueError: Required accounting or terminal valuation fails.
        """
        self._clock = instant
        if phase == "source" and item is not None:
            if self.observations.admit(item, instant):
                self._record(phase, "known_gap", intent=self._pending)
                self._pending = None
        elif (
            phase == "expiry" and self._pending is not None and instant >= self._pending.expires_at
        ):
            self._record(phase, "expired", intent=self._pending)
            self._pending = None
        elif phase == "fill":
            self._fill(instant)
        elif phase == "decision" and instant == self._next_decision and instant < self.spec.end:
            self._decide(instant)
            self._next_decision = min(instant + self._cadence, self.spec.end)
            self._mark_due = True
        elif phase == "mark" and (self._mark_due or instant == self.spec.end):
            observation = self.observations.latest(instant, start=self.spec.start)
            if observation.point is None and self.ledger.balance.holding.value:
                if instant == self.spec.end:
                    raise ValueError(f"missing required terminal valuation: {observation.reason}")
                self._record(phase, f"valuation_{observation.reason}")
            else:
                mark = self.ledger.mark(
                    None if observation.point is None else observation.point.price
                )
                self._record(phase, "terminal" if instant == self.spec.end else "valued", mark=mark)
            self._mark_due = False

    def _fill(self, instant: datetime) -> None:
        """Take the first eligible subsequent print, with final independent affordability checks."""
        pending = self._pending
        if pending is None:
            return
        for point in self.observations.fill_candidates(pending.decision_at, self._delay, instant):
            reason = self.spec.limits.price_reason(point.price)
            if reason is not None:
                self._record("fill", reason, intent=pending)
                self._pending = None
                return
            fill = self.spec.costs.fill(
                pending.identity,
                decision_at=pending.decision_at,
                filled_at=instant,
                quantity=pending.delta,
                reference=point.price,
            )
            balance = self.ledger.balance
            reason = self.spec.limits.fill_reason(
                fill.quantity, fill.effective, fill.fee, balance.cash, balance.holding
            )
            if reason is None:
                self.ledger.apply(fill)
                self._record("fill", "filled", fill=fill, intent=pending)
            else:
                self._record("fill", reason, intent=pending)
            self._pending = None
            return

    def _decide(self, instant: datetime) -> None:
        """Freeze the new close, obtain a rule target and reserve at most one intent."""
        completed = self.observations.state.completed
        previous = completed[-1] if completed else None
        current = self.observations.close(instant)
        ratio = None
        if previous is not None and previous.point is not None and current.point is not None:
            ratio = ExactRatio.from_fraction(
                Fraction(current.point.price.value) / Fraction(previous.point.price.value) - 1
            )
        target = self.rule.target(previous, current, self.spec.quantity, self._cadence)
        has_current_gap = any(known == instant for _, known in self.observations.state.gaps)
        if has_current_gap:
            target = None
        reason = (
            "warmup"
            if previous is None
            else current.reason
            if current.point is None
            else "previous_observation_unavailable"
        )
        if has_current_gap:
            reason = "known_gap"
        if target is not None:
            reason = (
                self.spec.limits.target_reason(
                    target, self.ledger.balance.holding, pending=self._pending is not None
                )
                or "unchanged_target"
            )
            if reason == "unchanged_target" and target != self.ledger.balance.holding:
                if current.point is None:
                    reason = "missing_reference"
                else:
                    delta = target - self.ledger.balance.holding
                    identity = hashlib.sha256(
                        self._codec.encode_json((self.spec.identity, instant))
                    ).hexdigest()
                    estimated = self.spec.costs.fill(
                        identity,
                        decision_at=instant,
                        filled_at=instant + self._delay,
                        quantity=delta,
                        reference=current.point.price,
                    )
                    reason = (
                        self.spec.limits.fill_reason(
                            delta,
                            estimated.effective,
                            estimated.fee,
                            self.ledger.balance.cash,
                            self.ledger.balance.holding,
                        )
                        or "intent_created"
                    )
                    if reason == "intent_created":
                        reserve = estimated.effective.amount(delta) + estimated.fee
                        if delta.value < 0:
                            reserve = reserve - reserve
                        self._pending = PendingIntent(
                            identity=identity,
                            decision_at=instant,
                            expires_at=min(instant + self._cadence, self.spec.end),
                            target=target,
                            delta=delta,
                            reserved_cash=reserve,
                        )
        self._record(
            "decision",
            reason,
            observation=current,
            target=target,
            return_ratio=ratio,
            intent=self._pending,
        )

    def _record(
        self,
        phase: ReplayPhase,
        reason: str,
        *,
        observation: Observation | None = None,
        target: Quantity | None = None,
        return_ratio: ExactRatio | None = None,
        fill: Fill | None = None,
        mark: LedgerMark | None = None,
        intent: PendingIntent | None = None,
    ) -> None:
        """Retain exact externally inspectable outcomes in deterministic phase order."""
        self._trace.append(
            EconomicEvent(
                at=self._clock,
                phase=phase,
                reason=reason,
                balance=self.ledger.balance,
                observation=observation,
                target=target,
                return_ratio=return_ratio,
                fill=fill,
                mark=mark,
                intent=intent,
            )
        )

    def checkpoint(self, cursor: ReplayCursor) -> EconomicCheckpoint:
        """Bind a completed source step to all economic state and schedules.

        Args:
            cursor: Completed scheduler cursor; partial callbacks cannot supply one.

        Returns:
            Complete typed checkpoint suitable for strict DomainCodec round-trip.
        """
        state = EconomicState(
            clock=self._clock,
            next_decision=self._next_decision,
            observations=self.observations.state,
            ledger=self.ledger.state,
            pending=self._pending,
            trace=tuple(self._trace),
        )
        return EconomicCheckpoint(
            spec_identity=self.spec.identity,
            cursor=cursor,
            state=state,
            state_sha256=hashlib.sha256(self._codec.encode_json(state)).hexdigest(),
        )

    def result(self, cursor: ReplayCursor) -> EconomicResult:
        """Finish only a reconciled terminal state, preserving admitted coverage limitations.

        Args:
            cursor: Completed terminal replay cursor.

        Returns:
            Exact result without a profitability, empirical-causality or deployment claim.

        Raises:
            ValueError: Terminal valuation was not successfully completed.
        """
        if not self._trace or self._trace[-1].mark is None:
            raise ValueError("terminal valuation is incomplete")
        limitations = tuple(
            sorted(
                {reason for evidence in self.observations.evidence for reason in evidence.reasons}
            )
        )
        return EconomicResult(
            spec=self.spec,
            checkpoint=self.checkpoint(cursor),
            terminal=self._trace[-1].mark,
            limitations=(
                *limitations,
                "exploratory_degraded inputs; synthetic software evidence only",
                "trade-price full fills; no spread, queue, liquidity, impact or financing model",
            ),
        )
