"""Retain hand-calculated, property, context, boundary and failure evidence for C03."""

from __future__ import annotations

# standard library imports
import operator
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from time import perf_counter
from typing import TypedDict
from uuid import UUID

# third party library imports
import pytest
import QuantLib as ql
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, TypeAdapter, ValidationError

# project library imports
from alpha_research.financial_units import (
    BusinessDayConvention as BDC,
)
from alpha_research.financial_units import (
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
    QuantLibConventions,
    Rate,
    RateConvention,
    Rounding,
    Tick,
    UnitError,
    Volatility,
    Yield,
    adjust_business_day,
    conventions,
    settlement_date,
)
from alpha_research.instrument_identity import InstrumentId
from alpha_research.venue_calendar import SettlementCalendar

D = Decimal
SHARES = Dimension(instrument_id=InstrumentId(UUID(int=1)), kind=QuantityKind.SHARE)
CONTRACTS = Dimension(instrument_id=InstrumentId(UUID(int=2)), kind=QuantityKind.CONTRACT)
CONTEXT = EvaluationContext(evaluation_date=date(2024, 1, 1), convention_revision="c03-v1")
CONVENTION = RateConvention(day_count=DayCount.ACTUAL_360, compounding=Compounding.SIMPLE)
FIXTURE = Path(__file__).parents[1] / "golden/financial_units/c03_units.json"


class _Tolerance(TypedDict):
    """Retain decimal-string year tolerances and their numerical justification."""

    absolute_years: str
    relative: str
    rationale: str


class _DayCountCase(TypedDict):
    """Describe an ISO-date interval and its hand-calculated rational year count."""

    basis: str
    start: str
    end: str
    numerator: int
    denominator: int


class _RoundingCase(TypedDict):
    """Retain exact decimal strings for a rounding input, grid and expected result."""

    value: str
    tick: str
    mode: str
    expected: str


class _FinancialFixture(TypedDict):
    """Bind synthetic golden cases to their convention, native version and tolerances."""

    fixture_kind: str
    convention_revision: str
    quantlib_version: str
    tolerance: _Tolerance
    day_counts: list[_DayCountCase]
    rounding: list[_RoundingCase]


def fixture() -> _FinancialFixture:
    """Read golden inputs and validate every consumed field without coercion.

    Returns:
        Typed cases preserving decimal strings and integer rational components.

    Raises:
        OSError: The golden file cannot be read.
        ValidationError: The JSON or a required field has an invalid shape or type.
    """
    return TypeAdapter(_FinancialFixture).validate_json(FIXTURE.read_bytes(), strict=True)


def calendar() -> SettlementCalendar:
    """Build the synthetic holiday gap used by settlement and coverage tests.

    Returns:
        A UTC calendar covering August 29 through September 5, 2024, inclusively.
    """
    return SettlementCalendar(
        calendar_id="synthetic",
        calendar_version="v1",
        timezone_name="UTC",
        covered_from=date(2024, 8, 29),
        covered_through=date(2024, 9, 5),
        settlement_dates=(
            date(2024, 8, 29),
            date(2024, 8, 30),
            date(2024, 9, 3),
            date(2024, 9, 4),
            date(2024, 9, 5),
        ),
        source="synthetic",
        source_revision="v1",
    )


class TestFinancialFixtureValidation:
    """Reject malformed golden inputs before they reach numerical assertions."""

    @pytest.mark.parametrize(
        ("original", "replacement"),
        [
            ('"quantlib_version"', '"missing_version"'),
            ('"numerator": 2', '"numerator": true'),
            ('"denominator": 360', '"denominator": "360"'),
            ('"absolute_years": "1e-12"', '"absolute_years": 1e-12'),
            ('"value": "1.025"', '"value": 1.025'),
        ],
    )
    def test_rejects_missing_fields_and_scalar_coercion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, original: str, replacement: str
    ) -> None:
        """Reject missing metadata and wrong scalar types inside both nested case groups."""
        payload = FIXTURE.read_text(encoding="utf-8")
        assert original in payload
        malformed = tmp_path / "malformed.json"
        malformed.write_text(payload.replace(original, replacement), encoding="utf-8")
        monkeypatch.setitem(globals(), "FIXTURE", malformed)
        with pytest.raises(ValidationError):
            fixture()


def test_hand_calculated_golden_day_counts() -> None:
    """Match native year fractions to rational goldens within the declared tolerances."""
    data = fixture()
    assert data["quantlib_version"] == conventions.QUANTLIB_VERSION
    for case in data["day_counts"]:
        result = QuantLibConventions().year_fraction(
            context=CONTEXT,
            start=date.fromisoformat(case["start"]),
            end=date.fromisoformat(case["end"]),
            day_count=DayCount(case["basis"]),
        )
        expected = case["numerator"] / case["denominator"]
        assert float(result.duration.value) == pytest.approx(
            expected,
            abs=float(data["tolerance"]["absolute_years"]),
            rel=float(data["tolerance"]["relative"]),
        )
        assert result.context == CONTEXT
        assert result.duration.day_count == DayCount(case["basis"])


def test_tick_and_lot_goldens_cover_sign_and_half_even_ties() -> None:
    """Match signed tick and lot rounding to exact decimal goldens."""
    for case in fixture()["rounding"]:
        price = Price(value=D(case["value"]), currency=Currency.USD, per=SHARES)
        quantity = Quantity(value=price.value, dimension=SHARES)
        tick = Tick(value=D(case["tick"]), currency=Currency.USD, per=SHARES)
        lot = Lot(value=tick.value, dimension=SHARES)
        assert price.rounded(tick, mode=Rounding(case["mode"])).value == D(case["expected"])
        assert quantity.rounded(lot, mode=Rounding(case["mode"])).value == D(case["expected"])


@settings(max_examples=50, derandomize=True, database=None)
@given(st.integers(-100_000, 100_000), st.integers(1, 100), st.sampled_from(list(Rounding)))
def test_rounding_is_on_grid_idempotent_and_has_bounded_error(
    raw: int, step: int, mode: Rounding
) -> None:
    """Keep every rounding mode on its grid with bounded directional error."""
    value = D(raw) / 1000
    quantum = D(step) / 100
    price = Price(value=value, currency=Currency.USD, per=SHARES)
    quantity = Quantity(value=value, dimension=SHARES)
    tick = Tick(value=quantum, currency=Currency.USD, per=SHARES)
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


@settings(max_examples=50, derandomize=True, database=None)
@given(st.integers(-1_000_000, 1_000_000), st.integers(1, 10000))
def test_fx_conversion_has_declared_currency_rounding_tolerance(raw: int, rate: int) -> None:
    """Bound conversion and round-trip error by the currency minor units."""
    money = Money(value=D(raw) / 100, currency=Currency.EUR)
    fx = FXRate(value=D(rate) / 100, base=Currency.EUR, quote=Currency.USD)
    converted = fx.convert(money, target=Currency.USD, mode=Rounding.HALF_EVEN)
    exact = Fraction(money.value) * Fraction(fx.value)
    assert abs(Fraction(converted.value) - exact) <= Fraction(1, 200)
    restored = fx.convert(converted, target=Currency.EUR, mode=Rounding.HALF_EVEN)
    # One half-minor-unit error in each currency, expressed back in base units.
    assert abs(Fraction(restored.value) - Fraction(money.value)) <= (
        Fraction(1, 200) / Fraction(fx.value) + Fraction(1, 200)
    )


def test_money_fx_quantity_multiplier_and_negative_price_reconcile() -> None:
    """Reconcile signed quantities, multipliers, prices and currency conversion."""
    quantity = Quantity(value=D("-2"), dimension=CONTRACTS)
    multiplier = Multiplier(value=D("100"), input_dimension=CONTRACTS, output_dimension=SHARES)
    shares = multiplier.apply(quantity)
    assert shares == Quantity(value=D("-200"), dimension=SHARES)
    amount = Price(value=D("-5.25"), currency=Currency.USD, per=SHARES).amount(shares)
    assert amount == Money(value=D("1050"), currency=Currency.USD)
    fx = FXRate(value=D("150"), base=Currency.USD, quote=Currency.JPY)
    assert fx.convert(amount, target=Currency.JPY, mode=Rounding.HALF_EVEN).value == D("157500")
    assert (amount + amount - amount) == amount
    assert Money(value=D("-1.005"), currency=Currency.USD).rounded(mode=Rounding.FLOOR).value == D(
        "-1.01"
    )


@pytest.mark.parametrize(
    "bad", [1, True, 1.0, "1", D("NaN"), D("sNaN"), D("Infinity"), D("1e18"), D("1e-19")]
)
def test_invalid_decimal_values_fail_without_coercion(bad: object) -> None:
    """Reject malformed decimals through the public Money constructor."""
    with pytest.raises(UnitError):
        Money(value=bad, currency=Currency.USD)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor decimal rejection; expires=2027-03-01]


def test_magnitude_and_precision_boundaries_fail_closed() -> None:
    """Reject overflow and unrepresentable exact arithmetic while normalizing zero."""
    valid = Money(value=D("999999999999999999.999999999999999999"), currency=Currency.USD)
    with pytest.raises(UnitError, match="magnitude"):
        valid + Money(value=D("0.000000000000000001"), currency=Currency.USD)
    with pytest.raises(UnitError, match="representable"):
        Price(value=D("1e-18"), currency=Currency.USD, per=SHARES).amount(
            Quantity(value=D("0.1"), dimension=SHARES)
        )
    assert Money(value=D("-0"), currency=Currency.USD).value == 0


def test_all_numeric_types_are_immutable_and_distinct() -> None:
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
    "operation",
    [
        lambda: Money(value=D("1"), currency="USD"),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor currency rejection; expires=2027-03-01]
        lambda: Dimension(instrument_id=UUID(int=1), kind=QuantityKind.SHARE),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor identifier rejection; expires=2027-03-01]
        lambda: Dimension(instrument_id=InstrumentId(UUID(int=1)), kind="share"),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor kind rejection; expires=2027-03-01]
        lambda: Quantity(value=D("1"), dimension={}),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor dimension rejection; expires=2027-03-01]
        lambda: Price(value=D("1"), currency=Currency.USD, per={}),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor dimension rejection; expires=2027-03-01]
        lambda: RateConvention(day_count="actual_360", compounding=Compounding.SIMPLE),  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor day-count rejection; expires=2027-03-01]
        lambda: RateConvention(day_count=DayCount.ACTUAL_360, compounding=Compounding.PERIODIC),
        lambda: RateConvention(
            day_count=DayCount.ACTUAL_360, compounding=Compounding.PERIODIC, payments_per_year=True
        ),
        lambda: CONVENTION.model_copy(update={"payments_per_year": 1}),
        lambda: EvaluationContext(evaluation_date=datetime(2024, 1, 1), convention_revision="v1"),
        lambda: CONTEXT.model_copy(update={"convention_revision": " "}),
        lambda: FXRate(value=D("1"), base=Currency.USD, quote=Currency.USD),
        lambda: FXRate(value=D("0"), base=Currency.USD, quote=Currency.EUR),
        lambda: Tick(value=D("0"), currency=Currency.USD, per=SHARES),
        lambda: Lot(value=D("-1"), dimension=SHARES),
        lambda: Multiplier(value=D("0"), input_dimension=SHARES, output_dimension=SHARES),
    ],
)
def test_invalid_units_and_conventions(operation: Callable[[], object]) -> None:
    """Require each malformed constructor or replacement to raise the owned error."""
    with pytest.raises(UnitError):
        operation()


def test_mismatched_arithmetic_rounding_fx_and_multiplier_reject() -> None:
    """Reject mismatched dimensions and unsupported operations at their public entry points."""
    money = Money(value=D("1"), currency=Currency.USD)
    price = Price(value=D("1"), currency=Currency.USD, per=SHARES)
    quantity = Quantity(value=D("1"), dimension=CONTRACTS)
    with pytest.raises(UnitError):
        money + money.model_copy(update={"currency": Currency.EUR})
    with pytest.raises(UnitError):
        price.amount(quantity)
    with pytest.raises(UnitError):
        price.rounded(Tick(value=D("0.1"), currency=Currency.EUR, per=SHARES), mode=Rounding.FLOOR)
    with pytest.raises(UnitError):
        quantity.rounded(Lot(value=D("1"), dimension=SHARES), mode=Rounding.FLOOR)
    with pytest.raises(UnitError):
        Multiplier(value=D("100"), input_dimension=SHARES, output_dimension=CONTRACTS).apply(
            quantity
        )
    with pytest.raises(UnitError):
        FXRate(value=D("1.1"), base=Currency.EUR, quote=Currency.USD).convert(
            money, target=Currency.JPY, mode=Rounding.HALF_EVEN
        )
    with pytest.raises(UnitError):
        money.rounded(mode="nearest")  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed rounding rejection; expires=2027-03-01]
    with pytest.raises(TypeError):
        operator.mul(money, price)


def test_decimal_context_cannot_change_any_exact_operation() -> None:
    """Keep exact arithmetic independent of the ambient decimal context."""
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        money = Money(value=D("123.456"), currency=Currency.USD)
        assert (money + money).value == D("246.912")
        assert money.rounded(mode=Rounding.HALF_EVEN).value == D("123.46")
        fx = FXRate(value=D("3"), base=Currency.EUR, quote=Currency.USD)
        assert fx.convert(money, target=Currency.EUR, mode=Rounding.HALF_EVEN).value == D("41.15")
        assert Price(value=D("123.45"), currency=Currency.USD, per=SHARES).amount(
            Quantity(value=D("3"), dimension=SHARES)
        ).value == D("370.35")


@pytest.mark.parametrize(
    ("convention", "candidate", "expected"),
    [
        (BDC.UNADJUSTED, date(2024, 8, 31), date(2024, 8, 31)),
        (BDC.FOLLOWING, date(2024, 8, 31), date(2024, 9, 3)),
        (BDC.MODIFIED_FOLLOWING, date(2024, 8, 31), date(2024, 8, 30)),
        (BDC.PRECEDING, date(2024, 9, 1), date(2024, 8, 30)),
        (BDC.MODIFIED_PRECEDING, date(2024, 9, 1), date(2024, 9, 3)),
    ],
)
def test_business_day_and_settlement_goldens(
    convention: BDC, candidate: date, expected: date
) -> None:
    """Match business-day adjustments and settlement lags across the holiday gap."""
    assert adjust_business_day(candidate, calendar=calendar(), convention=convention) == expected
    assert (
        settlement_date(candidate, business_day_lag=0, calendar=calendar(), convention=convention)
        == expected
    )
    assert settlement_date(
        date(2024, 8, 30), business_day_lag=2, calendar=calendar(), convention=BDC.FOLLOWING
    ) == date(2024, 9, 4)


@pytest.mark.parametrize("lag", [-1, 367, True, 1.0])
def test_bad_settlement_lag_rejects(lag: object) -> None:
    """Reject out-of-range and non-integer lags through the settlement function."""
    with pytest.raises(ConventionError, match="lag"):
        settlement_date(
            date(2024, 8, 30),
            business_day_lag=lag,  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed settlement lag rejection; expires=2027-03-01]
            calendar=calendar(),
            convention=BDC.FOLLOWING,
        )


def test_calendar_coverage_and_unknown_conventions_fail_closed() -> None:
    """Reject uncovered dates, empty calendars and untyped convention strings."""
    for candidate in (date(2024, 8, 28), date(2024, 9, 6)):
        with pytest.raises(ConventionError, match="coverage"):
            adjust_business_day(candidate, calendar=calendar(), convention=BDC.UNADJUSTED)
    with pytest.raises(ConventionError, match="coverage"):
        settlement_date(
            date(2024, 9, 5), business_day_lag=1, calendar=calendar(), convention=BDC.FOLLOWING
        )
    empty = calendar().model_copy(update={"settlement_dates": ()})
    with pytest.raises(ConventionError, match="coverage"):
        adjust_business_day(date(2024, 8, 31), calendar=empty, convention=BDC.FOLLOWING)
    with pytest.raises(UnitError):
        adjust_business_day(date(2024, 8, 31), calendar=calendar(), convention="following")  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed convention rejection; expires=2027-03-01]


def test_native_failure_nonfinite_and_version_mismatch_are_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Translate version, nonfinite-result and native-call failures into owned errors."""

    def calculate() -> None:
        """Invoke the owned adapter through its normal native day-count path.

        Raises:
            ConventionError: The currently patched metadata or native counter fails.
        """
        QuantLibConventions().time_to(
            context=CONTEXT, end=date(2025, 1, 1), day_count=DayCount.ACTUAL_360
        )

    monkeypatch.setattr(conventions, "version", lambda _: "1.40")
    with pytest.raises(ConventionError, match="exactly"):
        calculate()

    def missing(_: str) -> str:
        """Simulate unavailable native-package version metadata.

        Args:
            _: Distribution name, intentionally ignored by the failure double.

        Returns:
            No version string; every call raises instead.

        Raises:
            PackageNotFoundError: The synthetic native distribution is unavailable.
        """
        raise PackageNotFoundError

    monkeypatch.setattr(conventions, "version", missing)
    with pytest.raises(ConventionError, match="unavailable"):
        calculate()
    monkeypatch.setattr(conventions, "version", lambda _: "1.43")

    class BadCounter:
        """Simulate a native day counter returning a nonfinite float."""

        def yearFraction(self, start: object, end: object) -> float:
            """Return a nonfinite native result to exercise adapter rejection.

            Args:
                start: Native start-date argument, intentionally unused.
                end: Native end-date argument, intentionally unused.

            Returns:
                A NaN float, without validating the supplied dates.
            """
            return float("nan")

    monkeypatch.setattr(ql, "Actual360", BadCounter)
    with pytest.raises(ConventionError, match="invalid year"):
        calculate()

    def fail() -> None:
        """Simulate an exception from native counter construction.

        Raises:
            RuntimeError: The synthetic native counter cannot be constructed.
        """
        raise RuntimeError("synthetic native failure")

    monkeypatch.setattr(ql, "Actual360", fail)
    with pytest.raises(ConventionError, match="evaluation failed") as error:
        calculate()
    assert isinstance(error.value.__cause__, RuntimeError)


def test_explicit_context_isolated_from_native_global_date_and_concurrent_calls() -> None:
    """Keep concurrent evaluation contexts independent of native global date state."""
    # Settings is touched only in this adversarial test, never by the owned adapter.
    saved = ql.Settings.instance().evaluationDate
    try:
        ql.Settings.instance().evaluationDate = ql.Date(1, 1, 1999)
        contexts = [
            CONTEXT.model_copy(update={"evaluation_date": date(2024, 1, day)}) for day in (1, 2, 3)
        ]

        def evaluate(context: EvaluationContext) -> Decimal:
            """Calculate a context-specific year fraction ending on January 4, 2024.

            Args:
                context: Explicit evaluation date and convention revision for the adapter.

            Returns:
                Actual/360 duration from the evaluation date, rounded to 1e-15 years.

            Raises:
                ConventionError: Native evaluation or version validation fails.
            """
            return (
                QuantLibConventions()
                .time_to(context=context, end=date(2024, 1, 4), day_count=DayCount.ACTUAL_360)
                .duration.value
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(evaluate, contexts))
        assert results == [evaluate(context) for context in contexts]
        assert results[0] > results[1] > results[2]
        assert ql.Settings.instance().evaluationDate == ql.Date(1, 1, 1999)
    finally:
        ql.Settings.instance().evaluationDate = saved


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(1900, 1, 1), date(2024, 1, 1)),
        (date(2024, 1, 1), date(2200, 1, 1)),
        (date(2024, 1, 2), date(2024, 1, 1)),
    ],
)
def test_day_count_invalid_dates_fail(start: date, end: date) -> None:
    """Reject reversed intervals and dates outside native coverage."""
    with pytest.raises(ConventionError):
        QuantLibConventions().year_fraction(
            context=CONTEXT, start=start, end=end, day_count=DayCount.ACTUAL_360
        )


@settings(max_examples=50, derandomize=True, database=None)
@given(st.integers(0, 365), st.integers(0, 365))
def test_actual360_intervals_are_additive(first: int, second: int) -> None:
    """Bound additive interval error by the three declared year-fraction roundings."""
    adapter = QuantLibConventions()
    start = CONTEXT.evaluation_date
    middle = start + timedelta(days=first)
    end = middle + timedelta(days=second)

    def years(left: date, right: date) -> Decimal:
        """Extract the decimal duration for one Actual/360 interval.

        Args:
            left: Inclusive interval start within the generated date range.
            right: Interval end, at or after left.

        Returns:
            Duration rounded to 1e-15 years under the captured convention revision.

        Raises:
            ConventionError: Native evaluation or version validation fails.
        """
        return adapter.year_fraction(
            context=CONTEXT, start=left, end=right, day_count=DayCount.ACTUAL_360
        ).duration.value

    # Three 1e-15 roundings permit at most 1.5e-15 years absolute accumulation error.
    assert abs(years(start, middle) + years(middle, end) - years(start, end)) <= D("1.5e-15")


@pytest.mark.parametrize("bad", [float("inf"), -1.0, 1, True, None])
def test_native_results_reject_wrong_type_sign_and_infinity(
    monkeypatch: pytest.MonkeyPatch,
    bad: object,
) -> None:
    """Reject malformed native values before they become an owned duration."""

    class Counter:
        """Inject a native result with the wrong type, sign or finiteness."""

        def yearFraction(self, start: object, end: object) -> object:
            """Return the captured invalid native value without validating it.

            Args:
                start: Native start-date argument, intentionally unused.
                end: Native end-date argument, intentionally unused.

            Returns:
                The parametrized wrong-type, negative or nonfinite value unchanged.
            """
            return bad

    monkeypatch.setattr(ql, "Actual360", Counter)
    with pytest.raises(ConventionError, match="invalid year"):
        QuantLibConventions().time_to(
            context=CONTEXT, end=date(2025, 1, 1), day_count=DayCount.ACTUAL_360
        )


@pytest.mark.parametrize("bad", ["actual_360", None, 1])
def test_unknown_day_count_is_not_coerced(bad: object) -> None:
    """Reject raw day-count values through the typed adapter method."""
    with pytest.raises(UnitError, match="day count"):
        QuantLibConventions().time_to(context=CONTEXT, end=date(2025, 1, 1), day_count=bad)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed day-count rejection; expires=2027-03-01]


@pytest.mark.performance
def test_financial_rounding_local_diagnostic_budget() -> None:
    """Measure ten thousand exact tick roundings against the local two-second budget."""
    price = Price(value=D("123.456"), currency=Currency.USD, per=SHARES)
    tick = Tick(value=D("0.05"), currency=Currency.USD, per=SHARES)
    start = perf_counter()
    for _ in range(10_000):
        assert price.rounded(tick, mode=Rounding.HALF_EVEN).value == D("123.45")
    elapsed = perf_counter() - start
    print(f"C03 10000 tick-rounding operations: {elapsed:.6f}s; local budget 2s")
    assert elapsed < 2


def test_modified_adjustment_compares_year_as_well_as_month() -> None:
    """Treat same-month dates in different years as crossing an adjustment boundary."""
    bounded = SettlementCalendar(
        calendar_id="synthetic-sparse",
        calendar_version="v1",
        timezone_name="UTC",
        covered_from=date(2024, 1, 1),
        covered_through=date(2025, 1, 31),
        settlement_dates=(date(2024, 1, 1), date(2025, 1, 31)),
        source="synthetic",
        source_revision="v1",
    )
    assert adjust_business_day(
        date(2024, 1, 30), calendar=bounded, convention=BDC.MODIFIED_FOLLOWING
    ) == date(2024, 1, 1)
    assert adjust_business_day(
        date(2025, 1, 2), calendar=bounded, convention=BDC.MODIFIED_PRECEDING
    ) == date(2025, 1, 31)


def test_c01_c02_unvalidated_copies_cannot_bypass_boundary_validation() -> None:
    """Reject unchecked identity and calendar replacements at financial boundaries."""
    invalid_id = InstrumentId(UUID(int=1)).model_copy(update={"uuid_value": UUID(int=0)})
    with pytest.raises(UnitError, match="non-nil"):
        Dimension(instrument_id=invalid_id, kind=QuantityKind.SHARE)
    invalid_calendar = calendar().model_copy(
        update={"settlement_dates": (date(2024, 9, 3), date(2024, 8, 30))}
    )
    with pytest.raises(ConventionError, match="invalid settlement"):
        adjust_business_day(date(2024, 8, 31), calendar=invalid_calendar, convention=BDC.FOLLOWING)


@pytest.mark.parametrize(
    "model",
    [
        SHARES,
        CONVENTION,
        CONTEXT,
        Money(value=D("1.25"), currency=Currency.USD),
        Quantity(value=D("2"), dimension=SHARES),
        Price(value=D("1.25"), currency=Currency.USD, per=SHARES),
        Tick(value=D("0.05"), currency=Currency.USD, per=SHARES),
        Lot(value=D("1"), dimension=SHARES),
        Multiplier(value=D("100"), input_dimension=CONTRACTS, output_dimension=SHARES),
        FXRate(value=D("1.1"), base=Currency.EUR, quote=Currency.USD),
        Rate(value=D("0.05"), convention=CONVENTION),
        Yield(value=D("0.05"), convention=CONVENTION),
        Volatility(value=D("0.2"), day_count=DayCount.ACTUAL_365_FIXED),
        Duration(value=D("1"), day_count=DayCount.ACTUAL_360),
        DayCountResult(
            context=CONTEXT,
            start=date(2024, 1, 1),
            end=date(2024, 1, 2),
            duration=Duration(value=D("0.002777777777778"), day_count=DayCount.ACTUAL_360),
        ),
    ],
)
def test_all_public_models_keep_frozen_hashable_strict_pydantic_semantics(
    model: BaseModel,
) -> None:
    """Preserve strict validation, immutability and hashes across public model copies."""
    assert isinstance(model, BaseModel)
    assert type(model).model_validate(dict(model)) == model
    assert type(model).model_validate(model) == model
    for deep in (False, True):
        copied = model.model_copy(deep=deep)
        assert copied == model and copied is not model
        assert hash(copied) == hash(model)
    field = next(iter(type(model).model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(model, field, getattr(model, field))
    with pytest.raises(UnitError, match="Extra inputs"):
        model.model_copy(update={"unknown_field": "synthetic-sensitive-input"})


@pytest.mark.parametrize("bad", [D("NaN"), D("1e18"), D("1e-19"), 1.0, "1.25"])
def test_model_copy_revalidates_decimal_updates_without_mutating_original(bad: object) -> None:
    """Reject malformed decimal updates and preserve the original Money value."""
    money = Money(value=D("1.25"), currency=Currency.USD)
    with pytest.raises(UnitError):
        money.model_copy(update={"value": bad})
    assert money.value == D("1.25")
    assert money.model_copy(update={"value": D("2.50")}).value == D("2.50")


def test_nested_models_reject_dict_coercion_subclasses_and_unchecked_copies() -> None:
    """Revalidate nested dimensions and reject dictionaries, subclasses and hostile copies."""
    with pytest.raises(ValidationError, match="dimension"):
        Quantity.model_validate({"value": D("1"), "dimension": SHARES.model_dump()})

    class DerivedDimension(Dimension):
        """Exercise the unsupported nested-subclass boundary."""

    derived = DerivedDimension(instrument_id=SHARES.instrument_id, kind=SHARES.kind)
    with pytest.raises(UnitError, match="dimension"):
        Quantity(value=D("1"), dimension=derived)
    # Deliberately call the framework's unchecked primitive to represent hostile input.
    invalid = BaseModel.model_copy(SHARES, update={"kind": "share"})
    with pytest.raises(UnitError, match="kind"):
        Quantity(value=D("1"), dimension=invalid)
    original = Quantity(value=D("1"), dimension=SHARES)
    with pytest.raises(UnitError, match="kind"):
        original.model_copy(update={"dimension": invalid})


def test_constructor_errors_preserve_owned_types_and_hide_input_values() -> None:
    """Keep constructor error categories and causes without exposing rejected inputs."""
    secret = "synthetic-sensitive-input"
    with pytest.raises(UnitError) as caught:
        Money(value=D("1"), currency=secret)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise constructor error redaction; expires=2027-03-01]
    assert secret not in str(caught.value)
    assert isinstance(caught.value.__cause__, ValidationError)
    assert secret not in str(caught.value.__cause__)
    assert "errors.pydantic.dev" not in str(caught.value)
    with pytest.raises(ValidationError) as structured:
        Money.model_validate({"value": D("1"), "currency": secret})
    assert secret not in str(structured.value)
    with pytest.raises(ConventionError, match="adapter version"):
        DayCountResult(
            context=CONTEXT,
            start=date(2024, 1, 1),
            end=date(2024, 1, 2),
            duration=Duration(value=D("0"), day_count=DayCount.ACTUAL_360),
            adapter_version="1.40",
        )


class TestQuantLibStubConformance:
    """Verify the consumed native return types and convention identifiers."""

    def test_native_day_counter_surface(self) -> None:
        """Check every declared native convention against its installed implementation."""
        assert ql.__version__ == conventions.QUANTLIB_VERSION
        assert all(
            type(value) is int
            for value in (
                ql.ActualActual.ISDA,
                ql.Thirty360.BondBasis,
                ql.Thirty360.European,
            )
        )
        counters: tuple[ql.DayCounter, ...] = (
            ql.Actual360(),
            ql.Actual365Fixed(),
            ql.ActualActual(ql.ActualActual.ISDA),
            ql.Thirty360(ql.Thirty360.BondBasis),
            ql.Thirty360(ql.Thirty360.European),
        )
        for counter in counters:
            value = counter.yearFraction(ql.Date(1, 1, 2024), ql.Date(1, 7, 2024))
            assert type(value) is float and 0.49 < value < 0.51


if __name__ == "__main__":
    raise SystemExit(
        pytest.main(
            [
                __file__,
                "-q",
                "-W",
                "error",
                "--strict-markers",
                "-o",
                "markers=performance: local diagnostic timing",
                "-m",
                "not performance",
            ]
        )
    )
