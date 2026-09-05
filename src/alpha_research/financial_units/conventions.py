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
import QuantLib as _ql
from pydantic import BeforeValidator

# project library imports
from alpha_research.financial_units.models import (
    DayCount,
    Duration,
    EvaluationContext,
    Rounding,
    UnitError,
    _FinancialUnitModel,
    require_type,
    round_fraction,
)
from alpha_research.venue_calendar import SettlementCalendar

QUANTLIB_VERSION = "1.43"


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
        BeforeValidator(partial(require_type, expected=EvaluationContext, name="context")),
    ]
    start: date
    end: date
    duration: Annotated[
        Duration, BeforeValidator(partial(require_type, expected=Duration, name="duration"))
    ]
    adapter_version: str = QUANTLIB_VERSION

    def model_post_init(self, _context: object, /) -> None:
        """Validate the interval and exact native-adapter identity."""
        require_type(self.context, EvaluationContext, "context")
        require_type(self.start, date, "start")
        require_type(self.end, date, "end")
        require_type(self.duration, Duration, "duration")
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
        """
        require_type(context, EvaluationContext, "context")
        require_type(day_count, DayCount, "day count")
        for value in (start, end, context.evaluation_date):
            require_type(value, date, "date")
            if not 1901 <= value.year <= 2199:
                raise ConventionError("QuantLib date must be within 1901-2199")
        if end < start:
            raise ConventionError("end cannot precede start")
        try:
            if version("QuantLib") != QUANTLIB_VERSION or _ql.__version__ != QUANTLIB_VERSION:
                raise ConventionError(f"QuantLib must be exactly {QUANTLIB_VERSION}")
        except PackageNotFoundError as error:
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
        fraction = round_fraction(Fraction(Decimal(str(raw))), Decimal("1e-15"), Rounding.HALF_EVEN)
        return DayCountResult(
            context=context,
            start=start,
            end=end,
            duration=Duration(value=fraction, day_count=day_count),
        )

    def time_to(
        self, *, context: EvaluationContext, end: date, day_count: DayCount
    ) -> DayCountResult:
        """Measure from the caller's evaluation date, never the process-wide Settings date."""
        require_type(context, EvaluationContext, "context")
        return self.year_fraction(
            context=context, start=context.evaluation_date, end=end, day_count=day_count
        )


def adjust_business_day(
    candidate: date, *, calendar: SettlementCalendar, convention: BusinessDayConvention
) -> date:
    """Adjust within C02's complete explicit coverage; never invent holidays or weekdays."""
    require_type(candidate, date, "candidate")
    require_type(calendar, SettlementCalendar, "settlement calendar")
    require_type(convention, BusinessDayConvention, "business-day convention")
    try:
        calendar = SettlementCalendar.model_validate(calendar)
    except ValueError as error:
        raise ConventionError("invalid settlement calendar") from error
    if not calendar.covered_from <= candidate <= calendar.covered_through:
        raise ConventionError("date is outside settlement calendar coverage")
    if convention is BusinessDayConvention.UNADJUSTED:
        return candidate
    dates = calendar.settlement_dates
    following = bisect_left(dates, candidate)
    preceding = bisect_right(dates, candidate) - 1

    def select(index: int) -> date:
        if not 0 <= index < len(dates):
            raise ConventionError("settlement calendar cannot determine adjustment within coverage")
        return dates[index]

    if convention in (BusinessDayConvention.FOLLOWING, BusinessDayConvention.MODIFIED_FOLLOWING):
        result = select(following)
        if convention is BusinessDayConvention.MODIFIED_FOLLOWING and (
            result.year,
            result.month,
        ) != (candidate.year, candidate.month):
            result = select(preceding)
    else:
        result = select(preceding)
        if convention is BusinessDayConvention.MODIFIED_PRECEDING and (
            result.year,
            result.month,
        ) != (candidate.year, candidate.month):
            result = select(following)
    return result


def settlement_date(
    trade_date: date,
    *,
    business_day_lag: int,
    calendar: SettlementCalendar,
    convention: BusinessDayConvention,
) -> date:
    """Adjust the trade date, then count eligible dates strictly after it for a T+n lag.

    A zero lag returns the explicitly adjusted date. Positive lags exclude the
    adjusted anchor even when UNADJUSTED leaves it on a non-settlement date.
    """
    if type(business_day_lag) is not int or not 0 <= business_day_lag <= 366:
        raise ConventionError("business-day lag must be an integer between 0 and 366")
    anchor = adjust_business_day(trade_date, calendar=calendar, convention=convention)
    if business_day_lag == 0:
        return anchor
    index = bisect_right(calendar.settlement_dates, anchor) + business_day_lag - 1
    if index >= len(calendar.settlement_dates):
        raise ConventionError("settlement lag exceeds calendar coverage")
    return calendar.settlement_dates[index]
