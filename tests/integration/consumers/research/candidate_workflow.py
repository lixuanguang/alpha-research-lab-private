"""Package completed installed studies and replay their selected candidate components."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from applications.explore import StudyComponents, evaluate_study, run_candidate
from configuration import CapabilityRegistry
from research.experiments import AttemptStore, CandidateBundle, Fingerprint
from research.features import FeatureKernel, FeatureSchema, TransformAdapter
from research.labels import Outcome
from research.models import EstimatorAdapter
from research.studies import (
    ChartDefinition,
    DecisionStudy,
    MetricDefinition,
    PublicationPolicy,
    StudyArtifact,
)
from runtime import (
    CandidateComponents,
    CandidateLoader,
    CandidateMonitoringExporter,
    CandidateStep,
    ChartFactory,
    EstimatorFactory,
    FeatureFactory,
    MetricFactory,
    PolicyFactory,
    TransformFactory,
)
from serialization import DomainCodec
from strategies import DecisionPolicy, OrderIntent, TargetIntent
from telemetry import (
    DashboardBuilder,
    DashboardConfig,
    DashboardPanel,
    MetricRegistry,
    MonitoringMetric,
    MonitoringQuery,
    TelemetryStore,
)


class _PaperMonitoringAcceptance:
    """Evaluate one fresh metric from a durable paper inference and delayed source label."""

    @staticmethod
    def exercise(
        root: Path,
        *,
        exporter: CandidateMonitoringExporter,
        step: CandidateStep,
        pending: Outcome,
        observed: Outcome,
        metric: MonitoringMetric,
    ) -> dict[str, object]:
        """Keep pending and observed dashboards causal over the same saved feature sample."""
        assert step.feature is not None and step.prediction is not None
        prediction = exporter.prediction(step, recorded_at=step.at)
        pending_event = exporter.outcome(step, pending, recorded_at=step.at)
        assert observed.available_at is not None
        observed_event = exporter.outcome(
            step, observed, recorded_at=observed.available_at, revision=1
        )
        assert (
            prediction.sample
            == pending_event.sample
            == observed_event.sample
            == step.feature.identity
        )
        assert prediction.context == pending_event.context == observed_event.context
        assert prediction.context.mode == "paper"
        assert prediction.context.model == step.prediction.model_identity
        assert prediction.value == step.prediction.value
        assert prediction.clock_quality == observed_event.clock_quality == "modeled"
        assert pending_event.clock_quality == "unknown"
        assert prediction.recorded_at == pending_event.recorded_at == step.at
        assert pending_event.value is None and pending_event.missing_reason == "pending"
        assert observed_event.available_at == observed.available_at
        assert observed_event.recorded_at == observed.available_at
        store = TelemetryStore(root / "learned-paper-monitoring.sqlite")
        assert store.append((prediction, pending_event)) == 2
        config = DashboardConfig(
            title="Candidate prediction error",
            panels=(
                DashboardPanel(
                    title="Squared prediction error",
                    metric_identity=metric.spec.identity,
                    kind="line",
                ),
            ),
        )
        registry = MetricRegistry((metric,))
        pending_query = MonitoringQuery(
            scope=prediction.context.scope,
            mode="paper",
            start=step.at,
            end=step.at + timedelta(microseconds=1),
            as_of=step.at + timedelta(microseconds=1),
        )
        waiting = DashboardBuilder.build(
            config, pending_query, store.query(pending_query), registry
        )
        assert waiting.results[0].status == "missing"
        assert waiting.results[0].points[0].missing_reason == "pending"
        assert store.append((observed_event,)) == 1
        known_query = replace(pending_query, as_of=observed.available_at)
        known = DashboardBuilder.build(config, known_query, store.query(known_query), registry)
        assert known.results[0].status == "ok"
        assert known.results[0].value is not None
        assert known.results[0].points[0].value == known.results[0].value
        assert (
            DashboardBuilder.build(config, pending_query, store.query(pending_query), registry)
            == waiting
        )
        assert known.write(root / "learned-paper-dashboard").exists()
        return {
            "saved_paper_prediction": True,
            "pending_before_label": True,
            "observed_after_label": True,
            "metric_identity": metric.spec.identity,
        }


def main() -> None:
    """Run retained packaging, replay/runtime parity and a fresh process continuation."""
    consumer_root = Path(__file__).resolve().parent
    consumer_root_text = str(consumer_root)
    if consumer_root_text not in sys.path:
        sys.path.insert(0, consumer_root_text)
    # third party library imports
    from decision_study import _InstalledErrorMetric
    from research_workflows.candidate_bundle import _CandidateAcceptance
    from research_workflows.candidate_runtime import (
        _FeatureCandidateAcceptance,
        _PaperCandidateAcceptance,
    )
    from research_workflows.scenario import (
        _Feature,
        _FillCountMetric,
        _OrderPolicy,
        _ProfitChart,
        _Scenario,
        _ShiftedEstimator,
        _ShiftTransform,
        _TargetPolicy,
    )

    class _AuthoredScenario(_Scenario):
        """Place synthetic study clocks after the retained attempt publication clock."""

        @staticmethod
        def at(second: int) -> datetime:
            """Use one stable authored future epoch in both isolated processes."""
            return datetime(2100, 1, 1, tzinfo=UTC) + timedelta(seconds=second)

    class _NoFitEstimator(_ShiftedEstimator):
        """A runtime factory that detects any hidden fitting call."""

        def fit(self, rows: object, outcomes: object) -> bytes:
            """Reject fitting after the accepted study artifact was published."""
            raise AssertionError("candidate runtime refitted the estimator")

    class _NoFitTransform(_ShiftTransform):
        """A runtime factory that detects any hidden preprocessing fit."""

        def fit(self, rows: object) -> bytes:
            """Reject fitting after the accepted study artifact was published."""
            raise AssertionError("candidate runtime refitted the transform")

    class _Factories:
        """Resolve only reviewed companion implementations and declarative parameters."""

        def __init__(self, scenario: _Scenario) -> None:
            """Bind one instance's exact units and strategy state boundaries."""
            self.scenario = scenario

        def feature(self, schema: FeatureSchema, payload: bytes) -> FeatureKernel:
            """Load the retained fresh square definition."""
            _CandidateAcceptance._require_parameters(payload, {})
            return _Feature(schema.inputs[0])

        def policy(self, payload: bytes) -> DecisionPolicy:
            """Select the authored rule or learned target policy."""
            parameters = msgspec.json.decode(payload, type=dict[str, object])
            if parameters == {"threshold": 0}:
                return _TargetPolicy(self.scenario.dimension, threshold=0)
            if parameters == {"limit": "99", "quantity": "1"}:
                return _OrderPolicy(self.scenario)
            raise ValueError("unknown policy parameters")

        def transform(self, payload: bytes) -> TransformAdapter:
            """Load fitted preprocessing without permitting a new fit."""
            _CandidateAcceptance._require_parameters(payload, {})
            return _NoFitTransform()

        def estimator(self, payload: bytes) -> EstimatorAdapter:
            """Load fitted inference without permitting a new fit."""
            _CandidateAcceptance._require_parameters(payload, {})
            return _NoFitEstimator()

        def metric(self, payload: bytes) -> MetricDefinition:
            """Load the same selected study metric definition."""
            _CandidateAcceptance._require_parameters(payload, {})
            return _FillCountMetric()

        def chart(self, payload: bytes) -> ChartDefinition:
            """Load the same selected study chart definition."""
            _CandidateAcceptance._require_parameters(payload, {})
            return _ProfitChart()

        def register(self, implementation_sha256: str) -> CandidateComponents:
            """Register typed factories with the verified companion source fingerprint."""
            return CandidateComponents(
                features={"fresh-square": FeatureFactory(implementation_sha256, self.feature)},
                policies={"fresh-policy": PolicyFactory(implementation_sha256, self.policy)},
                transforms={"fresh-shift": TransformFactory(implementation_sha256, self.transform)},
                estimators={
                    "fresh-estimator": EstimatorFactory(implementation_sha256, self.estimator)
                },
                metrics={"fresh-fill-count": MetricFactory(implementation_sha256, self.metric)},
                charts={"fresh-profit-chart": ChartFactory(implementation_sha256, self.chart)},
            )

    output = Path(sys.argv[1])
    codec = DomainCodec()
    scenario = _AuthoredScenario()
    support_sources = tuple(sorted((consumer_root / "research_workflows").glob("*.py")))
    implementation_sources = (
        consumer_root / "decision_study.py",
        Path(__file__),
        *support_sources,
    )
    implementation_payload = codec.encode_json(
        tuple(source.read_bytes() for source in implementation_sources)
    )
    implementation_sha256 = _CandidateAcceptance._sha(implementation_payload)
    implementation_artifact = StudyArtifact(
        fingerprint=Fingerprint(
            name="installed-candidate-factories",
            sha256=implementation_sha256,
        ),
        payload=implementation_payload,
    )
    components = _Factories(scenario).register(implementation_sha256)
    if len(sys.argv) == 4 and sys.argv[3] == "resume":
        _CandidateAcceptance._resume(output, scenario, components)
        return
    output.mkdir(parents=True, exist_ok=True)
    feast_worker = os.environ.get("ALPHA_FEAST_WORKER_PYTHON")
    real_feast = len(sys.argv) == 3 and sys.argv[2] == "feast"
    if real_feast and feast_worker is None:
        raise ValueError("real Feast candidate mode requires ALPHA_FEAST_WORKER_PYTHON")
    features = _FeatureCandidateAcceptance(
        output / "feature-serving",
        Path(feast_worker) if real_feast and feast_worker is not None else None,
    )
    attempts = output / "attempts"
    studies: tuple[tuple[str, DecisionStudy, StudyComponents, bool], ...] = (
        (
            "rule",
            scenario.study(
                _OrderPolicy(scenario), fitted=False, passive=True, family="candidate-rule-order"
            ),
            scenario.components(_OrderPolicy(scenario), fitted=False, passive=True),
            False,
        ),
        (
            "learned",
            scenario.study(
                _TargetPolicy(scenario.dimension, threshold=0),
                fitted=True,
                transformed=True,
                family="candidate-learned-target",
            ),
            scenario.components(
                _TargetPolicy(scenario.dimension, threshold=0), fitted=True, transformed=True
            ),
            True,
        ),
    )
    summary: dict[str, object] = {}
    for name, selected_study, selected_components, learned in studies:
        extensions: tuple[Fingerprint, ...] = (
            *selected_study.extensions,
            implementation_artifact.fingerprint,
        )
        study = replace(selected_study, extensions=extensions)
        study_components = dataclass_replace(
            selected_components,
            artifacts=(*selected_components.artifacts, implementation_artifact),
        )
        history = evaluate_study(
            study,
            components=study_components,
            attempts=attempts,
            publication=PublicationPolicy(mode="local"),
        )
        assert history.status == "completed"
        store = AttemptStore(attempts)
        manifest = _CandidateAcceptance._bundle(
            output / name,
            study=study,
            history=history,
            store=store,
            learned=learned,
            implementation_sha256=implementation_sha256,
            implementation_payload=implementation_payload,
        )
        starts = scenario.at(30 if learned else 10)
        replay = _CandidateAcceptance._deployment(
            manifest,
            mode="replay",
            instance=f"{name}-replay",
            source_identity=scenario.source.identity,
            starts_at=starts,
        )
        runtime = _CandidateAcceptance._deployment(
            manifest,
            mode="runtime",
            instance=f"{name}-runtime",
            source_identity=scenario.source.identity,
            starts_at=starts,
        )
        registry = _CandidateAcceptance._registry(manifest.requirements)
        loader = CandidateLoader(components, registry)
        loader.load(CandidateBundle(output / name), replay)
        loaded_runtime = loader.load(CandidateBundle(output / name), runtime)
        first_at = scenario.at(30 if learned else 10)
        replay_run = run_candidate(
            CandidateBundle(output / name),
            replay,
            components=components,
            registry=registry,
            source=scenario.source,
            decisions=(first_at,),
        )
        runtime_run = run_candidate(
            CandidateBundle(output / name),
            runtime,
            components=components,
            registry=registry,
            source=scenario.source,
            decisions=(first_at,),
        )
        first_replay, first_runtime = replay_run.steps[0], runtime_run.steps[0]
        assert first_replay.feature == first_runtime.feature
        assert first_replay.prediction == first_runtime.prediction
        assert first_replay.decision is not None and first_runtime.decision is not None
        assert first_replay.decision.intent == first_runtime.decision.intent
        if learned:
            assert first_replay.prediction is not None
            assert first_replay.prediction.value.numerator == "9"
            assert first_replay.prediction.value.denominator == "2"
            assert isinstance(first_replay.decision.intent, TargetIntent)
            assert first_replay.decision.intent.quantity.value == 1
        else:
            assert first_replay.prediction is None
            assert isinstance(first_replay.decision.intent, OrderIntent)
            assert first_replay.decision.intent.limit.value == 99
            assert first_replay.decision.intent.time_in_force == "post-only"
        bundle = CandidateBundle(output / name)
        invalid_registry = CapabilityRegistry(
            tuple(
                replace(profile, operations=(), order_types=())
                if profile.kind == "execution"
                else profile
                for profile in registry.profiles
            )
        )
        _CandidateAcceptance._reject_before_read(
            bundle,
            replay,
            components=components,
            registry=invalid_registry,
            source=scenario.source,
            at=first_at,
        )
        _CandidateAcceptance._reject_before_read(
            bundle,
            replay,
            components=CandidateComponents(features={}, policies={}),
            registry=registry,
            source=scenario.source,
            at=first_at,
        )
        _CandidateAcceptance._reject_before_read(
            bundle,
            replace(replay, starts_at=manifest.available_at - timedelta(microseconds=1)),
            components=components,
            registry=registry,
            source=scenario.source,
            at=first_at,
        )
        _CandidateAcceptance._reject_before_read(
            bundle,
            runtime,
            components=components,
            registry=registry,
            source=scenario.source,
            at=first_at,
            checkpoint=first_replay.checkpoint,
        )
        malformed_root = output / f"{name}-unsupported-schema"
        shutil.copytree(output / name, malformed_root)
        malformed = msgspec.json.decode(
            (malformed_root / "manifest.json").read_bytes(), type=dict[str, object]
        )
        malformed["schema_version"] = "candidate-manifest-unsupported"
        altered_manifest = malformed_root / "altered-manifest.json"
        altered_manifest.write_bytes(codec.encode_json(malformed))
        altered_manifest.replace(malformed_root / "manifest.json")
        _CandidateAcceptance._reject_before_read(
            CandidateBundle(malformed_root),
            replay,
            components=components,
            registry=registry,
            source=scenario.source,
            at=first_at,
        )
        for mode, deployment, step in (
            ("replay", replay, first_replay),
            ("runtime", runtime, first_runtime),
        ):
            (output / f"{name}-{mode}-deployment.json").write_bytes(codec.encode_json(deployment))
            (output / f"{name}-{mode}-checkpoint.json").write_bytes(
                codec.encode_json(step.checkpoint)
            )
            (output / f"{name}-{mode}-first.json").write_bytes(codec.encode_json(step))
        summary[name] = {
            "dataset": manifest.dataset.sha256,
            "experiment": history.start.run_identity,
            "candidate": manifest.identity,
            "deployment": replay.identity,
            "report": manifest.report.sha256,
            "output": manifest.output,
            "qualification": manifest.qualification,
            "admission_rejections_before_source_reads": 5,
        }
        summary[f"{name}_features"] = features.exercise(
            name=name,
            bundle=CandidateBundle(output / name),
            manifest=manifest,
            components=components,
            scenario=scenario,
            source_deployment=replay,
            source_step=first_replay,
            decision_second=30 if learned else 10,
        )
        paper_proof, paper_checkpoint, paper_step = _PaperCandidateAcceptance.exercise(
            root=output,
            name=name,
            bundle=bundle,
            deployment=runtime,
            components=components,
            registry=registry,
            scenario=scenario,
            source_step=first_runtime,
            decision_second=30 if learned else 10,
        )
        summary[f"{name}_paper"] = paper_proof
        if learned:
            assert paper_step.feature is not None
            paper_config = _PaperCandidateAcceptance._config(name, "paper", scenario)
            exporter = CandidateMonitoringExporter(
                loaded_runtime,
                paper_config,
                paper_checkpoint,
                scope=f"{name}-paper-candidate",
                clock_quality="modeled",
            )
            pending = scenario.labels.read(paper_step.feature, as_of=paper_step.at)
            observed = scenario.labels.read(
                paper_step.feature, as_of=paper_step.at + timedelta(seconds=1)
            )
            summary["learned_monitoring"] = _PaperMonitoringAcceptance.exercise(
                output,
                exporter=exporter,
                step=paper_step,
                pending=pending,
                observed=observed,
                metric=_InstalledErrorMetric(),
            )
    subprocess.run(
        [sys.executable, "-I", __file__, str(output), "unused", "resume"],
        check=True,
        timeout=120,
    )
    resumed = msgspec.json.decode(
        (output / "resumed-summary.json").read_bytes(), type=dict[str, bool]
    )
    assert resumed == {"rule": True, "learned": True}
    summary["fresh_process_restart_equal"] = True
    (output / "summary.json").write_bytes(codec.encode_json(summary))
    print(codec.encode_json(summary).decode())


if __name__ == "__main__":
    main()
