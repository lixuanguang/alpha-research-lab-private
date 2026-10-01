"""Exact arithmetic, rounding and currency conversion contracts."""

from __future__ import annotations

# standard library imports
import operator
import os
import sys
from collections.abc import Callable
from decimal import Inexact, localcontext
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from typing import Protocol

# third party library imports
import pytest
from financial_unit_cases import CONTRACTS, SHARES, D, FinancialUnitCases
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

# project library imports
from financial_units import (
    Currency,
    FXRate,
    Lot,
    Money,
    Multiplier,
    Price,
    Quantity,
    Rounding,
    Tick,
    UnitError,
)


class _RoundingGiven(Protocol):
    """Type the three-argument Hypothesis decorator used by rounding tests."""

    def __call__(
        self,
        *,
        raw: SearchStrategy[int],
        step: SearchStrategy[int],
        mode: SearchStrategy[Rounding],
    ) -> Callable[[Callable[[int, int, Rounding], None]], Callable[[], None]]:
        """Decorate a test callable with generated rounding inputs."""
        ...


class _FxConversionGiven(Protocol):
    """Type the two-argument Hypothesis decorator used by FX tests."""

    def __call__(
        self, *, raw: SearchStrategy[int], rate: SearchStrategy[int]
    ) -> Callable[[Callable[[int, int], None]], Callable[[], None]]:
        """Decorate a test callable with generated money and rate values."""
        ...


_given_rounding: _RoundingGiven = given
_given_fx_conversion: _FxConversionGiven = given
_ROUNDING_MODES: st.SearchStrategy[Rounding] = st.sampled_from(tuple(Rounding))


class TestFinancialArithmeticContracts:
    """Exercise exact rounding, conversion and same-dimension arithmetic contracts."""

    def test_tick_and_lot_goldens_cover_sign_and_half_even_ties(self) -> None:
        """Match signed tick and lot rounding to exact decimal goldens."""
        for case in FinancialUnitCases.fixture()["rounding"]:
            price = Price(value=D(case["value"]), currency=Currency.from_code("USD"), per=SHARES)
            quantity = Quantity(value=price.value, dimension=SHARES)
            tick = Tick(value=D(case["tick"]), currency=Currency.from_code("USD"), per=SHARES)
            lot = Lot(value=tick.value, dimension=SHARES)
            assert price.rounded(tick, mode=Rounding(case["mode"])).value == D(case["expected"])
            assert quantity.rounded(lot, mode=Rounding(case["mode"])).value == D(case["expected"])

    def test_money_fx_quantity_multiplier_and_negative_price_reconcile(self) -> None:
        """Reconcile signed quantities, multipliers, prices and currency conversion."""
        quantity = Quantity(value=D("-2"), dimension=CONTRACTS)
        multiplier = Multiplier(value=D("100"), input_dimension=CONTRACTS, output_dimension=SHARES)
        shares = multiplier.apply(quantity)
        assert shares == Quantity(value=D("-200"), dimension=SHARES)
        amount = Price(value=D("-5.25"), currency=Currency.from_code("USD"), per=SHARES).amount(
            shares
        )
        assert amount == Money(value=D("1050"), currency=Currency.from_code("USD"))
        fx = FXRate(value=D("150"), base=Currency.from_code("USD"), quote=Currency.from_code("JPY"))
        assert fx.convert(
            amount, target=Currency.from_code("JPY"), mode=Rounding.HALF_EVEN
        ).value == D("157500")
        assert (amount + amount - amount) == amount
        assert Money(value=D("-1.005"), currency=Currency.from_code("USD")).rounded(
            mode=Rounding.FLOOR
        ).value == D("-1.01")

    def test_magnitude_and_precision_boundaries_fail_closed(self) -> None:
        """Reject overflow and unrepresentable exact arithmetic while normalizing zero."""
        valid = Money(
            value=D("999999999999999999.999999999999999999"), currency=Currency.from_code("USD")
        )
        with pytest.raises(UnitError, match="magnitude"):
            valid + Money(value=D("0.000000000000000001"), currency=Currency.from_code("USD"))
        with pytest.raises(UnitError, match="representable"):
            Price(value=D("1e-18"), currency=Currency.from_code("USD"), per=SHARES).amount(
                Quantity(value=D("0.1"), dimension=SHARES)
            )
        assert Money(value=D("-0"), currency=Currency.from_code("USD")).value == 0

    def test_mismatched_arithmetic_rounding_fx_and_multiplier_reject(self) -> None:
        """Reject mismatched dimensions and unsupported operations at their public entry points."""
        money = Money(value=D("1"), currency=Currency.from_code("USD"))
        price = Price(value=D("1"), currency=Currency.from_code("USD"), per=SHARES)
        quantity = Quantity(value=D("1"), dimension=CONTRACTS)
        with pytest.raises(UnitError):
            money + money.model_copy(update={"currency": Currency.from_code("EUR")})
        with pytest.raises(UnitError):
            price.amount(quantity)
        with pytest.raises(UnitError):
            price.rounded(
                Tick(value=D("0.1"), currency=Currency.from_code("EUR"), per=SHARES),
                mode=Rounding.FLOOR,
            )
        with pytest.raises(UnitError):
            quantity.rounded(Lot(value=D("1"), dimension=SHARES), mode=Rounding.FLOOR)
        with pytest.raises(UnitError):
            Multiplier(value=D("100"), input_dimension=SHARES, output_dimension=CONTRACTS).apply(
                quantity
            )
        with pytest.raises(UnitError):
            FXRate(
                value=D("1.1"), base=Currency.from_code("EUR"), quote=Currency.from_code("USD")
            ).convert(money, target=Currency.from_code("JPY"), mode=Rounding.HALF_EVEN)
        with pytest.raises(UnitError):
            money.rounded(mode="nearest")  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed rounding rejection; expires=2027-03-01]
        with pytest.raises(TypeError):
            operator.mul(money, price)

    def test_decimal_context_cannot_change_any_exact_operation(self) -> None:
        """Keep exact arithmetic independent of the ambient decimal context."""
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            money = Money(value=D("123.456"), currency=Currency.from_code("USD"))
            assert (money + money).value == D("246.912")
            assert money.rounded(mode=Rounding.HALF_EVEN).value == D("123.46")
            fx = FXRate(
                value=D("3"), base=Currency.from_code("EUR"), quote=Currency.from_code("USD")
            )
            assert fx.convert(
                money, target=Currency.from_code("EUR"), mode=Rounding.HALF_EVEN
            ).value == D("41.15")
            assert Price(value=D("123.45"), currency=Currency.from_code("USD"), per=SHARES).amount(
                Quantity(value=D("3"), dimension=SHARES)
            ).value == D("370.35")

    def test_subclass_fields_participate_in_arithmetic_and_validated_copies(self) -> None:
        """Preserve subclass fields during reflection and leave update mappings untouched."""

        class TaggedMoney(Money):
            """Add a nonfinancial field to exercise the inherited model contract."""

            tag: str

        left = TaggedMoney(value=D("1"), currency=Currency.from_code("USD"), tag="spot")
        right = TaggedMoney(value=D("2"), currency=Currency.from_code("USD"), tag="spot")
        update: dict[str, object] = {"value": D("3")}
        copied = left.model_copy(update=update)
        assert copied == TaggedMoney(value=D("3"), currency=Currency.from_code("USD"), tag="spot")
        assert update == {"value": D("3")}
        assert left + right == TaggedMoney(
            value=D("3"), currency=Currency.from_code("USD"), tag="spot"
        )
        with pytest.raises(UnitError, match="types and dimensions"):
            left + TaggedMoney(value=D("2"), currency=Currency.from_code("USD"), tag="close")

    @pytest.mark.performance
    def test_financial_rounding_local_diagnostic_budget(self) -> None:
        """Measure ten thousand exact tick roundings against the local two-second budget."""
        price = Price(value=D("123.456"), currency=Currency.from_code("USD"), per=SHARES)
        tick = Tick(value=D("0.05"), currency=Currency.from_code("USD"), per=SHARES)
        start = perf_counter()
        for _ in range(10_000):
            assert price.rounded(tick, mode=Rounding.HALF_EVEN).value == D("123.45")
        elapsed = perf_counter() - start
        print(f"C03 10000 tick-rounding operations: {elapsed:.6f}s; local budget 2s")
        assert elapsed < 2


class TestFinancialRoundingProperties:
    """Verify exact rounding for generated signed grids."""

    @staticmethod
    @settings(max_examples=50, derandomize=True, database=None)
    @_given_rounding(
        raw=st.integers(-100_000, 100_000),
        step=st.integers(1, 100),
        mode=_ROUNDING_MODES,
    )
    def test_rounding_is_on_grid_idempotent_and_has_bounded_error(
        raw: int, step: int, mode: Rounding
    ) -> None:
        """Keep every rounding mode on its grid with bounded directional error."""
        value = D(raw) / 1000
        quantum = D(step) / 100
        price = Price(value=value, currency=Currency.from_code("USD"), per=SHARES)
        quantity = Quantity(value=value, dimension=SHARES)
        tick = Tick(value=quantum, currency=Currency.from_code("USD"), per=SHARES)
        lot = Lot(value=quantum, dimension=SHARES)
        rounded = price.rounded(tick, mode=mode)
        assert Fraction(rounded.value) / Fraction(quantum) == int(
            Fraction(rounded.value) / Fraction(quantum)
        )
        assert rounded.rounded(tick, mode=mode) == rounded
        assert quantity.rounded(lot, mode=mode).value == rounded.value
        error = Fraction(rounded.value) - Fraction(value)
        if mode is Rounding.HALF_EVEN:
            assert abs(error) <= Fraction(quantum) / 2
        else:
            assert abs(error) < Fraction(quantum)
        if mode is Rounding.FLOOR:
            assert error <= 0
        elif mode is Rounding.CEILING:
            assert error >= 0
        elif mode is Rounding.TOWARD_ZERO:
            assert abs(rounded.value) <= abs(value)


class TestFXConversionProperties:
    """Bound generated conversion and round-trip currency errors."""

    @staticmethod
    @settings(max_examples=50, derandomize=True, database=None)
    @_given_fx_conversion(raw=st.integers(-1_000_000, 1_000_000), rate=st.integers(1, 10000))
    def test_fx_conversion_has_declared_currency_rounding_tolerance(raw: int, rate: int) -> None:
        """Bound conversion and round-trip error by the currency minor units."""
        money = Money(value=D(raw) / 100, currency=Currency.from_code("EUR"))
        fx = FXRate(
            value=D(rate) / 100, base=Currency.from_code("EUR"), quote=Currency.from_code("USD")
        )
        converted = fx.convert(money, target=Currency.from_code("USD"), mode=Rounding.HALF_EVEN)
        exact = Fraction(money.value) * Fraction(fx.value)
        assert abs(Fraction(converted.value) - exact) <= Fraction(1, 200)
        restored = fx.convert(converted, target=Currency.from_code("EUR"), mode=Rounding.HALF_EVEN)
        # One half-minor-unit error in each currency, expressed back in base units.
        assert abs(Fraction(restored.value) - Fraction(money.value)) <= (
            Fraction(1, 200) / Fraction(fx.value) + Fraction(1, 200)
        )


if __name__ == "__main__":
    # Start pytest before Hypothesis is imported so assertion rewriting stays valid.
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "pytest",
            __file__,
            str(Path(__file__).with_name("test_settlement_conventions.py")),
            str(Path(__file__).with_name("test_day_count_conventions.py")),
            str(Path(__file__).with_name("test_unit_model_contracts.py")),
            "-q",
            "-W",
            "error",
            "--strict-markers",
            "-o",
            "markers=performance: local diagnostic timing",
            "-m",
            "not performance",
        ],
    )
