"""Exercise durable job claims, bounded workers, retry and restart behavior."""

from __future__ import annotations

# standard library imports
import hashlib
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest

# project library imports
from runtime import JobQueue, JobRun, JobSpec, JobWorkerPool

_PIN = hashlib.sha256(b"installed-test-artifact").hexdigest()
_ENVIRONMENT = hashlib.sha256(b"test-environment").hexdigest()


class _Jobs:
    """Construct explicit pinned test jobs without a mutable global clock."""

    @staticmethod
    def spec(
        job_id: str,
        *,
        run_at: datetime | None = None,
        max_attempts: int = 3,
        retry_delay_seconds: int = 0,
    ) -> JobSpec:
        """Create one valid local test request."""
        return JobSpec(
            job_id=job_id,
            kind="test-work",
            run_at=run_at or datetime.now(UTC) - timedelta(seconds=1),
            implementation_sha256=_PIN,
            configuration_sha256=hashlib.sha256(b"config").hexdigest(),
            input_sha256=hashlib.sha256(b"input").hexdigest(),
            environment_sha256=_ENVIRONMENT,
            request=b"pinned-input",
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )


class _RetryHandler:
    """Fail once after retaining a diagnostic, then complete under the same key."""

    def __init__(self) -> None:
        """Retain observed retry keys and attempt directories."""
        self.keys: list[str] = []
        self.directories: list[Path] = []

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Publish no result on the first attempt, then return complete bytes."""
        self.keys.append(run.idempotency_key)
        self.directories.append(run.work_directory)
        run.report_progress(1, 2)
        (run.work_directory / "evidence.txt").write_text(f"attempt={run.attempt_index}")
        if run.attempt_index == 1:
            raise OSError("transient test failure")
        run.report_progress(2, 2)
        return spec.request + b"-complete"


class _CountingHandler:
    """Count invocations that a recovered published result must avoid."""

    def __init__(self) -> None:
        """Start with no worker invocations."""
        self.calls = 0

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Return only if the queue wrongly reexecutes published work."""
        self.calls += 1
        return spec.request


class _BlockingHandler:
    """Observe bounded overlap and cooperative cancellation."""

    def __init__(self, target: int) -> None:
        """Wait until a declared number of workers is active."""
        self.target = target
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Hold an active claim until the test releases it."""
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= self.target:
                self.started.set()
        try:
            if not self.release.wait(timeout=5):
                raise TimeoutError("test worker was not released")
            return spec.request
        finally:
            with self.lock:
                self.active -= 1


def test_scheduling_and_queued_cancel_survive_reopening(tmp_path: Path) -> None:
    """A future due time and queued cancellation are durable across queue instances."""
    queue = JobQueue(tmp_path / "jobs")
    spec = _Jobs.spec("future-job", run_at=datetime.now(UTC) + timedelta(days=1))
    assert queue.submit(spec).status == "queued"
    assert (
        JobWorkerPool(
            queue,
            {"test-work": _CountingHandler()},
            max_workers=1,
            implementation_sha256=_PIN,
            environment_sha256=_ENVIRONMENT,
        )
        .run_until_idle()
        .queued
        == 1
    )
    assert JobQueue(tmp_path / "jobs").cancel(spec.job_id).status == "cancelled"
    assert JobQueue(tmp_path / "jobs").read(spec.job_id).attempts == 0


def test_retry_reuses_key_and_preserves_failed_attempt(tmp_path: Path) -> None:
    """A transient handler failure cannot rewrite its evidence or change the stable key."""
    queue = JobQueue(tmp_path / "jobs")
    handler = _RetryHandler()
    spec = _Jobs.spec("retry-job", max_attempts=2)
    queue.submit(spec)
    health = JobWorkerPool(
        queue,
        {"test-work": handler},
        max_workers=2,
        implementation_sha256=_PIN,
        environment_sha256=_ENVIRONMENT,
    ).run_until_idle()
    state = queue.read(spec.job_id)
    assert health.completed == 1
    assert state.status == "completed"
    assert state.attempts == 2
    assert state.progress is not None and state.progress.completed == 2
    assert state.result == b"pinned-input-complete"
    assert handler.keys == [spec.job_id, spec.job_id]
    assert (handler.directories[0] / "evidence.txt").read_text() == "attempt=1"
    assert (queue.root / "results" / spec.job_id / "evidence.txt").read_text() == "attempt=2"
    assert queue.submit(spec).attempts == 2
    with pytest.raises(ValueError, match="different pinned inputs"):
        queue.submit(_Jobs.spec("retry-job", run_at=spec.run_at + timedelta(seconds=1)))


def test_restart_adopts_published_output_without_running_handler(tmp_path: Path) -> None:
    """A crash after atomic rename but before SQLite completion does not rerun effects."""
    queue = JobQueue(tmp_path / "jobs")
    spec = _Jobs.spec("crash-job")
    queue.submit(spec)
    claimed = queue._claim()
    assert claimed is not None
    work = queue.root / "work" / spec.job_id / "1"
    work.mkdir(parents=True)
    (work / "artifact.bin").write_bytes(b"retained-output")
    queue._publish_result(spec.job_id, 1, work, b"complete", 1_048_576)
    handler = _CountingHandler()
    JobWorkerPool(
        JobQueue(tmp_path / "jobs"),
        {"test-work": handler},
        max_workers=1,
        implementation_sha256=_PIN,
        environment_sha256=_ENVIRONMENT,
    ).run_until_idle()
    assert handler.calls == 0
    assert queue.read(spec.job_id).result == b"complete"
    artifact = queue.root / "results" / spec.job_id / "artifact.bin"
    assert artifact.read_bytes() == b"retained-output"


def test_workers_are_bounded_and_running_cancel_is_cooperative(tmp_path: Path) -> None:
    """Two workers overlap, a third waits, and cancel suppresses its result publication."""
    queue = JobQueue(tmp_path / "jobs")
    for job_id in ("work-a", "work-b", "work-c"):
        queue.submit(_Jobs.spec(job_id))
    handler = _BlockingHandler(target=2)
    pool = JobWorkerPool(
        queue,
        {"test-work": handler},
        max_workers=2,
        implementation_sha256=_PIN,
        environment_sha256=_ENVIRONMENT,
    )
    thread = threading.Thread(target=pool.run_until_idle)
    thread.start()
    try:
        assert handler.started.wait(timeout=5)
        running = tuple(state.spec.job_id for state in queue.list() if state.status == "running")
        assert len(running) == 2
        assert queue.cancel(running[0]).cancel_requested
    finally:
        handler.release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert handler.peak == 2
    assert queue.read(running[0]).status == "cancelled"
    assert queue.read(running[0]).result is None
    assert queue.health().completed == 2


def test_published_result_tampering_fails_closed(tmp_path: Path) -> None:
    """A changed output file is never returned as a completed job result."""
    queue = JobQueue(tmp_path / "jobs")
    spec = _Jobs.spec("tamper-job")
    queue.submit(spec)
    JobWorkerPool(
        queue,
        {"test-work": _CountingHandler()},
        max_workers=1,
        implementation_sha256=_PIN,
        environment_sha256=_ENVIRONMENT,
    ).run_until_idle()
    (queue.root / "results" / spec.job_id / "result.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="output bytes differ"):
        queue.read(spec.job_id)


def test_result_receipt_cannot_escape_job_directory(tmp_path: Path) -> None:
    """Changed receipt paths are rejected before any named file is opened."""
    queue = JobQueue(tmp_path / "jobs")
    spec = _Jobs.spec("unsafe-receipt")
    queue.submit(spec)
    JobWorkerPool(
        queue,
        {"test-work": _CountingHandler()},
        max_workers=1,
        implementation_sha256=_PIN,
        environment_sha256=_ENVIRONMENT,
    ).run_until_idle()
    receipt = queue.root / "results" / spec.job_id / "receipt.json"
    original = receipt.read_bytes()
    assert b'"name":"result.bin"' in original
    receipt.write_bytes(original.replace(b'"name":"result.bin"', b'"name":"../outside"'))
    with pytest.raises(ValueError, match="receipt file metadata"):
        queue.read(spec.job_id)


def test_secret_values_and_bad_worker_pin_are_rejected(tmp_path: Path) -> None:
    """Persist only explicit references and refuse a worker with mismatched installed bytes."""
    queue = JobQueue(tmp_path / "jobs")
    spec = _Jobs.spec("pin-job", max_attempts=1)
    with pytest.raises(ValueError, match="secret://"):
        queue.submit(
            JobSpec(
                job_id="bad-secret",
                kind=spec.kind,
                run_at=spec.run_at,
                implementation_sha256=spec.implementation_sha256,
                configuration_sha256=spec.configuration_sha256,
                input_sha256=spec.input_sha256,
                environment_sha256=spec.environment_sha256,
                secret_refs=("credential-value",),
            )
        )
    queue.submit(spec)
    handler = _CountingHandler()
    JobWorkerPool(
        queue,
        {"test-work": handler},
        max_workers=1,
        implementation_sha256=hashlib.sha256(b"different").hexdigest(),
        environment_sha256=_ENVIRONMENT,
    ).run_until_idle()
    assert handler.calls == 0
    assert queue.read(spec.job_id).status == "failed"
