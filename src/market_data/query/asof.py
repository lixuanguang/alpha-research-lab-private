"""Project admitted point-event history at an inclusive knowledge cutoff."""

from __future__ import annotations

# standard library imports
import bisect
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Literal

# third party library imports
import msgspec

# project library imports
from market_data.contracts import (
    ArchiveCapture,
    ArchiveTrade,
    Disconnect,
    Occurrence,
    OccurrenceVerifier,
    SourceRequest,
)
from market_data.datasets import DatasetReaders, SnapshotStore
from market_data.storage import RawStore
from market_data.validation import (
    Correction,
    QualityPolicy,
    SourceQualification,
    TradeKey,
    TradeRevision,
)
from reference_data.eligibility import EligibilityAssertion, EligibilityAssertions
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord

type InputBinding = tuple[str, str, InstrumentId]
type PointEvent = TradeRevision | Occurrence
type EconomicOrder = tuple[datetime, int, datetime, int, int]
type _Version = tuple[datetime | None, datetime, TradeRevision]
# (instant, partition start, raw position), knowledge, version.
type _Ordered = tuple[tuple[datetime, datetime, int], datetime | None, TradeRevision]


class _Partition(WireRecord, frozen=True, kw_only=True):
    """Decode the existing canonical format and reproduce its complete admission."""

    _codec: ClassVar[DomainCodec] = DomainCodec()
    _wire: ClassVar[msgspec.json.Decoder[dict[str, msgspec.Raw]]] = msgspec.json.Decoder(
        dict[str, msgspec.Raw]
    )
    schema_version: Literal[
        "canonical-trade-partition-exploratory",
        "canonical-trade-partition-witnessed",
        "canonical-trade-partition-qualified",
    ]
    scope: Literal["exploratory_degraded", "causal_witnessed", "causal_qualified"]
    policy: QualityPolicy
    request: SourceRequest
    eligibility: EligibilityAssertions
    membership: tuple[
        tuple[datetime, datetime, EligibilityAssertion | Literal["unknown", "unsupported"]], ...
    ]
    reasons: tuple[str, ...]
    revisions: tuple[TradeRevision, ...]
    controls: tuple[Occurrence, ...]
    capture: ArchiveCapture | None = None
    qualification: SourceQualification | None = None

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

    def verify(self, verifier: OccurrenceVerifier) -> None:
        """Reproduce every source occurrence and admission claim before query exposure.

        Args:
            verifier: Explicit native re-decoder for this partition's source.

        Raises:
            ValueError: Canonical content differs from fully reproduced admission.
        """
        self.__post_init__()
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
            verifier=verifier,
            capture=self.capture if isinstance(self.capture, ArchiveCapture) else None,
            qualification=self.qualification
            if isinstance(self.qualification, SourceQualification)
            else None,
        )
        # Both encodings use the same sorted domain codec. Compare field bytes
        # without allocating two additional trees of nested Python dictionaries.
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
        self,
        canonical: tuple[bytes, ...],
        *,
        readers: DatasetReaders,
        precedence: tuple[InputBinding, ...],
    ) -> None:
        """Validate complete partitions and freeze explicit source/stream/subscription order.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
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
        for partition in partitions:
            partition.verify(readers.verifier(partition.request))
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
        self._partitions = partitions
        self._precedence = precedence
        self._ranks = {binding: rank for rank, binding in enumerate(precedence)}
        self._indexes = tuple(_RevisionIndex(partition) for partition in partitions)
        self._binding_versions: (
            dict[InputBinding, tuple[list[tuple[datetime, datetime, int]], list[_Ordered]]] | None
        ) = None

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
        readers: DatasetReaders,
        identity: str,
        max_bytes: int,
        precedence: tuple[InputBinding, ...],
    ) -> AsOfSelector:
        """Verify an explicit snapshot and load its admitted partitions into the selector.

        Args:
            readers: Selected readers and native re-decoders for complete verification.
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
        manifest = SnapshotStore(directory, raw, readers=readers).read(
            identity, max_bytes=max_bytes
        )
        return cls(
            tuple(
                (directory / identity / part.sha256).read_bytes() for part in manifest.partitions
            ),
            precedence=precedence,
            readers=readers,
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
        for index in self._indexes:
            partition = index.partition
            request = partition.request
            if request.instrument.instrument_id not in instruments:
                continue
            # Chains with no version valid in [start, end) cannot pass the window test.
            for chain in index.chains(start, end):
                for version_known_at, instant, version in chain:
                    if version_known_at is not None and version_known_at <= known_at:
                        break
                else:
                    continue
                if not start <= instant < end:
                    continue
                membership = partition.eligibility.select(
                    request.instrument.instrument_id, valid_at=instant, known_at=known_at
                )
                if isinstance(membership, EligibilityAssertion) and membership.state == "included":
                    self._insert(selected, version, version_known_at, version.occurrences)
            for control in partition.controls:
                event = control.event
                if (
                    isinstance(event, Disconnect)
                    and event.provenance.ts_knowledge <= known_at
                    and event.provenance.valid_from <= end
                ):
                    self._insert(selected, control, event.provenance.ts_knowledge, (control,))
        # Caller mutation, including unsafe struct mutation, cannot poison later
        # queries. Admission remains cached only behind this ownership boundary.
        return deepcopy(tuple(selected[key] for key in sorted(selected)))

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
                self._ranks[self._binding(item.request)],
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

    def recoveries(
        self, instruments: tuple[InstrumentId, ...], *, end: datetime, known_at: datetime
    ) -> tuple[ContinuityResumed, ...]:
        """Pair each disconnect known by the cutoff with its first later same-binding trade.

        Args:
            instruments: Instruments whose bindings' disconnects are answered.
            end: Exclusive UTC business end; later disconnects are not answered.
            known_at: Inclusive UTC cutoff for the disconnect and the answering trade.

        Returns:
            One recovery per answered disconnect, in partition and raw order. A
            disconnect with no later trade known by the cutoff has none.
        """
        versions = self._versions_by_binding()
        results: list[ContinuityResumed] = []
        for partition in self._partitions:
            request = partition.request
            if request.instrument.instrument_id not in instruments:
                continue
            binding = self._binding(request)
            for control in partition.controls:
                event = control.event
                if not isinstance(event, Disconnect):
                    continue
                at = self._valid_from(control)
                if at >= end or event.provenance.ts_knowledge > known_at:
                    continue
                keys, candidates = versions.get(binding, ([], []))
                first = bisect.bisect_right(keys, (at, request.start, control.position))
                for order, version_known_at, version in candidates[first:]:
                    if version_known_at is not None and version_known_at <= known_at:
                        results.append(
                            ContinuityResumed(
                                binding=binding,
                                disconnect_identity=event.provenance.event_id,
                                trade_identity=version.identity,
                                resumed_at=order[0],
                                known_at=version_known_at,
                            )
                        )
                        break
        return tuple(results)

    def _versions_by_binding(
        self,
    ) -> dict[InputBinding, tuple[list[tuple[datetime, datetime, int]], list[_Ordered]]]:
        """Order every trade version of each binding by raw capture order, once."""
        if self._binding_versions is None:
            grouped: dict[InputBinding, list[_Ordered]] = {}
            for index in self._indexes:
                request = index.partition.request
                binding = self._binding(request)
                for chain in index.chains_all():
                    for version_known_at, instant, version in chain:
                        position = min(item.position for item in version.occurrences)
                        grouped.setdefault(binding, []).append(
                            ((instant, request.start, position), version_known_at, version)
                        )
            ordered: dict[
                InputBinding, tuple[list[tuple[datetime, datetime, int]], list[_Ordered]]
            ] = {}
            for binding, items in grouped.items():
                items.sort(key=self._raw_order)
                ordered[binding] = [item[0] for item in items], items
            self._binding_versions = ordered
        return self._binding_versions

    @staticmethod
    def _raw_order(item: _Ordered) -> tuple[datetime, datetime, int]:
        """Order by business instant, then partition start, then raw position."""
        return item[0]

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


class ContinuityResumed(WireRecord, frozen=True):
    """Answer one binding-scoped disconnect with the first later message on that binding.

    ``first_binding_message`` is the weaker basis the features README refuses by
    default: messages flowing again on the binding stand in for proof that the
    subscription resumed. A window accepts it only when its policy says so.
    """

    binding: InputBinding
    disconnect_identity: str
    trade_identity: str
    resumed_at: datetime
    known_at: datetime
    basis: Literal["first_binding_message"] = "first_binding_message"

    def __post_init__(self) -> None:
        """Require identities, UTC clocks and the one supported basis."""
        self._require_utc(self.resumed_at, field_name="resumed_at")
        self._require_utc(self.known_at, field_name="known_at")
        if (
            not self.disconnect_identity
            or not self.trade_identity
            or self.basis != "first_binding_message"
            or len(self.binding) != 3
        ):
            raise ValueError("invalid continuity recovery")


class _RevisionIndex:
    """Index one verified partition's revision chains by the instants they can select.

    Built once after admission verification, from the same cached partition that
    selection already trusts. Each chain keeps its versions newest first with their
    effective knowledge and earliest valid instant, so a query neither walks nor
    re-validates every revision. Chains whose versions share one instant are sorted
    by it; the rare chains whose corrections move the instant are tested per query.
    """

    def __init__(self, partition: _Partition) -> None:
        """Compute each chain's knowledge and instants once and sort fixed-instant chains."""
        self.partition = partition
        chains: list[tuple[_Version, ...]] = []
        for head in partition.revisions:
            versions: list[_Version] = []
            version: TradeRevision | None = head
            while version is not None:
                instant = min(AsOfSelector._valid_from(item) for item in version.occurrences)
                versions.append((version.ts_knowledge, instant, version))
                version = version.previous
            chains.append(tuple(versions))
        self._chains = tuple(chains)
        fixed: list[tuple[datetime, int]] = []
        moved: list[tuple[datetime, datetime, int]] = []
        for position, chain in enumerate(chains):
            instants = [instant for _, instant, _ in chain]
            if min(instants) == max(instants):
                fixed.append((instants[0], position))
            else:
                moved.append((min(instants), max(instants), position))
        fixed.sort()
        self._fixed_instants = [instant for instant, _ in fixed]
        self._fixed_positions = [position for _, position in fixed]
        self._moved = tuple(moved)
        bounds = [instant for chain in chains for _, instant, _ in chain]
        self._span = (min(bounds), max(bounds)) if bounds else None

    def chains_all(self) -> tuple[tuple[_Version, ...], ...]:
        """Return every chain in admission order."""
        return self._chains

    def chains(self, start: datetime, end: datetime) -> tuple[tuple[_Version, ...], ...]:
        """Return, in admission order, every chain with a version valid in [start, end).

        Args:
            start: Inclusive UTC business-window start.
            end: Exclusive UTC business-window end.

        Returns:
            Chains of (knowledge, instant, version), newest version first. A returned
            chain's selected version may still fall outside the window.
        """
        if self._span is None or self._span[1] < start or self._span[0] >= end:
            return ()
        positions = self._fixed_positions[
            bisect.bisect_left(self._fixed_instants, start) : bisect.bisect_left(
                self._fixed_instants, end
            )
        ]
        positions.extend(
            position for low, high, position in self._moved if low < end and high >= start
        )
        return tuple(self._chains[position] for position in sorted(positions))
