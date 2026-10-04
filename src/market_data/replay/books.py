"""Stream saved book messages and step known receipts on the shared replay clock."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
from collections.abc import Callable, Generator, Iterator
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import batched
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

# project library imports
from market_data.contracts import BookObservation
from market_data.datasets import BookSnapshot, CaptureInput, DatasetReaders
from market_data.query import EconomicOrder
from market_data.replay.events import ReplayCursor, ReplayPhase, _EventSteps
from market_data.storage import RawStore
from serialization import DomainCodec


class BookReplay:
    """Own a streaming native partition and a completed causal cursor.

    Receipt nanoseconds remain exact; scheduling rounds upwards to microseconds.
    Consumer state must be saved with the cursor. Unknown archive availability is
    never scheduled. Streamed snapshots retain only one lookahead and a delivery
    batch.
    """

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        identity: str,
        request_identity: str,
        terminal: datetime,
        config_identity: str,
        max_bytes: int,
        batch_size: int,
        cursor: ReplayCursor | None = None,
    ) -> BookReplay:
        """Verify a complete snapshot and open one explicitly selected native partition.

        Args:
            directory: Protected immutable publication root.
            raw: Retained originals for independent admission.
            readers: Explicit source decoders.
            identity: Immutable snapshot SHA-256.
            request_identity: Native request identity in that snapshot.
            terminal: Inclusive final UTC step time.
            config_identity: Resolved consumer configuration SHA-256.
            max_bytes: Positive per-file admission cap.
            batch_size: Positive whole-message delivery bound.
            cursor: Completed checkpoint paired with consumer state.

        Returns:
            Isolated source stream, evidence and shared replay phase semantics.
        """
        snapshot = BookSnapshot.read(
            directory, raw, readers=readers, identity=identity, max_bytes=max_bytes
        )
        return cls(
            snapshot,
            request_identity=request_identity,
            terminal=terminal,
            config_identity=config_identity,
            batch_size=batch_size,
            cursor=cursor,
        )

    def __init__(
        self,
        snapshot: BookSnapshot,
        *,
        request_identity: str,
        terminal: datetime,
        config_identity: str,
        batch_size: int,
        cursor: ReplayCursor | None = None,
    ) -> None:
        """Reuse explicit whole-snapshot admission without repeating raw reconstruction.

        Receipt ordering and the restored position are validated before any
        consumer callback.

        Args:
            snapshot: Verified session whose immutable stores remain protected.
            request_identity: Selected native partition.
            terminal: Inclusive final UTC step time.
            config_identity: Consumer configuration SHA-256.
            batch_size: Positive whole-message delivery bound.
            cursor: Completed cursor paired with restored consumer state.

        Raises:
            ValueError: Selection, ordering, identity or checkpoint is incompatible.
        """
        selected = snapshot.selection(request_identity)
        self._snapshot = snapshot
        self._request_identity = request_identity
        self._input_bytes = DomainCodec().encode_json(selected)
        identity = hashlib.sha256(
            DomainCodec().encode_json(
                (
                    "book-replay-stream",
                    snapshot.identity,
                    snapshot.partition(request_identity).sha256,
                    terminal,
                    config_identity,
                )
            )
        ).hexdigest()
        ReplayCursor(identity=config_identity, clock=terminal, position=None)
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("book replay requires positive batch_size")
        self._identity, self._terminal, self._batch_size = identity, terminal, batch_size
        self._position: EconomicOrder | None = None
        self._cursor: ReplayCursor | None = None
        self._is_stepping = False
        self._is_closed = False
        if cursor is not None:
            if type(cursor) is not ReplayCursor:
                raise TypeError("replay requires a ReplayCursor")
            cursor.__post_init__()
            if cursor.identity != identity or cursor.clock > terminal:
                raise ValueError("incompatible or incomplete replay checkpoint")
        # The pass is bounded by one row, and rejects a late clock regression before
        # callbacks can commit any economics. Unknown archive clocks need no scan.
        for key, _ in self._known():
            if cursor is not None and key[0] <= cursor.clock:
                self._position = key
        if cursor is not None and cursor.position != self._position:
            raise ValueError("incompatible or incomplete replay checkpoint")
        self._cursor = deepcopy(cursor)
        self._stream = self._known()
        self._next: tuple[EconomicOrder, BookObservation] | None = next(self._stream, None)
        if cursor is not None:
            while self._next is not None and self._next[0][0] <= cursor.clock:
                self._next = next(self._stream, None)

    def close(self) -> None:
        """Release an unfinished file stream; create a new replay to resume its cursor."""
        self._stream.close()
        self._next = None
        self._is_closed = True

    @property
    def evidence(self) -> CaptureInput:
        """Return isolated provenance; archive clocks and degraded scope stay unchanged."""
        return DomainCodec().decode_json(self._input_bytes, CaptureInput)

    @property
    def cursor(self) -> ReplayCursor | None:
        """Return the last completed cursor; refuse incomplete or failed callback steps."""
        if self._is_stepping:
            raise RuntimeError("incomplete replay step; restore the last completed checkpoint")
        return deepcopy(self._cursor)

    def batches(self) -> Iterator[tuple[BookObservation, ...]]:
        """Yield fresh whole-message batches without retaining a second history copy.

        Yields:
            Original messages and controls, including unschedulable archive records.
        """
        if self._is_closed:
            raise RuntimeError("book replay is closed")
        yield from batched(self._observations(), self._batch_size)

    def _observations(self) -> Generator[BookObservation]:
        """Decode the verified bounded file stream."""
        yield from self._snapshot.observations(self._request_identity)

    def _known(self) -> Generator[tuple[EconomicOrder, BookObservation]]:
        """Stream native source order, ordering equal receipts by epoch then position."""
        # Native receipts are normally distinct, so keep only one pending row.
        # Capture permits a prior-epoch stale snapshot at the same receipt as a
        # newer session. The cursor orders that tie by epoch then raw position.
        # Spill only tied groups to disk; even an all-tied partition cannot
        # retain a second full book history in Python memory.
        spill: TemporaryDirectory[str] | None = None
        connection: sqlite3.Connection | None = None
        codec = DomainCodec()
        try:
            with closing(self._scheduled()) as scheduled:
                pending = next(scheduled, None)
                while pending is not None:
                    current = pending
                    pending = next(scheduled, None)
                    if pending is None or pending[0][1] != current[0][1]:
                        yield current
                        continue
                    if connection is None:
                        spill = TemporaryDirectory(prefix="book-replay-ties-")
                        connection = sqlite3.connect(Path(spill.name) / "ties.sqlite")
                        connection.execute("PRAGMA journal_mode=OFF")
                        connection.execute("PRAGMA synchronous=OFF")
                        connection.execute("PRAGMA temp_store=FILE")
                        connection.execute("PRAGMA cache_size=-2048")
                        connection.execute(
                            "CREATE TABLE ties ("
                            "position INTEGER PRIMARY KEY, epoch_key BLOB NOT NULL, "
                            "observation BLOB NOT NULL)"
                        )
                        connection.execute("CREATE INDEX ties_order ON ties(epoch_key, position)")
                    connection.execute("DELETE FROM ties")
                    self._store_tie(connection, current, codec)
                    receipt_ns = current[0][1]
                    while pending is not None and pending[0][1] == receipt_ns:
                        self._store_tie(connection, pending, codec)
                        pending = next(scheduled, None)
                    rows = cast(
                        Iterator[tuple[object, ...]],
                        connection.execute(
                            "SELECT observation FROM ties ORDER BY epoch_key, position"
                        ),
                    )
                    for encoded_row in rows:
                        if len(encoded_row) != 1 or type(encoded_row[0]) is not bytes:
                            raise ValueError("invalid replay tie spill row")
                        row = codec.decode_json(encoded_row[0], BookObservation)
                        instant = current[0][0]
                        yield (
                            (
                                instant,
                                receipt_ns,
                                instant,
                                row.epoch or 0,
                                row.position,
                            ),
                            row,
                        )
        finally:
            if connection is not None:
                connection.close()
            if spill is not None:
                spill.cleanup()

    @staticmethod
    def _store_tie(
        connection: sqlite3.Connection,
        item: tuple[EconomicOrder, BookObservation],
        codec: DomainCodec,
    ) -> None:
        """Index a tied occurrence with an arbitrary-width nonnegative epoch key."""
        key, row = item
        epoch_digits = str(key[3]).encode("ascii")
        epoch_key = len(epoch_digits).to_bytes(8, "big") + epoch_digits
        connection.execute(
            "INSERT INTO ties(position, epoch_key, observation) VALUES (?, ?, ?)",
            (key[4], epoch_key, codec.encode_json(row)),
        )

    def _scheduled(self) -> Generator[tuple[EconomicOrder, BookObservation]]:
        """Retain receipt regression checks and round nanoseconds upward for UTC steps."""
        if self.evidence.archive is not None:
            self._snapshot.verify_partition(self._request_identity)
            return
        previous_ns = 0
        with closing(self._observations()) as observations:
            for row in observations:
                if row.received_ns is None:
                    continue
                if row.received_ns < previous_ns:
                    raise ValueError("book replay receipt order regressed")
                previous_ns = row.received_ns
                instant = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                    microseconds=(row.received_ns + 999) // 1000
                )
                if instant <= self._terminal:
                    yield (instant, row.received_ns, instant, row.epoch or 0, row.position), row

    def step(
        self,
        scheduled_at: datetime,
        consume: Callable[[ReplayPhase, datetime, BookObservation | None], None],
    ) -> ReplayCursor | None:
        """Advance source, expiry, fill, decision and mark phases at the next safe clock.

        Args:
            scheduled_at: Earliest pending consumer wakeup, strictly after completed time.
            consume: Callback receiving every equal-time source before other phases.
                A failure poisons this instance; restore cursor and consumer state together.

        Returns:
            Completed cursor, or None after terminal. Scheduling never uses source time
            as a substitute for unknown original availability.

        Raises:
            ValueError: A schedule repeats or reverses the completed clock.
            RuntimeError: A callback failed or attempted reentrant stepping.
        """
        if self._is_closed:
            raise RuntimeError("book replay is closed")
        cursor = self.cursor
        ReplayCursor._require_utc(scheduled_at, field_name="scheduled_at")
        if cursor is not None and cursor.clock == self._terminal:
            return None
        if cursor is not None and scheduled_at <= cursor.clock:
            raise ValueError("scheduled time must follow the completed replay clock")
        instant = min(scheduled_at, self._terminal)
        if self._next is not None:
            instant = min(instant, self._next[0][0])
        self._is_stepping = True
        while self._next is not None and self._next[0][0] == instant:
            key, row = self._next
            consume("source", instant, row)
            self._position = key
            self._next = next(self._stream, None)
        for phase in _EventSteps._phases:
            consume(phase, instant, None)
        self._cursor = ReplayCursor(identity=self._identity, clock=instant, position=self._position)
        self._is_stepping = False
        return self.cursor
