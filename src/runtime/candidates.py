"""Load candidate components and commit intent-only decisions at compatible state boundaries."""

from __future__ import annotations

# standard library imports
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

# project library imports
from configuration import CandidateDeployment, CapabilityBinding, CapabilityRegistry
from research.experiments import CandidateDefinition, CandidateSource, ExperimentSpec
from research.features import (
    FeatureCheckpoint,
    FeatureKernel,
    FeatureSchema,
    FeatureSession,
    FeatureStoreDefinition,
    FeatureVector,
    FittedTransform,
    TransformVersion,
    VectorSignature,
)
from research.observations import DecisionInputs
from research.results import Prediction
from runtime.components import CandidateComponents
from runtime.identity import ImplementationIdentity
from serialization import DomainCodec, WireRecord
from strategies import (
    DecisionContext,
    DecisionLifecycle,
    DecisionPolicy,
    DecisionRecord,
    DecisionSession,
    DecisionState,
    OrderIntent,
    QuoteIntent,
    StrategyEvent,
)

if TYPE_CHECKING:
    # project library imports
    from research.models import EstimatorLifecycle, EstimatorVersion
    from research.studies import ChartDefinition, MetricDefinition


@dataclass(frozen=True)
class LoadedCandidate:
    """Keep verified definitions and reconstructed components bound to one placement."""

    definition: CandidateDefinition
    deployment: CandidateDeployment
    capabilities: tuple[CapabilityBinding, ...]
    feature: FeatureKernel
    policy: DecisionPolicy
    transform: FittedTransform | None
    transform_version: TransformVersion | None
    estimator: EstimatorLifecycle | None
    estimator_version: EstimatorVersion | None
    store_definition: FeatureStoreDefinition | None
    metrics: tuple[MetricDefinition, ...]
    charts: tuple[ChartDefinition, ...]

    @property
    def identity(self) -> str:
        """Pin the resolved capability profiles as well as the candidate and placement."""
        return hashlib.sha256(
            DomainCodec().encode_json((self.deployment.identity, self.capabilities))
        ).hexdigest()


class CandidateLoader:
    """Reject incompatible artifacts, factories and environment before source or serving I/O."""

    def __init__(self, components: CandidateComponents, registry: CapabilityRegistry) -> None:
        """Bind reviewed installed factories and environment-owned adapter declarations."""
        self._components = components
        self._registry = registry

    def load(self, source: CandidateSource, deployment: CandidateDeployment) -> LoadedCandidate:
        """Verify a candidate definition and reconstruct its exact selected components.

        The source is a provenance-verified ``CandidateBundle`` or an application's
        in-memory ``CandidateObjects``; admitting the source kind is the caller's
        decision.

        Raises:
            ValueError: Identity, environment, schema, signature or capability admission fails.
            OSError: A retained candidate artifact cannot be read.

        Returns:
            A local intent-only binding. This neither installs code nor authorizes orders.
        """
        # project library imports
        from research.models import EstimatorLifecycle, EstimatorVersion

        definition = source.definition()
        deployment.__post_init__()
        if (
            definition.identity != deployment.candidate_identity
            or deployment.entity not in definition.entities
            or deployment.starts_at < definition.available_at
            or definition.code_sha256 != ImplementationIdentity.sha256()
            or definition.environment_sha256 != ExperimentSpec.installed_environment()
        ):
            raise ValueError(
                "candidate identity, entity, availability or installed environment differs"
            )
        bindings = self._registry.resolve(
            definition.requirements, deployment.selections, mode=deployment.mode
        )
        if {requirement.kind for requirement in definition.requirements} != {
            "market_data",
            "reference_data",
            "calendar",
            "valuation",
            "account",
            "execution",
        }:
            raise ValueError("candidate requires all six capability domains")
        for requirement in definition.requirements:
            if (
                requirement.product != definition.product
                or requirement.calendar != definition.calendar
            ):
                raise ValueError("candidate product/calendar differs from capability requirements")
        codec = DomainCodec()
        schema = codec.decode_json(source.artifact(definition.feature_schema), FeatureSchema)
        if schema.inputs != definition.inputs or schema.mode != definition.state.feature_mode:
            raise ValueError("candidate feature inputs or lifecycle differ")
        self._admit_inputs(definition)
        self._components.admit(definition.components)
        feature_spec = next(c for c in definition.components if c.role == "feature")
        policy_spec = next(c for c in definition.components if c.role == "policy")
        feature = self._components.feature(
            feature_spec, schema, source.artifact(feature_spec.parameters)
        )
        policy = self._components.policy(policy_spec, source.artifact(policy_spec.parameters))
        if policy.output != definition.output:
            raise ValueError("candidate policy output differs from declared intent family")
        transform, transform_version = None, None
        if definition.transform is not None:
            transform_version = codec.decode_json(
                source.artifact(definition.transform), TransformVersion
            )
            selected = next(c for c in definition.components if c.role == "transform")
            transform = FittedTransform(
                self._components.transform(selected, source.artifact(selected.parameters))
            )
            if transform.identity != transform_version.implementation:
                raise ValueError("candidate transform differs from its fitted implementation")
        signature = VectorSignature(
            definition=schema.identity, fields=schema.outputs, transform_identity=None
        )
        if transform_version is not None:
            if (
                transform_version.signature != signature
                or transform_version.available_at > deployment.starts_at
            ):
                raise ValueError("candidate transform signature or availability differs")
            signature = VectorSignature(
                definition=schema.identity,
                fields=transform_version.output_fields,
                transform_identity=transform_version.identity,
            )
        estimator, estimator_version = None, None
        if definition.estimator is not None:
            estimator_version = codec.decode_json(
                source.artifact(definition.estimator), EstimatorVersion
            )
            selected = next(c for c in definition.components if c.role == "estimator")
            estimator = EstimatorLifecycle(
                self._components.estimator(selected, source.artifact(selected.parameters))
            )
            if (
                estimator.identity != estimator_version.implementation
                or estimator_version.signature != signature
                or estimator_version.available_at > deployment.starts_at
            ):
                raise ValueError(
                    "candidate estimator implementation, signature or availability differs"
                )
        policy.admit(
            signature.fields, None if estimator_version is None else estimator_version.output
        )
        store_definition = None
        if definition.feature_store is not None:
            store_definition = codec.decode_json(
                source.artifact(definition.feature_store), FeatureStoreDefinition
            )
            if (
                store_definition.schema != schema
                or store_definition.transform_identity != signature.transform_identity
                or store_definition.fields != signature.fields
                or (
                    schema.mode == "incremental"
                    and store_definition.instance != deployment.instance
                )
            ):
                raise ValueError("candidate feature store definition differs from selected state")
        if deployment.input_mode != "source" and store_definition is None:
            raise ValueError("candidate serving requires a packaged feature-store definition")
        if (
            definition.state.on_restart == "restore"
            and definition.state.checkpoint_schema != "candidate-checkpoint"
        ):
            raise ValueError("candidate checkpoint schema is unsupported")
        return LoadedCandidate(
            definition=definition,
            deployment=deployment,
            capabilities=bindings,
            feature=feature,
            policy=policy,
            transform=transform,
            transform_version=transform_version,
            estimator=estimator,
            estimator_version=estimator_version,
            store_definition=store_definition,
            metrics=tuple(
                self._components.metric(c, source.artifact(c.parameters))
                for c in definition.components
                if c.role == "metric"
            ),
            charts=tuple(
                self._components.chart(c, source.artifact(c.parameters))
                for c in definition.components
                if c.role == "chart"
            ),
        )

    @staticmethod
    def _admit_inputs(definition: CandidateDefinition) -> None:
        """Require exact input fields, clocks and freshness plus declared intent operations."""
        for item in definition.inputs:
            matches = tuple(r for r in definition.requirements if r.name == item.name)
            if len(matches) != 1:
                raise ValueError("candidate input lacks a unique capability requirement")
            requirement = matches[0]
            if (
                requirement.kind
                != ("reference_data" if item.family == "reference" else "market_data")
                or requirement.channel != item.family
                or requirement.clock != item.clock
                or requirement.max_freshness_us is None
                or requirement.max_freshness_us > item.max_age_us
                or not any(
                    field.name == item.field.name and field.units == item.field.units
                    for field in requirement.fields
                )
            ):
                raise ValueError("candidate input capability signature/freshness differs")
        execution = tuple(r for r in definition.requirements if r.kind == "execution")
        if len(execution) != 1 or f"intent:{definition.output}" not in execution[0].operations:
            raise ValueError("candidate execution boundary cannot consume its intent family")


class CandidateCheckpoint(WireRecord, frozen=True):
    """Bind both state machines to exact placement, component profiles and completed cutoff."""

    binding_identity: str
    feature: FeatureCheckpoint | None
    policy: DecisionState
    observations: int
    sha256: str
    schema_version: Literal["candidate-checkpoint"] = "candidate-checkpoint"

    def __post_init__(self) -> None:
        """Reject disconnected state clocks and unsupported schema versions."""
        if (
            self.schema_version != "candidate-checkpoint"
            or self.binding_identity != self.policy.run_identity
            or type(self.observations) is not int
            or self.observations < 0
            or self.sha256
            != self.digest(self.binding_identity, self.feature, self.policy, self.observations)
        ):
            raise ValueError("invalid candidate checkpoint binding/count")
        self.policy.__post_init__()
        if self.feature is not None:
            self.feature.__post_init__()
            if self.feature.last_at != self.policy.last_at:
                raise ValueError("candidate feature and policy checkpoints disagree")

    @staticmethod
    def digest(
        binding_identity: str,
        feature: FeatureCheckpoint | None,
        policy: DecisionState,
        observations: int,
    ) -> str:
        """Bind the full continuation, including warm-up count, to one integrity digest."""
        return hashlib.sha256(
            DomainCodec().encode_json((binding_identity, feature, policy, observations))
        ).hexdigest()

    @classmethod
    def create(
        cls,
        *,
        binding_identity: str,
        feature: FeatureCheckpoint | None,
        policy: DecisionState,
        observations: int,
    ) -> CandidateCheckpoint:
        """Capture state only after both machines pass validation at the same boundary."""
        return cls(
            binding_identity=binding_identity,
            feature=feature,
            policy=policy,
            observations=observations,
            sha256=cls.digest(binding_identity, feature, policy, observations),
        )


class CandidateStep(WireRecord, frozen=True):
    """Retain an emitted intent or explicit pause with the atomic continuation state."""

    status: Literal["decided", "warming", "paused"]
    reason: str
    at: datetime
    feature: FeatureVector | None
    prediction: Prediction | None
    decision: DecisionRecord | None
    checkpoint: CandidateCheckpoint

    def __post_init__(self) -> None:
        """Reject status/intent disagreement and missing trace lineage."""
        self._require_utc(self.at, field_name="step time")
        self.checkpoint.__post_init__()
        if self.status not in ("decided", "warming", "paused") or not self.reason:
            raise ValueError("invalid candidate step status")
        if (self.status == "decided") != (self.decision is not None):
            raise ValueError("candidate step intent differs from status")
        if self.feature is not None:
            self.feature.require_available(self.at)
        if self.status == "paused" and (self.feature is not None or self.prediction is not None):
            raise ValueError("paused candidate cannot retain an uncommitted inference")
        if self.status != "paused" and (
            self.feature is None or self.checkpoint.policy.last_at != self.at
        ):
            raise ValueError("candidate step lacks a committed feature/cutoff")
        if self.prediction is not None:
            self.prediction.__post_init__()
            if self.feature is None:
                raise ValueError("candidate prediction requires its feature vector")
            DecisionContext(features=self.feature, prediction=self.prediction, evaluated_at=self.at)
        if self.decision is not None:
            self.decision.__post_init__()
            if (
                self.feature is None
                or self.decision.feature_identity != self.feature.identity
                or self.decision.at != self.at
                or self.decision.model_identity
                != (None if self.prediction is None else self.prediction.model_identity)
            ):
                raise ValueError("candidate step feature/decision lineage differs")


class CandidateSession:
    """Stage pure feature/model/policy transitions and commit only a fully admitted intent.

    The session has no account client, order transport or fitting method. The
    application owns scheduling and durable checkpoint storage. A serving pause
    or invalid transition leaves both state machines unchanged.
    """

    def __init__(
        self,
        loaded: LoadedCandidate,
        checkpoint: CandidateCheckpoint | None = None,
        *,
        continuing: bool = False,
    ) -> None:
        """Start one isolated instance or restore an exactly matching continuation.

        ``continuing`` resumes state committed earlier in the same run, which a
        caller that keeps no in-memory session reloads at every step. Restoring
        across a restart (the default) requires the ``restore`` restart rule.
        """
        self.loaded = loaded
        self._identity = loaded.identity
        if checkpoint is not None:
            checkpoint.__post_init__()
            if checkpoint.binding_identity != self._identity:
                raise ValueError("candidate checkpoint belongs to another binding")
            if not continuing and loaded.definition.state.on_restart != "restore":
                raise ValueError(
                    "candidate requires an explicit reset instead of checkpoint restore"
                )
            if (checkpoint.feature is None) != (loaded.deployment.input_mode != "source"):
                raise ValueError("candidate checkpoint input mode differs")
        features = FeatureSession(
            loaded.feature,
            instance=loaded.deployment.instance,
            entity=loaded.deployment.entity,
            checkpoint=None if checkpoint is None else checkpoint.feature,
        )
        policy = self._policy(None if checkpoint is None else checkpoint.policy)
        self._checkpoint = CandidateCheckpoint.create(
            binding_identity=self._identity,
            feature=(features.checkpoint() if loaded.deployment.input_mode == "source" else None),
            policy=policy.checkpoint(),
            observations=0 if checkpoint is None else checkpoint.observations,
        )

    def checkpoint(self) -> CandidateCheckpoint:
        """Return immutable committed state for caller-owned durable retention."""
        return self._checkpoint

    def handle_event(self, event: StrategyEvent) -> CandidateCheckpoint:
        """Stage an optional pure lifecycle callback without advancing the decision clock.

        The supervisor persists the returned checkpoint with the triggering event.
        Invalid successor bytes leave the session unchanged. Policies implementing
        only the decision contract retain their existing state.
        """
        event.__post_init__()
        previous = self._checkpoint
        if previous.policy.last_at is not None and event.at < previous.policy.last_at:
            raise ValueError("lifecycle event predates the committed decision")
        policy = self.loaded.policy
        if isinstance(policy, DecisionLifecycle):
            state = policy.on_event(event, previous.policy.state)
            if type(state) is not bytes:
                raise TypeError("lifecycle state must be immutable bytes")
            policy.validate_state(state)
            continuation = DecisionState(
                run_identity=self._identity,
                last_at=previous.policy.last_at,
                state=state,
                sha256=DecisionState.digest(self._identity, previous.policy.last_at, state),
            )
            self._checkpoint = CandidateCheckpoint.create(
                binding_identity=self._identity,
                feature=previous.feature,
                policy=continuation,
                observations=previous.observations,
            )
        return self._checkpoint

    def pause(self, at: datetime, reason: str) -> CandidateStep:
        """Report unavailable input without advancing either state machine."""
        return CandidateStep(
            status="paused",
            reason=reason,
            at=at,
            feature=None,
            prediction=None,
            decision=None,
            checkpoint=self._checkpoint,
        )

    def evaluate_inputs(self, inputs: DecisionInputs) -> CandidateStep:
        """Compute candidate features and commit the resulting intent atomically."""
        if self.loaded.deployment.input_mode != "source":
            raise ValueError("candidate binding expects feature-store values")
        if self._is_gap(inputs.decision_at) and self.loaded.definition.state.on_gap == "pause":
            return self.pause(inputs.decision_at, "input-gap")
        previous = self._continuation(inputs.decision_at)
        features = FeatureSession(
            self.loaded.feature,
            instance=self.loaded.deployment.instance,
            entity=self.loaded.deployment.entity,
            checkpoint=None if previous is None else previous.feature,
        )
        vector = features.evaluate(inputs)
        if self.loaded.transform is not None and self.loaded.transform_version is not None:
            vector = self.loaded.transform.apply(self.loaded.transform_version, vector)
        return self._commit(vector, inputs.decision_at, features.checkpoint(), previous)

    def evaluate_feature(self, vector: FeatureVector, at: datetime) -> CandidateStep:
        """Consume an already transformed versioned store value without rewriting its clocks."""
        if self.loaded.deployment.input_mode == "source":
            raise ValueError("candidate binding expects source inputs")
        if self._is_gap(at) and self.loaded.definition.state.on_gap == "pause":
            return self.pause(at, "input-gap")
        return self._commit(vector, at, None, self._continuation(at))

    def _continuation(self, at: datetime) -> CandidateCheckpoint | None:
        """Keep committed state unless a gap requires the declared reset."""
        if self._is_gap(at) and self.loaded.definition.state.on_gap == "reset":
            return None
        return self._checkpoint

    def _is_gap(self, at: datetime) -> bool:
        """Validate schedule and detect a missed cadence before any state mutation."""
        self.admit_cutoff(at)
        last = self._checkpoint.policy.last_at
        return at > (
            self.loaded.deployment.starts_at
            if last is None
            else last + timedelta(microseconds=self.loaded.definition.cadence_us)
        )

    def admit_cutoff(self, at: datetime, *, include_committed: bool = False) -> None:
        """Reject an incompatible schedule before source access; optionally admit a saved prefix."""
        CandidateStep._require_utc(at, field_name="decision time")
        deployment = self.loaded.deployment
        cadence = timedelta(microseconds=self.loaded.definition.cadence_us)
        last = self._checkpoint.policy.last_at
        if (
            at < deployment.starts_at
            or (at - deployment.starts_at) % cadence != timedelta(0)
            or (not include_committed and last is not None and at <= last)
        ):
            raise ValueError("candidate decision is outside its monotonic cadence")

    def _policy(self, checkpoint: DecisionState | None) -> DecisionSession:
        """Create a staged policy session; failed transitions cannot mutate committed bytes."""
        return DecisionSession(
            self.loaded.policy,
            run_identity=self._identity,
            instance=self.loaded.deployment.instance,
            entity=self.loaded.deployment.entity,
            checkpoint=checkpoint,
        )

    def _commit(
        self,
        vector: FeatureVector,
        at: datetime,
        feature: FeatureCheckpoint | None,
        previous: CandidateCheckpoint | None,
    ) -> CandidateStep:
        """Validate signatures, predictions and order types before committing state."""
        vector.require_available(at)
        definition = self.loaded.store_definition
        expected = VectorSignature(
            definition=self.loaded.feature.schema.identity,
            fields=(
                self.loaded.feature.schema.outputs
                if self.loaded.transform_version is None
                else self.loaded.transform_version.output_fields
            ),
            transform_identity=None
            if self.loaded.transform_version is None
            else self.loaded.transform_version.identity,
        )
        if VectorSignature.of(vector) != expected or vector.entity != self.loaded.deployment.entity:
            raise ValueError("candidate feature signature or entity differs")
        if (
            definition is not None
            and self.loaded.deployment.input_mode != "source"
            and vector.fields != definition.fields
        ):
            raise ValueError("candidate store signature differs")
        prediction = None
        if self.loaded.estimator is not None and self.loaded.estimator_version is not None:
            prediction = self.loaded.estimator.predict(self.loaded.estimator_version, vector)
        policy = self._policy(None if previous is None else previous.policy)
        record = policy.evaluate(
            DecisionContext(features=vector, prediction=prediction, evaluated_at=at)
        )
        intent = record.intent
        orders = (
            (intent,)
            if isinstance(intent, OrderIntent)
            else (intent.bid, intent.ask)
            if isinstance(intent, QuoteIntent)
            else ()
        )
        execution = next(r for r in self.loaded.definition.requirements if r.kind == "execution")
        if any(order.time_in_force not in execution.order_types for order in orders):
            raise ValueError("candidate policy emitted an undeclared order type")
        count = (0 if previous is None else previous.observations) + 1
        checkpoint = CandidateCheckpoint.create(
            binding_identity=self._identity,
            feature=feature,
            policy=policy.checkpoint(),
            observations=count,
        )
        warming = count <= self.loaded.definition.state.warmup_observations
        result = CandidateStep(
            status="warming" if warming else "decided",
            reason="warmup" if warming else "candidate-intent",
            at=at,
            feature=vector,
            prediction=prediction,
            decision=None if warming else record,
            checkpoint=checkpoint,
        )
        self._checkpoint = checkpoint
        return result
