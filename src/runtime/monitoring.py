"""Export admitted candidate predictions and delayed outcomes to optional telemetry."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from typing import Literal

# project library imports
from configuration import PaperConfiguration
from research.features import FeatureVector
from research.labels import Outcome
from research.results import Prediction
from runtime.candidates import CandidateStep, LoadedCandidate
from runtime.paper import PaperCandidateRuntime, PaperCheckpoint
from telemetry import MonitoringEvent, MonitoringIdentity


class CandidateMonitoringExporter:
    """Correlate a durable paper/shadow candidate step with later label revisions.

    The exporter has no control path back to the candidate, journal or account.
    Callers provide the monitoring receipt clock when each fact is emitted.
    """

    prediction_name = "research.prediction"
    outcome_name = "research.outcome"
    version = "1"

    def __init__(
        self,
        loaded: LoadedCandidate,
        config: PaperConfiguration,
        checkpoint: PaperCheckpoint,
        *,
        scope: str,
        clock_quality: Literal["observed", "modeled", "unknown"],
    ) -> None:
        """Bind the admitted candidate, account and durable runtime continuation."""
        loaded.manifest.__post_init__()
        loaded.deployment.__post_init__()
        config.__post_init__()
        checkpoint.__post_init__()
        MonitoringIdentity(scope=scope, mode=config.mode)
        if (
            checkpoint.binding_identity != PaperCandidateRuntime.binding(loaded, config)
            or checkpoint.candidate.binding_identity != loaded.identity
            or config.mode not in ("paper", "shadow")
            or clock_quality not in ("observed", "modeled", "unknown")
        ):
            raise ValueError("candidate monitoring requires the admitted paper continuation")
        self.loaded = loaded
        self.config = config
        self.checkpoint = checkpoint
        self.scope = scope
        self.clock_quality = clock_quality

    def prediction(self, step: CandidateStep, *, recorded_at: datetime) -> MonitoringEvent:
        """Emit the committed inference with its caller-supplied receipt clock."""
        feature, prediction = self._admit_step(step)
        MonitoringEvent._require_utc(recorded_at, field_name="candidate monitoring receipt")
        if recorded_at < step.at:
            raise ValueError("candidate monitoring receipt precedes committed inference")
        return MonitoringEvent(
            context=self._identity(step),
            name=self.prediction_name,
            version=self.version,
            sample=feature.identity,
            at=prediction.decision_at,
            available_at=step.at,
            recorded_at=recorded_at,
            units=prediction.field.units,
            value=prediction.value,
            clock_quality=self.clock_quality,
        )

    def outcome(
        self,
        step: CandidateStep,
        outcome: Outcome,
        *,
        recorded_at: datetime,
        revision: int = 0,
    ) -> MonitoringEvent:
        """Emit a pending, observed or corrected label at its genuine knowledge clock."""
        feature, prediction = self._admit_step(step)
        outcome.sample(feature)
        version = self.loaded.estimator_version
        if (
            version is None
            or outcome.definition != version.label_definition
            or outcome.field != prediction.field
        ):
            raise ValueError("candidate outcome differs from admitted fitted label")
        MonitoringEvent._require_utc(recorded_at, field_name="candidate label receipt")
        available_at = outcome.available_at or recorded_at
        if recorded_at < max(step.at, available_at):
            raise ValueError("candidate label receipt precedes inference or knowledge")
        return MonitoringEvent(
            context=self._identity(step),
            name=self.outcome_name,
            version=self.version,
            sample=feature.identity,
            at=prediction.decision_at,
            available_at=available_at,
            recorded_at=recorded_at,
            units=outcome.field.units,
            value=outcome.value,
            missing_reason=outcome.reason if outcome.value is None else None,
            revision=revision,
            clock_quality=self.clock_quality if outcome.available_at is not None else "unknown",
        )

    def _admit_step(self, step: CandidateStep) -> tuple[FeatureVector, Prediction]:
        """Reject an uncommitted or foreign step before emitting account telemetry."""
        step.__post_init__()
        if (
            step.status != "decided"
            or step.feature is None
            or step.prediction is None
            or step.checkpoint.binding_identity != self.loaded.identity
            or step.at > self.checkpoint.last_at
        ):
            raise ValueError("candidate monitoring requires a committed learned step")
        version = self.loaded.estimator_version
        if (
            version is None
            or step.prediction.model_identity != version.identity
            or step.prediction.field != version.output
        ):
            raise ValueError("candidate monitoring prediction differs from fitted model")
        return step.feature, step.prediction

    def _identity(self, step: CandidateStep) -> MonitoringIdentity:
        """Pin paper scope, installed code, study, source, model and account."""
        prediction = step.prediction
        if prediction is None:
            raise ValueError("candidate monitoring requires a model prediction")
        policy = next(
            item.identity for item in self.loaded.manifest.components if item.role == "policy"
        )
        return MonitoringIdentity(
            scope=self.scope,
            mode=self.config.mode,
            release=self.loaded.manifest.code_sha256,
            strategy=policy,
            model=prediction.model_identity,
            source=self.loaded.deployment.source_identity,
            study=self.loaded.manifest.dataset.sha256,
            account=self.config.account,
            instrument=self.loaded.deployment.entity,
        )
