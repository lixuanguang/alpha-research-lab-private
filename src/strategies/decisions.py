"""Describe strategy decisions independently of portfolio admission and executable authority."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal, Protocol

# project library imports
from financial_units import Quantity
from research.features import FeatureVector
from research.observations import NumericField
from research.results import Prediction
from serialization import DomainCodec, WireRecord
from strategies.intents import (
    DecisionIntent,
    ExposureIntent,
    OrderIntent,
    QuoteIntent,
    TargetIntent,
)


class DecisionContext(WireRecord, frozen=True):
    """Supply only a then-available feature vector and its optional aligned prediction."""

    features: FeatureVector
    prediction: Prediction | None
    evaluated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject foreign predictions and future or expired feature state."""
        self.features.require_available(self.decision_at)
        if self.prediction is not None:
            self.prediction.__post_init__()
            if (
                self.prediction.feature_identity,
                self.prediction.entity,
                self.prediction.decision_at,
            ) != (self.features.identity, self.features.entity, self.features.decision_at):
                raise ValueError("prediction does not belong to decision features")

    @property
    def decision_at(self) -> datetime:
        """Return the consuming decision clock without rewriting stored feature provenance."""
        at = self.features.decision_at if self.evaluated_at is None else self.evaluated_at
        self._require_utc(at, field_name="decision at")
        return at


class DecisionTransition(WireRecord, frozen=True):
    """Return typed intent and immutable successor policy state without side effects."""

    intent: DecisionIntent
    state: bytes

    def __post_init__(self) -> None:
        """Refuse unknown output contracts and mutable state."""
        if (
            type(self.intent) not in (TargetIntent, ExposureIntent, OrderIntent, QuoteIntent)
            or type(self.state) is not bytes
        ):
            raise ValueError("invalid decision transition")
        self.intent.__post_init__()


class DecisionPolicy(Protocol):
    """Turn features/predictions into an intent with explicitly portable instance state."""

    @property
    def identity(self) -> str:
        """Pin strategy implementation and complete parameters."""
        ...

    @property
    def output(self) -> Literal["target", "exposure", "order", "quote"]:
        """Declare the only admitted output family before work starts."""
        ...

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Reject unsupported feature names/units and prediction contracts before source access."""
        ...

    def initial_state(self) -> bytes:
        """Create independent initial state for each selected instance/entity."""
        ...

    def validate_state(self, state: bytes) -> None:
        """Reject foreign or malformed state without mutating hidden state."""
        ...

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Return a pure state transition with no order submission or risk self-approval."""
        ...


class DecisionRecord(WireRecord, frozen=True):
    """Retain decision ownership, exact feature/model identity and output for future consumers."""

    instance: str
    entity: str
    at: datetime
    policy: str
    feature_identity: str
    model_identity: str | None
    intent: DecisionIntent

    def __post_init__(self) -> None:
        """Validate immutable decision lineage and typed economics."""
        self._require_utc(self.at, field_name="decision at")
        for value in (self.instance, self.entity, self.policy, self.feature_identity):
            if type(value) is not str or not value:
                raise ValueError("decision requires instance, entity and component identities")
        if self.model_identity is not None and (
            type(self.model_identity) is not str or not self.model_identity
        ):
            raise ValueError("invalid decision model identity")
        if type(self.intent) not in (TargetIntent, ExposureIntent, OrderIntent, QuoteIntent):
            raise ValueError("unsupported decision intent")
        self.intent.__post_init__()


class ConfirmedSignal:
    """Request a long target after an explicit number of consecutive positive observations.

    Learned predictions take precedence when supplied; otherwise the named exact
    feature drives this rule. Missing/nonpositive signals reset confirmation and
    request flat. This engineering workload expresses no profitability claim.
    """

    def __init__(self, *, field: NumericField, quantity: Quantity, confirmations: int) -> None:
        """Bind the named signal, positive target and explicit warm-up length."""
        quantity.model_copy()
        field.__post_init__()
        if (
            type(field) is not NumericField
            or quantity.value <= 0
            or type(confirmations) is not int
            or confirmations < 1
        ):
            raise ValueError("invalid confirmed signal parameters")
        self._field, self._quantity, self._confirmations = field, quantity, confirmations
        self._codec = DomainCodec()

    @property
    def identity(self) -> str:
        """Bind formula, named feature, quantity dimensions and confirmation count."""
        return hashlib.sha256(
            self._codec.encode_json(
                ("confirmed-signal-v1", self._field, self._quantity, self._confirmations)
            )
        ).hexdigest()

    @property
    def output(self) -> Literal["target"]:
        """Declare absolute target-position output."""
        return "target"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require the named feature and compatible prediction units when a model is selected."""
        if self._field not in fields or (
            prediction is not None and prediction.units != self._field.units
        ):
            raise ValueError("signal feature or prediction signature mismatch")

    def initial_state(self) -> bytes:
        """Begin with no positive observations."""
        return self._codec.encode_json(_Confirmation(count=0))

    def validate_state(self, state: bytes) -> None:
        """Reject invalid or foreign confirmation counts."""
        count = self._codec.decode_json(state, _Confirmation).count
        if count > self._confirmations:
            raise ValueError("confirmation state exceeds policy bound")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Advance confirmation using only the delivered signal and prior state."""
        context.__post_init__()
        self.validate_state(state)
        count = self._codec.decode_json(state, _Confirmation).count
        names = tuple(f.name for f in context.features.fields)
        if self._field.name not in names:
            raise ValueError("required decision feature is absent")
        value = (
            context.prediction.value
            if context.prediction is not None
            else context.features.values[names.index(self._field.name)]
        )
        positive = value is not None and Fraction(int(value.numerator), int(value.denominator)) > 0
        count = min(count + 1, self._confirmations) if positive else 0
        quantity = (
            self._quantity
            if count == self._confirmations
            else Quantity(value=Decimal(0), dimension=self._quantity.dimension)
        )
        return DecisionTransition(
            intent=TargetIntent(quantity=quantity),
            state=self._codec.encode_json(_Confirmation(count=count)),
        )


class _Confirmation(WireRecord, frozen=True):
    """Retain bounded per-instance signal confirmation state."""

    count: int

    def __post_init__(self) -> None:
        """Reject negative and noninteger counts."""
        if type(self.count) is not int or self.count < 0:
            raise ValueError("invalid confirmation count")
