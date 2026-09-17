"""Verify installed dataset commands, progress, abrupt interruption and recovery."""

from __future__ import annotations

# standard library imports
import argparse
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
import alpha_research
from alpha_research.configuration import Configuration
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.quality import QualityPolicy
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec


class _Arguments(argparse.Namespace):
    """Type the external fixture directory."""

    inputs: Path


class _Progress(msgspec.Struct, frozen=True):
    """Read relevant command output fields while allowing additional diagnostics."""

    stage: str
    status: str
    snapshot_id: str | None
    scope: str | None = None
    duplicate_count: int | None = None
    invalid_count: int | None = None
    gap_count: int | None = None


class _Command:
    """Own subprocess invocation and typed progress assertions for this consumer."""

    def __init__(self, root: Path) -> None:
        """Bind an external working directory.

        Args:
            root: Existing directory outside the checkout.
        """
        self.root = root

    def run(
        self, arguments: list[str], *, status: int = 0, child: Path | None = None
    ) -> list[_Progress]:
        """Invoke the installed entry point and verify its exact process status."""
        executable = [str(Path(sys.executable).parent / "alpha-dataset")]
        if child is not None:
            executable = [sys.executable, "-I", str(child)]
        result = subprocess.run(
            [*executable, *arguments],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == status, (result.stdout, result.stderr)
        codec = DomainCodec()
        records = [codec.decode_json(line, _Progress) for line in result.stdout.splitlines()]
        if status == 0:
            assert not result.stderr and records[-1].status == "complete"
            assert records[-1].scope == "exploratory_degraded"
        elif status != 75:
            assert codec.decode_json(result.stderr, _Progress).status == "failed"
            assert not any(row.status == "complete" for row in records)
        return records


def main() -> None:
    """Exercise commands using only external inputs and installed runtime imports.

    Raises:
        AssertionError: Publication, reopening, progress or recovery violates the contract.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    inputs = parser.parse_args(namespace=_Arguments()).inputs.resolve()
    assert "site-packages" in Path(alpha_research.__file__).parts
    codec = DomainCodec()
    config = Configuration.read(inputs / "binance-archive.json")
    catalog = codec.decode_json(
        (inputs / "binance-archive-spot.json").read_bytes(), CatalogSnapshot
    )
    history = EligibilityAssertions.read(inputs / "eligibility.json", catalog=catalog)
    with TemporaryDirectory(prefix="mr16-consumer-") as temporary:
        root = Path(temporary)
        raw = root / "raw"
        raw.mkdir()
        snapshots = root / "snapshots"
        snapshots.mkdir()
        command = _Command(root)
        common = ["--store", str(raw), "--snapshots", str(snapshots), "--max-bytes", "262144"]
        (root / "eligibility.json").write_bytes(codec.encode_json(history))
        policy = QualityPolicy(
            use="exploratory", known_at=datetime(2024, 6, 1, tzinfo=UTC), max_gap=timedelta(hours=1)
        )
        policy_path = root / "policy.json"
        policy_path.write_bytes(codec.encode_json(policy))
        ids: list[str] = []
        for universe in ("btc", "eth"):
            selected = replace(config, jobs=(replace(config.jobs[0], universe=universe),))
            run = selected.resolve("btc-archive", catalog)
            request = SourceRequest.partition(run)[0]
            source = root / "source.zip"
            member = ZipInfo(f"{request.instrument.symbol}-trades-2024-06-01.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(source, "w") as archive:
                archive.writestr(member, b"12,100.00,2.0,200,1717200000000,true,true\n" * 2)
            descriptor = RawObject.from_file(
                source,
                request=request,
                retrieval_reference="synthetic:mr16",
                ts_received=datetime(2026, 9, 17, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 17, tzinfo=UTC),
            )
            RawStore(raw).publish(source, descriptor=descriptor, request=request)
            manifest_path = root / f"{universe}.json"
            AcquisitionManifest(run=run, completed=(descriptor,)).save(manifest_path)
            publish = [
                "publish",
                *common,
                "--policy",
                str(policy_path),
                "--eligibility",
                str(root / "eligibility.json"),
                "--manifests",
                str(manifest_path),
            ]
            stopped = command.run(publish, status=75, child=inputs / "interrupt_command.py")
            identity = stopped[-1].snapshot_id
            assert identity is not None and stopped[-1].stage == "publish"
            assert not (snapshots / identity).exists()
            command.run(["inspect", *common, "--snapshot-id", identity], status=4)
            for previous in ids:
                command.run(["inspect", *common, "--snapshot-id", previous])
            complete = command.run(publish)
            repeated = command.run([*publish, str(manifest_path)])
            assert complete[-1].snapshot_id == repeated[-1].snapshot_id == identity
            assert any(row.duplicate_count == 1 and row.invalid_count == 0 for row in complete)
            command.run(["inspect", *common, "--snapshot-id", identity])
            ids.append(identity)
            print("Published / repeated / reopened:", universe, identity)
        policy_path.write_bytes(
            codec.encode_json(replace(policy, use="causal", max_gap=timedelta(seconds=1)))
        )
        rejected = command.run(publish, status=3)
        assert rejected[-1].status == "rejected" and rejected[-1].gap_count == 1
        command.run(["inspect", *common, "--snapshot-id", "latest"], status=3)
        for identity in ids:
            command.run(["inspect", *common, "--snapshot-id", identity])
        assert len(list(snapshots.glob(".staging-*"))) == 2
    print("Installed MR 16 consumer passed:", alpha_research.__file__)


if __name__ == "__main__":
    main()
