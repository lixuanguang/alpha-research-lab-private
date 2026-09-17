"""Project admitted point-event history at an inclusive knowledge cutoff."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from alpha_research.data.eligibility import EligibilityAssertion, EligibilityAssertions
from alpha_research.data.events import Disconnect
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.binance.trades import ArchiveTrade
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, TradeKey, TradeRevision
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import _ReferenceRecord
from alpha_research.serialization import DomainCodec

type InputBinding = tuple[str, str, InstrumentId]
type PointEvent = TradeRevision | Occurrence
type EconomicOrder = tuple[datetime, int, datetime, int, int]


class _Partition(_ReferenceRecord, frozen=True, kw_only=True):
    """Decode the existing canonical format and reproduce its complete admission."""

    _codec: ClassVar[DomainCodec] = DomainCodec()
    _wire: ClassVar[msgspec.json.Decoder[object]] = msgspec.json.Decoder(object)
    schema_version: Literal["canonical-trade-partition-v1"]
    scope: Literal["exploratory_degraded"]
    policy: QualityPolicy
    request: SourceRequest
    eligibility: EligibilityAssertions
    membership: tuple[
        tuple[datetime, datetime, EligibilityAssertion | Literal["unknown", "unsupported"]], ...
    ]
    reasons: tuple[str, ...]
    revisions: tuple[TradeRevision, ...]
    controls: tuple[Occurrence, ...]

    def __post_init__(self) -> None:
        """Reject altered canonical claims using the existing source and quality gate.

        Raises:
            ValueError: The canonical content does not reproduce its admission.
            TypeError: A boundary record has an unsupported type.
        """
        if (
            type(self.policy) is not QualityPolicy
            or type(self.revisions) is not tuple
            or type(self.controls) is not tuple
        ):
            raise TypeError("canonical partition requires typed immutable admission inputs")
        occurrences = list(self.controls)
        corrections: dict[str, Correction] = {}
        for head in self.revisions:
            version: TradeRevision | None = head
            while version is not None:
                version.__post_init__()
                occurrences.extend(version.occurrences)
                if version.correction is not None:
                    corrections[version.identity] = version.correction
                version = version.previous
        report = self.policy.validate(
            self.request,
            sorted(occurrences, key=self._raw_order),
            eligibility=self.eligibility,
            corrections=tuple(corrections.values()),
        )
        if self._wire.decode(report.require_canonical()) != (
            self._wire.decode(self._codec.encode_json(self))
        ):
            raise ValueError("canonical partition differs from reproduced admission")

    @staticmethod
    def _raw_order(item: Occurrence) -> tuple[str, int, int]:
        """Group raw objects for validation only; hashes never order economic output."""
        return item.origin.sha256, item.position, item.record_index


class AsOfSelector:
    """Keep bounded admitted history separate from repeatable cutoff projections.

    Availability uses original capture or evidenced correction knowledge only. Unknown
    archive availability produces no selected version; original clocks are never filled
    from acquisition or event time. Retained canonical quality/history bytes remain
    available through history, including exclusions, unknowns and later revisions.
    """

    _codec: ClassVar[DomainCodec] = DomainCodec()

    def __init__(
        self, canonical: tuple[bytes, ...], *, precedence: tuple[InputBinding, ...]
    ) -> None:
        """Validate complete partitions and freeze explicit source/stream/subscription order.

        Args:
            canonical: Existing admitted partition bytes, retained unchanged in memory.
            precedence: Ordered source ID, stream and instrument bindings, fixed by caller
                configuration. Every retained binding must appear exactly once.

        Raises:
            ValueError: Inputs, precedence, overlapping bindings or economic heads conflict.
        """
        if (
            type(canonical) is not tuple
            or not canonical
            or any(type(p) is not bytes for p in canonical)
        ):
            raise ValueError("as-of selection requires nonempty immutable canonical bytes")
        partitions = tuple(self._codec.decode_json(payload, _Partition) for payload in canonical)
        bindings = {self._binding(partition.request) for partition in partitions}
        if (
            type(precedence) is not tuple
            or len(precedence) != len(bindings)
            or set(precedence) != bindings
        ):
            raise ValueError("precedence must name each retained input binding exactly once")
        heads: set[TradeKey] = set()
        intervals: dict[InputBinding, list[tuple[datetime, datetime]]] = {}
        for partition in partitions:
            request = partition.request
            start, end = (
                max(request.start, request.manifest.job.start),
                min(request.end, request.manifest.job.end),
            )
            previous = intervals.setdefault(self._binding(request), [])
            if any(start < right and left < end for left, right in previous):
                raise ValueError(
                    "overlapping input partitions require reconciliation before selection"
                )
            previous.append((start, end))
            for head in partition.revisions:
                if head.key in heads:
                    raise ValueError(
                        "competing economic heads require reconciliation before selection"
                    )
                heads.add(head.key)
        self._history = canonical
        self._precedence = precedence

    @property
    def history(self) -> tuple[bytes, ...]:
        """Retain complete admission inputs, quality scope and history independently of cutoffs.

        Returns:
            Original immutable canonical bytes, never a terminal revision projection.
        """
        return self._history

    @classmethod
    def read(
        cls,
        directory: Path,
        raw: RawStore,
        *,
        identity: str,
        max_bytes: int,
        precedence: tuple[InputBinding, ...],
    ) -> AsOfSelector:
        """Verify an explicit snapshot and load its admitted partitions into the selector.

        Args:
            directory: Snapshot store root under the existing exclusion of external mutation.
            raw: Retained raw store required by snapshot verification.
            identity: Explicit immutable snapshot SHA-256; mutable aliases are rejected.
            max_bytes: Positive per-file bound including expanded raw input.
            precedence: Explicit ordered bindings, as required by the constructor.

        Returns:
            Bounded in-memory reference selector after complete snapshot verification.

        Raises:
            ValueError: Snapshot integrity, admission, size or ordering is invalid.
            OSError: A retained input is missing or unreadable.
        """
        manifest = SnapshotStore(directory, raw).read(identity, max_bytes=max_bytes)
        return cls(
            tuple(
                (directory / identity / part.sha256).read_bytes() for part in manifest.partitions
            ),
            precedence=precedence,
        )

    def select(
        self,
        instruments: tuple[InstrumentId, ...],
        *,
        start: datetime,
        end: datetime,
        known_at: datetime,
    ) -> tuple[PointEvent, ...]:
        """Select known revisions, then business-window and decision-time membership.

        Args:
            instruments: Nonempty unique supported canonical IDs; controls retain binding scope.
            start: Inclusive UTC business-window start, using the event valid_from instant.
            end: Exclusive UTC business-window end; this is not a last-observation query.
            known_at: Inclusive UTC availability and membership cutoff, independent of validity.

        Returns:
            Latest known eligible version per economic key and applicable known disconnects,
            ordered by effective knowledge, explicit binding precedence, partition start and
            raw position. Earlier controls survive the window start as boundary state; terminal
            controls at end are retained. Absence never certifies coverage or membership;
            history retains all scoped quality evidence, unavailable versions and exclusions.
            Returned records retain distinct clocks and original lineage, without forward fill.

        Raises:
            ValueError: A window, selection or economically meaningful ordering tie is invalid.
            TypeError: A supplied clock is not timezone aware.
        """
        for name, instant in (("start", start), ("end", end), ("known_at", known_at)):
            _Partition._require_utc(instant, field_name=name)
        supported = {binding[2] for binding in self._precedence}
        if (
            end <= start
            or type(instruments) is not tuple
            or not instruments
            or (
                any(type(item) is not InstrumentId for item in instruments)
                or len(set(instruments)) != len(instruments)
                or not set(instruments) <= supported
            )
        ):
            raise ValueError(
                "as-of selection requires a positive window and unique supported instruments"
            )
        selected: dict[EconomicOrder, PointEvent] = {}
        for payload in self._history:
            partition = self._codec.decode_json(payload, _Partition)
            request = partition.request
            if request.instrument.instrument_id not in instruments:
                continue
            for head in partition.revisions:
                version: TradeRevision | None = head
                while version is not None and (
                    version.ts_knowledge is None or version.ts_knowledge > known_at
                ):
                    version = version.previous
                if version is None:
                    continue
                instant = min(self._valid_from(item) for item in version.occurrences)
                membership = partition.eligibility.select(
                    request.instrument.instrument_id, valid_at=instant, known_at=known_at
                )
                if (
                    start <= instant < end
                    and isinstance(membership, EligibilityAssertion)
                    and membership.state == "included"
                ):
                    self._insert(selected, version, version.ts_knowledge, version.occurrences)
            for control in partition.controls:
                event = control.event
                if (
                    isinstance(event, Disconnect)
                    and event.provenance.ts_knowledge <= known_at
                    and event.provenance.valid_from <= end
                ):
                    self._insert(selected, control, event.provenance.ts_knowledge, (control,))
        return tuple(selected[key] for key in sorted(selected))

    def _insert(
        self,
        selected: dict[EconomicOrder, PointEvent],
        event: PointEvent,
        known_at: datetime | None,
        occurrences: tuple[Occurrence, ...],
    ) -> None:
        """Resolve duplicate lineage by logical position and refuse ambiguous economic ties."""
        if known_at is None:
            raise ValueError("cannot order a revision with unknown availability")
        position = min(
            (
                self._precedence.index(self._binding(item.request)),
                item.request.start,
                item.position,
                item.record_index,
            )
            for item in occurrences
            if isinstance(item.event, ArchiveTrade)
            or item.event.provenance.ts_knowledge <= known_at
        )
        key = (known_at, *position)
        if key in selected:
            raise ValueError("ambiguous economic ordering; reconcile logical source positions")
        selected[key] = event

    @staticmethod
    def _valid_from(item: Occurrence) -> datetime:
        """Preserve the archive event instant or captured point's original business instant."""
        return (
            item.event.ts_event
            if isinstance(item.event, ArchiveTrade)
            else item.event.provenance.valid_from
        )

    @staticmethod
    def _binding(request: SourceRequest) -> InputBinding:
        """Identify the explicit source/stream/subscription scope without content hashes."""
        return (
            request.instrument.source,
            request.manifest.job.stream,
            request.instrument.instrument_id,
        )
