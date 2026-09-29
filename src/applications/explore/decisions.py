"""Compose named features, reload-only models and decision policies for retained research."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

# project library imports
from configuration import DecisionRun
from research.experiments import (
    AttemptHistory,
    AttemptStore,
    ExperimentSpec,
    Fingerprint,
    TimeWindow,
)
from research.features import (
    FeatureCheckpoint,
    FeatureKernel,
    FeatureSession,
    FeatureVector,
    FittedTransform,
    TransformVersion,
    VectorSignature,
)
from research.models import EstimatorLifecycle, EstimatorVersion
from research.observations import DecisionSource
from research.results import Prediction
from runtime import ImplementationIdentity
from serialization import DomainCodec, WireRecord
from strategies import (
    DecisionContext,
    DecisionPolicy,
    DecisionRecord,
    DecisionSession,
    DecisionState,
)


class DecisionCheckpoint(WireRecord, frozen=True):
    """Retain both feature and strategy state at the same committed decision boundary."""

    run_identity: str
    implementation: str
    feature: FeatureCheckpoint
    policy: DecisionState

    def __post_init__(self) -> None:
        """Reject mismatched cutoffs and run identities before either state is loaded."""
        self.feature.__post_init__()
        self.policy.__post_init__()
        if (
            self.run_identity != self.policy.run_identity
            or self.feature.last_at != self.policy.last_at
            or type(self.implementation) is not str
            or not self.implementation
        ):
            raise ValueError("decision checkpoint bindings or cutoffs differ")


class DecisionResult(WireRecord, frozen=True):
    """Retain versioned feature/prediction/intent traces and an exact restart boundary."""

    config: DecisionRun
    features: tuple[FeatureVector, ...]
    predictions: tuple[Prediction, ...]
    decisions: tuple[DecisionRecord, ...]
    checkpoint: DecisionCheckpoint

    def __post_init__(self) -> None:
        """Refuse disconnected trace rows and incompatible state/configuration."""
        self.config.__post_init__()
        self.checkpoint.__post_init__()
        if (
            self.checkpoint.run_identity != self.config.identity
            or any(type(v) is not tuple for v in (self.features, self.predictions, self.decisions))
            or len(self.features) != len(self.decisions)
        ):
            raise ValueError("invalid decision result")
        for feature, decision in zip(self.features, self.decisions, strict=True):
            feature.__post_init__()
            decision.__post_init__()
            if (
                decision.feature_identity != feature.identity
                or decision.instance != self.config.instance
                or decision.entity != self.config.entity
                or decision.at != feature.decision_at
            ):
                raise ValueError("decision trace lineage mismatch")
        if self.config.model_identity is None and self.predictions:
            raise ValueError("rule-only result cannot contain model predictions")
        if self.config.model_identity is not None:
            if len(self.predictions) != len(self.features):
                raise ValueError("learned result requires one prediction per feature")
            for prediction, feature, decision in zip(
                self.predictions, self.features, self.decisions, strict=True
            ):
                prediction.__post_init__()
                if (
                    prediction.feature_identity,
                    prediction.entity,
                    prediction.decision_at,
                    prediction.model_identity,
                ) != (
                    feature.identity,
                    feature.entity,
                    feature.decision_at,
                    self.config.model_identity,
                ) or decision.model_identity != prediction.model_identity:
                    raise ValueError("retained prediction lineage mismatch")
        for decision in self.decisions:
            if (
                decision.at not in self.config.decisions
                or decision.policy != self.config.policy_identity
            ):
                raise ValueError("retained decision differs from selected schedule/policy")
        if any(left.at >= right.at for left, right in zip(self.decisions, self.decisions[1:])):
            raise ValueError("retained decisions must strictly advance")
        if self.decisions and self.decisions[-1].at != self.checkpoint.policy.last_at:
            raise ValueError("checkpoint does not end at the final decision")


def run_decisions(
    config: DecisionRun,
    *,
    source: DecisionSource,
    feature: FeatureKernel,
    policy: DecisionPolicy,
    capabilities: tuple[str, ...],
    model: EstimatorLifecycle | None = None,
    model_version: EstimatorVersion | None = None,
    transform: FittedTransform | None = None,
    transform_version: TransformVersion | None = None,
    checkpoint: DecisionCheckpoint | None = None,
    stop_after: int | None = None,
) -> DecisionResult:
    """Admit selected components and run a bounded schedule without fitting or submission.

    Args:
        config: Resolved versioned selection and complete schedule; JSON uses DomainCodec.
        source: Explicit causal input adapter with pinned source identity.
        feature: Selected pure feature transition; no fallback implementation is selected.
        policy: Selected pure rule or prediction-to-intent transition.
        capabilities: Declared installed product/calendar/output and input capabilities.
        model: Optional inference adapter paired with model_version.
        model_version: Exact fitted state, never constructed implicitly during inference.
        transform: Optional preprocessing adapter paired with transform_version.
        transform_version: Exact train-only fitted transform state.
        checkpoint: Same-run state from a completed prefix; incompatible bytes fail.
        stop_after: Optional positive prefix length for a bounded checkpoint run.

    Returns:
        Actual vectors, predictions, decisions and one atomic continuation boundary.
        These are research intents, not fills, P&L, accepted candidates or live orders.

    Raises:
        ValueError: Admission, clocks, signatures, state or capabilities disagree.
        OSError: Retained source bytes cannot be read.
    """
    config.admit(capabilities)
    feature.schema.__post_init__()
    required = {f"input:{r.family}" for r in feature.schema.inputs} | {
        f"feature:{feature.schema.mode}"
    }
    if not required <= set(capabilities):
        raise ValueError("missing feature/input lifecycle capability")
    if (config.source_identity, config.feature_identity, config.policy_identity, config.output) != (
        source.identity,
        feature.schema.identity,
        policy.identity,
        policy.output,
    ) or source.requirements != feature.schema.inputs:
        raise ValueError("selected component identities or signatures differ")
    if (model is None) != (model_version is None) or (transform is None) != (
        transform_version is None
    ):
        raise ValueError("fitted adapters require their state versions")
    if config.model_identity != (
        None if model_version is None else model_version.identity
    ) or config.transform_identity != (
        None if transform_version is None else transform_version.identity
    ):
        raise ValueError("selected fitted component version mismatch")
    if (
        model is not None
        and model_version is not None
        and model.identity != model_version.implementation
    ):
        raise ValueError("estimator adapter differs from selected fitted state")
    if (
        transform is not None
        and transform_version is not None
        and transform.identity != transform_version.implementation
    ):
        raise ValueError("transform adapter differs from selected fitted state")
    signature = VectorSignature(
        definition=feature.schema.identity, fields=feature.schema.outputs, transform_identity=None
    )
    if transform_version is not None:
        if (
            transform_version.signature != signature
            or transform_version.available_at > config.decisions[0]
        ):
            raise ValueError("transform signature or availability incompatible before work")
        signature = VectorSignature(
            definition=signature.definition,
            fields=transform_version.output_fields,
            transform_identity=transform_version.identity,
        )
    if model_version is not None and (
        model_version.signature != signature or model_version.available_at > config.decisions[0]
    ):
        raise ValueError("model signature or availability incompatible before work")
    policy.admit(signature.fields, None if model_version is None else model_version.output)
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError("stop_after must be positive")
    implementation = ImplementationIdentity.sha256()
    if checkpoint is not None:
        checkpoint.__post_init__()
        if (
            checkpoint.run_identity != config.identity
            or checkpoint.implementation != implementation
            or checkpoint.policy.last_at not in config.decisions
        ):
            raise ValueError("checkpoint run, implementation or schedule mismatch")
    features = FeatureSession(
        feature,
        instance=config.instance,
        entity=config.entity,
        checkpoint=None if checkpoint is None else checkpoint.feature,
    )
    decisions = DecisionSession(
        policy,
        run_identity=config.identity,
        instance=config.instance,
        entity=config.entity,
        checkpoint=None if checkpoint is None else checkpoint.policy,
    )
    vectors: list[FeatureVector] = []
    predictions: list[Prediction] = []
    records: list[DecisionRecord] = []
    for at in config.decisions:
        if (
            checkpoint is not None
            and checkpoint.policy.last_at is not None
            and at <= checkpoint.policy.last_at
        ):
            continue
        vector = features.evaluate(source.read(config.entity, at))
        if transform is not None and transform_version is not None:
            vector = transform.apply(transform_version, vector)
        prediction = None
        if model is not None and model_version is not None:
            prediction = model.predict(model_version, vector)
            predictions.append(prediction)
        record = decisions.evaluate(DecisionContext(features=vector, prediction=prediction))
        vectors.append(vector)
        records.append(record)
        if stop_after is not None and len(records) == stop_after:
            break
    return DecisionResult(
        config=config,
        features=tuple(vectors),
        predictions=tuple(predictions),
        decisions=tuple(records),
        checkpoint=DecisionCheckpoint(
            run_identity=config.identity,
            implementation=implementation,
            feature=features.checkpoint(),
            policy=decisions.checkpoint(),
        ),
    )


def inspect_decisions(
    config: DecisionRun,
    *,
    source: DecisionSource,
    feature: FeatureKernel,
    policy: DecisionPolicy,
    capabilities: tuple[str, ...],
    attempts: Path,
    family: str,
    model: EstimatorLifecycle | None = None,
    model_version: EstimatorVersion | None = None,
    transform: FittedTransform | None = None,
    transform_version: TransformVersion | None = None,
) -> AttemptHistory:
    """Retain the engineering decision workload through the existing append-only attempt store.

    This explicitly local reference consumer records configuration and fitted bytes,
    completed traces or failed attempts. Formal study evaluation, holdout consumption,
    reports and remote publication remain owned by the existing study applications.
    """
    config.__post_init__()
    codec = DomainCodec()
    request = codec.encode_json(
        (config, feature.schema, model_version, transform_version, capabilities)
    )
    spec = ExperimentSpec(
        schema_version="experiment-engineering-sample",
        family=family,
        inputs=(Fingerprint(name="source", sha256=config.source_identity),),
        components=(
            Fingerprint(name="implementation", sha256=ImplementationIdentity.sha256()),
            Fingerprint(name="selection", sha256=hashlib.sha256(request).hexdigest()),
        ),
        parameters=(),
        seeds=(),
        environment_sha256=ExperimentSpec.installed_environment(),
        split=None,
        engineering_sample=TimeWindow(
            start=config.decisions[0], end=config.decisions[-1] + timedelta(microseconds=1)
        ),
    )
    with AttemptStore(attempts) as store:
        start = store.start(
            spec,
            request=request,
            invocation="applications.explore.inspect_decisions",
            at=datetime.now(UTC),
        )
        try:
            result = run_decisions(
                config,
                source=source,
                feature=feature,
                policy=policy,
                capabilities=capabilities,
                model=model,
                model_version=model_version,
                transform=transform,
                transform_version=transform_version,
            )
        except Exception as error:
            store.finish(
                start.attempt_id,
                status="failed",
                reason=f"{type(error).__name__}: {error}",
                at=datetime.now(UTC),
            )
            raise
        return store.finish(
            start.attempt_id,
            status="completed",
            reason="research decision workload; no execution or empirical acceptance",
            result=codec.encode_json(result),
            at=datetime.now(UTC),
        )
