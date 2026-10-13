"""Persist causal book boundaries so as-of queries do not replay a whole delivery log."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

# project library imports
from configuration import BookSelection
from market_data.books.registry import BookRegistry
from market_data.contracts import BookLookup, BookQuote
from serialization import DomainCodec, ReferenceFrames, SqliteLayout

_SCHEMA = (
    "CREATE TABLE boundaries (position INTEGER PRIMARY KEY, "
    "available_ns INTEGER NOT NULL, boundary BLOB NOT NULL, market_position INTEGER, "
    "offset INTEGER NOT NULL, length INTEGER NOT NULL)",
    "CREATE TABLE boundary_reference (id INTEGER PRIMARY KEY CHECK(id = 1), "
    "position INTEGER NOT NULL, payload BLOB NOT NULL)",
)


@dataclass(frozen=True, slots=True)
class _Tail:
    """Keep the newest committed row's continuation and the market it carries."""

    position: int
    available_ns: int
    end: int
    market: BookQuote | None


class BookAsOfIndex:
    """Index one delivery log's boundaries by availability for as-of lookups.

    The delivery owner appends a row only after that delivery's bytes are durable,
    so the index can lag the log after a crash but never describes bytes that are
    absent. Each row keeps the boundary quote, the position of the priced market it
    carries and the delivery's byte range, exactly as ``BookRegistry`` retained them.
    A lookup therefore equals a registry lookup that kept every boundary, and depth
    decodes only the selected delivery. The index is derived from the log, so its
    commits need not wait for an fsync; a lost tail is reported as partial coverage.

    A carried market is always a boundary the index already holds, its own row's or
    the one the previous row carried, so a row names that position instead of
    repeating the quote. Each boundary is stored as a reference frame against the
    first market the log carried (``boundary_reference``, written with that row);
    rows before it are plain frames. Availability never decreases with position, so a
    lookup finds its row by binary search on the position key, and no availability
    index is kept.
    """

    _maximum_quote_bytes: ClassVar[int] = 1_048_576
    _label: ClassVar[str] = "book as-of index boundary"

    def __init__(self, path: Path) -> None:
        """Bind an index path; only ``create`` opens a writer."""
        self.path = path
        self._codec = DomainCodec()
        self._writer: sqlite3.Connection | None = None
        self._tail: _Tail | None = None
        self._plain = ReferenceFrames(
            None, maximum_bytes=self._maximum_quote_bytes, label=self._label
        )
        # Written once and never changed: kept after it is first written or read.
        self._reference: tuple[int, ReferenceFrames] | None = None
        self._layout_checked = False

    @classmethod
    def create(cls, path: Path) -> BookAsOfIndex:
        """Create an empty index for a new delivery log and keep its writer open."""
        if path.exists():
            raise ValueError("book as-of index already exists")
        index = cls(path)
        # One owner appends in delivery order, possibly from a worker thread.
        writer = sqlite3.connect(path, timeout=5, check_same_thread=False)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA synchronous=NORMAL")
        for statement in _SCHEMA:
            writer.execute(statement)
        writer.commit()
        index._writer = writer
        return index

    def close(self) -> None:
        """Release the writer; retained rows stay readable."""
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def append(
        self, boundary: BookQuote, market: BookQuote | None, *, offset: int, length: int
    ) -> None:
        """Add the next boundary and the durable delivery byte range it was read from.

        Raises:
            ValueError: The range is not durable and contiguous, the position or
                availability does not continue the index, the market is neither this
                boundary nor the one the previous row carried, or no writer is open.
        """
        if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0:
            raise ValueError("book as-of index requires a durable delivery byte range")
        available = boundary.available_ns
        if available is None:
            raise ValueError("book as-of index requires known availability")
        connection = self._writer
        if connection is None:
            raise ValueError("book as-of index is not open for appending")
        tail = self._tail
        expected = (0, 0, 0) if tail is None else (tail.position + 1, tail.available_ns, tail.end)
        if boundary.position != expected[0] or available < expected[1] or offset != expected[2]:
            raise ValueError("book as-of index requires contiguous nondecreasing boundaries")
        market_position: int | None
        if market is None:
            market_position = None
        elif market.position == boundary.position and market == boundary:
            market_position = boundary.position
        elif tail is not None and market == tail.market:
            market_position = market.position
        else:
            raise ValueError("book as-of index market must be a boundary it retains")
        encoded = self._codec.encode_json(boundary)
        reference = self._reference
        connection.execute("BEGIN IMMEDIATE")
        try:
            if reference is None and market is not None:
                payload = self._codec.encode_json(market)
                connection.execute(
                    "INSERT INTO boundary_reference VALUES (1, ?, ?)",
                    (boundary.position, payload),
                )
                reference = (boundary.position, self._frames(payload))
            frames = self._plain if reference is None else reference[1]
            connection.execute(
                "INSERT INTO boundaries VALUES (?, ?, ?, ?, ?, ?)",
                (
                    boundary.position,
                    available,
                    frames.encode(encoded),
                    market_position,
                    offset,
                    length,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        self._reference = reference
        self._tail = _Tail(boundary.position, available, offset + length, market)

    def covered_bytes(self) -> int:
        """Return the delivery log prefix the index describes."""
        with closing(self._connect()) as connection:
            row = cast(
                tuple[int, int] | None,
                connection.execute(
                    "SELECT offset, length FROM boundaries ORDER BY position DESC LIMIT 1"
                ).fetchone(),
            )
        return 0 if row is None else row[0] + row[1]

    def lookup(
        self, selection: BookSelection, *, cutoff_ns: int
    ) -> tuple[BookLookup, tuple[int, int] | None]:
        """Return the registry lookup at a cutoff and the selected market's delivery range.

        The range belongs to the eligible quote when there is one, otherwise to the
        boundary, so depth is read from the same delivery the lookup reports.
        """
        if type(cutoff_ns) is not int or cutoff_ns < 0:
            raise ValueError("registry cutoff must be nonnegative integer nanoseconds")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            position = self._last_available(connection, cutoff_ns)
            if position is None:
                any_row = cast(
                    tuple[int] | None,
                    connection.execute("SELECT 1 FROM boundaries LIMIT 1").fetchone(),
                )
                return (
                    BookLookup(
                        selection=selection,
                        cutoff_ns=cutoff_ns,
                        boundary=None,
                        quote=None,
                        reason="not_yet_available" if any_row is not None else "missing",
                    ),
                    None,
                )
            reference = self._read_reference(connection)
            frame, market_position, offset, length = self._row(connection, position)
            boundary = self._quote(frame, position, reference)
            market: BookQuote | None = None
            market_range = (offset, length)
            if market_position == position:
                market = boundary
            elif market_position is not None:
                carried, _, carried_offset, carried_length = self._row(connection, market_position)
                market = self._quote(carried, market_position, reference)
                market_range = (carried_offset, carried_length)
            connection.rollback()
        reason = BookRegistry._refusal(selection, market, cutoff_ns)
        quote = market if reason == "eligible" else None
        return (
            BookLookup(
                selection=selection,
                cutoff_ns=cutoff_ns,
                boundary=boundary,
                quote=quote,
                reason=reason,
            ),
            market_range if quote is not None else (offset, length),
        )

    @staticmethod
    def _last_available(connection: sqlite3.Connection, cutoff_ns: int) -> int | None:
        """Return the last position available at the cutoff, by binary search.

        Positions are contiguous from zero and availability never decreases with
        position, so the positions available at any cutoff are a prefix.
        """
        newest = cast(
            tuple[int | None],
            connection.execute("SELECT max(position) FROM boundaries").fetchone(),
        )[0]
        low, high, found = 0, -1 if newest is None else newest, None
        while low <= high:
            middle = (low + high) // 2
            row = cast(
                tuple[int] | None,
                connection.execute(
                    "SELECT available_ns FROM boundaries WHERE position = ?", (middle,)
                ).fetchone(),
            )
            if row is None:
                raise ValueError("book as-of index positions are not contiguous")
            if row[0] <= cutoff_ns:
                found, low = middle, middle + 1
            else:
                high = middle - 1
        return found

    @staticmethod
    def _row(connection: sqlite3.Connection, position: int) -> tuple[bytes, int | None, int, int]:
        """Read one row's boundary frame, carried market position and byte range."""
        row = cast(
            tuple[object, object, object, object] | None,
            connection.execute(
                "SELECT boundary, market_position, offset, length FROM boundaries "
                "WHERE position = ?",
                (position,),
            ).fetchone(),
        )
        if row is None:
            raise ValueError("book as-of index lacks the carried market delivery")
        frame, market_position, offset, length = row
        if (
            type(frame) is not bytes
            or (
                market_position is not None
                and (type(market_position) is not int or not 0 <= market_position <= position)
            )
            or type(offset) is not int
            or type(length) is not int
        ):
            raise ValueError("book as-of index row is malformed")
        return frame, market_position, offset, length

    def _quote(
        self, frame: bytes, position: int, reference: tuple[int, ReferenceFrames] | None
    ) -> BookQuote:
        """Decode one stored boundary and require the position its row is keyed by."""
        frames = self._plain if reference is None or position < reference[0] else reference[1]
        quote = self._codec.decode_json(frames.decode(frame), BookQuote)
        if quote.position != position:
            raise ValueError("book as-of index boundary differs from its position")
        return quote

    def _read_reference(self, connection: sqlite3.Connection) -> tuple[int, ReferenceFrames] | None:
        """Return the first position framed against the reference, and its frames."""
        if self._reference is not None:
            return self._reference
        row = cast(
            tuple[object, object] | None,
            connection.execute(
                "SELECT position, payload FROM boundary_reference WHERE id = 1"
            ).fetchone(),
        )
        if row is None:
            return None
        position, payload = row
        if type(position) is not int or type(payload) is not bytes:
            raise ValueError("book as-of index reference is malformed")
        self._reference = (position, self._frames(payload))
        return self._reference

    def _frames(self, reference: bytes) -> ReferenceFrames:
        """Frame boundaries against one retained market's exact bytes."""
        return ReferenceFrames(
            reference, maximum_bytes=self._maximum_quote_bytes, label=self._label
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only connection to an index in the current layout.

        Readers never create or change the index. The layout is checked on this
        reader's first connection, and an index in another layout is refused.
        """
        if not self.path.is_file():
            raise ValueError("book as-of index is missing")
        connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        if not self._layout_checked:
            try:
                SqliteLayout.require(connection, _SCHEMA, "unsupported book as-of index schema")
            except BaseException:
                connection.close()
                raise
            self._layout_checked = True
        return connection
