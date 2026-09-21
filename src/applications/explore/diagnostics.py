"""Compose retained factor and window comparisons through the exploration application."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime
from pathlib import Path

# project library imports
from research.experiments import (
    AlphalensDiagnostics,
    AlphalensStudy,
    AttemptHistory,
    AttemptStore,
    ClearMLDestination,
    ClearMLPublication,
    ExperimentSpec,
    FeatureLabelPayload,
    Fingerprint,
    ResultManifest,
    TemporalSplit,
    WindowDiagnosticRun,
    WindowDiagnosticStudy,
)
from runtime import ImplementationIdentity
from serialization import DomainCodec


def compare_windows(
    study: WindowDiagnosticStudy, *, attempts: Path, tracking: ClearMLDestination
) -> AttemptHistory:
    """Compose retained window diagnostics and the existing recoverable ClearML outbox.

    Args:
        study: Frozen sources, windows, cutoff, applicability and thresholds.
        attempts: Existing retained single-writer root containing every upstream source.
        tracking: Required non-secret publication destination; credentials stay in SDK config.

    Returns:
        Completed local diagnostics after acknowledged report publication.

    Raises:
        Exception: Computation or publication fails with its saved inputs and history preserved.
    """
    spec = study.specification(
        implementation=ImplementationIdentity.sha256(),
        environment=ExperimentSpec.installed_environment(),
    )
    with AttemptStore(attempts) as store:
        start = store.start(
            spec,
            at=datetime.now(UTC),
            invocation="applications.explore.compare_windows",
            request=DomainCodec().encode_json(study),
        )
        publication = ClearMLPublication(store, tracking)
        publication.enqueue(start.attempt_id)
        history = WindowDiagnosticRun(store, study).execute(start.attempt_id)
        publication.publish(start.attempt_id)
        return history


def compare_factors(
    study: AlphalensStudy,
    *,
    family: str,
    source_attempt: str,
    source_sha256: str,
    split: TemporalSplit,
    attempts: Path,
    tracking: ClearMLDestination,
) -> AttemptHistory:
    """Retain a validation-only Alphalens report from a verified completed feature attempt.

    Args:
        study: Declared factor direction, universe, horizon, quantiles and observation cutoff.
        family: Research family sharing the existing frozen holdout history.
        source_attempt: Completed MR 3 feature/label attempt in this same retained store.
        source_sha256: Digest of the actual completed feature result bytes.
        split: Explicit no-fit validation/holdout partition; final holdout is never accessed.
        attempts: Existing single-writer attempt root.
        tracking: Required non-secret ClearML publication destination.

    Returns:
        Terminal software result after acknowledged publication; inapplicability stays explicit.

    Raises:
        ValueError: Source, temporal bounds or configuration fail admission.
        Exception: Computation or publication fails with retained attempt evidence.
    """
    study.__post_init__()
    split.__post_init__()
    if (
        split.fit_mode != "none"
        or study.known_at is None
        or not split.validation.start <= study.known_at < split.holdout.start
        or len(source_attempt) != 32
        or any(c not in "0123456789abcdef" for c in source_attempt)
    ):
        raise ValueError("factor comparison requires an explicit validation-only cutoff and source")
    codec = DomainCodec()
    request = codec.encode_json((study, source_attempt, source_sha256, split))
    spec = ExperimentSpec(
        family=family,
        inputs=(
            Fingerprint(name="feature-result", sha256=source_sha256),
            Fingerprint(name="research-selection", sha256=study.selection_identity),
            Fingerprint(name="factor-study", sha256=hashlib.sha256(request).hexdigest()),
        ),
        components=(Fingerprint(name="implementation", sha256=ImplementationIdentity.sha256()),),
        parameters=(("partition", "validation"), ("scope", "cross-sectional factor diagnostics")),
        seeds=(),
        environment_sha256=ExperimentSpec.installed_environment(),
        split=split,
    )
    with AttemptStore(attempts) as store:
        start = store.start(
            spec,
            at=datetime.now(UTC),
            invocation="applications.explore.compare_factors",
            request=request,
        )
        publication = ClearMLPublication(store, tracking)
        publication.enqueue(start.attempt_id)
        try:
            source = store.read(source_attempt)
            if any(event.status == "holdout_consumed" for event in source.events):
                raise ValueError("factor comparison cannot reuse a holdout feature result")
            payload = source.events[-1].result if source.events else None
            if (
                source.status != "completed"
                or payload is None
                or hashlib.sha256(payload).hexdigest() != source_sha256
            ):
                raise ValueError("factor source is not the pinned completed feature result")
            retained = FeatureLabelPayload.decode(payload)
            if retained.split_identity != split.identity:
                raise ValueError("factor comparison must preserve the source temporal split")
            if any(
                not split.validation.contains(row.decision_at)
                or row.information_end >= split.holdout.start
                for row in retained.samples
            ):
                raise ValueError("factor source observations reach outside declared validation")
            report = AlphalensDiagnostics().evaluate(study, retained)
            manifest = ResultManifest.retain(
                store,
                start.attempt_id,
                {
                    "resolved-factor-study": request,
                    "feature-result": payload,
                    "factor-diagnostics": codec.encode_json(report),
                    "factor-report-json": report.report_json,
                    "factor-report-html": report.report_html,
                },
            )
            store.finish(
                start.attempt_id,
                status="completed",
                at=datetime.now(UTC),
                reason=report.inapplicable_reason
                or "Completed factor diagnostics; no executable strategy claim",
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
            raise
        publication.publish(start.attempt_id)
        return store.read(start.attempt_id)
