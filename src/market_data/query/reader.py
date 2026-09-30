"""Query explicitly bounded reference snapshots without discarding replay history."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable, Generator
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from itertools import batched
from pathlib import Path
from typing import ClassVar, Literal, NamedTuple, cast

# third party library imports
from msgspec.structs import replace

# project library imports
from market_data.contracts import ArchiveTrade, Occurrence, SourceRequest, Trade
from market_data.datasets import DatasetReaders, SnapshotStore
from market_data.query.asof import (
    AsOfSelector,
    ContinuityResumed,
    InputBinding,
    PointEvent,
    _Partition,
    _RevisionIndex,
)
from market_data.storage import RawStore
from market_data.validation import QualityPolicy, TradeRevision
from reference_data.eligibility import EligibilityAssertions
from reference_data.instruments import InstrumentId
from serialization import DomainCodec

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
    scope: Literal["exploratory_degraded", "causal_witnessed", "causal_qualified"]
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
    # Requested first-binding-message recoveries; None unless the query asked.
    recoveries: tuple[ContinuityResumed, ...] | None = None


class QueryReader:
    """Own verified reference bytes with an explicit aggregate memory-input budget.

    No files remain open after read. Memory is proportional to the capped canonical
    input plus cached admitted partitions and selection, not just batch size. External store
    mutation remains excluded during read under SnapshotStore's contract.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self,
        canonical: tuple[bytes, ...],
        *,
        readers: DatasetReaders,
        precedence: tuple[InputBinding, ...],
        max_bytes: int,
    ) -> None:
        """Validate a bounded in-memory reference, also useful for admitted fixture inputs.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
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
        self._selector = AsOfSelector(canonical, precedence=precedence, readers=readers)
        self._evidence = self._shared_evidence(self._selector._partitions)
        self._identity = hashlib.sha256(self._codec.encode_json(canonical)).hexdigest()
        self._precedence = precedence

    @property
    def identity(self) -> str:
        """Identify admitted immutable input bytes before a consumer starts execution.

        Returns:
            Saved snapshot SHA-256, or the complete in-memory canonical input digest.
        """
        return self._identity

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        identity: str,
        max_bytes: int,
        precedence: tuple[InputBinding, ...],
    ) -> QueryReader:
        """Verify a whole snapshot and bound canonical bytes before constructing the selector.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
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
        manifest = SnapshotStore(directory, raw, readers=readers).read(
            identity, max_bytes=max_bytes
        )
        payloads: list[bytes] = []
        remaining = max_bytes
        for partition in manifest.partitions:
            with (directory / identity / partition.sha256).open("rb") as source:
                payload = source.read(remaining + 1)
            remaining -= len(payload)
            if remaining < 0:
                raise ValueError("query canonical input exceeds aggregate max_bytes")
            payloads.append(payload)
        reader = cls(tuple(payloads), precedence=precedence, max_bytes=max_bytes, readers=readers)
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
        recoveries: bool = False,
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
            recoveries: Cutoff only: also return each scoped disconnect's first later
                same-binding trade known by the cutoff, as ``ContinuityResumed`` records.

        Yields:
            Typed tuples with exact values in requested column order, full unprojectable
            controls and binding-scoped evidence. Cutoff order is AsOfSelector order;
            history is partition/head order, not chronological replay order. Original quality
            scope and limits survive. Reverified native evidence may supply archive availability.

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
            or (recoveries is not False and (recoveries is not True or mode != "cutoff"))
        ):
            raise ValueError(
                "query requires positive batches and unique supported columns; "
                "history requires revision"
            )
        self._check_cancelled(cancelled)
        selected = self._selector.select(instruments, start=start, end=end, known_at=known_at)
        # One deepcopy per result: shared manifests and histories are copied once.
        evidence = deepcopy(
            tuple(
                item
                for item in self._evidence
                if item.request.instrument.instrument_id in instruments
            )
        )
        if mode == "history":
            indexes = tuple(
                index
                for index in self._selector._indexes
                if index.partition.request.instrument.instrument_id in instruments
            )
            selected = tuple(self._history(indexes, start, end, known_at)) + tuple(
                item for item in selected if isinstance(item, Occurrence)
            )
        instrument_texts: tuple[str, ...] = tuple(sorted(str(item) for item in instruments))
        parts: tuple[object, ...] = (
            "reference-query",
            self._identity,
            self._precedence,
            instrument_texts,
            start,
            end,
            known_at,
            columns,
            mode,
        )
        if recoveries:
            parts = (*parts, "first-binding-message")
        identity = hashlib.sha256(self._codec.encode_json(parts)).hexdigest()
        recovered = (
            self._selector.recoveries(instruments, end=end, known_at=known_at)
            if recoveries
            else None
        )
        for chunk in batched(selected, batch_size) if selected else ((),):
            self._check_cancelled(cancelled)
            rows = tuple(
                self._project(deepcopy(item) if mode == "history" else item, columns)
                for item in chunk
            )
            yield QueryBatch(identity, mode, columns, rows, evidence, recovered)

    @classmethod
    def _shared_evidence(cls, partitions: tuple[_Partition, ...]) -> tuple[QueryEvidence, ...]:
        """Map byte-identical manifests, catalogs and eligibility histories to one instance.

        Values are unchanged. Each query deep-copies its evidence in one call, so a
        shared value is copied once per result instead of once per partition; a
        result's partitions may alias those copies, but no result aliases the cache
        or another result. Sharing is by encoded bytes, not equality: equal values
        can encode differently (Decimal 0.01 and 0.010), and each partition's
        evidence must keep its own bytes and identities.
        """
        shared: dict[tuple[type, bytes], object] = {}

        def one[T](value: T) -> T:
            """Return the first cached value with this one's type and encoded bytes."""
            return cast(T, shared.setdefault((type(value), cls._codec.encode_json(value)), value))

        evidence: list[QueryEvidence] = []
        for partition in partitions:
            manifest = partition.request.manifest
            manifest = one(replace(manifest, catalog=one(manifest.catalog)))
            eligibility = partition.eligibility
            eligibility = one(replace(eligibility, catalog=one(eligibility.catalog)))
            evidence.append(
                QueryEvidence(
                    replace(partition.request, manifest=manifest),
                    partition.scope,
                    partition.policy,
                    eligibility,
                    partition.reasons,
                )
            )
        return tuple(evidence)

    @staticmethod
    def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
        """Stop cooperatively at bounded reference selection/batch boundaries."""
        if cancelled is not None and cancelled():
            raise InterruptedError("query cancelled")

    @staticmethod
    def _history(
        indexes: tuple[_RevisionIndex, ...], start: datetime, end: datetime, known_at: datetime
    ) -> Generator[TradeRevision]:
        """Retain complete chains touching the window without terminal membership filtering."""
        for index in indexes:
            # Chains with no version valid in [start, end) cannot pass the window test.
            for chain in index.chains(start, end):
                # Chains are newest first; unknown knowledge counts as known.
                for position, (version_known_at, _, _) in enumerate(chain):
                    if version_known_at is None or version_known_at <= known_at:
                        break
                else:
                    continue
                if any(start <= instant < end for _, instant, _ in chain[position:]):
                    yield chain[position][2]

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
