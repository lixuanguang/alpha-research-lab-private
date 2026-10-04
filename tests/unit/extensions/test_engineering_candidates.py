"""Verify the engineering extension's exact smoothing, target decisions and factories."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

# third party library imports
import pytest
from engineering_candidates import (
    CenterScale,
    ComponentProvider,
    ImbalanceTarget,
    LeastSquares,
    PredictionTarget,
    SmoothedImbalance,
    TouchQuote,
)

# project library imports
from financial_units import ExactRatio
from research.features import FeatureSchema, FeatureVector
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField
from serialization import DomainCodec
from strategies import DecisionContext, QuoteIntent, TargetIntent

_AT = datetime(2026, 1, 1, tzinfo=UTC)
_INSTRUMENT = "4476df8e-6342-4417-839e-e41b88f41446"


class TestEngineeringCandidates:
    """Exercise the extension's components exactly as a candidate step uses them."""

    requirement = InputRequirement(
        name="book",
        family="book",
        clock="receipt",
        field=NumericField(name="imbalance", units="dimensionless"),
        max_age_us=30_000_000,
    )

    @classmethod
    def _schema(cls, weight: str = "1/2") -> FeatureSchema:
        """Declare the smoothing definition with an exact weight."""
        return FeatureSchema(
            implementation="smoothed-imbalance",
            inputs=(cls.requirement,),
            outputs=(NumericField(name="smoothed_imbalance", units="dimensionless"),),
            parameters=(("weight", weight),),
            mode="incremental",
            ttl_us=30_000_000,
        )

    @classmethod
    def _inputs(cls, seconds: int, value: Fraction | None) -> DecisionInputs:
        """Supply one book imbalance, or an explicitly missing one."""
        at = _AT + timedelta(seconds=seconds)
        return DecisionInputs(
            entity=_INSTRUMENT,
            decision_at=at,
            observations=(
                NamedObservation(
                    input=cls.requirement,
                    entity=_INSTRUMENT,
                    event_at=at,
                    available_at=at,
                    value=None if value is None else ExactRatio.from_fraction(value),
                    reason="authored" if value is not None else "stale_input",
                    lineage="authored-book",
                ),
            ),
        )

    def test_smoothing_is_exact_and_a_missing_input_keeps_state(self) -> None:
        """Each step moves halfway to the new value; a gap neither advances nor resets it."""
        feature = SmoothedImbalance(self._schema())
        state = feature.initial_state()
        values: list[ExactRatio | None] = []
        for seconds, value in ((0, Fraction(1)), (3, Fraction(0)), (6, None), (9, Fraction(1))):
            transition = feature.step(self._inputs(seconds, value), state)
            values.append(transition.values[0])
            state = transition.state
        assert values == [
            ExactRatio.from_fraction(Fraction(1)),
            ExactRatio.from_fraction(Fraction(1, 2)),
            None,
            ExactRatio.from_fraction(Fraction(3, 4)),
        ]
        with pytest.raises(ValueError, match="weight"):
            SmoothedImbalance(self._schema("3/2"))
        with pytest.raises(ValueError, match="schema"):
            SmoothedImbalance.create(self._schema(), b'{"weight":"1/2"}')

    @classmethod
    def _vector(cls, value: Fraction) -> FeatureVector:
        """Build one smoothed feature vector at a fixed instant."""
        return FeatureVector(
            entity=_INSTRUMENT,
            decision_at=_AT,
            event_at=_AT,
            information_start=_AT,
            available_at=_AT,
            expires_at=_AT + timedelta(seconds=30),
            definition=cls._schema().identity,
            fields=cls._schema().outputs,
            values=(ExactRatio.from_fraction(value),),
            reasons=("authored",),
            input_identity="authored-book",
        )

    def test_target_follows_the_threshold_and_identity_pins_parameters(self) -> None:
        """Above the threshold the policy targets its quantity; at or below it, flat."""
        codec = DomainCodec()
        parameters = codec.encode_json(
            {
                "instrument": _INSTRUMENT,
                "quantity": "1",
                "threshold": {"numerator": "1", "denominator": "10"},
            }
        )
        policy = ImbalanceTarget.create(parameters)
        field = NumericField(name="smoothed_imbalance", units="dimensionless")
        policy.admit((field,), None)
        quantities: list[Decimal] = []
        for value in (Fraction(1, 5), Fraction(1, 10)):
            context = DecisionContext(features=self._vector(value), prediction=None)
            intent = policy.decide(context, b"").intent
            assert isinstance(intent, TargetIntent)
            quantities.append(intent.quantity.value)
        assert quantities == [Decimal(1), Decimal(0)]
        other = ImbalanceTarget.create(parameters.replace(b'"quantity":"1"', b'"quantity":"2"'))
        assert other.identity != policy.identity
        factories = ComponentProvider().factories()
        assert set(factories.features) == {"smoothed-imbalance", "projection"}
        assert set(factories.policies) == {"imbalance-target", "touch-quote", "prediction-target"}
        assert set(factories.transforms) == {"center-scale"}
        assert set(factories.estimators) == {"least-squares"}
        assert set(factories.metrics) == {"fold-net"}
        assert set(factories.charts) == {"fold-net-path"}

    @staticmethod
    def _row(*values: Fraction | None, names: tuple[str, ...] = ("x",)) -> FeatureVector:
        """Build one vector with the given values under dimensionless fields."""
        fields = tuple(NumericField(name=name, units="dimensionless") for name in names)
        return FeatureVector(
            entity=_INSTRUMENT,
            decision_at=_AT,
            event_at=_AT,
            information_start=_AT,
            available_at=_AT,
            expires_at=_AT + timedelta(seconds=30),
            definition="authored",
            fields=fields,
            values=tuple(None if v is None else ExactRatio.from_fraction(v) for v in values),
            reasons=tuple("authored" for _ in values),
            input_identity="authored-input",
        )

    def test_center_scale_fits_training_rows_only(self) -> None:
        """Mean and largest deviation come from complete training rows; missing stays missing."""
        transform = CenterScale.create(b"{}")
        state = transform.fit((self._row(Fraction(1)), self._row(Fraction(3)), self._row(None)))
        assert transform.apply(state, self._row(Fraction(4))) == (
            ExactRatio.from_fraction(Fraction(2)),
        )
        assert transform.apply(state, self._row(None)) == (None,)
        with pytest.raises(ValueError, match="complete training row"):
            transform.fit((self._row(None),))

    def test_least_squares_is_exact_and_refuses_a_singular_design(self) -> None:
        """An exact line is recovered; a constant column is refused, not regularized."""
        model = LeastSquares.create(b"{}")
        rows = tuple(self._row(Fraction(x)) for x in (0, 1, 2))
        outcomes = tuple(ExactRatio.from_fraction(Fraction(1 + 2 * x)) for x in (0, 1, 2))
        state = model.fit(rows, outcomes)
        assert model.predict(state, self._row(Fraction(5))) == ExactRatio.from_fraction(
            Fraction(11)
        )
        constant = tuple(self._row(Fraction(1)) for _ in range(3))
        with pytest.raises(ValueError, match="singular"):
            model.fit(constant, outcomes)

    def test_quote_steps_back_and_target_follows_prediction(self) -> None:
        """The quote steps back on the opposed side; a missing touch is refused."""
        quote = TouchQuote.create(
            DomainCodec().encode_json(
                {
                    "instrument": _INSTRUMENT,
                    "quantity": "1",
                    "tick": "0.1",
                    "currency": "USDT",
                    "threshold": {"numerator": "1", "denominator": "5"},
                }
            )
        )
        names = ("depth_imbalance", "bid", "ask")
        row = self._row(Fraction(1, 2), Fraction(100), Fraction(1002, 10), names=names)
        intent = quote.decide(DecisionContext(features=row, prediction=None), b"").intent
        assert isinstance(intent, QuoteIntent)
        assert (intent.bid.limit.value, intent.ask.limit.value) == (Decimal(100), Decimal("100.3"))
        missing = self._row(Fraction(1, 2), None, Fraction(1002, 10), names=names)
        with pytest.raises(ValueError, match="then-known bid and ask"):
            quote.decide(DecisionContext(features=missing, prediction=None), b"")
        target = PredictionTarget.create(
            DomainCodec().encode_json(
                {
                    "instrument": _INSTRUMENT,
                    "quantity": "1",
                    "threshold": {"numerator": "0", "denominator": "1"},
                }
            )
        )
        flat = target.decide(DecisionContext(features=row, prediction=None), b"").intent
        assert isinstance(flat, TargetIntent) and flat.quantity.value == 0
