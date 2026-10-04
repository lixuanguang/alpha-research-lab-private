"""Verify the engineering extension's exact smoothing, target decisions and factories."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

# third party library imports
import pytest
from engineering_candidates import ComponentProvider, ImbalanceTarget, SmoothedImbalance

# project library imports
from financial_units import ExactRatio
from research.features import FeatureSchema, FeatureVector
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField
from serialization import DomainCodec
from strategies import DecisionContext, TargetIntent

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
        assert set(factories.features) == {"smoothed-imbalance"}
        assert set(factories.policies) == {"imbalance-target"}
        assert set(factories.metrics) == {"fold-net"}
        assert set(factories.charts) == {"fold-net-path"}
