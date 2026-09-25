"""Explicit native day-count evaluation and failure contracts."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from importlib.metadata import PackageNotFoundError
from typing import Protocol

# third party library imports
import pytest
import QuantLib as ql
from financial_unit_cases import CONTEXT, D, FinancialUnitCases
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

# project library imports
import financial_units.conventions as conventions
from financial_units import (
    ConventionError,
    DayCount,
    EvaluationContext,
    QuantLibConventions,
    UnitError,
)


class _Actual360Given(Protocol):
    """Type the two-argument Hypothesis decorator used by day-count tests."""

    def __call__(
        self, *, first: SearchStrategy[int], second: SearchStrategy[int]
    ) -> Callable[[Callable[[int, int], None]], Callable[[], None]]:
        """Decorate a test callable with generated interval lengths."""
        ...


_given_actual360: _Actual360Given = given


class TestQuantLibConventions:
    """Exercise explicit-date day-count behavior and native failure boundaries."""

    def test_hand_calculated_golden_day_counts(self) -> None:
        """Match native year fractions to rational goldens within the declared tolerances."""
        data = FinancialUnitCases.fixture()
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


class TestQuantLibFailureContracts:
    """Exercise native adapter version, result and exception boundaries."""

    def test_native_failure_nonfinite_and_version_mismatch_are_owned(
        self, monkeypatch: pytest.MonkeyPatch
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

        def mismatched_version(_: str) -> str:
            """Return a mismatched native distribution version.

            Args:
                _: Distribution name supplied by the adapter; unused by this callback.

            Returns:
                The intentionally mismatched native distribution version.
            """
            return "1.40"

        monkeypatch.setattr(conventions, "version", mismatched_version)
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

        def pinned_version(_: str) -> str:
            """Return the native distribution version accepted by the adapter.

            Args:
                _: Distribution name supplied by the adapter; unused by this callback.

            Returns:
                The pinned native distribution version accepted by the adapter.
            """
            return "1.43"

        monkeypatch.setattr(conventions, "version", pinned_version)

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


class TestQuantLibEvaluationContracts:
    """Verify explicit evaluation dates stay isolated across concurrent calls."""

    def test_explicit_context_isolated_from_native_global_date_and_concurrent_calls(self) -> None:
        """Keep concurrent evaluation contexts independent of native global date state."""
        # Settings is touched only in this adversarial test, never by the owned adapter.
        saved = ql.Settings.instance().evaluationDate
        try:
            ql.Settings.instance().evaluationDate = ql.Date(1, 1, 1999)
            contexts = [
                CONTEXT.model_copy(update={"evaluation_date": date(2024, 1, day)})
                for day in (1, 2, 3)
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


class TestQuantLibValidationContracts:
    """Exercise explicit date, native result and typed day-count validation."""

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            (date(1900, 1, 1), date(2024, 1, 1)),
            (date(2024, 1, 1), date(2200, 1, 1)),
            (date(2024, 1, 2), date(2024, 1, 1)),
        ],
    )
    def test_day_count_invalid_dates_fail(self, start: date, end: date) -> None:
        """Reject reversed intervals and dates outside native coverage."""
        with pytest.raises(ConventionError):
            QuantLibConventions().year_fraction(
                context=CONTEXT, start=start, end=end, day_count=DayCount.ACTUAL_360
            )

    @pytest.mark.parametrize("bad", [float("inf"), -1.0, 1, True, None])
    def test_native_results_reject_wrong_type_sign_and_infinity(
        self,
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
    def test_unknown_day_count_is_not_coerced(self, bad: object) -> None:
        """Reject raw day-count values through the typed adapter method."""
        with pytest.raises(UnitError, match="day count"):
            QuantLibConventions().time_to(context=CONTEXT, end=date(2025, 1, 1), day_count=bad)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed day-count rejection; expires=2027-03-01]


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


class TestDayCountProperties:
    """Verify generated Actual/360 interval additivity."""

    @staticmethod
    @settings(max_examples=50, derandomize=True, database=None)
    @_given_actual360(first=st.integers(0, 365), second=st.integers(0, 365))
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
