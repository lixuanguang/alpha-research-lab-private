"""Supervise bounded native sources and isolated policies over signed account services."""

from __future__ import annotations

# standard library imports
import errno
import fcntl
import hashlib
import multiprocessing
import os
import socket
import stat
import time
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

# project library imports
from applications.execute.service_inputs import ServiceBookInputs
from applications.execute.service_monitor import PaperServiceDiagnostics, PaperServiceMonitor
from applications.execute.source_service import _ReceivedSourceDelivery, run_source_service
from configuration import (
    BookRegistryConfiguration,
    BookSelection,
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
from market_data.books import BookRegistry
from market_data.collection import CaptureTransport
from market_data.contracts import CaptureCursor, CaptureRequest
from research.observations import LiveBookDecisionSource
from runtime import (
    InstalledIdentity,
    PolicyProcessFailure,
    ProcessDecisionPolicy,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
)
from serialization import DomainCodec, WireRecord
from strategies import DecisionPolicy, LiquidityClipPolicy, ReferenceClipPolicy
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


class _AccountHealth(WireRecord, frozen=True):
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
class _SourceChild:
    """Retain the sole process, pipe and freshness owner for one native input."""

    definition: PaperServiceSource
    request: CaptureRequest
    process: BaseProcess
    receiver: Connection[bytes, bytes]
    health: HealthMetrics
    observers: dict[str, SharedPaperCaptureObserver]
    stop: Event | None = None
    pipe_drained: bool = False
    received_count: int = 0


class PaperServices:
    """Own local child lifetime and deterministic per-source/account scheduling.

    Sources are visited in name order, one durable frame per turn. Each account's
    cohort is evaluated in instance order by the existing shared runtime. Policy
    children have no account client: the parent commits their complete cohort once.
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
    ) -> None:
        """Bind explicit configuration and claimed owners without starting any process."""
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
        self.workers: dict[str, ProcessDecisionPolicy] = {}
        self.sources: dict[str, _SourceChild] = {}
        self.faulted_accounts: set[str] = set()
        self.unavailable_accounts: set[str] = set()
        self.failures: list[dict[str, object]] = []
        self.monitor = PaperServiceMonitor(root / "monitoring")
        self.diagnostics: PaperServiceDiagnostics | None = None
        self.monitoring: dict[str, object] = {}
        self.account_phases: dict[str, object] = {}
        self.delivery_accounting: dict[str, object] = {}
        self.is_stopping = False
        self.run_id = uuid4().hex

    def policy(self, instance: PaperServiceInstance) -> DecisionPolicy:
        """Resolve the explicitly selected installed reference formula without fallback."""
        source = next(item for item in self.config.sources if item.name == instance.source)
        factory = ReferenceClipPolicy if instance.policy == "fixed_clip" else LiquidityClipPolicy
        return factory(
            instance.quantity,
            source.scenario.adverse.currency,
            instance.lot,
            implementation=self.implementation,
        )

    def binding(
        self, instance: PaperServiceInstance, policy: DecisionPolicy
    ) -> SharedStrategyBinding:
        """Bind stable policy continuation to one economic instance and venue."""
        source = next(item for item in self.config.sources if item.name == instance.source)
        account = self.accounts[instance.account_id]
        return SharedStrategyBinding(
            instance_id=instance.instance_id,
            account_id=instance.account_id,
            entity=str(source.scenario.instrument_id),
            policy=policy,
            context=PortfolioContext(
                portfolio_id="reference",
                strategy_id=instance.instance_id,
                model_revision="rule-only",
                config_revision="paper-services-v1",
                horizon="capture",
                reason="engineering-reference",
                venue=source.capture.venue,
                settlement="spot",
                risk_bucket="cash",
                authority_scope=account.config.mode,
            ),
            maximum_fee=instance.maximum_fee,
        )

    def preflight(self) -> None:
        """Verify immutable deployed definitions and active owners before scheduling work."""
        for account_id, account in self.accounts.items():
            state = account.execute(
                AccountExecutionRequest(action="inspect", account_id=account_id)
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
                inputs = ServiceBookInputs((), source.freshness_us, source.market_interval_us)
                scope = deployment.scope_for(definition.instance_id)
                identity = hashlib.sha256(
                    self.codec.encode_json((source.capture, inputs.requirement, inputs.identity))
                ).hexdigest()
                strategy = next(
                    item
                    for item in deployment.strategies
                    if item.instance_id == definition.instance_id
                )
                if (
                    scope.scenario != source.scenario
                    or scope.input_identity != identity
                    or strategy.policy_identity != self.policy(definition).identity
                    or strategy.feature_identity != inputs.identity
                    or strategy.model_identity != "rule-only"
                ):
                    raise ValueError("paper service strategy or source identity differs")
            if self.active.intersection(state.stopped_instances):
                raise ValueError("selected instance requires explicit reconciled restart")

    def run(self) -> dict[str, object]:
        """Hold the local launch fence, supervise children and stop services on completion."""
        service_deadline = time.monotonic() + self.config.duration_seconds
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
                drain_reserve = min(10.0, self.config.duration_seconds / 5)
                active_deadline, next_sample = service_deadline - drain_reserve, 0.0
                while not self.is_stopping and time.monotonic() < active_deadline:
                    self._control(listener)
                    consumed = self._supervise()
                    if time.monotonic() >= next_sample:
                        self._sample()
                        self._write_status()
                        next_sample = time.monotonic() + self.config.poll_seconds
                    if not consumed:
                        time.sleep(0.02)
            finally:
                self._shutdown(listener, deadline=service_deadline)
            return self.status()

    def _shutdown(self, listener: socket.socket, *, deadline: float | None = None) -> None:
        """Fence every child and request every account stop despite diagnostic close failure."""
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
        listener.close()
        self.control_socket.unlink(missing_ok=True)

    def status(self) -> dict[str, object]:
        """Expose liveness, freshness and economic observations as separate signals."""
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
            "schema_version": "paper-service-status-v1",
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
        self.workers[name] = ProcessDecisionPolicy(
            self.policy(self.instances[name]), timeout_seconds=self.config.worker_timeout_seconds
        )

    def _start_source(self, source: PaperServiceSource) -> None:
        """Create a fresh unsynchronized native recording and its independently watched child."""
        request = CaptureRequest(
            config=source.capture,
            recording_id=str(uuid4()),
            implementation_identity=self.implementation,
        )
        context = multiprocessing.get_context("spawn")
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            context.Pipe(duplex=False),
        )
        health = HealthMetrics()
        stop = context.Event()
        root = self.root / "runs" / self.run_id / source.name / request.recording_id
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
                    / f"{request.recording_id}.capture.jsonl"
                ),
                stop,
            ),
        )
        child = _SourceChild(source, request, process, receiver, health, {}, stop)
        self.sources[source.name] = child
        self._refresh_observers(source.name)
        process.start()
        sender.close()

    def _refresh_observers(self, source_name: str) -> None:
        """Replace only a cohort selection while retaining each native book and last mark."""
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
            inputs = ServiceBookInputs(names, source.freshness_us, source.market_interval_us)
            # An empty cohort still drains accepted paper obligations after a selective stop.
            bindings = tuple(
                self.binding(
                    item,
                    self.workers[item.instance_id]
                    if item.instance_id in self.workers
                    else self.policy(item),
                )
                for item in definitions
            )
            runtime = SharedDecisionRuntime(account, bindings)
            if account_id in child.observers:
                child.observers[account_id].inputs = inputs
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
                / f"{child.request.recording_id}-{account_id}.jsonl"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            measurements = (
                None
                if self.measurement_root is None
                else RuntimeMeasurementJournal(
                    self.measurement_root
                    / self.run_id
                    / source.name
                    / f"{child.request.recording_id}.{account_id}.paper.jsonl"
                )
            )
            child.observers[account_id] = SharedPaperCaptureObserver(
                source=LiveBookDecisionSource(
                    child.request, inputs.requirement, history_capacity=1000
                ),
                books=books,
                journal=account,
                runtime=runtime,
                account_id=account_id,
                scenario=source.scenario,
                inputs=inputs,
                delivery_path=path,
                market_interval_us=source.market_interval_us,
                measurements=measurements,
            )

    def _supervise(self) -> bool:
        """Fence failed children and consume at most one delivery per source this pass."""
        consumed = False
        for definition in self.config.accounts:
            if definition.account_id in self.faulted_accounts:
                continue
            try:
                health = self.codec.decode_json(
                    Path(definition.socket_path).with_suffix(".health.json").read_bytes(),
                    _AccountHealth,
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
                self._fault_account(definition.account_id, "account_owner_lost", str(error))
        for name in tuple(sorted(self.active)):
            worker = self.workers[name]
            try:
                heartbeat = worker.health.snapshot()[HealthMetric.HEARTBEAT]
                has_stalled = heartbeat != 0 and time.monotonic_ns() - heartbeat > 2_000_000_000
            except TimeoutError:
                has_stalled = True
            if not worker.is_alive or has_stalled:
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
                if child.receiver.poll():
                    try:
                        payload = child.receiver.recv_bytes(16_777_216)
                    except EOFError:
                        if self.is_stopping and child.stop is not None:
                            child.pipe_drained = True
                            continue
                        raise
                    delivery = self.codec.decode_json(payload, _ReceivedSourceDelivery)
                    if delivery.book.position != child.received_count:
                        raise ValueError("source pipe delivery position differs from durable order")
                    child.received_count += 1
                    consumed = True
                    for account_id, observer in sorted(child.observers.items()):
                        if account_id in self.unavailable_accounts:
                            continue
                        if account_id in self.faulted_accounts:
                            # Fresh input may settle old obligations, but never evaluates policies.
                            observer.inputs = ServiceBookInputs(
                                (),
                                child.definition.freshness_us,
                                child.definition.market_interval_us,
                            )
                        try:
                            observer._observe_validated(delivery.record, delivery.book)
                        except PolicyProcessFailure as error:
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
                                self._fault_account(
                                    account_id, "unidentified_policy_failure", str(error)
                                )
                            else:
                                # Only this typed pre-commit failure proves that no
                                # cohort admission was attempted. Earlier matching
                                # receipts remain committed and are never replayed.
                                self._stop_instance(failed_worker, "worker_lost_during_decision")
                        except Exception as error:
                            failed = tuple(
                                instance
                                for instance in tuple(self.active)
                                if not self.workers[instance].is_alive
                            )
                            for instance in failed:
                                self._stop_instance(instance, "worker_lost_during_decision")
                            # A coincident worker death does not classify an account
                            # response or delivery failure as a rejected transaction.
                            self._fault_account(
                                account_id, "account_or_delivery_failure", str(error)
                            )
            except (OSError, EOFError, ValueError, TimeoutError) as error:
                self._close_source(child)
                self._fault_source(name, f"source_failure:{type(error).__name__}")
        return consumed

    def _stop_instance(self, name: str, reason: str) -> None:
        """Stop a policy before durable selective cancellation, preserving every other owner."""
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
        for account_id in sorted(
            {item.account_id for item in self.config.instances if item.source == name}
        ):
            self._fault_account(account_id, reason, name)

    def _fault_account(self, account_id: str, reason: str, detail: str) -> None:
        """Terminate dependents before attempting the independent durable account fault."""
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

    def _account_source_delivery(self, name: str, child: _SourceChild) -> None:
        """Retain constant-cost native and account counts for exact offline parity review."""
        capture_root = (
            self.root
            / "runs"
            / self.run_id
            / name
            / child.request.recording_id
            / child.request.recording_id
        )
        completed = (capture_root / "manifest.json").is_file()
        result_retained = (capture_root.parent / "source-result.json").is_file()
        durable_records: int | None = None
        cursor_sha256: str | None = None
        error_name: str | None = None
        try:
            cursor = self.codec.decode_json(
                (capture_root / "cursor.json").read_bytes(), CaptureCursor
            )
            cursor.__post_init__()
            if cursor.request_identity != child.request.identity:
                raise ValueError("source cursor differs from its launched request")
            durable_records, cursor_sha256 = cursor.records, cursor.sha256
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
        self.delivery_accounting[name] = {
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
        if not is_complete:
            self._record(
                "source_delivery_incomplete",
                name,
                f"durable={durable_records} pipe={child.received_count} "
                f"drained={child.pipe_drained} completed={completed} error={error_name}",
            )

    def _sample(self) -> None:
        """Keep protection reads on cadence while full reports run in their own process."""
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
        if self.diagnostics is not None:
            self.diagnostics.submit(latest_markets)

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

    def _control(self, listener: socket.socket) -> None:
        """Handle one bounded control request while the source loop retains scheduling ownership."""
        try:
            connection, _ = listener.accept()
        except BlockingIOError:
            return
        with connection:
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
                result = {"ok": True, "status": self.apply(control)}
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                result = {"ok": False, "error": str(error)}
            try:
                connection.sendall(self.codec.encode_json(result) + b"\n")
            except OSError:
                # A lost operator response must not replay a completed control.
                self.monitor.failures += 1
                self.monitor.last_error = "operator_response_lost"

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

    @staticmethod
    def _close_source(child: _SourceChild, *, deadline: float | None = None) -> None:
        """Fence a source before releasing its receiver or starting a replacement."""
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
            if observer.measurements is not None:
                try:
                    observer.measurements.close()
                except OSError as error:
                    failed.append(f"{account_id}:{type(error).__name__}")
        if failed:
            raise OSError("measurement close failed: " + ", ".join(failed))


def run_paper_services(
    configuration: PaperServiceConfiguration,
    owners: tuple[PaperOwner, ...],
    *,
    root: Path,
    control_socket: Path,
    transports: Mapping[str, CaptureTransport] | None = None,
    measurement_root: Path | None = None,
) -> dict[str, object]:
    """Compose one explicit bounded installed deployment and return its stopped service state."""
    services = PaperServices(
        configuration,
        owners,
        root=root,
        control_socket=control_socket,
        transports=transports,
        measurement_root=measurement_root,
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
