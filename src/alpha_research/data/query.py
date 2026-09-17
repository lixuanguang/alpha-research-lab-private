"""Query explicitly bounded reference snapshots without discarding replay history."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable, Generator
from datetime import datetime
from decimal import Decimal
from itertools import batched
from pathlib import Path
from typing import ClassVar, Literal, NamedTuple

# project library imports
from alpha_research.data.asof import AsOfSelector, InputBinding, PointEvent, _Partition
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import TradeRevision
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.data.venues.binance.events import Trade
from alpha_research.instrument_identity import InstrumentId
from alpha_research.serialization import DomainCodec

type QueryColumn = Literal["identity", "ts_knowledge", "price", "quantity", "revision"]
type QueryValue = str | datetime | Decimal | TradeRevision | None


class QueryMarketRow(NamedTuple):
    """Bind projected values to their source, stream and instrument even for price-only queries."""

    binding: InputBinding
    values: tuple[QueryValue, ...]


type QueryRow = QueryMarketRow | Occurrence


class QueryEvidence(NamedTuple):
    """Carry unprojectable binding, units, quality and complete membership evidence."""

    request: SourceRequest
    scope: Literal["exploratory_degraded"]
    policy: QualityPolicy
    eligibility: EligibilityAssertions
    reasons: tuple[str, ...]


class QueryBatch(NamedTuple):
    """Return projected market rows or full scoped controls, with query evidence.

    These are in-process result containers, not a new serialized event schema.
    History rows require the revision column; their chains are candidates for replay,
    not an eligible economic projection. Evidence is repeated by reference per batch.
    An empty result still emits one empty batch so quality cannot disappear.
    """

    identity: str
    mode: Literal["cutoff", "history"]
    columns: tuple[QueryColumn, ...]
    rows: tuple[QueryRow, ...]
    evidence: tuple[QueryEvidence, ...]


class QueryReader:
    """Own verified reference bytes with an explicit aggregate memory-input budget.

    No files remain open after read. Memory is proportional to the capped canonical
    input plus decoded reference selection, not just batch size. External store
    mutation remains excluded during read under SnapshotStore's contract.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self, canonical: tuple[bytes, ...], *, precedence: tuple[InputBinding, ...], max_bytes: int
    ) -> None:
        """Validate a bounded in-memory reference, also useful for admitted fixture inputs.

        Args:
            canonical: Complete immutable admitted partitions.
            precedence: Explicit source/stream/subscription economic order.
            max_bytes: Positive aggregate canonical-byte budget, not a process RSS limit.

        Raises:
            ValueError: The budget, canonical admission or cross-partition contract fails.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("query max_bytes must be a positive integer")
        if sum(len(payload) for payload in canonical) > max_bytes:
            raise ValueError("query canonical input exceeds aggregate max_bytes")
        self._selector = AsOfSelector(canonical, precedence=precedence)
        self._identity = hashlib.sha256(self._codec.encode_json(canonical)).hexdigest()
        self._precedence = precedence

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        identity: str,
        max_bytes: int,
        precedence: tuple[InputBinding, ...],
    ) -> QueryReader:
        """Verify a whole snapshot and bound canonical bytes before constructing the selector.

        Args:
            directory: Existing immutable snapshot store root.
            raw: Retained raw objects for complete snapshot admission verification.
            identity: Explicit snapshot SHA-256, never a mutable alias.
            max_bytes: Per-file verification bound and aggregate canonical-input budget.
            precedence: Explicit ordered bindings for all snapshot partitions.

        Returns:
            Reusable reference reader with no open files or per-query mutable state.

        Raises:
            ValueError: Integrity, admission, aggregate budget or precedence fails.
            OSError: A retained input is unavailable.
        """
        manifest = SnapshotStore(directory, raw).read(identity, max_bytes=max_bytes)
        payloads: list[bytes] = []
        remaining = max_bytes
        for partition in manifest.partitions:
            with (directory / identity / partition.sha256).open("rb") as source:
                payload = source.read(remaining + 1)
            remaining -= len(payload)
            if remaining < 0:
                raise ValueError("query canonical input exceeds aggregate max_bytes")
            payloads.append(payload)
        reader = cls(tuple(payloads), precedence=precedence, max_bytes=max_bytes)
        reader._identity = identity
        return reader

    def batches(
        self,
        instruments: tuple[InstrumentId, ...],
        *,
        start: datetime,
        end: datetime,
        known_at: datetime,
        columns: tuple[QueryColumn, ...],
        batch_size: int,
        mode: Literal["cutoff", "history"] = "cutoff",
        cancelled: Callable[[], bool] | None = None,
    ) -> Generator[QueryBatch]:
        """Select before projecting, yielding at most batch_size market/control rows.

        Args:
            instruments: Nonempty unique supported IDs; their argument order is immaterial.
            start: Inclusive UTC business start; earlier applicable controls survive.
            end: Exclusive UTC business end; terminal controls are retained.
            known_at: Inclusive UTC knowledge cutoff, independent of business time.
            columns: Unique market fields in output order. History requires revision.
            batch_size: Positive row bound, counting controls too; identity is independent.
            mode: Cutoff selects eligible latest-known versions. History retains chains
                known by the cutoff (including unknown predecessors), even after membership
                withdrawal or a correction moves outside the window. Replay must apply the
                retained membership history at each decision. No event stepping is performed.
            cancelled: Optional cooperative cancellation predicate, checked before selection
                and between batches. Generator close also releases its local selection.

        Yields:
            Typed tuples with exact values in requested column order, full unprojectable
            controls and binding-scoped evidence. Cutoff order is AsOfSelector order;
            history is partition/head order, not chronological replay order. Quality remains
            exploratory_degraded. No retained evidence grants historical availability.

        Raises:
            ValueError: Options, admission, window or selection are invalid.
            InterruptedError: Cancellation is requested; no completion is implied.
        """
        if (
            type(batch_size) is not int
            or batch_size <= 0
            or mode not in ("cutoff", "history")
            or type(columns) is not tuple
            or not columns
            or len(set(columns)) != len(columns)
            or any(
                c not in ("identity", "ts_knowledge", "price", "quantity", "revision")
                for c in columns
            )
            or (mode == "history" and "revision" not in columns)
        ):
            raise ValueError(
                "query requires positive batches and unique supported columns; "
                "history requires revision"
            )
        self._check_cancelled(cancelled)
        selected = self._selector.select(instruments, start=start, end=end, known_at=known_at)
        partitions = tuple(
            partition
            for payload in self._selector.history
            if (
                partition := self._codec.decode_json(payload, _Partition)
            ).request.instrument.instrument_id
            in instruments
        )
        evidence = tuple(
            QueryEvidence(p.request, p.scope, p.policy, p.eligibility, p.reasons)
            for p in partitions
        )
        if mode == "history":
            selected = tuple(self._history(partitions, start, end, known_at)) + tuple(
                item for item in selected if isinstance(item, Occurrence)
            )
        identity = hashlib.sha256(
            self._codec.encode_json(
                (
                    "reference-query-v1",
                    self._identity,
                    self._precedence,
                    tuple(sorted(map(str, instruments))),
                    start,
                    end,
                    known_at,
                    columns,
                    mode,
                )
            )
        ).hexdigest()
        for chunk in batched(selected, batch_size) if selected else ((),):
            self._check_cancelled(cancelled)
            rows = tuple(self._project(item, columns) for item in chunk)
            yield QueryBatch(identity, mode, columns, rows, evidence)

    @staticmethod
    def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
        """Stop cooperatively at bounded reference selection/batch boundaries."""
        if cancelled is not None and cancelled():
            raise InterruptedError("query cancelled")

    @staticmethod
    def _history(
        partitions: tuple[_Partition, ...], start: datetime, end: datetime, known_at: datetime
    ) -> Generator[TradeRevision]:
        """Retain complete chains touching the window without terminal membership filtering."""
        for partition in partitions:
            for head in partition.revisions:
                version: TradeRevision | None = head
                while (
                    version is not None
                    and version.ts_knowledge is not None
                    and version.ts_knowledge > known_at
                ):
                    version = version.previous
                retained = version
                while version is not None:
                    if (
                        start
                        <= min(AsOfSelector._valid_from(item) for item in version.occurrences)
                        < end
                    ):
                        if retained is not None:
                            yield retained
                        break
                    version = version.previous

    @staticmethod
    def _project(item: PointEvent, columns: tuple[QueryColumn, ...]) -> QueryRow:
        """Project exact trade values only; disconnect scope and lineage are mandatory."""
        if isinstance(item, Occurrence):
            return item
        event = item.occurrences[0].event
        if not isinstance(event, (Trade, ArchiveTrade)):
            raise TypeError("query revision requires a trade")
        values: dict[QueryColumn, QueryValue] = {
            "identity": item.identity,
            "ts_knowledge": item.ts_knowledge,
            "price": event.price,
            "quantity": event.quantity,
            "revision": item,
        }
        return QueryMarketRow(
            AsOfSelector._binding(item.occurrences[0].request),
            tuple(values[column] for column in columns),
        )
