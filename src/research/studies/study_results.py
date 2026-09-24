"""Reopen complete typed study artifacts through the existing verified result manifest."""

from __future__ import annotations

# standard library imports
from fractions import Fraction
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from research.experiments import AttemptStore, TemporalSplit, TimeWindow
from research.features import FeatureCheckpoint, FeatureVector, TransformVersion
from research.labels import Outcome
from research.models import EstimatorVersion
from research.results import Prediction
from research.studies.decision_studies import DecisionStudy
from research.studies.extensions import ReportObservation
from research.studies.results import ResultManifest
from serialization import DomainCodec, WireRecord
from simulation import IntentSimulationResult
from strategies import DecisionRecord, DecisionState


class StudyFoldResult(WireRecord, frozen=True):
    """Retain actual features, fitted bytes, decisions, exclusions and reconciled economics."""

    name: str
    split: TemporalSplit
    features: tuple[FeatureVector, ...]
    outcomes: tuple[Outcome, ...]
    transform: TransformVersion | None
    model: EstimatorVersion | None
    predictions: tuple[Prediction, ...]
    decisions: tuple[DecisionRecord, ...]
    exclusions: tuple[tuple[str, str], ...]
    feature_state: FeatureCheckpoint
    policy_state: DecisionState
    economics: IntentSimulationResult

    def __post_init__(self) -> None:
        """Refuse mismatched model provenance and disconnected prediction/decision traces."""
        self.split.__post_init__()
        self.economics.__post_init__()
        self.feature_state.__post_init__()
        self.policy_state.__post_init__()
        for rows in (self.features, self.outcomes, self.predictions, self.decisions):
            if type(rows) is not tuple:
                raise TypeError("fold results require immutable typed traces")
            for row in rows:
                row.__post_init__()
        if type(self.name) is not str or not self.name:
            raise ValueError("fold result requires its configured name")
        if type(self.exclusions) is not tuple or any(
            type(item) is not tuple
            or len(item) != 2
            or any(type(v) is not str or not v for v in item)
            for item in self.exclusions
        ):
            raise ValueError("fold exclusions require named immutable reasons")
        for version in (self.model, self.transform):
            if version is not None:
                version.__post_init__()
                if version.split_identity != self.split.identity:
                    raise ValueError("fitted artifact differs from retained fold")
        if self.model is None and self.predictions:
            raise ValueError("unfitted result cannot retain predictions")
        if self.model is not None and any(
            p.model_identity != self.model.identity for p in self.predictions
        ):
            raise ValueError("prediction model differs from retained state")
        prediction_ids = {p.feature_identity for p in self.predictions}
        if self.model is not None and any(
            d.feature_identity not in prediction_ids for d in self.decisions
        ):
            raise ValueError("learned decision lacks its retained prediction")

    def prediction_errors(self, window: TimeWindow) -> tuple[ReportObservation, ...]:
        """Expose exact squared errors and pending-label reasons to custom report metrics."""
        if self.model is None:
            return ()
        labels = {outcome.feature_identity: outcome for outcome in self.outcomes}
        predictions = {value.decision_at: value for value in self.predictions}
        observations: list[ReportObservation] = []
        for row in self.features:
            if not window.contains(row.decision_at):
                continue
            outcome = labels.get(row.identity)
            prediction = predictions.get(row.decision_at)
            value = None
            reason = "missing prediction" if prediction is None else "missing outcome"
            if outcome is not None:
                if (outcome.definition, outcome.field) != (
                    self.model.label_definition,
                    self.model.output,
                ):
                    raise ValueError("evaluation outcome differs from fitted label definition")
                if prediction is not None and outcome.value is not None:
                    value = ExactRatio.from_fraction(
                        (
                            Fraction(
                                int(prediction.value.numerator), int(prediction.value.denominator)
                            )
                            - Fraction(int(outcome.value.numerator), int(outcome.value.denominator))
                        )
                        ** 2
                    )
                elif prediction is not None:
                    reason = outcome.reason
            observations.append(
                ReportObservation(
                    fold_id=self.name,
                    name="squared_prediction_error",
                    at=row.decision_at,
                    units=f"({self.model.output.units})^2",
                    value=value,
                    missing_reason=reason if value is None else None,
                )
            )
        return tuple(observations)


class StudyResult(WireRecord, frozen=True):
    """Retain the resolved configuration and exact independently evaluated fold results."""

    config: DecisionStudy
    folds: tuple[StudyFoldResult, ...]
    schema_version: Literal["decision-study-result-v1"] = "decision-study-result-v1"

    def __post_init__(self) -> None:
        """Reject omitted/reordered folds and foreign state before exposing a result."""
        self.config.__post_init__()
        if self.schema_version != "decision-study-result-v1" or type(self.folds) is not tuple:
            raise ValueError("invalid study result schema")
        if tuple(f.name for f in self.folds) != tuple(f.name for f in self.config.folds):
            raise ValueError("result folds differ from configured study")
        for result, fold in zip(self.folds, self.config.folds, strict=True):
            result.__post_init__()
            window = self.config.window(fold)
            if result.split.holdout != fold.split.holdout or any(
                not window.contains(d.at) for d in result.decisions
            ):
                raise ValueError("result decisions or holdout differ from configured fold")
            if (
                replace(result.split, samples=()) != fold.split
                or result.economics.spec
                != replace(self.config.economics, start=window.start, end=window.end)
                or tuple(item.decision for item in result.economics.decisions) != result.decisions
            ):
                raise ValueError(
                    "retained economics or resolved split differs from its configuration"
                )
            if (
                result.feature_state.definition != self.config.feature_identity
                or result.policy_state.run_identity != self.config.identity
            ):
                raise ValueError(
                    "retained feature/policy state differs from selected implementations"
                )

    @classmethod
    def read(cls, store: AttemptStore, attempt_id: str) -> StudyResult:
        """Verify complete retained artifact digests before decoding typed economic results."""
        manifest = ResultManifest.read(store, attempt_id)
        if "study-result" not in {item.name for item in manifest.artifacts}:
            raise ValueError("attempt does not contain a committed decision study")
        result = DomainCodec().decode_json(store.artifact(attempt_id, "study-result"), cls)
        request = DomainCodec().decode_json(store.read(attempt_id).start.request, DecisionStudy)
        if result.config != request:
            raise ValueError("study result differs from original attempt request")
        return result
