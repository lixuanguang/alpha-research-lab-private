"""Share the exact return of adjacent completed closes, scheduled or through any saved source."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Literal

# project library imports
from financial_units import ExactRatio
from research.features.contracts import FeatureSchema, FeatureTransition
from research.observations import DecisionInputs, Observation
from serialization import DomainCodec, WireRecord


class CompletedReturn(WireRecord, frozen=True):
    """Version the P1 completed-close formula separately from observed-trade windows."""

    cadence_seconds: int
    schema_version: Literal["completed-price-return"] = "completed-price-return"

    def __post_init__(self) -> None:
        """Reject unsupported formula versions and nonpositive cadence."""
        if (
            self.schema_version != "completed-price-return"
            or type(self.cadence_seconds) is not int
            or self.cadence_seconds <= 0
        ):
            raise ValueError("completed return requires its version and positive cadence")

    def evaluate(self, previous: Observation | None, current: Observation) -> ExactRatio | None:
        """Calculate an exact dimensionless return without revising either endpoint.

        Args:
            previous: Frozen preceding close, or None during warm-up.
            current: Newly frozen close with explicit missingness.

        Returns:
            Exact current/previous minus one, or None for missing/nonadjacent endpoints.

        Raises:
            ValueError: Endpoint units differ or a supposedly valid price is nonpositive.
        """
        self.__post_init__()
        current.__post_init__()
        if previous is None:
            return None
        previous.__post_init__()
        if (
            previous.point is None
            or current.point is None
            or current.closed_at - previous.closed_at != timedelta(seconds=self.cadence_seconds)
        ):
            return None
        left, right = previous.point.price, current.point.price
        if left.currency != right.currency or left.per != right.per:
            raise ValueError("completed return endpoint units differ")
        if left.value <= 0 or right.value <= 0:
            raise ValueError("completed return requires positive endpoint prices")
        return ExactRatio.from_fraction(Fraction(right.value) / Fraction(left.value) - 1)


class _CloseState(WireRecord, frozen=True):
    """Retain the previous decision's close, or its explicit absence."""

    closed_at: datetime | None
    close: ExactRatio | None

    def __post_init__(self) -> None:
        """Refuse a close without its decision clock."""
        if self.closed_at is None and self.close is not None:
            raise ValueError("completed return state requires its close clock")
        if self.closed_at is not None:
            self._require_utc(self.closed_at, field_name="closed_at")
        if self.close is not None:
            self.close.__post_init__()


class CompletedReturnFeature:
    """Return each decision's close against the previous decision's, through any saved source.

    The close is the selected input's then-known value at the decision, for example
    the latest captured trade price within the input's ``max_age_us``. A return
    exists only when both closes exist and are exactly one cadence apart; otherwise
    it is missing with its reason. This is the generic-lifecycle counterpart of
    ``ScheduledFeatures``, which reads the original REST trade format only.
    """

    def __init__(self, schema: FeatureSchema) -> None:
        """Require one input, one dimensionless output and an explicit positive cadence."""
        schema.__post_init__()
        cadence = dict(schema.parameters).get("cadence_seconds", "")
        if (
            schema.implementation != "completed-return"
            or schema.mode != "incremental"
            or len(schema.inputs) != 1
            or len(schema.outputs) != 1
            or schema.outputs[0].units != "dimensionless"
            or len(schema.parameters) != 1
            or not cadence.isdigit()
            or int(cadence) <= 0
        ):
            raise ValueError("unsupported completed return definition")
        self._schema, self._codec = schema, DomainCodec()
        self._cadence = timedelta(seconds=int(cadence))

    @property
    def schema(self) -> FeatureSchema:
        """Expose the versioned close input, cadence and output."""
        return self._schema

    def initial_state(self) -> bytes:
        """Start with no previous close."""
        return self._codec.encode_json(_CloseState(closed_at=None, close=None))

    def validate_state(self, state: bytes) -> None:
        """Reject malformed state."""
        self._codec.decode_json(state, _CloseState).__post_init__()

    def step(self, inputs: DecisionInputs, state: bytes) -> FeatureTransition:
        """Freeze this decision's close and return it against an adjacent previous close."""
        prior = self._codec.decode_json(state, _CloseState)
        prior.__post_init__()
        row = inputs.observations[0]
        close = row.value
        if close is not None and Fraction(int(close.numerator), int(close.denominator)) <= 0:
            raise ValueError("completed return requires positive closes")
        value: ExactRatio | None = None
        if close is None:
            reason = f"missing close: {row.reason}"
        elif prior.closed_at is None:
            reason = "no previous close"
        elif inputs.decision_at - prior.closed_at != self._cadence:
            reason = "previous close is not one cadence earlier"
        elif prior.close is None:
            reason = "previous close missing"
        else:
            previous = Fraction(int(prior.close.numerator), int(prior.close.denominator))
            current = Fraction(int(close.numerator), int(close.denominator))
            value, reason = ExactRatio.from_fraction(current / previous - 1), "completed return"
        return FeatureTransition(
            values=(value,),
            reasons=(reason,),
            state=self._codec.encode_json(_CloseState(closed_at=inputs.decision_at, close=close)),
        )
