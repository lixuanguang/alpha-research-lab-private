"""Construct and reload exact one-feature configured or least-squares predictive models."""

from __future__ import annotations

# standard library imports
import hashlib
import re
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from financial_units import ExactRatio
from research.experiments import Fingerprint, TemporalSplit, TimeWindow
from research.models.evaluation import EvaluationRecord
from research.models.inputs import ModelDataset, ModelRow, ModelSignature
from serialization import DomainCodec, WireRecord


class LinearDefinition(WireRecord, frozen=True, kw_only=True):
    """Select configured coefficients or train-only centered ordinary least squares."""

    mode: Literal["configured", "least-squares"]
    assumptions: str
    intercept: ExactRatio | None = None
    slope: ExactRatio | None = None
    schema_version: Literal["linear-return"] = "linear-return"

    def __post_init__(self) -> None:
        """Require explicit assumptions and coefficients only when no fitting applies."""
        if self.schema_version != "linear-return" or not self.assumptions.strip():
            raise ValueError("model requires a supported definition and assumptions")
        if self.mode == "configured":
            if type(self.intercept) is not ExactRatio or type(self.slope) is not ExactRatio:
                raise ValueError("configured model requires exact intercept and slope")
            self.intercept.__post_init__()
            self.slope.__post_init__()
        elif self.mode != "least-squares" or self.intercept is not None or self.slope is not None:
            raise ValueError("least-squares coefficients must be fitted, not supplied")


class LinearState(WireRecord, frozen=True, kw_only=True):
    """Encode prediction = intercept + slope * (feature - center), all exactly rational."""

    center: ExactRatio
    intercept: ExactRatio
    slope: ExactRatio
    schema_version: Literal["linear-state"] = "linear-state"

    def __post_init__(self) -> None:
        """Refuse incompatible or approximate model state."""
        if self.schema_version != "linear-state":
            raise ValueError("unsupported linear state")
        for value in (self.center, self.intercept, self.slope):
            if type(value) is not ExactRatio:
                raise TypeError("linear state requires exact ratios")
            value.__post_init__()

    @staticmethod
    def fraction(value: ExactRatio) -> Fraction:
        """Recover a canonical exact rational without using decimal context or floats.

        Args:
            value: Valid exact ratio.

        Returns:
            Exact arithmetic value.
        """
        value.__post_init__()
        return Fraction(int(value.numerator), int(value.denominator))


class ModelVersion(WireRecord, frozen=True, kw_only=True):
    """Retain usable state bytes independently of evaluation and external mutable model IDs."""

    schema_version: Literal["model-version"] = "model-version"
    definition: LinearDefinition
    signature: ModelSignature
    creation_attempt: str
    created_at: datetime
    available_at: datetime
    training: TimeWindow | None
    fit_cutoff: datetime | None
    fit_rows: tuple[str, ...]
    fit_input_sha256: str
    state_bytes: bytes
    state_sha256: str

    def __post_init__(self) -> None:
        """Validate state integrity, fit applicability and historical availability."""
        if (
            type(self.definition) is not LinearDefinition
            or type(self.signature) is not ModelSignature
            or type(self.state_bytes) is not bytes
            or type(self.fit_rows) is not tuple
            or any(type(row) is not str or not row.strip() for row in self.fit_rows)
        ):
            raise TypeError("model requires immutable typed definition, signature, rows and bytes")
        if self.schema_version != "model-version":
            raise ValueError("unsupported model manifest")
        self.definition.__post_init__()
        self.signature.__post_init__()
        if re.fullmatch(r"[a-f0-9]{32}", self.creation_attempt) is None:
            raise ValueError("model requires its creation attempt")
        self._require_utc(self.created_at, field_name="created_at")
        self._require_utc(self.available_at, field_name="available_at")
        Fingerprint(name="state", sha256=self.state_sha256)
        Fingerprint(name="fit inputs", sha256=self.fit_input_sha256)
        if hashlib.sha256(self.state_bytes).hexdigest() != self.state_sha256:
            raise ValueError("model state digest mismatch")
        state = DomainCodec().decode_json(self.state_bytes, LinearState)
        if self.definition.mode == "configured":
            if self.training is not None or self.fit_cutoff is not None or self.fit_rows:
                raise ValueError("configured model must not invent fitting")
            if (
                state.intercept != self.definition.intercept
                or state.slope != self.definition.slope
                or state.center != ExactRatio(numerator="0", denominator="1")
            ):
                raise ValueError("configured state differs from its definition")
        else:
            if self.training is None or self.fit_cutoff is None or len(self.fit_rows) < 2:
                raise ValueError("fitted model requires fit evidence")
            self.training.__post_init__()
            self._require_utc(self.fit_cutoff, field_name="fit_cutoff")
            if not self.training.end <= self.fit_cutoff <= self.available_at:
                raise ValueError("model availability precedes fitting cutoff")
            if len(set(self.fit_rows)) != len(self.fit_rows):
                raise ValueError("model fitting rows must be unique")

    @property
    def identity(self) -> str:
        """Fingerprint this exact version, including construction provenance.

        Returns:
            SHA-256 used by every evaluation and publication receipt.
        """
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()

    def predict(self, row: ModelRow, signature: ModelSignature) -> ExactRatio:
        """Load accepted numerical state and predict without implicit fitting or label access.

        Args:
            row: Exact feature and its decision-time availability; label is unused.
            signature: Explicit ordered feature, target and numerical contract.

        Returns:
            Exact dimensionless prediction.

        Raises:
            ValueError: State or features are incompatible, missing or unavailable at decision.
        """
        self.__post_init__()
        row.__post_init__()
        if self.signature != signature:
            raise ValueError("model feature order, definitions or units are incompatible")
        if (
            self.available_at > row.sample.decision_at
            or row.sample.features_available_at > row.sample.decision_at
            or row.feature is None
        ):
            raise ValueError("model or feature unavailable at decision")
        state = DomainCodec().decode_json(self.state_bytes, LinearState)
        return ExactRatio.from_fraction(
            LinearState.fraction(state.intercept)
            + LinearState.fraction(state.slope)
            * (LinearState.fraction(row.feature) - LinearState.fraction(state.center))
        )


class LinearModel:
    """Own construction and exact predictive diagnostics for the bounded linear consumer."""

    @staticmethod
    def construct(
        definition: LinearDefinition,
        dataset: ModelDataset,
        split: TemporalSplit,
        *,
        attempt_id: str,
        created_at: datetime,
        available_at: datetime,
    ) -> ModelVersion:
        """Fit centering and coefficients only on admitted, then-available training rows.

        Args:
            definition: Configured model or selected exact least-squares construction.
            dataset: Verified feature results with the explicit Pandera input boundary.
            split: Authored fold whose sample records must match the dataset exactly.
            attempt_id: Execution creating the retained model version.
            created_at: Actual UTC construction time, distinct from historical availability.
            available_at: Declared earliest historical use, no earlier than the fitting cutoff.

        Returns:
            Self-contained usable version; later rejection does not erase these bytes.

        Raises:
            ValueError: Fitting is forbidden, data is missing, or the design is singular.
        """
        definition.__post_init__()
        dataset.__post_init__()
        split.__post_init__()
        if {row.sample.row_id: row.sample for row in dataset.rows} != {
            row.row_id: row for row in split.samples
        }:
            raise ValueError("split sample records differ from verified dataset")
        codec = DomainCodec()
        used: tuple[ModelRow, ...] = ()
        if definition.mode == "configured":
            if split.fit_mode != "none" or definition.intercept is None or definition.slope is None:
                raise ValueError("configured model requires an explicit no-fit split")
            state = LinearState(
                center=ExactRatio(numerator="0", denominator="1"),
                intercept=definition.intercept,
                slope=definition.slope,
            )
        else:
            if split.fit_mode != "labels":
                raise ValueError("least-squares requires supervised label fitting")
            admitted = split.fitting_rows()
            split.require_fit_rows(tuple(row.row_id for row in admitted))
            lookup = {row.sample.row_id: row for row in dataset.rows}
            used = tuple(lookup[row.row_id] for row in admitted)
            if len(used) < 2 or any(row.feature is None or row.label is None for row in used):
                raise ValueError(
                    "fitting requires at least two complete admitted rows; no imputation"
                )
            x = tuple(LinearState.fraction(row.feature) for row in used if row.feature is not None)
            y = tuple(LinearState.fraction(row.label) for row in used if row.label is not None)
            center, average = sum(x, Fraction()) / len(x), sum(y, Fraction()) / len(y)
            denominator = sum(((value - center) ** 2 for value in x), Fraction())
            if denominator == 0:
                raise ValueError("singular calibration: training feature has zero variance")
            slope = (
                sum(((a - center) * (b - average) for a, b in zip(x, y, strict=True)), Fraction())
                / denominator
            )
            state = LinearState(
                center=ExactRatio.from_fraction(center),
                intercept=ExactRatio.from_fraction(average),
                slope=ExactRatio.from_fraction(slope),
            )
        payload = codec.encode_json(state)
        return ModelVersion(
            definition=definition,
            signature=dataset.signature,
            creation_attempt=attempt_id,
            created_at=created_at,
            available_at=available_at,
            training=split.training,
            fit_cutoff=split.fit_cutoff,
            fit_rows=tuple(row.sample.row_id for row in used),
            fit_input_sha256=hashlib.sha256(codec.encode_json(used)).hexdigest(),
            state_bytes=payload,
            state_sha256=hashlib.sha256(payload).hexdigest(),
        )

    @staticmethod
    def evaluate(
        versions: tuple[ModelVersion, ...],
        dataset: ModelDataset,
        split: TemporalSplit,
        *,
        partition: Literal["validation", "holdout"],
        known_at: datetime,
        max_mse: ExactRatio,
        reason: str,
    ) -> EvaluationRecord:
        """Select only then-available versions and retain delayed predictive error diagnostics.

        Args:
            versions: Exact reloaded versions eligible for this walk-forward evaluation.
            dataset: Verified rows and feature signature.
            split: Evaluation fold, independent of each model's construction fold.
            partition: Named validation or already-consumed holdout partition.
            known_at: Inclusive UTC outcome availability cutoff.
            max_mse: Declared exact acceptance threshold, frozen before evaluation.
            reason: Authored selection/rejection rationale; no empirical claim is inferred.

        Returns:
            Exact predictions, residual outcomes, exclusions and mean squared error.

        Raises:
            ValueError: A selected model is incompatible/unavailable, or no outcomes are usable.
        """
        dataset.__post_init__()
        split.__post_init__()
        if type(known_at) is not datetime or known_at.utcoffset() != timedelta(0):
            raise ValueError("evaluation cutoff must be a UTC datetime")
        max_mse.__post_init__()
        if int(max_mse.numerator) < 0 or partition not in ("validation", "holdout"):
            raise ValueError("invalid evaluation threshold or partition")
        if {row.sample.row_id: row.sample for row in dataset.rows} != {
            row.row_id: row for row in split.samples
        }:
            raise ValueError("evaluation split differs from verified dataset")
        for version in versions:
            version.__post_init__()
            if version.signature != dataset.signature:
                raise ValueError("incompatible model signature")
        if len({version.available_at for version in versions}) != len(versions):
            raise ValueError("ambiguous model availability ties")
        window = split.validation if partition == "validation" else split.holdout
        predictions: list[tuple[str, str, ExactRatio, ExactRatio, datetime]] = []
        excluded: list[tuple[str, str]] = []
        errors: list[Fraction] = []
        for row in dataset.rows:
            sample = row.sample
            if not window.contains(sample.decision_at):
                continue
            if partition == "validation" and sample.information_end >= split.holdout.start:
                raise ValueError("validation outcome reaches the frozen holdout")
            if row.feature is None or row.label is None or sample.label_available_at is None:
                excluded.append((sample.row_id, "missing feature or outcome; no imputation"))
                continue
            if sample.label_available_at > known_at:
                excluded.append((sample.row_id, "outcome unavailable at evaluation cutoff"))
                continue
            eligible = tuple(v for v in versions if v.available_at <= sample.decision_at)
            if not eligible:
                raise ValueError("no model was available at this walk-forward decision")
            selected = max(eligible, key=LinearModel._availability)
            prediction = selected.predict(row, dataset.signature)
            predictions.append(
                (sample.row_id, selected.identity, prediction, row.label, sample.label_available_at)
            )
            errors.append((LinearState.fraction(prediction) - LinearState.fraction(row.label)) ** 2)
        if not errors:
            raise ValueError("evaluation has no available complete outcomes")
        mse = sum(errors, Fraction()) / len(errors)
        return EvaluationRecord(
            dataset_sha256=hashlib.sha256(DomainCodec().encode_json(dataset)).hexdigest(),
            split_identity=split.identity,
            window=window,
            partition=partition,
            evaluated_as_of=known_at,
            predictions=tuple(predictions),
            excluded=tuple(excluded),
            mean_squared_error=ExactRatio.from_fraction(mse),
            selection="accepted" if mse <= LinearState.fraction(max_mse) else "rejected",
            reason=reason,
        )

    @staticmethod
    def _availability(version: ModelVersion) -> datetime:
        """Select the latest available version with ties already rejected."""
        return version.available_at


class EstimatorFactory(Protocol):
    """Construct a compatible estimator for one registered model implementation."""

    def __call__(self, definition: LinearDefinition) -> LinearModel:
        """Construct one estimator from the retained typed definition.

        Args:
            definition: Immutable configured or least-squares model settings.

        Returns:
            Estimator implementing the model consumer contract.
        """
        ...


class EstimatorRegistry:
    """Resolve compatible estimator implementations by explicit model identity."""

    def __init__(self) -> None:
        """Register the existing exact linear estimator by default."""
        self._factories: dict[str, EstimatorFactory] = {}
        self.register("linear-return", self._resolve_linear)

    @property
    def identities(self) -> tuple[str, ...]:
        """Return registered estimator identities in insertion order.

        Returns:
            Stable implementation identities available to this registry.
        """
        return tuple(self._factories)

    def register(self, identity: str, factory: EstimatorFactory) -> None:
        """Register one typed estimator factory under a unique identity.

        Args:
            identity: Stable estimator/model implementation identity.
            factory: Callable constructing an estimator from typed settings.

        Raises:
            ValueError: If the identity is invalid or duplicated.
        """
        identity = self._validate_identity(identity)
        if identity in self._factories:
            raise ValueError(f"duplicate estimator implementation identity: {identity}")
        self._factories[identity] = factory

    def resolve(self, identity: str, definition: LinearDefinition) -> LinearModel:
        """Construct a compatible estimator for one registered model identity.

        Args:
            identity: Versioned model implementation identity.
            definition: Immutable model definition supplied by the study or version.

        Returns:
            New estimator instance owned by the caller.

        Raises:
            ValueError: If the identity is invalid or unsupported.
        """
        self._validate_identity(identity)
        factory = self._factories.get(identity)
        if factory is None:
            raise ValueError(f"unsupported installed estimator: {identity}")
        definition.__post_init__()
        return factory(definition)

    def supports(self, identity: str) -> bool:
        """Report whether one estimator identity is registered.

        Args:
            identity: Candidate estimator implementation identity.

        Returns:
            Whether the identity is registered.
        """
        return type(identity) is str and bool(identity) and identity in self._factories

    @staticmethod
    def _validate_identity(identity: str) -> str:
        """Validate one nonempty, trimmed estimator identity."""
        if type(identity) is not str or not identity or identity != identity.strip():
            raise ValueError("estimator implementation identity must be a nonempty trimmed string")
        return identity

    @staticmethod
    def _resolve_linear(definition: LinearDefinition) -> LinearModel:
        """Resolve the maintained linear estimator after validating its definition."""
        if type(definition) is not LinearDefinition:
            raise TypeError("linear-return implementation requires LinearDefinition")
        definition.__post_init__()
        return LinearModel()
