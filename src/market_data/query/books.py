"""Project known native book states with receipt-clock windows and mandatory controls."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, NamedTuple

# project library imports
from market_data.contracts import BookObservation, Level, Order
from market_data.datasets import (
    BookInput,
    BookSnapshot,
    DatasetReaders,
)
from market_data.storage import RawStore
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord

type BookColumn = Literal["orders", "bids", "asks"]
type BookValue = tuple[Order, ...] | tuple[tuple[Decimal, Level], ...]


class BookQuery(WireRecord, frozen=True, kw_only=True):
    """Pin one native partition and receipt interval without inventing source availability.

    Receipt window is [start, end); known_at is inclusive UTC, compared to original
    integer nanoseconds. All earlier known controls survive projection. Archives
    with unknown original availability yield no decision-eligible states.
    """

    snapshot_id: str
    request_identity: str
    instrument: InstrumentId
    start: datetime
    end: datetime
    known_at: datetime
    columns: tuple[BookColumn, ...]
    batch_size: int
    max_bytes: int
    clock: Literal["receipt"] = "receipt"

    def __post_init__(self) -> None:
        """Reject unsupported fields, clocks, identifiers and unbounded reads."""
        for value in (self.snapshot_id, self.request_identity):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("book query requires explicit SHA-256 identities")
        for name, instant in (
            ("start", self.start),
            ("end", self.end),
            ("known_at", self.known_at),
        ):
            self._require_utc(instant, field_name=name)
        if (
            type(self.instrument) is not InstrumentId
            or self.end <= self.start
            or self.clock != "receipt"
            or any(
                type(value) is not int or value <= 0 for value in (self.batch_size, self.max_bytes)
            )
            or type(self.columns) is not tuple
            or not self.columns
            or any(column not in ("orders", "bids", "asks") for column in self.columns)
            or len(set(self.columns)) != len(self.columns)
        ):
            raise ValueError("invalid book query instrument, receipt window, fields or bounds")


class BookMarketRow(NamedTuple):
    """Retain whole-message identity, original clocks and quality beside exact selected values."""

    position: int
    epoch: int | None
    received_ns: int
    source_time: str | None
    sequence: int | None
    state_identity: str
    status: str
    reason: str
    values: tuple[BookValue, ...]


class BookQueryBatch(NamedTuple):
    """Keep native units/provenance, coverage limits and complete controls even with no values."""

    identity: str
    columns: tuple[BookColumn, ...]
    rows: tuple[BookMarketRow | BookObservation, ...]
    evidence: BookInput
    reasons: tuple[str, ...]


class BookQueryReader:
    """Read an admitted native prefix without treating it as trades or executable liquidity."""

    def __init__(self, snapshot: BookSnapshot) -> None:
        """Bind one explicitly verified immutable snapshot for repeated bounded queries."""
        self._snapshot = snapshot

    @classmethod
    def open(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        identity: str,
        max_bytes: int,
    ) -> BookQueryReader:
        """Verify all native partitions once and retain a session over protected files.

        Args:
            directory: Immutable publication root, protected from external mutation.
            raw: Retained original objects for independent native reconstruction.
            readers: Explicit source decoders.
            identity: Complete pinned snapshot identity.
            max_bytes: Positive per-file admission cap.

        Returns:
            Reader whose batches decode fresh records without re-admitting raw inputs.
        """
        return cls(
            BookSnapshot.read(
                directory, raw, readers=readers, identity=identity, max_bytes=max_bytes
            )
        )

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        query: BookQuery,
    ) -> tuple[BookQueryBatch, ...]:
        """Verify and collect one result; use open/batches for bounded repeated reads.

        Args:
            directory: Protected immutable snapshot root.
            raw: Original objects required by complete admission.
            readers: Explicit native source decoders.
            query: Pinned partition, instrument, fields and receipt/knowledge bounds.

        Returns:
            Collected batches with the original convenience API's result-sized memory cost.

        Raises:
            ValueError: Admission, selected identity, units or capabilities disagree.
            OSError: Retained bytes are unavailable.
        """
        query.__post_init__()
        reader = cls.open(
            directory, raw, readers=readers, identity=query.snapshot_id, max_bytes=query.max_bytes
        )
        return tuple(reader.batches(query))

    def batches(self, query: BookQuery) -> Iterator[BookQueryBatch]:
        """Stream fresh, isolated projections with at most one selected batch in memory.

        Args:
            query: Receipt interval [start, end), inclusive knowledge cutoff, and limits.

        Yields:
            Whole messages and earlier controls; at least one evidence batch. When no
            market values qualify, every batch explicitly records their absence.

        Raises:
            ValueError: Query bindings, byte limits or pinned canonical bytes disagree.
        """
        query.__post_init__()
        if query.snapshot_id != self._snapshot.identity:
            raise ValueError("book query differs from verified snapshot")
        self._snapshot.require_limit(query.max_bytes)
        selected = self._snapshot.selection(query.request_identity)
        if selected.request.config.instrument_id != query.instrument:
            raise ValueError("book query instrument differs from pinned request")
        capture = selected.capture
        if capture is not None and capture.universes is not None:
            capture.universes.require(query.instrument, "research")
        is_l3 = capture is not None and capture.config.channel in ("R0", "level3")
        supported = ("orders",) if is_l3 else ("bids", "asks")
        if any(column not in supported for column in query.columns):
            raise ValueError("book fields incompatible with native L2/L3 representation")
        identity = hashlib.sha256(
            DomainCodec().encode_json(
                (
                    "book-query",
                    query.snapshot_id,
                    query.request_identity,
                    query.instrument,
                    query.start,
                    query.end,
                    query.known_at,
                    query.columns,
                    query.clock,
                )
            )
        ).hexdigest()
        reasons = ["visible depth only; coverage and historical eligibility unproven"]
        if selected.archive is not None:
            reasons.append("original book availability unknown; no decision-eligible values")
        chunk: list[BookMarketRow | BookObservation] = []
        has_values = any(isinstance(row, BookMarketRow) for row in self._selected(query))
        if not has_values:
            reasons.append("no selected book values; absence does not establish an empty market")
        has_batches = False
        for row in self._selected(query):
            if len(chunk) == query.batch_size:
                yield BookQueryBatch(
                    identity,
                    query.columns,
                    tuple(chunk),
                    self._snapshot.selection(query.request_identity),
                    tuple(reasons),
                )
                has_batches = True
                chunk = []
            chunk.append(row)
        if chunk or not has_batches:
            yield BookQueryBatch(
                identity,
                query.columns,
                tuple(chunk),
                self._snapshot.selection(query.request_identity),
                tuple(reasons),
            )

    def _selected(self, query: BookQuery) -> Iterator[BookMarketRow | BookObservation]:
        """Preserve source order and exact nanosecond eligibility before projection."""
        start, end, cutoff = (
            self._nanoseconds(value) for value in (query.start, query.end, query.known_at)
        )
        if self._snapshot.selection(query.request_identity).archive is not None:
            self._snapshot.verify_partition(query.request_identity)
            return
        for row in self._snapshot.observations(query.request_identity):
            if row.received_ns is None or row.received_ns > cutoff:
                continue
            if row.outcome in ("snapshot", "update") and row.status == "degraded":
                if start <= row.received_ns < end:
                    values: dict[BookColumn, BookValue] = {
                        "orders": row.orders,
                        "bids": row.bids,
                        "asks": row.asks,
                    }
                    yield BookMarketRow(
                        row.position,
                        row.epoch,
                        row.received_ns,
                        row.source_time,
                        row.sequence,
                        row.state_identity,
                        row.status,
                        row.reason,
                        tuple(values[column] for column in query.columns),
                    )
            elif row.received_ns <= end:
                yield row

    @staticmethod
    def _nanoseconds(instant: datetime) -> int:
        """Convert a validated UTC microsecond boundary exactly, without rounding early."""
        elapsed = instant - datetime(1970, 1, 1, tzinfo=UTC)
        return (
            elapsed.days * 86_400_000_000 + elapsed.seconds * 1_000_000 + elapsed.microseconds
        ) * 1000
