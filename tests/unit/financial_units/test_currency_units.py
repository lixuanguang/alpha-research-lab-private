"""Protect explicit currency identity, accounting grids and nested validation."""

from __future__ import annotations

# standard library imports
from collections.abc import Mapping
from decimal import Decimal, Inexact, localcontext
from importlib import resources
from uuid import UUID

# third party library imports
import msgspec
import pytest
from pydantic import ValidationError

# project library imports
from alpha_research.financial_units import (
    Currency,
    Dimension,
    FXRate,
    Money,
    Price,
    Quantity,
    QuantityKind,
    Rounding,
    UnitError,
)
from alpha_research.financial_units.models import _FinancialUnitModel
from alpha_research.instrument_identity import InstrumentId


class _CurrencyDefinition(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Decode one authored currency definition for configuration-bound tests."""

    code: str
    minor_unit: str


def _packaged_currency_definitions() -> tuple[_CurrencyDefinition, ...]:
    """Read all currency defaults through the packaged, typed configuration."""
    payload = (
        resources.files("alpha_research.financial_units")
        .joinpath("default_currencies.json")
        .read_bytes()
    )
    return msgspec.json.decode(
        payload,
        type=tuple[_CurrencyDefinition, ...],
        strict=True,
    )


def _unsafe_currency_copy(model: Currency, update: Mapping[str, object]) -> Currency:
    """Apply the inherited unchecked Pydantic copy for boundary testing."""
    return super(_FinancialUnitModel, model).model_copy(update=update)


@pytest.mark.parametrize(
    ("code", "quantum", "value", "ceiling", "floor"),
    [
        ("USD", "0.01", "0.011", "0.02", "0.01"),
        ("JPY", "1", "1.1", "2", "1"),
        ("USDT", "0.00000001", "0.000000011", "0.00000002", "0.00000001"),
        ("GRID", "0.05", "0.076", "0.10", "0.05"),
    ],
)
def test_arbitrary_currency_grids_round_exactly_under_low_decimal_context(
    code: str, quantum: str, value: str, ceiling: str, floor: str
) -> None:
    """Round fiat-like, whole-unit, fine and non-power-of-ten grids independently."""
    currency = Currency(code=code, minor_unit=Decimal(quantum))
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        amount = Money(value=Decimal(value), currency=currency)
        assert amount.rounded(mode=Rounding.CEILING).value == Decimal(ceiling)
        assert amount.rounded(mode=Rounding.FLOOR).value == Decimal(floor)


def test_packaged_currency_defaults_are_resolved_from_authored_configuration() -> None:
    """Resolve every packaged currency without source-level declarations."""
    definitions = _packaged_currency_definitions()
    assert definitions
    resolved = tuple(Currency.from_code(definition.code) for definition in definitions)
    expected = tuple(
        Currency(code=definition.code, minor_unit=Decimal(definition.minor_unit))
        for definition in definitions
    )
    assert resolved == expected
    assert all(not hasattr(Currency, definition.code) for definition in definitions)
    assert len({currency.code for currency in resolved}) == len(definitions)


@pytest.mark.parametrize("code", ["QXX", "UNKNOWN", "usd"])
def test_currency_lookup_rejects_unknown_codes(code: str) -> None:
    """Fail closed when a code is absent from the packaged configuration."""
    with pytest.raises(ValueError):
        Currency.from_code(code)


@pytest.mark.parametrize("code", [None, 123, object()])
def test_currency_lookup_rejects_non_string_codes(code: object) -> None:
    """Reject non-string lookup inputs before configuration resolution."""
    with pytest.raises(TypeError):
        Currency.from_code(code)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise strict currency lookup type rejection; expires=2027-03-01]


def test_currency_arithmetic_rejects_code_and_quantum_mismatches() -> None:
    """Money addition requires both explicit currency fields to match exactly."""
    cent_code = Currency(code="QXX", minor_unit=Decimal("0.01"))
    other_code = Currency(code="QYY", minor_unit=Decimal("0.01"))
    other_quantum = Currency(code="QXX", minor_unit=Decimal("0.05"))
    assert cent_code == Currency(code="QXX", minor_unit=Decimal("0.01"))
    assert cent_code != other_quantum
    assert len({cent_code, other_quantum}) == 2
    left = Money(value=Decimal("1"), currency=cent_code)
    with pytest.raises(UnitError, match="identical types and dimensions"):
        left + Money(value=Decimal("1"), currency=other_code)
    with pytest.raises(UnitError, match="identical types and dimensions"):
        left + Money(value=Decimal("1"), currency=other_quantum)


@pytest.mark.parametrize(
    ("code", "quantum"),
    [
        ("", Decimal("0.01")),
        ("usd", Decimal("0.01")),
        ("US D", Decimal("0.01")),
        ("ÅAA", Decimal("0.01")),
        ("AAAAAAAAAAAAAAAAA", Decimal("0.01")),
        ("QXX", Decimal("0")),
        ("QXX", Decimal("-0.01")),
        ("QXX", Decimal("NaN")),
        ("QXX", Decimal("Infinity")),
        ("QXX", Decimal("1e-19")),
        ("QXX", Decimal("1e18")),
    ],
)
def test_currency_rejects_invalid_code_or_quantum(code: str, quantum: Decimal) -> None:
    """Reject malformed codes and nonpositive, nonfinite or unrepresentable quanta."""
    with pytest.raises((TypeError, ValueError)):
        Currency(code=code, minor_unit=quantum)


@pytest.mark.parametrize("quantum", [0.05, True, "0.05"])
def test_currency_rejects_non_decimal_quantum_types(quantum: object) -> None:
    """Reject float, boolean and string quantum coercion at the constructor boundary."""
    with pytest.raises((TypeError, ValueError)):
        Currency(code="QXX", minor_unit=quantum)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise strict currency quantum types; expires=2027-03-01]


def test_currency_and_nested_financial_values_are_frozen_and_revalidated() -> None:
    """Reject mutation and unsafe currency replacements at every public value boundary."""
    currency = Currency(code="QXX", minor_unit=Decimal("0.05"))
    with pytest.raises(ValidationError):
        setattr(currency, "code", "QYY")

    copied = currency.model_copy()
    assert copied == currency and copied is not currency
    with pytest.raises(UnitError):
        currency.model_copy(update={"minor_unit": Decimal("0")})

    amount = Money(value=Decimal("1"), currency=currency)
    with pytest.raises(UnitError):
        amount.model_copy(update={"currency": object()})

    unsafe_quantum = _unsafe_currency_copy(currency, {"minor_unit": Decimal("0")})

    dimension = Dimension(instrument_id=InstrumentId(UUID(int=1)), kind=QuantityKind.BASE_UNIT)
    with pytest.raises((TypeError, ValueError)):
        Money(value=Decimal("1"), currency=unsafe_quantum)
    with pytest.raises((TypeError, ValueError)):
        Price(value=Decimal("1"), currency=unsafe_quantum, per=dimension)
    with pytest.raises((TypeError, ValueError)):
        FXRate(value=Decimal("1"), base=unsafe_quantum, quote=currency)
    with pytest.raises((TypeError, ValueError)):
        FXRate(value=Decimal("1"), base=currency, quote=unsafe_quantum)


def test_price_amount_and_fx_conversion_preserve_configured_currency() -> None:
    """Carry an arbitrary currency through amount formation and explicit FX rounding."""
    dimension = Dimension(instrument_id=InstrumentId(UUID(int=2)), kind=QuantityKind.BASE_UNIT)
    source = Currency(code="QXX", minor_unit=Decimal("0.05"))
    target = Currency(code="QYY", minor_unit=Decimal("0.1"))
    price = Price(value=Decimal("0.125"), currency=source, per=dimension)
    amount = price.amount(Quantity(value=Decimal("2"), dimension=dimension))
    assert amount == Money(value=Decimal("0.250"), currency=source)

    fx = FXRate(value=Decimal("2.1"), base=source, quote=target)
    converted = fx.convert(amount, target=target, mode=Rounding.CEILING)
    assert converted == Money(value=Decimal("0.6"), currency=target)

    with pytest.raises(UnitError, match="distinct currencies"):
        FXRate(
            value=Decimal("2"),
            base=Currency(code="QXX", minor_unit=Decimal("0.01")),
            quote=Currency(code="QXX", minor_unit=Decimal("0.05")),
        )
