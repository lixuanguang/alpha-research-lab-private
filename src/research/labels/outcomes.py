"""Keep arbitrary supervised outcomes separate from decision-time feature vectors."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from fractions import Fraction
from typing import Protocol

# project library imports
from financial_units import ExactRatio
from research.experiments import SampleInterval
from research.features import FeatureVector
from research.observations import NamedObservation, NumericField
from serialization import DomainCodec, WireRecord


class Outcome(WireRecord, frozen=True):
    """Bind a label to exact feature bytes and its own full information/knowledge interval."""

    feature_identity: str
    definition: str
    field: NumericField
    information_start: datetime
    information_end: datetime
    available_at: datetime | None
    value: ExactRatio | None
    reason: str
    lineage: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject fabricated availability, malformed values and absent lineage."""
        for text in (self.feature_identity, self.definition, self.reason):
            if type(text) is not str or not text:
                raise ValueError("outcome requires identities and reason")
        self.field.__post_init__()
        self._require_utc(self.information_start, field_name="information_start")
        self._require_utc(self.information_end, field_name="information_end")
        if self.information_start > self.information_end:
            raise ValueError("outcome information interval is reversed")
        if self.available_at is not None:
            self._require_utc(self.available_at, field_name="available_at")
            if self.available_at < self.information_end:
                raise ValueError("outcome precedes its information end")
        if (
            type(self.lineage) is not tuple
            or not self.lineage
            or any(type(v) is not str or not v for v in self.lineage)
        ):
            raise ValueError("outcome requires immutable source lineage")
        if self.value is not None:
            if type(self.value) is not ExactRatio or self.available_at is None:
                raise ValueError("outcome value requires exact known result")
            self.value.__post_init__()

    def sample(self, row: FeatureVector) -> SampleInterval:
        """Bind independent label and feature bytes into the existing temporal split contract."""
        self.__post_init__()
        if (
            self.feature_identity != row.identity
            or not self.information_start <= row.decision_at <= self.information_end
        ):
            raise ValueError("outcome does not describe this feature sample")
        return SampleInterval(
            row_id=row.identity,
            input_sha256=hashlib.sha256(DomainCodec().encode_json((row, self))).hexdigest(),
            decision_at=row.decision_at,
            information_start=min(self.information_start, row.information_start),
            information_end=self.information_end,
            features_available_at=row.available_at,
            label_available_at=self.available_at,
        )


class LabelAdapter(Protocol):
    """Generate a versioned outcome from independently admitted base/future observations."""

    def evaluate(
        self,
        row: FeatureVector,
        base: NamedObservation,
        future: NamedObservation,
        *,
        observed_at: datetime,
    ) -> Outcome:
        """Retain missing or pending outcomes without leaking them into feature inputs."""
        ...


class NumericDifference:
    """Provide an exact non-return label over matching named scalar observations."""

    def evaluate(
        self,
        row: FeatureVector,
        base: NamedObservation,
        future: NamedObservation,
        *,
        observed_at: datetime,
    ) -> Outcome:
        """Calculate future minus frozen base in original units, or retain a pending result."""
        row.__post_init__()
        base.__post_init__()
        future.__post_init__()
        Outcome._require_utc(observed_at, field_name="observed_at")
        if (
            base.input != future.input
            or base.entity != row.entity
            or future.entity != row.entity
            or base.event_at > row.decision_at
            or base.available_at is None
            or base.available_at > row.decision_at
            or future.event_at <= row.decision_at
        ):
            raise ValueError("difference label requires matching causal base and future input")
        available = future.available_at
        value = None
        if (
            base.value is not None
            and future.value is not None
            and available is not None
            and available <= observed_at
        ):
            value = ExactRatio.from_fraction(
                Fraction(int(future.value.numerator), int(future.value.denominator))
                - Fraction(int(base.value.numerator), int(base.value.denominator))
            )
        return Outcome(
            feature_identity=row.identity,
            definition=hashlib.sha256(
                DomainCodec().encode_json(
                    ("numeric-difference", base.input, future.event_at - row.decision_at)
                )
            ).hexdigest(),
            field=NumericField(name="difference", units=base.input.field.units),
            information_start=base.event_at,
            information_end=future.event_at,
            available_at=available if value is not None else None,
            value=value,
            reason="observed" if value is not None else "missing_or_pending",
            lineage=(base.lineage, future.lineage),
        )
