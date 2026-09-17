"""Verify atomic visibility, immutable reuse and recovery at real snapshot boundaries."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.datasets import DatasetManifest
from alpha_research.data.eligibility import EligibilityAssertions
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.quality import QualityPolicy, QualityReport
from alpha_research.data.raw_objects import RawObject
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.data.snapshots import SnapshotStore
from alpha_research.pipelines.dataset import assemble_dataset, publish_dataset
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_LIMIT = 262_144


class _QualitySink:
    """Retain verified reports and optionally fail the caller's reporting boundary."""

    def __init__(self, *, fail: bool = False) -> None:
        """Start an isolated report collection with an optional sink failure."""
        self.reports: list[tuple[str, QualityReport]] = []
        self.fail = fail

    def report(self, identity: str, outcome: QualityReport) -> None:
        """Keep one reproduced partition result or propagate a failed sink."""
        if self.fail:
            raise OSError("report sink unavailable")
        self.reports.append((identity, outcome))


class _SyncFailure:
    """Fail one real synchronization boundary without changing the others."""

    def __init__(self, boundary: int) -> None:
        """Select a file, staged-directory or publication-directory synchronization.

        Args:
            boundary: One-based synchronization call to fail.
        """
        self._boundary = boundary
        self._calls = 0
        self._fsync = os.fsync

    def fsync(self, descriptor: int) -> None:
        """Raise the selected disk failure while preserving earlier synchronization."""
        self._calls += 1
        if self._calls == self._boundary:
            raise OSError("injected synchronization failure")
        self._fsync(descriptor)


class _CompetingPublisher:
    """Install a complete winner at the rename boundary and retain its file identities."""

    def __init__(self, store: SnapshotStore, identity: str) -> None:
        """Bind the reader used to inspect prepublication visibility.

        Args:
            store: Snapshot store being exercised.
            identity: Expected dataset identity.
        """
        self._store = store
        self._identity = identity
        self._rename = os.rename
        self.inodes: dict[str, int] = {}

    def rename(self, source: Path, destination: Path) -> None:
        """Install a competing snapshot and exercise the real directory collision."""
        with pytest.raises(FileNotFoundError):
            self._store.read(self._identity, max_bytes=_LIMIT)
        shutil.copytree(source, destination)
        self.inodes.update({path.name: path.stat().st_ino for path in destination.iterdir()})
        self._rename(source, destination)


class TestSnapshotStore:
    """Exercise two admitted instruments with independent raw and snapshot stores."""

    @pytest.fixture()
    def inputs(self, tmp_path: Path) -> tuple[DatasetManifest, tuple[bytes, ...], RawStore]:
        """Build complete deterministic synthetic partitions without publishing a snapshot.

        Args:
            tmp_path: Isolated raw-input and snapshot directories.

        Returns:
            Admitted manifest, ordered canonical bytes and their retained raw store.
        """
        raw = tmp_path / "raw"
        raw.mkdir()
        (tmp_path / "snapshots").mkdir()
        store = RawStore(raw)
        config = Configuration.read(_ROOT / "configs/data-jobs/binance-archive.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-archive-spot.json").read_bytes(), CatalogSnapshot
        )
        run = config.resolve("btc-archive", catalog)
        acquisitions: list[AcquisitionManifest] = []
        for symbol in ("BTCUSDT", "ETHUSDT"):
            instrument = next(item for item in catalog.instruments if item.symbol == symbol)
            selected = replace(run, instruments=(instrument,))
            request = SourceRequest.partition(selected)[0]
            source = raw / "source.zip"
            member = ZipInfo(f"{symbol}-trades-2024-06-01.csv")
            member.compress_type = ZIP_DEFLATED
            with ZipFile(source, "w") as archive:
                archive.writestr(member, b"12,100.00,2.0,200,1717200000000,true,true\n" * 2)
            descriptor = RawObject.from_file(
                source,
                request=request,
                retrieval_reference="synthetic:mr15",
                ts_received=datetime(2026, 9, 17, tzinfo=UTC),
                ts_ingested=datetime(2026, 9, 17, tzinfo=UTC),
            )
            store.publish(source, descriptor=descriptor, request=request)
            acquisitions.append(AcquisitionManifest(run=selected, completed=(descriptor,)))
        history = EligibilityAssertions.read(
            _ROOT / "tests/fixtures/mr12/eligibility.json", catalog=catalog
        )
        manifest, payloads = assemble_dataset(
            tuple(acquisitions),
            store,
            max_bytes=_LIMIT,
            policy=QualityPolicy(
                use="exploratory", known_at=run.job.start, max_gap=timedelta(hours=1)
            ),
            eligibility=history,
            corrections={},
        )
        return manifest, payloads, store

    def test_pipeline_reopen_reuse_and_new_snapshot(
        self, tmp_path: Path, inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore]
    ) -> None:
        """Publish the full pipeline result and preserve earlier bytes after a policy change."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        part = manifest.partitions[0]
        identity = publish_dataset(
            tuple(item.acquisition for item in manifest.partitions),
            raw,
            root,
            max_bytes=_LIMIT,
            policy=part.policy,
            eligibility=part.eligibility,
            corrections={},
        )
        assert identity == manifest.identity
        assert store.read(identity, max_bytes=_LIMIT) == manifest
        inodes = {path.name: path.stat().st_ino for path in (root / identity).iterdir()}
        assert store.publish(manifest, payloads, max_bytes=_LIMIT) == identity
        assert {path.name: path.stat().st_ino for path in (root / identity).iterdir()} == inodes
        changed = publish_dataset(
            tuple(item.acquisition for item in manifest.partitions),
            raw,
            root,
            max_bytes=_LIMIT,
            policy=replace(part.policy, max_gap=timedelta(minutes=5)),
            eligibility=part.eligibility,
            corrections={},
        )
        assert changed != identity
        assert store.read(changed, max_bytes=_LIMIT).scope == "exploratory_degraded"
        assert store.read(identity, max_bytes=_LIMIT) == manifest
        assert {path.name for path in root.iterdir()} == {identity, changed}
        for partition, payload in zip(manifest.partitions, payloads, strict=True):
            path = root / identity / partition.sha256
            assert path.read_bytes() == payload and path.stat().st_mode & 0o222 == 0

    def test_read_reports_only_verified_partitions_and_propagates_sink_failure(
        self, tmp_path: Path, inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore]
    ) -> None:
        """Reuse reproduced quality without allowing reports to acknowledge a damaged snapshot."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        identity = store.publish(manifest, payloads, max_bytes=_LIMIT)
        sink = _QualitySink()
        assert store.read(identity, max_bytes=_LIMIT, report=sink.report) == manifest
        assert [key for key, _ in sink.reports] == [
            item.acquisition.run.identity for item in manifest.partitions
        ]
        assert tuple(report.require_canonical() for _, report in sink.reports) == payloads
        with pytest.raises(OSError, match="report sink"):
            store.read(identity, max_bytes=_LIMIT, report=_QualitySink(fail=True).report)
        damaged = root / identity / manifest.partitions[1].sha256
        damaged.chmod(0o644)
        damaged.write_bytes(b"damaged")
        sink.reports.clear()
        with pytest.raises(ValueError, match="SHA-256"):
            store.read(identity, max_bytes=_LIMIT, report=sink.report)
        assert [key for key, _ in sink.reports] == [manifest.partitions[0].acquisition.run.identity]

    @pytest.mark.parametrize("limit", [0, -1, True, 10])
    def test_invalid_limits_never_publish(
        self,
        tmp_path: Path,
        inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore],
        limit: int,
    ) -> None:
        """Reject invalid or exceeded limits without exposing or retaining staging files."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        with pytest.raises(ValueError, match="max_bytes"):
            SnapshotStore(root, raw).publish(manifest, payloads, max_bytes=limit)
        assert list(root.iterdir()) == []

    def test_late_invalid_bytes_and_rejected_quality_never_publish(
        self, tmp_path: Path, inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore]
    ) -> None:
        """Refuse incomplete tuples, a damaged second partition and causal admission."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        for invalid in (payloads[:1], (*payloads, b"extra"), (payloads[0], b"damaged")):
            with pytest.raises(ValueError):
                store.publish(manifest, invalid, max_bytes=_LIMIT)
            assert list(root.iterdir()) == []
        part = manifest.partitions[0]
        with pytest.raises(ValueError, match="publication refused"):
            publish_dataset(
                tuple(item.acquisition for item in manifest.partitions),
                raw,
                root,
                max_bytes=_LIMIT,
                policy=replace(part.policy, use="causal"),
                eligibility=part.eligibility,
                corrections={},
            )
        assert list(root.iterdir()) == []

    @pytest.mark.parametrize("target", ["manifest", "canonical", "raw"])
    def test_missing_or_mutated_inputs_fail_without_replacement(
        self,
        tmp_path: Path,
        inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore],
        target: str,
    ) -> None:
        """Fail closed on damaged retained files, including idempotent publication retries."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        identity = store.publish(manifest, payloads, max_bytes=_LIMIT)
        part = manifest.partitions[0]
        path = root / identity / "manifest.json"
        if target == "canonical":
            path = root / identity / part.sha256
        elif target == "raw":
            path = tmp_path / "raw" / part.acquisition.completed[0].sha256
        original = path.read_bytes()
        path.unlink()
        with pytest.raises((OSError, ValueError)):
            store.read(identity, max_bytes=_LIMIT)
        path.write_bytes(b"damaged")
        with pytest.raises(ValueError):
            store.publish(manifest, payloads, max_bytes=_LIMIT)
        assert path.read_bytes() == b"damaged"
        path.write_bytes(original)
        assert store.read(identity, max_bytes=_LIMIT) == manifest

    def test_explicit_identity_and_nonregular_files(
        self, tmp_path: Path, inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore]
    ) -> None:
        """Never interpret a tag, staging path, symlink or empty directory as a snapshot."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        for invalid in ("latest", "", "../raw", ".staging-test", "A" * 64):
            with pytest.raises(ValueError, match="explicit lowercase"):
                store.read(invalid, max_bytes=_LIMIT)
        with pytest.raises(FileNotFoundError):
            store.read(manifest.identity, max_bytes=_LIMIT)
        (root / manifest.identity).mkdir()
        with pytest.raises(FileNotFoundError):
            store.publish(manifest, payloads, max_bytes=_LIMIT)
        (root / manifest.identity).rmdir()
        identity = store.publish(manifest, payloads, max_bytes=_LIMIT)
        (root / ("f" * 64)).symlink_to(root / identity, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            store.read("f" * 64, max_bytes=_LIMIT)
        canonical = root / identity / manifest.partitions[0].sha256
        canonical.unlink()
        canonical.symlink_to(root / identity / "manifest.json")
        with pytest.raises(ValueError, match="regular files"):
            store.read(identity, max_bytes=_LIMIT)

    @pytest.mark.parametrize("boundary", [1, 4, 5])
    def test_sync_failure_and_retry(
        self,
        tmp_path: Path,
        inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore],
        boundary: int,
    ) -> None:
        """Keep prepublication failures invisible and reconcile uncertain durable success."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        failure = _SyncFailure(boundary)
        with patch("alpha_research.data.snapshots.os.fsync", failure.fsync):
            with pytest.raises(OSError, match="synchronization failure"):
                store.publish(manifest, payloads, max_bytes=_LIMIT)
        assert (root / manifest.identity).exists() == (boundary == 5)
        assert not list(root.glob(".staging-*"))
        assert store.publish(manifest, payloads, max_bytes=_LIMIT) == manifest.identity
        assert store.read(manifest.identity, max_bytes=_LIMIT) == manifest

    def test_competing_publisher_is_verified_without_overwrite(
        self, tmp_path: Path, inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore]
    ) -> None:
        """Exercise the real nonempty-directory collision and preserve the winner's inodes."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        competitor = _CompetingPublisher(store, manifest.identity)
        with patch("alpha_research.data.snapshots.os.rename", competitor.rename):
            assert store.publish(manifest, payloads, max_bytes=_LIMIT) == manifest.identity
        assert {
            p.name: p.stat().st_ino for p in (root / manifest.identity).iterdir()
        } == competitor.inodes
        assert not list(root.glob(".staging-*"))

    @pytest.mark.integration
    @pytest.mark.parametrize("point", ["partial", "before", "after"])
    def test_process_death_preserves_prior_snapshot(
        self,
        tmp_path: Path,
        inputs: tuple[DatasetManifest, tuple[bytes, ...], RawStore],
        point: str,
    ) -> None:
        """Abruptly exit an installed writer and inspect visibility from the surviving reader."""
        manifest, payloads, raw = inputs
        root = tmp_path / "snapshots"
        store = SnapshotStore(root, raw)
        previous = replace(manifest, normalization_identity="a" * 64)
        store.publish(previous, payloads, max_bytes=_LIMIT)
        working = tmp_path / "working"
        working.mkdir()
        (working / "manifest.json").write_bytes(_CODEC.encode_json(manifest))
        for part, payload in zip(manifest.partitions, payloads, strict=True):
            (working / part.sha256).write_bytes(payload)
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(_ROOT / "tests/fixtures/mr15/interrupt_snapshot.py"),
                str(root),
                str(tmp_path / "raw"),
                str(working),
                point,
            ],
            cwd=tmp_path,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 75, completed.stderr.decode()
        assert store.read(previous.identity, max_bytes=_LIMIT) == previous
        if point == "after":
            assert store.read(manifest.identity, max_bytes=_LIMIT) == manifest
        else:
            with pytest.raises(FileNotFoundError):
                store.read(manifest.identity, max_bytes=_LIMIT)
            (orphan,) = root.glob(".staging-*")
            with pytest.raises(ValueError, match="explicit lowercase"):
                store.read(orphan.name, max_bytes=_LIMIT)
            if point == "partial":
                assert len(list(orphan.iterdir())) == 1
        assert store.publish(manifest, payloads, max_bytes=_LIMIT) == manifest.identity
        assert store.read(manifest.identity, max_bytes=_LIMIT) == manifest
        assert store.read(previous.identity, max_bytes=_LIMIT) == previous
