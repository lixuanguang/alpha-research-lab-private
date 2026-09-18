"""Inspect fixtures and compose saved-input admission through atomic snapshot publication."""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import sys
from collections.abc import Callable, Generator, Mapping
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from alpha_research.configuration import Configuration, ResolvedManifest
from alpha_research.data.book_datasets import BookDatasetManifest, BookInput, BookPartition
from alpha_research.data.datasets import DatasetInput, DatasetManifest, DatasetPartition
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.events import MarketEventRecord
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.normalization import Occurrence
from alpha_research.data.providers.catalog import SourceAdapters
from alpha_research.data.quality import QualityPolicy, QualityReport
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.revisions import Correction, TradeRevision
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


class _InspectionArguments(argparse.Namespace):
    """Keep command input types explicit at the argparse boundary."""

    config: Path
    catalog: Path
    job: str
    fixture: Path
    received: str
    ingested: str
    sequence: int


def publish_book_dataset(
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
            directory / selected.raw.sha256, descriptor=selected.raw, request=selected.request
        )
        outcome = selected.admit(store, max_bytes=max_bytes)
        if report is not None:
            report(selected.request.identity, outcome)
        canonical = outcome.require_canonical()
        payloads.append(canonical)
        partitions.append(BookPartition(hashlib.sha256(canonical).hexdigest(), selected))
    manifest = BookDatasetManifest(
        normalization_identity=Configuration._implementation_identity(),
        partitions=tuple(partitions),
    )
    return SnapshotStore(destination, store, manifest_type=BookDatasetManifest).publish(
        manifest,
        tuple(payloads),
        max_bytes=max_bytes,
    )


def publish_dataset(
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
    manifest, payloads = assemble_dataset(
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
    identity = SnapshotStore(destination, store).publish(manifest, payloads, max_bytes=max_bytes)
    if progress is not None:
        progress("complete", manifest)
    return identity


def assemble_dataset(
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
                    with closing(iter_occurrences(acquisition, store, max_bytes=max_bytes)) as rows:
                        versions = {TradeRevision(occurrences=(item,)).identity for item in rows}
                except ValueError, TypeError, OSError, OverflowError:
                    # The quality gate below retains the input failure and invalid count.
                    pass
                else:
                    evidence = tuple(
                        item
                        for item in evidence
                        if item.supersedes in versions or item.replacement in versions
                    )
            outcome = validate_saved_partition(
                acquisition,
                store,
                max_bytes=max_bytes,
                policy=selected.policy,
                eligibility=selected.eligibility,
                corrections=evidence,
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
                )
            )
            payloads.append(canonical)
        if unused:
            raise ValueError("dataset correction evidence names an unselected partition payload")
    return DatasetManifest(
        normalization_identity=Configuration._implementation_identity(),
        partitions=tuple(partitions),
    ), tuple(payloads)


def validate_saved_partition(
    manifest: AcquisitionManifest,
    store: RawStore,
    *,
    max_bytes: int,
    policy: QualityPolicy,
    eligibility: EligibilityAssertions,
    corrections: tuple[Correction, ...] = (),
) -> QualityReport:
    """Route one saved partition through quality admission before publication.

    Args:
        manifest: One selected instrument/day acquisition, with original raw identity.
        store: Immutable raw storage; originals remain retrievable after rejection.
        max_bytes: Positive compressed/expanded byte cap for the complete archive.
        policy: Declared use, eligibility cutoff and maximum observed silence.
        eligibility: Retained assertions tied to the acquisition's exact catalog/units.
        corrections: Explicit evidence linking economic versions within this partition.

    Returns:
        Scoped report with invalid/gap counts; require_canonical refuses rejected input.
        A terminal read/decode failure rejects the whole partition, retaining its reason.

    Raises:
        ValueError: The selection spans multiple partitions or configuration is invalid.
    """
    requests = SourceRequest.partition(manifest.run)
    if len(requests) != 1:
        raise ValueError("quality requires exactly one selected instrument/source partition")
    with closing(iter_occurrences(manifest, store, max_bytes=max_bytes)) as occurrences:
        return policy.validate(
            requests[0], occurrences, eligibility=eligibility, corrections=corrections
        )


def admit_saved_trades(
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
        with closing(iter_occurrences(manifest, store, max_bytes=max_bytes)) as occurrences:
            inputs.extend(occurrences)
    return TradeRevision.admit(inputs, policy=policy, corrections=corrections)


def iter_occurrences(
    manifest: AcquisitionManifest, store: RawStore, *, max_bytes: int
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
    for reader in SourceAdapters.saved(manifest):
        with closing(reader.read(store, max_bytes=max_bytes)) as occurrences:
            yield from occurrences


def inspect_fixture(
    manifest: ResolvedManifest,
    fixture: Path,
    *,
    local_received: datetime,
    local_ingested: datetime,
    source_sequence: int,
) -> tuple[SourceRequest, MarketEventRecord, str]:
    """Read a bounded saved frame, compose the decoders and bind its source request.

    Args:
        manifest: Resolved selection validated before fixture access.
        fixture: UTF-8 file with exactly one nonblank trade frame, at most one MiB.
        local_received: Explicit original receipt time; never inferred from this attempt.
        local_ingested: Explicit original ingestion time, preserved by the decoder.
        source_sequence: Original zero-based line position, supplied by the caller.

    Returns:
        Matching minute request, exact canonical trade and SHA-256 of the saved bytes.

    Raises:
        OSError: The fixture cannot be read.
        ValueError: Frame, clocks, stream, instrument or capture interval is invalid.
        TypeError: A supplied decoder boundary value has an invalid type.
    """
    manifest.__post_init__()
    if manifest.job.pipeline != "dataset.inspect":
        raise ValueError("fixture inspection requires the dataset.inspect pipeline")
    with fixture.open("rb") as source:
        payload = source.read(1_048_577)
    if len(payload) > 1_048_576:
        raise ValueError("fixture exceeds one MiB; supply one saved trade frame")
    line = payload.decode("utf-8").removesuffix("\n").removesuffix("\r")
    if not line or "\n" in line or "\r" in line:
        raise ValueError("fixture must contain exactly one nonblank trade frame")
    digest = hashlib.sha256(payload).hexdigest()
    decoder = SourceAdapters.fixture(manifest)
    request, event = decoder.decode(
        line,
        source_sequence=source_sequence,
        local_received=local_received,
        local_ingested=local_ingested,
        source_digest=digest,
    )
    return request, event, digest


class _DatasetArguments(argparse.Namespace):
    """Type explicit saved inputs and enforce bounded strict file decoding."""

    action: str
    store: Path
    snapshots: Path
    max_bytes: int
    manifests: list[Path] | None
    inputs: list[Path] | None
    policy: Path | None
    eligibility: Path | None
    correction: list[list[str]]
    snapshot_id: str

    def read[T](self, path: Path, target: type[T]) -> T:
        """Read one required input without treating absence as an empty acquisition."""
        with path.open("rb") as source:
            payload = source.read(self.max_bytes + 1)
        if len(payload) > self.max_bytes:
            raise ValueError(f"{path.name} exceeds max_bytes")
        return DomainCodec().decode_json(payload, target)


class _DatasetOutput:
    """Emit flushed command progress without serializing canonical observations."""

    def __init__(self) -> None:
        """Initialize attempt-local progress; an unacknowledged ID is only a candidate."""
        self.stage: str = "configuration"
        self.snapshot_id: str | None = None

    def emit(self, status: str, **fields: object) -> None:
        """Write a safe JSON record to the status-appropriate stream."""
        record = {"stage": self.stage, "status": status, "snapshot_id": self.snapshot_id, **fields}
        print(
            DomainCodec().encode_json(record).decode(),
            file=sys.stderr if status in {"failed", "interrupted"} else sys.stdout,
            flush=True,
        )

    def quality(self, run_identity: str, report: QualityReport) -> None:
        """Expose each complete or rejected partition's counts and evidence limitations."""
        self.emit(
            "rejected" if report.scope == "rejected" else "validated",
            run_identity=run_identity,
            scope=report.scope,
            invalid_count=report.invalid_count,
            gap_count=report.gap_count,
            duplicate_count=report.duplicate_count,
            reasons=report.reasons,
        )

    def publication(
        self, status: Literal["started", "complete"], manifest: DatasetManifest
    ) -> None:
        """Report the candidate before persistence and acknowledge verified durable completion."""
        self.stage = "publish"
        self.snapshot_id = manifest.identity
        if status == "started":
            self.emit("started", partitions=len(manifest.partitions))
        else:
            self.emit("persisted")
            self.emit(
                "complete", scope=manifest.scope, partitions=len(manifest.partitions), exit_code=0
            )


def dataset_main(argv: list[str] | None = None) -> int:
    """Publish saved acquisitions or inspect an explicitly selected immutable snapshot.

    Args:
        argv: Command arguments, or process arguments when omitted. Publish accepts
            complete daily manifests; exact repeated manifests are reused. Selected
            instruments become separate partitions without changing raw identities.
            Correction pairs bind one strict evidence file to its retained run identity.

    Returns:
        Zero only after verified reopening, two for configuration, three for admission,
        four for I/O/unexpected failure, or 130 for interruption. Failed publication can
        leave a complete visible snapshot; retry the same command to acknowledge it.

    Raises:
        SystemExit: Argparse handles help or invalid syntax.
        OSError: An unwritable terminal report propagates.
    """
    parser = argparse.ArgumentParser(description=__doc__, prog="alpha-dataset")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("publish", "inspect"):
        command = commands.add_parser(action)
        for option in ("store", "snapshots"):
            command.add_argument(f"--{option}", type=Path, required=True)
        command.add_argument("--max-bytes", type=int, required=True)
        if action == "publish":
            selection = command.add_mutually_exclusive_group(required=True)
            selection.add_argument("--manifests", type=Path, nargs="+")
            selection.add_argument("--inputs", type=Path, nargs="+")
            for option in ("policy", "eligibility"):
                command.add_argument(f"--{option}", type=Path)
            command.add_argument(
                "--correction", nargs=2, action="append", default=list[list[str]]()
            )
        else:
            command.add_argument("--snapshot-id", required=True)
    args = parser.parse_args(argv, namespace=_DatasetArguments())
    output = _DatasetOutput()
    try:
        if args.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        raw = RawStore(args.store)
        output.emit("started", action=args.action)
        if args.action == "publish":
            policy: QualityPolicy | None = None
            eligibility: EligibilityAssertions | None = None
            corrections: dict[str, tuple[Correction, ...]] | None = None
            if args.inputs is not None:
                if args.policy is not None or args.eligibility is not None or args.correction:
                    raise ValueError("--inputs retains its own policy, eligibility and corrections")
            else:
                if args.policy is None or args.eligibility is None or args.manifests is None:
                    raise ValueError("--manifests requires --policy and --eligibility")
                policy = args.read(args.policy, QualityPolicy)
                eligibility = args.read(args.eligibility, EligibilityAssertions)
                corrections = {}
                for run_identity, path in args.correction:
                    corrections[run_identity] = (
                        *corrections.get(run_identity, ()),
                        args.read(Path(path), Correction),
                    )
            output.stage = "normalize"
            output.emit("started")
            acquisitions: tuple[DatasetInput, ...] | tuple[AcquisitionManifest, ...]
            if args.inputs is not None:
                acquisitions = tuple(args.read(path, DatasetInput) for path in args.inputs)
            elif args.manifests is not None:
                acquisitions = tuple(
                    args.read(path, AcquisitionManifest) for path in args.manifests
                )
            else:
                raise ValueError("publication requires explicit saved inputs")
            publish_dataset(
                acquisitions,
                raw,
                args.snapshots,
                max_bytes=args.max_bytes,
                policy=policy,
                eligibility=eligibility,
                corrections=corrections,
                report=output.quality,
                progress=output.publication,
            )
        else:
            output.snapshot_id = args.snapshot_id
            output.stage = "reopen"
            output.emit("started")
            manifest = SnapshotStore(args.snapshots, raw).read(
                args.snapshot_id, max_bytes=args.max_bytes, report=output.quality
            )
            output.emit(
                "complete", scope=manifest.scope, partitions=len(manifest.partitions), exit_code=0
            )
    except (Exception, KeyboardInterrupt) as error:
        status = 2 if output.stage == "configuration" else 3
        if isinstance(error, OSError) or not isinstance(error, (ValueError, TypeError)):
            status = 4
        if isinstance(error, KeyboardInterrupt):
            status = 130
        output.emit(
            "interrupted" if status == 130 else "failed",
            exit_code=status,
            error_type=type(error).__name__,
            diagnostic=str(error),
            recovery="Check inputs/policy and retained stores, then retry the same command; "
            "an unacknowledged publication may be complete. Inspect only its explicit ID.",
        )
        return status
    return 0


def main(argv: list[str] | None = None) -> int:
    """Resolve an offline job and print a canonical event or an actionable diagnostic.

    Args:
        argv: Command arguments, or process arguments when omitted.

    Returns:
        Zero on success, two for configuration/usage, three for fixture/decoding,
        or four for local I/O failure. Argument syntax errors exit with two.

    Raises:
        SystemExit: Argument parsing handles help or invalid command syntax.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("config", "catalog", "fixture"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    for option in ("job", "received", "ingested"):
        parser.add_argument(f"--{option}", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    arguments = parser.parse_args(argv, namespace=_InspectionArguments())
    codec = DomainCodec()
    run_identity: str | None = None
    stage = "configuration"
    try:
        configuration = Configuration.read(arguments.config)
        with arguments.catalog.open("rb") as source:
            catalog_bytes = source.read(1_048_577)
        if len(catalog_bytes) > 1_048_576:
            raise ValueError("catalog exceeds one MiB")
        catalog = codec.decode_json(catalog_bytes, CatalogSnapshot)
        manifest = configuration.resolve(arguments.job, catalog)
        run_identity = manifest.identity
        stage = "fixture"
        request, event, digest = inspect_fixture(
            manifest,
            arguments.fixture,
            local_received=datetime.fromisoformat(arguments.received),
            local_ingested=datetime.fromisoformat(arguments.ingested),
            source_sequence=arguments.sequence,
        )
        print(
            codec.encode_json(
                {
                    "schema_version": "1",
                    "run_identity": run_identity,
                    "manifest": manifest,
                    "request_identity": request.identity,
                    "request_start": request.start,
                    "request_end": request.end,
                    "fixture_sha256": digest,
                    "event": event,
                }
            ).decode()
        )
    except (OSError, ValueError, TypeError, OverflowError) as error:
        status = 4 if isinstance(error, OSError) else (2 if stage == "configuration" else 3)
        print(
            codec.encode_json(
                {
                    "status": "error",
                    "stage": stage,
                    "exit_code": status,
                    "job": arguments.job,
                    "run_identity": run_identity,
                    "diagnostic": str(error),
                }
            ).decode(),
            file=sys.stderr,
        )
        return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
