"""Verify sequential resume, abrupt checkpoints and bounded source-only retries."""

from __future__ import annotations

# standard library imports
import gzip
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from http.client import HTTPSConnection
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration, ResolvedManifest
from alpha_research.data.manifests import AcquisitionManifest
from alpha_research.data.providers.tardis.transport import TardisTransport, TransientFetchError
from alpha_research.data.raw_store import RawStore
from alpha_research.data.requests import SourceRequest
from alpha_research.pipelines.acquisition import acquire
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()


class TestAcquisitionResume:
    """Protect the manifest/store boundary through the installed pipeline consumer."""

    @pytest.fixture()
    def run(self) -> ResolvedManifest:
        """Resolve one instrument over three synthetic minute partitions.

        Returns:
            Historical acquisition selection with explicit synthetic rights.
        """
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        original = configuration.resolve("btc-fixture", catalog)
        return replace(
            original,
            job=replace(
                original.job,
                mode="historical",
                pipeline="acquisition.fetch",
                end=original.job.start + timedelta(minutes=3),
            ),
        )

    @staticmethod
    def _clock() -> datetime:
        """Return one deterministic UTC receipt/durability instant."""
        return datetime(2026, 9, 15, tzinfo=UTC)

    def _run(
        self,
        run: ResolvedManifest,
        root: Path,
        waits: list[float],
        reports: list[str],
        retry_delays: tuple[float, ...] = (0.1, 0.2),
    ) -> AcquisitionManifest:
        """Compose an isolated destination with fake timing and the actual pipeline."""
        (root / "raw").mkdir(exist_ok=True)
        return acquire(
            run,
            manifest_path=root / "manifest.json",
            store=RawStore(root / "raw"),
            connection=HTTPSConnection("api.tardis.dev"),
            clock=self._clock,
            sleep=waits.append,
            report=reports.append,
            timeout_seconds=1.0,
            max_bytes=4096,
            permitted_rights_reference="synthetic-local-fixtures-v1",
            retry_delays=retry_delays,
        )

    @staticmethod
    def _process(root: Path, run_path: Path, point: str) -> subprocess.CompletedProcess[str]:
        """Run a fresh isolated interpreter outside the checkout at a real fault boundary."""
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(_ROOT / "tests/fixtures/mr06/acquire.py"),
                str(root),
                str(run_path),
                point,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    @pytest.mark.parametrize(
        "point", ["before-raw", "after-raw", "before-checkpoint", "after-checkpoint"]
    )
    def test_process_restart_matches_uninterrupted_manifest(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
        point: str,
    ) -> None:
        """Keep each logical completion once across abrupt raw/checkpoint publication exits."""
        run_path = tmp_path / "run.json"
        run_path.write_bytes(_CODEC.encode_json(run))
        baseline, interrupted = tmp_path / "baseline", tmp_path / "interrupted"
        for root in (baseline, interrupted):
            (root / "raw").mkdir(parents=True)
        result = self._process(baseline, run_path, "none")
        assert result.returncode == 0, result.stderr
        result = self._process(interrupted, run_path, point)
        assert result.returncode == 75, result.stderr
        before = _CODEC.decode_json(
            (interrupted / "manifest.json").read_bytes(), AcquisitionManifest
        )
        assert len(before.completed) == (2 if point == "after-checkpoint" else 1)
        inodes = {
            path.name: path.stat().st_ino
            for path in (interrupted / "raw").iterdir()
            if not path.name.startswith(".")
        }
        result = self._process(interrupted, run_path, "none")
        assert result.returncode == 0, result.stderr
        assert (interrupted / "manifest.json").read_bytes() == (
            baseline / "manifest.json"
        ).read_bytes()
        assert (interrupted / "fetches.txt").read_text().splitlines() == (
            ["0", "1", "1", "2"] if point == "before-raw" else ["0", "1", "2"]
        )
        assert all(
            (interrupted / "raw" / name).stat().st_ino == inode for name, inode in inodes.items()
        )
        result = self._process(interrupted, run_path, "none")
        assert result.returncode == 0, result.stderr
        assert (interrupted / "manifest.json").read_bytes() == (
            baseline / "manifest.json"
        ).read_bytes()
        assert (interrupted / "fetches.txt").read_text().count("2\n") == 1

    def test_retry_then_continue_and_exhaustion_retains_prefix(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
    ) -> None:
        """Retry only the active partition with exact finite waits; restart skips the prefix."""
        payload = gzip.compress(b"observation\n", mtime=0)
        waits: list[float] = []
        reports: list[str] = []
        failure = TransientFetchError("temporary")
        outcomes: list[bytes | TransientFetchError] = [payload, failure, failure, failure]
        with patch.object(TardisTransport, "fetch", side_effect=outcomes) as fetch:
            with pytest.raises(TransientFetchError):
                self._run(run, tmp_path, waits, reports)
            assert fetch.call_count == 4
        state = _CODEC.decode_json((tmp_path / "manifest.json").read_bytes(), AcquisitionManifest)
        assert len(state.completed) == 1 and state.pending is None
        assert waits == [0.1, 0.2]
        assert sum('"status":"retry"' in row for row in reports) == 2
        waits.clear()
        outcomes = [failure, payload, payload]
        with patch.object(TardisTransport, "fetch", side_effect=outcomes) as fetch:
            resumed = self._run(run, tmp_path, waits, reports)
            assert fetch.call_count == 3
        assert len(resumed.completed) == 3 and resumed.completed[0] == state.completed[0]
        assert waits == [0.1]

    @pytest.mark.parametrize(
        "failure", [PermissionError("denied"), ValueError("schema"), OSError("terminal")]
    )
    def test_terminal_source_failure_does_not_retry(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
        failure: Exception,
    ) -> None:
        """Leave a persisted empty run when authentication, schema or permanent I/O fails."""
        waits: list[float] = []
        with patch.object(TardisTransport, "fetch", side_effect=failure) as fetch:
            with pytest.raises(type(failure)):
                self._run(run, tmp_path, waits, [])
        assert fetch.call_count == 1 and not waits
        state = _CODEC.decode_json((tmp_path / "manifest.json").read_bytes(), AcquisitionManifest)
        assert not state.completed and state.pending is None

    @pytest.mark.parametrize("damage", ["missing", "mutation", "truncation"])
    def test_completed_corruption_fails_before_source_access(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
        damage: str,
    ) -> None:
        """Never silently refetch an acknowledged object that has disappeared or changed."""
        with patch.object(
            TardisTransport, "fetch", return_value=gzip.compress(b"fixture", mtime=0)
        ):
            state = self._run(run, tmp_path, [], [])
        path = tmp_path / "raw" / state.completed[0].sha256
        if damage == "missing":
            path.unlink()
        else:
            payload = path.read_bytes()
            path.chmod(0o644)
            path.write_bytes(payload[:-1] if damage == "truncation" else b"X" + payload[1:])
        manifest = (tmp_path / "manifest.json").read_bytes()
        with patch.object(TardisTransport, "fetch") as fetch:
            with pytest.raises((ValueError, FileNotFoundError)):
                self._run(run, tmp_path, [], [])
            fetch.assert_not_called()
        assert (tmp_path / "manifest.json").read_bytes() == manifest

    def test_publication_failure_is_terminal_and_receipt_can_recover(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
    ) -> None:
        """Keep a write-ahead receipt on disk failure and re-fetch only unpublished bytes."""
        waits: list[float] = []
        with patch.object(
            TardisTransport, "fetch", return_value=gzip.compress(b"one", mtime=0)
        ) as fetch:
            with patch.object(RawStore, "publish", side_effect=OSError("disk full")):
                with pytest.raises(OSError, match="disk full"):
                    self._run(run, tmp_path, waits, [])
            assert fetch.call_count == 1 and not waits
        state = _CODEC.decode_json((tmp_path / "manifest.json").read_bytes(), AcquisitionManifest)
        assert not state.completed and state.pending is not None
        with patch.object(
            TardisTransport, "fetch", return_value=gzip.compress(b"two", mtime=0)
        ) as fetch:
            resumed = self._run(run, tmp_path, waits, [])
            assert fetch.call_count == 3
        assert len(resumed.completed) == 3 and resumed.completed[0].sha256 != state.pending.sha256

    @pytest.mark.parametrize("delays", [(-1.0,), (float("nan"),)])
    def test_invalid_retry_policy_fails_before_io(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
        delays: tuple[float, ...],
    ) -> None:
        """Reject invalid waits before writing a manifest or constructing source work."""
        with pytest.raises(ValueError, match="retry_delays"):
            self._run(run, tmp_path, [], [], delays)
        assert not (tmp_path / "manifest.json").exists()

    @pytest.mark.parametrize("is_corrupt", [False, True])
    def test_pending_publication_preserves_receipt_or_rejects_mutation(
        self,
        tmp_path: Path,
        run: ResolvedManifest,
        is_corrupt: bool,
    ) -> None:
        """Recover published pending bytes without a fetch and timestamp confirmed durability."""
        requests = SourceRequest.partition(run)
        early = self._clock() - timedelta(hours=1)
        (tmp_path / "raw").mkdir()
        store = RawStore(tmp_path / "raw")
        with patch.object(
            TardisTransport, "fetch", return_value=gzip.compress(b"original", mtime=0)
        ):
            state = self._run(run, tmp_path, [], [])
        pending = replace(state.completed[0], ts_received=early, ts_ingested=early)
        AcquisitionManifest(run=run, pending=pending).save(tmp_path / "manifest.json")
        if is_corrupt:
            path = tmp_path / "raw" / pending.sha256
            path.chmod(0o644)
            path.write_bytes(b"damaged")
            with patch.object(TardisTransport, "fetch") as fetch:
                with pytest.raises(ValueError, match="size mismatch"):
                    self._run(run, tmp_path, [], [])
                fetch.assert_not_called()
        else:
            with patch.object(
                TardisTransport, "fetch", return_value=gzip.compress(b"later", mtime=0)
            ) as fetch:
                recovered = self._run(run, tmp_path, [], [])
                assert fetch.call_count == 2
            first = recovered.completed[0]
            assert first.ts_received == early and first.ts_ingested == self._clock()
            assert first.sha256 == pending.sha256
            with store.open(descriptor=first, request=requests[0]) as saved:
                assert gzip.decompress(saved.read()) == b"original"
