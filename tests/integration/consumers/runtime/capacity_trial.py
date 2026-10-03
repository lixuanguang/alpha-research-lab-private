"""Run finite signed paper capacity trials and retain failures and cleanup.

Copy this consumer with capacity_inputs, capacity_reads and paper_services outside
the checkout. Use an installed research interpreter and separately verified signed
account targets. Every invocation gets a fresh evidence directory.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import BinaryIO, Literal
from uuid import uuid4

# third party library imports
import msgspec
from capacity_inputs import CapacityVariant, CapacityWorkload
from capacity_reads import CapacityReadObserver
from capacity_recovery import CapacityRecovery

# project library imports
from accounting import AccountLedger
from applications.execute.services import (
    PaperServiceControl,
    PaperServiceOwners,
    run_paper_services,
)
from configuration import PaperAuthorization, PaperDeployment, PaperServiceConfiguration
from execution import (
    AccountControl,
    AccountExecutionRequest,
    InstalledPaperAccount,
    PaperOwner,
    SocketPaperAccount,
)
from runtime import InstalledIdentity
from serialization import DomainCodec


class _Health(msgspec.Struct, frozen=True):
    """Read the signed service process identity without weakening account responses."""

    pid: int
    generation: int
    heartbeat_ns: int = 0
    owner_id: str | None = None
    release_identity: str | None = None


class _Child(msgspec.Struct, frozen=True):
    """Read an observed child process identity from supervisor status."""

    pid: int | None
    alive: bool


class _AccountPhase(msgspec.Struct, frozen=True):
    """Retain the actual account-phase read and its observation clock."""

    observed_at: datetime
    status: str
    phase: str | None = None


class _Status(msgspec.Struct, frozen=True):
    """Read only operating signals needed by the diagnostic driver."""

    active: tuple[str, ...]
    workers: dict[str, _Child]
    sources: dict[str, _Child]
    faulted_accounts: tuple[str, ...]
    stopping: bool
    diagnostics: _Child | None = None
    observed_at: datetime | None = None
    configuration: str | None = None
    run_id: str | None = None
    pid: int | None = None
    owners: tuple[PaperOwner, ...] = ()
    account_phases: dict[str, _AccountPhase] | None = None


class AlertReceiver:
    """Retain actual local diagnostic receipt without acknowledging economic work."""

    def __init__(self, path: Path, output: Path) -> None:
        """Bind a fresh finite trial's datagram endpoint."""
        self.path, self.output = path, output
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket.bind(str(path))
        self.socket.settimeout(0.1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._receive)
        self.thread.start()

    def _receive(self) -> None:
        """Retain each datagram with its actual local receipt clock."""
        with self.output.open("ab") as stream:
            while not self.stop.is_set():
                try:
                    payload = self.socket.recv(8192)
                except TimeoutError:
                    continue
                stream.write(
                    DomainCodec().encode_json(
                        {"received_ns": time.monotonic_ns(), "payload": payload.decode()}
                    )
                    + b"\n"
                )
                stream.flush()

    def close(self) -> None:
        """Stop receipt and remove only this driver's endpoint."""
        self.stop.set()
        self.thread.join(2)
        self.socket.close()
        self.path.unlink(missing_ok=True)


class CapacityTrial:
    """Own signed startup, a measured finite interval and unconditional shutdown."""

    def __init__(
        self,
        root: Path,
        output: Path,
        launcher: Path,
        *,
        public_venue: Literal["okx", "bitfinex"] | None = None,
        variant: CapacityVariant = "base",
        recover: bool = False,
        faults: bool = False,
        features: bool = False,
    ) -> None:
        """Bind predeclared configuration and exact signed installation paths."""
        self.root, self.output, self.launcher = root, output, launcher
        self.public_venue, self.variant = public_venue, variant
        self.recover, self.faults = recover, faults
        self.features = features
        self.codec = DomainCodec()
        self.config = self.codec.decode_json(
            (root / "preparation/services-initial.json").read_bytes(), PaperServiceConfiguration
        )
        self.socket_root = Path(self.config.accounts[0].socket_path).parent
        self.control_socket = self.socket_root / "supervisor.sock"
        self.workload = CapacityWorkload(
            opening_at=self.config.accounts[0].configuration.opening_at,
            socket_root=self.socket_root,
            public_venue=public_venue,
        )
        self.policy = root / "release-policy.json"
        self.service_root = output / "operating"
        self.processes: list[subprocess.Popen[bytes]] = []
        self.streams: list[BinaryIO] = []
        self.watchers: list[threading.Thread] = []
        self.owners: dict[str, PaperOwner] = {}
        self.clients: dict[str, SocketPaperAccount] = {}
        self.account_pids: dict[str, int] = {}
        self.child_pids: set[int] = set()
        self.failures: list[str] = []
        self.replacement_checkpoints: dict[str, bytes] = {}
        self.supervisor: subprocess.Popen[bytes] | None = None
        self.supervisor_started_at: float | None = None
        self.receiver: AlertReceiver | None = None
        self.first_service_at: float | None = None
        self.shutdown_requested = False
        self._health_stop = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._health_run_id: str | None = None
        self._health_last_ns: int | None = None
        self._health_configuration: str | None = None

    def record(self, kind: str, values: object) -> None:
        """Flush an attributable driver observation before the next operation."""
        row = {
            "kind": kind,
            "at": datetime.now(UTC),
            "monotonic": time.monotonic(),
            "values": values,
        }
        with (self.output / "observations.jsonl").open("ab") as stream:
            stream.write(self.codec.encode_json(row) + b"\n")
            stream.flush()

    def admin(self, account_id: str) -> InstalledPaperAccount:
        """Select the exact fixed installed account configuration and retained target."""
        definition = next(item for item in self.config.accounts if item.account_id == account_id)
        return InstalledPaperAccount(
            config=definition.configuration,
            launcher=self.launcher,
            target=self.root / f"target-{account_id}",
            policy=self.policy,
            requests=self.output / "admin" / account_id,
        )

    @staticmethod
    def wait_until(condition: Callable[[], bool], seconds: float) -> None:
        """Wait for one actual condition with an explicit monotonic deadline."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        raise TimeoutError("bounded capacity condition did not become true")

    def bootstrap(self) -> None:
        """Install declared paper authority and claim all owners before service lifetime starts."""
        for definition in self.config.accounts:
            name = definition.account_id
            admin = self.admin(name)
            state = admin.execute(AccountExecutionRequest(action="inspect"))
            if state.paper_activations:
                raise ValueError(
                    "fresh capacity trial requires unused targets or explicit recovery"
                )
            deployment = self.codec.decode_json(
                (self.root / f"preparation/deployment-{name}.json").read_bytes(), PaperDeployment
            )
            authorization = self.codec.decode_json(
                (self.root / f"preparation/authorization-{name}.json").read_bytes(),
                PaperAuthorization,
            )
            self.owners[name] = self.workload.install_and_claim(
                definition,
                deployment,
                authorization,
                launcher=self.launcher,
                target=admin.target,
                policy=self.policy,
                requests=admin.requests,
            )
        self.record("claimed_owners", self.owners)

    def _spawn(self, name: str, args: list[str]) -> subprocess.Popen[bytes]:
        """Retain stdout/stderr for one finite owned child, including failed starts."""
        out = (self.output / f"{name}.stdout").open("wb")
        err = (self.output / f"{name}.stderr").open("wb")
        self.streams.extend((out, err))
        started = time.monotonic()
        if name == "supervisor":
            self.supervisor_started_at = started
        child = subprocess.Popen(args, stdout=out, stderr=err)
        self.processes.append(child)
        watcher = threading.Thread(target=self._watch_lifetime, args=(name, child, started))
        self.watchers.append(watcher)
        watcher.start()
        return child

    def _watch_lifetime(self, name: str, child: subprocess.Popen[bytes], started: float) -> None:
        """Measure actual process exit independently of later sequential cleanup checks."""
        code = child.wait()
        elapsed = time.monotonic() - started
        bound = 75 if name == "supervisor" else 120
        self.record(
            "process_lifetime",
            {
                "name": name,
                "pid": child.pid,
                "seconds": elapsed,
                "bound_seconds": bound,
                "exit": code,
                "within_bound": elapsed <= bound,
            },
        )
        if elapsed > bound:
            self.failures.append(f"{name} lifetime exceeds {bound} seconds")

    def _account_ready(self) -> bool:
        """Require current generations from every launched signed account owner."""
        for definition in self.config.accounts:
            path = Path(definition.socket_path).with_suffix(".health.json")
            if not path.is_file():
                return False
            health = msgspec.json.decode(path.read_bytes(), type=_Health)
            if health.generation != self.owners[definition.account_id].generation:
                return False
            self.account_pids[definition.account_id] = health.pid
        return True

    def launch(self) -> None:
        """Start four finite signed services together and measure real startup skew."""
        self.socket_root.mkdir(parents=True, exist_ok=True)
        self.receiver = AlertReceiver(
            self.socket_root / "alerts.sock", self.output / "alerts.jsonl"
        )
        selected = msgspec.structs.replace(
            self.config, alert_socket=str(self.socket_root / "alerts.sock")
        )
        self._health_configuration = selected.identity
        (self.output / "configuration.json").write_bytes(self.codec.encode_json(selected))
        (self.output / "owners.json").write_bytes(
            self.codec.encode_json(PaperServiceOwners(owners=tuple(self.owners.values())))
        )
        self.first_service_at = time.monotonic()
        for definition in self.config.accounts:
            name = definition.account_id
            request = AccountExecutionRequest(
                action="serve_paper",
                paper_owner=self.owners[name],
                service_socket=definition.socket_path,
                service_seconds=120,
            )
            path = self.output / f"serve-{name}.json"
            path.write_bytes(self.codec.encode_json(request))
            self._spawn(
                name,
                [
                    str(self.launcher),
                    "run",
                    "--target",
                    str(self.root / f"target-{name}"),
                    "--policy",
                    str(self.policy),
                    "--",
                    "account",
                    "--request",
                    str(path),
                ],
            )
            self.clients[name] = SocketPaperAccount(
                config=definition.configuration,
                socket_path=Path(definition.socket_path),
                requests=self.output / "client" / name,
                paper_owner=self.owners[name],
                timeout_seconds=2,
            )
        self.wait_until(self._account_ready, 18)
        args = [
            sys.executable,
            str(Path(__file__).resolve()),
            "child",
            "--root",
            str(self.root),
            "--output",
            str(self.output),
            "--launcher",
            str(self.launcher),
            "--variant",
            self.variant,
        ]
        if self.public_venue is not None:
            args.extend(("--public-venue", self.public_venue))
        if self.recover:
            args.append("--recover")
        self.supervisor = self._spawn("supervisor", args)
        skew = time.monotonic() - self.first_service_at
        self.record(
            "startup",
            {"first_service_to_supervisor_seconds": skew, "account_pids": self.account_pids},
        )
        if skew > 20:
            self.failures.append("supervisor startup exceeds 20 seconds")
        self.wait_until(self._steady_ready, 12)

    def status(self) -> _Status:
        """Read retained status without imposing a synchronous control round trip."""
        result = msgspec.json.decode((self.service_root / "status.json").read_bytes(), type=_Status)
        for child in (*result.workers.values(), *result.sources.values()):
            if child.pid is not None:
                self.child_pids.add(child.pid)
        if result.diagnostics is not None and result.diagnostics.pid is not None:
            self.child_pids.add(result.diagnostics.pid)
        return result

    def _steady_ready(self) -> bool:
        """Separate startup until every policy has actually committed a checkpoint."""
        if self.supervisor is None or self.supervisor.poll() is not None:
            raise RuntimeError("capacity supervisor exited during startup")
        if not (self.service_root / "status.json").exists():
            return False
        status = self.status()
        if not self._healthy_status(status):
            return False
        return all(
            self.clients[item.account_id].checkpoint(item.instance_id) is not None
            for item in self.config.instances
        )

    def _healthy_status(self, status: _Status) -> bool:
        """Require every declared source and policy alive under unfaulted owners."""
        return (
            not status.stopping
            and not status.faulted_accounts
            and set(status.active) == {item.instance_id for item in self.config.instances}
            and set(status.sources) == {item.name for item in self.config.sources}
            and set(status.workers) == {item.instance_id for item in self.config.instances}
            and all(
                child.pid is not None and child.alive
                for child in (*status.sources.values(), *status.workers.values())
            )
        )

    def control(
        self, action: Literal["inspect", "shutdown", "restart_source"], subject: str | None = None
    ) -> None:
        """Send one explicit control once; never retry an uncertain economic request."""
        if action == "shutdown":
            if self.shutdown_requested:
                return
            self.shutdown_requested = True
        request = PaperServiceControl(action=action, identity=uuid4().hex, subject=subject)
        path = self.output / f"control-{request.identity}.json"
        path.write_bytes(self.codec.encode_json(request))
        result = subprocess.run(
            [
                str(Path(sys.executable).parent / "alpha-execute"),
                "deployment-control",
                "--socket",
                str(self.control_socket),
                "--request",
                str(path),
            ],
            capture_output=True,
            timeout=8,
        )
        path.with_suffix(".stdout").write_bytes(result.stdout)
        path.with_suffix(".stderr").write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(f"control failed: {path}")

    def retain_accounts(self, label: str, *, sockets: bool) -> None:
        """Retain complete current facts and per-instance checkpoint identities."""
        for definition in self.config.accounts:
            name = definition.account_id
            client = self.clients[name] if sockets else self.admin(name)
            state = client.execute(AccountExecutionRequest(action="inspect", account_id=name))
            (self.output / f"{label}-{name}.json").write_bytes(self.codec.encode_json(state))
            snapshot = AccountLedger(state.accounts[0].ledger).snapshot()
            self.record(
                "account_facts",
                {
                    "label": label,
                    "account": name,
                    "snapshot": snapshot,
                    "physical_orders": len(state.net_orders),
                    "child_orders": len(state.orders),
                    "checkpoints": {
                        item.instance_id: client.checkpoint(item.instance_id)
                        for item in self.config.instances
                        if item.account_id == name
                    },
                },
            )
            if self.public_venue is None and label in ("steady", "post_shutdown"):
                cash, fees, positions = self.workload.first_touch_oracle()[name]
                if (snapshot.cash, snapshot.fees, snapshot.positions) != (
                    (cash,),
                    (fees,),
                    positions,
                ):
                    self.failures.append(f"independent first-touch economics differ: {name}")

    def run_faults(self) -> None:
        """Inject one-shot protection faults during the declared native burst."""
        recovery = CapacityRecovery(self)
        anchors = tuple(
            int(
                (self.output / "fixture-epochs" / f"{source.name}.epoch")
                .read_bytes()
                .splitlines()[1]
            )
            for source in self.config.sources
        )
        burst_start = max(anchors) / 1_000_000_000 + 40
        burst_end = min(anchors) / 1_000_000_000 + 50
        time.sleep(max(0, burst_start - time.monotonic()))
        self.record(
            "loaded_faults_started",
            {"burst_start_monotonic": burst_start, "burst_end_monotonic": burst_end},
        )
        probes: tuple[tuple[str, Callable[[], object]], ...] = (
            ("policy_death", partial(recovery.worker_death, "okx-shared-fixed-btc")),
            ("source_death", partial(recovery.source_death, "okx-eth-book")),
            (
                "request_retention",
                partial(
                    recovery.request_retention_failure,
                    "bitfinex-shared",
                    "bitfinex-shared-fixed-btc",
                ),
            ),
            ("owner_death", partial(recovery.account_death, "bitfinex-isolated")),
        )
        for name, probe in probes:
            within_burst = burst_start <= time.monotonic() < burst_end
            self.record("fault_window", {"name": name, "within_declared_burst": within_burst})
            if not within_burst:
                self.failures.append(f"{name}: injection did not begin inside declared burst")
            try:
                self.record("fault_result", {"name": name, "result": probe()})
            except Exception as error:
                self.failures.append(f"{name}: {type(error).__name__}: {error}")
                self.record("fault_failure", self.failures[-1])
        self.control("shutdown")

    def _replacement_progressed(self, recovery: CapacityRecovery) -> bool:
        """Require eight live selections and eight nonempty, changed checkpoints."""
        status = self.status()
        if not self._healthy_status(status):
            return False
        checkpoints: dict[str, bytes] = {}
        for item in self.config.instances:
            before = recovery.before_checkpoints.get(item.instance_id)
            current = self.clients[item.account_id].checkpoint(item.instance_id)
            if before is None or current is None or current == before:
                return False
            checkpoints[item.instance_id] = current
        self.replacement_checkpoints = checkpoints
        return True

    def _await_replacement_progress(self, recovery: CapacityRecovery, first_claim: float) -> None:
        """Measure all eight advances against the first actual claim's fixed deadline."""
        remaining = max(0.0, 40 - (time.monotonic() - first_claim))
        try:
            if not self._replacement_progressed(recovery):
                self.wait_until(partial(self._replacement_progressed, recovery), remaining)
        except TimeoutError as error:
            self.record(
                "replacement_progress_timeout",
                {
                    "first_claim_to_timeout_seconds": time.monotonic() - first_claim,
                    "status": self.status(),
                },
            )
            raise AssertionError(
                "four-owner recovery exceeds unchanged 40-second budget"
            ) from error
        elapsed = time.monotonic() - first_claim
        self.record(
            "all_replacement_instances_progressed",
            {
                "first_claim_to_progress_seconds": elapsed,
                "operator_total_seconds": time.monotonic()
                - (recovery.operator_started_at or first_claim),
                "within_40_seconds": elapsed <= 40,
                "checkpoint_sha256": {
                    instance_id: hashlib.sha256(checkpoint).hexdigest()
                    for instance_id, checkpoint in self.replacement_checkpoints.items()
                },
            },
        )
        if elapsed > 40:
            self.failures.append("four-owner recovery exceeds unchanged 40-second budget")

    def finish_interval(self) -> None:
        """Stop at the measured boundary before reading accounts after fence release."""
        final = self.status()
        self.record("steady_completed", final)
        if not self._healthy_status(final):
            self.failures.append("steady interval lost active owners, sources or instances")
        self.control("shutdown")
        if self.supervisor is None or self.supervisor_started_at is None:
            raise RuntimeError("capacity shutdown lacks a started supervisor")
        code = self.supervisor.wait(
            timeout=max(0, self.supervisor_started_at + 75 - time.monotonic())
        )
        if code:
            raise RuntimeError(f"supervisor exited with status {code}")
        accounts = tuple(process for process in self.processes if process is not self.supervisor)
        if self.first_service_at is None or len(accounts) != len(self.config.accounts):
            raise RuntimeError("capacity shutdown lacks every account launcher")
        deadline = self.first_service_at + 120
        for process in accounts:
            code = process.wait(timeout=max(0, deadline - time.monotonic()))
            if code:
                raise RuntimeError(f"account launcher {process.pid} exited with status {code}")
        self.retain_accounts("post_shutdown", sockets=False)

    def _sample_health(self) -> None:
        """Retain fresh four-owner health throughout the declared measured interval."""
        status = self.status()
        at, now_ns = datetime.now(UTC), time.monotonic_ns()
        phases = status.account_phases or {}
        if self._health_run_id is None:
            self._health_run_id = status.run_id
        healthy = (
            self._healthy_status(status)
            and self._health_configuration is not None
            and status.configuration == self._health_configuration
            and status.run_id is not None
            and status.run_id == self._health_run_id
            and status.observed_at is not None
            and 0 <= (at - status.observed_at).total_seconds() <= 2
            and {owner.account_id: owner for owner in status.owners} == self.owners
            and set(phases) == set(self.owners)
            and all(
                phase.status == "observed"
                and phase.phase == "running"
                and 0 <= (at - phase.observed_at).total_seconds() <= 2
                for phase in phases.values()
            )
            and self.supervisor is not None
            and status.pid == self.supervisor.pid
            and self.supervisor.poll() is None
            and (self._health_last_ns is None or now_ns - self._health_last_ns <= 2_000_000_000)
        )
        health: dict[str, _Health] = {}
        for account in self.config.accounts:
            row = self.codec.decode_json(
                Path(account.socket_path).with_suffix(".health.json").read_bytes(), _Health
            )
            health[account.account_id] = row
            owner = self.owners[account.account_id]
            healthy = healthy and (
                row.pid == self.account_pids[account.account_id]
                and row.generation == owner.generation
                and row.owner_id == owner.owner_id
                and row.release_identity == owner.release_identity
                and 0 <= time.monotonic_ns() - row.heartbeat_ns <= 2_000_000_000
            )
            os.kill(row.pid, 0)
        for child in (*status.workers.values(), *status.sources.values()):
            if child.pid is not None:
                os.kill(child.pid, 0)
        self._health_last_ns = now_ns
        self.record("steady_health", {"healthy": healthy, "status": status, "owners": health})
        if not healthy:
            raise ValueError("measured interval has stale, missing or unhealthy service evidence")

    def _monitor_health(self) -> None:
        """Sample sticky protection and actual liveness without economic requests."""
        while not self._health_stop.wait(0.5):
            try:
                self._sample_health()
            except (OSError, ValueError) as error:
                self.failures.append(f"steady health: {type(error).__name__}: {error}")
                self.record("steady_health_failure", self.failures[-1])
                return

    def _stop_health_monitor(self) -> None:
        """Join the owned observer before service shutdown or failure cleanup."""
        self._health_stop.set()
        if self._health_thread is not None:
            self._health_thread.join(2)
            if self._health_thread.is_alive():
                raise TimeoutError("bounded health observer did not stop")

    def _finish_healthy_interval(self) -> None:
        """Close the continuous health witness before requesting finite shutdown."""
        self._stop_health_monitor()
        self._sample_health()
        self.finish_interval()

    def run(self) -> dict[str, object]:
        """Measure at least 60 seconds, retaining every first failure and final protection."""
        self.output.mkdir(parents=True, exist_ok=False)
        result: dict[str, object] = {
            "implementation": InstalledIdentity.sha256(),
            "public_venue": self.public_venue,
            "variant": self.variant,
            "features": self.features,
            "recover": self.recover,
            "fixture_identity": hashlib.sha256(
                Path(__file__).with_name("capacity_inputs.py").read_bytes()
            ).hexdigest(),
        }
        try:
            recovery = CapacityRecovery(self) if self.recover else None
            if recovery is None:
                self.bootstrap()
                first_claim = None
            else:
                first_claim = recovery.recover_four_owners()
            self.launch()
            if recovery is not None and first_claim is not None:
                self._await_replacement_progress(recovery, first_claim)
            if self.faults:
                self.run_faults()
                result["faults_only"] = True
                return result
            start = time.monotonic()
            self._sample_health()
            self._health_thread = threading.Thread(target=self._monitor_health)
            self._health_thread.start()
            self.record("steady_started", {"monotonic": start})
            result["reads"] = CapacityReadObserver(
                self.output / "reads",
                self.service_root,
                process_pids=(os.getpid(),),
                occupied_roots=(
                    self.service_root,
                    self.output / "measurements",
                    *(
                        self.root / f"target-{item.account_id}" / "state"
                        for item in self.config.accounts
                    ),
                    *((self.output / "reads" / "features",) if self.features else ()),
                ),
                duration_seconds=60,
                features=self.features,
                feature_cohort="recovery_steady" if self.recover else "initial_steady",
            ).run(
                on_interval_complete=self._finish_healthy_interval,
                on_feature_processes=lambda pids: self.record(
                    "feature_processes", {"feature_pids": pids}
                ),
            )
            result["measurement_and_postprocess_seconds"] = time.monotonic() - start
        except Exception as error:
            self.failures.append(f"{type(error).__name__}: {error}")
            self.record("failure", self.failures[-1])
        finally:
            try:
                self._stop_health_monitor()
            finally:
                self.cleanup()
            result["failures"] = self.failures
            result["passed"] = not self.failures
            (self.output / "summary.json").write_bytes(self.codec.encode_json(result))
        return result

    def cleanup(self) -> None:
        """Stop all owned processes and verify stopped journals even after failed measurement."""
        if self.supervisor is not None and self.supervisor.poll() is None:
            try:
                self.control("shutdown")
            except Exception as error:
                self.failures.append(f"shutdown request: {error}")
        if self.supervisor is None or self.supervisor.poll() is not None:
            for name, client in self.clients.items():
                if not client.socket_path.exists():
                    continue
                try:
                    client.shutdown(
                        AccountControl(
                            identity=uuid4().hex,
                            account_id=name,
                            kind="stop",
                            at=datetime.now(UTC),
                            reason="capacity final socket shutdown",
                        )
                    )
                except Exception as error:
                    self.record(
                        "uncertain_cleanup_shutdown", {"account": name, "error": str(error)}
                    )
                    pid = self.account_pids.get(name)
                    if pid is not None:
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
        for process in reversed(self.processes):
            if process.poll() is None:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        for watcher in self.watchers:
            watcher.join(1)
        for pid in self.child_pids:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            self.failures.append(f"owned child still alive: {pid}")
            os.kill(pid, signal.SIGTERM)
        if self.receiver is not None:
            self.receiver.close()
        for stream in self.streams:
            stream.close()
        phases: dict[str, str] = {}
        for definition in self.config.accounts:
            try:
                admin = self.admin(definition.account_id)
                state = admin.execute(AccountExecutionRequest(action="inspect"))
                if state.accounts[0].phase != "stopped":
                    admin.control(
                        AccountControl(
                            identity=uuid4().hex,
                            account_id=definition.account_id,
                            kind="stop",
                            at=datetime.now(UTC),
                            reason="capacity trial final cleanup",
                        )
                    )
                    state = admin.execute(AccountExecutionRequest(action="inspect"))
                phases[definition.account_id] = state.accounts[0].phase
                (self.output / f"final-{definition.account_id}.json").write_bytes(
                    self.codec.encode_json(state)
                )
            except Exception as error:
                self.failures.append(f"cleanup {definition.account_id}: {error}")
        self.record(
            "cleanup",
            {"phases": phases, "process_exits": [(p.pid, p.returncode) for p in self.processes]},
        )


class _Arguments(argparse.Namespace):
    """Carry finite driver and supervised-child arguments."""

    action: Literal["run", "child"]
    root: Path
    output: Path
    launcher: Path
    public_venue: Literal["okx", "bitfinex"] | None
    variant: CapacityVariant
    recover: bool
    faults: bool
    features: bool


def main() -> None:
    """Compose an installed finite characterization or its supervised source child."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "child"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--public-venue", choices=("okx", "bitfinex"))
    parser.add_argument(
        "--variant",
        choices=("base", "quiet", "oversize", "backpressure", "reconnect"),
        default="base",
    )
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--faults", action="store_true")
    parser.add_argument("--features", action="store_true")
    args = parser.parse_args(namespace=_Arguments())
    if args.faults and (args.public_venue is not None or args.variant != "base"):
        parser.error("burst fault drills require four base fixture sources")
    if args.action == "run":
        print(
            DomainCodec()
            .encode_json(
                CapacityTrial(
                    args.root,
                    args.output,
                    args.launcher,
                    public_venue=args.public_venue,
                    variant=args.variant,
                    recover=args.recover,
                    faults=args.faults,
                    features=args.features,
                ).run()
            )
            .decode()
        )
    else:
        codec = DomainCodec()
        config = codec.decode_json(
            (args.output / "configuration.json").read_bytes(), PaperServiceConfiguration
        )
        owners = codec.decode_json((args.output / "owners.json").read_bytes(), PaperServiceOwners)
        workload = CapacityWorkload(
            opening_at=config.accounts[0].configuration.opening_at,
            socket_root=Path(config.accounts[0].socket_path).parent,
            public_venue=args.public_venue,
        )
        # Alert routing is an invocation setting, independent of native fixture identity.
        transports = workload.fixture_transports(
            msgspec.structs.replace(config, alert_socket=None),
            variant=args.variant,
            exclude_venue=args.public_venue,
            epoch_root=args.output / "fixture-epochs",
            start_high=frozenset(item.name for item in config.sources)
            if args.recover
            else frozenset(),
        )
        result = run_paper_services(
            config,
            owners.owners,
            root=args.output / "operating",
            control_socket=Path(config.accounts[0].socket_path).parent / "supervisor.sock",
            transports=transports,
            measurement_root=args.output / "measurements",
        )
        print(codec.encode_json(result).decode())


if __name__ == "__main__":
    main()
