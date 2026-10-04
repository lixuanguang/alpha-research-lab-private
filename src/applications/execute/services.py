"""Supervise bounded native sources and isolated policies over signed account services."""

from __future__ import annotations

# standard library imports
import concurrent.futures
import errno
import fcntl
import hashlib
import multiprocessing
import os
import socket
import sqlite3
import stat
import time
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

# project library imports
from applications.execute.service_candidates import PaperServiceCandidates
from applications.execute.service_monitor import (
    DiagnosticReceipt,
    PaperServiceDiagnostics,
    PaperServiceMonitor,
)
from applications.execute.source_service import ReceivedSourceDelivery, run_source_service
from configuration import (
    BookRegistryConfiguration,
    BookSelection,
    CaptureRunConfig,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
)
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountObservation,
    PaperMarket,
    PaperOwner,
    PortfolioContext,
    SocketPaperAccount,
)
from market_data.adapters.sources import BookAdapters
from market_data.books import BookAsOfIndex, BookRegistry
from market_data.collection import CaptureTransport
from market_data.contracts import CaptureRequest, CaptureRunRequest, RecordingRequest
from market_data.storage import CaptureRecording
from research.observations import InputRequirement, LiveBookDecisionSource
from runtime import (
    CandidateExecutor,
    CandidateProcessFailure,
    InstalledIdentity,
    LoadedCandidate,
    ProcessCandidateExecutor,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
)
from serialization import DomainCodec, WireRecord
from telemetry import (
    HealthAlert,
    HealthMetric,
    HealthMetrics,
    HealthPolicy,
    RuntimeMeasurementJournal,
)


class PaperServiceControl(WireRecord, frozen=True):
    """Request inspection or an explicit scoped local lifecycle operation."""

    action: Literal[
        "inspect", "stop_instance", "restart_instance", "stop_source", "restart_source", "shutdown"
    ]
    identity: str
    subject: str | None = None
    observation: AccountObservation | None = None

    def __post_init__(self) -> None:
        """Reject incomplete controls before touching a service or its account."""
        if (
            not self.identity
            or self.action
            not in (
                "inspect",
                "stop_instance",
                "restart_instance",
                "stop_source",
                "restart_source",
                "shutdown",
            )
            or (self.action not in ("inspect", "shutdown") and not self.subject)
        ):
            raise ValueError("invalid paper service control")
        if self.observation is not None:
            if (
                self.action != "restart_instance"
                or type(self.observation) is not AccountObservation
            ):
                raise ValueError("only an instance restart accepts an account observation")
            self.observation.__post_init__()


class PaperServiceOwners(WireRecord, frozen=True):
    """Carry the explicitly claimed account tokens through one typed launch file."""

    owners: tuple[PaperOwner, ...]


class AccountHealth(WireRecord, frozen=True):
    """Decode the account service's separate liveness and completed-request clocks."""

    pid: int
    owner_id: str
    generation: int
    release_identity: str
    heartbeat_at: str
    heartbeat_ns: int
    request_progress_ns: int
    status: Literal["ready"]


@dataclass
class SourceChild:
    """Retain the sole process, pipe and freshness owner for one native input."""

    definition: PaperServiceSource
    request: RecordingRequest
    process: BaseProcess
    receiver: Connection[bytes, bytes]
    health: HealthMetrics
    observers: dict[str, SharedPaperCaptureObserver]
    stop: Event | None = None
    pipe_drained: bool = False
    received_count: int = 0


class PaperServices:
    """Own local child lifetime and deterministic per-source/account scheduling.

    Sources are visited in name order, one durable frame per turn. Sources with
    disjoint accounts may keep one observation in flight across turns. A source
    receives its next frame only after completion; every job joins before a
    lifecycle, control, phase or status mutation. Health checks continue while
    jobs are pending. Shared-account sources remain serial.
    Each account's cohort is evaluated in instance order by the existing shared
    runtime. Policy children have no account client: the parent commits their
    complete cohort once.
    No uncertain account operation is retried. Operator recovery uses retained
    facts and the separate signed account command, then a new explicit launch.
    """

    def __init__(
        self,
        configuration: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        *,
        root: Path,
        control_socket: Path,
        transports: Mapping[str, CaptureTransport] | None = None,
        measurement_root: Path | None = None,
        candidates: Path | None = None,
    ) -> None:
        """Bind explicit configuration and claimed owners without starting any process.

        ``candidates`` is the installed release's signed candidates directory, which
        packaged candidates require.
        """
        configuration.__post_init__()
        if (
            not root.is_absolute()
            or not control_socket.is_absolute()
            or (measurement_root is not None and not measurement_root.is_absolute())
        ):
            raise ValueError("paper services require absolute operating paths")
        if len(str(control_socket).encode()) > 100:
            raise ValueError("paper supervisor socket path is too long")
        if {item.account_id for item in owners} != {
            item.account_id for item in configuration.accounts
        } or len(owners) != len(configuration.accounts):
            raise ValueError("paper service owners differ from configured accounts")
        for owner in owners:
            owner.__post_init__()
        self.config, self.owners, self.root, self.control_socket = (
            configuration,
            owners,
            root,
            control_socket,
        )
        self.transports = {} if transports is None else dict(transports)
        self.measurement_root = measurement_root
        if not set(self.transports).issubset(item.name for item in configuration.sources):
            raise ValueError("unknown injected source transport")
        self.codec = DomainCodec()
        self.implementation = InstalledIdentity.sha256()
        self.accounts = {
            definition.account_id: SocketPaperAccount(
                config=definition.configuration,
                socket_path=Path(definition.socket_path),
                requests=root / "requests" / definition.account_id,
                paper_owner=next(
                    owner for owner in owners if owner.account_id == definition.account_id
                ),
                timeout_seconds=2.0,
            )
            for definition in configuration.accounts
        }
        self.instances = {item.instance_id: item for item in configuration.instances}
        self.active = set(configuration.active)
        self.workers: dict[str, ProcessCandidateExecutor] = {}
        self.resolved = PaperServiceCandidates(configuration, candidates)
        self.sources: dict[str, SourceChild] = {}
        self.faulted_accounts: set[str] = set()
        self.unavailable_accounts: set[str] = set()
        self.failures: list[dict[str, object]] = []
        self.monitor = PaperServiceMonitor(root / "monitoring")
        self.diagnostics: PaperServiceDiagnostics | None = None
        self.monitoring: dict[str, object] = {}
        self.account_phases: dict[str, object] = {}
        self.delivery_accounting: dict[str, object] = {}
        self.is_stopping = False
        self.shutdown_requested = False
        self.run_id = uuid4().hex
        # The supervisor's own UTC end bounds every segment-chain window it opens.
        self.stop_at: datetime | None = None
        self._observation_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._has_disjoint_source_accounts = self._sources_have_disjoint_accounts()
        self._next_telemetry = 0.0
        self._pending_observations: dict[
            str, concurrent.futures.Future[tuple[tuple[str, Exception], ...]]
        ] = {}
        self._observation_wake_receiver: socket.socket | None = None
        self._observation_wake_sender: socket.socket | None = None
        self._next_owner_health_ns = 0

    def _sources_have_disjoint_accounts(self) -> bool:
        """Permit parallel source observations only with distinct complete account sets."""
        source_accounts: dict[str, set[str]] = {}
        for instance in self.config.instances:
            source_accounts.setdefault(instance.source, set()).add(instance.account_id)
        if len(source_accounts) < 2:
            return False
        seen: set[str] = set()
        for account_ids in source_accounts.values():
            if seen.intersection(account_ids):
                return False
            seen.update(account_ids)
        return True

    def requirements(self, source: PaperServiceSource) -> tuple[InputRequirement, ...]:
        """Return the native book fields the source's candidates read."""
        return self.resolved.requirements(source)

    def source_identity(self, source: PaperServiceSource) -> str:
        """Identify a source's capture and projected fields independently of recordings."""
        return self.resolved.source_identity(source)

    def candidate(self, instance: PaperServiceInstance) -> LoadedCandidate:
        """Load the instance's explicitly selected candidate without fallback."""
        return self.resolved.candidate(instance)

    def binding(self, instance: PaperServiceInstance) -> SharedStrategyBinding:
        """Bind one candidate's continuation to its economic instance and venue."""
        source = next(item for item in self.config.sources if item.name == instance.source)
        account = self.accounts[instance.account_id]
        loaded = self.candidate(instance)
        return SharedStrategyBinding(
            instance_id=instance.instance_id,
            account_id=instance.account_id,
            entity=str(source.scenario.instrument_id),
            candidate=loaded,
            context=PortfolioContext(
                portfolio_id="reference",
                strategy_id=instance.instance_id,
                model_revision=self.model_identity(loaded),
                config_revision="paper-services",
                horizon="capture",
                reason="engineering-reference",
                venue=source.capture.venue,
                settlement="spot",
                risk_bucket="cash",
                authority_scope=account.config.mode,
            ),
            maximum_fee=instance.maximum_fee,
        )

    @staticmethod
    def model_identity(loaded: LoadedCandidate) -> str:
        """Name the candidate's fitted model, or the explicit rule-only selection."""
        return PaperServiceCandidates.model_identity(loaded)

    def preflight(self) -> None:
        """Verify immutable deployed definitions and active owners before scheduling work."""
        for account_id, account in self.accounts.items():
            # A bounded read: the full trace history outgrows the one MiB socket response.
            state = account.execute(
                AccountExecutionRequest(
                    action="inspect", account_id=account_id, projection="monitoring"
                )
            )
            activation = next(
                (
                    item
                    for item in state.paper_activations
                    if item.deployment.account_id == account_id
                ),
                None,
            )
            if activation is None or activation.owner != account.paper_owner:
                raise ValueError("paper service requires the current explicitly claimed owner")
            activation.require_authority(datetime.now(UTC))
            deployment = activation.deployment
            deployment.require_configuration(account.config)
            if any(item.phase != "running" for item in state.accounts):
                raise ValueError("paper service account is not explicitly activated")
            definitions = tuple(
                item for item in self.config.instances if item.account_id == account_id
            )
            if {item.instance_id for item in definitions} != {
                item.instance_id for item in deployment.strategies
            }:
                raise ValueError("paper service instance definitions differ from deployment")
            for definition in definitions:
                source = next(
                    item for item in self.config.sources if item.name == definition.source
                )
                loaded = self.candidate(definition)
                scope = deployment.scope_for(definition.instance_id)
                strategy = next(
                    item
                    for item in deployment.strategies
                    if item.instance_id == definition.instance_id
                )
                if (
                    scope.scenario != source.scenario
                    or scope.input_identity != self.source_identity(source)
                    or strategy.policy_identity != loaded.policy.identity
                    or strategy.candidate_identity != loaded.definition.identity
                    or strategy.feature_identity != loaded.feature.schema.identity
                    or strategy.model_identity != self.model_identity(loaded)
                ):
                    raise ValueError("paper service strategy or source identity differs")
            if self.active.intersection(state.stopped_instances):
                raise ValueError("selected instance requires explicit reconciled restart")

    def run(self) -> dict[str, object]:
        """Hold the local launch fence, supervise children and stop services on completion."""
        service_deadline = time.monotonic() + self.config.duration_seconds
        self.stop_at = datetime.now(UTC) + timedelta(seconds=self.config.duration_seconds)
        self.root.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            self.control_socket.parent.mkdir(parents=True, exist_ok=True)
            endpoint_descriptor = os.open(
                self.control_socket.with_suffix(".endpoint.lock"),
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
            )
            endpoint_fence = stack.enter_context(os.fdopen(endpoint_descriptor, "a+b"))
            fcntl.flock(endpoint_fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fence = stack.enter_context((self.root / "supervisor.lock").open("a+b"))
            fcntl.flock(fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            for definition in sorted(self.config.accounts, key=self._account_socket):
                socket_path = Path(definition.socket_path)
                account_fence = stack.enter_context(
                    socket_path.with_suffix(".scheduler.lock").open("a+b")
                )
                fcntl.flock(account_fence.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                owner = next(
                    item for item in self.owners if item.account_id == definition.account_id
                )
                claim_path = socket_path.with_suffix(".scheduler-owner.json")
                if claim_path.exists():
                    previous = self.codec.decode_json(claim_path.read_bytes(), PaperOwner)
                    if (
                        owner.deployment_sha256 != previous.deployment_sha256
                        or owner.generation <= previous.generation
                    ):
                        raise ValueError(
                            "scheduler restart requires a freshly reconciled owner generation"
                        )
            self.preflight()
            self._retain_selection()
            for definition in self.config.accounts:
                owner = next(
                    item for item in self.owners if item.account_id == definition.account_id
                )
                claim_path = Path(definition.socket_path).with_suffix(".scheduler-owner.json")
                with claim_path.open("wb") as stream:
                    stream.write(self.codec.encode_json(owner))
                    stream.flush()
                    os.fsync(stream.fileno())
            listener = self._listen()
            try:
                if self._has_disjoint_source_accounts:
                    self._start_observation_executor(stack)
                self.diagnostics = PaperServiceDiagnostics(
                    self.config,
                    self.owners,
                    root=self.root / "monitoring",
                    deadline=service_deadline,
                )
                self.diagnostics.start()
                for name in sorted(self.active):
                    self._start_instance(name)
                for source in self.config.sources:
                    if any(
                        item.source == source.name and item.instance_id in self.active
                        for item in self.config.instances
                    ):
                        self._start_source(source)
                active_deadline = service_deadline - self.drain_reserve(
                    self.config.duration_seconds
                )
                next_sample = 0.0
                while not self.is_stopping and time.monotonic() < active_deadline:
                    self._control(listener)
                    consumed = self._supervise()
                    if time.monotonic() >= next_sample:
                        self._sample()
                        self._write_status()
                        next_sample = time.monotonic() + self.config.poll_seconds
                    if not consumed:
                        self._wait_for_source()
            finally:
                try:
                    self._join_observations()
                finally:
                    try:
                        self._shutdown(listener, deadline=service_deadline)
                    finally:
                        self._observation_executor = None
            return self.status()

    @staticmethod
    def drain_reserve(duration_seconds: float) -> float:
        """Reserve the end of the service life for draining sources and stopping accounts.

        Observed drains finish in about a second; five seconds keeps that margin while
        leaving a 75-second service 70 seconds to serve its sources.
        """
        return min(5.0, duration_seconds / 5)

    def _shutdown(self, listener: socket.socket, *, deadline: float | None = None) -> None:
        """Fence every child and request every account stop despite diagnostic close failure."""
        self._join_observations()
        self.is_stopping = True
        drain_deadline = min(
            time.monotonic() + 10.0,
            float("inf") if deadline is None else deadline,
        )
        if self.diagnostics is not None:
            self.diagnostics.request_stop()
        for child in self.sources.values():
            if child.stop is not None:
                child.stop.set()
        if self.diagnostics is not None:
            try:
                self.diagnostics.close(deadline=min(drain_deadline, time.monotonic() + 2.0))
            except (OSError, RuntimeError) as error:
                self._record("diagnostic_close_failed", "monitoring", str(error))
            self._collect_diagnostics()
        while (
            any(
                child.stop is not None and not child.pipe_drained and not child.receiver.closed
                for child in self.sources.values()
            )
            and time.monotonic() < drain_deadline
        ):
            self._control(listener, draining=True)
            if not self._supervise():
                time.sleep(0.005)
        for name, child in self.sources.items():
            if child.stop is not None and child.pipe_drained and child.process.pid is not None:
                child.process.join(max(0.0, drain_deadline - time.monotonic()))
            try:
                self._close_source(child, deadline=drain_deadline)
            except OSError as error:
                self._record("source_close_failed", name, str(error))
            if child.stop is not None:
                self._account_source_delivery(name, child)
        for name, worker in self.workers.items():
            try:
                worker.close()
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                self._record("worker_close_failed", name, str(error))
        for account_id, account in self.accounts.items():
            try:
                account.shutdown(self._account_control(account_id, "stop", "supervisor_shutdown"))
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                self._record("shutdown_failed", account_id, str(error))
        self._write_status()
        # A drain this service started itself still answers the operator's shutdown
        # until just before the service deadline, so a request racing the end of the
        # active window is not lost and the process still exits inside its lifetime.
        service_end = time.monotonic() if deadline is None else deadline - 0.5
        while not self.shutdown_requested and time.monotonic() < service_end:
            if not self._control(listener, draining=True):
                time.sleep(0.02)
        while self._control(listener, draining=True):
            pass
        listener.close()
        self.control_socket.unlink(missing_ok=True)

    def status(self) -> dict[str, object]:
        """Expose liveness, freshness and economic observations as separate signals."""
        self._join_observations()
        source_states: dict[str, object] = {}
        for name, child in self.sources.items():
            try:
                values: object = child.health.snapshot()
            except TimeoutError:
                values = "health_lock_stalled"
            source_states[name] = {
                "pid": child.process.pid,
                "alive": child.process.is_alive(),
                "health": values,
                "markets": tuple(observer.last_market for observer in child.observers.values()),
            }
        return {
            "schema_version": "paper-service-status",
            "configuration": self.config.identity,
            "run_id": self.run_id,
            "observed_at": datetime.now(UTC),
            "pid": os.getpid(),
            "stopping": self.is_stopping,
            "active": tuple(sorted(self.active)),
            "workers": {
                name: {"pid": worker.pid, "alive": worker.is_alive}
                for name, worker in self.workers.items()
            },
            "sources": source_states,
            "source_delivery_accounting": self.delivery_accounting,
            "faulted_accounts": tuple(sorted(self.faulted_accounts)),
            "monitoring": self.monitoring,
            "account_phases": self.account_phases,
            "diagnostics": None if self.diagnostics is None else self.diagnostics.status(),
            "diagnostic_failures": self.monitor.failures
            + (0 if self.diagnostics is None else self.diagnostics.failure_count),
            "failures": tuple(self.failures),
            "owners": self.owners,
        }

    def apply(self, control: PaperServiceControl) -> dict[str, object]:
        """Apply one explicit operator command without clearing account-wide protection."""
        control.__post_init__()
        self._join_observations()
        controls = self.root / "controls"
        controls.mkdir(exist_ok=True)
        control_path = controls / f"{hashlib.sha256(control.identity.encode()).hexdigest()}.json"
        if control_path.exists():
            if self.codec.decode_json(control_path.read_bytes(), PaperServiceControl) != control:
                raise ValueError("service control identity reused with different content")
            return self.status()
        name = control.subject
        if control.action == "shutdown":
            self.is_stopping = True
            self.shutdown_requested = True
        elif control.action in ("stop_instance", "restart_instance"):
            if name is None or name not in self.instances:
                raise ValueError("unknown service instance")
            definition = self.instances[name]
            account = self.accounts[definition.account_id]
            if control.action == "stop_instance":
                self._stop_instance(name, "operator_stop")
            else:
                if name not in self.config.active:
                    raise ValueError(
                        "activate additional instances through a controlled configuration restart"
                    )
                observation = control.observation
                if (
                    observation is not None
                    and observation.snapshot.account_id != definition.account_id
                ):
                    raise ValueError("instance restart observation names another account")
                if name not in self.active:
                    if observation is not None and not account.reconcile(observation):
                        raise ValueError("instance_restart_requires_reconciliation")
                    account.execute(
                        AccountExecutionRequest(
                            action="restart_instance",
                            instance_id=name,
                            at=datetime.now(UTC),
                            paper_owner=account.paper_owner,
                        )
                    )
                    self.active.add(name)
                    self._start_instance(name)
                    self._refresh_observers(definition.source)
        elif control.action in ("stop_source", "restart_source"):
            if name is None or name not in self.sources:
                raise ValueError("unknown service source")
            child = self.sources[name]
            self._close_source(child)
            self._fault_source(name, "operator_source_stop")
            if control.action == "restart_source":
                self._start_source(child.definition)
        if control.action != "inspect":
            with control_path.open("xb") as stream:
                stream.write(self.codec.encode_json(control))
                stream.flush()
                os.fsync(stream.fileno())
        return self.status()

    def _retain_selection(self) -> None:
        """Retain strict selection ancestry before starting consumers of existing state."""
        path = self.root / "configuration.json"
        if path.exists():
            self.config.require_successor(
                self.codec.decode_json(path.read_bytes(), PaperServiceConfiguration)
            )
        revisions = self.root / "configurations"
        revisions.mkdir(exist_ok=True)
        payload = self.codec.encode_json(self.config)
        retained = revisions / f"{self.config.identity}.json"
        if not retained.exists():
            with retained.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)

    def _start_instance(self, name: str) -> None:
        """Spawn one policy with no journal or account credentials."""
        self._join_observations()
        self.workers[name] = ProcessCandidateExecutor(
            self.candidate(self.instances[name]),
            timeout_seconds=self.config.worker_timeout_seconds,
        )

    def _start_source(self, source: PaperServiceSource) -> None:
        """Create a fresh unsynchronized native recording and its independently watched child."""
        self._join_observations()
        request = self._capture_request(source)
        context = multiprocessing.get_context("spawn")
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            context.Pipe(duplex=False),
        )
        health = HealthMetrics()
        stop = context.Event()
        root = self.root / "runs" / self.run_id / source.name / request.recording_key
        process = context.Process(
            target=run_source_service,
            args=(
                request,
                root,
                sender,
                health,
                self.transports.get(source.name),
                (
                    None
                    if self.measurement_root is None
                    else self.measurement_root
                    / self.run_id
                    / source.name
                    / f"{request.recording_key}.capture.jsonl"
                ),
                stop,
            ),
        )
        child = SourceChild(source, request, process, receiver, health, {}, stop)
        self.sources[source.name] = child
        self._refresh_observers(source.name)
        process.start()
        sender.close()

    def _capture_request(self, source: PaperServiceSource) -> RecordingRequest:
        """Bind a fresh recording: one finite journal, or a chain when the source declares one.

        A chain's window opens now and closes at the supervisor's own end. Paper capture
        keeps the supervisor's readiness checks, so readiness is the stop instant.
        """
        if source.chain is None:
            return CaptureRequest(
                config=source.capture,
                recording_id=str(uuid4()),
                implementation_identity=self.implementation,
            )
        now = datetime.now(UTC)
        planned = self.stop_at or now + timedelta(seconds=self.config.duration_seconds)
        stop_at = max(planned, now + timedelta(seconds=1))
        return CaptureRunRequest(
            config=source.capture,
            window=CaptureRunConfig(
                start_at=now,
                ready_by=stop_at,
                stop_at=stop_at,
                max_messages=source.chain.max_messages,
                max_bytes=source.chain.max_bytes,
                max_segments=source.chain.max_segments,
                max_reconnects=source.capture.retries,
            ),
            run_id=str(uuid4()),
            implementation_identity=self.implementation,
        )

    def _refresh_observers(self, source_name: str) -> None:
        """Replace only a cohort selection while retaining each native book and last mark."""
        self._join_observations()
        child = self.sources.get(source_name)
        if child is None:
            return
        source = child.definition
        for account_id, account in self.accounts.items():
            definitions = tuple(
                item
                for item in self.config.instances
                if item.source == source_name and item.account_id == account_id
            )
            if not definitions:
                continue
            names = tuple(
                item.instance_id for item in definitions if item.instance_id in self.active
            )
            # An empty cohort still drains accepted paper obligations after a selective stop.
            bindings = tuple(self.binding(item) for item in definitions)
            executors: dict[str, CandidateExecutor] = {
                name: self.workers[name] for name in names if name in self.workers
            }
            runtime = SharedDecisionRuntime(account, bindings, executors)
            if account_id in child.observers:
                child.observers[account_id].active = names
                child.observers[account_id].runtime = runtime
                continue
            books = BookRegistry(
                BookRegistryConfiguration(
                    selections=(
                        BookSelection.from_capture(
                            source.capture,
                            source_id=child.request.identity,
                            capability=BookAdapters.capability(source.capture),
                            max_age_ns=source.freshness_us * 1000,
                            allow_degraded=True,
                        ),
                    ),
                    equivalences=(),
                    history_capacity=1000,
                )
            )
            path = (
                self.root
                / "runs"
                / self.run_id
                / source.name
                / f"{child.request.recording_key}-{account_id}.jsonl"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            measurements = (
                None
                if self.measurement_root is None
                else RuntimeMeasurementJournal(
                    self.measurement_root
                    / self.run_id
                    / source.name
                    / f"{child.request.recording_key}.{account_id}.paper.jsonl"
                )
            )
            child.observers[account_id] = SharedPaperCaptureObserver(
                source=LiveBookDecisionSource(
                    child.request, self.requirements(source), history_capacity=1000
                ),
                books=books,
                journal=account,
                runtime=runtime,
                account_id=account_id,
                scenario=source.scenario,
                delivery_path=path,
                active=names,
                measurements=measurements,
                index=BookAsOfIndex.create(path.with_name(path.stem + ".index.sqlite3")),
            )

    def _wait_for_source(self) -> None:
        """Wake on a source delivery while bounding control and health polling delay."""
        if any(future.done() for future in self._pending_observations.values()):
            return
        receivers: list[Connection[bytes, bytes] | socket.socket] = [
            child.receiver
            for name, child in self.sources.items()
            if not child.pipe_drained
            and not child.receiver.closed
            and name not in self._pending_observations
        ]
        timeout = 0.02
        if self._observation_executor is not None and self._has_disjoint_source_accounts:
            timeout = min(
                timeout,
                max(0.0, (self._next_owner_health_ns - time.monotonic_ns()) / 1_000_000_000),
            )
        if self._pending_observations and self._observation_wake_receiver is not None:
            receivers.append(self._observation_wake_receiver)
        if receivers:
            wait(receivers, timeout=timeout)
        elif self._pending_observations:
            concurrent.futures.wait(
                tuple(self._pending_observations.values()),
                timeout=timeout,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
        else:
            time.sleep(timeout)

    def _start_observation_executor(self, stack: ExitStack) -> None:
        """Own completion sockets until every worker and completion callback has joined."""
        receiver, sender = socket.socketpair()
        stack.callback(receiver.close)
        stack.callback(sender.close)
        stack.callback(self._clear_observation_executor)
        receiver.setblocking(False)
        sender.setblocking(False)
        self._observation_wake_receiver, self._observation_wake_sender = receiver, sender
        self._observation_executor = stack.enter_context(
            concurrent.futures.ThreadPoolExecutor(
                max_workers=len(self.config.accounts), thread_name_prefix="paper-source"
            )
        )

    def _clear_observation_executor(self) -> None:
        """Clear run-owned references after the executor has joined its callbacks."""
        self._observation_executor = None
        self._observation_wake_receiver = self._observation_wake_sender = None

    def _notify_observation_completion(
        self, _future: concurrent.futures.Future[tuple[tuple[str, Exception], ...]]
    ) -> None:
        """Coalesce a completed job into one bounded, nonblocking wake notification."""
        sender = self._observation_wake_sender
        if sender is not None:
            try:
                sender.send(b"\0")
            except BlockingIOError:
                # A queued notification already makes the receiver readable.
                pass

    def _check_owner_health(self) -> None:
        """Fence owner loss within the existing idle bound without caching RPC authority."""
        if self._observation_executor is not None and self._has_disjoint_source_accounts:
            checked_ns = time.monotonic_ns()
            if checked_ns < self._next_owner_health_ns:
                return
            self._next_owner_health_ns = checked_ns + 20_000_000
        for definition in self.config.accounts:
            if definition.account_id in self.faulted_accounts:
                continue
            try:
                health = self.codec.decode_json(
                    Path(definition.socket_path).with_suffix(".health.json").read_bytes(),
                    AccountHealth,
                )
                heartbeat = health.heartbeat_ns
                owner = next(
                    item for item in self.owners if item.account_id == definition.account_id
                )
                if (
                    type(heartbeat) is not int
                    or type(health.pid) is not int
                    or health.pid <= 0
                    or time.monotonic_ns() - heartbeat > 2_000_000_000
                    or health.generation != owner.generation
                    or health.owner_id != owner.owner_id
                    or health.release_identity != owner.release_identity
                ):
                    raise ValueError("account owner heartbeat is stale or replaced")
                os.kill(health.pid, 0)
            except (OSError, ValueError, TypeError) as error:
                self._join_observations()
                self._fault_account(definition.account_id, "account_owner_lost", str(error))

    def _supervise(self) -> bool:
        """Fence failed children and consume at most one delivery per source this pass."""
        self._finish_observations()
        consumed = False
        executor = self._observation_executor if self._has_disjoint_source_accounts else None
        ready: list[tuple[SourceChild, ReceivedSourceDelivery, int]] = []
        self._check_owner_health()
        for name in tuple(sorted(self.active)):
            worker = self.workers[name]
            try:
                heartbeat = worker.health.snapshot()[HealthMetric.HEARTBEAT]
                has_stalled = heartbeat != 0 and time.monotonic_ns() - heartbeat > 2_000_000_000
            except TimeoutError:
                has_stalled = True
            if not worker.is_alive or has_stalled:
                self._join_observations()
                if name in self.active:
                    self._stop_instance(name, "worker_lost")
        for name, child in tuple(sorted(self.sources.items())):
            if child.pipe_drained or child.receiver.closed:
                continue
            is_live = child.process.is_alive()
            if not is_live and not (self.is_stopping and child.stop is not None):
                self._fault_source(name, "source_lost")
                continue
            try:
                if not self.is_stopping:
                    policy = HealthPolicy(
                        heartbeat_seconds=2,
                        progress_seconds=30,
                        freshness_seconds=max(1, child.definition.freshness_us // 1_000_000),
                        max_queue=child.definition.capture.queue_capacity,
                        max_reconnects=child.definition.capture.retries,
                        max_invalid=0,
                        alert_socket=self.config.alert_socket
                        or "/private/tmp/absent-paper-alert.sock",
                    )
                    reason = policy.reason(child.health.snapshot(), now_ns=time.monotonic_ns())
                    if reason:
                        self._close_source(child)
                        self._fault_source(name, reason)
                        continue
                if name in self._pending_observations:
                    continue
                if child.receiver.poll():
                    try:
                        payload = child.receiver.recv_bytes(16_777_216)
                        received_ns = time.monotonic_ns()
                    except EOFError:
                        if self.is_stopping and child.stop is not None:
                            child.pipe_drained = True
                            continue
                        raise
                    delivery = self.codec.decode_json(payload, ReceivedSourceDelivery)
                    if delivery.book.position != child.received_count:
                        raise ValueError("source pipe delivery position differs from durable order")
                    child.received_count += 1
                    consumed = True
                    if executor is not None:
                        ready.append((child, delivery, received_ns))
                        continue
                    for account_id, observer in sorted(child.observers.items()):
                        if account_id in self.unavailable_accounts:
                            continue
                        if account_id in self.faulted_accounts:
                            # Fresh input may settle old obligations but never evaluates
                            # candidates.
                            observer.active = ()
                        try:
                            observer._observe_validated(
                                delivery.record, delivery.book, received_ns=received_ns
                            )
                        except Exception as error:
                            self._observer_failed(account_id, error)
            except (OSError, EOFError, ValueError, TimeoutError) as error:
                self._close_source(child)
                self._fault_source(name, f"source_failure:{type(error).__name__}")
        if executor is not None:
            # Collect this pass's health/receive results before adding jobs. Older
            # jobs may remain in flight; each lifecycle fence joins them first.
            self._observe_ready_sources(ready, executor)
        return consumed

    def _observe_ready_sources(
        self,
        ready: list[tuple[SourceChild, ReceivedSourceDelivery, int]],
        executor: concurrent.futures.ThreadPoolExecutor,
    ) -> None:
        """Own at most one in-flight frame per disjoint source across supervisor turns."""
        try:
            for child, delivery, received_ns in ready:
                observers = []
                for account_id, observer in sorted(child.observers.items()):
                    if account_id in self.unavailable_accounts:
                        continue
                    if account_id in self.faulted_accounts:
                        observer.active = ()
                    observers.append((account_id, observer))
                if observers:
                    future = executor.submit(
                        self._observe_source_group, delivery, tuple(observers), received_ns
                    )
                    self._pending_observations[child.definition.name] = future
                    future.add_done_callback(self._notify_observation_completion)
        except BaseException:
            self._join_observations()
            raise

    def _finish_observations(self) -> None:
        """Release completed source slots and fence failures after every other job joins."""
        receiver = self._observation_wake_receiver
        if receiver is not None:
            try:
                # At most four jobs plus their preceding callbacks can notify
                # between turns; one bounded drain also tolerates coalescing.
                receiver.recv(64)
            except BlockingIOError:
                pass
        completed = [
            name for name, future in sorted(self._pending_observations.items()) if future.done()
        ]
        failures: list[tuple[str, Exception]] = []
        try:
            for name in completed:
                failures.extend(self._pending_observations.pop(name).result())
            if failures and self._pending_observations:
                concurrent.futures.wait(tuple(self._pending_observations.values()))
                for name in sorted(tuple(self._pending_observations)):
                    failures.extend(self._pending_observations.pop(name).result())
        except BaseException:
            concurrent.futures.wait(tuple(self._pending_observations.values()))
            self._pending_observations.clear()
            raise
        # Every failed future has been removed and every outstanding job joined
        # before handlers can recursively stop, fault or refresh another owner.
        for account_id, error in failures:
            self._observer_failed(account_id, error)

    def _join_observations(self) -> None:
        """Finish all owned source work before a supervisor lifecycle or status mutation."""
        if self._pending_observations:
            concurrent.futures.wait(tuple(self._pending_observations.values()))
            self._finish_observations()

    @staticmethod
    def _observe_source_group(
        delivery: ReceivedSourceDelivery,
        observers: tuple[tuple[str, SharedPaperCaptureObserver], ...],
        received_ns: int | None = None,
    ) -> tuple[tuple[str, Exception], ...]:
        """Preserve a source's account order without mutating supervisor lifecycle state."""
        failures: list[tuple[str, Exception]] = []
        for account_id, observer in observers:
            try:
                observer._observe_validated(delivery.record, delivery.book, received_ns=received_ns)
            except Exception as error:
                failures.append((account_id, error))
        return tuple(failures)

    def _observer_failed(self, account_id: str, error: Exception) -> None:
        """Classify an observer failure on the supervisor after all parallel jobs joined."""
        self._join_observations()
        if isinstance(error, CandidateProcessFailure):
            failed_worker = next(
                (
                    instance
                    for instance in sorted(self.active)
                    if self.workers[instance].pid == error.pid
                    and self.instances[instance].account_id == account_id
                ),
                None,
            )
            if failed_worker is None:
                self._fault_account(account_id, "unidentified_policy_failure", str(error))
            else:
                # Only this typed pre-commit failure proves that no cohort admission
                # was attempted. Earlier matching receipts are never replayed.
                self._stop_instance(failed_worker, "worker_lost_during_decision")
        else:
            failed = tuple(
                instance for instance in tuple(self.active) if not self.workers[instance].is_alive
            )
            for instance in failed:
                self._stop_instance(instance, "worker_lost_during_decision")
            # A coincident worker death does not classify an uncertain account
            # response or delivery failure as a rejected transaction.
            self._fault_account(account_id, "account_or_delivery_failure", str(error))

    def _stop_instance(self, name: str, reason: str) -> None:
        """Stop a policy before durable selective cancellation, preserving every other owner."""
        self._join_observations()
        definition = self.instances[name]
        worker = self.workers.get(name)
        if worker is not None:
            worker.close()
        self.active.discard(name)
        account = self.accounts[definition.account_id]
        try:
            account.execute(
                AccountExecutionRequest(
                    action="stop_instance",
                    instance_id=name,
                    at=datetime.now(UTC),
                    paper_owner=account.paper_owner,
                )
            )
            self._refresh_observers(definition.source)
            self._record(
                reason,
                name,
                "instance stopped; shared parent cancellation remains explicit in journal",
            )
        except (OSError, ValueError, RuntimeError, TimeoutError) as error:
            self._fault_account(definition.account_id, "selective_stop_failed", str(error))

    def _fault_source(self, name: str, reason: str) -> None:
        """Stop every dependent account's new exposure without assuming unrelated source health."""
        self._join_observations()
        for account_id in sorted(
            {item.account_id for item in self.config.instances if item.source == name}
        ):
            self._fault_account(account_id, reason, name)

    def _fault_account(self, account_id: str, reason: str, detail: str) -> None:
        """Terminate dependents before attempting the independent durable account fault."""
        self._join_observations()
        if reason in ("account_owner_lost", "account_or_delivery_failure", "selective_stop_failed"):
            self.unavailable_accounts.add(account_id)
        if account_id in self.faulted_accounts:
            return
        self.faulted_accounts.add(account_id)
        self._stop_account_workers(account_id)
        try:
            self.accounts[account_id].control(self._account_control(account_id, "fault", reason))
        except (OSError, ValueError, RuntimeError, TimeoutError) as error:
            detail += f"; durable fault unavailable: {type(error).__name__}"
        self._record(reason, account_id, detail)

    def _stop_account_workers(self, account_id: str) -> None:
        """Fence all dependent policies without changing an existing account stop identity."""
        self._join_observations()
        for name in tuple(self.active):
            if self.instances[name].account_id == account_id:
                self.workers[name].close()
                self.active.discard(name)

    def _record(self, reason: str, subject: str, detail: str) -> None:
        """Retain actual protection and local socket outcome separately from receiver evidence."""
        accepted = self.config.alert_socket is not None and HealthAlert.deliver(
            self.config.alert_socket, f"paper-services {subject} {reason}"
        )
        event: dict[str, object] = {
            "at": datetime.now(UTC),
            "reason": reason,
            "subject": subject,
            "detail": detail,
            "alert_socket_accepted": accepted,
        }
        self.failures.append(event)
        try:
            with (self.root / "events.jsonl").open("ab") as stream:
                stream.write(self.codec.encode_json(event) + b"\n")
                stream.flush()
        except OSError as error:
            self.monitor.failures += 1
            self.monitor.last_error = f"event_retention:{type(error).__name__}"

    def _account_source_delivery(self, name: str, child: SourceChild) -> None:
        """Retain constant-cost native and account counts for exact offline parity review."""
        key = child.request.recording_key
        recording = CaptureRecording(
            self.root / "runs" / self.run_id / name / key / key, child.request
        )
        result_retained = (recording.root.parent / "source-result.json").is_file()
        completed = False
        durable_records: int | None = None
        cursor_sha256: str | None = None
        segments: int | None = None
        error_name: str | None = None
        try:
            # A chain counts run-wide across its segments; its digest is the last segment's.
            completed = recording.completed
            cursor = recording.cursor()
            durable_records, cursor_sha256 = cursor.records, cursor.sha256
            segments = len(cursor.segments)
        except (OSError, ValueError, OverflowError) as error:
            error_name = type(error).__name__
        accounts: dict[str, object] = {}
        for account_id, observer in sorted(child.observers.items()):
            retained = observer.retained_count
            accounts[account_id] = {
                "delivery_path": None
                if observer.delivery_path is None
                else str(observer.delivery_path),
                "retained_deliveries": retained,
                "observed_deliveries": observer.delivered_count,
                "complete": (
                    completed
                    and result_retained
                    and child.pipe_drained
                    and child.process.exitcode == 0
                    and durable_records is not None
                    and retained == durable_records == observer.delivered_count
                ),
            }
        is_complete = (
            completed
            and result_retained
            and child.pipe_drained
            and child.process.exitcode == 0
            and durable_records is not None
            and child.received_count == durable_records
            and all(
                isinstance(value, dict) and value["complete"] is True for value in accounts.values()
            )
        )
        accounting: dict[str, object] = {
            "status": "complete" if is_complete else "incomplete",
            "capture_finalization": "completed" if completed else "interrupted_prefix",
            "result_retained": result_retained,
            "pipe_drained": child.pipe_drained,
            "source_exitcode": child.process.exitcode,
            "durable_records": durable_records,
            "cursor_sha256": cursor_sha256,
            "pipe_deliveries": child.received_count,
            "accounts": accounts,
            "error": error_name,
        }
        if isinstance(child.request, CaptureRunRequest):
            accounting["capture_segments"] = segments
        self.delivery_accounting[name] = accounting
        if not is_complete:
            self._record(
                "source_delivery_incomplete",
                name,
                f"durable={durable_records} pipe={child.received_count} "
                f"drained={child.pipe_drained} completed={completed} error={error_name}",
            )

    def _sample(self) -> None:
        """Keep protection reads on cadence while full reports run in their own process."""
        self._join_observations()
        self._collect_diagnostics()
        latest_markets: dict[str, tuple[PaperMarket, ...]] = {}
        for account_id, account in self.accounts.items():
            latest_markets[account_id] = tuple(
                observer.last_market
                for child in self.sources.values()
                for owner, observer in child.observers.items()
                if owner == account_id and observer.last_market is not None
            )
            try:
                view = next(
                    item for item in account.accounts() if item.ledger.account_id == account_id
                )
                self.account_phases[account_id] = {
                    "observed_at": datetime.now(UTC),
                    "phase": view.phase,
                    "status": "observed",
                }
                if view.phase in ("stopped", "faulted") and account_id not in self.faulted_accounts:
                    self.faulted_accounts.add(account_id)
                    self._stop_account_workers(account_id)
                    self._record("account_protected", account_id, view.phase)
            except (OSError, ValueError, RuntimeError, TimeoutError, StopIteration) as error:
                self.monitor.failures += 1
                self.monitor.last_error = f"account_phase:{type(error).__name__}: {error}"
                self.account_phases[account_id] = {
                    "observed_at": datetime.now(UTC),
                    "status": "failed",
                    "error": self.monitor.last_error,
                }
        # Diagnostic telemetry is retained every pass, or on its own declared cadence
        # once every account's latest report was retained. Until then (for example
        # before a held position has its first mark) it retries every pass.
        if self.diagnostics is not None and (
            not self._telemetry_retained() or time.monotonic() >= self._next_telemetry
        ):
            self._next_telemetry = time.monotonic() + self.config.telemetry_interval
            self.diagnostics.submit(latest_markets)

    def _telemetry_retained(self) -> bool:
        """Report whether every account's latest diagnostic report was retained."""
        return all(
            isinstance(receipt := self.monitoring.get(account_id), DiagnosticReceipt)
            and receipt.status == "retained"
            for account_id in self.accounts
        )

    def _collect_diagnostics(self) -> None:
        """Keep actual compact report receipts separate from synchronous phase protection."""
        if self.diagnostics is None:
            return
        for receipt in self.diagnostics.poll():
            self.monitoring[receipt.account_id] = receipt

    def _write_status(self) -> None:
        """Publish a replaceable liveness view; economic state remains in the account journal."""
        temporary = self.root / ".status.json"
        try:
            temporary.write_bytes(self.codec.encode_json(self.status()))
            temporary.replace(self.root / "status.json")
        except OSError as error:
            self.monitor.failures += 1
            self.monitor.last_error = f"status_retention:{type(error).__name__}"

    def _control(self, listener: socket.socket, *, draining: bool = False) -> bool:
        """Handle one bounded control request while the source loop retains scheduling ownership.

        While draining, only ``inspect`` and ``shutdown`` are applied; any other
        control is answered with a refusal.

        Returns:
            Whether a pending connection was handled.
        """
        try:
            connection, _ = listener.accept()
        except BlockingIOError:
            return False
        except OSError:
            # A drain may meet a listener that never listened; nothing is pending there.
            if draining:
                return False
            raise
        with connection:
            self._join_observations()
            connection.settimeout(2)
            try:
                payload = bytearray()
                deadline = time.monotonic() + 2
                while b"\n" not in payload:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("service control frame deadline exceeded")
                    connection.settimeout(remaining)
                    block = connection.recv(4096)
                    if not block or len(payload) + len(block) > 65536:
                        raise ValueError("incomplete or oversized service control")
                    payload.extend(block)
                control = self.codec.decode_json(
                    bytes(payload).split(b"\n", 1)[0], PaperServiceControl
                )
                if draining and control.action not in ("inspect", "shutdown"):
                    raise ValueError("service is draining; only inspect and shutdown apply")
                result = {"ok": True, "status": self.apply(control)}
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                result = {"ok": False, "error": str(error)}
            try:
                connection.sendall(self.codec.encode_json(result) + b"\n")
            except OSError:
                # A lost operator response must not replay a completed control.
                self.monitor.failures += 1
                self.monitor.last_error = "operator_response_lost"
        return True

    @staticmethod
    def _account_socket(account: PaperServiceAccount) -> str:
        """Acquire multiple account scheduling fences in a fixed order."""
        return account.socket_path

    def _listen(self) -> socket.socket:
        """Refuse occupied endpoints and remove only a demonstrably stale local socket."""
        self.control_socket.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = self.control_socket.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISSOCK(existing.st_mode):
                raise ValueError("paper supervisor endpoint is not a socket")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                try:
                    probe.connect(str(self.control_socket))
                except OSError as error:
                    if error.errno not in (errno.ECONNREFUSED, errno.ENOENT):
                        raise ValueError("paper supervisor endpoint cannot be replaced") from error
                else:
                    raise ValueError("paper supervisor endpoint is already active")
            self.control_socket.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.control_socket))
            os.chmod(self.control_socket, 0o600)
            listener.listen(8)
            listener.setblocking(False)
        except BaseException:
            listener.close()
            raise
        return listener

    @staticmethod
    def _account_control(
        account_id: str, kind: Literal["stop", "fault"], reason: str
    ) -> AccountControl:
        """Name one actual supervisor control without inventing a historical receipt."""
        return AccountControl(
            identity=f"service:{uuid4().hex}",
            account_id=account_id,
            kind=kind,
            at=datetime.now(UTC),
            reason=reason,
        )

    def _close_source(self, child: SourceChild, *, deadline: float | None = None) -> None:
        """Fence a source before releasing its receiver or starting a replacement."""
        self._join_observations()
        if child.process.pid is not None:
            if child.process.is_alive():
                child.process.terminate()
            child.process.join(
                1 if deadline is None else max(0.0, min(1.0, deadline - time.monotonic()))
            )
            if child.process.is_alive():
                child.process.kill()
                child.process.join(
                    1 if deadline is None else max(0.0, min(1.0, deadline - time.monotonic()))
                )
        child.receiver.close()
        failed: list[str] = []
        for account_id, observer in child.observers.items():
            if observer.index is not None:
                # Release the delivery index writer and its WAL; rows stay readable.
                try:
                    observer.index.close()
                except sqlite3.Error as error:
                    failed.append(f"{account_id}:{type(error).__name__}")
            if observer.measurements is not None:
                try:
                    observer.measurements.close()
                except OSError as error:
                    failed.append(f"{account_id}:{type(error).__name__}")
        if failed:
            raise OSError("observer close failed: " + ", ".join(failed))


def run_paper_services(
    configuration: PaperServiceConfiguration,
    owners: tuple[PaperOwner, ...],
    *,
    root: Path,
    control_socket: Path,
    transports: Mapping[str, CaptureTransport] | None = None,
    measurement_root: Path | None = None,
    candidates: Path | None = None,
) -> dict[str, object]:
    """Compose one explicit bounded installed deployment and return its stopped service state."""
    services = PaperServices(
        configuration,
        owners,
        root=root,
        control_socket=control_socket,
        transports=transports,
        measurement_root=measurement_root,
        candidates=candidates,
    )
    return services.run()


def control_paper_services(socket_path: Path, request_path: Path) -> bytes:
    """Validate one operator request, send it once and return the retained service observation."""
    codec = DomainCodec()
    payload = request_path.read_bytes()
    control = codec.decode_json(payload, PaperServiceControl)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(socket_path))
        connection.sendall(codec.encode_json(control) + b"\n")
        response = bytearray()
        while b"\n" not in response:
            block = connection.recv(65536)
            if not block or len(response) + len(block) > 16_777_216:
                raise ValueError("incomplete or oversized service response")
            response.extend(block)
    return bytes(response).split(b"\n", 1)[0]
