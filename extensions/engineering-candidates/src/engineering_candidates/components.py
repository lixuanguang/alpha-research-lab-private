"""Define a stateful smoothed book-imbalance feature and an imbalance target policy.

These are engineering workloads that exercise the extension contract. They make
no profitability claim.
"""

from __future__ import annotations

# standard library imports
import hashlib
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING, Literal
from uuid import UUID

# project library imports
from financial_units import Dimension, ExactRatio, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from research.experiments import Fingerprint
from research.features import FeatureSchema, FeatureTransition
from research.observations import DecisionInputs, NumericField
from runtime import ExtensionFactories
from serialization import DomainCodec, WireRecord
from strategies import DecisionContext, DecisionTransition, TargetIntent

# project library imports
from .learning import CenterScale, LeastSquares, NamedProjection, PredictionTarget, TouchQuote

if TYPE_CHECKING:
    # project library imports
    from research.reports import ChartSpec, MetricValue, ReportContext

_SMOOTHED = NumericField(name="smoothed_imbalance", units="dimensionless")


class _Smoothed(WireRecord, frozen=True):
    """Carry the last smoothed value, absent before the first observation."""

    value: ExactRatio | None


class _TargetParameters(WireRecord, frozen=True):
    """Carry the policy's instrument, target quantity and entry threshold."""

    instrument: str
    quantity: Decimal
    threshold: ExactRatio


class SmoothedImbalance:
    """Exponentially smooth one book imbalance input with an exact rational weight.

    An optional second input, a public trade ``signed_flow``, confirms the signal:
    the output is the smoothed imbalance when the flow has the same sign, else zero.
    A missing input yields a missing value and keeps the prior state, so a gap in
    either feed never advances the smoothing.
    """

    def __init__(self, schema: FeatureSchema) -> None:
        """Require the declared smoothing definition, its inputs and a weight."""
        schema.__post_init__()
        parameters = dict(schema.parameters)
        if (
            schema.implementation != "smoothed-imbalance"
            or schema.mode != "incremental"
            or len(schema.inputs) not in (1, 2)
            or schema.inputs[0].field != NumericField(name="imbalance", units="dimensionless")
            or (
                len(schema.inputs) == 2
                and (
                    schema.inputs[1].family != "trade"
                    or schema.inputs[1].field.name != "signed_flow"
                )
            )
            or schema.outputs != (_SMOOTHED,)
            or set(parameters) != {"weight"}
        ):
            raise ValueError("unsupported smoothed imbalance definition")
        self._weight = Fraction(parameters["weight"])
        if not 0 < self._weight <= 1:
            raise ValueError("smoothing weight must lie in (0, 1]")
        self._schema, self._codec = schema, DomainCodec()

    @classmethod
    def create(cls, schema: FeatureSchema, parameters: bytes) -> SmoothedImbalance:
        """Construct the feature for its packaged schema; it takes no extra parameters."""
        if parameters != b"{}":
            raise ValueError("smoothed imbalance takes its parameters from its schema")
        return cls(schema)

    @property
    def schema(self) -> FeatureSchema:
        """Expose the exact smoothing definition."""
        return self._schema

    def initial_state(self) -> bytes:
        """Start with no smoothed value."""
        return self._codec.encode_json(_Smoothed(value=None))

    def validate_state(self, state: bytes) -> None:
        """Reject a foreign or malformed smoothing state."""
        self._codec.decode_json(state, _Smoothed)

    def step(self, inputs: DecisionInputs, state: bytes) -> FeatureTransition:
        """Advance the smoothed value from the then-known imbalance."""
        prior = self._codec.decode_json(state, _Smoothed)
        observation = inputs.observations[0]
        missing = next((row for row in inputs.observations if row.value is None), None)
        if observation.value is None or missing is not None:
            reason = observation.reason if missing is None else missing.reason
            return FeatureTransition(values=(None,), reasons=(reason,), state=state)
        current = Fraction(int(observation.value.numerator), int(observation.value.denominator))
        if prior.value is None:
            smoothed = current
        else:
            previous = Fraction(int(prior.value.numerator), int(prior.value.denominator))
            smoothed = previous + self._weight * (current - previous)
        value = ExactRatio.from_fraction(smoothed)
        output = value
        if len(inputs.observations) == 2:
            flow = inputs.observations[1].value
            if flow is None or Fraction(int(flow.numerator), int(flow.denominator)) * smoothed <= 0:
                output = ExactRatio.from_fraction(Fraction(0))
        return FeatureTransition(
            values=(output,),
            reasons=(observation.reason,),
            state=self._codec.encode_json(_Smoothed(value=value)),
        )


class ImbalanceTarget:
    """Hold a fixed long target while the smoothed imbalance exceeds a threshold, else flat."""

    def __init__(self, parameters: _TargetParameters) -> None:
        """Bind the exact instrument, target quantity and threshold."""
        if parameters.quantity <= 0:
            raise ValueError("imbalance target requires a positive quantity")
        dimension = Dimension(
            instrument_id=InstrumentId(UUID(parameters.instrument)), kind=QuantityKind.BASE_UNIT
        )
        self._quantity = Quantity(value=parameters.quantity, dimension=dimension)
        self._flat = Quantity(value=Decimal(0), dimension=dimension)
        self._threshold = Fraction(
            int(parameters.threshold.numerator), int(parameters.threshold.denominator)
        )
        self._codec = DomainCodec()
        self._parameters = parameters

    @classmethod
    def create(cls, parameters: bytes) -> ImbalanceTarget:
        """Construct the policy from its canonical JSON parameters."""
        return cls(DomainCodec().decode_json(parameters, _TargetParameters))

    @property
    def identity(self) -> str:
        """Bind the formula and every exact parameter."""
        return hashlib.sha256(
            self._codec.encode_json(("imbalance-target", self._parameters))
        ).hexdigest()

    @property
    def output(self) -> Literal["target"]:
        """Declare absolute target-position output."""
        return "target"

    def admit(self, fields: tuple[NumericField, ...], prediction: NumericField | None) -> None:
        """Require the smoothed imbalance feature and no learned prediction."""
        if fields != (_SMOOTHED,) or prediction is not None:
            raise ValueError("imbalance target requires the smoothed imbalance signature")

    def initial_state(self) -> bytes:
        """Keep no policy state; the feature carries the history."""
        return b""

    def validate_state(self, state: bytes) -> None:
        """Reject any policy state."""
        if state != b"":
            raise ValueError("imbalance target is stateless")

    def decide(self, context: DecisionContext, state: bytes) -> DecisionTransition:
        """Target the fixed quantity above the threshold, flat otherwise or when missing."""
        context.__post_init__()
        self.validate_state(state)
        value = context.features.values[0]
        above = value is not None and (
            Fraction(int(value.numerator), int(value.denominator)) > self._threshold
        )
        return DecisionTransition(
            intent=TargetIntent(quantity=self._quantity if above else self._flat), state=b""
        )


class FoldNetMetric:
    """Sum terminal net value across folds that share one quote currency.

    Study records load only when a research report evaluates the metric, so an
    operating service can construct it without the research reporting stack.
    """

    identity = Fingerprint(
        name="fold-net",
        sha256=hashlib.sha256(b"engineering_candidates.FoldNetMetric/1").hexdigest(),
    )

    @classmethod
    def create(cls, parameters: bytes) -> FoldNetMetric:
        """Construct the parameter-free metric."""
        if parameters != b"{}":
            raise ValueError("fold net metric takes no parameters")
        return cls()

    def evaluate(self, context: ReportContext) -> MetricValue:
        """Keep each fold's terminal net value and withhold a total across currencies."""
        # project library imports
        from research.reports import MetricValue, ReportObservation

        observations: list[ReportObservation] = []
        total = Fraction(0)
        currencies: set[str] = set()
        unvalued: str | None = None
        for fold in context.folds:
            currencies.add(fold.ledger.initial_cash.currency.code)
            if fold.terminal_mark is None:
                unvalued = fold.terminal_missing_reason
            else:
                total += Fraction(fold.terminal_mark.net.value)
            observations.append(
                ReportObservation(
                    fold_id=fold.fold_id,
                    name="fold-net",
                    at=fold.window.end,
                    units=fold.ledger.initial_cash.currency.code,
                    value=None
                    if fold.terminal_mark is None
                    else ExactRatio.from_fraction(Fraction(fold.terminal_mark.net.value)),
                    missing_reason=fold.terminal_missing_reason,
                )
            )
        single = len(currencies) == 1
        reason = "fold quote currencies differ" if not single else unvalued
        return MetricValue(
            definition=self.identity,
            name="Fold net value",
            version="1",
            units=currencies.pop() if single else "mixed",
            value=ExactRatio.from_fraction(total) if reason is None else None,
            missing_reason=reason,
            observations=tuple(observations),
        )


class FoldNetChart:
    """Chart each fold's terminal net value in its own currency."""

    identity = Fingerprint(
        name="fold-net-path",
        sha256=hashlib.sha256(b"engineering_candidates.FoldNetChart/1").hexdigest(),
    )

    @classmethod
    def create(cls, parameters: bytes) -> FoldNetChart:
        """Construct the parameter-free chart."""
        if parameters != b"{}":
            raise ValueError("fold net chart takes no parameters")
        return cls()

    def evaluate(self, context: ReportContext) -> ChartSpec:
        """Return one exact observation per fold."""
        # project library imports
        from research.reports import ChartSpec, ReportObservation

        observations = tuple(
            ReportObservation(
                fold_id=fold.fold_id,
                name=f"fold-net ({fold.ledger.initial_cash.currency.code})",
                at=fold.window.end,
                units=fold.ledger.initial_cash.currency.code,
                value=None
                if fold.terminal_mark is None
                else ExactRatio.from_fraction(Fraction(fold.terminal_mark.net.value)),
                missing_reason=fold.terminal_missing_reason,
            )
            for fold in context.folds
        )
        return ChartSpec(
            definition=self.identity,
            title="Fold net value",
            kind="line",
            data_references=tuple(sorted({item.name for item in observations})),
            observations=observations,
        )


class ComponentProvider:
    """Register this extension's components under the candidate component contract."""

    def factories(self) -> ExtensionFactories:
        """Return the feature and policy constructors by registered key."""
        return ExtensionFactories(
            features={
                "smoothed-imbalance": SmoothedImbalance.create,
                "projection": NamedProjection.create,
            },
            policies={
                "imbalance-target": ImbalanceTarget.create,
                "touch-quote": TouchQuote.create,
                "prediction-target": PredictionTarget.create,
            },
            transforms={"center-scale": CenterScale.create},
            estimators={"least-squares": LeastSquares.create},
            metrics={"fold-net": FoldNetMetric.create},
            charts={"fold-net-path": FoldNetChart.create},
        )
