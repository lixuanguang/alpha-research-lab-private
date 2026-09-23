"""Project known native book states with receipt-clock windows and mandatory controls."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from itertools import batched
from pathlib import Path
from typing import Literal, NamedTuple

# project library imports
from market_data.contracts import BookObservation, Level, Order
from market_data.datasets import (
    BookDatasetManifest,
    BookHistory,
    BookInput,
    DatasetReaders,
    SnapshotStore,
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

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        query: BookQuery,
    ) -> tuple[BookQueryBatch, ...]:
        """Verify a whole snapshot, select one native partition, then project known values.

        Args:
            directory: Immutable publication root, protected from concurrent external mutation.
            raw: Retained raw objects for independent reconstruction verification.
            readers: Explicitly selected native source readers.
            query: Pinned partition, instrument, fields and receipt/knowledge bounds.

        Returns:
            Bounded in-memory batches; one empty evidence batch when nothing is known.
            Memory includes verified native state and all selected rows, not just batch_size.

        Raises:
            ValueError: Admission, selected identity, units or field capabilities disagree.
            OSError: A retained snapshot or original object is unavailable.
        """
        query.__post_init__()
        manifest = SnapshotStore(
            directory, raw, readers=readers, manifest_type=BookDatasetManifest
        ).read(query.snapshot_id, max_bytes=query.max_bytes)
        for partition in manifest.partitions:
            if partition.selection.request.identity != query.request_identity:
                continue
            config = partition.selection.request.config
            if config.instrument_id != query.instrument:
                raise ValueError("book query instrument differs from pinned request")
            capture = partition.selection.capture
            if capture is not None and capture.universes is not None:
                capture.universes.require(query.instrument, "research")
            is_l3 = capture is not None and capture.config.channel in ("R0", "level3")
            supported = ("orders",) if is_l3 else ("bids", "asks")
            if any(column not in supported for column in query.columns):
                raise ValueError("book fields incompatible with native L2/L3 representation")
            with (directory / query.snapshot_id / partition.sha256).open("rb") as source:
                payload = source.read(query.max_bytes + 1)
            if (
                len(payload) > query.max_bytes
                or hashlib.sha256(payload).hexdigest() != partition.sha256
            ):
                raise ValueError("book canonical size or identity mismatch")
            history = DomainCodec().decode_json(payload, BookHistory)
            return cls._select(history, query)
        raise ValueError("book query request absent from pinned snapshot")

    @classmethod
    def _select(cls, history: BookHistory, query: BookQuery) -> tuple[BookQueryBatch, ...]:
        """Filter exact receipt boundaries before exposing values; preserve scoped controls."""
        start, end, cutoff = (
            cls._nanoseconds(value) for value in (query.start, query.end, query.known_at)
        )
        rows: list[BookMarketRow | BookObservation] = []
        reasons = ["visible depth only; coverage and historical eligibility unproven"]
        if history.input.archive is not None:
            reasons.append("original book availability unknown; no decision-eligible values")
        for row in history.observations:
            if row.received_ns is None or row.received_ns > cutoff:
                continue
            if row.outcome in ("snapshot", "update") and row.status == "degraded":
                if start <= row.received_ns < end:
                    values: dict[BookColumn, BookValue] = {
                        "orders": row.orders,
                        "bids": row.bids,
                        "asks": row.asks,
                    }
                    rows.append(
                        BookMarketRow(
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
                    )
            elif row.received_ns <= end:
                rows.append(row)
        if not any(isinstance(row, BookMarketRow) for row in rows):
            reasons.append("no selected book values; absence does not establish an empty market")
        identity = hashlib.sha256(
            DomainCodec().encode_json(
                (
                    "book-query-v1",
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
        chunks: Iterator[tuple[BookMarketRow | BookObservation, ...]] = (
            batched(rows, query.batch_size) if rows else iter(((),))
        )
        evidence = deepcopy(history.input)
        return tuple(
            BookQueryBatch(identity, query.columns, deepcopy(chunk), evidence, tuple(reasons))
            for chunk in chunks
        )

    @staticmethod
    def _nanoseconds(instant: datetime) -> int:
        """Convert a validated UTC microsecond boundary exactly, without rounding early."""
        elapsed = instant - datetime(1970, 1, 1, tzinfo=UTC)
        return (
            elapsed.days * 86_400_000_000 + elapsed.seconds * 1_000_000 + elapsed.microseconds
        ) * 1000
