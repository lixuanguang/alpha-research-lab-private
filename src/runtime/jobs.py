"""Schedule durable local jobs with bounded workers and atomic local results."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import os
import re
import sqlite3
import stat
import threading
from collections.abc import Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Literal, Protocol, Self, cast

# project library imports
from serialization import DomainCodec, WireRecord, publish_directory, sync_directory

type JobStatus = Literal["queued", "running", "retry", "completed", "failed", "cancelled"]

_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_REF = re.compile(r"secret://[a-zA-Z0-9][a-zA-Z0-9_./-]{0,127}\Z")


class JobSpec(WireRecord, frozen=True, kw_only=True):
    """Pin a job to its actual artifact, configuration, inputs and worker environment."""

    job_id: str
    kind: str
    run_at: datetime
    implementation_sha256: str
    configuration_sha256: str
    input_sha256: str
    environment_sha256: str
    request: bytes = b""
    secret_refs: tuple[str, ...] = ()
    max_attempts: int = 3
    retry_delay_seconds: int = 1

    def __post_init__(self) -> None:
        """Reject ambiguous identities, embedded credentials and unbounded retry policy."""
        if (
            type(self.job_id) is not str
            or type(self.kind) is not str
            or not _NAME.fullmatch(self.job_id)
            or not _NAME.fullmatch(self.kind)
        ):
            raise ValueError("job identity and kind must be lowercase safe names")
        self._require_utc(self.run_at, field_name="run_at")
        for digest in (
            self.implementation_sha256,
            self.configuration_sha256,
            self.input_sha256,
            self.environment_sha256,
        ):
            if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
                raise ValueError("job pins must be lowercase SHA-256 digests")
        if type(self.request) is not bytes or len(self.request) > 1_048_576:
            raise ValueError("job request must be at most 1 MiB of bytes")
        if type(self.secret_refs) is not tuple or any(
            type(ref) is not str or _SECRET_REF.fullmatch(ref) is None for ref in self.secret_refs
        ):
            raise ValueError("job secrets must be explicit secret:// references")
        if len(set(self.secret_refs)) != len(self.secret_refs):
            raise ValueError("job secret references must be unique")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 10:
            raise ValueError("job max_attempts must be between 1 and 10")
        if type(self.retry_delay_seconds) is not int or not 0 <= self.retry_delay_seconds <= 3600:
            raise ValueError("job retry delay must be between 0 and 3600 seconds")


class JobState(WireRecord, frozen=True, kw_only=True):
    """Expose a persisted job transition and a verified local result if complete."""

    spec: JobSpec
    status: JobStatus
    attempts: int
    next_run_at: datetime
    cancel_requested: bool
    progress: JobProgress | None
    result: bytes | None
    last_error: str | None


class JobProgress(WireRecord, frozen=True, kw_only=True):
    """Retain one worker's completed units for its current attempt."""

    attempt_index: int
    completed: int
    total: int
    updated_at: datetime


class JobHealth(WireRecord, frozen=True, kw_only=True):
    """Summarize queue and worker progress without exposing request or secret bytes."""

    queued: int
    running: int
    retry: int
    completed: int
    failed: int
    cancelled: int
    oldest_due_at: datetime | None
    is_worker_active: bool


class JobRun:
    """Give a handler a stable key and an isolated, durable attempt directory."""

    def __init__(self, queue: JobQueue, job_id: str, attempt_index: int, work_directory: Path):
        """Bind execution context to the queue's persisted cancellation request."""
        self._queue = queue
        self.idempotency_key = job_id
        self.attempt_index = attempt_index
        self.work_directory = work_directory

    def cancel_requested(self) -> bool:
        """Observe cooperative cancellation before starting another effect."""
        return self._queue.read(self.idempotency_key).cancel_requested

    def report_progress(self, completed: int, total: int) -> JobProgress:
        """Persist monotonic completed units for this attempt without sensitive text."""
        return self._queue._progress(self.idempotency_key, self.attempt_index, completed, total)


class JobHandler(Protocol):
    """Execute a pinned job under a stable key; external effects require own deduplication."""

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Return bounded result bytes after writing only isolated local outputs."""
        ...


class _ResultFile(WireRecord, frozen=True, kw_only=True):
    """Record one immutable local result file."""

    name: str
    size_bytes: int
    sha256: str


class _ResultReceipt(WireRecord, frozen=True, kw_only=True):
    """Witness the complete output directory before its atomic publication."""

    schema_version: Literal["local-job-result"]
    job_id: str
    attempt_index: int
    files: tuple[_ResultFile, ...]

    def __post_init__(self) -> None:
        """Keep saved receipt names inside one bounded immutable result directory."""
        if (
            self.schema_version != "local-job-result"
            or type(self.job_id) is not str
            or _NAME.fullmatch(self.job_id) is None
            or type(self.attempt_index) is not int
            or self.attempt_index < 1
        ):
            raise ValueError("published job receipt identity is invalid")
        if not 1 <= len(self.files) <= 1025:
            raise ValueError("published job receipt file count is invalid")
        names: set[str] = set()
        total = 0
        for record in self.files:
            if type(record) is not _ResultFile:
                raise ValueError("published job receipt file metadata is invalid")
            path = Path(record.name)
            if (
                not record.name
                or path.is_absolute()
                or path.as_posix() != record.name
                or any(part in (".", "..") for part in path.parts)
                or record.name == "receipt.json"
                or record.name in names
                or type(record.size_bytes) is not int
                or record.size_bytes < 0
                or type(record.sha256) is not str
                or _DIGEST.fullmatch(record.sha256) is None
            ):
                raise ValueError("published job receipt file metadata is invalid")
            names.add(record.name)
            total += record.size_bytes
        result_record = next((record for record in self.files if record.name == "result.bin"), None)
        if (
            result_record is None
            or result_record.size_bytes > 1_048_576
            or total > 1_073_741_824 + 1_048_576
        ):
            raise ValueError("published job receipt output budget is invalid")


class JobQueue:
    """Persist one local queue with transactional claims and immutable result directories.

    A single worker pool holds ``.workers.lock``. Multiple submitters and readers
    may use independent SQLite connections. The queue uses a local POSIX filesystem.
    """

    def __init__(self, root: Path) -> None:
        """Provision a local queue and its SQLite WAL database."""
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "work").mkdir(exist_ok=True)
        (root / "results").mkdir(exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    spec BLOB NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    next_run_us INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL,
                    result_sha256 TEXT,
                    last_error TEXT
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS progress (
                    job_id TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL,
                    completed INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    updated_us INTEGER NOT NULL,
                    PRIMARY KEY(job_id, attempt_index)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        """Open one short-lived transaction with durable local write settings."""
        connection = sqlite3.connect(self.root / "jobs.sqlite3", timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        """Keep administrative queue mutations out of a quiesced workspace backup."""
        with (self.root / ".workspace.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            yield

    @staticmethod
    def _query_one(
        connection: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
    ) -> tuple[object, ...] | None:
        """Narrow an untyped SQLite row at the persistence boundary."""
        raw = cast(object, connection.execute(query, params).fetchone())
        if raw is None:
            return None
        if not isinstance(raw, tuple):
            raise ValueError("job database returned a non-row value")
        return cast(tuple[object, ...], raw)

    @staticmethod
    def _query_all(
        connection: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
    ) -> tuple[tuple[object, ...], ...]:
        """Narrow a SQLite result set without allowing dynamic values into domain state."""
        raw = cast(object, connection.execute(query, params).fetchall())
        if not isinstance(raw, list):
            raise ValueError("job database returned a non-list result")
        rows: list[tuple[object, ...]] = []
        for value in raw:
            if not isinstance(value, tuple):
                raise ValueError("job database returned a non-row value")
            rows.append(cast(tuple[object, ...], value))
        return tuple(rows)

    @staticmethod
    def _text(value: object) -> str:
        """Require one saved SQLite text field."""
        if type(value) is not str:
            raise ValueError("job database text field is malformed")
        return value

    @staticmethod
    def _integer(value: object) -> int:
        """Require one saved SQLite integer field."""
        if type(value) is not int:
            raise ValueError("job database integer field is malformed")
        return value

    @staticmethod
    def _bytes(value: object) -> bytes:
        """Require one saved SQLite blob field."""
        if type(value) is not bytes:
            raise ValueError("job database blob field is malformed")
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        """Require an absent or saved SQLite text field."""
        if value is None:
            return None
        return JobQueue._text(value)

    @staticmethod
    def _status(value: object) -> JobStatus:
        """Reject unknown saved job transitions."""
        if value == "queued":
            return "queued"
        if value == "running":
            return "running"
        if value == "retry":
            return "retry"
        if value == "completed":
            return "completed"
        if value == "failed":
            return "failed"
        if value == "cancelled":
            return "cancelled"
        raise ValueError("job database contains an unknown status")

    def submit(self, spec: JobSpec) -> JobState:
        """Submit once by stable job ID; identical repeats return the retained state.

        Raises:
            ValueError: A job ID is reused with different pinned request bytes.
        """
        spec.__post_init__()
        payload = DomainCodec().encode_json(spec)
        with self._mutation_lock(), closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._query_one(
                connection, "SELECT spec FROM jobs WHERE job_id = ?", (spec.job_id,)
            )
            if existing is None:
                connection.execute(
                    "INSERT INTO jobs VALUES (?, ?, 'queued', 0, ?, 0, NULL, NULL)",
                    (spec.job_id, payload, self._epoch_us(spec.run_at)),
                )
            elif self._bytes(existing[0]) != payload:
                raise ValueError("job ID already binds different pinned inputs")
        return self.read(spec.job_id)

    def read(self, job_id: str) -> JobState:
        """Reload one state and verify any completed local result before returning it."""
        self._require_name(job_id)
        with closing(self._connect()) as connection, connection:
            row = self._query_one(
                connection,
                "SELECT spec, status, attempts, next_run_us, cancel_requested, result_sha256, "
                "last_error FROM jobs WHERE job_id = ?",
                (job_id,),
            )
        if row is None:
            raise KeyError(job_id)
        spec = DomainCodec().decode_json(self._bytes(row[0]), JobSpec)
        spec.__post_init__()
        if spec.job_id != job_id:
            raise ValueError("job database specification identity differs")
        status = self._status(row[1])
        attempts = self._integer(row[2])
        with closing(self._connect()) as connection, connection:
            progress_row = self._query_one(
                connection,
                "SELECT completed, total, updated_us FROM progress "
                "WHERE job_id=? AND attempt_index=?",
                (job_id, attempts),
            )
        progress = (
            None
            if progress_row is None
            else JobProgress(
                attempt_index=attempts,
                completed=self._integer(progress_row[0]),
                total=self._integer(progress_row[1]),
                updated_at=datetime.fromtimestamp(
                    self._integer(progress_row[2]) / 1_000_000, tz=UTC
                ),
            )
        )
        result = None
        if status == "completed":
            result = self._verify_result(job_id, self._optional_text(row[5]))
        return JobState(
            spec=spec,
            status=status,
            attempts=attempts,
            next_run_at=datetime.fromtimestamp(self._integer(row[3]) / 1_000_000, tz=UTC),
            cancel_requested=self._integer(row[4]) == 1,
            progress=progress,
            result=result,
            last_error=self._optional_text(row[6]),
        )

    def list(self) -> tuple[JobState, ...]:
        """List all retained jobs in stable ID order."""
        with closing(self._connect()) as connection, connection:
            ids = tuple(
                self._text(row[0])
                for row in self._query_all(connection, "SELECT job_id FROM jobs ORDER BY job_id")
            )
        return tuple(self.read(job_id) for job_id in ids)

    def cancel(self, job_id: str) -> JobState:
        """Cancel unstarted work or request cooperative stop from a running handler."""
        self._require_name(job_id)
        with self._mutation_lock(), closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._query_one(connection, "SELECT status FROM jobs WHERE job_id = ?", (job_id,))
            if row is None:
                raise KeyError(job_id)
            if self._status(row[0]) in ("queued", "retry"):
                connection.execute(
                    "UPDATE jobs SET status='cancelled', cancel_requested=1 WHERE job_id=?",
                    (job_id,),
                )
            elif row[0] == "running":
                connection.execute("UPDATE jobs SET cancel_requested=1 WHERE job_id=?", (job_id,))
        return self.read(job_id)

    def health(self) -> JobHealth:
        """Report durable status counts and the earliest queued/retry eligibility time."""
        counts = dict.fromkeys(
            ("queued", "running", "retry", "completed", "failed", "cancelled"), 0
        )
        with closing(self._connect()) as connection, connection:
            for count_row in self._query_all(
                connection, "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            ):
                counts[self._status(count_row[0])] = self._integer(count_row[1])
            row = self._query_one(
                connection, "SELECT MIN(next_run_us) FROM jobs WHERE status IN ('queued', 'retry')"
            )
        due = (
            None
            if row is None or row[0] is None
            else datetime.fromtimestamp(self._integer(row[0]) / 1_000_000, tz=UTC)
        )
        return JobHealth(
            queued=counts["queued"],
            running=counts["running"],
            retry=counts["retry"],
            completed=counts["completed"],
            failed=counts["failed"],
            cancelled=counts["cancelled"],
            oldest_due_at=due,
            is_worker_active=self._worker_active(),
        )

    def _worker_active(self) -> bool:
        """Observe the pool ownership fence without relying on a stale running row."""
        with (self.root / ".workers.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return False

    def _claim(self) -> JobState | None:
        """Atomically claim one due job, preserving its stable ID across retries."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._query_one(
                connection,
                "SELECT job_id FROM jobs WHERE status IN ('queued', 'retry') AND next_run_us <= ? "
                "ORDER BY next_run_us, job_id LIMIT 1",
                (self._epoch_us(datetime.now(UTC)),),
            )
            if row is None:
                return None
            job_id = self._text(row[0])
            connection.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1 WHERE job_id=?",
                (job_id,),
            )
        return self.read(job_id)

    def _recover(self) -> None:
        """Adopt committed output after a crash; retry only unpublished work."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = self._query_all(
                connection,
                "SELECT job_id, spec, attempts, cancel_requested FROM jobs WHERE status='running'",
            )
            for row in rows:
                job_id = self._text(row[0])
                spec = DomainCodec().decode_json(self._bytes(row[1]), JobSpec)
                attempts = self._integer(row[2])
                is_cancelled = self._integer(row[3]) == 1
                spec.__post_init__()
                if spec.job_id != job_id:
                    raise ValueError("job database specification identity differs")
                if (self.root / "results" / job_id).is_dir():
                    result = self._verify_result(job_id, None)
                    sync_directory(self.root / "results")
                    connection.execute(
                        "UPDATE jobs SET status='completed', result_sha256=? WHERE job_id=?",
                        (hashlib.sha256(result).hexdigest(), job_id),
                    )
                elif is_cancelled:
                    connection.execute(
                        "UPDATE jobs SET status='cancelled' WHERE job_id=?", (job_id,)
                    )
                elif attempts >= spec.max_attempts:
                    connection.execute(
                        "UPDATE jobs SET status='failed', last_error='worker_lost' WHERE job_id=?",
                        (job_id,),
                    )
                else:
                    connection.execute(
                        "UPDATE jobs SET status='retry', next_run_us=?, last_error='worker_lost' "
                        "WHERE job_id=?",
                        (self._epoch_us(datetime.now(UTC)), job_id),
                    )

    def _finish(
        self, job_id: str, attempt: int, result_sha256: str | None, error: str | None
    ) -> None:
        """Record only the claimed attempt's terminal or bounded retry transition."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._query_one(
                connection,
                "SELECT spec, status, attempts, cancel_requested FROM jobs WHERE job_id=?",
                (job_id,),
            )
            if row is None or self._status(row[1]) != "running" or self._integer(row[2]) != attempt:
                raise RuntimeError("job claim changed before completion")
            spec = DomainCodec().decode_json(self._bytes(row[0]), JobSpec)
            spec.__post_init__()
            if result_sha256 is not None:
                connection.execute(
                    "UPDATE jobs SET status='completed', result_sha256=?, last_error=NULL "
                    "WHERE job_id=?",
                    (result_sha256, job_id),
                )
            elif self._integer(row[3]) == 1:
                connection.execute(
                    "UPDATE jobs SET status='cancelled', last_error=? WHERE job_id=?",
                    (error, job_id),
                )
            elif attempt >= spec.max_attempts:
                connection.execute(
                    "UPDATE jobs SET status='failed', last_error=? WHERE job_id=?",
                    (error, job_id),
                )
            else:
                backoff = min(spec.retry_delay_seconds * (1 << (attempt - 1)), 3600)
                next_run = datetime.now(UTC) + timedelta(seconds=backoff)
                connection.execute(
                    "UPDATE jobs SET status='retry', next_run_us=?, last_error=? WHERE job_id=?",
                    (self._epoch_us(next_run), error, job_id),
                )

    def _progress(self, job_id: str, attempt: int, completed: int, total: int) -> JobProgress:
        """Persist bounded monotonic progress for the active claim."""
        if (
            type(completed) is not int
            or type(total) is not int
            or not 0 <= completed <= total <= 1_000_000_000
            or total == 0
        ):
            raise ValueError("job progress requires bounded completed and total units")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            claim = self._query_one(
                connection, "SELECT status, attempts FROM jobs WHERE job_id=?", (job_id,)
            )
            if (
                claim is None
                or self._status(claim[0]) != "running"
                or self._integer(claim[1]) != attempt
            ):
                raise RuntimeError("job progress requires the active claim")
            prior = self._query_one(
                connection,
                "SELECT completed, total FROM progress WHERE job_id=? AND attempt_index=?",
                (job_id, attempt),
            )
            if prior is not None and (
                self._integer(prior[1]) != total or self._integer(prior[0]) > completed
            ):
                raise ValueError("job progress cannot regress or change total units")
            updated_at = datetime.now(UTC)
            connection.execute(
                "INSERT INTO progress VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id, attempt_index) DO UPDATE SET "
                "completed=excluded.completed, updated_us=excluded.updated_us",
                (job_id, attempt, completed, total, self._epoch_us(updated_at)),
            )
        return JobProgress(
            attempt_index=attempt, completed=completed, total=total, updated_at=updated_at
        )

    def _publish_result(
        self, job_id: str, attempt: int, directory: Path, result: bytes, max_output_bytes: int
    ) -> str:
        """Verify, sync and atomically reveal a complete local result directory."""
        if type(result) is not bytes or len(result) > 1_048_576:
            raise ValueError("job result must be at most 1 MiB of bytes")
        if (directory / "result.bin").exists() or (directory / "receipt.json").exists():
            raise ValueError("handler output uses reserved result filenames")
        files: list[_ResultFile] = []
        total = len(result)
        for path in sorted(directory.rglob("*")):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("job outputs must contain only regular files and directories")
            name = path.relative_to(directory).as_posix()
            if len(files) >= 1024 or path.stat().st_size + total > max_output_bytes:
                raise ValueError("job outputs exceed bounded file or byte budget")
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1_048_576), b""):
                    digest.update(chunk)
                os.fsync(source.fileno())
            size = path.stat().st_size
            total += size
            files.append(_ResultFile(name=name, size_bytes=size, sha256=digest.hexdigest()))
        with (directory / "result.bin").open("xb") as output:
            output.write(result)
            output.flush()
            os.fsync(output.fileno())
        files.append(
            _ResultFile(
                name="result.bin", size_bytes=len(result), sha256=hashlib.sha256(result).hexdigest()
            )
        )
        receipt = _ResultReceipt(
            schema_version="local-job-result",
            job_id=job_id,
            attempt_index=attempt,
            files=tuple(files),
        )
        with (directory / "receipt.json").open("xb") as output:
            output.write(DomainCodec().encode_json(receipt))
            output.flush()
            os.fsync(output.fileno())
        for path in sorted(directory.rglob("*"), reverse=True):
            if path.is_dir():
                sync_directory(path)
        destination = self.root / "results" / job_id
        if not publish_directory(directory, destination):
            raise FileExistsError("published job result already exists")
        return hashlib.sha256(result).hexdigest()

    def _verify_result(self, job_id: str, expected_sha256: str | None) -> bytes:
        """Reject missing, extra or changed published output bytes."""
        directory = self.root / "results" / job_id
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("published job result directory is missing or unsafe")
        if not stat.S_ISREG((directory / "receipt.json").lstat().st_mode):
            raise ValueError("published job receipt file is unsafe")
        receipt = DomainCodec().decode_json(
            (directory / "receipt.json").read_bytes(), _ResultReceipt
        )
        receipt.__post_init__()
        if receipt.schema_version != "local-job-result" or receipt.job_id != job_id:
            raise ValueError("published job receipt identity differs")
        actual: set[str] = set()
        for path in directory.rglob("*"):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("published job output has unsafe file type")
            actual.add(path.relative_to(directory).as_posix())
        names = {record.name for record in receipt.files}
        if actual != names | {"receipt.json"} or len(names) != len(receipt.files):
            raise ValueError("published job result file inventory differs")
        for record in receipt.files:
            path = directory / record.name
            if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink():
                raise ValueError("published job output has unsafe file type")
            if path.stat().st_size != record.size_bytes:
                raise ValueError("published job output bytes differ")
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1_048_576), b""):
                    digest.update(chunk)
            if digest.hexdigest() != record.sha256:
                raise ValueError("published job output bytes differ")
        result = (directory / "result.bin").read_bytes()
        if expected_sha256 is not None and hashlib.sha256(result).hexdigest() != expected_sha256:
            raise ValueError("published job result digest differs")
        return result

    @staticmethod
    def _epoch_us(at: datetime) -> int:
        """Store UTC scheduling time at integer microsecond precision."""
        return int(at.timestamp() * 1_000_000)

    @staticmethod
    def _require_name(name: str) -> None:
        """Keep externally supplied job IDs out of filesystem paths and SQL ambiguity."""
        if type(name) is not str or _NAME.fullmatch(name) is None:
            raise ValueError("invalid job identity")


class JobWorkerPool:
    """Run at most ``max_workers`` independent claims under one fenced pool owner."""

    def __init__(
        self,
        queue: JobQueue,
        handlers: Mapping[str, JobHandler],
        *,
        max_workers: int,
        implementation_sha256: str,
        environment_sha256: str,
        max_output_bytes: int = 67_108_864,
    ) -> None:
        """Bind installed and environment identity to the selected handler set."""
        if type(max_workers) is not int or not 1 <= max_workers <= 32:
            raise ValueError("max_workers must be between 1 and 32")
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 1_073_741_824:
            raise ValueError("max_output_bytes must be positive and at most 1 GiB")
        if (
            _DIGEST.fullmatch(implementation_sha256) is None
            or _DIGEST.fullmatch(environment_sha256) is None
        ):
            raise ValueError("worker identities must be lowercase SHA-256 digests")
        self._queue = queue
        self._handlers = dict(handlers)
        self._max_workers = max_workers
        self._implementation_sha256 = implementation_sha256
        self._environment_sha256 = environment_sha256
        self._max_output_bytes = max_output_bytes
        self._lock: BinaryIO | None = None

    def __enter__(self) -> Self:
        """Fence other pools before crash recovery or worker execution."""
        if self._lock is not None:
            raise RuntimeError("job pool already owns its worker lock")
        lock = (self._queue.root / ".workers.lock").open("a+b")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._queue._recover()
        except BaseException:
            lock.close()
            raise
        self._lock = lock
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the pool fence after owned workers have stopped."""
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def run_until_idle(self) -> JobHealth:
        """Execute all presently due work with bounded parallel claims and retries."""
        with self:
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                pending: set[Future[None]] = set()
                while True:
                    while len(pending) < self._max_workers:
                        claimed = self._queue._claim()
                        if claimed is None:
                            break
                        pending.add(executor.submit(self._execute, claimed))
                    if not pending:
                        break
                    completed, pending = wait(pending, timeout=0.1)
                    for future in completed:
                        future.result()
        return self._queue.health()

    def serve(self, stop_event: threading.Event, *, poll_seconds: float = 0.1) -> None:
        """Run scheduled jobs until stopped, awaiting all active handlers before release."""
        if not 0 < poll_seconds <= 60:
            raise ValueError("poll_seconds must be positive and at most 60")
        with self:
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                pending: set[Future[None]] = set()
                while not stop_event.is_set():
                    while len(pending) < self._max_workers:
                        claimed = self._queue._claim()
                        if claimed is None:
                            break
                        pending.add(executor.submit(self._execute, claimed))
                    if not pending:
                        stop_event.wait(timeout=poll_seconds)
                        continue
                    completed, pending = wait(pending, timeout=poll_seconds)
                    for future in completed:
                        future.result()
                for future in pending:
                    future.result()

    def _execute(self, claimed: JobState) -> None:
        """Enforce worker pins, isolate an attempt and record one visible outcome."""
        spec = claimed.spec
        directory = self._queue.root / "work" / spec.job_id / str(claimed.attempts)
        directory.mkdir(parents=True, exist_ok=False)
        run = JobRun(self._queue, spec.job_id, claimed.attempts, directory)
        error = None
        try:
            if spec.implementation_sha256 != self._implementation_sha256:
                raise ValueError("worker implementation identity differs from job pin")
            if spec.environment_sha256 != self._environment_sha256:
                raise ValueError("worker environment identity differs from job pin")
            handler = self._handlers.get(spec.kind)
            if handler is None:
                raise ValueError("no handler for selected job kind")
            if run.cancel_requested():
                self._queue._finish(spec.job_id, claimed.attempts, None, "cancel_requested")
                return
            result = handler.execute(spec, run)
            if run.cancel_requested():
                self._queue._finish(spec.job_id, claimed.attempts, None, "cancel_requested")
                return
            digest = self._queue._publish_result(
                spec.job_id, claimed.attempts, directory, result, self._max_output_bytes
            )
            self._queue._finish(spec.job_id, claimed.attempts, digest, None)
            return
        except Exception as failure:
            # The handler exception may contain a credential; retain only its class.
            error = f"handler_failed:{type(failure).__name__}"
            if (self._queue.root / "results" / spec.job_id).is_dir():
                # A crash or write error after rename must never invoke the
                # handler again. Verify and adopt the already published bytes.
                result = self._queue._verify_result(spec.job_id, None)
                sync_directory(self._queue.root / "results")
                self._queue._finish(
                    spec.job_id, claimed.attempts, hashlib.sha256(result).hexdigest(), None
                )
                return
        self._queue._finish(spec.job_id, claimed.attempts, None, error)
