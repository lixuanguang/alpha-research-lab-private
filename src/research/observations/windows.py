"""Freeze completed event-time windows without revising earlier decisions."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta

# project library imports
from financial_units import Price
from market_data.contracts import ArchiveTrade, Disconnect, Occurrence
from market_data.query import InputBinding, PointEvent, QueryEvidence
from market_data.validation import TradeRevision
from reference_data.eligibility import EligibilityAssertion
from serialization import WireRecord


class TradePoint(WireRecord, frozen=True):
    """Retain one admitted economic revision and its causal logical order."""

    trade_id: int
    revision: str
    event_at: datetime
    known_at: datetime
    order: int
    price: Price

    def __post_init__(self) -> None:
        """Reject malformed clocks, prices and source sequence counters."""
        self._require_utc(self.event_at, field_name="event_at")
        self._require_utc(self.known_at, field_name="known_at")
        if type(self.trade_id) is not int or type(self.order) is not int or self.order < 0:
            raise ValueError("trade point requires integer identity and nonnegative order")
        if type(self.revision) is not str or not self.revision or type(self.price) is not Price:
            raise TypeError("trade point requires revision and price")
        self.price.model_copy()


class Observation(WireRecord, frozen=True):
    """Keep a completed price or an explicit missingness reason at its original close."""

    closed_at: datetime
    point: TradePoint | None
    reason: str

    def __post_init__(self) -> None:
        """Require consistent value/missingness and knowledge at the completed close."""
        self._require_utc(self.closed_at, field_name="closed_at")
        if self.reason not in (
            "valid",
            "missing",
            "stale",
            "known_gap",
            "ineligible",
            "invalid_price",
        ):
            raise ValueError("unsupported observation reason")
        if (self.point is None) != (self.reason != "valid"):
            raise ValueError("observation value and reason disagree")
        if self.point is not None:
            self.point.__post_init__()
            if self.point.event_at >= self.closed_at or self.point.known_at > self.closed_at:
                raise ValueError("observation uses an incomplete or unavailable trade")


class ObservationState(WireRecord, frozen=True):
    """Retain admitted latest revisions, scoped gap clocks and frozen completed windows."""

    points: tuple[TradePoint, ...] = ()
    gaps: tuple[tuple[datetime, datetime], ...] = ()
    completed: tuple[Observation, ...] = ()
    next_order: int = 0

    def __post_init__(self) -> None:
        """Validate immutable history and monotone frozen observation closes."""
        if any(type(value) is not tuple for value in (self.points, self.gaps, self.completed)):
            raise TypeError("observation state requires tuples")
        if type(self.next_order) is not int or self.next_order < 0:
            raise ValueError("invalid source order counter")
        identities: set[int] = set()
        for point in self.points:
            if type(point) is not TradePoint:
                raise TypeError("observation state requires trade points")
            point.__post_init__()
            if point.trade_id in identities or point.order >= self.next_order:
                raise ValueError("duplicate trade head or inconsistent source order")
            identities.add(point.trade_id)
        for event, known in self.gaps:
            self._require_utc(event, field_name="gap event")
            self._require_utc(known, field_name="gap knowledge")
        previous: datetime | None = None
        for observation in self.completed:
            if type(observation) is not Observation:
                raise TypeError("observation state requires completed windows")
            observation.__post_init__()
            if previous is not None and observation.closed_at <= previous:
                raise ValueError("completed observations must have increasing closes")
            previous = observation.closed_at


class Observations:
    """Own admitted information and completed-window state for one explicit input binding."""

    def __init__(
        self,
        binding: InputBinding,
        evidence: tuple[QueryEvidence, ...],
        *,
        tick: Price,
        cadence: timedelta,
        max_age: timedelta,
        state: ObservationState | None = None,
    ) -> None:
        """Bind units and bitemporal eligibility without treating read-ahead as knowledge.

        Args:
            binding: Explicit source, stream and instrument selection.
            evidence: Verified query evidence, including unrelated bindings.
            tick: Positive quote increment and complete dimensions.
            cadence: Positive completed-window width.
            max_age: Positive maximum event age at a close or fill.
            state: Complete observation checkpoint, or None for a fresh consumer.

        Raises:
            ValueError: Clocks, units, binding or checkpoint are incompatible.
        """
        if (
            cadence <= timedelta(0)
            or max_age <= timedelta(0)
            or tick.value <= 0
            or tick.per.instrument_id != binding[2]
        ):
            raise ValueError("invalid observation units or timing")
        self.binding, self.tick, self.cadence, self.max_age = binding, tick, cadence, max_age
        self.evidence = tuple(
            item
            for item in evidence
            if (
                item.request.instrument.source,
                item.request.manifest.job.stream,
                item.request.instrument.instrument_id,
            )
            == binding
        )
        if not self.evidence:
            raise ValueError("observation binding has no admitted evidence")
        self._state = state if state is not None else ObservationState()
        self._state.__post_init__()

    @property
    def state(self) -> ObservationState:
        """Expose completed windows and admitted information for recovery.

        Returns:
            Immutable observation state.
        """
        return self._state

    def admit(self, item: PointEvent, instant: datetime) -> bool:
        """Admit a matching source revision/control only at its replay knowledge clock.

        Args:
            item: Complete source event delivered by chronological replay.
            instant: Current inclusive UTC knowledge clock.

        Returns:
            True only for a newly known applicable gap; unrelated controls stay isolated.

        Raises:
            ValueError: Source availability differs from the current replay clock.
        """
        occurrence = item if isinstance(item, Occurrence) else item.occurrences[0]
        request = occurrence.request
        if (
            request.instrument.source,
            request.manifest.job.stream,
            request.instrument.instrument_id,
        ) != self.binding:
            return False
        state = self._state
        event = occurrence.event
        if isinstance(item, Occurrence) and isinstance(event, Disconnect):
            if event.provenance.ts_knowledge != instant:
                raise ValueError("control admitted outside its knowledge clock")
            self._state = ObservationState(
                points=state.points,
                gaps=(*state.gaps, (event.provenance.ts_event, instant)),
                completed=state.completed,
                next_order=state.next_order,
            )
            return True
        if not isinstance(item, TradeRevision) or isinstance(event, Disconnect):
            raise ValueError("observation requires trade revisions or scoped controls")
        if item.ts_knowledge != instant:
            raise ValueError("revision admitted outside its knowledge clock")
        point = TradePoint(
            trade_id=event.trade_id,
            revision=item.identity,
            event_at=event.ts_event
            if isinstance(event, ArchiveTrade)
            else event.provenance.ts_event,
            known_at=instant,
            order=state.next_order,
            price=Price(value=event.price, currency=self.tick.currency, per=self.tick.per),
        )
        self._state = ObservationState(
            points=(*tuple(old for old in state.points if old.trade_id != point.trade_id), point),
            gaps=state.gaps,
            completed=state.completed,
            next_order=state.next_order + 1,
        )
        return False

    def eligible(self, valid_at: datetime, known_at: datetime) -> bool:
        """Check retained membership at explicit business and knowledge times.

        Args:
            valid_at: Business instant being admitted or valued.
            known_at: Information cutoff; later withdrawals cannot rewrite earlier actions.

        Returns:
            True only when all applicable histories explicitly include this instrument.
        """
        states = [
            item.eligibility.select(self.binding[2], valid_at=valid_at, known_at=known_at)
            for item in self.evidence
            if item.request.start <= valid_at <= item.request.end
        ]
        return bool(states) and all(
            isinstance(state, EligibilityAssertion) and state.state == "included"
            for state in states
        )

    def close(self, instant: datetime) -> Observation:
        """Freeze one completed half-open event window; later corrections cannot revise it.

        Args:
            instant: Scheduled UTC close, strictly later than the previous close.

        Returns:
            Valid observed close or explicit missingness, never a padded price.

        Raises:
            ValueError: A close repeats or reverses the completed schedule.
        """
        state = self._state
        if state.completed and instant <= state.completed[-1].closed_at:
            raise ValueError("observation close must advance")
        observation = self.latest(instant, start=instant - self.cadence, window=True)
        self._state = ObservationState(
            points=state.points,
            gaps=state.gaps,
            completed=(*state.completed, observation),
            next_order=state.next_order,
        )
        return observation

    def latest(self, instant: datetime, *, start: datetime, window: bool = False) -> Observation:
        """Select a fresh eligible mark or completed-window endpoint without mutating history.

        Args:
            instant: Inclusive knowledge cutoff and exclusive event cutoff.
            start: Inclusive event-window start.
            window: Whether any known gap in the entire window invalidates its observation.

        Returns:
            Latest event-time price with logical-order ties, or explicit invalidity.
        """
        candidates = [
            point
            for point in self._state.points
            if start <= point.event_at < instant and point.known_at <= instant
        ]
        point = max(candidates, key=self._event_order) if candidates else None
        reason = "valid"
        if point is None:
            reason = "missing"
        elif point.price.value <= 0:
            reason = "invalid_price"
        elif instant - point.event_at > self.max_age:
            reason = "stale"
        elif not self.eligible(point.event_at, instant) or not self.eligible(instant, instant):
            reason = "ineligible"
        if any(
            known <= instant
            and (start if window or point is None else point.event_at) <= event
            and (event < instant if window else event <= instant)
            for event, known in self._state.gaps
        ):
            reason = "known_gap"
        return Observation(
            closed_at=instant, point=point if reason == "valid" else None, reason=reason
        )

    @staticmethod
    def _event_order(point: TradePoint) -> tuple[datetime, int]:
        """Use causal logical source order for equal event timestamps."""
        return point.event_at, point.order

    def fill_candidates(
        self, decision_at: datetime, delay: timedelta, instant: datetime
    ) -> tuple[TradePoint, ...]:
        """Return then-known trades satisfying both delay clocks in causal order.

        Args:
            decision_at: Pending intent creation time.
            delay: Strictly positive processing/execution delay.
            instant: Current replay fill phase.

        Returns:
            Eligible candidates at their first possible fill clock; old trades never age in.
        """
        threshold = decision_at + delay
        return tuple(
            sorted(
                (
                    point
                    for point in self._state.points
                    if point.event_at >= threshold
                    and point.known_at >= threshold
                    and max(point.event_at, point.known_at) == instant
                    and instant - point.event_at <= self.max_age
                    and self.eligible(point.event_at, instant)
                    and self.eligible(instant, instant)
                ),
                key=self._source_order,
            )
        )

    @staticmethod
    def _source_order(point: TradePoint) -> int:
        """Preserve admitted source precedence for competing execution prints."""
        return point.order

    def next_fill_clock(
        self, decision_at: datetime, delay: timedelta, after: datetime
    ) -> datetime | None:
        """Schedule already-known trades whose exchange clock is still in the future.

        Args:
            decision_at: Pending intent creation clock.
            delay: Positive execution delay.
            after: Last completed simulation clock.

        Returns:
            Earliest future eligible event clock, or None.
        """
        clocks = [
            point.event_at
            for point in self._state.points
            if point.event_at > after
            and point.event_at >= decision_at + delay
            and point.known_at >= decision_at + delay
        ]
        return min(clocks) if clocks else None
