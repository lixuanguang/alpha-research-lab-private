"""Compose verified diagnostics, exact model lifecycle, retained evaluation and ClearML."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

# project library imports
from research.experiments import AttemptHistory, AttemptStore, ExperimentSpec
from research.models import EstimatorRegistry, ModelStudy, ModelVersion
from research.studies import (
    ClearMLDestination,
    ClearMLPublication,
    PublicationReceipt,
    TrackedModel,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec


def evaluate_model(
    config: Path,
    *,
    attempts: Path,
    tracking: ClearMLDestination,
    registry: EstimatorRegistry | None = None,
) -> AttemptHistory:
    """Construct or reload configured model state, evaluate and publish the retained attempt.

    Args:
        config: Strict non-secret ModelStudy JSON, at most one MiB.
        attempts: Complete local single-writer history, feature results and model bytes.
        tracking: Required formal-workflow destination; credentials remain SDK configuration.
        registry: Optional estimator registry; the default supplies the installed model.

    Returns:
        Immutable completed or empirically rejected attempt; model/evaluation bytes remain retained.

    Raises:
        ValueError: Configuration, input, fitting, holdout or evaluation contract is violated.
        Exception: Computation or publication fails; retained evidence and intent survive.
    """
    codec = DomainCodec()
    with config.open("rb") as source:
        payload = source.read(1_048_577)
    if len(payload) > 1_048_576:
        raise ValueError("model study config exceeds one MiB")
    study = codec.decode_json(payload, ModelStudy)
    resolved_registry = EstimatorRegistry() if registry is None else registry
    spec = study.specification(
        implementation=ImplementationIdentity.sha256(),
        environment=ExperimentSpec.installed_environment(),
    )
    with AttemptStore(attempts) as store:
        publication = ClearMLPublication(store, tracking)
        before = {history.start.attempt_id for history in store.histories()}
        try:
            start = store.start(
                spec,
                at=datetime.now(UTC),
                invocation="applications.explore.evaluate_model",
                request=payload,
            )
        except ValueError:
            # start retains changed-holdout rejection before raising; enqueue that
            # exact new attempt as well, without replacing its original exception.
            for history in store.histories():
                if history.start.attempt_id not in before:
                    publication.enqueue(history.start.attempt_id)
                    publication.publish(history.start.attempt_id)
            raise
        publication.enqueue(start.attempt_id)
        try:
            if study.partition == "holdout":
                try:
                    store.consume_holdout(
                        start.attempt_id, at=datetime.now(UTC), reason=study.selection_reason
                    )
                except ValueError as error:
                    store.finish(
                        start.attempt_id, status="rejected", at=datetime.now(UTC), reason=str(error)
                    )
                    raise
            dataset = study.dataset(store)
            versions: tuple[ModelVersion, ...]
            if study.definition is not None and study.available_at is not None:
                estimator = study.resolve_estimator(resolved_registry)
                model = estimator.construct(
                    study.definition,
                    dataset,
                    study.split,
                    attempt_id=start.attempt_id,
                    created_at=datetime.now(UTC),
                    available_at=study.available_at,
                )
                store.retain(start.attempt_id, "model-version", codec.encode_json(model))
                versions = (model,)
            else:
                versions = study.reload(store)
                if not versions:
                    raise ValueError("model study reload returned no model versions")
                estimator = resolved_registry.resolve(
                    study.estimator_implementation, versions[0].definition
                )
            store.retain(
                start.attempt_id,
                "tracked-models",
                codec.encode_json(
                    tuple(
                        TrackedModel(
                            version_sha256=model.identity,
                            state_sha256=model.state_sha256,
                            state_bytes=model.state_bytes,
                            manifest_bytes=codec.encode_json(model),
                            creation_attempt=model.creation_attempt,
                        )
                        for model in versions
                    )
                ),
            )
            evaluation = estimator.evaluate(
                versions,
                dataset,
                study.split,
                partition=study.partition,
                known_at=study.known_at,
                max_mse=study.max_mse,
                reason=study.selection_reason,
            )
            result = codec.encode_json(evaluation)
            store.retain(start.attempt_id, "evaluation", result)
            status: Literal["completed", "rejected"] = (
                "completed" if evaluation.selection == "accepted" else "rejected"
            )
            store.finish(
                start.attempt_id,
                status=status,
                at=datetime.now(UTC),
                reason=evaluation.reason,
                result=result if status == "completed" else None,
            )
        except (Exception, KeyboardInterrupt) as error:
            if store.read(start.attempt_id).status == "incomplete":
                store.finish(
                    start.attempt_id,
                    status="abandoned" if isinstance(error, KeyboardInterrupt) else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            publication.publish(start.attempt_id)
            raise
        publication.publish(start.attempt_id)
        return store.read(start.attempt_id)


def publish_experiments(attempts: Path) -> tuple[PublicationReceipt, ...]:
    """Publish pending terminal attempts, including previously failed or interrupted workflows.

    Args:
        attempts: Complete retained root; credentials are supplied through SDK configuration.

    Returns:
        Receipts for every terminal attempt with publication intent, including existing receipts.
        Incomplete attempts remain visible and require explicit abandonment before publication.

    Raises:
        Exception: A publication failure propagates; earlier receipts and all outcomes are retained.
    """
    receipts: list[PublicationReceipt] = []
    with AttemptStore(attempts) as store:
        for history in store.histories():
            attempt_id = history.start.attempt_id
            if history.status != "incomplete" and "clearml-destination" in store.artifacts(
                attempt_id
            ):
                destination = DomainCodec().decode_json(
                    store.artifact(attempt_id, "clearml-destination"), ClearMLDestination
                )
                receipts.append(ClearMLPublication(store, destination).publish(attempt_id))
    return tuple(receipts)
