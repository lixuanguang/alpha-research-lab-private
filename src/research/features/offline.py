"""Admit a bounded, causal Feast offline feature view through a worker boundary.

The core research runtime deliberately does not import Feast.  Feast 0.66 is
kept in a separately locked worker because its pandas requirement cannot share
the repository's pandas 3 runtime.  This module owns the versioned request and
result records, eligibility checks, and parity comparison; a worker only
executes the SDK call and returns the records described here.
"""

from __future__ import annotations

# standard library imports
import hashlib
import os
import re
import select
import subprocess  # nosec B404  # [owner=research; rationale=explicit isolated Feast interpreter argv boundary; expires=2026-12-01]
import tempfile
import threading
import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Literal, Protocol

# third party library imports
from msgspec.structs import replace

# project library imports
from serialization import DomainCodec, WireRecord

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_RATIO = re.compile(r"-?(?:0|[1-9][0-9]*)/[1-9][0-9]*\Z")
_MAX_ROWS = 4_096
_MAX_WIRE_BYTES = 16 * 1024 * 1024


class FeatureAccessError(ValueError):
    """Report a feature-store result that cannot prove causal eligibility."""


class FeatureEntity(WireRecord, frozen=True, kw_only=True):
    """Retain an explicit Feast entity type and join key."""

    schema_version: Literal["feature-entity"] = "feature-entity"
    entity_type: str
    entity_key: str

    def __post_init__(self) -> None:
        """Reject ambiguous entity names or keys before they cross the worker boundary."""
        if self.schema_version != "feature-entity":
            raise ValueError("unsupported feature entity schema")
        OfflineFeatureDefinition._text(self.entity_type, "entity_type")
        OfflineFeatureDefinition._text(self.entity_key, "entity_key")


class OfflineFeatureDefinition(WireRecord, frozen=True, kw_only=True):
    """Pin one Feast feature view, its bytes, source snapshot and causal policy.

    ``eligibility`` deliberately has one supported value.  Feast's ordinary
    event-time join does not establish knowledge/revision eligibility, so the
    source presented to this view must already be immutable and filtered for
    each decision.  The local worker also requests Feast's created-time filter
    and requires a registered availability clock; a worker that cannot prove
    those clocks fails closed.
    """

    schema_version: Literal["offline-feature-definition"] = "offline-feature-definition"
    feature_name: str
    feature_ref: str
    entity_type: str
    units: str
    ttl_us: int
    sdk_version: str
    definition_version: str
    definition_bytes: bytes
    registry_bytes: bytes
    source_version: str
    source_sha256: str
    eligibility: Literal["immutable-source"] = "immutable-source"
    join_key: str | None = None
    repository_path: str | None = None

    @staticmethod
    def _text(value: object, field_name: str) -> str:
        """Require one nonempty, trimmed feature-manifest text field."""
        if type(value) is not str or not value or value != value.strip():
            raise ValueError(f"{field_name} must be a nonempty trimmed string")
        return value

    @classmethod
    def _digest(cls, value: object, field_name: str) -> str:
        """Require one lowercase SHA-256 digest in feature metadata."""
        result = cls._text(value, field_name)
        if _HEX.fullmatch(result) is None:
            raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        return result

    @classmethod
    def _ratio(cls, value: object, field_name: str) -> str:
        """Require canonical rational text without converting it to a float."""
        if type(value) is not str or _RATIO.fullmatch(value) is None:
            raise ValueError(f"{field_name} must be a canonical numerator/denominator string")
        numerator, denominator = value.split("/", 1)
        if int(numerator) == 0 and (numerator != "0" or denominator != "1"):
            raise ValueError(f"{field_name} must use canonical zero")
        if int(denominator) <= 0 or str(abs(int(numerator))) != numerator.lstrip("-"):
            raise ValueError(f"{field_name} must use canonical integer components")
        left, right = abs(int(numerator)), int(denominator)
        while right:
            left, right = right, left % right
        if left != 1 and int(numerator) != 0:
            raise ValueError(f"{field_name} must be reduced")
        return value

    @staticmethod
    def _digest_bytes(value: bytes) -> str:
        """Return the stable digest for retained definition or registry bytes."""
        return hashlib.sha256(value).hexdigest()

    def __post_init__(self) -> None:
        """Validate the immutable feature-view manifest and its bounded TTL."""
        if self.schema_version != "offline-feature-definition":
            raise ValueError("unsupported offline feature definition schema")
        for value, name in (
            (self.feature_name, "feature_name"),
            (self.feature_ref, "feature_ref"),
            (self.entity_type, "entity_type"),
            (self.units, "units"),
            (self.sdk_version, "sdk_version"),
            (self.definition_version, "definition_version"),
            (self.source_version, "source_version"),
        ):
            self._text(value, name)
        if type(self.ttl_us) is not int or not 0 < self.ttl_us <= 31_536_000_000_000:
            raise ValueError("ttl_us must be a positive bounded duration")
        if type(self.definition_bytes) is not bytes or not self.definition_bytes:
            raise ValueError("definition_bytes must be nonempty retained bytes")
        if type(self.registry_bytes) is not bytes or not self.registry_bytes:
            raise ValueError("registry_bytes must be nonempty retained bytes")
        self._digest(self.source_sha256, "source_sha256")
        if self.eligibility != "immutable-source":
            raise ValueError("only eligibility-filtered immutable sources are supported")
        if self.join_key is not None:
            self._text(self.join_key, "join_key")
        if self.repository_path is not None:
            self._text(self.repository_path, "repository_path")

    @property
    def definition_sha256(self) -> str:
        """Return the digest of the exact feature definition bytes.

        Returns:
            Lowercase SHA-256 for ``definition_bytes``.
        """
        return self._digest_bytes(self.definition_bytes)

    @property
    def registry_sha256(self) -> str:
        """Return the digest of the exact registry bytes.

        Returns:
            Lowercase SHA-256 for ``registry_bytes``.
        """
        return self._digest_bytes(self.registry_bytes)

    @property
    def identity(self) -> str:
        """Hash all semantic definition and source bindings, including retained bytes.

        Returns:
            Lowercase SHA-256 identity for this immutable definition.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class FeatureObservation(WireRecord, frozen=True, kw_only=True):
    """Carry one exact nullable feature value and all clocks needed for admission."""

    schema_version: Literal["feature-observation"] = "feature-observation"
    definition_identity: str
    source_version: str
    source_sha256: str
    feature_name: str
    entity_type: str
    entity_key: str
    decision_at: datetime
    event_at: datetime | None
    available_at: datetime | None
    ttl_us: int
    units: str
    value: str | None
    revision_identity: str | None = None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        """Reject future clocks, malformed identity metadata and approximate values."""
        if self.schema_version != "feature-observation":
            raise ValueError("unsupported feature observation schema")
        OfflineFeatureDefinition._digest(self.definition_identity, "definition_identity")
        OfflineFeatureDefinition._text(self.source_version, "source_version")
        OfflineFeatureDefinition._digest(self.source_sha256, "source_sha256")
        OfflineFeatureDefinition._text(self.feature_name, "feature_name")
        OfflineFeatureDefinition._text(self.entity_type, "entity_type")
        OfflineFeatureDefinition._text(self.entity_key, "entity_key")
        self._require_utc(self.decision_at, field_name="decision_at")
        if type(self.ttl_us) is not int or not 0 < self.ttl_us <= 31_536_000_000_000:
            raise ValueError("ttl_us must be a positive bounded duration")
        OfflineFeatureDefinition._text(self.units, "units")
        if self.revision_identity is not None:
            OfflineFeatureDefinition._digest(self.revision_identity, "revision_identity")
        if self.missing_reason is not None:
            OfflineFeatureDefinition._text(self.missing_reason, "missing_reason")
        if self.event_at is None:
            if self.available_at is not None:
                raise ValueError("available_at requires event_at")
            if self.value is not None:
                raise ValueError("a value requires event_at")
        else:
            self._require_utc(self.event_at, field_name="event_at")
            if self.event_at > self.decision_at:
                raise ValueError("event_at cannot be after decision_at")
            if self.available_at is not None:
                self._require_utc(self.available_at, field_name="available_at")
                if self.available_at < self.event_at:
                    raise ValueError("available_at cannot precede event_at")
        if self.value is not None:
            OfflineFeatureDefinition._ratio(self.value, "value")

    @property
    def row_identity(self) -> str:
        """Return the stable key used to align worker and causal reference rows.

        Returns:
            Lowercase SHA-256 identity for the feature/entity/decision cell.
        """
        encoded = DomainCodec().encode_json(
            (self.feature_name, self.entity_type, self.entity_key, self.decision_at)
        )
        return hashlib.sha256(encoded).hexdigest()

    @property
    def expired(self) -> bool:
        """Report whether the observation's event timestamp has exceeded its TTL.

        Returns:
            ``True`` when the decision is later than the declared event TTL.
        """
        return self.event_at is not None and (
            self.decision_at - self.event_at > timedelta(microseconds=self.ttl_us)
        )


class OfflineFeatureRequest(WireRecord, frozen=True, kw_only=True):
    """Describe a bounded entity/decision grid for one offline retrieval."""

    schema_version: Literal["offline-feature-request"] = "offline-feature-request"
    definition: OfflineFeatureDefinition
    entities: tuple[FeatureEntity, ...]
    decisions: tuple[datetime, ...]
    request_identity: str | None = None
    definition_identity: str | None = None

    def __post_init__(self) -> None:
        """Require a small unique grid and retain UTC decision clocks verbatim."""
        if self.schema_version != "offline-feature-request":
            raise ValueError("unsupported offline feature request schema")
        if type(self.definition) is not OfflineFeatureDefinition:
            raise TypeError("request requires OfflineFeatureDefinition")
        self.definition.__post_init__()
        if type(self.entities) is not tuple or not self.entities:
            raise ValueError("offline feature request requires entities")
        if type(self.decisions) is not tuple or not self.decisions:
            raise ValueError("offline feature request requires decisions")
        if len(self.entities) * len(self.decisions) > _MAX_ROWS:
            raise ValueError("offline feature request exceeds the bounded entity/decision grid")
        seen_entities: set[tuple[str, str]] = set()
        for entity in self.entities:
            if type(entity) is not FeatureEntity:
                raise TypeError("request entities must be FeatureEntity records")
            entity.__post_init__()
            key = (entity.entity_type, entity.entity_key)
            if key in seen_entities:
                raise ValueError("request entities must be unique")
            seen_entities.add(key)
            if entity.entity_type != self.definition.entity_type:
                raise ValueError("request entity type differs from feature definition")
        previous: datetime | None = None
        for decision in self.decisions:
            self._require_utc(decision, field_name="decision")
            if previous is not None and decision <= previous:
                raise ValueError("request decisions must be strictly increasing")
            previous = decision
        if self.request_identity is not None:
            OfflineFeatureDefinition._digest(self.request_identity, "request_identity")
        if self.definition_identity is not None:
            OfflineFeatureDefinition._digest(self.definition_identity, "definition_identity")

    @property
    def identity(self) -> str:
        """Hash the semantic request while excluding the optional cached identity.

        Returns:
            Lowercase SHA-256 identity for the requested feature grid.
        """
        self.__post_init__()
        payload = (self.schema_version, self.definition.identity, self.entities, self.decisions)
        return hashlib.sha256(DomainCodec().encode_json(payload)).hexdigest()

    @property
    def expected_rows(self) -> int:
        """Return the number of entity/decision cells that must be represented.

        Returns:
            Number of cells in the bounded entity/decision grid.
        """
        return len(self.entities) * len(self.decisions)


class OfflineFeatureResult(WireRecord, frozen=True, kw_only=True):
    """Retain the worker's typed rows and the SDK/source bindings it actually used."""

    schema_version: Literal["offline-feature-result"] = "offline-feature-result"
    request_identity: str
    definition_identity: str
    registry_sha256: str
    sdk_version: str
    source_version: str
    source_sha256: str
    eligibility: Literal["immutable-source"] = "immutable-source"
    rows: tuple[FeatureObservation, ...] = ()

    def __post_init__(self) -> None:
        """Validate result metadata and keep result rows bounded and uniquely keyed."""
        if self.schema_version != "offline-feature-result":
            raise ValueError("unsupported offline feature result schema")
        OfflineFeatureDefinition._digest(self.request_identity, "request_identity")
        OfflineFeatureDefinition._digest(self.definition_identity, "definition_identity")
        OfflineFeatureDefinition._digest(self.registry_sha256, "registry_sha256")
        OfflineFeatureDefinition._text(self.sdk_version, "sdk_version")
        OfflineFeatureDefinition._text(self.source_version, "source_version")
        OfflineFeatureDefinition._digest(self.source_sha256, "source_sha256")
        if self.eligibility != "immutable-source":
            raise ValueError("result must state immutable-source eligibility")
        if type(self.rows) is not tuple or len(self.rows) > _MAX_ROWS:
            raise ValueError("offline feature result exceeds the bounded row limit")
        seen: set[str] = set()
        for row in self.rows:
            if type(row) is not FeatureObservation:
                raise TypeError("result rows must be FeatureObservation records")
            row.__post_init__()
            if row.row_identity in seen:
                raise ValueError("offline feature result contains duplicate entity/decision rows")
            seen.add(row.row_identity)


class FeastWorker(Protocol):
    """Describe a worker callable that consumes and returns versioned JSON bytes."""

    def __call__(self, request: bytes) -> bytes:
        """Execute one isolated Feast request."""
        ...


class FeastOfflineWorker:
    """Run an explicitly selected Feast worker executable without shell expansion."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 60.0,
        max_output_bytes: int = _MAX_WIRE_BYTES,
        cwd: Path | None = None,
    ) -> None:
        """Bind a complete worker command and bounded process I/O.

        Args:
            command: Executable and arguments for the separately locked worker.
            timeout_seconds: Maximum time for one local SDK retrieval.
            max_output_bytes: Maximum versioned result size accepted from stdout.
            cwd: Optional worker working directory; no ambient shell is used.

        Raises:
            TypeError: The working directory is not a ``Path``.
            ValueError: A command, timeout or output budget is invalid.
        """
        if not command or any(type(item) is not str or not item for item in command):
            raise ValueError("worker command must contain a nonempty executable and arguments")
        if not Path(command[0]).is_absolute():
            raise ValueError("worker executable must be an explicit absolute path")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 600:
            raise ValueError("worker timeout must be a positive bounded number of seconds")
        if type(max_output_bytes) is not int or not 0 < max_output_bytes <= _MAX_WIRE_BYTES:
            raise ValueError("worker output budget is invalid")
        if cwd is not None and not isinstance(cwd, Path):
            raise TypeError("worker cwd must be a Path")
        self.command = tuple(command)
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = max_output_bytes
        self.cwd = cwd

    def __call__(self, request: bytes) -> bytes:
        """Execute one request and fail closed on timeout, stderr or malformed output."""
        if type(request) is not bytes or not request or len(request) > _MAX_WIRE_BYTES:
            raise FeatureAccessError("worker request exceeds the bounded JSON budget")
        try:
            completed = subprocess.run(  # nosec B603  # [owner=research; rationale=caller-selected absolute worker executable with shell disabled; expires=2026-12-01]
                self.command,
                input=request,
                capture_output=True,
                cwd=self.cwd,
                check=False,
                shell=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise FeatureAccessError("Feast worker could not complete the request") from error
        if completed.returncode != 0:
            detail = completed.stderr[:2_048].decode("utf-8", errors="replace")
            raise FeatureAccessError(
                f"Feast worker failed with exit {completed.returncode}: {detail}"
            )
        if len(completed.stdout) == 0 or len(completed.stdout) > self.max_output_bytes:
            raise FeatureAccessError("Feast worker returned an empty or oversized result")
        return completed.stdout


class FeastWorkerSession:
    """Keep one Feast worker process answering newline-delimited requests across calls.

    The worker program answers one response line per request line until its input
    ends, so a session pays the worker's interpreter and SDK start once rather than
    per request. Requests are serialized. A worker that ends, exceeds the timeout,
    answers out of protocol or fails a request is stopped, the request raises
    ``FeatureAccessError`` carrying the worker's stderr, and the next request starts
    a fresh worker.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 60.0,
        max_output_bytes: int = _MAX_WIRE_BYTES,
        cwd: Path | None = None,
    ) -> None:
        """Bind the worker command and the per-request bounds of ``FeastOfflineWorker``.

        Raises:
            TypeError: The working directory is not a ``Path``.
            ValueError: A command, timeout or output budget is invalid.
        """
        launch = FeastOfflineWorker(
            command, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes, cwd=cwd
        )
        self._command, self._timeout = launch.command, launch.timeout_seconds
        self._max_output, self._cwd = launch.max_output_bytes, launch.cwd
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr: IO[bytes] | None = None
        # The worker's request and response pipe ends held by this process.
        self._input = self._output = -1

    def __call__(self, request: bytes) -> bytes:
        """Answer one request through the running worker, starting it when needed."""
        if (
            type(request) is not bytes
            or not request
            or len(request) > _MAX_WIRE_BYTES
            or b"\n" in request
        ):
            raise FeatureAccessError("worker request exceeds the bounded JSON budget")
        with self._lock:
            if self._process is None:
                self._start()
            deadline = time.monotonic() + self._timeout
            try:
                self._send(request + b"\n", deadline)
                return self._response(deadline)
            except (OSError, TimeoutError, FeatureAccessError) as error:
                detail = self._stop()
                raise FeatureAccessError(
                    f"Feast worker session failed: {error}; {detail}".rstrip("; ")
                ) from error

    def start(self) -> None:
        """Start the worker ahead of its first request, if none is running.

        A service calls this as it starts, so the worker's interpreter and SDK load
        while nothing waits on them.
        """
        with self._lock:
            if self._process is None:
                self._start()

    def close(self) -> None:
        """Stop the worker, if one is running."""
        with self._lock:
            self._stop()

    def _start(self) -> None:
        """Start one worker on private pipes, its stderr retained for a failure."""
        self._stderr = tempfile.TemporaryFile()
        request_read, self._input = os.pipe()
        self._output, response_write = os.pipe()
        try:
            self._process = subprocess.Popen(  # nosec B603  # [owner=research; rationale=caller-selected absolute worker executable with shell disabled; expires=2026-12-01]
                self._command,
                stdin=request_read,
                stdout=response_write,
                stderr=self._stderr,
                cwd=self._cwd,
                shell=False,
            )
        except OSError as error:
            self._stop()
            raise FeatureAccessError("Feast worker could not start") from error
        finally:
            os.close(request_read)
            os.close(response_write)

    def _wait(self, descriptor: int, event: int, deadline: float) -> None:
        """Wait until the descriptor is ready for ``event`` or the deadline passes."""
        poller = select.poll()
        poller.register(descriptor, event | select.POLLHUP | select.POLLERR)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Feast worker exceeded its request timeout")
            if poller.poll(max(1, int(remaining * 1000))):
                return

    def _send(self, payload: bytes, deadline: float) -> None:
        """Write the whole request line before the deadline."""
        view = memoryview(payload)
        while view:
            self._wait(self._input, select.POLLOUT, deadline)
            view = view[os.write(self._input, view) :]

    def _response(self, deadline: float) -> bytes:
        """Read exactly one bounded response line before the deadline."""
        buffer = bytearray()
        while not buffer.endswith(b"\n"):
            self._wait(self._output, select.POLLIN, deadline)
            block = os.read(self._output, 65_536)
            if not block:
                raise FeatureAccessError("Feast worker ended before answering")
            buffer.extend(block)
            if len(buffer) > self._max_output + 1:
                raise FeatureAccessError("Feast worker returned an oversized result")
        response = bytes(buffer[:-1])
        if not response or b"\n" in response:
            raise FeatureAccessError("Feast worker answered outside its line protocol")
        return response

    def _stop(self) -> str:
        """Kill and reap any worker, close its pipes and return the tail of its stderr."""
        process, stderr = self._process, self._stderr
        self._process = self._stderr = None
        for descriptor in (self._input, self._output):
            if descriptor >= 0:
                os.close(descriptor)
        self._input = self._output = -1
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
        if stderr is None:
            return ""
        with stderr:
            stderr.seek(0)
            return stderr.read()[-2_048:].decode("utf-8", errors="replace").strip()


class OfflineFeatureBridge:
    """Decode an isolated worker result before exposing it to the causal adapter."""

    def __init__(self, worker: FeastWorker, *, max_bytes: int = _MAX_WIRE_BYTES) -> None:
        """Bind one explicit worker callable and a result byte ceiling.

        Args:
            worker: Callable for the separately locked Feast worker process.
            max_bytes: Maximum result size accepted at this boundary.

        Raises:
            ValueError: The result byte ceiling is outside the bounded contract.
        """
        self._worker = worker
        if type(max_bytes) is not int or not 0 < max_bytes <= _MAX_WIRE_BYTES:
            raise ValueError("offline bridge byte budget is invalid")
        self._max_bytes = max_bytes

    def retrieve(self, request: OfflineFeatureRequest) -> OfflineFeatureResult:
        """Send a strict request and decode only the declared result schema.

        Args:
            request: Validated immutable feature definition and bounded grid.

        Returns:
            Worker result after request, source and registry identity checks.

        Raises:
            FeatureAccessError: Worker bytes are unavailable, malformed, or carry a
                mismatched request/definition/source binding.
        """
        request.__post_init__()
        # The worker is intentionally independent of the core package and
        # cannot recompute DomainCodec's canonical identity.  Include the
        # already verified identity in the wire request while leaving the
        # semantic request identity unchanged.
        wire_request = replace(
            request,
            request_identity=request.identity,
            definition_identity=request.definition.identity,
        )
        payload = DomainCodec().encode_json(wire_request)
        try:
            raw = self._worker(payload)
        except FeatureAccessError:
            raise
        except Exception as error:
            raise FeatureAccessError("offline feature worker raised an unexpected error") from error
        if type(raw) is not bytes or not raw or len(raw) > self._max_bytes:
            raise FeatureAccessError("offline feature worker returned invalid bytes")
        try:
            result = DomainCodec().decode_json(raw, OfflineFeatureResult)
        except (TypeError, ValueError) as error:
            raise FeatureAccessError(
                "offline feature worker returned invalid result JSON"
            ) from error
        if result.request_identity != request.identity:
            raise FeatureAccessError("offline feature result request identity differs")
        if result.definition_identity != request.definition.identity:
            raise FeatureAccessError("offline feature result definition identity differs")
        if result.registry_sha256 != request.definition.registry_sha256:
            raise FeatureAccessError("offline feature result registry bytes differ")
        if result.sdk_version != request.definition.sdk_version:
            raise FeatureAccessError("offline feature worker SDK version differs")
        if result.source_version != request.definition.source_version:
            raise FeatureAccessError("offline feature result source version differs")
        if result.source_sha256 != request.definition.source_sha256:
            raise FeatureAccessError("offline feature result source bytes differ")
        if result.eligibility != request.definition.eligibility:
            raise FeatureAccessError("offline feature result eligibility differs")
        return result


class OfflineFeatureAccess:
    """Admit worker values at decision time and compare them with causal reference rows."""

    def __init__(self, bridge: OfflineFeatureBridge) -> None:
        """Bind the isolated Feast bridge; no online store or fallback is created.

        Args:
            bridge: Versioned worker bridge used for offline retrieval.
        """
        self._bridge = bridge

    def retrieve(self, request: OfflineFeatureRequest) -> OfflineFeatureResult:
        """Retrieve and causally admit a complete entity/decision grid.

        Args:
            request: Validated feature definition and bounded retrieval grid.

        Returns:
            Result containing every requested cell, including explicit nulls.

        Raises:
            FeatureAccessError: A worker row cannot prove identity, availability or TTL.

        Missing entities remain explicit nullable rows.  A non-null value that is
        unavailable at its decision or has exceeded its TTL is rejected, because
        turning it into a null would hide a worker correctness failure.
        """
        result = self._bridge.retrieve(request)
        rows = {row.row_identity: row for row in result.rows}
        admitted: list[FeatureObservation] = []
        for entity in request.entities:
            for decision in request.decisions:
                identity = self._row_identity(
                    request.definition.feature_name, entity.entity_type, entity.entity_key, decision
                )
                row = rows.pop(identity, None)
                if row is None:
                    row = FeatureObservation(
                        definition_identity=request.definition.identity,
                        source_version=request.definition.source_version,
                        source_sha256=request.definition.source_sha256,
                        feature_name=request.definition.feature_name,
                        entity_type=entity.entity_type,
                        entity_key=entity.entity_key,
                        decision_at=decision,
                        event_at=None,
                        available_at=None,
                        ttl_us=request.definition.ttl_us,
                        units=request.definition.units,
                        value=None,
                        missing_reason="missing entity or no eligible source row",
                    )
                self._admit_row(row, request.definition, decision)
                admitted.append(row)
        if rows:
            raise FeatureAccessError(
                "offline feature worker returned an unexpected entity/decision"
            )
        return OfflineFeatureResult(
            request_identity=request.identity,
            definition_identity=request.definition.identity,
            registry_sha256=request.definition.registry_sha256,
            sdk_version=request.definition.sdk_version,
            source_version=request.definition.source_version,
            source_sha256=request.definition.source_sha256,
            rows=tuple(admitted),
        )

    def compare(
        self,
        request: OfflineFeatureRequest,
        reference: Sequence[FeatureObservation],
    ) -> OfflineFeatureComparison:
        """Compare admitted Feast values with a retained causal reference by exact text.

        Args:
            request: Feature definition and bounded retrieval grid.
            reference: Complete causal reference grid with retained clocks and values.

        Returns:
            Exact parity rows, including null/null matches.

        Raises:
            FeatureAccessError: The reference is incomplete or has different bindings.
        """
        retrieved = self.retrieve(request)
        return self.compare_result(request, retrieved, reference)

    def compare_result(
        self,
        request: OfflineFeatureRequest,
        retrieved: OfflineFeatureResult,
        reference: Sequence[FeatureObservation],
    ) -> OfflineFeatureComparison:
        """Compare one already admitted result without issuing another worker request.

        Args:
            request: Feature definition and bounded retrieval grid.
            retrieved: Result previously returned by :meth:`retrieve` for this request.
            reference: Complete causal reference grid with retained clocks and values.

        Returns:
            Exact parity rows, including null/null matches.

        Raises:
            FeatureAccessError: The result or reference has different bindings.
        """
        request.__post_init__()
        retrieved.__post_init__()
        if (
            retrieved.request_identity != request.identity
            or retrieved.definition_identity != request.definition.identity
            or retrieved.registry_sha256 != request.definition.registry_sha256
            or retrieved.sdk_version != request.definition.sdk_version
            or retrieved.source_version != request.definition.source_version
            or retrieved.source_sha256 != request.definition.source_sha256
            or retrieved.eligibility != request.definition.eligibility
        ):
            raise FeatureAccessError("retrieved feature result identity differs")
        if len(retrieved.rows) != request.expected_rows:
            raise FeatureAccessError("offline feature result does not cover the request grid")
        for row in retrieved.rows:
            self._admit_row(row, request.definition, row.decision_at)
        expected = self._reference_grid(request, reference)
        comparisons: list[FeatureParity] = []
        for row in retrieved.rows:
            reference_row = expected.get(row.row_identity)
            if reference_row is None:
                raise FeatureAccessError("causal reference omits an expected entity/decision")
            if row.value == reference_row.value:
                status: Literal["match", "mismatch"] = "match"
                reason = None
            else:
                status = "mismatch"
                reason = "exact feature value differs from causal reference"
            comparisons.append(
                FeatureParity(
                    row_identity=row.row_identity,
                    feature_name=row.feature_name,
                    entity_type=row.entity_type,
                    entity_key=row.entity_key,
                    decision_at=row.decision_at,
                    reference_value=reference_row.value,
                    retrieved_value=row.value,
                    status=status,
                    reason=reason,
                )
            )
        return OfflineFeatureComparison(
            request_identity=request.identity,
            definition_identity=request.definition.identity,
            rows=tuple(comparisons),
        )

    @staticmethod
    def _row_identity(
        feature_name: str, entity_type: str, entity_key: str, decision_at: datetime
    ) -> str:
        """Construct the same identity used by FeatureObservation without a dummy record."""
        encoded = DomainCodec().encode_json((feature_name, entity_type, entity_key, decision_at))
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _reference_grid(
        cls, request: OfflineFeatureRequest, reference: Sequence[FeatureObservation]
    ) -> dict[str, FeatureObservation]:
        """Validate and index a causal reference grid without mutating caller state."""
        if len(reference) != request.expected_rows:
            raise FeatureAccessError("causal reference does not contain the complete grid")
        indexed: dict[str, FeatureObservation] = {}
        for row in reference:
            if type(row) is not FeatureObservation:
                raise TypeError("causal reference rows must be FeatureObservation records")
            row.__post_init__()
            if row.definition_identity != request.definition.identity:
                raise FeatureAccessError("causal reference definition identity differs")
            if row.source_version != request.definition.source_version:
                raise FeatureAccessError("causal reference source version differs")
            if row.source_sha256 != request.definition.source_sha256:
                raise FeatureAccessError("causal reference source bytes differ")
            if row.ttl_us != request.definition.ttl_us or row.units != request.definition.units:
                raise FeatureAccessError("causal reference units or TTL differs")
            if row.row_identity in indexed:
                raise FeatureAccessError("causal reference contains duplicate rows")
            indexed[row.row_identity] = row
        return indexed

    @classmethod
    def _admit_row(
        cls, row: FeatureObservation, definition: OfflineFeatureDefinition, decision: datetime
    ) -> None:
        """Check one returned row's identity, clocks, availability and TTL."""
        if (
            row.definition_identity != definition.identity
            or row.source_version != definition.source_version
            or row.source_sha256 != definition.source_sha256
            or row.feature_name != definition.feature_name
            or row.entity_type != definition.entity_type
            or row.ttl_us != definition.ttl_us
            or row.units != definition.units
            or row.decision_at != decision
        ):
            raise FeatureAccessError("offline feature row metadata differs from the request")
        if row.value is None:
            if row.available_at is not None and row.available_at > decision:
                raise FeatureAccessError("null feature row has a future availability timestamp")
            return
        if row.event_at is None or row.available_at is None:
            raise FeatureAccessError("non-null feature row lacks event or availability timestamp")
        if row.available_at > decision:
            raise FeatureAccessError("feature value was unavailable at its decision")
        if row.expired:
            raise FeatureAccessError("feature value exceeded its declared TTL")


class FeatureParity(WireRecord, frozen=True, kw_only=True):
    """Retain one exact Feast/reference comparison, including missingness."""

    schema_version: Literal["feature-parity"] = "feature-parity"
    row_identity: str
    feature_name: str
    entity_type: str
    entity_key: str
    decision_at: datetime
    reference_value: str | None
    retrieved_value: str | None
    status: Literal["match", "mismatch"]
    reason: str | None

    def __post_init__(self) -> None:
        """Validate comparison identity, UTC clock and exact nullable values."""
        if self.schema_version != "feature-parity":
            raise ValueError("unsupported feature parity schema")
        OfflineFeatureDefinition._digest(self.row_identity, "row_identity")
        OfflineFeatureDefinition._text(self.feature_name, "feature_name")
        OfflineFeatureDefinition._text(self.entity_type, "entity_type")
        OfflineFeatureDefinition._text(self.entity_key, "entity_key")
        self._require_utc(self.decision_at, field_name="decision_at")
        for value, name in (
            (self.reference_value, "reference_value"),
            (self.retrieved_value, "retrieved_value"),
        ):
            if value is not None:
                OfflineFeatureDefinition._ratio(value, name)
        if self.status not in ("match", "mismatch"):
            raise ValueError("unsupported feature parity status")
        if (self.status == "match") != (self.reference_value == self.retrieved_value):
            raise ValueError("feature parity status differs from exact values")
        if self.reason is not None:
            OfflineFeatureDefinition._text(self.reason, "reason")


class OfflineFeatureComparison(WireRecord, frozen=True, kw_only=True):
    """Retain all bounded parity rows and their immutable request/definition identities."""

    schema_version: Literal["offline-feature-comparison"] = "offline-feature-comparison"
    request_identity: str
    definition_identity: str
    rows: tuple[FeatureParity, ...]

    def __post_init__(self) -> None:
        """Require one nonempty, bounded comparison with stable row identities."""
        if self.schema_version != "offline-feature-comparison":
            raise ValueError("unsupported offline feature comparison schema")
        OfflineFeatureDefinition._digest(self.request_identity, "request_identity")
        OfflineFeatureDefinition._digest(self.definition_identity, "definition_identity")
        if type(self.rows) is not tuple or not 0 < len(self.rows) <= _MAX_ROWS:
            raise ValueError("feature comparison requires a bounded nonempty row set")
        seen: set[str] = set()
        for row in self.rows:
            if type(row) is not FeatureParity:
                raise TypeError("comparison rows must be FeatureParity records")
            row.__post_init__()
            if row.row_identity in seen:
                raise ValueError("comparison rows must be unique")
            seen.add(row.row_identity)

    @property
    def mismatches(self) -> tuple[FeatureParity, ...]:
        """Return exact mismatches without discarding matching evidence.

        Returns:
            Parity rows whose retained values differ.
        """
        return tuple(row for row in self.rows if row.status == "mismatch")

    @property
    def matches(self) -> tuple[FeatureParity, ...]:
        """Return exact matches, including explicit null/null rows.

        Returns:
            Parity rows whose retained values are exactly equal.
        """
        return tuple(row for row in self.rows if row.status == "match")
