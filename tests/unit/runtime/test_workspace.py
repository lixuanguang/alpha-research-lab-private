"""Verify complete workspace backup, mutation rejection and atomic restoration."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from research.experiments import AttemptStore
from runtime import JobQueue, JobRun, JobSpec, JobWorkerPool, WorkspaceBackup

_PIN = hashlib.sha256(b"installed-test-artifact").hexdigest()


class _EchoHandler:
    """Retain one output file to exercise result and queue restoration."""

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Write a local artifact under the isolated attempt directory."""
        (run.work_directory / "report.txt").write_text("reopened study")
        return spec.request


class _Workspace:
    """Provision a small linked dataset, feature, attempt, artifact and job state."""

    @staticmethod
    def prepare(root: Path) -> JobQueue:
        """Create retained component bytes and one completed durable job."""
        root.mkdir()
        for component in ("attempts", "datasets", "features", "artifacts"):
            (root / component).mkdir()
        (root / "attempts" / "attempt.json").write_bytes(b'{"attempt":"complete"}')
        (root / "datasets" / "pinned.bin").write_bytes(b"raw-and-canonical-data")
        (root / "features" / "version.bin").write_bytes(b"matched-cutoff-feature")
        (root / "artifacts" / "result.bin").write_bytes(b"retained-result")
        queue = JobQueue(root / "jobs")
        queue.submit(
            JobSpec(
                job_id="saved-study",
                kind="echo",
                run_at=datetime.now(UTC) - timedelta(seconds=1),
                implementation_sha256=_PIN,
                configuration_sha256=_PIN,
                input_sha256=_PIN,
                environment_sha256=_PIN,
                request=b"complete-job",
            )
        )
        JobWorkerPool(
            queue,
            {"echo": _EchoHandler()},
            max_workers=1,
            implementation_sha256=_PIN,
            environment_sha256=_PIN,
        ).run_until_idle()
        return queue


class TestWorkspaceBackup:
    """Back up and restore reopenable workspaces without partial or active state."""

    def test_backup_restores_reopenable_store_and_verified_bytes(self, tmp_path: Path) -> None:
        """A complete backup reopens exact component bytes and SQLite WAL state."""
        source = tmp_path / "workspace"
        _Workspace.prepare(source)
        backup = tmp_path / "backup"
        components = ("attempts", "datasets", "features", "artifacts", "jobs")
        identity = WorkspaceBackup.create(source, backup, components=components)
        manifest = WorkspaceBackup.verify(backup)
        assert identity == hashlib.sha256((backup / "manifest.json").read_bytes()).hexdigest()
        assert manifest.components == components
        destination = tmp_path / "restored"
        restored = WorkspaceBackup.restore(backup, destination)
        assert restored == manifest
        assert (destination / "datasets" / "pinned.bin").read_bytes() == b"raw-and-canonical-data"
        assert (destination / "features" / "version.bin").read_bytes() == b"matched-cutoff-feature"
        assert (destination / "artifacts" / "result.bin").read_bytes() == b"retained-result"
        assert (destination / "attempts" / "attempt.json").read_bytes() == b'{"attempt":"complete"}'
        assert JobQueue(destination / "jobs").read("saved-study").result == b"complete-job"
        report = destination / "jobs" / "results" / "saved-study" / "report.txt"
        assert report.read_text() == "reopened study"

    def test_backup_refuses_active_job_pool(self, tmp_path: Path) -> None:
        """A fenced worker prevents a snapshot from claiming quiescence."""
        source = tmp_path / "workspace"
        queue = _Workspace.prepare(source)
        pool = JobWorkerPool(
            queue,
            {"echo": _EchoHandler()},
            max_workers=1,
            implementation_sha256=_PIN,
            environment_sha256=_PIN,
        )
        with pool:
            assert queue.health().is_worker_active
            with pytest.raises(BlockingIOError):
                WorkspaceBackup.create(source, tmp_path / "busy-backup", components=("jobs",))
        assert not queue.health().is_worker_active
        assert not (tmp_path / "busy-backup").exists()

    def test_corrupt_backup_never_publishes_restore(self, tmp_path: Path) -> None:
        """Digest failure leaves the requested restore destination absent."""
        source = tmp_path / "workspace"
        _Workspace.prepare(source)
        backup = tmp_path / "backup"
        WorkspaceBackup.create(source, backup, components=("datasets", "features", "jobs"))
        (backup / "payload" / "features" / "version.bin").write_bytes(b"altered")
        destination = tmp_path / "restored"
        with pytest.raises(ValueError, match=r"size differs|digest differs"):
            WorkspaceBackup.restore(backup, destination)
        assert not destination.exists()

    def test_restore_refuses_existing_workspace(self, tmp_path: Path) -> None:
        """An active or prior destination cannot be replaced by a backup."""
        source = tmp_path / "workspace"
        _Workspace.prepare(source)
        backup = tmp_path / "backup"
        WorkspaceBackup.create(source, backup, components=("datasets",))
        existing = tmp_path / "existing"
        existing.mkdir()
        with pytest.raises(FileExistsError, match="absent"):
            WorkspaceBackup.restore(backup, existing)

    def test_backup_leaves_out_dispatch_lease_locks(self, tmp_path: Path) -> None:
        """A live send's lease lock file is transient coordination, never retained."""
        source = tmp_path / "workspace"
        _Workspace.prepare(source)
        lock = source / "datasets" / "account.sqlite3.lease-0123abcd"
        lock.write_bytes(b"")
        backup = tmp_path / "backup"
        WorkspaceBackup.create(source, backup, components=("datasets",))
        restored = tmp_path / "restored"
        WorkspaceBackup.restore(backup, restored)
        assert not (restored / "datasets" / lock.name).exists()

    def test_backup_refuses_nested_study_writer(self, tmp_path: Path) -> None:
        """A family-scoped AttemptStore lock also blocks a workspace snapshot."""
        source = tmp_path / "workspace"
        family = source / "studies" / "family-a"
        family.mkdir(parents=True)
        (family / "start.json").write_bytes(b"retained-start")
        with (family / ".writer.lock").open("a+b") as writer:
            fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError):
                WorkspaceBackup.create(source, tmp_path / "busy-backup", components=("studies",))

    def test_backup_refuses_open_study_session(self, tmp_path: Path) -> None:
        """An open AttemptStore session blocks a snapshot even between its mutations."""
        source = tmp_path / "workspace"
        (source / "attempts").mkdir(parents=True)
        with AttemptStore(source / "attempts"):
            with pytest.raises(BlockingIOError):
                WorkspaceBackup.create(source, tmp_path / "busy-backup", components=("attempts",))
        WorkspaceBackup.create(source, tmp_path / "backup", components=("attempts",))
        assert not (tmp_path / "busy-backup").exists()

    def test_mutable_sqlite_wal_and_immutable_serving_bytes_restore(self, tmp_path: Path) -> None:
        """Capture committed WAL rows while preserving pinned Feast generation bytes."""
        source = tmp_path / "workspace"
        features = source / "features"
        serving = source / "serving" / "generation" / "data"
        features.mkdir(parents=True)
        serving.mkdir(parents=True)
        history = features / "history.sqlite3"
        database = sqlite3.connect(history)
        try:
            database.execute("PRAGMA journal_mode=WAL")
            database.execute("PRAGMA wal_autocheckpoint=0")
            database.execute("CREATE TABLE versions (name TEXT PRIMARY KEY, payload BLOB NOT NULL)")
            database.execute("INSERT INTO versions VALUES (?, ?)", ("current", b"matched-cutoff"))
            database.commit()
            assert Path(f"{history}-wal").exists()
            online = serving / "online.db"
            online.write_bytes(b"SQLite format 3\x00immutable-pinned-generation")
            online_sha = hashlib.sha256(online.read_bytes()).hexdigest()
            backup = tmp_path / "backup"
            WorkspaceBackup.create(source, backup, components=("features", "serving"))
        finally:
            database.close()
        restored = tmp_path / "restored"
        WorkspaceBackup.restore(backup, restored)
        with closing(sqlite3.connect(restored / "features" / "history.sqlite3")) as connection:
            row = cast(
                object,
                connection.execute("SELECT payload FROM versions WHERE name='current'").fetchone(),
            )
            assert row == (b"matched-cutoff",)
        assert (
            hashlib.sha256(
                (restored / "serving" / "generation" / "data" / "online.db").read_bytes()
            ).hexdigest()
            == online_sha
        )
