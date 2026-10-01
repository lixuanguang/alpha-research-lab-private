"""Strict financial model construction, copies and validation contracts."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable, Mapping
from datetime import date, datetime
from uuid import UUID

# third party library imports
import pytest
from financial_unit_cases import CONTEXT, CONVENTION, SHARES, D, FinancialUnitCases
from pydantic import ValidationError

# project library imports
from financial_units import (
    Compounding,
    ConventionError,
    Currency,
    DayCount,
    DayCountResult,
    Dimension,
    Duration,
    EvaluationContext,
    FXRate,
    Lot,
    Money,
    Multiplier,
    Price,
    Quantity,
    QuantityKind,
    Rate,
    RateConvention,
    SettlementConventions,
    Tick,
    UnitError,
    Volatility,
    Yield,
)
from financial_units.models import _FinancialUnitModel
from reference_data.instruments import InstrumentId


class TestFinancialModelContracts:
    """Exercise strict model construction, immutable copies and boundary rejection."""

    @staticmethod
    def _unchecked_dimension_copy(model: Dimension, update: Mapping[str, object]) -> Dimension:
        """Apply the inherited unchecked copy primitive to a deliberately invalid dimension.

        Args:
            model: Valid dimension whose identity is retained in the raw copy.
            update: Deliberately invalid field replacement passed to Pydantic.

        Returns:
            A dimension carrying the unchecked replacement for boundary testing.
        """
        return super(_FinancialUnitModel, model).model_copy(update=update)

    def test_c01_c02_unvalidated_copies_cannot_bypass_boundary_validation(self) -> None:
        """Reject unchecked identity and calendar replacements at financial boundaries."""
        identity_update: Mapping[str, object] = {"uuid_value": UUID(int=0)}
        invalid_id = InstrumentId(UUID(int=1)).model_copy(update=identity_update)
        with pytest.raises(UnitError, match="non-nil"):
            Dimension(instrument_id=invalid_id, kind=QuantityKind.SHARE)
        calendar_update: Mapping[str, object] = {
            "settlement_dates": (date(2024, 9, 3), date(2024, 8, 30))
        }
        invalid_calendar = FinancialUnitCases.calendar().model_copy(update=calendar_update)
        with pytest.raises(ConventionError, match="invalid settlement"):
            SettlementConventions(invalid_calendar)

    def test_all_numeric_types_are_immutable_and_distinct(self) -> None:
        """Preserve frozen values and reject arithmetic across distinct quote types."""
        rate = Rate(value=D("-0.02"), convention=CONVENTION)
        yield_quote = Yield(value=D("-0.02"), convention=CONVENTION)
        assert rate != yield_quote
        with pytest.raises(UnitError, match="types and dimensions"):
            rate + yield_quote
        with pytest.raises(ValidationError, match="frozen"):
            setattr(rate, "value", D("3"))
        with pytest.raises(UnitError):
            Volatility(value=D("-0.01"), day_count=DayCount.ACTUAL_365_FIXED)
        with pytest.raises(UnitError):
            Duration(value=D("-1"), day_count=DayCount.ACTUAL_360)
        assert (rate + rate).value == D("-0.04")
        vol = Volatility(value=D("0.2"), day_count=DayCount.ACTUAL_365_FIXED)
        assert (vol + vol).value == D("0.4")

    @pytest.mark.parametrize(
        "model",
        [
            SHARES,
            Money(value=D("1.25"), currency=Currency.from_code("USD")),
            DayCountResult(
                context=CONTEXT,
                start=date(2024, 1, 1),
                end=date(2024, 1, 2),
                duration=Duration(value=D("0.002777777777778"), day_count=DayCount.ACTUAL_360),
            ),
        ],
    )
    def test_representative_models_keep_frozen_hashable_strict_pydantic_semantics(
        self, model: _FinancialUnitModel
    ) -> None:
        """Preserve strict validation, immutability and hashes across public model copies."""
        assert isinstance(model, _FinancialUnitModel)
        payload: dict[str, object] = dict(model)
        assert model.model_validate(payload) == model
        assert model.model_validate(model) == model
        for deep in (False, True):
            copied = model.model_copy(deep=deep)
            assert copied == model and copied is not model
            assert hash(copied) == hash(model)
        field = next(iter(payload))
        field_value: object = getattr(model, field)
        with pytest.raises(ValidationError, match="frozen"):
            setattr(model, field, field_value)
        with pytest.raises(UnitError, match="Extra inputs"):
            unknown_update: Mapping[str, object] = {"unknown_field": "synthetic-sensitive-input"}
            model.model_copy(update=unknown_update)

    @pytest.mark.parametrize("bad", [1.0, D("NaN"), D("1e18"), D("1e-19")])
    def test_invalid_decimal_values_fail_without_coercion(self, bad: object) -> None:
        """Reject malformed decimals through the public Money constructor."""
        with pytest.raises(UnitError):
            Money(value=bad, currency=Currency.from_code("USD"))  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor decimal rejection; expires=2027-03-01]

    @pytest.mark.parametrize(
        "operation",
        [
            lambda: Money(value=D("1"), currency="USD"),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor currency rejection; expires=2027-03-01]
            lambda: Dimension(instrument_id=UUID(int=1), kind=QuantityKind.SHARE),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor identifier rejection; expires=2027-03-01]
            lambda: Dimension(instrument_id=InstrumentId(UUID(int=1)), kind="share"),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor kind rejection; expires=2027-03-01]
            lambda: Quantity(value=D("1"), dimension={}),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor dimension rejection; expires=2027-03-01]
            lambda: Price(value=D("1"), currency=Currency.from_code("USD"), per={}),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor dimension rejection; expires=2027-03-01]
            lambda: RateConvention(day_count="actual_360", compounding=Compounding.SIMPLE),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor day-count rejection; expires=2027-03-01]
            lambda: RateConvention(day_count=DayCount.ACTUAL_360, compounding=Compounding.PERIODIC),
            lambda: RateConvention(
                day_count=DayCount.ACTUAL_360,
                compounding=Compounding.PERIODIC,
                payments_per_year=True,
            ),
            lambda: CONVENTION.model_copy(update={"payments_per_year": 1}),
            lambda: EvaluationContext(
                evaluation_date=datetime(2024, 1, 1), convention_revision="v1"
            ),
            lambda: CONTEXT.model_copy(update={"convention_revision": " "}),
            lambda: FXRate(
                value=D("1"), base=Currency.from_code("USD"), quote=Currency.from_code("USD")
            ),
            lambda: FXRate(
                value=D("0"), base=Currency.from_code("USD"), quote=Currency.from_code("EUR")
            ),
            lambda: Tick(value=D("0"), currency=Currency.from_code("USD"), per=SHARES),
            lambda: Lot(value=D("-1"), dimension=SHARES),
            lambda: Multiplier(value=D("0"), input_dimension=SHARES, output_dimension=SHARES),
        ],
    )
    def test_invalid_units_and_conventions(self, operation: Callable[[], object]) -> None:
        """Require each malformed constructor or replacement to raise the owned error."""
        with pytest.raises(UnitError):
            operation()

    @pytest.mark.parametrize("bad", [D("NaN"), D("1e18"), D("1e-19"), 1.0])
    def test_model_copy_revalidates_decimal_updates_without_mutating_original(
        self, bad: object
    ) -> None:
        """Reject malformed decimal updates and preserve the original Money value."""
        money = Money(value=D("1.25"), currency=Currency.from_code("USD"))
        with pytest.raises(UnitError):
            money.model_copy(update={"value": bad})
        assert money.value == D("1.25")
        assert money.model_copy(update={"value": D("2.50")}).value == D("2.50")

    def test_nested_models_reject_dict_coercion_subclasses_and_unchecked_copies(self) -> None:
        """Revalidate nested dimensions and reject dictionaries, subclasses and hostile copies."""
        dimension_payload: Mapping[str, object] = {
            "value": D("1"),
            "dimension": {"instrument_id": SHARES.instrument_id, "kind": SHARES.kind},
        }
        with pytest.raises(ValidationError, match="dimension"):
            Quantity.model_validate(dimension_payload)

        class DerivedDimension(Dimension):
            """Exercise the unsupported nested-subclass boundary."""

        derived = DerivedDimension(instrument_id=SHARES.instrument_id, kind=SHARES.kind)
        with pytest.raises(UnitError, match="dimension"):
            Quantity(value=D("1"), dimension=derived)
        # Deliberately call the framework's unchecked primitive to represent hostile input.
        nested_update: Mapping[str, object] = {"kind": "share"}
        invalid = self._unchecked_dimension_copy(SHARES, update=nested_update)
        with pytest.raises(UnitError, match="kind"):
            Quantity(value=D("1"), dimension=invalid)
        original = Quantity(value=D("1"), dimension=SHARES)
        with pytest.raises(UnitError, match="kind"):
            original.model_copy(update={"dimension": invalid})

    def test_constructor_errors_preserve_owned_types_and_hide_input_values(self) -> None:
        """Keep constructor error categories and causes without exposing rejected inputs."""
        secret = "synthetic-sensitive-input"
        with pytest.raises(UnitError) as caught:
            Money(value=D("1"), currency=secret)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor error redaction; expires=2027-03-01]
        assert secret not in str(caught.value)
        assert isinstance(caught.value.__cause__, ValidationError)
        assert secret not in str(caught.value.__cause__)
        assert "errors.pydantic.dev" not in str(caught.value)
        structured_payload: Mapping[str, object] = {"value": D("1"), "currency": secret}
        with pytest.raises(ValidationError) as structured:
            Money.model_validate(structured_payload)
        assert secret not in str(structured.value)
        with pytest.raises(ConventionError, match="invalid result interval"):
            DayCountResult(
                context=CONTEXT,
                start=date(2024, 1, 2),
                end=date(2024, 1, 1),
                duration=Duration(value=D("0"), day_count=DayCount.ACTUAL_360),
            )
