"""Inspect fixtures and compose saved-input admission through atomic snapshot publication."""

from __future__ import annotations

# standard library imports
import argparse
import sys
from pathlib import Path
from typing import Literal

# project library imports
from applications.publish_dataset.public import public_dataset
from market_data.acquisition import AcquisitionManifest
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import DatasetInput, DatasetManifest, DatasetPublication, SnapshotStore
from market_data.storage import RawStore
from market_data.validation import Correction, QualityPolicy, QualityReport
from reference_data.eligibility import EligibilityAssertions
from runtime import ImplementationIdentity
from serialization import DomainCodec


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


def main(argv: list[str] | None = None) -> int:
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
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] in (["discover"], ["public-publish"], ["public-read"]):
        return public_dataset(arguments)
    parser = argparse.ArgumentParser(
        description=__doc__,
        prog="alpha-dataset",
        epilog=(
            "Public data commands: alpha-dataset public-publish --help; "
            "alpha-dataset public-read --help; alpha-dataset discover --help"
        ),
    )
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
    args = parser.parse_args(arguments, namespace=_DatasetArguments())
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
            DatasetPublication(SourceAdapters(), ImplementationIdentity.sha256()).publish(
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
            manifest = SnapshotStore(args.snapshots, raw, readers=SourceAdapters()).read(
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
