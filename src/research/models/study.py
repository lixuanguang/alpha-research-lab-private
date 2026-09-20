"""Resolve bounded construction/evaluation requests against retained feature and model bytes."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime
from typing import Literal

# project library imports
from financial_units import ExactRatio
from research.experiments import AttemptStore, ExperimentSpec, Fingerprint, TemporalSplit
from research.models.inputs import ModelDataset
from research.models.linear import LinearDefinition, ModelVersion
from serialization import DomainCodec, WireRecord


class RetainedResult(WireRecord, frozen=True, kw_only=True):
    """Pin completed feature result bytes or an existing model manifest by execution and digest."""

    attempt_id: str
    sha256: str

    def __post_init__(self) -> None:
        """Prevent path traversal and require exact retained content identity."""
        if re.fullmatch(r"[a-f0-9]{32}", self.attempt_id) is None:
            raise ValueError("retained reference requires an attempt ID")
        Fingerprint(name="retained result", sha256=self.sha256)


class ModelStudy(WireRecord, frozen=True, kw_only=True):
    """Freeze one model question, exact inputs, fold, acceptance rule and outcome cutoff."""

    schema_version: Literal["model-study-v1"] = "model-study-v1"
    family: str
    question: str
    sources: tuple[RetainedResult, ...]
    split: TemporalSplit
    partition: Literal["validation", "holdout"]
    known_at: datetime
    max_mse: ExactRatio
    selection_reason: str
    definition: LinearDefinition | None
    available_at: datetime | None
    models: tuple[RetainedResult, ...] = ()

    def __post_init__(self) -> None:
        """Require exactly construction or reload, with explicit historical availability."""
        if (
            self.schema_version != "model-study-v1"
            or not self.family.strip()
            or not self.question.strip()
            or not self.selection_reason.strip()
            or self.partition not in ("validation", "holdout")
            or type(self.sources) is not tuple
            or not self.sources
            or len(self.sources) > 1024
            or type(self.models) is not tuple
        ):
            raise ValueError("invalid model study configuration")
        for reference in (*self.sources, *self.models):
            reference.__post_init__()
        self.split.__post_init__()
        self._require_utc(self.known_at, field_name="known_at")
        self.max_mse.__post_init__()
        if int(self.max_mse.numerator) < 0:
            raise ValueError("MSE threshold must be nonnegative")
        if self.definition is not None:
            self.definition.__post_init__()
            if self.models or self.available_at is None:
                raise ValueError("construction requires availability and no reload models")
            self._require_utc(self.available_at, field_name="available_at")
        elif not self.models or self.available_at is not None:
            raise ValueError("inference requires exact model versions and no new construction")

    def specification(self, *, implementation: str, environment: str) -> ExperimentSpec:
        """Bind semantic configuration without using upstream execution locations as inputs.

        Args:
            implementation: Installed implementation digest.
            environment: Actual interpreter/platform/dependency digest.

        Returns:
            Reproducible run identity; deterministic construction uses no random seeds.
        """
        self.__post_init__()
        parameters = DomainCodec().encode_json(
            (
                self.question,
                self.partition,
                self.known_at,
                self.max_mse,
                self.selection_reason,
                self.definition,
                self.available_at,
            )
        )
        return ExperimentSpec(
            family=self.family,
            inputs=tuple(
                Fingerprint(name=f"features-{index}", sha256=reference.sha256)
                for index, reference in enumerate(self.sources)
            )
            + tuple(
                Fingerprint(name=f"model-{index}", sha256=reference.sha256)
                for index, reference in enumerate(self.models)
            ),
            components=(Fingerprint(name="implementation", sha256=implementation),),
            parameters=(("model-study", parameters.decode()),),
            seeds=(),
            environment_sha256=environment,
            split=self.split,
        )

    def dataset(self, store: AttemptStore) -> ModelDataset:
        """Reopen and hash actual completed diagnostic bytes before dataframe admission.

        Args:
            store: Retained source history, including the related family's holdout records.

        Returns:
            Verified model dataset; no implicit acquisition, resampling or filling.

        Raises:
            ValueError: An upstream result is absent, unsuccessful or differs from its digest.
        """
        payloads: list[bytes] = []
        for reference in self.sources:
            history = store.read(reference.attempt_id)
            result = history.events[-1].result if history.status == "completed" else None
            if result is None or hashlib.sha256(result).hexdigest() != reference.sha256:
                raise ValueError("model feature result is incomplete or its digest differs")
            payloads.append(result)
        return ModelDataset.from_results(tuple(payloads))

    def reload(self, store: AttemptStore) -> tuple[ModelVersion, ...]:
        """Verify and load existing state without fitting or relying on a mutable alias.

        Args:
            store: Retained model creation attempts; usable rejected variants remain accessible.

        Returns:
            Exact compatible-schema model manifests with verified state bytes.

        Raises:
            ValueError: A pinned version differs from its retained bytes or creation attempt.
        """
        versions: list[ModelVersion] = []
        for reference in self.models:
            payload = store.artifact(reference.attempt_id, "model-version")
            model = DomainCodec().decode_json(payload, ModelVersion)
            if model.identity != reference.sha256 or model.creation_attempt != reference.attempt_id:
                raise ValueError("pinned model version differs from retained bytes")
            versions.append(model)
        return tuple(versions)
