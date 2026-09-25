"""Publish, admit, and resume installed candidate bundles for workflow acceptance."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

# third party library imports
import msgspec

# project library imports
from applications.explore import run_candidate
from configuration import (
    CandidateDeployment,
    CapabilityField,
    CapabilityProfile,
    CapabilityRegistry,
    CapabilityRequirement,
    CapabilitySelection,
    UniverseSelection,
)
from financial_units import Currency, Dimension, Price, Quantity
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
)
from research.features import FeatureSchema, FeatureStoreDefinition
from research.observations import DecisionInputs, InputRequirement, NumericHistorySource
from research.studies import DecisionStudy, StudyResult
from runtime import (
    CandidateCheckpoint,
    CandidateComponents,
    CandidateStep,
    ImplementationIdentity,
)
from serialization import DomainCodec
from strategies import OrderIntent, TargetIntent


class _ScenarioView(Protocol):
    """Describe the authored scenario surface shared by candidate acceptance paths."""

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
    """Own candidate evidence construction and verification for installed workflows."""

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
                CapabilitySelection(name=requirement.name, profile=f"fixture-{requirement.name}")
                for requirement in manifest.requirements
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
