"""Retain formal parity between an admitted MR3 feature grid and an offline worker."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

# project library imports
from research.experiments import (
    AttemptHistory,
    AttemptStore,
    ExperimentSpec,
    Fingerprint,
    TemporalSplit,
)
from research.exploration import VerifiedFeatureRows
from research.features import (
    OfflineFeatureAccess,
    OfflineFeatureRequest,
)
from research.results import FeatureStudyResult
from research.studies import (
    ClearMLDestination,
    ClearMLPublication,
    ResultManifest,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ATTEMPT_ID = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def compare_offline_features(
    request: OfflineFeatureRequest,
    access: OfflineFeatureAccess,
    *,
    family: str,
    source_attempt: str,
    source_sha256: str,
    split: TemporalSplit,
    attempts: Path,
    tracking: ClearMLDestination,
) -> AttemptHistory:
    """Retain validation-only parity between an MR3 result and one offline retrieval.

    Args:
        request: Explicit bounded entity/decision request for the offline feature worker.
        access: Existing worker bridge that admits source, availability and TTL metadata.
        family: Existing retained experiment family sharing its frozen holdout.
        source_attempt: Completed MR3 feature-study attempt supplying the causal reference.
        source_sha256: SHA-256 of the exact completed MR3 result bytes.
        split: Validation/holdout partition retained by the MR3 feature study.
        attempts: Existing local single-writer attempt root.
        tracking: Non-secret ClearML destination for the terminal attempt publication.

    Returns:
        Retained completed attempt when every grid cell matches, or rejected attempt on parity
        mismatch. Failed attempts retain all artifacts available before the exception.

    Raises:
        ValueError: The source, split or request violates the validation-only parity contract.
        Exception: Worker, storage or publication failures propagate after attempt retention.
    """
    request.__post_init__()
    split.__post_init__()
    _validate_source_identity(source_attempt, source_sha256)
    if split.fit_mode != "none":
        raise ValueError("offline feature comparison requires a validation-only split")
    if any(not split.validation.contains(decision) for decision in request.decisions):
        raise ValueError("offline feature request must remain inside validation")

    codec = DomainCodec()
    request_bytes = codec.encode_json(request)
    spec = ExperimentSpec(
        family=family,
        inputs=(
            Fingerprint(name="mr3-feature-result", sha256=source_sha256),
            Fingerprint(name="offline-feature-request", sha256=request.identity),
        ),
        components=(Fingerprint(name="implementation", sha256=ImplementationIdentity.sha256()),),
        parameters=(
            ("partition", "validation"),
            ("scope", "offline-feature-parity"),
            ("feature-name", request.definition.feature_name),
        ),
        seeds=(),
        environment_sha256=ExperimentSpec.installed_environment(),
        split=split,
    )
    with AttemptStore(attempts) as store:
        before = {history.start.attempt_id for history in store.histories()}
        try:
            start = store.start(
                spec,
                at=datetime.now(UTC),
                invocation="applications.explore.compare_offline_features",
                request=request_bytes,
            )
        except ValueError:
            _publish_new_rejections(store, before, tracking)
            raise
        publication = ClearMLPublication(store, tracking)
        publication.enqueue(start.attempt_id)
        try:
            source = store.read(source_attempt)
            payload = _source_payload(source, source_sha256, family, split)
            store.retain(start.attempt_id, "offline-feature-request", request_bytes)
            store.retain(start.attempt_id, "mr3-feature-result", payload)
            retained = FeatureStudyResult.decode(payload)
            if (
                request.definition.definition_version
                not in (
                    retained.feature_definition.identity,
                    retained.feature_definition.schema_version,
                )
                or retained.feature_definition.units != request.definition.units
            ):
                raise ValueError("offline feature source definition differs from the request")
            verified = VerifiedFeatureRows.from_result(
                payload,
                source_sha256,
                ttl_us=request.definition.ttl_us,
                feature_name=request.definition.feature_name,
                entity_type=request.definition.entity_type,
            )
            reference = verified.for_request(request)
            reference_bytes = codec.encode_json(reference)
            store.retain(start.attempt_id, "offline-feature-reference", reference_bytes)

            result = access.retrieve(request)
            result_bytes = codec.encode_json(result)
            store.retain(start.attempt_id, "offline-feature-result", result_bytes)
            comparison = access.compare_result(request, result, reference)
            comparison_bytes = codec.encode_json(comparison)
            store.retain(start.attempt_id, "offline-feature-comparison", comparison_bytes)
            manifest = ResultManifest.retain(
                store,
                start.attempt_id,
                {
                    "offline-feature-request": request_bytes,
                    "mr3-feature-result": payload,
                    "offline-feature-reference": reference_bytes,
                    "offline-feature-result": result_bytes,
                    "offline-feature-comparison": comparison_bytes,
                },
            )
            if comparison.mismatches:
                store.finish(
                    start.attempt_id,
                    status="rejected",
                    at=datetime.now(UTC),
                    reason=(
                        f"offline feature parity rejected: "
                        f"{len(comparison.mismatches)} of {len(comparison.rows)} rows mismatch"
                    ),
                )
            else:
                store.finish(
                    start.attempt_id,
                    status="completed",
                    at=datetime.now(UTC),
                    reason="offline feature parity matched the retained MR3 grid",
                    result=codec.encode_json(manifest),
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


def _validate_source_identity(source_attempt: str, source_sha256: str) -> None:
    """Validate the retained source identifiers before building an experiment spec."""
    if type(source_attempt) is not str or _ATTEMPT_ID.fullmatch(source_attempt) is None:
        raise ValueError("offline feature comparison requires a canonical source attempt")
    if type(source_sha256) is not str or _DIGEST.fullmatch(source_sha256) is None:
        raise ValueError("offline feature comparison requires a lowercase source digest")


def _source_payload(
    source: AttemptHistory,
    source_sha256: str,
    family: str,
    split: TemporalSplit,
) -> bytes:
    """Verify one completed MR3 result and its validation-only retained boundary."""
    if source.start.spec.family != family or source.start.spec.split != split:
        raise ValueError("offline feature source differs from the requested family or split")
    if source.status != "completed" or any(
        event.status == "holdout_consumed" for event in source.events
    ):
        raise ValueError("offline feature source must be completed without holdout access")
    result = source.events[-1].result if source.events else None
    if type(result) is not bytes or not result:
        raise ValueError("offline feature source has no completed result bytes")
    if hashlib.sha256(result).hexdigest() != source_sha256:
        raise ValueError("offline feature source bytes differ from the pinned digest")
    payload = FeatureStudyResult.decode(result)
    if payload.split_identity != split.identity:
        raise ValueError("offline feature source split differs from the requested split")
    if any(
        not split.validation.contains(sample.decision_at)
        or sample.information_end >= split.holdout.start
        for sample in payload.samples
    ):
        raise ValueError("offline feature source reaches outside validation")
    return result


def _publish_new_rejections(
    store: AttemptStore, before: set[str], tracking: ClearMLDestination
) -> None:
    """Publish a start-time rejected attempt while preserving the original exception."""
    publication = ClearMLPublication(store, tracking)
    for history in store.histories():
        if history.start.attempt_id not in before:
            publication.enqueue(history.start.attempt_id)
            publication.publish(history.start.attempt_id)
