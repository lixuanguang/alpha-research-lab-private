"""Schedule retained studies on bounded workers without coupling compatible environments."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

# project library imports
from applications.explore.studies import StudyComponents, evaluate_study
from research.experiments import ExperimentSpec
from research.studies import DecisionStudy, PublicationPolicy
from runtime import ImplementationIdentity, JobQueue, JobRun, JobSpec
from serialization import DomainCodec, WireRecord


class QueuedStudy(WireRecord, frozen=True):
    """Retain exact study and publication selection; credentials remain worker references."""

    study: DecisionStudy
    publication: PublicationPolicy

    def __post_init__(self) -> None:
        """Require local or deferred effects so cancellation cannot race remote publication."""
        if type(self.study) is not DecisionStudy or type(self.publication) is not PublicationPolicy:
            raise TypeError("queued study requires typed configuration and publication")
        self.study.__post_init__()
        self.publication.__post_init__()
        if self.publication.mode not in ("local", "deferred"):
            raise ValueError("queued studies require local or deferred publication")

    @property
    def input_sha256(self) -> str:
        """Pin both named decision inputs and the separately selected economic source."""
        return hashlib.sha256(
            DomainCodec().encode_json(
                (self.study.source_identity, self.study.economics.source_identity)
            )
        ).hexdigest()


class StudyJobHandler:
    """Run explicitly injected study components with durable family and retry identities.

    Each family has one authoritative attempt store. Distinct families can run
    concurrently; competing writers of the same family retry through the job
    service. External publication follows the existing recoverable outbox after
    successful computation. A running study observes cancellation after its
    bounded evaluation returns; it never submits orders.
    """

    def __init__(self, bindings: Mapping[str, StudyComponents], retained_root: Path) -> None:
        """Bind selected components by study identity and an owned workspace component."""
        self._bindings = dict(bindings)
        self._root = retained_root

    @staticmethod
    def environment_sha256() -> str:
        """Identify the installed interpreter and dependency versions used by formal studies."""
        return hashlib.sha256(
            DomainCodec().encode_json(ExperimentSpec.installed_environment())
        ).hexdigest()

    def execute(self, spec: JobSpec, run: JobRun) -> bytes:
        """Recover completed attempts before recomputing; retain failed and holdout history."""
        request = DomainCodec().decode_json(spec.request, QueuedStudy)
        request.__post_init__()
        study = request.study
        if (
            spec.kind != "decision-study"
            or spec.configuration_sha256 != study.identity
            or spec.input_sha256 != request.input_sha256
            or spec.implementation_sha256 != ImplementationIdentity.sha256()
            or spec.environment_sha256 != self.environment_sha256()
        ):
            raise ValueError("queued study implementation, environment or request identity differs")
        if run.cancel_requested():
            raise InterruptedError("study cancelled before reading inputs")
        components = self._bindings.get(study.identity)
        if components is None:
            raise ValueError("selected study has no supplied implementation binding")
        family = hashlib.sha256(study.family.encode()).hexdigest()
        history = evaluate_study(
            study,
            components=components,
            attempts=self._root / family,
            publication=request.publication,
            idempotency_key=run.idempotency_key,
        )
        return DomainCodec().encode_json(history)


def schedule_study(
    queue: JobQueue,
    study: DecisionStudy,
    *,
    job_id: str,
    run_at: datetime,
    publication: PublicationPolicy,
    secret_refs: tuple[str, ...] = (),
    max_attempts: int = 3,
    retry_delay_seconds: int = 1,
) -> JobSpec:
    """Persist a study with exact installed identities before a compatible worker claims it.

    Submission is idempotent for identical job bytes. Reusing a key with changed
    configuration fails. Secrets are names resolved privately by workers, never
    credential values. The separately locked Feast worker remains independent.
    """
    request = QueuedStudy(study=study, publication=publication)
    spec = JobSpec(
        job_id=job_id,
        kind="decision-study",
        run_at=run_at,
        implementation_sha256=ImplementationIdentity.sha256(),
        configuration_sha256=study.identity,
        input_sha256=request.input_sha256,
        environment_sha256=StudyJobHandler.environment_sha256(),
        secret_refs=secret_refs,
        request=DomainCodec().encode_json(request),
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
    queue.submit(spec)
    return spec
