"""Count explicit day-count year fractions and bounded settlement conventions exactly."""

from __future__ import annotations

# standard library imports
import calendar
from bisect import bisect_left, bisect_right
from datetime import date
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from functools import partial
from typing import Annotated, ClassVar

# third party library imports
from pydantic import BeforeValidator

# project library imports
from financial_units.models import (
    DayCount,
    DecimalGrid,
    Duration,
    EvaluationContext,
    Rounding,
    UnitError,
    _FinancialUnitModel,
)
from reference_data.calendars import SettlementCalendar


class ConventionError(UnitError):
    """Report an invalid interval or unavailable convention/calendar coverage."""


class BusinessDayConvention(StrEnum):
    """Enumerate supported settlement-date adjustments."""

    UNADJUSTED = "unadjusted"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    MODIFIED_PRECEDING = "modified_preceding"


class DayCountResult(_FinancialUnitModel):
    """Retain the explicit evaluation and interval inputs with the exact result."""

    _validation_error_type: ClassVar[type[UnitError]] = ConventionError

    context: Annotated[
        EvaluationContext,
        BeforeValidator(
            partial(_FinancialUnitModel._require_type, expected=EvaluationContext, name="context")
        ),
    ]
    start: date
    end: date
    duration: Annotated[
        Duration,
        BeforeValidator(
            partial(_FinancialUnitModel._require_type, expected=Duration, name="duration")
        ),
    ]

    def model_post_init(self, _context: object, /) -> None:
        """Validate the interval.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: Context, dates, or duration have an unexpected concrete type.
            ConventionError: The interval is reversed.
        """
        _FinancialUnitModel._require_type(self.context, EvaluationContext, "context")
        _FinancialUnitModel._require_type(self.start, date, "start")
        _FinancialUnitModel._require_type(self.end, date, "end")
        _FinancialUnitModel._require_type(self.duration, Duration, "duration")
        if self.end < self.start:
            raise ConventionError("invalid result interval")


class DayCountConventions:
    """Count year fractions from explicit dates with exact rational arithmetic.

    Every supported convention is a ratio of whole day counts, so each result is
    computed exactly and rounded once. No ambient or global date is read.
    """

    def year_fraction(
        self,
        *,
        context: EvaluationContext,
        start: date,
        end: date,
        day_count: DayCount,
    ) -> DayCountResult:
        """Evaluate a nonnegative interval with explicit variant and retained attribution.

        The exact year fraction is rounded once, half-even, to 1e-15 years. No
        cashflow, curve, fixing, reference-period, or global date is inferred.

        - Actual/360 and Actual/365 Fixed divide the actual days by 360 or 365.
        - Actual/Actual ISDA divides the days falling in each calendar year by
          that year's length (365 or 366) and adds the parts.
        - 30/360 Bond Basis sets a start day of 31 to 30, then an end day of 31
          to 30 when the (adjusted) start day is 30.
        - 30E/360 sets any day of 31 to 30.

        Args:
            context: Caller-supplied evaluation date and convention revision, retained
                for attribution; the evaluation date need not equal ``start``.
            start: Inclusive interval start.
            end: Interval end, on or after ``start``.
            day_count: Explicit supported day-count variant.

        Returns:
            Attributed result containing a nonnegative duration in years, rounded
            once with ties to even, together with the original dates and context.

        Raises:
            UnitError: An input has an unexpected concrete type or the rounded
                result exceeds the owned Decimal bounds.
            ConventionError: The interval is reversed.
        """
        _FinancialUnitModel._require_type(context, EvaluationContext, "context")
        _FinancialUnitModel._require_type(day_count, DayCount, "day count")
        for value in (start, end, context.evaluation_date):
            _FinancialUnitModel._require_type(value, date, "date")
        if end < start:
            raise ConventionError("end cannot precede start")
        fraction = DecimalGrid.round_fraction(
            self._exact(start, end, day_count), Decimal("1e-15"), Rounding.HALF_EVEN
        )
        return DayCountResult(
            context=context,
            start=start,
            end=end,
            duration=Duration(value=fraction, day_count=day_count),
        )

    def time_to(
        self, *, context: EvaluationContext, end: date, day_count: DayCount
    ) -> DayCountResult:
        """Measure from the caller's evaluation date, never an ambient date.

        Args:
            context: Explicit start date and convention revision to retain.
            end: Interval end, on or after the evaluation date.
            day_count: Supported day-count variant for the elapsed year fraction.

        Returns:
            The result of ``year_fraction`` starting at ``context.evaluation_date``,
            with the same rounding and attribution.

        Raises:
            UnitError: An input has an unexpected concrete type or the rounded
                result exceeds the owned Decimal bounds.
            ConventionError: The interval is reversed.
        """
        _FinancialUnitModel._require_type(context, EvaluationContext, "context")
        return self.year_fraction(
            context=context, start=context.evaluation_date, end=end, day_count=day_count
        )

    @staticmethod
    def _exact(start: date, end: date, day_count: DayCount) -> Fraction:
        """Return the exact year fraction of an ordered interval."""
        match day_count:
            case DayCount.ACTUAL_360:
                return Fraction((end - start).days, 360)
            case DayCount.ACTUAL_365_FIXED:
                return Fraction((end - start).days, 365)
            case DayCount.ACTUAL_ACTUAL_ISDA:
                total = Fraction(0)
                cursor = start
                while cursor < end:
                    boundary = min(end, date(cursor.year + 1, 1, 1))
                    year_days = 366 if calendar.isleap(cursor.year) else 365
                    total += Fraction((boundary - cursor).days, year_days)
                    cursor = boundary
                return total
            case DayCount.THIRTY_360_BOND_BASIS:
                first = 30 if start.day == 31 else start.day
                last = 30 if end.day == 31 and first == 30 else end.day
                return DayCountConventions._thirty_360(start, end, first, last)
            case DayCount.THIRTY_E_360:
                return DayCountConventions._thirty_360(
                    start, end, min(start.day, 30), min(end.day, 30)
                )

    @staticmethod
    def _thirty_360(start: date, end: date, first: int, last: int) -> Fraction:
        """Return a 30/360 year fraction from already adjusted day-of-month values."""
        days = 360 * (end.year - start.year) + 30 * (end.month - start.month) + (last - first)
        return Fraction(days, 360)


class SettlementConventions:
    """Apply bounded business-day conventions against one settlement calendar.

    Construction validates and retains an independent calendar copy without I/O.
    Each operation derives its result from that immutable copy, so repeated calls
    cannot share mutable adjustment or lag state.

    Attributes:
        _calendar: Revalidated, bounded settlement calendar used by every method.
    """

    _calendar: SettlementCalendar

    def __init__(self, calendar: SettlementCalendar) -> None:
        """Bind and revalidate the calendar used by settlement operations.

        Args:
            calendar: Explicit bounded settlement dates and inclusive coverage.

        Raises:
            UnitError: ``calendar`` is not an exact ``SettlementCalendar`` instance.
            ConventionError: The supplied calendar instance fails revalidation.
        """
        _FinancialUnitModel._require_type(calendar, SettlementCalendar, "settlement calendar")
        try:
            self._calendar = SettlementCalendar.model_validate(calendar)
        except ValueError as error:
            raise ConventionError("invalid settlement calendar") from error

    def adjust_business_day(self, candidate: date, *, convention: BusinessDayConvention) -> date:
        """Adjust a covered date using explicit settlement eligibility.

        Modified conventions reverse direction when the first selected date
        changes year or month. Coverage is checked before either directional search, so
        the reverse direction cannot compensate for missing first-direction data.

        Args:
            candidate: Exact date inside the calendar's inclusive coverage.
            convention: Direction and month rule for the adjustment. UNADJUSTED
                retains a covered date even when it is not settlement-eligible.

        Returns:
            The selected eligible date, or the covered candidate for UNADJUSTED.

        Raises:
            UnitError: ``candidate`` or ``convention`` has an unexpected concrete type.
            ConventionError: The candidate is outside coverage, or the required
                directional search has no eligible date within coverage.
        """
        _FinancialUnitModel._require_type(candidate, date, "candidate")
        _FinancialUnitModel._require_type(
            convention, BusinessDayConvention, "business-day convention"
        )
        calendar = self._calendar
        if not calendar.covered_from <= candidate <= calendar.covered_through:
            raise ConventionError("date is outside settlement calendar coverage")
        if convention is BusinessDayConvention.UNADJUSTED:
            return candidate
        dates = calendar.settlement_dates
        following = bisect_left(dates, candidate)
        preceding = bisect_right(dates, candidate) - 1

        if convention in (
            BusinessDayConvention.FOLLOWING,
            BusinessDayConvention.MODIFIED_FOLLOWING,
        ):
            result = self._select_date(following)
            if convention is BusinessDayConvention.MODIFIED_FOLLOWING and (
                result.year,
                result.month,
            ) != (candidate.year, candidate.month):
                result = self._select_date(preceding)
        else:
            result = self._select_date(preceding)
            if convention is BusinessDayConvention.MODIFIED_PRECEDING and (
                result.year,
                result.month,
            ) != (candidate.year, candidate.month):
                result = self._select_date(following)
        return result

    def settlement_date(
        self,
        trade_date: date,
        *,
        business_day_lag: int,
        convention: BusinessDayConvention,
    ) -> date:
        """Adjust a trade date and count later eligible dates for a T+n lag.

        A zero lag returns the explicitly adjusted date. Positive lags exclude
        the adjusted anchor even when UNADJUSTED leaves it on a non-settlement
        date. No additional adjustment or calendar extrapolation occurs.

        Args:
            trade_date: Exact date inside the calendar's inclusive coverage.
            business_day_lag: Number of eligible dates after the adjusted anchor;
                an exact integer from zero through 366, excluding booleans.
            convention: Business-day adjustment applied to the trade date first.

        Returns:
            The adjusted anchor for zero lag, otherwise the requested subsequent
            eligible date within the retained calendar coverage.

        Raises:
            ConventionError: The lag is invalid, the trade date cannot be adjusted,
                or too few eligible dates remain within calendar coverage.
            UnitError: ``trade_date`` or ``convention`` has an unexpected concrete type.
        """
        if type(business_day_lag) is not int or not 0 <= business_day_lag <= 366:
            raise ConventionError("business-day lag must be an integer between 0 and 366")
        anchor = self.adjust_business_day(trade_date, convention=convention)
        if business_day_lag == 0:
            return anchor
        dates = self._calendar.settlement_dates
        index = bisect_right(dates, anchor) + business_day_lag - 1
        if index >= len(dates):
            raise ConventionError("settlement lag exceeds calendar coverage")
        return dates[index]

    def _select_date(self, index: int) -> date:
        """Select an eligible date without leaving known calendar coverage.

        Args:
            index: Position in the calendar's sorted eligible settlement dates.

        Returns:
            The eligible date at the requested position.

        Raises:
            ConventionError: The position is outside the retained settlement dates.
        """
        if not 0 <= index < len(self._calendar.settlement_dates):
            raise ConventionError("settlement calendar cannot determine adjustment within coverage")
        return self._calendar.settlement_dates[index]
