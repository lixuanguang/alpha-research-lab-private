"""Measure authored research capacity through real stores, Feast and study workers.

This is a synthetic diagnostic, never representative-input acceptance. Copy this
file outside the checkout and run with the installed research interpreter.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
import math
import resource
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

# project library imports
from applications.explore import (
    StudyComponents,
    StudyJobHandler,
    materialize_features,
    schedule_study,
)
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.contracts import BookObservation, Level
from reference_data.instruments import InstrumentId
from research.experiments import AttemptStore, Fingerprint, TemporalSplit, TimeWindow
from research.features import (
    FeastOfflineWorker,
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureSchema,
    FeatureStoreDefinition,
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


class _Measurements:
    """Retain flushed individual samples and resource observations even after failure."""

    def __init__(self, root: Path, implementation: str) -> None:
        """Bind a fresh absolute output and an already verified implementation identity."""
        self.root = root
        self.samples: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self.started = time.perf_counter()
        self.implementation = implementation

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

    def finish(self, status: str, reason: str = "") -> None:
        """Report empirical nearest-rank percentiles only with at least one thousand samples."""
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
            "scope": "synthetic-diagnostic",
            "status": status,
            "reason": reason,
            "implementation": self.implementation,
            "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "elapsed_seconds": time.perf_counter() - self.started,
            "stages": stages,
            "cpu_user_seconds": own.ru_utime + child.ru_utime,
            "cpu_system_seconds": own.ru_stime + child.ru_stime,
            "self_peak_rss_bytes": own.ru_maxrss * scale,
            "child_peak_rss_bytes": child.ru_maxrss * scale,
            "disk_bytes": sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file()),
            "os_block_io": "unavailable as byte measurements on Darwin",
            "cache": "fresh application/store; OS page cache uncontrolled; PIT queries warm",
            "representative_acceptance": False,
        }
        (self.root / "measurement.json").write_bytes(DomainCodec().encode_json(payload))
        print(DomainCodec().encode_json(payload).decode(), flush=True)


class _Market:
    """Supply explicit authored minute books with independent exact trade economics."""

    def __init__(self, entity: str, decisions: tuple[datetime, ...]) -> None:
        """Pin the synthetic source clocks and entity; no original receipt clocks are claimed."""
        self.entity, self.decisions = entity, decisions
        self.identity = hashlib.sha256(
            DomainCodec().encode_json((entity, decisions, "constant-book-v1"))
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
                ("capacity-round-trip-v1", field, quantity, currency, count, entry)
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
    ) -> None:
        """Bind the declared minute grid, two distinct entities and exact running means."""
        self.m = measurements
        self.count = count
        self.artifact = artifact
        self.bridge = bridge
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
                implementation="running-mean-v1",
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
        result = materialize_features(
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
        started = time.perf_counter()
        reopened = VersionedFeatureStore.open(self.m.root / "features" / "history.sqlite3")
        assert (
            reopened.retrieve_online(self.definition, self.entities[0], self.decisions[-1]).feature
            is not None
        )
        self.m.record("feature-reopen", started)

    def studies(self) -> None:
        """Run concurrent families, retaining reports and independent net-loss oracles."""
        metric, chart = NetReturnMetric(), LedgerCurveChart()
        queue = JobQueue(self.m.root / "jobs")
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
            started = time.perf_counter()
            pool.run_until_idle()
            self.m.record("two-worker-wave", started, peak_active_workers=handler.peak)
            for entity_index in range(2):
                state = queue.read(f"trial-{entity_index}-{trial}")
                assert state.status == "completed", state.last_error
        assert handler.peak == 2
        for entity_index in range(2):
            family = hashlib.sha256(f"capacity-{entity_index}".encode()).hexdigest()
            store = AttemptStore(self.m.root / "studies" / family)
            histories = store.histories()
            assert len(histories) == 2 and all(h.status == "completed" for h in histories)
            for history in histories:
                started = time.perf_counter()
                result = StudyResult.read(store, history.start.attempt_id)
                StudyReportReader.read(store, history.start.attempt_id)
                self.m.record("report-and-result-reopen", started)
                economics = result.folds[0].economics
                assert len(economics.ledger.fills) == 2
                # Buy at 100.99 + 0.01 adverse, sell at 99.01 - 0.01;
                # rounded 0.2% fees are 0.20 each: 99 - 101 - 0.40.
                assert economics.mark.net.value == Decimal("-2.40"), economics.mark
        started = time.perf_counter()
        WorkspaceBackup.create(
            self.m.root,
            self.m.root.parent / (self.m.root.name + "-backup"),
            components=("features", "serving", "jobs", "studies"),
        )
        restored = self.m.root.parent / (self.m.root.name + "-restored")
        WorkspaceBackup.restore(self.m.root.parent / (self.m.root.name + "-backup"), restored)
        restored_store = VersionedFeatureStore.open(restored / "features" / "history.sqlite3")
        snapshot = FeastServingSnapshot.from_materialization(
            restored_store.get_materialization(self.definition, "complete")
        )
        generation = self.bridge.open_generation(snapshot, restored / "serving")
        for entity in self.entities:
            served = self.bridge.retrieve(snapshot, generation, entity, self.decisions[-1])
            assert served.status == "ready" and served.values == ("0/1",)
        for entity_index in range(2):
            family = hashlib.sha256(f"capacity-{entity_index}".encode()).hexdigest()
            original = AttemptStore(self.m.root / "studies" / family)
            recovered = AttemptStore(restored / "studies" / family)
            assert original.histories() == recovered.histories()
            for history in original.histories():
                assert StudyResult.read(original, history.start.attempt_id) == StudyResult.read(
                    recovered, history.start.attempt_id
                )
        self.m.record("backup-restore-equivalence", started)


class _Arguments(argparse.Namespace):
    """Require explicit retained output, scale and independently locked worker selection."""

    output: Path
    worker_python: Path
    decisions: int


def main() -> None:
    """Run the declared diagnostic and retain a failed measurement before propagating errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--decisions", type=int, default=4320)
    args = parser.parse_args(namespace=_Arguments())
    if not 4 <= args.decisions <= 8192 or args.decisions % 2:
        raise ValueError("diagnostic requires an even 4..8192 decision count")
    measurements = _Measurements.create(args.output)
    try:
        spec = find_spec("applications.explore.command")
        if spec is None or spec.origin is None:
            raise ValueError("installed Feast command missing")
        bridge = FeastServingBridge(
            FeastOfflineWorker(
                (
                    str(args.worker_python.absolute()),
                    "-I",
                    "-c",
                    "from runpy import run_path; "
                    + f"raise SystemExit(run_path({spec.origin!r})['main']"
                    "(['feast-serving-worker']))",
                ),
                timeout_seconds=120,
            )
        )
        consumer = Path(__file__).read_bytes()
        artifact = StudyArtifact(
            fingerprint=Fingerprint(
                name="capacity-consumer", sha256=hashlib.sha256(consumer).hexdigest()
            ),
            payload=consumer,
        )
        workload = _Workload(measurements, args.decisions, bridge, artifact)
        (measurements.root / "inputs.json").write_bytes(workload.payload)
        workload.features()
        workload.studies()
    except Exception as error:
        measurements.finish("failed", f"{type(error).__name__}: {error}")
        raise
    measurements.finish("complete")


if __name__ == "__main__":
    main()
