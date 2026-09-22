"""Inspect fixtures and compose saved-input admission through atomic snapshot publication."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Callable, Generator, Mapping
from contextlib import closing
from pathlib import Path
from typing import Literal

# project library imports
from market_data.acquisition import AcquisitionManifest
from market_data.contracts import ArchiveCapture, Occurrence, SourceRequest
from market_data.datasets.books import BookDatasetManifest, BookInput, BookPartition
from market_data.datasets.manifests import DatasetInput, DatasetManifest, DatasetPartition
from market_data.datasets.readers import DatasetReaders
from market_data.datasets.snapshots import SnapshotStore
from market_data.storage import RawStore
from market_data.validation import Correction, QualityPolicy, QualityReport, TradeRevision
from reference_data.eligibility import EligibilityAssertions


class DatasetPublication:
    """Assemble and atomically publish admitted inputs using explicit source capabilities."""

    def __init__(self, readers: DatasetReaders, normalization_identity: str) -> None:
        """Bind source verification and the application's installed code identity.

        Args:
            readers: Selected saved readers and native re-decoders.
            normalization_identity: Installed source identity supplied by composition.
        """
        self._readers = readers
        self._normalization_identity = normalization_identity

    def publish_books(
        self,
        directories: tuple[Path, ...],
        store: RawStore,
        destination: Path,
        *,
        max_records: int,
        max_bytes: int,
        report: Callable[[str, QualityReport], None] | None = None,
    ) -> str:
        """Bind saved native inputs, admit exploratory prefixes and atomically publish them.

        Args:
            directories: Completed capture/archive directories; no network access is performed.
            store: Provisioned immutable raw store retaining copied original inputs.
            destination: Provisioned directory shared with the existing snapshot store.
            max_records: Explicit per-input raw-position prefix ceiling, at most 10,000.
            max_bytes: Positive per-file raw/canonical byte bound.
            report: Optional quality sink called before each partition's publication gate.

        Returns:
            Explicit book snapshot identity for reopening with the selected book manifest type.

        Raises:
            ValueError: An input is incomplete, unsupported, malformed or exceeds its bounds.
        """
        partitions, payloads = [], []
        for directory in directories:
            selected = BookInput.read(directory, max_records=max_records)
            if type(max_bytes) is not int or not 0 < selected.raw.size_bytes <= max_bytes:
                raise ValueError("book raw input exceeds max_bytes")
            store.publish(
                directory / selected.raw.sha256,
                descriptor=selected.raw,
                request=selected.request.binding,
            )
            outcome = selected.admit(store, readers=self._readers, max_bytes=max_bytes)
            if report is not None:
                report(selected.request.identity, outcome)
            canonical = outcome.require_canonical()
            payloads.append(canonical)
            partitions.append(BookPartition(hashlib.sha256(canonical).hexdigest(), selected))
        manifest = BookDatasetManifest(
            normalization_identity=self._normalization_identity,
            partitions=tuple(partitions),
        )
        return SnapshotStore(
            destination, store, readers=self._readers, manifest_type=BookDatasetManifest
        ).publish(
            manifest,
            tuple(payloads),
            max_bytes=max_bytes,
        )

    def publish(
        self,
        acquisitions: tuple[DatasetInput, ...] | tuple[AcquisitionManifest, ...],
        store: RawStore,
        destination: Path,
        *,
        max_bytes: int,
        policy: QualityPolicy | None = None,
        eligibility: EligibilityAssertions | None = None,
        corrections: Mapping[str, tuple[Correction, ...]] | None = None,
        report: Callable[[str, QualityReport], None] | None = None,
        progress: Callable[[Literal["started", "complete"], DatasetManifest], None] | None = None,
    ) -> str:
        """Admit all selected inputs and atomically publish one complete snapshot.

        Args:
            acquisitions: Ordered DatasetInput records with per-source evidence, or complete
                daily acquisitions using shared evidence. Exact repeats are reused
                in first-seen order; nonidentical overlaps within a source/stream are rejected.
            store: Retained immutable raw objects needed by publication and later reads.
            destination: Existing, durably provisioned snapshot store directory.
            max_bytes: Positive per-file limit, including expanded archive bytes.
            policy: Shared declared use, knowledge cutoff and gap tolerance for acquisitions.
            eligibility: Shared retained eligibility history for acquisitions' catalog.
            corrections: Shared correction map by run identity. Omit all three shared inputs
                when supplying DatasetInput records; each retains its own evidence instead.
            report: Optional synchronous quality sink, called before each admission gate.
            progress: Optional publication sink receiving the candidate manifest at started,
                then complete only after verified reopening and durable acknowledgement.
                Callback failures propagate; a failed completion sink may leave a snapshot.

        Returns:
            Published dataset SHA-256 for explicit reopening with SnapshotStore.read.

        Raises:
            ValueError: Any selected input or admission contract fails.
            OSError: Persistence fails; retry verifies any already visible complete snapshot.
        """
        manifest, payloads = self.assemble(
            acquisitions,
            store,
            max_bytes=max_bytes,
            policy=policy,
            eligibility=eligibility,
            corrections=corrections,
            report=report,
        )
        if progress is not None:
            progress("started", manifest)
        identity = SnapshotStore(destination, store, readers=self._readers).publish(
            manifest, payloads, max_bytes=max_bytes
        )
        if progress is not None:
            progress("complete", manifest)
        return identity

    def assemble(
        self,
        acquisitions: tuple[DatasetInput, ...] | tuple[AcquisitionManifest, ...],
        store: RawStore,
        *,
        max_bytes: int,
        policy: QualityPolicy | None = None,
        eligibility: EligibilityAssertions | None = None,
        corrections: Mapping[str, tuple[Correction, ...]] | None = None,
        report: Callable[[str, QualityReport], None] | None = None,
    ) -> tuple[DatasetManifest, tuple[bytes, ...]]:
        """Admit saved partitions and assemble their manifest without publishing files.

        Args:
            acquisitions: Ordered DatasetInput records retaining each source's admission
                evidence, or complete daily acquisitions using shared evidence.
            store: Existing immutable raw objects, verified before admission.
            max_bytes: Positive compressed/expanded byte cap per raw archive.
            policy: Shared declared use, knowledge cutoff and gap tolerance for acquisitions.
            eligibility: Shared retained history matching the acquisitions' catalog.
            corrections: Shared correction map by run identity; use an empty mapping when
                absent. Omit all shared evidence when supplying DatasetInput records.
            report: Optional synchronous sink called with each run identity and quality outcome
                before its publication gate. Sink failures propagate without publication.

        Returns:
            Manifest and corresponding canonical bytes, only after every partition passes.
            The caller may save these working files; atomic snapshot publication is separate.

        Raises:
            ValueError: A partition is rejected, conflicting, incomplete or incompatibly bound.
        """
        inputs = DatasetInput.resolve(
            acquisitions, policy=policy, eligibility=eligibility, corrections=corrections
        )
        partitions: list[DatasetPartition] = []
        payloads: list[bytes] = []
        for selected in inputs:
            partitioned = selected.acquisition.partitions()
            unused = set(selected.corrections)
            for acquisition in partitioned:
                evidence = selected.corrections
                if evidence and len(partitioned) > 1:
                    try:
                        with closing(
                            self.occurrences(acquisition, store, max_bytes=max_bytes)
                        ) as rows:
                            versions = {
                                TradeRevision(occurrences=(item,)).identity for item in rows
                            }
                    except ValueError, TypeError, OSError, OverflowError:
                        # The quality gate below retains the input failure and invalid count.
                        pass
                    else:
                        evidence = tuple(
                            item
                            for item in evidence
                            if item.supersedes in versions or item.replacement in versions
                        )
                outcome = self.validate_partition(
                    acquisition,
                    store,
                    max_bytes=max_bytes,
                    policy=selected.policy,
                    eligibility=selected.eligibility,
                    corrections=evidence,
                    capture=selected.capture
                    if isinstance(selected.capture, ArchiveCapture)
                    else None,
                )
                if report is not None:
                    report(acquisition.run.identity, outcome)
                canonical = outcome.require_canonical()
                unused.difference_update(evidence)
                partitions.append(
                    DatasetPartition(
                        sha256=hashlib.sha256(canonical).hexdigest(),
                        acquisition=acquisition,
                        policy=selected.policy,
                        eligibility=selected.eligibility,
                        corrections=evidence,
                        capture=selected.capture,
                    )
                )
                payloads.append(canonical)
            if unused:
                raise ValueError(
                    "dataset correction evidence names an unselected partition payload"
                )
        witnessed = any(isinstance(part.capture, ArchiveCapture) for part in partitions)
        return DatasetManifest(
            schema_version="2" if witnessed else "1",
            canonical_schema="canonical-trade-partition-v2"
            if witnessed
            else "canonical-trade-partition-v1",
            availability_policy="native-witness-or-evidenced-later-v2"
            if witnessed
            else "original-or-evidenced-later-v1",
            normalization_identity=self._normalization_identity,
            scope="causal_witnessed"
            if all(p.policy.use == "witnessed" for p in partitions)
            else "exploratory_degraded",
            partitions=tuple(partitions),
        ), tuple(payloads)

    def validate_partition(
        self,
        manifest: AcquisitionManifest,
        store: RawStore,
        *,
        max_bytes: int,
        policy: QualityPolicy,
        eligibility: EligibilityAssertions,
        corrections: tuple[Correction, ...] = (),
        capture: ArchiveCapture | None = None,
    ) -> QualityReport:
        """Route one saved partition through quality admission before publication.

        Args:
            manifest: One selected instrument/day acquisition, with original raw identity.
            store: Immutable raw storage; originals remain retrievable after rejection.
            max_bytes: Positive compressed/expanded byte cap for the complete archive.
            policy: Declared use, eligibility cutoff and maximum observed silence.
            eligibility: Retained assertions tied to the acquisition's exact catalog/units.
            corrections: Explicit evidence linking economic versions within this partition.
            capture: Optional complete native captures for witnessed archive admission.

        Returns:
            Scoped report with invalid/gap counts; require_canonical refuses rejected input.
            A terminal read/decode failure rejects the whole partition, retaining its reason.

        Raises:
            ValueError: The selection spans multiple partitions or configuration is invalid.
        """
        requests = SourceRequest.partition(manifest.run)
        if len(requests) != 1:
            raise ValueError("quality requires exactly one selected instrument/source partition")
        with closing(self.occurrences(manifest, store, max_bytes=max_bytes)) as occurrences:
            return policy.validate(
                requests[0],
                occurrences,
                eligibility=eligibility,
                corrections=corrections,
                capture=capture,
                verifier=self._readers.verifier(requests[0]),
            )

    def admit_trades(
        self,
        manifests: tuple[AcquisitionManifest, ...],
        store: RawStore,
        *,
        max_bytes: int,
        policy: Literal["reject", "evidenced"],
        corrections: tuple[Correction, ...],
    ) -> tuple[TradeRevision, ...]:
        """Read complete saved inputs and admit duplicate/correction histories before return.

        Args:
            manifests: Explicit original and revised acquisitions for a bounded study.
            store: Verified immutable raw objects for every supplied acquisition.
            max_bytes: Positive compressed/expanded byte limit per archive.
            policy: Explicit conflict rejection or evidenced correction admission.
            corrections: Retained evidence linking the selected economic payload versions.

        Returns:
            One envelope per economic trade, including duplicate lineage and predecessors.
            The complete batch resides in memory; no snapshot or quality acceptance is implied.

        Raises:
            ValueError: A saved input, trade conflict or correction evidence fails admission.
            OSError: A required saved input is missing or unreadable.
        """
        inputs: list[Occurrence] = []
        for manifest in manifests:
            with closing(self.occurrences(manifest, store, max_bytes=max_bytes)) as occurrences:
                inputs.extend(occurrences)
        return TradeRevision.admit(inputs, policy=policy, corrections=corrections)

    def occurrences(
        self, manifest: AcquisitionManifest, store: RawStore, *, max_bytes: int
    ) -> Generator[Occurrence]:
        """Decode verified saved archive inputs under their retained resolved selection.

        Args:
            manifest: Explicit saved acquisition state containing resolved universe/bindings.
            store: Immutable raw storage, protected by the caller from concurrent mutation.
            max_bytes: Positive compressed/expanded byte cap per daily archive.

        Yields:
            Bound trades in partition/row order within the half-open research interval.

        Raises:
            ValueError: An incompatible binding, damaged input or malformed trade is encountered.
            OSError: An expected completion or stored object is missing or unreadable.

        Notes:
            The MR 08 archive reader is the supported persisted adapter. Existing Tardis
            fixtures use inspect_fixture. All rows are decoded before interval selection;
            exhaust for complete validation, or close an abandoned prefix. No quality,
            coverage, revision or publication acceptance follows from a yielded prefix.
        """
        for reader in self._readers.saved(manifest):
            with closing(reader.read(store, max_bytes=max_bytes)) as occurrences:
                yield from occurrences
