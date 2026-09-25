"""Define bounded settlement-calendar contracts."""

from __future__ import annotations

# standard library imports
from datetime import date, datetime

# project library imports
from reference_data.calendars.core import (
    UnknownSettlementDateError,
    VenueCalendarValidationError,
    _VenueCalendarModel,
)


class SettlementCalendar(_VenueCalendarModel):
    """Hold a bounded versioned set of eligible settlement dates.

    Dates and coverage are independent of trading-session eligibility. An empty
    settlement-date tuple is valid. Queries do not infer weekends or holidays.

    Attributes:
        calendar_id: Stable token identifying the settlement calendar.
        calendar_version: Exact calendar version token.
        timezone_name: Available IANA timezone for date interpretation, not automatic query
            conversion.
        covered_from: Inclusive first covered date.
        covered_through: Inclusive last covered date, at or after covered_from.
        settlement_dates: Immutable, strictly increasing, unique dates within coverage.
        source: Stable source attribution token.
        source_revision: Exact source revision token.
    """

    calendar_id: str
    calendar_version: str
    timezone_name: str
    covered_from: date
    covered_through: date
    settlement_dates: tuple[date, ...]
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate exact settlement dates and finite source coverage.

        Raises:
            VenueCalendarValidationError: Metadata or coverage is invalid, or eligible dates are
                not an immutable, unique, strictly increasing tuple within coverage.
        """
        _VenueCalendarModel._require_stable_token(
            self.calendar_id, field_name="settlement calendar_id"
        )
        _VenueCalendarModel._require_stable_token(
            self.calendar_version, field_name="settlement calendar_version"
        )
        _VenueCalendarModel._require_timezone_name(
            self.timezone_name, field_name="settlement timezone_name"
        )
        covered_from = _VenueCalendarModel._require_date(
            self.covered_from, field_name="settlement covered_from"
        )
        covered_through = _VenueCalendarModel._require_date(
            self.covered_through, field_name="settlement covered_through"
        )
        if covered_through < covered_from:
            raise VenueCalendarValidationError(
                "settlement covered_through cannot precede covered_from"
            )
        if not isinstance(self.settlement_dates, tuple) or not all(
            isinstance(item, date) and not isinstance(item, datetime)
            for item in self.settlement_dates
        ):
            raise VenueCalendarValidationError(
                "settlement_dates must be an immutable tuple of dates"
            )
        if tuple(sorted(set(self.settlement_dates))) != self.settlement_dates:
            raise VenueCalendarValidationError(
                "settlement_dates must be unique and strictly increasing"
            )
        if any(not covered_from <= item <= covered_through for item in self.settlement_dates):
            raise VenueCalendarValidationError("settlement date lies outside the calendar coverage")
        _VenueCalendarModel._require_stable_token(self.source, field_name="settlement source")
        _VenueCalendarModel._require_stable_token(
            self.source_revision, field_name="settlement source_revision"
        )

    def is_settlement_day(self, candidate: date) -> bool:
        """Return whether a date is explicitly eligible for settlement.

        Args:
            candidate: Date within inclusive settlement coverage; datetimes are rejected.

        Returns:
            True only if the date is recorded as eligible; False for other covered dates.

        Raises:
            VenueCalendarValidationError: The candidate is not a date or is a datetime.
            UnknownSettlementDateError: The candidate lies outside settlement coverage.
        """
        checked = _VenueCalendarModel._require_date(
            candidate, field_name="candidate settlement date"
        )
        if not self.covered_from <= checked <= self.covered_through:
            raise UnknownSettlementDateError(
                f"settlement date {checked.isoformat()} is outside calendar coverage"
            )
        return checked in self.settlement_dates

    def settlement_day_on_or_after(self, candidate: date) -> date:
        """Return the first recorded settlement date on or after a date.

        Args:
            candidate: Date within inclusive settlement coverage; datetimes are rejected.

        Returns:
            The earliest eligible date greater than or equal to the candidate.

        Raises:
            VenueCalendarValidationError: The candidate is not a date or is a datetime.
            UnknownSettlementDateError: The candidate is outside coverage, or no eligible date
                remains.
        """
        checked = _VenueCalendarModel._require_date(
            candidate, field_name="candidate settlement date"
        )
        if not self.covered_from <= checked <= self.covered_through:
            raise UnknownSettlementDateError(
                f"settlement date {checked.isoformat()} is outside calendar coverage"
            )
        for settlement_date in self.settlement_dates:
            if settlement_date >= checked:
                return settlement_date
        raise UnknownSettlementDateError(
            f"no settlement date is available on or after {checked.isoformat()}"
        )
