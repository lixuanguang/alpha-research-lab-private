"""Join live decision sources and replay followed durable recordings into them."""

from __future__ import annotations

# standard library imports
import hashlib
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

# project library imports
from configuration import CaptureConfig
from market_data.books import BookProjection, CaptureReplay, NativeBook
from market_data.contracts import CaptureRecord
from market_data.storage import RecordingFollower
from research.observations import (
    DecisionInputs,
    DecisionSource,
    InputRequirement,
    LiveBookDecisionSource,
    LiveTradeDecisionSource,
    NamedObservation,
)
from serialization import DomainCodec


class LiveInputs:
    """Read one ordered named projection from several live sources, as one source.

    Each requirement is answered by the first source that declares it, so a book
    source and its instrument's trade source together serve a candidate or a
    feature kernel whose inputs span both. The identity pins the projection and
    every joined source's own identity.
    """

    def __init__(
        self, requirements: tuple[InputRequirement, ...], sources: tuple[DecisionSource, ...]
    ) -> None:
        """Bind the ordered requirements to sources that together declare all of them.

        Raises:
            ValueError: A requirement is repeated or no joined source declares it.
        """
        provided = {item for source in sources for item in source.requirements}
        if (
            type(requirements) is not tuple
            or not requirements
            or len(set(requirements)) != len(requirements)
            or not set(requirements) <= provided
        ):
            raise ValueError("live inputs require distinct requirements their sources declare")
        self._requirements, self._sources = requirements, sources
        self._identity: str | None = None

    @property
    def identity(self) -> str:
        """Pin the ordered projection and each joined source."""
        if self._identity is None:
            self._identity = hashlib.sha256(
                DomainCodec().encode_json(
                    (self._requirements, tuple(source.identity for source in self._sources))
                )
            ).hexdigest()
        return self._identity

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Return the ordered joined requirements."""
        return self._requirements

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Return each requirement's then-known row from its source, in declared order."""
        rows: dict[InputRequirement, NamedObservation] = {}
        for source in self._sources:
            for row in source.read(entity, at).observations:
                rows.setdefault(row.input, row)
        return DecisionInputs(
            entity=entity,
            decision_at=at,
            observations=tuple(rows[item] for item in self._requirements),
        )


class FollowedFeed:
    """Replay one followed recording's durable records into its live source.

    Each record is applied to the collector's native reconstruction and accepted
    on its receipt clock, so the source's state at a cutoff equals a saved
    reconstruction of the same journal, independent of when it was followed.
    Records are buffered from the follower in bounded batches.
    """

    def __init__(
        self,
        follower: RecordingFollower,
        source: LiveBookDecisionSource | LiveTradeDecisionSource,
        *,
        natives: Callable[[CaptureConfig], NativeBook],
        batch: int = 10_000,
    ) -> None:
        """Bind a follower to the live source of the same recording.

        Args:
            follower: Read-only follower of the recording.
            source: Live source bound to that recording's request.
            natives: The installed native book or tape constructor the collector uses.
            batch: Maximum records read from the follower at once.

        Raises:
            ValueError: The source names another recording or the batch is not positive.
        """
        if follower.recording.request != source.request:
            raise ValueError("followed recording differs from its live source")
        if type(batch) is not int or batch <= 0:
            raise ValueError("followed feed requires a positive batch")
        self.follower, self.source = follower, source
        self.accepted = 0
        self._replay = CaptureReplay(source.request.config, book_factory=natives)
        self._pending: deque[CaptureRecord] = deque()
        self._batch = batch

    def next_available_at(self) -> datetime | None:
        """Return the next durable record's receipt availability, or None if none is durable."""
        if not self._pending:
            self._pending.extend(self.follower.poll(max_records=self._batch))
        if not self._pending:
            return None
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=(self._pending[0].received_ns + 999) // 1000
        )

    def accept(self) -> None:
        """Apply and deliver the next durable record on its receipt clock.

        Raises:
            ValueError: No record is pending, or the source refuses the boundary.
        """
        if not self._pending:
            raise ValueError("followed feed has no durable record pending")
        record = self._pending.popleft()
        outcome = self._replay.apply(record)
        row = BookProjection.capture(self.accepted, record, outcome, self._replay)
        self.source.accept(record, row)
        self.accepted += 1

    @property
    def finished(self) -> bool:
        """Report a completed recording whose every durable record was accepted."""
        recording = self.follower.recording
        return (
            not self._pending
            and recording.completed
            and self.accepted == recording.cursor().records
        )
