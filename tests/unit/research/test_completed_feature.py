"""Check completed returns through the generic feature lifecycle against authored closes."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from financial_units import ExactRatio
from research.features import CompletedReturnFeature, FeatureSchema, FeatureSession
from research.observations import DecisionInputs, InputRequirement, NamedObservation, NumericField

_START = datetime(2026, 10, 6, 12, tzinfo=UTC)
_ENTITY = "4476df8e-6342-4417-839e-e41b88f41446"
_PRICE = InputRequirement(
    name="trades",
    family="trade",
    clock="event",
    field=NumericField(name="price", units="USDT/BTC"),
    max_age_us=60_000_000,
)
_SCHEMA = FeatureSchema(
    implementation="completed-return",
    inputs=(_PRICE,),
    outputs=(NumericField(name="completed_return", units="dimensionless"),),
    parameters=(("cadence_seconds", "60"),),
    mode="incremental",
    ttl_us=60_000_000,
)


class TestCompletedReturnFeature:
    """Exact adjacent returns, explicit missingness and restart through checkpoints."""

    @staticmethod
    def _inputs(minute: int, price: str | None) -> DecisionInputs:
        """Author one decision's then-known close, or its explicit absence."""
        at = _START + timedelta(minutes=minute)
        return DecisionInputs(
            entity=_ENTITY,
            decision_at=at,
            observations=(
                NamedObservation(
                    input=_PRICE,
                    entity=_ENTITY,
                    event_at=at - timedelta(seconds=1),
                    available_at=None if price is None else at - timedelta(seconds=1),
                    value=None if price is None else ExactRatio(numerator=price, denominator="1"),
                    reason="authored close" if price is not None else "no trade within max age",
                    lineage=f"authored:{minute}",
                ),
            ),
        )

    def test_exact_returns_and_missing_reasons(self) -> None:
        """A return needs two present closes exactly one cadence apart."""
        session = FeatureSession(CompletedReturnFeature(_SCHEMA), instance="i", entity=_ENTITY)
        rows = tuple(
            session.evaluate(self._inputs(minute, price))
            for minute, price in (
                (0, "100"),
                (1, "101"),
                (2, None),
                (3, "99"),
                (4, "110"),
                (6, "121"),
            )
        )
        assert tuple(row.values[0] for row in rows) == (
            None,
            ExactRatio(numerator="1", denominator="100"),
            None,
            None,
            ExactRatio(numerator="1", denominator="9"),
            None,
        )
        assert tuple(row.reasons[0] for row in rows) == (
            "no previous close",
            "completed return",
            "missing close: no trade within max age",
            "previous close missing",
            "completed return",
            "previous close is not one cadence earlier",
        )

    def test_checkpoint_continues_exactly(self) -> None:
        """A session restored from its checkpoint continues the same returns."""
        kernel = CompletedReturnFeature(_SCHEMA)
        whole = FeatureSession(kernel, instance="i", entity=_ENTITY)
        expected = tuple(
            whole.evaluate(self._inputs(m, p)) for m, p in ((0, "100"), (1, "105"), (2, "84"))
        )
        first = FeatureSession(kernel, instance="i", entity=_ENTITY)
        head = first.evaluate(self._inputs(0, "100"))
        resumed = FeatureSession(
            kernel, instance="i", entity=_ENTITY, checkpoint=first.checkpoint()
        )
        tail = tuple(resumed.evaluate(self._inputs(m, p)) for m, p in ((1, "105"), (2, "84")))
        assert (head, *tail) == expected

    @pytest.mark.parametrize(
        "schema",
        (
            replace(_SCHEMA, mode="batch"),
            replace(_SCHEMA, parameters=()),
            replace(_SCHEMA, parameters=(("cadence_seconds", "0"),)),
            replace(_SCHEMA, outputs=(NumericField(name="completed_return", units="USDT"),)),
            replace(_SCHEMA, implementation="running-mean"),
        ),
    )
    def test_refuses_unsupported_definitions(self, schema: FeatureSchema) -> None:
        """Only the incremental, one-input, dimensionless, explicit-cadence form is admitted."""
        with pytest.raises(ValueError, match="unsupported completed return"):
            CompletedReturnFeature(schema)

    def test_refuses_nonpositive_close(self) -> None:
        """A zero close cannot anchor a return."""
        session = FeatureSession(CompletedReturnFeature(_SCHEMA), instance="i", entity=_ENTITY)
        with pytest.raises(ValueError, match="positive closes"):
            session.evaluate(self._inputs(0, "0"))
