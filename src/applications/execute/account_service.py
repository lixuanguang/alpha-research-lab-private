"""Host one bounded installed account owner behind a local serial command socket."""

from __future__ import annotations

# standard library imports
import errno
import fcntl
import json
import os
import signal
import socket
import stat
import struct
import threading
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import BinaryIO, Protocol
from uuid import uuid4

# project library imports
from configuration import AccountConfiguration
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    PaperOwner,
)
from serialization import DomainCodec, DurableLines


class _AccountApplication(Protocol):
    """Apply retained requests under the signed target's fixed account binding."""

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        request_path: Path | None = None,
        request_payload: bytes | None = None,
        telemetry_path: Path | None = None,
        release_identity: str | None = None,
        opened_journal: AccountJournal | None = None,
        phases: dict[str, int] | None = None,
    ) -> AccountExecutionResult:
        """Return a typed account result for one retained command."""
        ...


class AccountOwnerService:
    """Serialize local requests under one installed owner, journal and release.

    The service retains every request before application: one fsynced line of its
    exact bytes in ``service-requests/<life>.jsonl``, one append-only log per service
    life, applied only after that line is durable. A response lost after a commit is
    an uncertain outcome for the client and is never retried here.
    The service life is bounded by the signed configuration's cap (120 seconds when
    undeclared), and a life under a current grant must end by the grant's expiry; the
    service never renews it. The signed launcher adds an independent outer bound of
    that cap plus 60 seconds.
    """

    _maximum_bytes = 1_048_576
    _served_actions = frozenset(
        {
            "inspect",
            "admit",
            "event",
            "post",
            "reconcile",
            "block",
            "quote",
            "coordinate",
            "net_event",
            "stop_instance",
            "restart_instance",
            "reissue_pending",
            "net_cost",
            "control",
            "bind_paper_scenario",
            "paper_market",
            "reduce_paper",
            "shutdown_paper",
        }
    )

    def __init__(
        self,
        *,
        application: _AccountApplication,
        config: AccountConfiguration,
        config_path: Path,
        journal_path: Path,
        telemetry_path: Path | None,
        release_identity: str,
        paper_owner: PaperOwner,
        socket_path: Path,
        duration_seconds: int,
    ) -> None:
        """Bind immutable installed authority and a finite local service lifetime."""
        if (
            any(not path.is_absolute() for path in (config_path, journal_path, socket_path))
            or (telemetry_path is not None and not telemetry_path.is_absolute())
            or type(duration_seconds) is not int
            or not 1 <= duration_seconds <= config.service_life_limit
            or paper_owner.release_identity != release_identity
            or len(config.accounts) != 1
            or config.accounts[0].account_id != paper_owner.account_id
        ):
            raise ValueError("paper service differs from its fixed installed account")
        self.application = application
        self.config = config
        self.config_path, self.journal_path = config_path, journal_path
        self.telemetry_path, self.release_identity = telemetry_path, release_identity
        self.paper_owner, self.socket_path = paper_owner, socket_path
        self.duration_seconds = duration_seconds
        self.health_path = socket_path.with_suffix(".health.json")
        # Opt-in request timings: written only if the operator created this file first.
        self.timings_path = socket_path.with_suffix(".request-timings.jsonl")
        self._timings: Path | None = None
        self.requests_path = journal_path.parent / "service-requests"
        self._requests = DurableLines(self.requests_path / f"{uuid4().hex}.jsonl")
        self._codec = DomainCodec()
        self._stopping = threading.Event()
        self._heartbeat_failed = threading.Event()
        self._shutdown_applied = False
        self._request_progress_ns = time.monotonic_ns()
        self._owner_journal: AccountJournal | None = None

    def serve(self) -> AccountExecutionResult:
        """Hold one stable journal lock, serve serially, and stop on normal exit."""
        with ExitStack() as stack:
            stack.enter_context(self._claim_lock())
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                self.socket_path.with_suffix(".endpoint.lock"),
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
            )
            endpoint_fence = stack.enter_context(os.fdopen(descriptor, "a+b"))
            fcntl.flock(endpoint_fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self._require_current_owner()
            self._enable_timings()
            self._owner_journal = AccountJournal(
                self.journal_path, self.config, paper_owner=self.paper_owner
            )
            with self._listen() as listener:
                previous_handler = signal.signal(signal.SIGTERM, self._request_stop)
                heartbeat = threading.Thread(
                    target=self._write_heartbeats, name="paper-account-heartbeat", daemon=True
                )
                heartbeat.start()
                try:
                    deadline = time.monotonic() + self.duration_seconds
                    listener.settimeout(0.1)
                    while not self._stopping.is_set() and time.monotonic() < deadline:
                        try:
                            connection, _ = listener.accept()
                        except TimeoutError:
                            continue
                        with connection:
                            response = self._serve_connection(connection)
                            if response is not None:
                                result = response
                    if self._heartbeat_failed.is_set():
                        raise OSError("paper service heartbeat persistence failed")
                finally:
                    try:
                        if not self._shutdown_applied:
                            result = self._stop_account("service_lifetime_complete")
                    finally:
                        self._stopping.set()
                        heartbeat.join(timeout=1)
                        signal.signal(signal.SIGTERM, previous_handler)
                        self._remove_owned_socket()
            return result

    def _claim_lock(self) -> BinaryIO:
        """Fence duplicate services even if they choose different socket names."""
        lock_path = self.journal_path.with_name(self.journal_path.name + ".service.lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        lock = os.fdopen(descriptor, "a+b")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            lock.close()
            raise ValueError("paper account service already owns this journal") from error
        return lock

    def _listen(self) -> socket.socket:
        """Bind a private stream socket, removing a stale socket only under lock."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = self.socket_path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISSOCK(existing.st_mode):
                raise ValueError("paper service socket path is not a socket")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                try:
                    probe.connect(str(self.socket_path))
                except OSError as error:
                    if error.errno not in (errno.ECONNREFUSED, errno.ENOENT):
                        raise ValueError(
                            "paper service socket cannot be safely replaced"
                        ) from error
                else:
                    raise ValueError("paper service socket is already active")
            self.socket_path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound = False
        try:
            listener.bind(str(self.socket_path))
            bound = True
            os.chmod(self.socket_path, 0o600)
            listener.listen(8)
        except BaseException:
            listener.close()
            if bound:
                self._remove_owned_socket()
            raise
        return listener

    def _require_current_owner(self) -> AccountExecutionResult:
        """Read durable activation without claiming a generation or changing state."""
        request = AccountExecutionRequest(
            action="inspect", paper_owner=self.paper_owner, projection="paper_activations"
        )
        payload = self._retain_request(self._codec.encode_json(request))
        result = self._apply(payload, telemetry=False)
        activation = next(
            (
                item
                for item in result.paper_activations
                if item.deployment.account_id == self.paper_owner.account_id
            ),
            None,
        )
        if activation is None or activation.owner != self.paper_owner:
            raise ValueError("paper_owner_stale_or_absent")
        grant = activation.authorization
        now = datetime.now(UTC)
        # An expired or revoked grant already blocks new exposure; the service may still
        # settle obligations. A current grant must outlast the whole service life.
        if (
            grant is not None
            and grant.identity not in activation.revoked
            and grant.valid_from <= now < grant.expires_at
            and (grant.expires_at - now).total_seconds() < self.duration_seconds
        ):
            raise ValueError("paper_service_life_exceeds_authorization")
        return result

    def _require_current_owner_fast(self) -> None:
        """Check the durable generation once without composing a second report."""
        if self._owner_journal is None:
            raise ValueError("paper account service has no opened journal")
        activation = next(
            (
                item
                for item in self._owner_journal.paper_activations()
                if item.deployment.account_id == self.paper_owner.account_id
            ),
            None,
        )
        if activation is None or activation.owner != self.paper_owner:
            raise ValueError("paper_owner_stale_or_absent")

    def _serve_connection(self, connection: socket.socket) -> AccountExecutionResult | None:
        """Read one bounded frame, retain it, then send a success or fixed error."""
        phases: dict[str, int] | None = {} if self._timings is not None else None
        action: str | None = None
        try:
            deadline = time.monotonic() + 2
            header = self._read_exact(connection, 4, deadline=deadline)
            if phases is not None:
                phases["header_ns"] = time.monotonic_ns()
            length = int.from_bytes(header, "big")
            if not 0 < length <= self._maximum_bytes:
                raise ValueError("paper service request exceeds one MiB")
            payload = self._read_exact(connection, length, deadline=deadline)
            request = self._codec.decode_json(payload, AccountExecutionRequest)
            request.__post_init__()
            action = request.action
            if request.action not in self._served_actions:
                raise ValueError("paper service action is outside its operating scope")
            if request.paper_owner is not None and request.paper_owner != self.paper_owner:
                raise ValueError("paper_owner_stale_or_absent")
            if request.action != "inspect" and request.paper_owner != self.paper_owner:
                raise ValueError("paper_owner_stale_or_absent")
            if request.account_id is not None and request.account_id != self.paper_owner.account_id:
                raise ValueError("paper service account differs from its owner")
            retained = self._retain_request(payload)
            if phases is not None:
                phases["retained_ns"] = time.monotonic_ns()
            self._require_current_owner_fast()
            if phases is not None:
                phases["owner_checked_ns"] = time.monotonic_ns()
            if request.action == "shutdown_paper":
                if request.control is None:
                    raise ValueError("paper service shutdown lacks stop control")
                response = self._apply_stop(request.control)
                self._shutdown_applied = True
                self._stopping.set()
            else:
                response = self._apply(
                    retained, telemetry=request.action != "inspect", phases=phases
                )
            self._send(connection, b"\x00", self._codec.encode_json(response))
            return response
        except Exception as error:
            reason = f"{type(error).__name__}: {error}".encode("utf-8", errors="replace")[:2048]
            try:
                self._send(connection, b"\x01", reason)
            except OSError:
                pass
            return None
        finally:
            self._request_progress_ns = time.monotonic_ns()
            if phases is not None and self._timings is not None:
                phases["sent_ns"] = self._request_progress_ns
                row: dict[str, object] = {"action": action, **phases}
                with self._timings.open("ab") as stream:
                    stream.write(self._codec.encode_json(row) + b"\n")

    def _enable_timings(self) -> None:
        """Record request timings only when the operator created the timings file."""
        self._timings = self.timings_path if self.timings_path.is_file() else None

    def _apply_stop(self, control: AccountControl) -> AccountExecutionResult:
        """Translate a service shutdown into the ordinary fenced control path."""
        request = AccountExecutionRequest(
            action="control", control=control, paper_owner=self.paper_owner
        )
        result = self._apply(self._retain_request(self._codec.encode_json(request)))
        if result.control is None or result.control.status != "applied":
            raise ValueError("paper service stop control was rejected")
        return result

    def _stop_account(self, reason: str) -> AccountExecutionResult:
        """Stop the account on expiry, termination or a service failure."""
        return self._apply_stop(
            AccountControl(
                identity=f"paper-service-stop:{uuid4().hex}",
                account_id=self.paper_owner.account_id,
                kind="stop",
                at=datetime.now(UTC),
                reason=reason,
            )
        )

    def _apply(
        self,
        payload: bytes,
        *,
        telemetry: bool = True,
        phases: dict[str, int] | None = None,
    ) -> AccountExecutionResult:
        """Use only the signed config, journal, release and fixed telemetry path."""
        return self.application.run(
            config_path=self.config_path,
            journal_path=self.journal_path,
            request_payload=payload,
            telemetry_path=self.telemetry_path if telemetry else None,
            release_identity=self.release_identity,
            opened_journal=self._owner_journal,
            phases=phases,
        )

    def _retain_request(self, payload: bytes) -> bytes:
        """Fsync an exact request line before any account application sees its bytes."""
        if len(payload) > self._maximum_bytes:
            raise ValueError("paper service request exceeds one MiB")
        if b"\n" in payload:
            raise ValueError("paper service request is not one compact JSON line")
        self._requests.append(payload)
        return payload

    def _write_heartbeats(self) -> None:
        """Publish process liveness independently of serial account requests."""
        while not self._stopping.is_set():
            health = {
                "pid": os.getpid(),
                "owner_id": self.paper_owner.owner_id,
                "generation": self.paper_owner.generation,
                "release_identity": self.release_identity,
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "heartbeat_ns": time.monotonic_ns(),
                "request_progress_ns": self._request_progress_ns,
                "status": "ready",
            }
            temporary = self.health_path.with_name(f".{self.health_path.name}.{os.getpid()}.tmp")
            try:
                temporary.write_bytes(json.dumps(health, sort_keys=True).encode("utf-8"))
                temporary.replace(self.health_path)
            except OSError:
                self._heartbeat_failed.set()
                self._stopping.set()
                return
            self._stopping.wait(0.1)

    def _request_stop(self, _signum: int, _frame: FrameType | None) -> None:
        """Defer SIGTERM until the current account request has completed."""
        self._stopping.set()

    def _remove_owned_socket(self) -> None:
        """Remove only this socket and heartbeat while the stable lock is held."""
        try:
            if stat.S_ISSOCK(self.socket_path.lstat().st_mode):
                self.socket_path.unlink()
        except FileNotFoundError:
            pass
        self.health_path.unlink(missing_ok=True)

    @staticmethod
    def _read_exact(connection: socket.socket, count: int, *, deadline: float) -> bytes:
        """Require a complete frame within one total read deadline."""
        pieces: list[bytes] = []
        remaining = count
        while remaining:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise TimeoutError("paper service request read timed out")
            connection.settimeout(remaining_seconds)
            part = connection.recv(remaining)
            if not part:
                raise ConnectionError("paper service request ended before its frame")
            pieces.append(part)
            remaining -= len(part)
        return b"".join(pieces)

    @staticmethod
    def _send(connection: socket.socket, status: bytes, payload: bytes) -> None:
        """Return one typed result or an explicit failure without a retry loop."""
        connection.sendall(status + struct.pack("!I", len(payload)) + payload)
