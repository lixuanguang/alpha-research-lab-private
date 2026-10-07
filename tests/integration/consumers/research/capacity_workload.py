"""Measure authored research capacity through real stores, Feast and study workers.

This is a synthetic diagnostic, never representative-input acceptance. Copy this
file outside the checkout and run with the installed research interpreter.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import json
import math
import os
import resource
import signal
import subprocess  # nosec B404  # [owner=research; rationale=bounded local Feast and diagnostic worker subprocesses; expires=2027-02-01]
import sys
import textwrap
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from importlib.util import find_spec
from pathlib import Path
from typing import Literal, Protocol, cast

# third party library imports
import psutil  # type: ignore[import-untyped]  # [owner=research; rationale=locked diagnostic dependency has no bundled typing stubs; expires=2027-02-01]

# project library imports
from applications.explore import (
    StudyComponents,
    StudyJobHandler,
    evaluate_study,
    schedule_study,
)
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.contracts import BookObservation, Level
from reference_data.instruments import InstrumentId
from research.experiments import AttemptStore, Fingerprint, TemporalSplit, TimeWindow
from research.features import (
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureEntity,
    FeatureMaterializer,
    FeatureObservation,
    FeatureSchema,
    FeatureStoreDefinition,
    OfflineFeatureAccess,
    OfflineFeatureBridge,
    OfflineFeatureDefinition,
    OfflineFeatureRequest,
    RunningMeanFeature,
    VersionedFeatureStore,
)
from research.observations import (
    InputRequirement,
    NamedObservation,
    NumericField,
    NumericHistorySource,
)
from research.studies import (
    DecisionStudy,
    LedgerCurveChart,
    NetReturnMetric,
    PublicationPolicy,
    StudyArtifact,
    StudyFold,
    StudyReportReader,
    StudyResult,
)
from risk import SpotLimits
from runtime import (
    ImplementationIdentity,
    JobQueue,
    JobRun,
    JobSpec,
    JobWorkerPool,
    WorkspaceBackup,
)
from serialization import DomainCodec
from simulation import (
    IntentMarket,
    IntentSimulationSpec,
    LimitExecutionConfig,
    LimitOrderExecution,
    SpotCosts,
    SpotFeeModel,
)
from strategies import DecisionContext, DecisionTransition, OrderIntent

_NO_SUCH_PROCESS = cast(type[Exception], psutil.NoSuchProcess)  # type: ignore[misc]  # [owner=research; rationale=untyped psutil process-exit exception is handled at sampling boundary; expires=2027-02-01]
_ACCESS_DENIED = cast(type[Exception], psutil.AccessDenied)  # type: ignore[misc]  # [owner=research; rationale=untyped psutil access exception is recorded at sampling boundary; expires=2027-02-01]

_OFFLINE_FIXTURE_SOURCE = textwrap.dedent(
    """
    import json
    import sys
    from datetime import timedelta
    from pathlib import Path

    import pandas as pd
    from feast import Entity, FeatureStore, FeatureView, Field, FileSource
    from feast.types import String, ZonedTimestamp
    from feast.value_type import ValueType

    repository = Path(sys.argv[1]).resolve()
    rows_path = Path(sys.argv[2]).resolve()
    repository.mkdir(parents=True)
    (repository / "data").mkdir()
    (repository / "feature_store.yaml").write_text(
        "project: research_capacity_diagnostic\\n"
        "provider: local\\n"
        "registry: data/registry.db\\n"
        "online_store:\\n"
        "  type: sqlite\\n"
        "  path: data/online.db\\n",
        encoding="utf-8",
    )
    frame = pd.DataFrame(json.loads(rows_path.read_text(encoding="utf-8")))
    for name in ("feature_event_timestamp", "created_timestamp"):
        frame[name] = pd.to_datetime(frame[name], utc=True, format="mixed")
    source_path = repository / "data" / "features.parquet"
    frame.to_parquet(source_path, index=False)
    entity = Entity(name="instrument", join_keys=["instrument"], value_type=ValueType.STRING)
    source = FileSource(
        name="capacity_mean_source",
        path=str(source_path),
        event_timestamp_column="feature_event_timestamp",
        created_timestamp_column="created_timestamp",
        timestamp_field="feature_event_timestamp",
    )
    view = FeatureView(
        name="running_mean",
        entities=[entity],
        ttl=timedelta(minutes=1),
        schema=[
            Field(name="running_mean", dtype=String),
            Field(name="feature_event_timestamp", dtype=ZonedTimestamp),
            Field(name="created_timestamp", dtype=ZonedTimestamp),
        ],
        source=source,
        online=False,
        offline=True,
    )
    FeatureStore(repo_path=str(repository)).apply([entity, source, view])
    """
).strip()


class _MemorySample(Protocol):
    """Describe the single measured resident-memory field from the OS adapter."""

    rss: int


class _CpuSample(Protocol):
    """Describe process user and kernel seconds from the OS adapter."""

    user: float
    system: float


class _SampledProcess(Protocol):
    """Narrow the optional psutil surface used by this diagnostic."""

    pid: int

    def memory_info(self) -> _MemorySample:
        """Read current resident bytes."""
        ...

    def cpu_times(self) -> _CpuSample:
        """Read cumulative user and kernel CPU seconds."""
        ...

    def create_time(self) -> float:
        """Read the process creation clock to disambiguate reused PID values."""
        ...

    def children(self, *, recursive: bool) -> list[_SampledProcess]:
        """Find every currently visible descendant for process-tree sampling."""
        ...


class _Measurements:
    """Retain flushed individual samples and resource observations even after failure."""

    def __init__(self, root: Path, implementation: str, *, sample_resources: bool = True) -> None:
        """Bind a fresh absolute output and an already verified implementation identity."""
        self.root = root
        self.samples: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self.started = time.perf_counter()
        self.implementation = implementation
        self.input_configuration: dict[str, object] = {}
        # A native consumer reuses this measurement and names its own scope and bytes.
        self.scope = "synthetic-diagnostic"
        self.consumer = Path(__file__)
        self._tracked_pids = {os.getpid()}
        self._stop = threading.Event()
        self._resource_samples = 0
        self._recursive_enumeration_failures = 0
        self._process_read_failures = 0
        self._peak_sampled_rss_bytes = 0
        self._peak_sampled_logical_cpus = 0.0
        self._peak_system_cpu_percent = 0.0
        self._prior_process_cpu: dict[tuple[int, float], float] = {}
        self._sampled_cpu_seconds = 0.0
        self._prior_at: float | None = None
        self._sampler_error: str | None = None
        self._growth: list[dict[str, object]] = []
        self._sampler = (
            threading.Thread(target=self._sample_resources, daemon=True)
            if sample_resources
            else None
        )
        if self._sampler is not None:
            self._sampler.start()

    @classmethod
    def create(cls, root: Path) -> _Measurements:
        """Reserve an exclusive attempt and verify installed bytes before timing work."""
        root.mkdir(parents=True, exist_ok=False)
        return cls(root.resolve(), ImplementationIdentity.sha256())

    def record(self, stage: str, started: float, **facts: object) -> None:
        """Append elapsed seconds and boundary facts without replacing earlier samples."""
        elapsed = time.perf_counter() - started
        with self._lock:
            self.samples.setdefault(stage, []).append(elapsed)
            with (self.root / "samples.jsonl").open("ab") as output:
                output.write(
                    DomainCodec().encode_json(
                        dict(
                            stage=stage,
                            seconds=elapsed,
                            started_offset_seconds=started - self.started,
                            **facts,
                        )
                    )
                    + b"\n"
                )

    def pin_inputs(self, workload: _Workload, worker_python: Path) -> None:
        """Retain authored source, feature and SDK configuration identities."""
        worker_lock = worker_python.parents[2] / "uv.lock"
        self.input_configuration = {
            "authored_source_sha256": workload.source_hash,
            "source_identity": workload.source.identity,
            "feature_schema_identity": workload.kernel.schema.identity,
            "feature_definition_identity": workload.definition.identity,
            "entities": workload.entities,
            "decisions_per_entity": workload.count,
            "decision_start_utc": workload.decisions[0],
            "decision_end_utc_exclusive": workload.end,
            "worker_python": str(worker_python),
            "worker_lock_sha256": (
                hashlib.sha256(worker_lock.read_bytes()).hexdigest()
                if worker_lock.is_file()
                else None
            ),
        }

    def track(self, pid: int) -> None:
        """Include one owned subprocess in concurrent parent and child resource samples."""
        with self._lock:
            self._tracked_pids.add(pid)

    def untrack(self, pid: int) -> None:
        """Remove an exited owned subprocess after its final resource observation."""
        with self._lock:
            self._tracked_pids.discard(pid)

    def checkpoint(self, stage: str, root: Path | None = None) -> None:
        """Retain actual logical and allocated output growth at a completed stage."""
        measured_root = root if root is not None else self.root
        files = tuple(path for path in measured_root.rglob("*") if path.is_file())
        growth = {
            "stage": stage,
            "root": str(measured_root),
            "seconds_since_start": time.perf_counter() - self.started,
            "file_count": len(files),
            "logical_bytes": sum(path.stat().st_size for path in files),
            "allocated_bytes": sum(path.stat().st_blocks * 512 for path in files),
        }
        self._growth.append(growth)
        with (self.root / "growth.jsonl").open("ab") as output:
            output.write(DomainCodec().encode_json(growth) + b"\n")

    def _sample_resources(self) -> None:
        """Sample the owned recursive process tree and retain any sampler failure."""
        try:
            while not self._stop.is_set():
                self._sample_once()
                self._stop.wait(0.2)
        except Exception as error:
            self._sampler_error = f"{type(error).__name__}: {error}"
            self._stop.set()

    def _sample_once(self) -> None:
        """Compute CPU deltas only across stable PID and creation-time identities."""
        with self._lock:
            pids = tuple(self._tracked_pids)
        at = time.perf_counter()
        processes: dict[int, _SampledProcess] = {}
        for pid in pids:
            try:
                process = cast(_SampledProcess, psutil.Process(pid))  # type: ignore[misc]  # [owner=research; rationale=untyped psutil constructor confined to typed resource sampling protocol; expires=2027-02-01]
                processes[pid] = process
                for descendant in process.children(recursive=True):
                    processes[descendant.pid] = descendant
            except _NO_SUCH_PROCESS:
                continue
            except OSError, _ACCESS_DENIED:
                self._recursive_enumeration_failures += 1
        rss, live_cpu_seconds, cpu_delta_seconds = 0, 0.0, 0.0
        current_cpu: dict[tuple[int, float], float] = {}
        process_samples: list[dict[str, object]] = []
        for process in processes.values():
            try:
                identity = (process.pid, process.create_time())
                resident_bytes = process.memory_info().rss
                clocks = process.cpu_times()
                cumulative = clocks.user + clocks.system
            except _NO_SUCH_PROCESS:
                continue
            except OSError, _ACCESS_DENIED:
                self._process_read_failures += 1
                continue
            prior = self._prior_process_cpu.get(identity)
            delta = max(0.0, cumulative - prior) if prior is not None else 0.0
            current_cpu[identity] = cumulative
            rss += resident_bytes
            live_cpu_seconds += cumulative
            cpu_delta_seconds += delta
            process_samples.append(
                {
                    "pid": identity[0],
                    "created_at_epoch_seconds": identity[1],
                    "rss_bytes": resident_bytes,
                    "cpu_seconds": cumulative,
                    "cpu_delta_seconds": delta,
                }
            )
        logical_cpus = (
            cpu_delta_seconds / (at - self._prior_at)
            if self._prior_at is not None and at > self._prior_at
            else 0.0
        )
        system_cpu_percent = cast(float, psutil.cpu_percent(interval=None))  # type: ignore[misc]  # [owner=research; rationale=untyped locked psutil system CPU sampler is confined to diagnostics; expires=2027-02-01]
        self._prior_process_cpu, self._prior_at = current_cpu, at
        self._sampled_cpu_seconds += cpu_delta_seconds
        self._resource_samples += 1
        self._peak_sampled_rss_bytes = max(self._peak_sampled_rss_bytes, rss)
        self._peak_sampled_logical_cpus = max(self._peak_sampled_logical_cpus, logical_cpus)
        self._peak_system_cpu_percent = max(self._peak_system_cpu_percent, system_cpu_percent)
        sample = {
            "seconds_since_start": at - self.started,
            "tracked_processes": len(process_samples),
            "rss_bytes": rss,
            "live_cumulative_cpu_seconds": live_cpu_seconds,
            "sampled_cpu_delta_seconds": cpu_delta_seconds,
            "sampled_cpu_seconds_cumulative": self._sampled_cpu_seconds,
            "sampled_logical_cpus": logical_cpus,
            "system_cpu_percent": system_cpu_percent,
            "processes": process_samples,
        }
        with (self.root / "resources.jsonl").open("ab") as output:
            output.write(DomainCodec().encode_json(sample) + b"\n")

    def finish(self, status: str, reason: str = "") -> None:
        """Report empirical nearest-rank percentiles only with at least one thousand samples."""
        completed_requested = status == "complete"
        self._stop.set()
        if self._sampler is not None:
            self._sampler.join(timeout=5)
            if self._sampler.is_alive():
                self._sampler_error = "resource sampler did not stop within five seconds"
        if self._sampler_error is not None:
            status = "failed"
            reason = f"resource sampler failed: {self._sampler_error}"
        self.checkpoint("finish")
        stages: dict[str, object] = {}
        for name, values in self.samples.items():
            ordered = sorted(values)
            stages[name] = {
                "count": len(values),
                "total_seconds": sum(values),
                "min_seconds": min(values),
                "max_seconds": max(values),
                "percentiles_seconds": {
                    str(p): ordered[math.ceil(p / 100 * len(ordered)) - 1] for p in (50, 95, 99)
                }
                if len(values) >= 1000
                else None,
            }
        own = resource.getrusage(resource.RUSAGE_SELF)
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        scale = 1 if sys.platform == "darwin" else 1024
        payload = {
            "scope": self.scope,
            "status": status,
            "reason": reason,
            "implementation": self.implementation,
            "input_configuration": self.input_configuration,
            "consumer_sha256": hashlib.sha256(self.consumer.read_bytes()).hexdigest(),
            "elapsed_seconds": time.perf_counter() - self.started,
            "stages": stages,
            "cpu_user_seconds": own.ru_utime + child.ru_utime,
            "cpu_system_seconds": own.ru_stime + child.ru_stime,
            "self_peak_rss_bytes": own.ru_maxrss * scale,
            "child_peak_rss_bytes": child.ru_maxrss * scale,
            "sampled_peak_process_tree_rss_bytes": self._peak_sampled_rss_bytes,
            "sampled_peak_logical_cpus": self._peak_sampled_logical_cpus,
            "sampled_peak_system_cpu_percent": self._peak_system_cpu_percent,
            "sampled_cpu_seconds": self._sampled_cpu_seconds,
            "resource_sample_count": self._resource_samples,
            "target_resource_sample_interval_seconds": 0.2,
            "resource_scope": (
                "sampled recursive process tree"
                if self._recursive_enumeration_failures == 0
                else "recursive enumeration partly unavailable; registered processes sampled"
            ),
            "recursive_enumeration_failures": self._recursive_enumeration_failures,
            "process_read_failures": self._process_read_failures,
            "sampler_error": self._sampler_error,
            "logical_disk_growth": self._growth,
            "disk_bytes": sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file()),
            "disk_bytes_scope": "measured before writing measurement.json",
            "allocated_bytes_scope": (
                "file st_blocks times 512; APFS shared extents make summed roots non-additive"
            ),
            "os_block_io": (
                "Darwin ru_inblock/ru_oublock are counts, not physical byte measurements"
            ),
            "input_block_operations": own.ru_inblock + child.ru_inblock,
            "output_block_operations": own.ru_oublock + child.ru_oublock,
            "cache": (
                "fresh application/store; OS page cache uncontrolled; PIT queries warm; "
                "each Feast request uses a fresh SDK subprocess over pinned source bytes"
            ),
            "representative_acceptance": False,
        }
        (self.root / "measurement.json").write_bytes(DomainCodec().encode_json(payload))
        print(DomainCodec().encode_json(payload).decode(), flush=True)
        if self._sampler_error is not None and completed_requested:
            raise RuntimeError(reason)


class _TrackedProcess:
    """Run one owned local child while the diagnostic samples its live resources."""

    def __init__(self, measurements: _Measurements) -> None:
        """Bind the process sampler shared by Feast and fault injection."""
        self.measurements = measurements

    def start(self, command: tuple[str, ...], *, cwd: Path) -> subprocess.Popen[bytes]:
        """Start an explicit absolute command with captured finite output."""
        if not Path(command[0]).is_absolute():
            raise ValueError("tracked subprocess requires an absolute executable")
        started = time.perf_counter()
        process = subprocess.Popen(  # nosec B603  # [owner=research; rationale=explicit installed local interpreter argv without shell; expires=2027-02-01]
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.measurements.track(process.pid)
        self.measurements.record("subprocess-spawn", started, pid=process.pid)
        return process

    def complete(
        self, process: subprocess.Popen[bytes], *, payload: bytes | None, timeout: float
    ) -> bytes:
        """Collect a bounded child result and report its process failure."""
        try:
            stdout, stderr = process.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate()
            raise TimeoutError("tracked local subprocess exceeded its timeout") from error
        finally:
            self.measurements.untrack(process.pid)
        exit_code = process.poll()
        if exit_code != 0:
            raise RuntimeError(
                f"local subprocess exited {exit_code}: "
                + stderr[:2_048].decode("utf-8", errors="replace")
            )
        if len(stdout) > 16 * 1024 * 1024:
            raise ValueError("local subprocess response exceeds the Feast wire budget")
        return stdout


class _TrackedFeastWorker:
    """Call the installed Feast SDK command with measured subprocess ownership."""

    def __init__(
        self,
        runner: _TrackedProcess,
        command: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float,
        operation: str,
    ) -> None:
        """Bind the same explicit worker argv used by the standard Feast bridge."""
        self.runner, self.command, self.cwd, self.timeout, self.operation = (
            runner,
            command,
            cwd,
            timeout,
            operation,
        )

    def __call__(self, request: bytes) -> bytes:
        """Return the bounded SDK response after sampling the actual worker process."""
        if not request or len(request) > 16 * 1024 * 1024:
            raise ValueError("Feast request exceeds its bounded wire budget")
        operation = self.operation
        if self.operation == "online-boundary":
            operation = (
                "online-generation"
                if b'"feast-materialize-request"' in request
                else "online-retrieval"
            )
        started = time.perf_counter()
        result = self.runner.complete(
            self.runner.start(self.command, cwd=self.cwd), payload=request, timeout=self.timeout
        )
        self.runner.measurements.record(
            f"feast-sdk-{operation}",
            started,
            request_bytes=len(request),
            response_bytes=len(result),
        )
        return result


class _Market:
    """Supply explicit authored minute books with independent exact trade economics."""

    def __init__(self, entity: str, decisions: tuple[datetime, ...]) -> None:
        """Pin the synthetic source clocks and entity; no original receipt clocks are claimed."""
        self.entity, self.decisions = entity, decisions
        self.identity = hashlib.sha256(
            DomainCodec().encode_json((entity, decisions, "constant-book"))
        ).hexdigest()

    def read(self, window: TimeWindow) -> tuple[IntentMarket, ...]:
        """Provide a fresh book one second after each decision to exercise delayed fills."""
        rows: list[IntentMarket] = []
        clocks = tuple(
            sorted(
                {
                    window.start,
                    *self.decisions,
                    *(at + timedelta(seconds=1) for at in self.decisions),
                    window.end,
                }
            )
        )
        for index, at in enumerate(clocks):
            if not window.start <= at <= window.end:
                continue
            identity = hashlib.sha256(DomainCodec().encode_json((self.identity, at))).hexdigest()
            rows.append(
                IntentMarket(
                    identity=identity,
                    source_identity=self.identity,
                    instrument=self.entity,
                    channel="l2",
                    source_at=at,
                    known_at=at,
                    book=BookObservation(
                        position=index,
                        epoch=None,
                        received_ns=None,
                        source_time=str(int(at.timestamp()) * 1000),
                        sequence=None,
                        outcome="snapshot",
                        status="degraded",
                        reason="authored capacity diagnostic",
                        state_identity=identity,
                        bids=(
                            (
                                Decimal("99.01" if at.second == 1 else "99"),
                                Level(Decimal("100"), 1),
                            ),
                        ),
                        asks=(
                            (
                                Decimal("100.99" if at.second == 1 else "101"),
                                Level(Decimal("100"), 1),
                            ),
                        ),
                    ),
                )
            )
        return tuple(rows)


class _RoundTripPolicy:
    """Enter and exit once, with explicit limits that allow modeled adverse slippage."""

    def __init__(
        self, field: NumericField, quantity: Quantity, currency: Currency, count: int, entry: int
    ) -> None:
        """Bind the authored grid and isolated units; intermediate asks never cross."""
        self.field, self.quantity, self.currency = field, quantity, currency
        self.count, self.entry = count, entry
        self.identity = hashlib.sha256(
            DomainCodec().encode_json(
                ("capacity-round-trip", field, quantity, currency, count, entry)
            )
        ).hexdigest()

    @property
    def output(self) -> Literal["order"]:
        """Declare explicit bounded orders rather than inferring a limit from the touch."""
        return "order"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require the measured running-mean feature without a fitted model."""
        if fields != (self.field,) or prediction is not None:
            raise ValueError("capacity policy signature differs")

    def initial_state(self) -> bytes:
        """Start an independent per-trial decision counter."""
        return b"0"

    def validate_state(self, state: bytes) -> None:
        """Reject counters outside the declared finite sample."""
        if not state.isdigit() or not 0 <= int(state) <= self.count:
            raise ValueError("invalid capacity policy counter")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Use then-known positive entry and zero terminal signal for the exact round trip."""
        self.validate_state(state)
        index = int(state)
        signal = context.features.values[0]
        if signal is None:
            raise ValueError("capacity policy cannot use missing signal")
        buying = index <= self.entry
        limit = (
            "102" if index == self.entry else "98" if buying or index == self.count - 1 else "102"
        )
        if index == self.entry and int(signal.numerator) <= 0:
            raise ValueError("authored entry signal must be positive")
        if index == self.count - 1 and int(signal.numerator) != 0:
            raise ValueError("authored terminal signal must be zero")
        return DecisionTransition(
            intent=OrderIntent(
                side="buy" if buying else "sell",
                quantity=self.quantity,
                limit=Price(
                    value=Decimal(limit), currency=self.currency, per=self.quantity.dimension
                ),
                time_in_force="ioc" if index in (self.entry, self.count - 1) else "post-only",
            ),
            state=str(index + 1).encode(),
        )


class _TimedHandler:
    """Measure actual concurrent studies and retain an injected lost acknowledgement."""

    def __init__(self, handler: StudyJobHandler, measurements: _Measurements) -> None:
        """Bind the real handler with a thread-safe active-worker counter."""
        self.handler, self.measurements = handler, measurements
        self.active = self.peak = 0
        self._lock = threading.Lock()
        self._lost = False

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Allow durable completion before losing one acknowledgement, then recover by job key."""
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        started = time.perf_counter()
        try:
            result = self.handler.execute(spec, run)
            with self._lock:
                if spec.job_id == "trial-1-1" and not self._lost:
                    self._lost = True
                    self.measurements.record("injected-ack-loss", started, job=spec.job_id)
                    raise OSError("injected response loss after durable study completion")
            return result
        finally:
            self.measurements.record("study-worker", started, job=spec.job_id)
            with self._lock:
                self.active -= 1


class _Workload:
    """Compose immutable authored inputs through the installed public research APIs."""

    def __init__(
        self,
        measurements: _Measurements,
        count: int,
        bridge: FeastServingBridge,
        artifact: StudyArtifact,
        runner: _TrackedProcess,
        worker_python: Path,
        offline_command: tuple[str, ...],
    ) -> None:
        """Bind the declared minute grid, two distinct entities and exact running means."""
        self.m = measurements
        self.count = count
        self.artifact = artifact
        self.bridge = bridge
        self.runner = runner
        self.worker_python = worker_python
        self.offline_command = offline_command
        self.entities = (
            "4476df8e-6342-4417-839e-e41b88f41446",
            "5ff4f1a3-f2e1-5662-b60f-70e24d2ad521",
        )
        start = datetime(2026, 9, 20, tzinfo=UTC)
        self.decisions = tuple(start + timedelta(minutes=i) for i in range(count))
        self.end = start + timedelta(minutes=count)
        self.field = NumericField(name="signal", units="dimensionless")
        requirement = InputRequirement(
            name="authored-signal",
            family="non-book",
            clock="authored",
            field=self.field,
            max_age_us=0,
        )
        rows = tuple(
            NamedObservation(
                input=requirement,
                entity=entity,
                event_at=at,
                available_at=at,
                value=ExactRatio(numerator="1" if i < count // 2 else "-1", denominator="1"),
                reason="synthetic capacity input",
                lineage=f"authored:{entity}:{i}",
            )
            for entity in self.entities
            for i, at in enumerate(self.decisions)
        )
        self.payload = DomainCodec().encode_json(rows)
        self.source_hash = hashlib.sha256(self.payload).hexdigest()
        self.source = NumericHistorySource(rows, (requirement,))
        self.kernel = RunningMeanFeature(
            FeatureSchema(
                implementation="running-mean",
                inputs=(requirement,),
                outputs=(self.field,),
                parameters=(),
                mode="incremental",
                ttl_us=60_000_000,
            )
        )
        self.definition = FeatureStoreDefinition(
            name="capacity-mean",
            entity_type="instrument",
            schema=self.kernel.schema,
            instance="capacity-stream",
        )

    def features(self) -> None:
        """Measure materialization, every PIT cell, and restart without advancing state twice."""
        store = VersionedFeatureStore.open(self.m.root / "features" / "history.sqlite3")
        started = time.perf_counter()
        result = FeatureMaterializer().materialize(
            store,
            self.definition,
            source=self.source,
            kernel=self.kernel,
            instance="capacity-stream",
            entities=self.entities,
            decisions=self.decisions,
            source_version=self.source.identity,
            source_sha256=self.source_hash,
            dataset_version=self.source_hash,
            dataset_sha256=self.source_hash,
            version="complete",
            bridge=self.bridge,
            serving_root=self.m.root / "serving",
        )
        self.m.record(
            "feature-materialization-with-feast",
            started,
            rows=self.count * 2,
            identity=result.identity,
        )
        offline_rows: list[tuple[str, datetime, ExactRatio, datetime, datetime]] = []
        for entity in self.entities:
            total = 0
            for i, at in enumerate(self.decisions):
                total += 1 if i < self.count // 2 else -1
                started = time.perf_counter()
                value = store.retrieve_offline(self.definition, entity, at)
                self.m.record("pit-retrieval", started)
                assert value.feature is not None
                assert value.feature.vector.values == (
                    ExactRatio.from_fraction(Fraction(total, i + 1)),
                )
                vector = value.feature.vector
                ratio = vector.values[0]
                assert ratio is not None
                offline_rows.append((entity, at, ratio, vector.decision_at, vector.available_at))
        started = time.perf_counter()
        reopened = VersionedFeatureStore.open(self.m.root / "features" / "history.sqlite3")
        assert (
            reopened.retrieve_online(self.definition, self.entities[0], self.decisions[-1]).feature
            is not None
        )
        self.m.record("feature-reopen", started)
        self.m.checkpoint("durable-features-and-online-feast")
        self.offline_features(tuple(offline_rows))

    def offline_features(
        self, rows: tuple[tuple[str, datetime, ExactRatio, datetime, datetime], ...]
    ) -> None:
        """Run actual bounded Feast offline chunks and reconcile each exact PIT cell."""
        root = self.m.root / "offline-feast"
        root.mkdir()
        repository = root / "repository"
        source_rows = [
            {
                "instrument": entity,
                "feature_event_timestamp": event_at.isoformat(),
                "created_timestamp": available_at.isoformat(),
                "running_mean": f"{ratio.numerator}/{ratio.denominator}",
            }
            for entity, _, ratio, event_at, available_at in rows
        ]
        rows_path = root / "rows.json"
        rows_path.write_text(json.dumps(source_rows, separators=(",", ":")), encoding="utf-8")
        author = root / "author.py"
        author.write_text(_OFFLINE_FIXTURE_SOURCE + "\n", encoding="utf-8")
        started = time.perf_counter()
        self.runner.complete(
            self.runner.start(
                (str(self.worker_python), "-I", str(author), str(repository), str(rows_path)),
                cwd=root,
            ),
            payload=None,
            timeout=120,
        )
        source = repository / "data" / "features.parquet"
        registry = repository / "data" / "registry.db"
        definition_path = repository / "feature_store.yaml"
        if not all(path.is_file() for path in (source, registry, definition_path)):
            raise AssertionError("installed Feast did not retain the offline fixture")
        self.m.record(
            "feast-offline-fixture-construction",
            started,
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            source_bytes=source.stat().st_size,
            registry_sha256=hashlib.sha256(registry.read_bytes()).hexdigest(),
        )
        definition = OfflineFeatureDefinition(
            feature_name="running_mean",
            feature_ref="running_mean:running_mean",
            entity_type="instrument",
            units="dimensionless",
            ttl_us=60_000_000,
            sdk_version="0.66.0",
            definition_version="capacity-running-mean",
            definition_bytes=definition_path.read_bytes(),
            registry_bytes=registry.read_bytes(),
            source_version="authored-capacity-feature",
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            join_key="instrument",
            repository_path=str(repository),
        )
        access = OfflineFeatureAccess(
            OfflineFeatureBridge(
                _TrackedFeastWorker(
                    self.runner,
                    self.offline_command,
                    cwd=repository,
                    timeout=120,
                    operation="offline-retrieval",
                )
            )
        )
        indexed = {
            (entity, at): (ratio, event_at, available_at)
            for entity, at, ratio, event_at, available_at in rows
        }
        chunk_width = max(1, min(2048, self.count // 3))
        chunks = 0
        reconciled = 0
        for offset in range(0, self.count, chunk_width):
            decisions = self.decisions[offset : offset + chunk_width]
            request = OfflineFeatureRequest(
                definition=definition,
                entities=tuple(
                    FeatureEntity(entity_type="instrument", entity_key=entity)
                    for entity in self.entities
                ),
                decisions=decisions,
            )
            reference = tuple(
                FeatureObservation(
                    definition_identity=definition.identity,
                    source_version=definition.source_version,
                    source_sha256=definition.source_sha256,
                    feature_name=definition.feature_name,
                    entity_type=definition.entity_type,
                    entity_key=entity,
                    decision_at=at,
                    event_at=indexed[(entity, at)][1],
                    available_at=indexed[(entity, at)][2],
                    ttl_us=definition.ttl_us,
                    units=definition.units,
                    value=(
                        f"{indexed[(entity, at)][0].numerator}/"
                        f"{indexed[(entity, at)][0].denominator}"
                    ),
                )
                for entity in self.entities
                for at in decisions
            )
            started = time.perf_counter()
            comparison = access.compare(request, reference)
            if comparison.mismatches or len(comparison.matches) != request.expected_rows:
                raise AssertionError("Feast offline chunk differs from every durable PIT cell")
            self.m.record(
                "feast-offline-chunk",
                started,
                chunk=chunks,
                cells=request.expected_rows,
                request_sha256=request.identity,
            )
            chunks += 1
            reconciled += request.expected_rows
        if chunks < 3 or reconciled != self.count * len(self.entities):
            raise AssertionError("offline Feast did not cover the declared grid in three chunks")
        self.m.checkpoint("offline-feast")

    def _study_specs(self) -> tuple[tuple[DecisionStudy, ...], dict[str, StudyComponents]]:
        """Build identical immutable trial bindings for parent and interrupted child."""
        metric, chart = NetReturnMetric(), LedgerCurveChart()
        currency = Currency(code="USDT", minor_unit=Decimal("0.01"))
        studies: list[DecisionStudy] = []
        bindings: dict[str, StudyComponents] = {}
        for entity_index, entity in enumerate(self.entities):
            dimension = Dimension(
                instrument_id=InstrumentId.from_canonical_text(entity), kind=QuantityKind.BASE_UNIT
            )
            quantity = Quantity(value=Decimal(1), dimension=dimension)
            price = Price(value=Decimal("0.01"), currency=currency, per=dimension)
            market = _Market(entity, self.decisions)
            execution = LimitOrderExecution(
                LimitExecutionConfig(
                    entry_delay_us=1_000_000,
                    cancel_delay_us=0,
                    lifetime_us=2_000_000,
                    max_book_age_us=120_000_000,
                    take_fraction=Decimal(1),
                    queue_ahead_fraction=Decimal(1),
                )
            )
            fees = SpotCosts(adverse=price, fee_rate=Decimal("0.002"), rounding="half_even")
            costs = SpotFeeModel(
                maker=SpotCosts(
                    adverse=Price(value=Decimal(0), currency=currency, per=dimension),
                    fee_rate=Decimal("0.002"),
                    rounding="half_even",
                ),
                taker=fees,
            )
            split = TemporalSplit(
                training=None,
                validation=TimeWindow(start=self.decisions[0], end=self.end),
                holdout=TimeWindow(
                    start=self.end + timedelta(days=1), end=self.end + timedelta(days=2)
                ),
                samples=(),
                fit_mode="none",
                fit_cutoff=None,
                embargo_us=0,
                rationale="authored capacity diagnostic; holdout not consumed",
            )
            fold = StudyFold(
                name="capacity-validation",
                split=split,
                training_decisions=(),
                decisions=self.decisions,
                evaluated_as_of=self.end,
            )
            for trial in range(2):
                policy = _RoundTripPolicy(self.field, quantity, currency, self.count, trial)
                components = StudyComponents(
                    source=self.source,
                    market=market,
                    feature=self.kernel,
                    policy=policy,
                    execution=execution,
                    costs=costs,
                    capabilities=(
                        "product:spot",
                        "calendar:continuous-utc",
                        "intent:order",
                        "feature:incremental",
                        "input:non-book",
                    ),
                    metrics=(metric,),
                    charts=(chart,),
                    artifacts=(self.artifact,),
                )
                study = DecisionStudy(
                    family=f"capacity-{entity_index}",
                    source_identity=self.source.identity,
                    feature_identity=self.kernel.schema.identity,
                    policy_identity=policy.identity,
                    model_identity=None,
                    transform_identity=None,
                    label_identity=None,
                    output="order",
                    calendar="continuous-utc",
                    required_capabilities=(),
                    folds=(fold,),
                    partition="validation",
                    economics=IntentSimulationSpec(
                        instance=f"capacity-{entity_index}",
                        entity=entity,
                        source_identity=market.identity,
                        start=self.decisions[0],
                        end=self.end,
                        initial_cash=Money(value=Decimal("1000"), currency=currency),
                        limits=SpotLimits(
                            maximum=quantity,
                            lot=quantity,
                            tick=price,
                            product="spot",
                            specification_identity="a" * 64,
                            minimum_order=quantity,
                        ),
                        execution_identity=execution.identity,
                        cost_identity=costs.identity,
                    ),
                    metrics=(metric.identity,),
                    charts=(chart.identity,),
                    extensions=(self.artifact.fingerprint,),
                )
                studies.append(study)
                bindings[study.identity] = components
        return tuple(studies), bindings

    def interrupted_worker(self) -> None:
        """Run the first queued trial in an owned child eligible for forced termination."""
        _, bindings = self._study_specs()
        queue = JobQueue(self.m.root / "jobs")
        handler = StudyJobHandler(bindings, self.m.root / "studies")
        pool = JobWorkerPool(
            queue,
            {"decision-study": handler},
            max_workers=1,
            implementation_sha256=ImplementationIdentity.sha256(),
            environment_sha256=StudyJobHandler.environment_sha256(),
        )
        pool.run_until_idle()

    def _interrupt_active_trial(self, family: str) -> None:
        """Kill only this diagnostic's child after a durable study start is observed."""
        command = (
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--output",
            str(self.m.root),
            "--worker-python",
            str(self.worker_python),
            "--decisions",
            str(self.count),
            "--action",
            "interrupted-worker",
        )
        process = self.runner.start(command, cwd=self.m.root.parent)
        family_root = self.m.root / "studies" / hashlib.sha256(family.encode()).hexdigest()
        started = time.perf_counter()
        try:
            while time.perf_counter() - started < 30:
                if tuple(family_root.glob("*/artifact-job-key.bin")):
                    break
                if process.poll() is not None:
                    raise AssertionError("diagnostic child exited before its study attempt started")
                time.sleep(0.02)
            else:
                raise TimeoutError("diagnostic child did not begin a durable study attempt")
            if process.poll() is not None:
                raise AssertionError("diagnostic child completed before process interruption")
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
            exit_code = process.poll()
            if exit_code != -signal.SIGKILL:
                raise AssertionError("diagnostic child was not terminated by SIGKILL")
            (self.m.root / "interrupted-child.json").write_bytes(
                DomainCodec().encode_json(
                    {
                        "exit_code": exit_code,
                        "pid": process.pid,
                        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                    }
                )
            )
            self.m.record("injected-process-kill", started, job="trial-0-0")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
            self.m.untrack(process.pid)

    def studies(self) -> None:
        """Run concurrent families, retaining reports and independent net-loss oracles."""
        studies, bindings = self._study_specs()
        queue = JobQueue(self.m.root / "jobs")
        handler = _TimedHandler(StudyJobHandler(bindings, self.m.root / "studies"), self.m)
        pool = JobWorkerPool(
            queue,
            {"decision-study": handler},
            max_workers=2,
            implementation_sha256=ImplementationIdentity.sha256(),
            environment_sha256=StudyJobHandler.environment_sha256(),
        )
        for trial in range(2):
            for entity_index in range(2):
                study = studies[entity_index * 2 + trial]
                schedule_study(
                    queue,
                    study,
                    job_id=f"trial-{entity_index}-{trial}",
                    run_at=self.decisions[0],
                    publication=PublicationPolicy(mode="local"),
                    retry_delay_seconds=0,
                )
            if trial == 0:
                self._interrupt_active_trial(studies[0].family)
                interrupted = queue.read("trial-0-0")
                assert interrupted.status == "running" and interrupted.attempts == 1
                interrupted_family = hashlib.sha256(studies[0].family.encode()).hexdigest()
                interrupted_history = AttemptStore(
                    self.m.root / "studies" / interrupted_family
                ).histories()
                assert len(interrupted_history) == 1
                assert interrupted_history[0].status == "incomplete"
            started = time.perf_counter()
            pool.run_until_idle()
            if trial == 0:
                self.m.record("process-kill-recovery", started, job="trial-0-0")
            self.m.record("two-worker-wave", started, peak_active_workers=handler.peak)
            for entity_index in range(2):
                state = queue.read(f"trial-{entity_index}-{trial}")
                assert state.status == "completed", state.last_error
        recovered = queue.read("trial-0-0")
        assert recovered.attempts == 2 and recovered.last_error is None
        assert handler.peak == 2
        interrupted_family = hashlib.sha256(studies[0].family.encode()).hexdigest()
        interrupted_store = AttemptStore(self.m.root / "studies" / interrupted_family)
        histories = interrupted_store.histories()
        assert len(histories) == 3
        assert sum(history.status == "abandoned" for history in histories) == 1
        assert sum(history.status == "completed" for history in histories) == 2
        recovered_history = next(
            history
            for history in histories
            if history.status == "completed"
            and interrupted_store.artifact(history.start.attempt_id, "job-key") == b"trial-0-0"
        )
        started = time.perf_counter()
        reference = evaluate_study(
            studies[0],
            components=bindings[studies[0].identity],
            attempts=self.m.root / "uninterrupted-control",
            publication=PublicationPolicy(mode="local"),
        )
        control_store = AttemptStore(self.m.root / "uninterrupted-control")
        recovered_result = StudyResult.read(interrupted_store, recovered_history.start.attempt_id)
        control_result = StudyResult.read(control_store, reference.start.attempt_id)
        assert recovered_result == control_result
        assert recovered_result.folds[0].economics == control_result.folds[0].economics
        self.m.record("uninterrupted-control-parity", started, exact=True)
        for entity_index in range(2):
            family = hashlib.sha256(f"capacity-{entity_index}".encode()).hexdigest()
            store = AttemptStore(self.m.root / "studies" / family)
            histories = store.histories()
            expected = 3 if entity_index == 0 else 2
            assert len(histories) == expected
            completed = tuple(h for h in histories if h.status == "completed")
            assert len(completed) == 2
            for history in completed:
                started = time.perf_counter()
                result = StudyResult.read(store, history.start.attempt_id)
                StudyReportReader.read(store, history.start.attempt_id)
                self.m.record("report-and-result-reopen", started)
                economics = result.folds[0].economics
                assert len(economics.ledger.fills) == 2
                # Buy at 100.99 + 0.01 adverse, sell at 99.01 - 0.01;
                # rounded 0.2% fees are 0.20 each: 99 - 101 - 0.40.
                assert economics.mark is not None
                assert economics.mark.net.value == Decimal("-2.40"), economics.mark
        self.m.checkpoint("studies-and-control")
        started = time.perf_counter()
        WorkspaceBackup.create(
            self.m.root,
            self.m.root.parent / (self.m.root.name + "-backup"),
            components=("features", "serving", "offline-feast", "jobs", "studies"),
        )
        restored = self.m.root.parent / (self.m.root.name + "-restored")
        backup = self.m.root.parent / (self.m.root.name + "-backup")
        self.m.checkpoint("backup", backup)
        WorkspaceBackup.restore(backup, restored)
        self.m.checkpoint("restore", restored)
        restored_store = VersionedFeatureStore.open(restored / "features" / "history.sqlite3")
        reopened_started = time.perf_counter()
        snapshot = FeastServingSnapshot.from_materialization(
            restored_store.get_materialization(self.definition, "complete")
        )
        generation = self.bridge.open_generation(snapshot, restored / "serving")
        self.m.record("online-generation-reopen", reopened_started)
        for entity in self.entities:
            served_started = time.perf_counter()
            served = self.bridge.retrieve(snapshot, generation, entity, self.decisions[-1])
            assert served.status == "ready" and served.values == ("0/1",)
            self.m.record("online-retrieval-after-restore", served_started, entity=entity)
        for entity_index in range(2):
            family = hashlib.sha256(f"capacity-{entity_index}".encode()).hexdigest()
            original = AttemptStore(self.m.root / "studies" / family)
            restored_attempts = AttemptStore(restored / "studies" / family)
            assert original.histories() == restored_attempts.histories()
            for history in original.histories():
                if history.status == "completed":
                    assert StudyResult.read(original, history.start.attempt_id) == StudyResult.read(
                        restored_attempts, history.start.attempt_id
                    )
        for relative in (
            "offline-feast/repository/data/features.parquet",
            "offline-feast/repository/data/registry.db",
            "offline-feast/repository/feature_store.yaml",
        ):
            assert (self.m.root / relative).read_bytes() == (restored / relative).read_bytes()
        self.m.record("backup-restore-equivalence", started)


class _Arguments(argparse.Namespace):
    """Require explicit retained output, scale and independently locked worker selection."""

    output: Path
    worker_python: Path
    decisions: int
    action: Literal["run", "interrupted-worker"]


def main() -> None:
    """Run the declared diagnostic and retain a failed measurement before propagating errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--decisions", type=int, default=4320)
    parser.add_argument("--action", choices=("run", "interrupted-worker"), default="run")
    args = parser.parse_args(namespace=_Arguments())
    if not 4 <= args.decisions <= 8192 or args.decisions % 2:
        raise ValueError("diagnostic requires an even 4..8192 decision count")
    measurements = (
        _Measurements.create(args.output)
        if args.action == "run"
        else _Measurements(
            args.output.resolve(), ImplementationIdentity.sha256(), sample_resources=False
        )
    )
    try:
        spec = find_spec("applications.explore.command")
        if spec is None or spec.origin is None:
            raise ValueError("installed Feast command missing")
        worker_command = (
            str(args.worker_python.absolute()),
            "-I",
            "-c",
            "from runpy import run_path; " + f"raise SystemExit(run_path({spec.origin!r})['main']"
            "(['feast-serving-worker']))",
        )
        offline_command = (
            str(args.worker_python.absolute()),
            "-I",
            "-c",
            "from runpy import run_path; "
            + f"raise SystemExit(run_path({spec.origin!r})['main'](['feast-worker']))",
        )
        runner = _TrackedProcess(measurements)
        bridge = FeastServingBridge(
            _TrackedFeastWorker(
                runner,
                worker_command,
                cwd=measurements.root,
                timeout=120,
                operation="online-boundary",
            )
        )
        consumer = Path(__file__).read_bytes()
        artifact = StudyArtifact(
            fingerprint=Fingerprint(
                name="capacity-consumer", sha256=hashlib.sha256(consumer).hexdigest()
            ),
            payload=consumer,
        )
        workload = _Workload(
            measurements,
            args.decisions,
            bridge,
            artifact,
            runner,
            args.worker_python.absolute(),
            offline_command,
        )
        measurements.pin_inputs(workload, args.worker_python.absolute())
        if args.action == "interrupted-worker":
            workload.interrupted_worker()
            return
        (measurements.root / "inputs.json").write_bytes(workload.payload)
        measurements.checkpoint("authored-inputs")
        workload.features()
        workload.studies()
    except Exception as error:
        if args.action == "run":
            measurements.finish("failed", f"{type(error).__name__}: {error}")
        raise
    if args.action == "run":
        measurements.finish("complete")


if __name__ == "__main__":
    main()
