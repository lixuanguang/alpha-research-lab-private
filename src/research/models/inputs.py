"""Admit retained price diagnostics at a strict, exact-valued dataframe boundary."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from typing import Literal

# third party library imports
import pandas as pd
import pandera.pandas as pa

# project library imports
from financial_units import ExactRatio
from research.experiments import Fingerprint, SampleInterval
from research.results import FeatureStudyResult
from serialization import DomainCodec, WireRecord


class ModelSignature(WireRecord, frozen=True, kw_only=True):
    """Bind ordered feature names, definitions, units and the separate prediction target."""

    feature_order: tuple[str, ...] = ("trailing_return",)
    feature_identity: str
    label_identity: str
    units: Literal["dimensionless"] = "dimensionless"
    numerical_contract: Literal["exact-rational"] = "exact-rational"

    def __post_init__(self) -> None:
        """Reject incompatible order, units, definitions and numerical representation."""
        if (
            self.feature_order != ("trailing_return",)
            or self.units != "dimensionless"
            or self.numerical_contract != "exact-rational"
        ):
            raise ValueError("unsupported model feature order, units or numerical contract")
        Fingerprint(name="feature", sha256=self.feature_identity)
        Fingerprint(name="label", sha256=self.label_identity)


class ModelRow(WireRecord, frozen=True, kw_only=True):
    """Carry exact nullable values with verified information and availability intervals."""

    sample: SampleInterval
    feature: ExactRatio | None
    label: ExactRatio | None

    def __post_init__(self) -> None:
        """Reject unsafe construction while preserving explicit missing values."""
        if type(self.sample) is not SampleInterval:
            raise TypeError("model row requires a sample interval")
        self.sample.__post_init__()
        for value in (self.feature, self.label):
            if value is not None:
                if type(value) is not ExactRatio:
                    raise TypeError("model values must remain ExactRatio")
                value.__post_init__()
        if self.label is not None and self.sample.label_available_at is None:
            raise ValueError("present label requires known availability")


class ModelFrame:
    """Validate the selected diagnostic's dataframe without coercion or imputation.

    All columns deliberately use object dtype: UTC Python datetimes and exact
    rational objects retain microseconds and arbitrary precision. Pandera checks
    order, dtype, nullability and element constraints; domain validation owns
    identities, clocks and fitting permission. Caller frames are never modified.
    """

    _COLUMNS: tuple[str, ...] = (
        "row_id",
        "decision_at",
        "features_available_at",
        "label_available_at",
        "units",
        "trailing_return",
        "forward_return",
    )

    def __init__(self) -> None:
        """Compile one explicit schema for the actual one-feature consumer."""
        self._schema = pa.DataFrameSchema(
            {
                "row_id": pa.Column(object, pa.Check(self._name, element_wise=True), unique=True),
                "decision_at": pa.Column(object, pa.Check(self._utc, element_wise=True)),
                "features_available_at": pa.Column(object, pa.Check(self._utc, element_wise=True)),
                "label_available_at": pa.Column(
                    object,
                    pa.Check(self._optional_utc, element_wise=True, ignore_na=False),
                    nullable=True,
                ),
                "units": pa.Column(object, pa.Check(self._units, element_wise=True)),
                "trailing_return": pa.Column(
                    object, pa.Check(self._ratio, element_wise=True, ignore_na=False), nullable=True
                ),
                "forward_return": pa.Column(
                    object, pa.Check(self._ratio, element_wise=True, ignore_na=False), nullable=True
                ),
            },
            ordered=True,
            strict=True,
            coerce=False,
            unique_column_names=True,
        )

    def validate(self, frame: pd.DataFrame) -> None:
        """Require the declared order, object dtypes, UTC clocks and exact nullable ratios.

        Args:
            frame: Caller-owned frame with the seven explicit model input columns.

        Raises:
            pa.errors.SchemaError: A column, dtype, clock, unit or value violates the schema.
        """
        self._schema.validate(frame, inplace=False)

    def from_rows(self, rows: tuple[ModelRow, ...]) -> pd.DataFrame:
        """Build and validate the dataframe projection while retaining typed domain rows.

        Args:
            rows: Immutable model records with known missingness and information intervals.

        Returns:
            A new validated object-dtype frame; no value is cast to float or filled.
        """
        values: list[list[object]] = []
        for row in rows:
            row.__post_init__()
            values.append(
                [
                    row.sample.row_id,
                    row.sample.decision_at,
                    row.sample.features_available_at,
                    row.sample.label_available_at,
                    "dimensionless",
                    row.feature,
                    row.label,
                ]
            )
        frame = pd.DataFrame(values, columns=list(self._COLUMNS), dtype=object)
        self.validate(frame)
        return frame

    @staticmethod
    def _name(value: object) -> bool:
        """Require explicit nonempty row identities."""
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _utc(value: object) -> bool:
        """Refuse timestamp coercion, NaT and naive clocks."""
        return type(value) is datetime and value.utcoffset() == timedelta(0)

    @staticmethod
    def _optional_utc(value: object) -> bool:
        """Represent unknown outcome availability only as explicit None."""
        return value is None or ModelFrame._utc(value)

    @staticmethod
    def _units(value: object) -> bool:
        """Admit only the selected dimensionless return output."""
        return value == "dimensionless"

    @staticmethod
    def _ratio(value: object) -> bool:
        """Require canonical rational records rather than approximate financial values."""
        if value is None:
            return True
        if type(value) is not ExactRatio:
            return False
        try:
            value.__post_init__()
        except TypeError, ValueError:
            return False
        return True


class ModelDataset(WireRecord, frozen=True, kw_only=True):
    """Retain input byte identities and aligned model rows admitted from MR 3 diagnostics."""

    signature: ModelSignature
    sources: tuple[str, ...]
    rows: tuple[ModelRow, ...]

    def __post_init__(self) -> None:
        """Validate direct construction and bounded, unique aligned rows."""
        if type(self.signature) is not ModelSignature:
            raise TypeError("dataset requires ModelSignature")
        self.signature.__post_init__()
        if type(self.sources) is not tuple or not self.sources:
            raise ValueError("model dataset requires retained source identities")
        for source in self.sources:
            Fingerprint(name="source", sha256=source)
        if type(self.rows) is not tuple or not 1 <= len(self.rows) <= 1024:
            raise ValueError("model dataset requires 1 to 1024 rows")
        for row in self.rows:
            if type(row) is not ModelRow:
                raise TypeError("dataset requires ModelRow")
            row.__post_init__()
        if len({row.sample.row_id for row in self.rows}) != len(self.rows):
            raise ValueError("model row identities must be unique")

    @classmethod
    def from_results(cls, payloads: tuple[bytes, ...]) -> ModelDataset:
        """Verify MR 3 result identities and align feature/label records without joining clocks.

        Args:
            payloads: Completed diagnostic result bytes verified against their retained attempts.

        Returns:
            Bounded exact dataset with a validated Pandera projection.

        Raises:
            ValueError: Inputs mix definitions, duplicate rows, omit labels or misstate intervals.
        """
        codec = DomainCodec()
        rows: list[ModelRow] = []
        signature: ModelSignature | None = None
        for payload in payloads:
            result = codec.decode_json(payload, FeatureStudyResult)
            if result.label_definition is None:
                raise ValueError("model consumer requires a declared forward label")
            current = ModelSignature(
                feature_identity=result.feature_definition.identity,
                label_identity=result.label_definition.identity,
            )
            if signature is not None and current != signature:
                raise ValueError("model inputs mix feature/label definitions")
            signature = current
            if tuple(name for name, _ in result.features) != tuple(
                name for name, _ in result.labels
            ) or tuple(name for name, _ in result.features) != tuple(
                sample.row_id for sample in result.samples
            ):
                raise ValueError("model input rows are not aligned")
            for (_, feature), (_, label), sample in zip(
                result.features, result.labels, result.samples, strict=True
            ):
                expected = SampleInterval(
                    row_id=sample.row_id,
                    input_sha256=hashlib.sha256(codec.encode_json((feature, label))).hexdigest(),
                    decision_at=feature.decision_at,
                    information_start=label.information_start,
                    information_end=label.information_end,
                    features_available_at=feature.available_at,
                    label_available_at=label.available_at,
                )
                if (
                    sample != expected
                    or label.decision_at != feature.decision_at
                    or feature.definition_identity != current.feature_identity
                    or label.definition_identity != current.label_identity
                ):
                    raise ValueError("model input digest, definition or interval mismatch")
                rows.append(ModelRow(sample=sample, feature=feature.value, label=label.value))
        if signature is None:
            raise ValueError("model requires feature results")
        dataset = cls(
            signature=signature,
            sources=tuple(hashlib.sha256(payload).hexdigest() for payload in payloads),
            rows=tuple(rows),
        )
        ModelFrame().from_rows(dataset.rows)
        return dataset
