"""Admit saved diagnostic sources and retain computation state through the attempt store."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime

# third party library imports
import msgspec

# project library imports
from research.experiments import AttemptHistory, AttemptStore
from research.studies.diagnostics import FeatureLabelPayload
from research.studies.evaluation import EvaluationRecord
from research.studies.results import ResultManifest
from research.studies.tracking import TrackedModel
from research.studies.window_diagnostics import (
    DiagnosticSource,
    WindowDiagnostics,
    WindowDiagnosticStudy,
)
from serialization import DomainCodec


class WindowDiagnosticRun:
    """Own saved-source validation and terminal diagnostic transitions for one invocation."""

    def __init__(self, store: AttemptStore, study: WindowDiagnosticStudy) -> None:
        """Bind the existing single-writer store and frozen diagnostic contract.

        Args:
            store: Entered local attempt store; all source attempts must remain retrievable.
            study: Explicit windows, source references, cutoff and frozen diagnostic policy.
        """
        study.__post_init__()
        self._store = store
        self._study = study

    def execute(self, attempt_id: str) -> AttemptHistory:
        """Retain inputs before computation and atomically complete or preserve failure.

        Args:
            attempt_id: Incomplete attempt with publication intent already retained.

        Returns:
            Completed diagnostic attempt with verified input and report artifacts.

        Raises:
            Exception: Input, computation or retention fails; the terminal failure is preserved.
        """
        codec = DomainCodec()
        try:
            inputs: dict[str, bytes] = {"window-study": codec.encode_json(self._study)}
            features = tuple(
                self._feature(source, inputs, index)
                for index, source in enumerate(self._study.features)
            )
            predictions = tuple(
                self._prediction(source, inputs, index, features)
                for index, source in enumerate(self._study.predictions)
            )
            ResultManifest.retain(self._store, attempt_id, inputs)
            report = WindowDiagnostics().evaluate(self._study, features, predictions)
            inputs.update(
                {
                    "window-report-json": codec.encode_json(report),
                    "window-report-html": report.html_bytes(),
                }
            )
            manifest = ResultManifest.retain(self._store, attempt_id, inputs)
            self._store.finish(
                attempt_id,
                status="completed",
                at=datetime.now(UTC),
                reason="Completed offline window diagnostics; no automatic action",
                result=codec.encode_json(manifest),
            )
        except (Exception, KeyboardInterrupt) as error:
            if self._store.read(attempt_id).status == "incomplete":
                self._store.finish(
                    attempt_id,
                    status="abandoned" if isinstance(error, KeyboardInterrupt) else "failed",
                    at=datetime.now(UTC),
                    reason=f"{type(error).__name__}: {error}",
                )
            raise
        return self._store.read(attempt_id)

    def _history(self, source: DiagnosticSource) -> AttemptHistory:
        """Reject unsuccessful sources and preserve the original frozen validation geometry."""
        history = self._store.read(source.attempt_id)
        if history.status not in ("completed", "rejected") or any(
            event.status == "holdout_consumed" for event in history.events
        ):
            raise ValueError(
                "diagnostics require terminal validation sources without holdout access"
            )
        split = history.start.spec.split
        if split is None:
            raise ValueError("validation diagnostics require a temporal split")
        if (
            split.validation != self._study.split.validation
            or split.holdout != self._study.split.holdout
        ):
            raise ValueError("diagnostics must preserve source validation and holdout windows")
        return history

    @staticmethod
    def _verify(payload: bytes, source: DiagnosticSource) -> None:
        """Verify actual retained content against the frozen source digest."""
        if hashlib.sha256(payload).hexdigest() != source.sha256:
            raise ValueError("diagnostic source digest mismatch")

    def _feature(
        self, source: DiagnosticSource, inputs: dict[str, bytes], index: int
    ) -> FeatureLabelPayload:
        """Reopen an exact completed feature result and retain its full upstream history."""
        history = self._history(source)
        payload = history.events[-1].result
        if history.status != "completed" or payload is None:
            raise ValueError("diagnostics require completed retained feature bytes")
        self._verify(payload, source)
        feature = FeatureLabelPayload.decode(payload)
        split = history.start.spec.split
        if split is None:
            raise ValueError("feature diagnostics require a temporal split")
        if (
            feature.split_identity != split.identity
            or feature.split_identity != self._study.split.identity
        ):
            raise ValueError("diagnostics must preserve the source feature temporal split")
        inputs[f"feature-source-{index}"] = payload
        inputs[f"feature-history-{index}"] = DomainCodec().encode_json(history)
        return feature

    def _prediction(
        self,
        source: DiagnosticSource,
        inputs: dict[str, bytes],
        index: int,
        features: tuple[FeatureLabelPayload, ...],
    ) -> EvaluationRecord:
        """Bind retained predictions to their feature sources, sample intervals and models."""
        codec = DomainCodec()
        history = self._history(source)
        payload = self._store.artifact(source.attempt_id, "evaluation")
        self._verify(payload, source)
        evaluation = codec.decode_json(payload, EvaluationRecord)
        split = history.start.spec.split
        if split is None:
            raise ValueError("validation diagnostics require a temporal split")
        if evaluation.split_identity != split.identity or evaluation.window != split.validation:
            raise ValueError("prediction evaluation differs from its retained temporal split")
        declared = sorted(item.sha256 for item in self._study.features)
        upstream = sorted(
            item.sha256 for item in history.start.spec.inputs if item.name.startswith("features-")
        )
        if upstream != declared:
            raise ValueError("predictions do not reference the declared retained feature results")
        samples = {sample.row_id: sample for feature in features for sample in feature.samples}
        if {sample.row_id: sample for sample in split.samples} != samples:
            raise ValueError("prediction sample intervals differ from retained features")
        models_payload = self._store.artifact(source.attempt_id, "tracked-models")
        models = msgspec.json.decode(models_payload, type=tuple[TrackedModel, ...])
        available: dict[str, datetime] = {}
        for model in models:
            model.__post_init__()
            manifest = self._store.artifact(model.creation_attempt, "model-version")
            if manifest != model.manifest_bytes:
                raise ValueError("prediction model differs from its retained creation manifest")
            # Inspect only the clock needed by this consumer; the model owner
            # validated the complete manifest before retaining the evaluation.
            fields = msgspec.json.decode(manifest, type=dict[str, msgspec.Raw])
            available[model.version_sha256] = codec.decode_json(
                bytes(fields["available_at"]), datetime
            )
            inputs[f"prediction-{index}-model-{model.version_sha256}"] = manifest
        for row_id, model_id, _, _, _ in evaluation.predictions:
            sample = samples.get(row_id)
            model_clock = available.get(model_id)
            if sample is None or model_clock is None or model_clock > sample.decision_at:
                raise ValueError("prediction has no model available at its original decision")
        inputs[f"prediction-source-{index}"] = payload
        inputs[f"prediction-history-{index}"] = codec.encode_json(history)
        inputs[f"prediction-models-{index}"] = models_payload
        return evaluation
