"""Fit arbitrary exact estimators and reload state through declared multi-feature signatures."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from financial_units import ExactRatio
from research.experiments import TemporalSplit
from research.features import (
    FeatureVector,
    FittedTransform,
    FittingRows,
    TransformVersion,
    VectorSignature,
)
from research.labels import Outcome
from research.observations import NumericField
from research.results import Prediction
from serialization import DomainCodec, WireRecord


class EstimatorAdapter(Protocol):
    """Own an estimator's immutable exact state; implementations need not subclass LinearModel."""

    @property
    def identity(self) -> str:
        """Pin implementation and all hyperparameters, including seeds where applicable."""
        ...

    def fit(self, rows: tuple[FeatureVector, ...], outcomes: tuple[ExactRatio, ...]) -> bytes:
        """Fit only the admitted aligned training sample and return portable state bytes."""
        ...

    def predict(self, state: bytes, row: FeatureVector) -> ExactRatio:
        """Validate state and return an exact prediction; never fit implicitly."""
        ...


class EstimatorVersion(WireRecord, frozen=True):
    """Retain the complete estimator, transformed signature and label/fit provenance."""

    implementation: str
    signature: VectorSignature
    output: NumericField
    label_definition: str
    split_identity: str
    fit_rows: tuple[str, ...]
    fit_inputs_sha256: str
    fit_cutoff: datetime
    available_at: datetime
    state: bytes
    state_sha256: str
    schema_version: Literal["estimator-version"] = "estimator-version"

    def __post_init__(self) -> None:
        """Reject changed state, absent provenance and impossible historical availability."""
        self.signature.__post_init__()
        self.output.__post_init__()
        self._require_utc(self.fit_cutoff, field_name="fit_cutoff")
        self._require_utc(self.available_at, field_name="available_at")
        if (
            self.schema_version != "estimator-version"
            or type(self.state) is not bytes
            or hashlib.sha256(self.state).hexdigest() != self.state_sha256
            or self.available_at < self.fit_cutoff
        ):
            raise ValueError("invalid estimator version or state digest")
        if (
            any(
                type(v) is not str or not v
                for v in (
                    self.implementation,
                    self.label_definition,
                    self.split_identity,
                    self.fit_inputs_sha256,
                )
            )
            or type(self.fit_rows) is not tuple
            or not self.fit_rows
            or len(set(self.fit_rows)) != len(self.fit_rows)
            or any(type(v) is not str or not v for v in self.fit_rows)
        ):
            raise ValueError("estimator requires complete unique fit provenance")

    @property
    def identity(self) -> str:
        """Identify reload bytes together with their training and inference contracts."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class EstimatorLifecycle:
    """Enforce causal fitting, transform admission and signature-safe reload inference."""

    def __init__(self, adapter: EstimatorAdapter) -> None:
        """Bind the explicitly injected estimator without a built-in fallback."""
        self._adapter = adapter

    @property
    def identity(self) -> str:
        """Expose the selected adapter identity for pre-work admission."""
        return self._adapter.identity

    def fit(
        self,
        rows: tuple[FeatureVector, ...],
        outcomes: tuple[Outcome, ...],
        split: TemporalSplit,
        *,
        available_at: datetime,
        transform: FittedTransform | None = None,
        transform_version: TransformVersion | None = None,
    ) -> EstimatorVersion:
        """Fit only split-admitted labels/features; optional preprocessing fits separately.

        Complete split records must equal actual feature/label bytes. The adapter
        receives no validation or holdout rows, labels or source history.
        """
        admitted = FittingRows.select(rows, split)
        if split.fit_mode != "labels" or split.fit_cutoff is None:
            raise ValueError("supervised estimator requires label fitting")
        EstimatorVersion._require_utc(available_at, field_name="available_at")
        if available_at < split.fit_cutoff:
            raise ValueError("model cannot precede fitting cutoff")
        labels = {o.feature_identity: o for o in outcomes}
        samples = {s.row_id: s for s in split.samples}
        if len(labels) != len(outcomes) or set(labels) != {r.identity for r in rows}:
            raise ValueError("labels must align uniquely with all feature rows")
        for row in rows:
            if labels[row.identity].sample(row) != samples[row.identity]:
                raise ValueError("split differs from actual feature/label bytes")
        # A row whose label is missing is left out, as one missing a feature is.
        admitted = tuple(r for r in admitted if labels[r.identity].value is not None)
        if not admitted:
            raise ValueError("fitting requires at least one labelled complete training row")
        selected = tuple(labels[r.identity] for r in admitted)
        if any(
            o.value is None
            or o.available_at is None
            or o.available_at > split.fit_cutoff
            or (o.definition, o.field) != (selected[0].definition, selected[0].field)
            for o in selected
        ):
            raise ValueError("training labels missing, late or incompatible")
        fitted = admitted
        if (transform is None) != (transform_version is None):
            raise ValueError("transform implementation and version must be paired")
        if transform is not None and transform_version is not None:
            if (
                transform_version.split_identity != split.identity
                or not {r.identity for r in admitted} <= set(transform_version.fit_rows)
                or transform_version.available_at > available_at
            ):
                raise ValueError("transform fit or availability differs from model training")
            fitted = tuple(transform.training_apply(transform_version, row) for row in admitted)
        state = self._adapter.fit(fitted, tuple(o.value for o in selected if o.value is not None))
        return EstimatorVersion(
            implementation=self._adapter.identity,
            signature=VectorSignature.of(fitted[0]),
            output=selected[0].field,
            label_definition=selected[0].definition,
            split_identity=split.identity,
            fit_rows=tuple(r.identity for r in admitted),
            fit_inputs_sha256=hashlib.sha256(
                DomainCodec().encode_json((fitted, selected))
            ).hexdigest(),
            fit_cutoff=split.fit_cutoff,
            available_at=available_at,
            state=state,
            state_sha256=hashlib.sha256(state).hexdigest(),
        )

    def predict(self, version: EstimatorVersion, row: FeatureVector) -> Prediction:
        """Reload only compatible then-available state, refusing missing feature values."""
        version.__post_init__()
        row.require_available(row.decision_at)
        if (
            version.implementation != self._adapter.identity
            or version.signature != VectorSignature.of(row)
            or version.available_at > row.decision_at
            or any(v is None for v in row.values)
        ):
            raise ValueError("model signature, availability or feature missingness mismatch")
        return Prediction(
            entity=row.entity,
            decision_at=row.decision_at,
            feature_identity=row.identity,
            model_identity=version.identity,
            field=version.output,
            value=self._adapter.predict(version.state, row),
        )


class NearestExample:
    """Provide a non-linear multi-feature reference estimator with exact nearest-row distance.

    Inputs must share units so squared Euclidean distances can be added. Equal
    distances select the first temporally ordered admitted row deterministically.
    State retains actual transformed training points and outcomes, not executable code.
    """

    @property
    def identity(self) -> str:
        """Version exact one-nearest-example prediction and first-row tie handling."""
        return "nearest-example"

    def fit(self, rows: tuple[FeatureVector, ...], outcomes: tuple[ExactRatio, ...]) -> bytes:
        """Save complete exact training rows; reject mixed distance units."""
        if not rows or len(rows) != len(outcomes) or len({f.units for f in rows[0].fields}) != 1:
            raise ValueError("nearest example requires aligned rows with common feature units")
        return DomainCodec().encode_json(
            _Examples(points=tuple(self._values(row) for row in rows), outcomes=outcomes)
        )

    def predict(self, state: bytes, row: FeatureVector) -> ExactRatio:
        """Select the earliest nearest saved point with exact squared distance."""
        saved = DomainCodec().decode_json(state, _Examples)
        values = self._values(row)
        distances = tuple(
            sum(
                (
                    (
                        Fraction(int(a.numerator), int(a.denominator))
                        - Fraction(int(b.numerator), int(b.denominator))
                    )
                    ** 2
                    for a, b in zip(point, values, strict=True)
                ),
                Fraction(),
            )
            for point in saved.points
        )
        return saved.outcomes[distances.index(min(distances))]

    @staticmethod
    def _values(row: FeatureVector) -> tuple[ExactRatio, ...]:
        """Refuse missing values before using a point in the distance calculation."""
        if any(v is None for v in row.values):
            raise ValueError("nearest example cannot consume missing features")
        return tuple(v for v in row.values if v is not None)


class _Examples(WireRecord, frozen=True):
    """Retain exact points and targets without pickle or executable state."""

    points: tuple[tuple[ExactRatio, ...], ...]
    outcomes: tuple[ExactRatio, ...]

    def __post_init__(self) -> None:
        """Reject incomplete, ragged or malformed estimator state."""
        if (
            type(self.points) is not tuple
            or type(self.outcomes) is not tuple
            or not self.points
            or len(self.points) != len(self.outcomes)
            or not self.points[0]
        ):
            raise ValueError("invalid nearest-example state")
        for point in self.points:
            if type(point) is not tuple or len(point) != len(self.points[0]):
                raise ValueError("ragged nearest-example state")
            for value in point:
                value.__post_init__()
        for value in self.outcomes:
            value.__post_init__()
