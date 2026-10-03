"""Exact explicit-date day-count evaluation and failure contracts."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Protocol

# third party library imports
import pytest
from financial_unit_cases import CONTEXT, D, FinancialUnitCases
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

# project library imports
from financial_units import (
    ConventionError,
    DayCount,
    DayCountConventions,
    EvaluationContext,
    UnitError,
)


class DayCountFixture:
    """Round year fractions for comparisons."""

    @staticmethod
    def rounded(numerator: int, denominator: int) -> Decimal:
        """Round a rational year count half-even to 1e-15 years, independently of the code."""
        with localcontext() as context:
            context.prec = 60
            return (Decimal(numerator) / Decimal(denominator)).quantize(
                Decimal("1e-15"), rounding=ROUND_HALF_EVEN
            )


class _IntervalGiven(Protocol):
    """Type the three-argument Hypothesis decorator used by day-count tests."""

    def __call__(
        self,
        *,
        start: SearchStrategy[int],
        first: SearchStrategy[int],
        second: SearchStrategy[int],
    ) -> Callable[[Callable[[int, int, int], None]], Callable[[], None]]:
        """Decorate a test callable with a generated start day and interval lengths."""
        ...


_given_interval: _IntervalGiven = given


class TestDayCountConventions:
    """Match hand-calculated rational goldens exactly."""

    def test_hand_calculated_golden_day_counts(self) -> None:
        """Every golden interval rounds to exactly the rational year count it declares."""
        data = FinancialUnitCases.fixture()
        for case in data["day_counts"]:
            result = DayCountConventions().year_fraction(
                context=CONTEXT,
                start=date.fromisoformat(case["start"]),
                end=date.fromisoformat(case["end"]),
                day_count=DayCount(case["basis"]),
            )
            assert result.duration.value == DayCountFixture.rounded(
                case["numerator"], case["denominator"]
            )
            assert result.context == CONTEXT
            assert result.duration.day_count == DayCount(case["basis"])

    def test_dates_are_not_limited_to_a_native_range(self) -> None:
        """Exact counting covers any calendar date, including 1800 and 2300."""
        result = DayCountConventions().year_fraction(
            context=CONTEXT,
            start=date(1800, 1, 1),
            end=date(2300, 1, 1),
            day_count=DayCount.ACTUAL_ACTUAL_ISDA,
        )
        assert result.duration.value == D("500")


class TestDayCountEvaluationContracts:
    """Verify explicit evaluation dates stay isolated across concurrent calls."""

    @staticmethod
    def _to_january_fourth(context: EvaluationContext) -> Decimal:
        """Calculate a context-specific year fraction ending on January 4, 2024.

        Args:
            context: Explicit evaluation date and convention revision.

        Returns:
            Actual/360 duration from the evaluation date, rounded to 1e-15 years.
        """
        return (
            DayCountConventions()
            .time_to(context=context, end=date(2024, 1, 4), day_count=DayCount.ACTUAL_360)
            .duration.value
        )

    def test_explicit_context_isolated_across_concurrent_calls(self) -> None:
        """Each call measures from its own evaluation date, with no shared state."""
        contexts = [
            CONTEXT.model_copy(update={"evaluation_date": date(2024, 1, day)}) for day in (1, 2, 3)
        ]
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self._to_january_fourth, contexts))
        assert results == [DayCountFixture.rounded(days, 360) for days in (3, 2, 1)]


class TestDayCountValidationContracts:
    """Exercise interval and typed day-count validation."""

    def test_reversed_interval_fails(self) -> None:
        """Reject an interval whose end precedes its start."""
        with pytest.raises(ConventionError, match="end cannot precede start"):
            DayCountConventions().year_fraction(
                context=CONTEXT,
                start=date(2024, 1, 2),
                end=date(2024, 1, 1),
                day_count=DayCount.ACTUAL_360,
            )

    @pytest.mark.parametrize("bad", ["actual_360", None, 1])
    def test_unknown_day_count_is_not_coerced(self, bad: object) -> None:
        """Reject raw day-count values through the typed method."""
        with pytest.raises(UnitError, match="day count"):
            DayCountConventions().time_to(context=CONTEXT, end=date(2025, 1, 1), day_count=bad)  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed day-count rejection; expires=2027-03-01]

    @pytest.mark.parametrize("bad", ["2024-01-01", None, 20240101])
    def test_untyped_dates_are_refused(self, bad: object) -> None:
        """Reject dates that are not exact date objects."""
        with pytest.raises(UnitError, match="date"):
            DayCountConventions().year_fraction(
                context=CONTEXT,
                start=bad,  # type: ignore[arg-type]  # [owner=platform; rationale=exercise typed date rejection; expires=2027-03-01]
                end=date(2025, 1, 1),
                day_count=DayCount.ACTUAL_360,
            )


class TestDayCountProperties:
    """Verify generated interval additivity."""

    @staticmethod
    def _years(adapter: DayCountConventions, begin: date, end: date, basis: DayCount) -> Decimal:
        """Extract the decimal duration of one interval.

        Args:
            adapter: Day-count conventions under test.
            begin: Inclusive interval start.
            end: Interval end, at or after begin.
            basis: Actual day-count convention under test.

        Returns:
            Duration rounded to 1e-15 years.
        """
        return adapter.year_fraction(
            context=CONTEXT, start=begin, end=end, day_count=basis
        ).duration.value

    @staticmethod
    @settings(max_examples=100, derandomize=True, database=None)
    @_given_interval(
        start=st.integers(0, 3650), first=st.integers(0, 800), second=st.integers(0, 800)
    )
    def test_actual_intervals_are_additive(start: int, first: int, second: int) -> None:
        """Actual conventions split at any date within three 1e-15 roundings."""
        adapter = DayCountConventions()
        left = CONTEXT.evaluation_date + timedelta(days=start)
        middle = left + timedelta(days=first)
        right = middle + timedelta(days=second)
        for basis in (DayCount.ACTUAL_360, DayCount.ACTUAL_365_FIXED, DayCount.ACTUAL_ACTUAL_ISDA):
            # Three 1e-15 roundings permit at most 1.5e-15 years of accumulated error.
            years = TestDayCountProperties._years
            total = (
                years(adapter, left, middle, basis)
                + years(adapter, middle, right, basis)
                - years(adapter, left, right, basis)
            )
            assert abs(total) <= D("1.5e-15")
