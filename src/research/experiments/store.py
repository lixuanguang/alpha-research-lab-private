"""Retain local single-writer attempts with atomic, append-only outcomes and holdout access."""

from __future__ import annotations

# standard library imports
import fcntl
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Literal, Self
from uuid import uuid4

# project library imports
from research.experiments.identity import ExperimentSpec
from serialization import DomainCodec, WireRecord


class AttemptStart(WireRecord, frozen=True, kw_only=True):
    """Bind one execution to a semantic specification and retained invocation bytes."""

    schema_version: Literal["experiment-attempt"] = "experiment-attempt"
    attempt_id: str
    run_identity: str
    spec: ExperimentSpec
    started_at: datetime
    invocation: str
    request: bytes

    def __post_init__(self) -> None:
        """Verify the semantic identity instead of trusting saved or copied records."""
        if (
            self.schema_version != "experiment-attempt"
            or type(self.attempt_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", self.attempt_id) is None
        ):
            raise ValueError("invalid attempt identity or schema")
        if type(self.spec) is not ExperimentSpec or self.run_identity != self.spec.identity:
            raise ValueError("attempt semantic identity mismatch")
        self._require_utc(self.started_at, field_name="started_at")
        if type(self.invocation) is not str or not self.invocation.strip():
            raise ValueError("attempt requires its invocation")
        if type(self.request) is not bytes:
            raise TypeError("attempt request must be retained bytes")


class AttemptEvent(WireRecord, frozen=True, kw_only=True):
    """Retain access or a terminal outcome; completed results live in the same atomic record."""

    status: Literal["holdout_consumed", "completed", "failed", "rejected", "abandoned"]
    recorded_at: datetime
    reason: str
    result: bytes | None = None

    def __post_init__(self) -> None:
        """Require a reason and prevent partial or failed output from becoming completion."""
        self._require_utc(self.recorded_at, field_name="recorded_at")
        if self.status not in ("holdout_consumed", "completed", "failed", "rejected", "abandoned"):
            raise ValueError("unknown attempt status")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("attempt event requires a reason")
        if self.status == "completed":
            if type(self.result) is not bytes or not self.result:
                raise ValueError("completion requires retained result bytes")
        elif self.result is not None:
            raise ValueError("only completed attempts may publish results")


class AttemptHistory(WireRecord, frozen=True, kw_only=True):
    """Expose retained starts, consumed holdouts and outcomes, including interrupted attempts."""

    start: AttemptStart
    events: tuple[AttemptEvent, ...]

    def __post_init__(self) -> None:
        """Validate direct construction and the complete append-only state sequence."""
        if type(self.start) is not AttemptStart or type(self.events) is not tuple:
            raise TypeError("history requires an attempt start and immutable events")
        self.start.__post_init__()
        for index, event in enumerate(self.events):
            if type(event) is not AttemptEvent:
                raise TypeError("history requires AttemptEvent records")
            event.__post_init__()
            if index and self.events[index - 1].status != "holdout_consumed":
                raise ValueError("attempt contains events after a terminal outcome")
            if index and event.status == "holdout_consumed":
                raise ValueError("attempt repeats holdout consumption")

    @property
    def status(self) -> str:
        """Report incomplete unless an atomic terminal event exists.

        Returns:
            The terminal status, or incomplete after a start/holdout-only history.
        """
        if self.events and self.events[-1].status != "holdout_consumed":
            return self.events[-1].status
        return "incomplete"


class AttemptStore:
    """Own a local POSIX store with one nonblocking writer and concurrent immutable readers.

    Enter the store for the entire attempt workflow. A process-scoped advisory
    flock is released on exit or process death; a second writer fails explicitly.
    Retain the whole root to preserve family/holdout history. External mutation,
    network filesystems and hostile code are outside this initial boundary.
    """

    def __init__(self, root: Path) -> None:
        """Bind a retained local directory without performing I/O.

        Args:
            root: Attempt history root, outside ordinary version-controlled source.
        """
        self._root = root
        self._codec = DomainCodec()
        self._lock: BinaryIO | None = None
        self._pid: int | None = None

    def __enter__(self) -> Self:
        """Acquire the sole writer before inspecting or mutating family history.

        Returns:
            This writer; read methods do not require the writer lock.

        Raises:
            RuntimeError: This instance already owns a writer session.
            BlockingIOError: Another process or instance holds the store writer lock.
            OSError: The root or lock cannot be opened.
        """
        if self._lock is not None:
            raise RuntimeError("attempt writer is already open")
        self._root.mkdir(parents=True, exist_ok=True)
        lock = (self._root / ".writer.lock").open("a+b")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise
        self._lock, self._pid = lock, os.getpid()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the writer without inventing completion for interrupted work.

        Args:
            exc_type: Propagated exception type, if any.
            exc_value: Propagated exception, if any.
            traceback: Propagated traceback, if any.
        """
        if self._lock is not None:
            self._lock.close()
            self._lock, self._pid = None, None

    def start(
        self,
        spec: ExperimentSpec,
        *,
        at: datetime,
        invocation: str,
        request: bytes = b"",
    ) -> AttemptStart:
        """Atomically retain an execution start before any study consumes input values.

        Args:
            spec: Immutable semantic choices including the frozen family holdout window.
            at: UTC execution time, excluded from semantic identity.
            invocation: Actual command or callable invocation, excluded from identity.
            request: Original configuration bytes, including nonsemantic resource bounds.

        Returns:
            Newly committed unique execution attempt, even when the semantic run repeats.

        Raises:
            ValueError: An existing family declares a different final holdout window.
            RuntimeError: This process has not acquired the writer.
            OSError: The atomic start cannot be committed.
        """
        self._require_writer()
        start = AttemptStart(
            attempt_id=uuid4().hex,
            run_identity=spec.identity,
            spec=spec,
            started_at=at,
            invocation=invocation,
            request=request,
        )
        family_path = self._family_path(spec.family)
        if not family_path.exists():
            self._publish(family_path, self._family_declaration(spec))
        directory = self._root / start.attempt_id
        directory.mkdir()
        self._publish(directory / "start.json", self._codec.encode_json(start))
        self._sync(self._root)
        if family_path.read_bytes() != self._family_declaration(spec):
            self.finish(
                start.attempt_id,
                status="rejected",
                at=at,
                reason="family holdout is frozen; new evidence requires a new family",
            )
            raise ValueError("family holdout is frozen; rejected attempt retained")
        return start

    def consume_holdout(self, attempt_id: str, *, at: datetime, reason: str) -> None:
        """Commit final holdout consumption before exposing its values to a consumer.

        Args:
            attempt_id: Incomplete execution about to access final OOS values.
            at: UTC access-record time; this precedes the actual read.
            reason: Authored evaluation or unchanged-reproduction reason.

        Raises:
            ValueError: The attempt is terminal or another semantic run consumed this family.
            RuntimeError: This process does not own the writer session.
        """
        self._require_writer()
        current = self.read(attempt_id)
        if current.start.spec.split is None:
            raise ValueError("engineering sample has no holdout to consume")
        self._require_frozen_holdout(current.start.spec)
        for history in self.histories():
            if (
                history.start.spec.family == current.start.spec.family
                and history.start.run_identity != current.start.run_identity
                and any(event.status == "holdout_consumed" for event in history.events)
            ):
                raise ValueError("family holdout already consumed by a different semantic run")
        self._append(
            attempt_id, AttemptEvent(status="holdout_consumed", recorded_at=at, reason=reason)
        )

    def finish(
        self,
        attempt_id: str,
        *,
        status: Literal["completed", "failed", "rejected", "abandoned"],
        at: datetime,
        reason: str,
        result: bytes | None = None,
    ) -> AttemptHistory:
        """Atomically retain an immutable terminal outcome and, on success, complete results.

        Args:
            attempt_id: Incomplete execution; prior failures cannot be rewritten as success.
            status: Terminal execution outcome, independent of empirical success or selection.
            at: UTC terminal-record time.
            reason: Completion, failure, rejection or abandonment explanation.
            result: Complete output bytes only for a completed execution.

        Returns:
            Reloaded history including the newly committed terminal event.

        Raises:
            ValueError: The transition or payload is invalid, or a terminal outcome exists.
            RuntimeError: This process does not own the writer session.
            OSError: Publication failed; reload the history to resolve an uncertain outcome.
        """
        if status == "completed":
            self._require_frozen_holdout(self.read(attempt_id).start.spec)
        self._append(
            attempt_id, AttemptEvent(status=status, recorded_at=at, reason=reason, result=result)
        )
        return self.read(attempt_id)

    def read(self, attempt_id: str) -> AttemptHistory:
        """Reload validated immutable records without requiring the writer lock.

        Args:
            attempt_id: A lowercase 32-hex execution identity, never a filesystem path.

        Returns:
            Inspectable history; staging files are not committed events.

        Raises:
            ValueError: Identity, semantic digest, event sequence or state transitions are invalid.
            OSError: A committed record cannot be read.
        """
        if type(attempt_id) is not str or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None:
            raise ValueError("invalid attempt identity")
        directory = self._root / attempt_id
        start = self._codec.decode_json((directory / "start.json").read_bytes(), AttemptStart)
        if start.attempt_id != attempt_id:
            raise ValueError("attempt directory identity mismatch")
        events: list[AttemptEvent] = []
        for index, path in enumerate(sorted(directory.glob("event-*.json")), start=1):
            if path.name != f"event-{index:06d}.json":
                raise ValueError("attempt event sequence is incomplete")
            event = self._codec.decode_json(path.read_bytes(), AttemptEvent)
            events.append(event)
        return AttemptHistory(start=start, events=tuple(events))

    def histories(self) -> tuple[AttemptHistory, ...]:
        """Discover all committed starts, including rejected, failed and interrupted attempts.

        Returns:
            Histories in stable attempt-ID order; a root with no starts is empty.
        """
        return tuple(
            self.read(path.parent.name) for path in sorted(self._root.glob("*/start.json"))
        )

    def retain(self, attempt_id: str, name: str, payload: bytes) -> str:
        """Retain immutable supplemental bytes, including usable rejected model states.

        Args:
            attempt_id: Existing execution, including a terminal execution during publication.
            name: Lowercase artifact name containing only letters, digits and hyphens.
            payload: Complete artifact bytes; identical retries are idempotent.

        Returns:
            SHA-256 of the retained bytes, verified on an identical retry.

        Raises:
            ValueError: Name/payload is invalid or an existing artifact differs.
            RuntimeError: This process does not own the writer.
        """
        self._require_writer()
        self.read(attempt_id)
        path = self._artifact_path(attempt_id, name)
        if type(payload) is not bytes or not payload:
            raise ValueError("artifact requires nonempty bytes")
        digest = hashlib.sha256(payload).hexdigest()
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError("retained artifact cannot be replaced")
        else:
            # Share immutable content within this store; each attempt path links to it.
            content = self._root / "artifacts"
            if not content.exists():
                content.mkdir()
                self._sync(self._root)
            canonical = content / digest
            if canonical.exists():
                if canonical.read_bytes() != payload:
                    raise ValueError("retained artifact content digest mismatch")
            else:
                self._publish(canonical, payload)
            canonical.chmod(canonical.stat().st_mode & ~0o222)
            os.link(canonical, path)
            self._sync(path.parent)
        return digest

    def artifact(self, attempt_id: str, name: str) -> bytes:
        """Read supplemental bytes without changing execution or holdout history.

        Args:
            attempt_id: Existing execution identity.
            name: Retained artifact name.

        Returns:
            Original bytes; the consuming manifest verifies their digest and schema.
        """
        self.read(attempt_id)
        return self._artifact_path(attempt_id, name).read_bytes()

    def export(self, attempt_id: str, name: str, destination: Path) -> None:
        """Expose retained immutable bytes under another name on the same filesystem.

        Args:
            attempt_id: Existing execution owning the retained artifact.
            name: Retained artifact name.
            destination: Export path whose parent already exists on the store's filesystem.

        Raises:
            ValueError: An existing export contains different bytes.
            RuntimeError: This process does not own the writer context.
            OSError: The artifact is missing or a durable hard link cannot be created.
        """
        self._require_writer()
        self.read(attempt_id)
        source = self._artifact_path(attempt_id, name)
        if destination.exists():
            if destination.read_bytes() != source.read_bytes():
                raise ValueError("existing export differs; select a new output path")
            return
        # Exports share immutable storage; editing requires a separate working copy.
        source.chmod(source.stat().st_mode & ~0o222)
        os.link(source, destination)
        self._sync(destination.parent)

    def artifacts(self, attempt_id: str) -> tuple[str, ...]:
        """List committed supplemental artifacts, excluding incomplete staging files.

        Args:
            attempt_id: Existing execution identity.

        Returns:
            Sorted artifact names.
        """
        self.read(attempt_id)
        return tuple(
            path.name.removeprefix("artifact-").removesuffix(".bin")
            for path in sorted((self._root / attempt_id).glob("artifact-*.bin"))
        )

    def _artifact_path(self, attempt_id: str, name: str) -> Path:
        """Keep supplemental records within the already validated attempt directory."""
        if type(name) is not str or re.fullmatch(r"[a-z][a-z0-9-]{0,127}", name) is None:
            raise ValueError("invalid retained artifact name")
        return self._root / attempt_id / f"artifact-{name}.bin"

    def _family_path(self, family: str) -> Path:
        """Use a path-independent digest for the immutable final holdout declaration."""
        return self._root / f"family-{hashlib.sha256(family.encode()).hexdigest()}.json"

    def _require_frozen_holdout(self, spec: ExperimentSpec) -> None:
        """Refuse interrupted rejected starts and fail closed on missing family metadata."""
        frozen = self._family_path(spec.family).read_bytes()
        if frozen != self._family_declaration(spec):
            raise ValueError("family holdout is frozen")

    def _family_declaration(self, spec: ExperimentSpec) -> bytes:
        """Freeze a disjoint design kind; an engineering family cannot evade a holdout."""
        spec.__post_init__()
        return self._codec.encode_json(
            spec.split.holdout
            if spec.split is not None
            else ("unfitted-engineering-sample", spec.engineering_sample)
        )

    def _require_writer(self) -> None:
        """Refuse mutations from readers, closed contexts or inherited fork handles."""
        if self._lock is None or self._pid != os.getpid():
            raise RuntimeError("attempt mutation requires the owning process writer context")

    def _append(self, attempt_id: str, event: AttemptEvent) -> None:
        """Recheck persisted state and append exactly one atomic access or terminal event."""
        self._require_writer()
        history = self.read(attempt_id)
        if history.status != "incomplete":
            raise ValueError("terminal attempt cannot be changed; start a new attempt")
        if event.status == "holdout_consumed" and history.events:
            raise ValueError("holdout access already recorded for this attempt")
        self._publish(
            self._root / attempt_id / f"event-{len(history.events) + 1:06d}.json",
            self._codec.encode_json(event),
        )

    @staticmethod
    def _sync(directory: Path) -> None:
        """Persist local directory entries after an atomic rename."""
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _publish(cls, path: Path, payload: bytes) -> None:
        """Flush bytes before atomic visibility; preserve staging evidence after interruption."""
        temporary = path.with_name(f".pending-{uuid4().hex}")
        with temporary.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            raise FileExistsError("attempt records are append-only")
        os.replace(temporary, path)
        cls._sync(path.parent)
