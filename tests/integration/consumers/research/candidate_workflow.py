"""Package completed installed studies and replay their selected candidate components."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.util import find_spec
from pathlib import Path
from typing import Literal, Protocol

# third party library imports
import msgspec
from msgspec.structs import replace

# project library imports
from accounting import Ledger, LedgerState
from applications.explore import (
    StudyComponents,
    evaluate_study,
    run_candidate,
)
from applications.paper import PaperRunResult, PaperTimer, run_paper
from configuration import (
    CandidateDeployment,
    CapabilityField,
    CapabilityProfile,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
    PaperConfiguration,
    UniverseSelection,
)
from execution import PaperMarket, PaperOrderJournal
from financial_units import Currency, Dimension, Money, Price, Quantity
from reference_data.instruments import InstrumentId
from research.experiments import (
    AttemptHistory,
    AttemptStore,
    CandidateArtifact,
    CandidateBundle,
    CandidateComponent,
    CandidateManifest,
    CandidateMetricContract,
    CandidateStateContract,
    Fingerprint,
)
from research.features import (
    FeastOfflineWorker,
    FeastServingBridge,
    FeastServingSnapshot,
    FeatureKernel,
    FeatureSchema,
    FeatureStoreDefinition,
    StoredFeature,
    TransformAdapter,
    VersionedFeatureStore,
)
from research.models import EstimatorAdapter
from research.observations import DecisionInputs, InputRequirement, NumericHistorySource
from research.studies import (
    ChartDefinition,
    DecisionStudy,
    MetricDefinition,
    PublicationPolicy,
    StudyArtifact,
    StudyResult,
)
from risk import SpotLimits
from runtime import (
    CandidateCheckpoint,
    CandidateComponents,
    CandidateFeatureFeed,
    CandidateLoader,
    CandidateSession,
    CandidateStep,
    ChartFactory,
    EstimatorFactory,
    FeatureFactory,
    ImplementationIdentity,
    MetricFactory,
    PaperCandidateRuntime,
    PolicyFactory,
    TransformFactory,
)
from serialization import DomainCodec
from strategies import DecisionPolicy, OrderIntent, TargetIntent


class _ScenarioView(Protocol):
    """Keep the companion MR03 fixture source typed in this standalone script."""

    entity: str
    source: NumericHistorySource
    dimension: Dimension
    currency: Currency

    def at(self, second: int) -> datetime:
        """Return the fixture's authored UTC clock."""
        ...

    def price(self, value: str) -> Price:
        """Return an exact price for the fixture's instrument and quote currency."""
        ...

    def quantity(self, value: str) -> Quantity:
        """Return an exact base-unit quantity for the fixture's instrument."""
        ...


class _ReadProbe:
    """Count source effects while testing complete pre-read candidate admission."""

    def __init__(self, source: NumericHistorySource) -> None:
        """Wrap an installed decision source without changing its declared identity."""
        self.source = source
        self.reads = 0

    @property
    def identity(self) -> str:
        """Expose the exact bound source identity."""
        return self.source.identity

    @property
    def requirements(self) -> tuple[InputRequirement, ...]:
        """Expose the same named input signature."""
        return self.source.requirements

    def read(self, entity: str, at: datetime) -> DecisionInputs:
        """Record any attempted source access."""
        self.reads += 1
        return self.source.read(entity, at)


class _CandidateAcceptance:
    """Own candidate evidence construction and verification for this installed workflow."""

    @staticmethod
    def _sha(payload: bytes) -> str:
        """Fingerprint exact bytes, including independently copied extension source."""
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _require_parameters(payload: bytes, expected: dict[str, object]) -> None:
        """Require exact selected parameters before creating a registered component."""
        if msgspec.json.decode(payload, type=dict[str, object]) != expected:
            raise ValueError("candidate factory parameters differ")

    @staticmethod
    def _capabilities(output: Literal["target", "order"]) -> tuple[CapabilityRequirement, ...]:
        """Pin all six local fixture families with a tight non-book input signature."""
        return (
            CapabilityRequirement(
                name="authored-signal",
                kind="market_data",
                channel="non-book",
                clock="authored",
                max_freshness_us=0,
                fields=(CapabilityField(name="level", units="dimensionless"),),
                qualification="fixture",
                product="spot",
                venue="synthetic",
                calendar="continuous-utc",
            ),
            CapabilityRequirement(
                name="reference",
                kind="reference_data",
                qualification="fixture",
                product="spot",
                venue="synthetic",
                calendar="continuous-utc",
            ),
            CapabilityRequirement(
                name="calendar",
                kind="calendar",
                qualification="fixture",
                product="spot",
                venue="synthetic",
                calendar="continuous-utc",
            ),
            CapabilityRequirement(
                name="valuation",
                kind="valuation",
                qualification="fixture",
                product="spot",
                venue="synthetic",
                calendar="continuous-utc",
            ),
            CapabilityRequirement(
                name="account",
                kind="account",
                qualification="fixture",
                product="spot",
                venue="synthetic",
                calendar="continuous-utc",
            ),
            CapabilityRequirement(
                name="execution",
                kind="execution",
                qualification="fixture",
                operations=(f"intent:{output}",),
                order_types=("post-only",) if output == "order" else (),
                product="spot",
                venue="synthetic",
                calendar="continuous-utc",
            ),
        )

    @staticmethod
    def _registry(requirements: tuple[CapabilityRequirement, ...]) -> CapabilityRegistry:
        """Declare fixture support independently of the candidate's requirements."""
        return CapabilityRegistry(
            tuple(
                CapabilityProfile(
                    name=f"fixture-{requirement.name}",
                    kind=requirement.kind,
                    implementation_identity=f"installed-fixture-{requirement.kind}",
                    version="1",
                    products=("spot",),
                    venues=("synthetic",),
                    calendars=("continuous-utc",),
                    modes=("replay", "runtime"),
                    channels=("non-book",) if requirement.kind == "market_data" else (),
                    clocks=("authored",) if requirement.kind == "market_data" else (),
                    max_freshness_us=0 if requirement.kind == "market_data" else None,
                    fields=(CapabilityField(name="level", units="dimensionless"),)
                    if requirement.kind == "market_data"
                    else (),
                    operations=("intent:target", "intent:order")
                    if requirement.kind == "execution"
                    else (),
                    order_types=("post-only",) if requirement.kind == "execution" else (),
                    qualification="fixture",
                )
                for requirement in requirements
            )
        )

    @staticmethod
    def _bundle(
        root: Path,
        *,
        study: DecisionStudy,
        history: AttemptHistory,
        store: AttemptStore,
        learned: bool,
        implementation_sha256: str,
        implementation_payload: bytes,
        requirements: tuple[CapabilityRequirement, ...] | None = None,
        cadence_us: int = 10_000_000,
        on_gap: Literal["pause", "reset"] = "pause",
        metric_currency: str = "USDT",
    ) -> CandidateManifest:
        """Publish exact completed study and selected fold state as an engineering handoff."""
        codec = DomainCodec()
        result = StudyResult.read(store, history.start.attempt_id)
        fold = result.folds[-1]
        output: Literal["target", "order"] = "target" if learned else "order"
        payloads: dict[str, bytes] = {
            "dataset": codec.encode_json(study),
            "experiment": codec.encode_json(history.start.spec),
            "attempt": codec.encode_json(history),
            "study-report": store.artifact(history.start.attempt_id, "study-report"),
            "feature-schema": store.artifact(history.start.attempt_id, "feature-schema"),
            "factory-implementation": implementation_payload,
        }
        assert _CandidateAcceptance._sha(implementation_payload) == implementation_sha256
        assert store.artifact(history.start.attempt_id, "extension-0001") == implementation_payload
        feature = codec.decode_json(payloads["feature-schema"], FeatureSchema)
        definition = FeatureStoreDefinition(
            name=f"{study.family}-features",
            entity_type="instrument",
            schema=feature,
            transform_identity=fold.transform.identity if fold.transform is not None else None,
            output_fields=fold.transform.output_fields if fold.transform is not None else None,
        )
        payloads["feature-store"] = codec.encode_json(definition)
        if learned:
            payloads["transform"] = store.artifact(history.start.attempt_id, "transform-0001")
            payloads["estimator"] = store.artifact(history.start.attempt_id, "model-0001")
            assert fold.transform is not None and fold.model is not None
        parameter_values: dict[str, dict[str, object]] = {
            "feature": {},
            "policy": {"threshold": 0} if learned else {"limit": "99", "quantity": "1"},
            "metric": {},
            "chart": {},
        }
        if learned:
            parameter_values.update(transform={}, estimator={})
        for role, values in parameter_values.items():
            payloads[f"{role}-parameters"] = codec.encode_json(values)
        refs = {
            name: CandidateArtifact(name=name, sha256=_CandidateAcceptance._sha(value))
            for name, value in payloads.items()
        }
        assert refs["dataset"].sha256 == study.identity
        policy_identity = study.policy_identity
        assert policy_identity is not None
        components = [
            CandidateComponent(
                role="feature",
                factory_key="fresh-square",
                identity=study.feature_identity,
                implementation_sha256=implementation_sha256,
                parameters=refs["feature-parameters"],
            ),
            CandidateComponent(
                role="policy",
                factory_key="fresh-policy",
                identity=policy_identity,
                implementation_sha256=implementation_sha256,
                parameters=refs["policy-parameters"],
            ),
        ]
        if learned:
            assert study.transform_identity is not None and study.model_identity is not None
            components.extend(
                (
                    CandidateComponent(
                        role="transform",
                        factory_key="fresh-shift",
                        identity=study.transform_identity,
                        implementation_sha256=implementation_sha256,
                        parameters=refs["transform-parameters"],
                    ),
                    CandidateComponent(
                        role="estimator",
                        factory_key="fresh-estimator",
                        identity=study.model_identity,
                        implementation_sha256=implementation_sha256,
                        parameters=refs["estimator-parameters"],
                    ),
                )
            )
        components.extend(
            (
                CandidateComponent(
                    role="metric",
                    factory_key="fresh-fill-count",
                    identity=study.metrics[0].sha256,
                    implementation_sha256=implementation_sha256,
                    parameters=refs["metric-parameters"],
                ),
                CandidateComponent(
                    role="chart",
                    factory_key="fresh-profit-chart",
                    identity=study.charts[0].sha256,
                    implementation_sha256=implementation_sha256,
                    parameters=refs["chart-parameters"],
                ),
            )
        )
        manifest = CandidateManifest(
            name="installed-learned-target" if learned else "installed-rule-order",
            version="1",
            qualification="engineering",
            code_sha256=ImplementationIdentity.sha256(),
            environment_sha256=history.start.spec.environment_sha256,
            dataset=refs["dataset"],
            experiment=refs["experiment"],
            attempt=refs["attempt"],
            report=refs["study-report"],
            feature_schema=refs["feature-schema"],
            feature_store=refs["feature-store"],
            transform=refs.get("transform"),
            estimator=refs.get("estimator"),
            assessment=None,
            components=tuple(components),
            inputs=feature.inputs,
            requirements=(
                _CandidateAcceptance._capabilities(output) if requirements is None else requirements
            ),
            product="spot",
            calendar="continuous-utc",
            entities=(study.economics.entity,),
            cadence_us=cadence_us,
            available_at=fold.model.available_at
            if learned and fold.model is not None
            else study.folds[0].decisions[0],
            output=output,
            state=CandidateStateContract(
                feature_mode="batch",
                warmup_observations=0,
                checkpoint_schema="candidate-checkpoint-v1",
                on_gap=on_gap,
                on_restart="restore",
                policy_state_schema="decision-state-v1",
            ),
            metrics=(
                CandidateMetricContract(
                    name="posted-fills",
                    kind="metric",
                    component_key="fresh-fill-count",
                    version="1",
                    units="fills",
                    applies_to=("research", "runtime"),
                ),
                CandidateMetricContract(
                    name="fold-profit",
                    kind="chart",
                    component_key="fresh-profit-chart",
                    version="1",
                    units=metric_currency,
                    applies_to=("research", "runtime"),
                ),
            ),
            artifacts=tuple(refs.values()),
            limitations=("Synthetic fixture; no venue or empirical strategy qualification.",),
        )
        CandidateBundle(root).publish(manifest, payloads)
        assert CandidateBundle(root).read() == manifest
        return manifest

    @staticmethod
    def _deployment(
        manifest: CandidateManifest,
        *,
        mode: Literal["replay", "runtime"],
        instance: str,
        source_identity: str,
        starts_at: datetime,
    ) -> CandidateDeployment:
        """Keep placements distinct and trading authorization empty."""
        entity = InstrumentId.from_canonical_text(manifest.entities[0])
        return CandidateDeployment(
            name=f"{manifest.name}-{mode}-{instance}",
            candidate_identity=manifest.identity,
            instance=instance,
            entity=manifest.entities[0],
            mode=mode,
            input_mode="source",
            source_identity=source_identity,
            starts_at=starts_at,
            selections=tuple(
                CapabilitySelection(name=r.name, profile=f"fixture-{r.name}")
                for r in manifest.requirements
            ),
            universes=UniverseSelection(
                collection=(entity,),
                research=(entity,),
                strategy=(entity,),
                authorized_trading=(),
            ),
        )

    @staticmethod
    def _resume(output: Path, scenario: _ScenarioView, components: CandidateComponents) -> None:
        """Reopen verified bundle and checkpoint in another isolated Python process."""
        codec = DomainCodec()
        result: dict[str, bool] = {}
        for name, second in (("rule", 20), ("learned", 40)):
            bundle = CandidateBundle(output / name)
            manifest = bundle.read()
            registry = _CandidateAcceptance._registry(manifest.requirements)
            steps: list[CandidateStep] = []
            for mode in ("replay", "runtime"):
                deployment = codec.decode_json(
                    (output / f"{name}-{mode}-deployment.json").read_bytes(), CandidateDeployment
                )
                checkpoint = codec.decode_json(
                    (output / f"{name}-{mode}-checkpoint.json").read_bytes(), CandidateCheckpoint
                )
                run = run_candidate(
                    bundle,
                    deployment,
                    components=components,
                    registry=registry,
                    source=scenario.source,
                    decisions=(scenario.at(second),),
                    checkpoint=checkpoint,
                )
                step = run.steps[0]
                (output / f"{name}-{mode}-resumed.json").write_bytes(codec.encode_json(step))
                first = codec.decode_json(
                    (output / f"{name}-{mode}-first.json").read_bytes(), CandidateStep
                )
                whole = run_candidate(
                    bundle,
                    deployment,
                    components=components,
                    registry=registry,
                    source=scenario.source,
                    decisions=(scenario.at(30 if name == "learned" else 10), scenario.at(second)),
                )
                assert whole.steps == (first, step)
                assert whole.checkpoint == step.checkpoint
                steps.append(step)
            assert steps[0].feature == steps[1].feature
            assert steps[0].prediction == steps[1].prediction
            assert steps[0].decision is not None and steps[1].decision is not None
            assert steps[0].decision.intent == steps[1].decision.intent
            assert steps[0].checkpoint.observations == 2
            if name == "learned":
                assert steps[0].prediction is not None
                assert steps[0].prediction.value.numerator == "11"
                assert steps[0].prediction.value.denominator == "2"
                assert isinstance(steps[0].decision.intent, TargetIntent)
                assert steps[0].decision.intent.quantity.value == 1
            else:
                assert isinstance(steps[0].decision.intent, OrderIntent)
                assert steps[0].decision.intent.limit.value == 99
            result[name] = True
        (output / "resumed-summary.json").write_bytes(codec.encode_json(result))

    @staticmethod
    def _reject_before_read(
        bundle: CandidateBundle,
        deployment: CandidateDeployment,
        *,
        components: CandidateComponents,
        registry: CapabilityRegistry,
        source: NumericHistorySource,
        at: datetime,
        checkpoint: CandidateCheckpoint | None = None,
    ) -> None:
        """Prove invalid admission cannot touch the selected source adapter."""
        probe = _ReadProbe(source)
        try:
            run_candidate(
                bundle,
                deployment,
                components=components,
                registry=registry,
                source=probe,
                decisions=(at,),
                checkpoint=checkpoint,
            )
        except ValueError:
            assert probe.reads == 0
        else:
            raise AssertionError("candidate admission accepted an invalid selection")


class _FeatureCandidateAcceptance:
    """Prove packaged candidates consume pinned offline and optional real Feast values."""

    def __init__(self, root: Path, worker_python: Path | None) -> None:
        """Open an authoritative store and optionally bind an isolated Feast worker."""
        self.root = root
        self.root.mkdir()
        self.bridge: FeastServingBridge | None = None
        if worker_python is not None:
            spec = find_spec("applications.explore.command")
            if spec is None or spec.origin is None:
                raise ValueError("installed Feast worker command is missing")
            command = (
                str(worker_python.absolute()),
                "-I",
                "-c",
                "from runpy import run_path; "
                f"raise SystemExit(run_path({spec.origin!r})['main'](['feast-serving-worker']))",
            )
            self.bridge = FeastServingBridge(FeastOfflineWorker(command, timeout_seconds=120))
        self.store = VersionedFeatureStore.open(root / "features.sqlite3")
        self.serving_root = root / "serving"

    def exercise(
        self,
        *,
        name: str,
        bundle: CandidateBundle,
        manifest: CandidateManifest,
        components: CandidateComponents,
        scenario: _ScenarioView,
        source_deployment: CandidateDeployment,
        source_step: CandidateStep,
        decision_second: int,
    ) -> dict[str, object]:
        """Pin a real snapshot and compare source, offline and optional Feast intents."""
        assert manifest.feature_store is not None and source_step.feature is not None
        definition = DomainCodec().decode_json(
            bundle.artifact(manifest.feature_store), FeatureStoreDefinition
        )
        vector = source_step.feature
        self.store.register(definition)
        self.store.append(
            definition,
            StoredFeature(
                definition_identity=definition.identity,
                vector=vector,
                source_version=scenario.source.identity,
                source_sha256=_CandidateAcceptance._sha(
                    DomainCodec().encode_json((scenario.source.identity, vector.input_identity))
                ),
                dataset_version=manifest.dataset.sha256,
                dataset_sha256=manifest.dataset.sha256,
                revision_identity=_CandidateAcceptance._sha(DomainCodec().encode_json(vector)),
            ),
        )
        version = f"{name}-selected-v1"
        snapshot = self.store.materialize(definition, version, vector.decision_at, (vector.entity,))
        self.store.activate(definition, version)
        offline = replace(
            source_deployment,
            name=f"{name}-offline",
            input_mode="offline_features",
            source_identity=snapshot.identity,
            feature_version=version,
        )
        registry = _CandidateAcceptance._registry(manifest.requirements)
        loader = CandidateLoader(components, registry)
        offline_session = CandidateSession(loader.load(bundle, offline))
        offline_step = CandidateFeatureFeed(self.store).evaluate(
            offline_session, vector.decision_at
        )
        assert source_step.status == offline_step.status == "decided"
        assert source_step.feature == offline_step.feature
        assert source_step.prediction == offline_step.prediction
        assert source_step.decision is not None and offline_step.decision is not None
        assert source_step.decision.intent == offline_step.decision.intent
        proof: dict[str, object] = {
            "snapshot": snapshot.identity,
            "source_offline_equal": True,
        }
        if self.bridge is None:
            return proof
        serving = FeastServingSnapshot.from_materialization(snapshot)
        self.bridge.materialize(serving, self.serving_root)
        online = replace(
            source_deployment,
            name=f"{name}-online",
            mode="runtime",
            input_mode="online_features",
            source_identity=snapshot.identity,
            feature_version=version,
        )
        online_session = CandidateSession(loader.load(bundle, online))
        online_feed = CandidateFeatureFeed(
            self.store, bridge=self.bridge, serving_root=self.serving_root
        )
        online_step = online_feed.evaluate(online_session, vector.decision_at)
        assert online_step.status == "decided"
        assert source_step.feature == online_step.feature
        assert source_step.prediction == online_step.prediction
        assert online_step.decision is not None
        assert source_step.decision.intent == online_step.decision.intent
        market_events = _PaperCandidateAcceptance._events(name, scenario, decision_second)
        paper, paper_step = _PaperCandidateAcceptance.run_online(
            root=self.root,
            name=name,
            case="online",
            bundle=bundle,
            deployment=online,
            components=components,
            registry=registry,
            scenario=scenario,
            feed=online_feed,
            decision_second=decision_second,
            events=market_events,
        )
        assert paper_step.status == "decided" and paper_step.decision is not None
        assert paper_step.feature == source_step.feature
        assert paper_step.prediction == source_step.prediction
        assert paper_step.decision.intent == source_step.decision.intent
        assert len(paper.orders) == len(paper.ledger.fills) == 1
        assert paper.checkpoint.candidate.policy.last_at == vector.decision_at
        assert paper.submission_attempted is False
        checkpoint = online_session.checkpoint()
        stale = online_feed.evaluate(online_session, vector.decision_at + timedelta(seconds=10))
        assert stale.status == "paused" and stale.checkpoint == checkpoint
        lost_session = CandidateSession(loader.load(bundle, online))
        unavailable = CandidateFeatureFeed(
            self.store, bridge=self.bridge, serving_root=self.root / "missing-serving"
        ).evaluate(lost_session, vector.decision_at)
        assert (
            unavailable.status == "paused" and unavailable.checkpoint == lost_session.checkpoint()
        )
        lost_paper, lost_step = _PaperCandidateAcceptance.run_online(
            root=self.root,
            name=name,
            case="service-loss",
            bundle=bundle,
            deployment=online,
            components=components,
            registry=registry,
            scenario=scenario,
            feed=CandidateFeatureFeed(
                self.store, bridge=self.bridge, serving_root=self.root / "missing-serving"
            ),
            decision_second=decision_second,
            events=market_events[:2],
        )
        assert lost_step.status == "paused" and lost_step.reason == "feature-service-unavailable"
        assert lost_paper.orders == () and lost_paper.ledger.fills == ()
        assert lost_paper.checkpoint.candidate.policy.last_at is None
        changed_version = f"{name}-changed-v2"
        self.store.materialize(definition, changed_version, vector.decision_at, (vector.entity,))
        self.store.activate(definition, changed_version)
        changed_session = CandidateSession(loader.load(bundle, online))
        changed = online_feed.evaluate(changed_session, vector.decision_at)
        assert changed.status == "paused" and changed.reason == "feature-version-changed"
        assert changed.checkpoint == changed_session.checkpoint()
        changed_paper, changed_step = _PaperCandidateAcceptance.run_online(
            root=self.root,
            name=name,
            case="version-change",
            bundle=bundle,
            deployment=online,
            components=components,
            registry=registry,
            scenario=scenario,
            feed=online_feed,
            decision_second=decision_second,
            events=market_events[:2],
        )
        assert changed_step.status == "paused" and changed_step.reason == "feature-version-changed"
        assert changed_paper.orders == () and changed_paper.ledger.fills == ()
        assert changed_paper.checkpoint.candidate.policy.last_at is None
        self.store.activate(definition, version)
        proof.update(
            source_offline_online_equal=True,
            online_paper_intent_equal=True,
            online_paper_fill_count=len(paper.ledger.fills),
            online_paper_service_loss_paused=True,
            online_paper_version_change_paused=True,
            stale_paused=True,
            service_loss_paused=True,
            version_change_paused=True,
        )
        return proof


class _PaperCandidateAcceptance:
    """Exercise packaged source candidates in dedicated paper and shadow accounts."""

    @staticmethod
    def _config(
        name: str, mode: Literal["paper", "shadow"], scenario: _ScenarioView
    ) -> PaperConfiguration:
        """Declare a finite, cash-backed local spot scenario for one candidate."""
        return PaperConfiguration(
            account=f"{name}-{mode}-account",
            mode=mode,
            initial_cash=Money(value=Decimal("1000"), currency=scenario.currency),
            maximum=scenario.quantity("10"),
            lot=scenario.quantity("1"),
            tick=scenario.price("0.01"),
            maximum_fee=Money(value=Decimal("1"), currency=scenario.currency),
            fee_rate=Decimal("0.002"),
            market_max_age_us=5_000_000,
        )

    @staticmethod
    def _events(
        name: str, scenario: _ScenarioView, decision_second: int
    ) -> tuple[PaperMarket | PaperTimer, ...]:
        """Place one authored timer between an eligible quote and later finite touches."""
        return (
            PaperMarket(
                identity=f"{name}-before",
                at=scenario.at(decision_second - 1),
                bid=scenario.price("98"),
                ask=scenario.price("100"),
                bid_quantity=scenario.quantity("5"),
                ask_quantity=scenario.quantity("5"),
            ),
            PaperTimer(identity=f"{name}-decision", at=scenario.at(decision_second)),
            PaperMarket(
                identity=f"{name}-entry",
                at=scenario.at(decision_second + 1),
                bid=scenario.price("98"),
                ask=scenario.price("100"),
                bid_quantity=scenario.quantity("5"),
                ask_quantity=scenario.quantity("1"),
            ),
            PaperMarket(
                identity=f"{name}-cross",
                at=scenario.at(decision_second + 2),
                bid=scenario.price("98"),
                ask=scenario.price("99"),
                bid_quantity=scenario.quantity("5"),
                ask_quantity=scenario.quantity("1"),
            ),
        )

    @classmethod
    def run_online(
        cls,
        *,
        root: Path,
        name: str,
        case: str,
        bundle: CandidateBundle,
        deployment: CandidateDeployment,
        components: CandidateComponents,
        registry: CapabilityRegistry,
        scenario: _ScenarioView,
        feed: CandidateFeatureFeed,
        decision_second: int,
        events: tuple[PaperMarket | PaperTimer, ...],
    ) -> tuple[PaperRunResult, CandidateStep]:
        """Run a pinned online candidate and reopen its durable timer decision."""
        config = cls._config(f"{name}-feast-{case}", "paper", scenario)
        journal_path = root / f"{name}-feast-{case}.sqlite3"
        result = run_paper(
            bundle,
            deployment,
            config,
            components=components,
            registry=registry,
            journal_path=journal_path,
            events=events,
            opened_at=scenario.at(decision_second - 1),
            owner=f"{name}-feast-{case}-owner",
            source=None,
            features=feed,
        )
        loaded = CandidateLoader(components, registry).load(bundle, deployment)
        journal = PaperOrderJournal(
            journal_path,
            account=config.account,
            instance=deployment.instance,
            binding_identity=PaperCandidateRuntime.binding(loaded, config),
            mode=config.mode,
            limits=SpotLimits(
                maximum=config.maximum, lot=config.lot, tick=config.tick, product="spot"
            ),
            ledger_state=LedgerState(
                initial_cash=config.initial_cash, dimension=config.maximum.dimension
            ),
        )
        saved = journal.step(f"timer:{name}-decision")
        assert saved is not None
        return result, DomainCodec().decode_json(saved.result_bytes, CandidateStep)

    @classmethod
    def exercise(
        cls,
        *,
        root: Path,
        name: str,
        bundle: CandidateBundle,
        deployment: CandidateDeployment,
        components: CandidateComponents,
        registry: CapabilityRegistry,
        scenario: _ScenarioView,
        source_step: CandidateStep,
        decision_second: int,
    ) -> dict[str, object]:
        """Compare pure decisions, exact fills and reopened journal economics."""
        events = cls._events(name, scenario, decision_second)
        opened_at = scenario.at(decision_second - 1)
        paper_config = cls._config(name, "paper", scenario)
        paper_path = root / f"{name}-paper.sqlite3"
        paper = run_paper(
            bundle,
            deployment,
            paper_config,
            components=components,
            registry=registry,
            journal_path=paper_path,
            events=events,
            opened_at=opened_at,
            owner=f"{name}-paper-first",
            source=scenario.source,
        )
        shadow = run_paper(
            bundle,
            deployment,
            cls._config(name, "shadow", scenario),
            components=components,
            registry=registry,
            journal_path=root / f"{name}-shadow.sqlite3",
            events=events,
            opened_at=opened_at,
            owner=f"{name}-shadow-first",
            source=scenario.source,
        )
        assert len(paper.orders) == len(shadow.orders) == 1
        paper_order, shadow_order = paper.orders[0], shadow.orders[0]
        assert paper_order.intent == shadow_order.intent
        assert paper_order.status == "filled" and shadow_order.status == "intent"
        assert source_step.decision is not None
        if isinstance(source_step.decision.intent, OrderIntent):
            assert source_step.decision.intent == paper_order.intent
        else:
            assert isinstance(source_step.decision.intent, TargetIntent)
            assert source_step.decision.intent.quantity == paper_order.intent.quantity
            assert paper_order.intent.time_in_force == "ioc"
        assert shadow.ledger.fills == ()
        (fill,) = paper.ledger.fills
        expected_price = Decimal("100" if name == "learned" else "99")
        expected_cash = Decimal("899.80" if name == "learned" else "900.80")
        assert fill.quantity.value == Decimal("1")
        assert fill.effective.value == expected_price
        assert fill.reference == fill.effective
        assert fill.fee.value == Decimal("0.20")
        balance = Ledger(paper.ledger).balance
        assert balance.cash.value == expected_cash
        assert balance.holding.value == Decimal("1")
        assert balance.fees.value == Decimal("0.20")
        assert paper.submission_attempted is False and shadow.submission_attempted is False
        restarted = run_paper(
            bundle,
            deployment,
            paper_config,
            components=components,
            registry=registry,
            journal_path=paper_path,
            events=events,
            opened_at=scenario.at(decision_second + 2),
            owner=f"{name}-paper-restarted",
            source=scenario.source,
        )
        assert restarted.ledger == paper.ledger
        assert restarted.orders == paper.orders
        assert restarted.checkpoint.order_sequence == paper.checkpoint.order_sequence
        return {
            "paper_shadow_intent_equal": True,
            "paper_status": paper_order.status,
            "shadow_status": shadow_order.status,
            "paper_fill_quantity": str(fill.quantity.value),
            "paper_fill_price": str(fill.effective.value),
            "paper_fee": str(fill.fee.value),
            "paper_cash": str(balance.cash.value),
            "shadow_zero_fills": True,
            "restart_no_duplicate_effects": True,
            "submission_attempted": False,
        }


def main() -> None:
    """Run retained packaging, replay/runtime parity and a fresh process continuation."""
    # The companion MR03 consumer is copied beside this script. Python -I can see
    # only its installed packages, so add this one explicit copied fixture directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    # third party library imports
    from decision_study import (
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
    implementation_payload = codec.encode_json(
        (
            (Path(__file__).parent / "decision_study.py").read_bytes(),
            Path(__file__).read_bytes(),
        )
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
        study = replace(
            selected_study,
            extensions=extensions,
        )
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
        loader.load(CandidateBundle(output / name), runtime)
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
        malformed["schema_version"] = "candidate-manifest-v2"
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
        summary[f"{name}_paper"] = _PaperCandidateAcceptance.exercise(
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
