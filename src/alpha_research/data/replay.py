"""Step bounded reference history through one shared chronological phase order."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from bisect import bisect_right
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import ClassVar, Literal

# project library imports
from alpha_research.data.asof import EconomicOrder, PointEvent
from alpha_research.data.events import Disconnect
from alpha_research.data.normalization import Occurrence
from alpha_research.data.query import QueryEvidence, QueryReader
from alpha_research.data.revisions import TradeRevision
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import _ReferenceRecord
from alpha_research.serialization import DomainCodec

type ReplayPhase = Literal["source", "expiry", "fill", "decision", "mark"]


class ReplayCursor(_ReferenceRecord, frozen=True, kw_only=True):
    """Identify a completed step, bound inputs/configuration and last logical source position.

    Serialize with DomainCodec. This cursor does not contain consumer observations,
    scheduled times or economics; save and restore those with the completed cursor.
    """

    identity: str
    clock: datetime
    position: EconomicOrder | None

    def __post_init__(self) -> None:
        """Reject malformed identities, clocks and logical positions.

        Raises:
            ValueError: An identity or position is invalid.
            TypeError: A clock is not aware UTC.
        """
        if (
            not isinstance(self.identity, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.identity) is None
        ):
            raise ValueError("replay cursor requires a SHA-256 identity")
        self._require_utc(self.clock, field_name="clock")
        if self.position is not None:
            if type(self.position) is not tuple or len(self.position) != 5:
                raise ValueError("replay cursor requires a logical source position")
            for instant in (self.position[0], self.position[2]):
                self._require_utc(instant, field_name="position")
            if self.position[0] > self.clock or any(
                type(value) is not int or value < 0
                for value in (self.position[1], self.position[3], self.position[4])
            ):
                raise ValueError("replay cursor position must be nonnegative and already known")


class _EventSteps[Event]:
    """Share completed-clock phases and cursor recovery across admitted event formats."""

    _phases: ClassVar[tuple[ReplayPhase, ...]] = ("expiry", "fill", "decision", "mark")

    def __init__(
        self,
        ordered: dict[EconomicOrder, Event],
        *,
        identity: str,
        terminal: datetime,
        cursor: ReplayCursor | None,
    ) -> None:
        """Bind an owned ordered reference and validate its completed checkpoint."""
        ReplayCursor._require_utc(terminal, field_name="terminal")
        self._identity = identity
        self._keys = tuple(sorted(ordered))
        self._events = tuple(ordered[key] for key in self._keys)
        self._times = tuple(key[0] for key in self._keys)
        self._terminal = terminal
        self._index = 0
        self._cursor = deepcopy(cursor)
        self._is_stepping = False
        if cursor is not None:
            if type(cursor) is not ReplayCursor:
                raise TypeError("replay requires a ReplayCursor")
            cursor.__post_init__()
            self._index = bisect_right(self._times, cursor.clock)
            position = self._keys[self._index - 1] if self._index else None
            if (
                cursor.identity != self._identity
                or cursor.clock > terminal
                or cursor.position != position
            ):
                raise ValueError("incompatible or incomplete replay checkpoint")

    @property
    def cursor(self) -> ReplayCursor | None:
        """Expose a checkpoint only outside an active or failed step.

        Returns:
            Last completed cursor, or None before the first step.

        Raises:
            RuntimeError: An incomplete callback sequence cannot be checkpointed.
        """
        if self._is_stepping:
            raise RuntimeError("incomplete replay step; restore the last completed checkpoint")
        return deepcopy(self._cursor)

    def step(
        self,
        scheduled_at: datetime,
        consume: Callable[[ReplayPhase, datetime, Event | None], None],
    ) -> ReplayCursor | None:
        """Advance to the next source, consumer wakeup or terminal, in fixed phase order.

        Args:
            scheduled_at: Earliest outstanding decision, expiry or additional fill-eligibility
                time, in UTC. Recompute after each step; it must exceed the completed clock.
                Use terminal when there is no earlier consumer wakeup.
            consume: Synchronous callback for each source event, then expiry, fill, decision
                and mark with None. Evaluate only due decisions; enforce expiry and fill
                eligibility in their owning libraries. Exceptions propagate and poison this
                replay instance: restore both cursor and consumer state before retrying.

        Returns:
            Completed cursor, or None if terminal was already completed. All equal-time
            sources are admitted before other phases regardless of original query batches.

        Raises:
            ValueError: A scheduled time would repeat or reverse the completed clock.
            TypeError: The scheduled clock is not aware UTC.
            RuntimeError: Reentrant or previously failed stepping is refused.
        """
        cursor = self.cursor
        ReplayCursor._require_utc(scheduled_at, field_name="scheduled_at")
        if cursor is not None and cursor.clock == self._terminal:
            return None
        if cursor is not None and scheduled_at <= cursor.clock:
            raise ValueError("scheduled time must follow the completed replay clock")
        instant = min(scheduled_at, self._terminal)
        if self._index < len(self._keys):
            instant = min(instant, self._times[self._index])
        self._is_stepping = True
        while self._index < len(self._keys) and self._times[self._index] == instant:
            consume("source", instant, deepcopy(self._events[self._index]))
            self._index += 1
        for phase in self._phases:
            consume(phase, instant, None)
        self._cursor = ReplayCursor(
            identity=self._identity,
            clock=instant,
            position=self._keys[self._index - 1] if self._index else None,
        )
        self._is_stepping = False
        return self.cursor


class Replay(_EventSteps[PointEvent]):
    """Own a bounded ordered reference and per-consumer clock, with no economic state.

    History admission reads ahead within QueryReader's aggregate canonical-byte cap.
    Memory includes all retained versions and their sorted index, not just one batch.
    Only step callbacks advance knowledge. Unknown availability is never scheduled;
    membership and quality remain explicit evidence, not automatic trading permission.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self,
        reader: QueryReader,
        instruments: tuple[InstrumentId, ...],
        *,
        start: datetime,
        end: datetime,
        terminal: datetime,
        config_identity: str,
        batch_size: int,
        cursor: ReplayCursor | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Order admitted query history and optionally restore a completed source position.

        Args:
            reader: Verified, byte-capped trade/control reference with frozen precedence.
            instruments: Explicit supported subscription selection.
            start: Inclusive UTC business-window start; earlier controls are retained.
            end: Exclusive UTC business-window end; terminal controls are retained.
            terminal: Inclusive final UTC knowledge/step time.
            config_identity: SHA-256 of the consumer's resolved configuration and timing rules.
            batch_size: Positive query delivery bound; cannot affect order or cursor identity.
            cursor: Completed step, restored together with consumer state and pending schedule.
            cancelled: Cooperative query cancellation checked before and between batches.

        Raises:
            ValueError: Query admission, ordering, configuration or checkpoint is incompatible.
            TypeError: A clock or checkpoint has an invalid type.
            InterruptedError: Query admission is cancelled.
        """
        if (
            not isinstance(config_identity, str)
            or re.fullmatch(r"[0-9a-f]{64}", config_identity) is None
        ):
            raise ValueError("replay requires a resolved configuration SHA-256")
        ordered: dict[EconomicOrder, PointEvent] = {}
        batches = reader.batches(
            instruments,
            start=start,
            end=end,
            known_at=terminal,
            columns=("revision",),
            batch_size=batch_size,
            mode="history",
            cancelled=cancelled,
        )
        for batch in batches:
            for row in batch.rows:
                if isinstance(row, Occurrence):
                    if not isinstance(row.event, Disconnect):
                        raise TypeError("replay requires scoped disconnect controls")
                    reader._selector._insert(
                        ordered, row, row.event.provenance.ts_knowledge, (row,)
                    )
                else:
                    version = row.values[0]
                    if not isinstance(version, TradeRevision):
                        raise TypeError("replay requires complete trade revisions")
                    while version is not None:
                        known_at = version.ts_knowledge
                        if known_at is not None:
                            reader._selector._insert(
                                ordered, version, known_at, version.occurrences
                            )
                        version = version.previous
        identity = hashlib.sha256(
            self._codec.encode_json(("reference-replay-v1", batch.identity, config_identity))
        ).hexdigest()
        self._evidence = batch.evidence
        super().__init__(ordered, identity=identity, terminal=terminal, cursor=cursor)

    @property
    def evidence(self) -> tuple[QueryEvidence, ...]:
        """Retain isolated quality and bitemporal membership for cutoff-aware consumers.

        Returns:
            Complete selected query evidence, including unknown availability/eligibility.
        """
        return deepcopy(self._evidence)
