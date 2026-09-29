"""Evaluate scheduled completed-price features over explicitly pinned saved input."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime, timedelta
from itertools import pairwise
from typing import ClassVar, Literal

# project library imports
from financial_units import ExactRatio, Price, QuantityKind
from market_data.query import InputBinding, PointEvent, QueryReader
from market_data.replay import Replay, ReplayCursor, ReplayPhase
from research.features.completed import CompletedReturn
from research.observations import Observation, Observations, ObservationState
from serialization import DomainCodec, WireRecord


class ScheduledFeatureSpec(WireRecord, frozen=True):
    """Bind one saved-input feature instance, units and bounded close schedule."""

    instance: str
    binding: InputBinding
    tick: Price
    start: datetime
    end: datetime
    cadence_seconds: int
    max_age_seconds: int
    schema_version: Literal["scheduled-completed-feature"] = "scheduled-completed-feature"

    def __post_init__(self) -> None:
        """Reject incompatible dimensions, clocks, versions and unbounded schedules."""
        self._require_utc(self.start, field_name="start")
        self._require_utc(self.end, field_name="end")
        if type(self.tick) is not Price:
            raise TypeError("scheduled feature requires an exact price dimension")
        self.tick.model_copy()
        if (
            self.schema_version != "scheduled-completed-feature"
            or type(self.instance) is not str
            or not self.instance.strip()
            or type(self.binding) is not tuple
            or len(self.binding) != 3
            or any(
                type(value) is not str or not value for value in (self.binding[0], self.binding[1])
            )
            or self.binding[1] != "trade"
            or self.binding[2] != self.tick.per.instrument_id
            or self.tick.per.kind != QuantityKind.BASE_UNIT
            or self.tick.value <= 0
            or type(self.max_age_seconds) is not int
            or self.max_age_seconds <= 0
        ):
            raise ValueError("invalid scheduled feature identity, binding or units")
        CompletedReturn(self.cadence_seconds)
        if (
            not timedelta(0)
            < self.end - self.start
            <= timedelta(seconds=self.cadence_seconds * 8193)
        ):
            raise ValueError("scheduled feature requires a bounded positive sample")

    @property
    def identity(self) -> str:
        """Identify formula, instance, input binding, units and timing policy.

        Returns:
            Stable SHA-256 of the complete versioned definition.
        """
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class ScheduledFeatureValue(WireRecord, frozen=True):
    """Retain the original close, exact return and separate decision-clock gap control."""

    observation: Observation
    value: ExactRatio | None
    has_current_gap: bool

    def __post_init__(self) -> None:
        """Reject malformed feature values without changing missingness into zero."""
        if type(self.observation) is not Observation or type(self.has_current_gap) is not bool:
            raise TypeError("scheduled feature requires observation and explicit gap status")
        self.observation.__post_init__()
        if self.value is not None:
            if type(self.value) is not ExactRatio:
                raise TypeError("scheduled feature requires an exact return")
            self.value.__post_init__()


class ScheduledFeatureCheckpoint(WireRecord, frozen=True):
    """Bind frozen decisions and an optional resumable cursor to immutable input bytes."""

    definition: ScheduledFeatureSpec
    input_identity: str
    values: tuple[ScheduledFeatureValue, ...]
    values_sha256: str
    cursor: ReplayCursor | None = None
    observation_state: ObservationState | None = None
    schema_version: Literal["scheduled-feature-state"] = "scheduled-feature-state"

    def __post_init__(self) -> None:
        """Validate compatible state, schedule, units, exact calculations and content digest."""
        if type(self.definition) is not ScheduledFeatureSpec or type(self.values) is not tuple:
            raise TypeError("scheduled checkpoint requires definition and immutable values")
        self.definition.__post_init__()
        if (
            self.schema_version != "scheduled-feature-state"
            or type(self.input_identity) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.input_identity) is None
            or self.values_sha256
            != hashlib.sha256(DomainCodec().encode_json(self.values)).hexdigest()
        ):
            raise ValueError("scheduled checkpoint version, input identity or digest is invalid")
        definition = self.definition
        cadence = timedelta(seconds=definition.cadence_seconds)
        formula = CompletedReturn(definition.cadence_seconds)
        previous: Observation | None = None
        for index, value in enumerate(self.values, 1):
            if type(value) is not ScheduledFeatureValue:
                raise TypeError("scheduled checkpoint requires feature values")
            value.__post_init__()
            current = value.observation
            if (
                current.closed_at != definition.start + cadence * index
                or current.closed_at >= definition.end
            ):
                raise ValueError("scheduled checkpoint has an incomplete or incompatible schedule")
            if current.point is not None and (
                current.point.price.currency != definition.tick.currency
                or current.point.price.per != definition.tick.per
                or current.point.event_at < current.closed_at - cadence
                or current.closed_at - current.point.event_at
                > timedelta(seconds=definition.max_age_seconds)
            ):
                raise ValueError("scheduled checkpoint observation units or freshness differ")
            if value.value != formula.evaluate(previous, current):
                raise ValueError("scheduled checkpoint return differs from frozen endpoints")
            previous = current
        if (self.cursor is None) != (self.observation_state is None):
            raise ValueError("scheduled checkpoint cursor and observation state must be paired")
        if self.cursor is not None and self.observation_state is not None:
            cursor, state = self.cursor, self.observation_state
            cursor.__post_init__()
            state.__post_init__()
            last_point = self.values[-1].observation.point if self.values else None
            if (
                not self.values
                or cursor.clock != self.values[-1].observation.closed_at
                or state.completed != (self.values[-1].observation,)
                or (state.next_order > 0 and cursor.position is None)
                or (last_point is not None and last_point.order >= state.next_order)
                or any(
                    point.event_at < cursor.clock
                    or point.known_at > cursor.clock
                    or point.price.currency != definition.tick.currency
                    or point.price.per != definition.tick.per
                    for point in state.points
                )
                or any(left.order >= right.order for left, right in pairwise(state.points))
                or any(
                    event_at < cursor.clock or known_at > cursor.clock
                    for event_at, known_at in state.gaps
                )
            ):
                raise ValueError("scheduled checkpoint cursor or compact observation state differs")


class _BatchClose:
    """Reconstruct a cutoff window through shared replay and scoped observation admission."""

    def __init__(
        self,
        reader: QueryReader,
        definition: ScheduledFeatureSpec,
        decision_at: datetime,
        batch_size: int,
    ) -> None:
        """Bind a single cutoff evaluation and its temporary admitted source state."""
        self._decision_at = decision_at
        self._replay = Replay(
            reader,
            (definition.binding[2],),
            start=definition.start,
            end=definition.end,
            terminal=decision_at,
            config_identity=definition.identity,
            batch_size=batch_size,
        )
        self._observations = Observations(
            definition.binding,
            self._replay.evidence,
            tick=definition.tick,
            cadence=timedelta(seconds=definition.cadence_seconds),
            max_age=timedelta(seconds=definition.max_age_seconds),
        )
        if any(item.request.instrument.product != "spot" for item in self._observations.evidence):
            raise ValueError("scheduled completed features support spot inputs only")
        if any(
            item.request.instrument.quote_currency != definition.tick.currency
            for item in self._observations.evidence
        ):
            raise ValueError("scheduled feature quote currency differs from admitted source")

    def read(self) -> tuple[Observation, bool]:
        """Freeze the requested window after complete inclusive cutoff admission."""
        while self._replay.step(self._decision_at, self._consume) is not None:
            pass
        return self._observations.close(self._decision_at), any(
            known == self._decision_at for _, known in self._observations.state.gaps
        )

    def _consume(self, phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Admit source phases without filling gaps or retroactively closing earlier windows."""
        if phase == "source" and item is not None:
            self._observations.admit(item, instant)


class ScheduledFeatures:
    """Advance one causal saved-input replay while freezing each completed close."""

    _codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self,
        reader: QueryReader,
        definition: ScheduledFeatureSpec,
        *,
        checkpoint: ScheduledFeatureCheckpoint | None = None,
        batch_size: int = 256,
    ) -> None:
        """Bind verified source bytes and optionally restore compatible completed state.

        Args:
            reader: Explicit byte-bounded saved input; no acquisition or live qualification.
            definition: Instance, exact units, window and freshness policy.
            checkpoint: Entire frozen feature state, restored with the identical definition/input.
            batch_size: Positive source delivery bound; excluded from semantic identity.

        Raises:
            ValueError: Definition, source, batch bound or restored state is incompatible.
        """
        self.definition = self._codec.decode_json(
            self._codec.encode_json(definition), ScheduledFeatureSpec
        )
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("scheduled features require a positive batch size")
        self._reader, self._batch_size = reader, batch_size
        self._values: tuple[ScheduledFeatureValue, ...] = ()
        self._cursor: ReplayCursor | None = None
        self._observation_state: ObservationState | None = None
        self._replay: Replay | None = None
        self._observations: Observations | None = None
        if checkpoint is not None:
            checkpoint = self._codec.decode_json(
                self._codec.encode_json(checkpoint), ScheduledFeatureCheckpoint
            )
            if (
                checkpoint.definition != self.definition
                or checkpoint.input_identity != reader.identity
            ):
                raise ValueError("scheduled checkpoint definition or source changed")
            if checkpoint.values and checkpoint.cursor is None:
                raise ValueError("unsupported value-only scheduled checkpoint schema")
            self._values = checkpoint.values
            self._cursor = checkpoint.cursor
            self._observation_state = checkpoint.observation_state

    @property
    def checkpoint(self) -> ScheduledFeatureCheckpoint:
        """Capture complete frozen state after the last successful decision.

        Returns:
            Versioned, digest-checked state suitable for DomainCodec serialization.
        """
        return ScheduledFeatureCheckpoint(
            definition=self.definition,
            input_identity=self._reader.identity,
            values=self._values,
            values_sha256=hashlib.sha256(self._codec.encode_json(self._values)).hexdigest(),
            cursor=self._cursor,
            observation_state=self._observation_state,
        )

    def evaluate(self, decision_at: datetime) -> ScheduledFeatureValue:
        """Complete exactly the next scheduled half-open window at its knowledge cutoff.

        Args:
            decision_at: Next UTC close, before the exclusive sample end. Missing wakeups
                must be evaluated explicitly in order; calls cannot skip or revise closes.

        Returns:
            Frozen observation, exact adjacent return and current-clock gap status.

        Raises:
            ValueError: Schedule, input admission, product or units are unsupported.
        """
        definition = self.definition
        definition._require_utc(decision_at, field_name="decision_at")
        cadence = timedelta(seconds=definition.cadence_seconds)
        if (
            decision_at != definition.start + cadence * (len(self._values) + 1)
            or decision_at >= definition.end
        ):
            raise ValueError("scheduled feature decision must be the next close before sample end")
        prior_values, prior_cursor, prior_state = (
            self._values,
            self._cursor,
            self._observation_state,
        )
        try:
            if self._replay is None:
                self._open_replay()
            previous = self._values[-1].observation if self._values else None
            value, state = self._advance(decision_at, previous)
            if self._replay is None:
                raise RuntimeError("scheduled replay disappeared before commit")
            cursor = self._replay.cursor
            if cursor is None:
                raise RuntimeError("scheduled replay did not complete the decision clock")
            self._values = (*self._values, value)
            self._cursor, self._observation_state = cursor, state
            return value
        except Exception, KeyboardInterrupt:
            # Replay callbacks can fail after partial admission. Reopen from the
            # last committed cursor and compact observation state on retry.
            self._values = prior_values
            self._cursor, self._observation_state = prior_cursor, prior_state
            self._replay = None
            self._observations = None
            raise

    def _open_replay(self) -> None:
        """Read the pinned history once and restore a committed cursor if present."""
        definition = self.definition
        replay = Replay(
            self._reader,
            (definition.binding[2],),
            start=definition.start,
            end=definition.end,
            terminal=definition.end,
            config_identity=definition.identity,
            batch_size=self._batch_size,
            cursor=self._cursor,
        )
        observations = Observations(
            definition.binding,
            replay.evidence,
            tick=definition.tick,
            cadence=timedelta(seconds=definition.cadence_seconds),
            max_age=timedelta(seconds=definition.max_age_seconds),
            state=self._observation_state,
        )
        if any(item.request.instrument.product != "spot" for item in observations.evidence):
            raise ValueError("scheduled completed features support spot inputs only")
        if any(
            item.request.instrument.quote_currency != definition.tick.currency
            for item in observations.evidence
        ):
            raise ValueError("scheduled feature quote currency differs from admitted source")
        self._replay, self._observations = replay, observations

    def _advance(
        self, decision_at: datetime, previous: Observation | None
    ) -> tuple[ScheduledFeatureValue, ObservationState]:
        """Admit all equal-clock sources, freeze one window and retain only useful state."""
        replay, observations = self._replay, self._observations
        if replay is None or observations is None:
            raise RuntimeError("scheduled replay is unavailable")
        cursor = replay.cursor
        while cursor is None or cursor.clock < decision_at:
            cursor = replay.step(decision_at, self._consume)
            if cursor is None:
                raise RuntimeError("scheduled replay ended before its decision clock")
        current = observations.close(decision_at)
        has_current_gap = any(known == decision_at for _, known in observations.state.gaps)
        value = ScheduledFeatureValue(
            observation=current,
            value=CompletedReturn(self.definition.cadence_seconds).evaluate(previous, current),
            has_current_gap=has_current_gap,
        )
        state = observations.state
        compact = ObservationState(
            points=tuple(point for point in state.points if point.event_at >= decision_at),
            gaps=tuple(gap for gap in state.gaps if gap[0] >= decision_at),
            completed=(current,),
            next_order=state.next_order,
        )
        self._observations = Observations(
            self.definition.binding,
            observations.evidence,
            tick=self.definition.tick,
            cadence=timedelta(seconds=self.definition.cadence_seconds),
            max_age=timedelta(seconds=self.definition.max_age_seconds),
            state=compact,
        )
        return value, compact

    def _consume(self, phase: ReplayPhase, instant: datetime, item: PointEvent | None) -> None:
        """Admit actual source phases without changing already frozen closes."""
        if phase == "source" and item is not None:
            if self._observations is None:
                raise RuntimeError("scheduled observations are unavailable")
            self._observations.admit(item, instant)


class ScheduledFeatureParity(WireRecord, frozen=True):
    """Retain exact saved-input replay, batch and serialized-restart feature traces."""

    reference_sha256: str
    implementation_sha256: str
    replay: ScheduledFeatureCheckpoint
    batch: ScheduledFeatureCheckpoint
    restarted: ScheduledFeatureCheckpoint
    limitations: tuple[str, ...]
    scope: Literal["saved-input-batch"] = "saved-input-batch"
    schema_version: Literal["scheduled-feature-parity"] = "scheduled-feature-parity"

    def __post_init__(self) -> None:
        """Validate identities and compatible trace contracts without concealing disagreement."""
        if self.scope != "saved-input-batch" or self.schema_version != "scheduled-feature-parity":
            raise ValueError("unsupported scheduled feature parity scope or version")
        if (
            type(self.limitations) is not tuple
            or not self.limitations
            or any(type(value) is not str or not value for value in self.limitations)
        ):
            raise ValueError("feature parity must retain its evidence limitations")
        for identity in (self.reference_sha256, self.implementation_sha256):
            if type(identity) is not str or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
                raise ValueError("feature parity requires reference and implementation digests")
        for trace in (self.replay, self.batch, self.restarted):
            if type(trace) is not ScheduledFeatureCheckpoint:
                raise TypeError("feature parity requires complete typed traces")
            trace.__post_init__()
            if (
                trace.definition != self.replay.definition
                or trace.input_identity != self.replay.input_identity
            ):
                raise ValueError("feature parity traces have different definitions or inputs")
        cadence = timedelta(seconds=self.replay.definition.cadence_seconds)
        if (
            not self.replay.values
            or self.replay.values[-1].observation.closed_at + cadence < self.replay.definition.end
        ):
            raise ValueError("feature parity requires a complete nonempty reference schedule")

    @property
    def first_divergence(self) -> str | None:
        """Locate the first exact mismatch, including a missing or extra scheduled decision.

        Returns:
            Mode and decision ordinal/UTC clock for investigation, or None for exact equality.
        """
        for index in range(
            max(len(trace.values) for trace in (self.replay, self.batch, self.restarted))
        ):
            expected = self.replay.values[index] if index < len(self.replay.values) else None
            for name, trace in (("batch", self.batch), ("restarted", self.restarted)):
                actual = trace.values[index] if index < len(trace.values) else None
                if actual != expected:
                    instant = self.replay.definition.start + timedelta(
                        seconds=self.replay.definition.cadence_seconds * (index + 1)
                    )
                    return f"{name} decision {index + 1} at {instant.isoformat()}"
        return None

    @property
    def is_equal(self) -> bool:
        """Report exact equality without claiming empirical or live acceptance.

        Returns:
            True only when all three complete traces agree with zero tolerance.
        """
        return self.first_divergence is None
