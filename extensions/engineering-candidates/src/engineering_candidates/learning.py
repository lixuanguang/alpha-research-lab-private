"""Define a fitted transform, an exact estimator, a forward label and two more policies.

With ``components.py`` these give one maintained example of every component role a
study or candidate can select. They are engineering workloads with no
profitability claim.
"""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal
from uuid import UUID

# project library imports
from financial_units import (
    Currency,
    DecimalGrid,
    Dimension,
    ExactRatio,
    Price,
    Quantity,
    QuantityKind,
)
from reference_data.instruments import InstrumentId
from research.features import FeatureSchema, FeatureVector, ProjectionFeature
from research.labels import Outcome
from research.observations import DecisionSource, NumericField
from serialization import DomainCodec, WireRecord
from strategies import DecisionContext, DecisionTransition, OrderIntent, QuoteIntent, TargetIntent


class _Exact:
    """Convert between exact ratios and fractions."""

    @staticmethod
    def fraction(value: ExactRatio) -> Fraction:
        """Return the exact fraction of a ratio."""
        return Fraction(int(value.numerator), int(value.denominator))


class NamedProjection:
    """Register the platform's named projection, so a study's projected inputs can be packaged.

    The schema's ``named-projection`` implementation passes each input through
    unchanged; its identity is the schema's, as a study records it.
    """

    @staticmethod
    def create(schema: FeatureSchema, parameters: bytes) -> ProjectionFeature:
        """Construct the projection for its packaged schema; it takes no parameters."""
        if parameters != b"{}":
            raise ValueError("named projection takes its definition from its schema")
        return ProjectionFeature(schema)


class _CenterScaleState(WireRecord, frozen=True):
    """Carry each column's training mean and largest absolute deviation."""

    means: tuple[ExactRatio, ...]
    scales: tuple[ExactRatio, ...]


class CenterScale:
    """Center each column on its training mean and divide by its largest deviation.

    Fitting sees only the admitted training rows; every value stays exact. A column
    with no deviation keeps scale one. Outputs are dimensionless and keep the input
    column names. A missing input stays missing.
    """

    identity = "engineering-candidates.center-scale/1"

    @classmethod
    def create(cls, parameters: bytes) -> CenterScale:
        """Construct the parameter-free transform."""
        if parameters != b"{}":
            raise ValueError("center-scale takes no parameters")
        return cls()

    def fit(self, rows: tuple[FeatureVector, ...]) -> bytes:
        """Fit means and deviations from complete training rows only."""
        complete = [
            [_Exact.fraction(value) for value in row.values if value is not None]
            for row in rows
            if all(value is not None for value in row.values)
        ]
        if not complete:
            raise ValueError("center-scale needs at least one complete training row")
        width = len(complete[0])
        means = [
            sum((row[i] for row in complete), Fraction()) / len(complete) for i in range(width)
        ]
        scales = [
            max((abs(row[i] - means[i]) for row in complete), default=Fraction(0)) or Fraction(1)
            for i in range(width)
        ]
        return DomainCodec().encode_json(
            _CenterScaleState(
                means=tuple(ExactRatio.from_fraction(value) for value in means),
                scales=tuple(ExactRatio.from_fraction(value) for value in scales),
            )
        )

    def output_fields(
        self, state: bytes, fields: tuple[NumericField, ...]
    ) -> tuple[NumericField, ...]:
        """Keep each column's name; scaled values are dimensionless."""
        saved = DomainCodec().decode_json(state, _CenterScaleState)
        if len(saved.means) != len(fields):
            raise ValueError("center-scale state differs from the feature signature")
        return tuple(NumericField(name=field.name, units="dimensionless") for field in fields)

    def apply(self, state: bytes, row: FeatureVector) -> tuple[ExactRatio | None, ...]:
        """Scale each present value with the fitted state."""
        saved = DomainCodec().decode_json(state, _CenterScaleState)
        return tuple(
            None
            if value is None
            else ExactRatio.from_fraction(
                (_Exact.fraction(value) - _Exact.fraction(mean)) / _Exact.fraction(scale)
            )
            for value, mean, scale in zip(row.values, saved.means, saved.scales, strict=True)
        )


class _LeastSquaresState(WireRecord, frozen=True):
    """Carry the intercept and one coefficient per feature column."""

    coefficients: tuple[ExactRatio, ...]


class LeastSquares:
    """Fit an intercept and linear coefficients by exact ordinary least squares.

    The normal equations are solved by exact Gaussian elimination. A singular
    design (for example, a constant column) is refused rather than regularized.
    """

    identity = "engineering-candidates.least-squares/1"

    @classmethod
    def create(cls, parameters: bytes) -> LeastSquares:
        """Construct the parameter-free estimator."""
        if parameters != b"{}":
            raise ValueError("least squares takes no parameters")
        return cls()

    def fit(self, rows: tuple[FeatureVector, ...], outcomes: tuple[ExactRatio, ...]) -> bytes:
        """Solve ``(X'X) b = X'y`` exactly over the admitted training sample."""
        if len(rows) != len(outcomes) or not rows:
            raise ValueError("least squares needs aligned, nonempty training rows")
        design = [[Fraction(1), *self._values(row)] for row in rows]
        target = [_Exact.fraction(value) for value in outcomes]
        width = len(design[0])
        matrix = [
            [sum((x[i] * x[j] for x in design), Fraction()) for j in range(width)]
            + [sum((x[i] * y for x, y in zip(design, target, strict=True)), Fraction())]
            for i in range(width)
        ]
        for column in range(width):
            pivot = next((row for row in range(column, width) if matrix[row][column] != 0), None)
            if pivot is None:
                raise ValueError("least squares design is singular")
            matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
            lead = matrix[column][column]
            matrix[column] = [value / lead for value in matrix[column]]
            for row in range(width):
                if row != column and matrix[row][column] != 0:
                    factor = matrix[row][column]
                    matrix[row] = [
                        value - factor * base
                        for value, base in zip(matrix[row], matrix[column], strict=True)
                    ]
        return DomainCodec().encode_json(
            _LeastSquaresState(
                coefficients=tuple(ExactRatio.from_fraction(matrix[i][width]) for i in range(width))
            )
        )

    def predict(self, state: bytes, row: FeatureVector) -> ExactRatio:
        """Return the intercept plus the weighted feature values."""
        coefficients = [
            _Exact.fraction(value)
            for value in DomainCodec().decode_json(state, _LeastSquaresState).coefficients
        ]
        values = self._values(row)
        if len(values) + 1 != len(coefficients):
            raise ValueError("least squares state differs from the feature signature")
        return ExactRatio.from_fraction(
            coefficients[0]
            + sum((b * x for b, x in zip(coefficients[1:], values, strict=True)), Fraction())
        )

    @staticmethod
    def _values(row: FeatureVector) -> list[Fraction]:
        """Require every feature value; missing rows are excluded before fitting."""
        if any(value is None for value in row.values):
            raise ValueError("least squares requires complete feature rows")
        return [_Exact.fraction(value) for value in row.values if value is not None]


class ForwardMidReturn:
    """Label each decision with the touch mid return over a fixed horizon.

    The label reads ``bid`` and ``ask`` book fields from its own decision source at
    the decision and at ``decision + horizon``. It is available when the later touch
    is; before that, or when either touch is missing, it is pending or missing with
    the source's reason. It never enters the decision's feature vector.
    """

    field = NumericField(name="forward_mid_return", units="dimensionless")

    def __init__(self, source: DecisionSource, horizon: timedelta) -> None:
        """Bind the touch source and a positive horizon."""
        names = tuple(item.field.name for item in source.requirements)
        if names != ("bid", "ask") or horizon <= timedelta(0):
            raise ValueError("forward mid return needs a bid/ask source and a positive horizon")
        self._source, self._horizon = source, horizon

    @property
    def identity(self) -> str:
        """Pin the formula, the touch source and the horizon."""
        return hashlib.sha256(
            DomainCodec().encode_json(
                ("forward-mid-return/1", self._source.identity, self._horizon.total_seconds())
            )
        ).hexdigest()

    def read(self, row: FeatureVector, *, as_of: datetime) -> Outcome:
        """Return the realized return known by ``as_of``, or a pending/missing outcome."""
        end = row.decision_at + self._horizon
        base = self._mid(row.entity, row.decision_at)
        if as_of < end:
            return self._outcome(row, end, None, None, "pending_horizon", (row.identity,))
        future = self._mid(row.entity, end)
        if base[0] is None or future[0] is None:
            return self._outcome(row, end, None, None, base[2] or future[2], (row.identity,))
        # The later touch is a fact about the book at ``end``; it is known no earlier.
        available = None if future[1] is None else max(future[1], end)
        if available is None or available > as_of:
            return self._outcome(row, end, None, None, "pending_availability", (row.identity,))
        return self._outcome(
            row,
            end,
            available,
            ExactRatio.from_fraction(future[0] / base[0] - 1),
            "observed_touch_mid",
            (base[2], future[2]),
        )

    def _mid(self, entity: str, at: datetime) -> tuple[Fraction | None, datetime | None, str]:
        """Return the touch mid, its availability and its lineage or missing reason."""
        bid, ask = self._source.read(entity, at).observations
        if bid.value is None or ask.value is None:
            return None, None, bid.reason if bid.value is None else ask.reason
        available = max(
            (item for item in (bid.available_at, ask.available_at) if item is not None),
            default=None,
        )
        return (
            (_Exact.fraction(bid.value) + _Exact.fraction(ask.value)) / 2,
            available,
            f"{bid.lineage}|{ask.lineage}",
        )

    def _outcome(
        self,
        row: FeatureVector,
        end: datetime,
        available: datetime | None,
        value: ExactRatio | None,
        reason: str,
        lineage: tuple[str, ...],
    ) -> Outcome:
        """Build one outcome record for the decision row."""
        return Outcome(
            feature_identity=row.identity,
            definition=self.identity,
            field=self.field,
            information_start=row.decision_at,
            information_end=end,
            available_at=available,
            value=value,
            reason=reason,
            lineage=lineage,
        )


class _QuoteParameters(WireRecord, frozen=True):
    """Carry the quote instrument, size, price tick, currency and skew threshold."""

    instrument: str
    quantity: Decimal
    tick: Decimal
    currency: str
    threshold: ExactRatio


class TouchQuote:
    """Rule-only two-sided quote at the touch, stepped back on the side the imbalance opposes.

    The features are, in order, ``depth_imbalance``, ``bid`` and ``ask``. With the
    imbalance above the threshold the ask steps back one tick; below its negative,
    the bid does. The quote rests post-only. Without a then-known bid and ask it
    abstains: inventing a price is worse, and abstaining withdraws its resting quote.
    """

    def __init__(self, parameters: _QuoteParameters) -> None:
        """Bind exact parameters."""
        if parameters.quantity <= 0 or parameters.tick <= 0:
            raise ValueError("touch quote requires positive size and tick")
        self._parameters = parameters
        self._dimension = Dimension(
            instrument_id=InstrumentId(UUID(parameters.instrument)), kind=QuantityKind.BASE_UNIT
        )
        self._currency = Currency.from_code(parameters.currency)
        self._threshold = _Exact.fraction(parameters.threshold)

    @classmethod
    def create(cls, parameters: bytes) -> TouchQuote:
        """Construct the policy from its canonical JSON parameters."""
        return cls(DomainCodec().decode_json(parameters, _QuoteParameters))

    @property
    def identity(self) -> str:
        """Bind the rule and every exact parameter."""
        return hashlib.sha256(
            DomainCodec().encode_json(("touch-quote/2", self._parameters))
        ).hexdigest()

    @property
    def output(self) -> Literal["quote"]:
        """Declare two-sided quote output."""
        return "quote"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require imbalance, bid and ask features and no learned prediction."""
        if (
            tuple(field.name for field in fields)[:3]
            != (
                "depth_imbalance",
                "bid",
                "ask",
            )
            or prediction is not None
        ):
            raise ValueError("touch quote requires depth_imbalance, bid and ask features")

    def initial_state(self) -> bytes:
        """Keep no state."""
        return b""

    def validate_state(self, state: bytes) -> None:
        """Refuse any state."""
        if state != b"":
            raise ValueError("touch quote is stateless")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Quote at the then-known touch, stepping back on the opposed side."""
        self.validate_state(state)
        imbalance, bid, ask = context.features.values[:3]
        if bid is None or ask is None:
            return DecisionTransition(intent=None, state=b"")
        tick = Fraction(self._parameters.tick)
        signal = Fraction(0) if imbalance is None else _Exact.fraction(imbalance)
        bid_price = _Exact.fraction(bid) - (tick if signal < -self._threshold else 0)
        ask_price = _Exact.fraction(ask) + (tick if signal > self._threshold else 0)
        quantity = Quantity(value=self._parameters.quantity, dimension=self._dimension)
        return DecisionTransition(
            intent=QuoteIntent(
                bid=self._order("buy", quantity, bid_price),
                ask=self._order("sell", quantity, ask_price),
            ),
            state=b"",
        )

    def _order(
        self, side: Literal["buy", "sell"], quantity: Quantity, price: Fraction
    ) -> OrderIntent:
        """Build one resting order at an exact price."""
        return OrderIntent(
            side=side,
            quantity=quantity,
            limit=Price(
                value=DecimalGrid.exact_decimal(price), currency=self._currency, per=self._dimension
            ),
            time_in_force="post-only",
        )


class _PredictionParameters(WireRecord, frozen=True):
    """Carry the target instrument, size and prediction threshold."""

    instrument: str
    quantity: Decimal
    threshold: ExactRatio


class PredictionTarget:
    """Learned long/flat target: hold the size while the prediction exceeds the threshold."""

    def __init__(self, parameters: _PredictionParameters) -> None:
        """Bind exact parameters."""
        if parameters.quantity <= 0:
            raise ValueError("prediction target requires a positive size")
        dimension = Dimension(
            instrument_id=InstrumentId(UUID(parameters.instrument)), kind=QuantityKind.BASE_UNIT
        )
        self._parameters = parameters
        self._long = Quantity(value=parameters.quantity, dimension=dimension)
        self._flat = Quantity(value=Decimal(0), dimension=dimension)
        self._threshold = _Exact.fraction(parameters.threshold)

    @classmethod
    def create(cls, parameters: bytes) -> PredictionTarget:
        """Construct the policy from its canonical JSON parameters."""
        return cls(DomainCodec().decode_json(parameters, _PredictionParameters))

    @property
    def identity(self) -> str:
        """Bind the rule and every exact parameter."""
        return hashlib.sha256(
            DomainCodec().encode_json(("prediction-target/1", self._parameters))
        ).hexdigest()

    @property
    def output(self) -> Literal["target"]:
        """Declare absolute target output."""
        return "target"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require a dimensionless learned prediction."""
        if prediction is None or prediction.units != "dimensionless":
            raise ValueError("prediction target requires a dimensionless prediction")

    def initial_state(self) -> bytes:
        """Keep no state."""
        return b""

    def validate_state(self, state: bytes) -> None:
        """Refuse any state."""
        if state != b"":
            raise ValueError("prediction target is stateless")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Target the size above the threshold; flat otherwise or without a prediction."""
        self.validate_state(state)
        forecast = context.prediction
        above = forecast is not None and _Exact.fraction(forecast.value) > self._threshold
        return DecisionTransition(
            intent=TargetIntent(quantity=self._long if above else self._flat), state=b""
        )
