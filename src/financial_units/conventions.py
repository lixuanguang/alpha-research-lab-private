"""Adapt explicit day counts and bounded settlement conventions without ambient state."""

from __future__ import annotations

# standard library imports
import math
from bisect import bisect_left, bisect_right
from datetime import date
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from functools import partial
from importlib.metadata import PackageNotFoundError, version
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

QUANTLIB_VERSION: str = "1.43"


class ConventionError(UnitError):
    """Report incompatible native results or unavailable convention/calendar coverage."""


class BusinessDayConvention(StrEnum):
    """Enumerate supported settlement-date adjustments."""

    UNADJUSTED = "unadjusted"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    MODIFIED_PRECEDING = "modified_preceding"


class DayCountResult(_FinancialUnitModel):
    """Retain the explicit evaluation and interval inputs with the owned native result."""

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
    adapter_version: str = QUANTLIB_VERSION

    def model_post_init(self, _context: object, /) -> None:
        """Validate the interval and exact native-adapter identity.

        Args:
            _context: Pydantic validation context; unused by this invariant check.

        Raises:
            UnitError: Context, dates, or duration have an unexpected concrete type.
            ConventionError: The interval is reversed or the adapter version differs
                from the pinned version.
        """
        _FinancialUnitModel._require_type(self.context, EvaluationContext, "context")
        _FinancialUnitModel._require_type(self.start, date, "start")
        _FinancialUnitModel._require_type(self.end, date, "end")
        _FinancialUnitModel._require_type(self.duration, Duration, "duration")
        if self.end < self.start or self.adapter_version != QUANTLIB_VERSION:
            raise ConventionError("invalid result interval or adapter version")


class QuantLibConventions:
    """Use only explicit-date day counters; never read or write QuantLib Settings."""

    def year_fraction(
        self,
        *,
        context: EvaluationContext,
        start: date,
        end: date,
        day_count: DayCount,
    ) -> DayCountResult:
        """Evaluate a nonnegative interval with explicit variant and retained attribution.

        Native double output is rounded once to 1e-15 years. Golden acceptance uses
        absolute tolerance 1e-12 years and relative tolerance 2e-15 over 1901-2199.
        No cashflow, curve, fixing, reference-period, or global date is inferred.

        Args:
            context: Caller-supplied evaluation date and convention revision, retained
                for attribution; the evaluation date need not equal ``start``.
            start: Inclusive interval start as an exact date in 1901-2199.
            end: Interval end as an exact date in 1901-2199, on or after ``start``.
            day_count: Explicit supported day-count variant used by the native counter.

        Returns:
            Attributed result containing a nonnegative duration in years, rounded
            once with ties to even, together with the original dates and context.

        Raises:
            UnitError: An input has an unexpected concrete type or the rounded native
                result exceeds the owned Decimal bounds.
            ConventionError: Any date, including the evaluation date, is outside
                1901-2199; the interval is reversed; the pinned library is unavailable
                or mismatched; or native evaluation fails or returns an invalid value.
        """
        _FinancialUnitModel._require_type(context, EvaluationContext, "context")
        _FinancialUnitModel._require_type(day_count, DayCount, "day count")
        for value in (start, end, context.evaluation_date):
            _FinancialUnitModel._require_type(value, date, "date")
            if not 1901 <= value.year <= 2199:
                raise ConventionError("QuantLib date must be within 1901-2199")
        if end < start:
            raise ConventionError("end cannot precede start")
        try:
            # third party library imports
            import QuantLib as _ql

            if version("QuantLib") != QUANTLIB_VERSION or _ql.__version__ != QUANTLIB_VERSION:
                raise ConventionError(f"QuantLib must be exactly {QUANTLIB_VERSION}")
        except (ImportError, PackageNotFoundError) as error:
            raise ConventionError("QuantLib distribution is unavailable") from error
        counter: _ql.DayCounter
        try:
            match day_count:
                case DayCount.ACTUAL_360:
                    counter = _ql.Actual360()
                case DayCount.ACTUAL_365_FIXED:
                    counter = _ql.Actual365Fixed()
                case DayCount.ACTUAL_ACTUAL_ISDA:
                    counter = _ql.ActualActual(_ql.ActualActual.ISDA)
                case DayCount.THIRTY_360_BOND_BASIS:
                    counter = _ql.Thirty360(_ql.Thirty360.BondBasis)
                case DayCount.THIRTY_E_360:
                    counter = _ql.Thirty360(_ql.Thirty360.European)
            raw: object = counter.yearFraction(
                _ql.Date(start.day, start.month, start.year),
                _ql.Date(end.day, end.month, end.year),
            )
        except (RuntimeError, TypeError, OverflowError) as error:
            raise ConventionError("QuantLib day-count evaluation failed") from error
        if type(raw) is not float or not math.isfinite(raw) or raw < 0:
            raise ConventionError("QuantLib returned an invalid year fraction")
        fraction = DecimalGrid.round_fraction(
            Fraction(Decimal(str(raw))), Decimal("1e-15"), Rounding.HALF_EVEN
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
        """Measure from the caller's evaluation date, never the process-wide Settings date.

        Args:
            context: Explicit start date and convention revision to retain.
            end: Interval end, on or after the evaluation date, in 1901-2199.
            day_count: Supported day-count variant for the elapsed year fraction.

        Returns:
            The result of ``year_fraction`` starting at ``context.evaluation_date``,
            with the same rounding and attribution.

        Raises:
            UnitError: An input has an unexpected concrete type or the rounded native
                result exceeds the owned Decimal bounds.
            ConventionError: Date coverage, interval ordering, library compatibility,
                or native-result validation fails as described by ``year_fraction``.
        """
        _FinancialUnitModel._require_type(context, EvaluationContext, "context")
        return self.year_fraction(
            context=context, start=context.evaluation_date, end=end, day_count=day_count
        )


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
