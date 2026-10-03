"""Exercise the local account owner socket, retention and process fencing."""

from __future__ import annotations

# standard library imports
import os
import socket
import stat
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace
from test_paper_activation import TestPaperActivation as _ActivationFixture

# project library imports
from applications.execute import AccountExecutionApplication
from applications.execute.account_service import AccountOwnerService
from configuration import AccountConfiguration
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountObservation,
    SocketPaperAccount,
)
from serialization import DomainCodec

# A short existing root keeps AF_UNIX paths in limits on macOS and Linux.
_SOCKET_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"


class _ServiceHealth(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Decode the exact independent liveness record emitted by the child."""

    pid: int
    owner_id: str
    generation: int
    release_identity: str
    heartbeat_at: str
    heartbeat_ns: int
    request_progress_ns: int
    status: str


class _RecordingAccountApplication:
    """Record service telemetry binding without performing account mutations."""

    def __init__(self) -> None:
        """Retain exact validated requests and diagnostic destination choices."""
        self.requests: list[tuple[AccountExecutionRequest, Path | None]] = []

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        request_path: Path | None = None,
        telemetry_path: Path | None = None,
        release_identity: str | None = None,
        opened_journal: AccountJournal | None = None,
        phases: dict[str, int] | None = None,
    ) -> AccountExecutionResult:
        """Read the retained typed request and expose the selected telemetry path."""
        assert request_path is not None and opened_journal is not None
        request = DomainCodec().decode_json(request_path.read_bytes(), AccountExecutionRequest)
        self.requests.append((request, telemetry_path))
        return AccountExecutionResult(accounts=(), orders=())


class TestAccountOwnerService:
    """Verify one process owns a retained journal and serves typed account commands."""

    @pytest.mark.parametrize("action", ("inspect", "block"))
    def test_only_inspection_suppresses_redundant_operation_telemetry(
        self, tmp_path: Path, action: str
    ) -> None:
        """Reads keep exact request retention; mutations retain their configured telemetry."""
        journal_path = tmp_path / "account.sqlite3"
        owner = _ActivationFixture._bootstrap(journal_path)[-1]
        config = _ActivationFixture._config()
        application = _RecordingAccountApplication()
        telemetry_path = tmp_path / "telemetry.sqlite3"
        service = AccountOwnerService(
            application=application,
            config=config,
            config_path=tmp_path / "config.json",
            journal_path=journal_path,
            telemetry_path=telemetry_path,
            release_identity=owner.release_identity,
            paper_owner=owner,
            socket_path=tmp_path / "account.sock",
            duration_seconds=10,
        )
        service._owner_journal = AccountJournal(journal_path, config, paper_owner=owner)
        request = (
            AccountExecutionRequest(action="inspect", paper_owner=owner)
            if action == "inspect"
            else AccountExecutionRequest(
                action="block",
                account_id=owner.account_id,
                reason="explicit protection",
                paper_owner=owner,
            )
        )
        codec = DomainCodec()
        payload = codec.encode_json(request)
        server, client = socket.socketpair()
        with server, client:
            client.sendall(struct.pack("!I", len(payload)) + payload)
            response = service._serve_connection(server)
            assert response is not None
        assert application.requests == [(request, None if action == "inspect" else telemetry_path)]
        retained = tuple(service.requests_path.glob("*.json"))
        assert len(retained) == 1 and retained[0].read_bytes() == payload

    @pytest.mark.parametrize("opted_in", (True, False))
    def test_request_timings_are_opt_in_and_ordered(self, tmp_path: Path, opted_in: bool) -> None:
        """An operator-created timings file receives one ordered row per request."""
        journal_path = tmp_path / "account.sqlite3"
        owner = _ActivationFixture._bootstrap(journal_path)[-1]
        config = _ActivationFixture._config()
        codec = DomainCodec()
        config_path = tmp_path / "config.json"
        config_path.write_bytes(codec.encode_json(config))
        service = AccountOwnerService(
            application=AccountExecutionApplication(),
            config=config,
            config_path=config_path,
            journal_path=journal_path,
            telemetry_path=tmp_path / "telemetry.sqlite3",
            release_identity=owner.release_identity,
            paper_owner=owner,
            socket_path=tmp_path / "account.sock",
            duration_seconds=10,
        )
        if opted_in:
            service.timings_path.touch()
        service._enable_timings()
        service._owner_journal = AccountJournal(journal_path, config, paper_owner=owner)
        payload = codec.encode_json(
            AccountExecutionRequest(
                action="block",
                account_id=owner.account_id,
                reason="explicit protection",
                paper_owner=owner,
            )
        )
        server, client = socket.socketpair()
        with server, client:
            client.sendall(struct.pack("!I", len(payload)) + payload)
            assert service._serve_connection(server) is not None
        if not opted_in:
            assert not service.timings_path.exists()
            return
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in service.timings_path.read_bytes().splitlines()
        ]
        assert len(rows) == 1 and rows[0]["action"] == "block"
        order = (
            "header_ns",
            "retained_ns",
            "owner_checked_ns",
            "journal_ns",
            "alerts_ns",
            "snapshot_ns",
            "monitoring_ns",
            "telemetry_ns",
            "sent_ns",
        )
        clocks = [rows[0][name] for name in order]
        assert all(type(clock) is int for clock in clocks)
        assert clocks == sorted(cast(list[int], clocks))

    @pytest.mark.parametrize("mismatch", ("path", "owner"))
    def test_opened_journal_cannot_override_request_binding(
        self, tmp_path: Path, mismatch: str
    ) -> None:
        """Reusing a store handle cannot substitute another path or owner generation."""
        journal_path = tmp_path / "account.sqlite3"
        _, _, _, _, _, owner = _ActivationFixture._bootstrap(journal_path)
        config = _ActivationFixture._config()
        codec = DomainCodec()
        config_path, request_path = tmp_path / "config.json", tmp_path / "inspect.json"
        config_path.write_bytes(codec.encode_json(config))
        request_path.write_bytes(
            codec.encode_json(AccountExecutionRequest(action="inspect", paper_owner=owner))
        )
        opened = AccountJournal(
            tmp_path / "other.sqlite3" if mismatch == "path" else journal_path,
            config,
            paper_owner=replace(owner, generation=owner.generation + 1)
            if mismatch == "owner"
            else owner,
        )
        with pytest.raises(ValueError, match="opened account journal differs"):
            AccountExecutionApplication().run(
                config_path=config_path,
                journal_path=journal_path,
                request_path=request_path,
                release_identity=owner.release_identity,
                opened_journal=opened,
            )

    @staticmethod
    def _wait_ready(process: subprocess.Popen[bytes], socket_path: Path) -> _ServiceHealth:
        """Wait for the actual child PID and ready socket within a finite test budget."""
        health_path = socket_path.with_suffix(".health.json")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate()
                raise AssertionError(f"paper account service exited: {stderr.decode()}")
            if socket_path.exists() and health_path.exists():
                health = msgspec.json.decode(health_path.read_bytes(), type=_ServiceHealth)
                if health.pid == process.pid:
                    return health
            time.sleep(0.02)
        raise AssertionError("paper account service did not become ready")

    def test_socket_owner_fence_and_graceful_shutdown(self, tmp_path: Path) -> None:
        """A live owner serves inspection, rejects peers, and stops durably."""

        class _CurrentActivationFixture(_ActivationFixture):
            """Keep the signed test grant current for selective restart."""

            opening_at = datetime.now(UTC) - timedelta(seconds=13)

        journal_path = tmp_path / "account.sqlite3"
        _, _, _, _, _, owner = _CurrentActivationFixture._bootstrap(journal_path)
        config: AccountConfiguration = _CurrentActivationFixture._config()
        codec = DomainCodec()
        config_path = tmp_path / "config.json"
        config_path.write_bytes(codec.encode_json(config))
        socket_directory = TemporaryDirectory(prefix="paper-account-", dir=_SOCKET_ROOT)
        socket_path = Path(socket_directory.name) / "s.sock"
        serve_path = tmp_path / "serve.json"
        serve_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="serve_paper",
                    service_socket=str(socket_path),
                    service_seconds=10,
                    paper_owner=owner,
                )
            )
        )
        process: subprocess.Popen[bytes] = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from applications.execute import main; main()",
                "account",
                "--config",
                str(config_path),
                "--journal",
                str(journal_path),
                "--request",
                str(serve_path),
                "--release-identity",
                owner.release_identity,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            first_health = self._wait_ready(process, socket_path)
            assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
            assert first_health.generation == owner.generation
            account = SocketPaperAccount(
                config=config,
                socket_path=socket_path,
                requests=tmp_path / "client-requests",
                paper_owner=owner,
            )
            assert account.accounts()[0].ledger.account_id == owner.account_id
            assert account.paper_market_seen(owner.account_id, "unseen-service-market") is False
            stopped_instance = account.execute(
                AccountExecutionRequest(
                    action="stop_instance",
                    instance_id="alpha",
                    at=datetime.now(UTC),
                    paper_owner=owner,
                )
            )
            assert "alpha" in stopped_instance.stopped_instances
            assert account.reconcile(
                AccountObservation(
                    identity="service-selective-restart-reconcile",
                    at=datetime.now(UTC),
                    snapshot=_CurrentActivationFixture._opening(),
                    open_orders=(),
                )
            )
            restarted_instance = account.execute(
                AccountExecutionRequest(
                    action="restart_instance",
                    instance_id="alpha",
                    at=datetime.now(UTC),
                    paper_owner=owner,
                )
            )
            assert "alpha" not in restarted_instance.stopped_instances
            with pytest.raises(ValueError, match="already owns"):
                AccountExecutionApplication().run(
                    config_path=config_path,
                    journal_path=journal_path,
                    request_path=serve_path,
                    release_identity=owner.release_identity,
                )
            peer = SocketPaperAccount(
                config=config,
                socket_path=socket_path,
                requests=tmp_path / "peer-requests",
                paper_owner=replace(owner, owner_id="replaced-owner"),
            )
            with pytest.raises(RuntimeError, match="paper_owner_stale_or_absent"):
                peer.block(owner.account_id, "peer-must-not-stop-owner")
            with pytest.raises(RuntimeError, match="paper_owner_stale_or_absent"):
                peer.paper_market_seen(owner.account_id, "unseen-service-market")
            assert account.accounts()[0].operator_block is None
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stalled:
                stalled.connect(str(socket_path))
                stalled.sendall(struct.pack("!I", 100) + b"{")
                time.sleep(0.15)
                before_stall = msgspec.json.decode(
                    socket_path.with_suffix(".health.json").read_bytes(), type=_ServiceHealth
                )
                time.sleep(0.25)
                second_health = msgspec.json.decode(
                    socket_path.with_suffix(".health.json").read_bytes(), type=_ServiceHealth
                )
            assert second_health.heartbeat_ns > before_stall.heartbeat_ns
            assert second_health.request_progress_ns == before_stall.request_progress_ns
            stopped = account.shutdown(
                AccountControl(
                    identity="operator-stop-service",
                    account_id=owner.account_id,
                    kind="stop",
                    at=datetime.now(UTC),
                    reason="bounded service complete",
                )
            )
            assert stopped.control is not None and stopped.control.status == "applied"
            stdout, stderr = process.communicate(timeout=8)
            assert process.wait(timeout=0) == 0, stderr.decode()
            assert codec.decode_json(stdout.strip(), AccountExecutionResult).accounts[0].phase == (
                "stopped"
            )
            assert not socket_path.exists()
            assert not socket_path.with_suffix(".health.json").exists()
            retained = tuple((tmp_path / "service-requests").glob("*.json"))
            decoded = tuple(
                codec.decode_json(path.read_bytes(), AccountExecutionRequest) for path in retained
            )
            assert {"stop_instance", "restart_instance"}.issubset(
                {request.action for request in decoded if request.paper_owner == owner}
            )
            assert any(request.action == "shutdown_paper" for request in decoded)
            assert any(request.action == "control" for request in decoded)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
            else:
                process.communicate()
            socket_directory.cleanup()

    def test_service_request_bounds_and_socket_only_shutdown(self, tmp_path: Path) -> None:
        """Startup rejects unbounded lifetimes; CLI cannot execute socket shutdown."""
        owner = _ActivationFixture._bootstrap(tmp_path / "account.sqlite3")[-1]
        with pytest.raises(ValueError, match="bounded lifetime"):
            AccountExecutionRequest(
                action="serve_paper",
                service_socket=str(tmp_path / "s.sock"),
                service_seconds=121,
                paper_owner=owner,
            )
        config_path = tmp_path / "config.json"
        codec = DomainCodec()
        config_path.write_bytes(codec.encode_json(_ActivationFixture._config()))
        stop_path = tmp_path / "stop.json"
        stop_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="shutdown_paper",
                    paper_owner=owner,
                    control=AccountControl(
                        identity="invalid-direct-shutdown",
                        account_id=owner.account_id,
                        kind="stop",
                        at=datetime.now(UTC),
                        reason="socket only",
                    ),
                )
            )
        )
        with pytest.raises(ValueError, match="active socket"):
            AccountExecutionApplication().run(
                config_path=config_path,
                journal_path=tmp_path / "account.sqlite3",
                request_path=stop_path,
                release_identity=owner.release_identity,
            )
        assert (tmp_path / "account.sqlite3").is_file()

    def test_heartbeat_write_failure_stops_durable_account(self, tmp_path: Path) -> None:
        """A lost liveness record ends service after a fenced account stop."""
        journal_path = tmp_path / "account.sqlite3"
        _, _, _, _, _, owner = _ActivationFixture._bootstrap(journal_path)
        config = _ActivationFixture._config()
        before = AccountJournal(journal_path, config)
        original_activation = before.paper_activations()[0]
        original_orders, original_net_orders = before.orders(), before.net_orders()
        config_path = tmp_path / "config.json"
        codec = DomainCodec()
        config_path.write_bytes(codec.encode_json(config))
        socket_directory = TemporaryDirectory(prefix="paper-account-", dir=_SOCKET_ROOT)
        socket_path = Path(socket_directory.name) / "s.sock"
        serve_path = tmp_path / "serve.json"
        serve_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="serve_paper",
                    service_socket=str(socket_path),
                    service_seconds=10,
                    paper_owner=owner,
                )
            )
        )
        process: subprocess.Popen[bytes] = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from applications.execute import main; main()",
                "account",
                "--config",
                str(config_path),
                "--journal",
                str(journal_path),
                "--request",
                str(serve_path),
                "--release-identity",
                owner.release_identity,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self._wait_ready(process, socket_path)
            health_path = socket_path.with_suffix(".health.json")
            for _ in range(10):
                health_path.unlink(missing_ok=True)
                try:
                    health_path.mkdir()
                except FileExistsError:
                    continue
                break
            assert health_path.is_dir()
            _, stderr = process.communicate(timeout=8)
            assert process.wait(timeout=0) != 0, stderr.decode()
            reopened = AccountJournal(journal_path, config)
            assert reopened.accounts()[0].phase == "stopped"
            assert reopened.paper_activations()[0] == original_activation
            assert reopened.orders() == original_orders
            assert reopened.net_orders() == original_net_orders
            assert any(
                item.request.kind == "stop"
                and item.request.reason == "service_lifetime_complete"
                and item.status == "applied"
                for item in reopened.controls()
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
            else:
                process.communicate()
            socket_directory.cleanup()
