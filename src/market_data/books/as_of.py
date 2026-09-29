"""Persist causal book boundaries so as-of queries do not replay a whole delivery log."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

# project library imports
from configuration import BookSelection
from market_data.books.registry import BookRegistry
from market_data.contracts import BookLookup, BookQuote
from serialization import DomainCodec

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS boundaries (position INTEGER PRIMARY KEY, "
    "available_ns INTEGER NOT NULL, boundary BLOB NOT NULL, market BLOB, "
    "offset INTEGER NOT NULL, length INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS boundaries_available ON boundaries(available_ns, position)",
)


class BookAsOfIndex:
    """Index one delivery log's boundaries by availability for as-of lookups.

    The delivery owner appends a row only after that delivery's bytes are durable,
    so the index can lag the log after a crash but never describes bytes that are
    absent. Each row keeps the boundary quote, the priced market it carries and the
    delivery's byte range, exactly as ``BookRegistry`` retained them. A lookup
    therefore equals a registry lookup that kept every boundary, and depth decodes
    only the selected delivery. The index is derived from the log, so its commits
    need not wait for an fsync; a lost tail is reported as partial coverage.
    """

    def __init__(self, path: Path) -> None:
        """Bind an index path; only ``create`` opens a writer."""
        self.path = path
        self._codec = DomainCodec()
        self._writer: sqlite3.Connection | None = None

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
        """Add the next boundary and the durable delivery byte range it was read from."""
        if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0:
            raise ValueError("book as-of index requires a durable delivery byte range")
        available = boundary.available_ns
        if available is None:
            raise ValueError("book as-of index requires known availability")
        connection = self._writer
        if connection is None:
            raise ValueError("book as-of index is not open for appending")
        connection.execute("BEGIN IMMEDIATE")
        try:
            last = cast(
                tuple[int, int, int, int] | None,
                connection.execute(
                    "SELECT position, available_ns, offset, length FROM boundaries "
                    "ORDER BY position DESC LIMIT 1"
                ).fetchone(),
            )
            expected = (0, 0, 0) if last is None else (last[0] + 1, last[1], last[2] + last[3])
            if boundary.position != expected[0] or available < expected[1] or offset != expected[2]:
                raise ValueError("book as-of index requires contiguous nondecreasing boundaries")
            connection.execute(
                "INSERT INTO boundaries VALUES (?, ?, ?, ?, ?, ?)",
                (
                    boundary.position,
                    available,
                    self._codec.encode_json(boundary),
                    None if market is None else self._codec.encode_json(market),
                    offset,
                    length,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

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
            row = cast(
                tuple[bytes, bytes | None, int, int] | None,
                connection.execute(
                    "SELECT boundary, market, offset, length FROM boundaries "
                    "WHERE available_ns <= ? ORDER BY available_ns DESC, position DESC LIMIT 1",
                    (cutoff_ns,),
                ).fetchone(),
            )
            if row is None:
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
            boundary = self._codec.decode_json(row[0], BookQuote)
            market = None if row[1] is None else self._codec.decode_json(row[1], BookQuote)
            reason = BookRegistry._refusal(selection, market, cutoff_ns)
            quote = market if reason == "eligible" else None
            selected_range: tuple[int, int] = (row[2], row[3])
            target = quote if quote is not None else boundary
            if target.position != boundary.position:
                located = cast(
                    tuple[int, int] | None,
                    connection.execute(
                        "SELECT offset, length FROM boundaries WHERE position = ?",
                        (target.position,),
                    ).fetchone(),
                )
                if located is None:
                    raise ValueError("book as-of index lacks the carried market delivery")
                selected_range = located
            connection.rollback()
        return (
            BookLookup(
                selection=selection,
                cutoff_ns=cutoff_ns,
                boundary=boundary,
                quote=quote,
                reason=reason,
            ),
            selected_range,
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only connection; readers never create or change the index."""
        if not self.path.is_file():
            raise ValueError("book as-of index is missing")
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
