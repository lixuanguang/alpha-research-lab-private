"""Fit transforms only on admitted temporal rows and reload immutable versioned state."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from financial_units import ExactRatio
from research.experiments import TemporalSplit
from research.features.contracts import FeatureVector
from research.observations import NumericField
from serialization import DomainCodec, WireRecord


class VectorSignature(WireRecord, frozen=True):
    """Bind ordered fields to feature and optional fitted-transform versions."""

    definition: str
    fields: tuple[NumericField, ...]
    transform_identity: str | None

    def __post_init__(self) -> None:
        """Validate immutable schema metadata independently of values."""
        if (
            type(self.definition) is not str
            or not self.definition
            or type(self.fields) is not tuple
            or not self.fields
        ):
            raise ValueError("invalid vector signature")
        for field in self.fields:
            field.__post_init__()
        if len({f.name for f in self.fields}) != len(self.fields):
            raise ValueError("duplicate vector field")
        if self.transform_identity is not None and (
            type(self.transform_identity) is not str or not self.transform_identity
        ):
            raise ValueError("invalid transform version")

    @classmethod
    def of(cls, row: FeatureVector) -> VectorSignature:
        """Read a validated vector's complete signature without its outcome values."""
        row.__post_init__()
        return cls(
            definition=row.definition, fields=row.fields, transform_identity=row.transform_identity
        )


class FittingRows:
    """Admit feature bytes by identity through the existing purge/embargo split owner."""

    @staticmethod
    def select(rows: tuple[FeatureVector, ...], split: TemporalSplit) -> tuple[FeatureVector, ...]:
        """Select train-only complete vectors; reject mismatched sample metadata.

        Sample row IDs are the feature vector digest. Outcomes are deliberately
        absent; supervised consumers additionally bind and validate label bytes.
        Missing admitted features fail rather than silently changing the sample.
        """
        split.__post_init__()
        if type(rows) is not tuple or not rows:
            raise ValueError("fitting requires immutable feature rows")
        by_id = {r.identity: r for r in rows}
        if len(by_id) != len(rows):
            raise ValueError("duplicate fitting row")
        for sample in split.samples:
            row = by_id.get(sample.row_id)
            if (
                row is None
                or row.decision_at != sample.decision_at
                or row.available_at != sample.features_available_at
                or sample.information_start > row.information_start
            ):
                raise ValueError("split sample does not match feature bytes/clocks")
        if set(by_id) != {s.row_id for s in split.samples}:
            raise ValueError("split must describe every supplied feature row")
        admitted = tuple(by_id[s.row_id] for s in split.fitting_rows())
        split.require_fit_rows(tuple(r.identity for r in admitted))
        signature = VectorSignature.of(admitted[0])
        for row in admitted:
            if VectorSignature.of(row) != signature or any(v is None for v in row.values):
                raise ValueError("fitting requires complete matching feature signatures")
            row.require_available(row.decision_at)
        return admitted


class TransformAdapter(Protocol):
    """Own fitted transform semantics and portable state, with no implicit inference-time fit."""

    @property
    def identity(self) -> str:
        """Version implementation and all authored transform parameters."""
        ...

    def fit(self, rows: tuple[FeatureVector, ...]) -> bytes:
        """Construct immutable state from only the supplied admitted training vectors."""
        ...

    def output_fields(
        self, state: bytes, fields: tuple[NumericField, ...]
    ) -> tuple[NumericField, ...]:
        """Validate state and declare ordered output names/units, including selected columns."""
        ...

    def apply(self, state: bytes, row: FeatureVector) -> tuple[ExactRatio | None, ...]:
        """Validate state and return values in the declared output signature."""
        ...


class TransformVersion(WireRecord, frozen=True):
    """Retain state bytes, fit identity/cutoff and availability independently of creation time."""

    implementation: str
    signature: VectorSignature
    output_fields: tuple[NumericField, ...]
    split_identity: str
    fit_rows: tuple[str, ...]
    fit_cutoff: datetime
    available_at: datetime
    state: bytes
    state_sha256: str
    schema_version: Literal["transform-version"] = "transform-version"

    def __post_init__(self) -> None:
        """Reject changed bytes, unsupported schemas and invented pre-fit availability."""
        self.signature.__post_init__()
        VectorSignature(
            definition=self.signature.definition, fields=self.output_fields, transform_identity=None
        )
        self._require_utc(self.fit_cutoff, field_name="fit_cutoff")
        self._require_utc(self.available_at, field_name="available_at")
        if (
            self.schema_version != "transform-version"
            or type(self.state) is not bytes
            or hashlib.sha256(self.state).hexdigest() != self.state_sha256
            or self.available_at < self.fit_cutoff
        ):
            raise ValueError("invalid fitted transform version")
        if (
            any(type(v) is not str or not v for v in (self.implementation, self.split_identity))
            or type(self.fit_rows) is not tuple
            or not self.fit_rows
            or len(set(self.fit_rows)) != len(self.fit_rows)
            or any(type(v) is not str or not v for v in self.fit_rows)
        ):
            raise ValueError("transform requires implementation and unique fitted rows")

    @property
    def identity(self) -> str:
        """Bind the full fitted version for feature-store and model signatures."""
        self.__post_init__()
        return hashlib.sha256(DomainCodec().encode_json(self)).hexdigest()


class FittedTransform:
    """Enforce temporal admission and reload-only transformation around an injected adapter."""

    def __init__(self, adapter: TransformAdapter) -> None:
        """Bind the explicitly selected implementation; no global factory or default replaces it."""
        self._adapter = adapter

    @property
    def identity(self) -> str:
        """Expose the selected adapter identity for pre-work admission."""
        return self._adapter.identity

    def fit(
        self, rows: tuple[FeatureVector, ...], split: TemporalSplit, *, available_at: datetime
    ) -> TransformVersion:
        """Fit only admitted rows and retain the exact state and split provenance."""
        admitted = FittingRows.select(rows, split)
        if split.fit_cutoff is None:
            raise ValueError("transform requires a fitting cutoff")
        TransformVersion._require_utc(available_at, field_name="available_at")
        if available_at < split.fit_cutoff:
            raise ValueError("transform cannot precede fitting cutoff")
        state = self._adapter.fit(admitted)
        return TransformVersion(
            implementation=self._adapter.identity,
            signature=VectorSignature.of(admitted[0]),
            output_fields=self._adapter.output_fields(state, admitted[0].fields),
            split_identity=split.identity,
            fit_rows=tuple(r.identity for r in admitted),
            fit_cutoff=split.fit_cutoff,
            available_at=available_at,
            state=state,
            state_sha256=hashlib.sha256(state).hexdigest(),
        )

    def apply(self, version: TransformVersion, row: FeatureVector) -> FeatureVector:
        """Transform then-available inputs without refitting; future fitted state is refused."""
        version.__post_init__()
        row.require_available(row.decision_at)
        if (
            version.implementation != self._adapter.identity
            or VectorSignature.of(row) != version.signature
            or version.available_at > row.decision_at
        ):
            raise ValueError("transform signature, implementation or availability mismatch")
        return self.training_apply(version, row)

    def training_apply(self, version: TransformVersion, row: FeatureVector) -> FeatureVector:
        """Transform an admitted fit row retrospectively, never representing it as a past decision.

        This permits estimator fitting on train-only centered values. Other rows use
        apply(), which checks historical availability. Output availability is the
        later of the original value and the actual fitted transform availability.
        """
        version.__post_init__()
        row.__post_init__()
        if (
            version.implementation != self._adapter.identity
            or VectorSignature.of(row) != version.signature
        ):
            raise ValueError("transform signature or implementation mismatch")
        if row.decision_at < version.available_at and row.identity not in version.fit_rows:
            raise ValueError("retrospective transform requires an admitted fit row")
        if self._adapter.output_fields(version.state, row.fields) != version.output_fields:
            raise ValueError("transform output signature differs from fitted state")
        values = self._adapter.apply(version.state, row)
        reasons = (
            row.reasons
            if version.output_fields == row.fields
            else tuple(
                "transformed" if value is not None else "missing_transformed_input"
                for value in values
            )
        )
        availability = max(row.available_at, version.available_at)
        return FeatureVector(
            entity=row.entity,
            decision_at=row.decision_at,
            event_at=row.event_at,
            information_start=row.information_start,
            available_at=availability,
            expires_at=max(row.expires_at, availability),
            definition=row.definition,
            fields=version.output_fields,
            values=values,
            reasons=reasons,
            input_identity=row.identity,
            transform_identity=version.identity,
        )


class CenterColumns:
    """Subtract train-only exact column means; preserve units and explicit missing values."""

    @property
    def identity(self) -> str:
        """Version exact mean subtraction and strict complete-fit behavior."""
        return "center-columns"

    def fit(self, rows: tuple[FeatureVector, ...]) -> bytes:
        """Retain one exact mean per column; the caller supplies only admitted rows."""
        means: list[ExactRatio] = []
        for index in range(len(rows[0].fields)):
            column = tuple(row.values[index] for row in rows)
            if any(v is None for v in column):
                raise ValueError("centering cannot fit missing values")
            total = sum(
                (Fraction(int(v.numerator), int(v.denominator)) for v in column if v is not None),
                Fraction(),
            )
            means.append(ExactRatio.from_fraction(total / len(rows)))
        return DomainCodec().encode_json(_Centers(values=tuple(means)))

    def output_fields(
        self, state: bytes, fields: tuple[NumericField, ...]
    ) -> tuple[NumericField, ...]:
        """Preserve original names/units while verifying the saved mean count."""
        means = DomainCodec().decode_json(state, _Centers).values
        if len(means) != len(fields):
            raise ValueError("centering output signature width mismatch")
        return fields

    def apply(self, state: bytes, row: FeatureVector) -> tuple[ExactRatio | None, ...]:
        """Reload exact centers and reject a state whose width differs from the signature."""
        means = DomainCodec().decode_json(state, _Centers).values
        return tuple(
            None
            if value is None
            else ExactRatio.from_fraction(
                Fraction(int(value.numerator), int(value.denominator))
                - Fraction(int(mean.numerator), int(mean.denominator))
            )
            for value, mean in zip(row.values, means, strict=True)
        )


class _Centers(WireRecord, frozen=True):
    """Encode the reference transform's exact fitted column means."""

    values: tuple[ExactRatio, ...]

    def __post_init__(self) -> None:
        """Validate nonempty immutable exact state."""
        if type(self.values) is not tuple or not self.values:
            raise ValueError("centers require a nonempty tuple")
        for value in self.values:
            value.__post_init__()
