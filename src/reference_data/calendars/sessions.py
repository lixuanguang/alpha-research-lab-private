"""Define immutable trading-session, auction, and closure contracts."""

from __future__ import annotations

# standard library imports
from datetime import date, datetime
from enum import StrEnum

# third party library imports
from pydantic import field_validator

# project library imports
from reference_data.calendars.core import (
    VenueCalendarModel,
    VenueCalendarValidationError,
)


class SessionKind(StrEnum):
    """Classify the schedule shape of a trading session."""

    REGULAR = "regular"
    HALF_DAY = "half_day"
    SPECIAL = "special"


class AuctionKind(StrEnum):
    """Classify an explicitly declared venue auction window."""

    OPENING = "opening"
    CLOSING = "closing"
    REOPENING = "reopening"
    INTRADAY = "intraday"


class AuctionWindow(VenueCalendarModel):
    """Describe one half-open auction interval within a trading session.

    The window validates its own UTC bounds; TradingSession checks containment
    and ordering against other auctions. Auction and break windows may overlap.

    Attributes:
        kind: Typed auction classification.
        starts_at: Inclusive aware UTC start.
        ends_at: Exclusive aware UTC end strictly later than the start.
    """

    kind: AuctionKind
    starts_at: datetime
    ends_at: datetime

    def model_post_init(self, _context: object, /) -> None:
        """Validate the non-empty UTC auction interval.

        Raises:
            VenueCalendarValidationError: The auction kind is invalid or bounds are not aware
                UTC instants in increasing order.
        """
        if not isinstance(self.kind, AuctionKind):
            raise VenueCalendarValidationError("auction kind must be an AuctionKind")
        start = VenueCalendarModel._require_utc_datetime(
            self.starts_at, field_name="auction starts_at"
        )
        end = VenueCalendarModel._require_utc_datetime(self.ends_at, field_name="auction ends_at")
        if end <= start:
            raise VenueCalendarValidationError("auction ends_at must be after starts_at")

    def contains(self, instant: datetime) -> bool:
        """Return whether an explicit UTC instant lies in this half-open auction window.

        Args:
            instant: Aware datetime with a zero UTC offset.

        Returns:
            True from the inclusive start until the exclusive end defined by starts_at and
            ends_at.

        Raises:
            VenueCalendarValidationError: The input is not an aware datetime with a zero UTC
                offset.
        """
        checked = VenueCalendarModel._require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class TradingSession(VenueCalendarModel):
    """Describe one venue session with optional break and auction windows.

    The label is an explicit date, not derived from UTC bounds. Sessions may
    cross midnight. Breaks are strictly inside the session; auctions are ordered,
    non-overlapping and contained in the session, but may overlap the break.

    Attributes:
        session_label: Unique session date within the owning snapshot.
        opens_at: Inclusive aware UTC opening instant.
        closes_at: Exclusive aware UTC closing instant, later than opening.
        kind: Schedule classification; defaults to REGULAR.
        break_starts_at: Optional inclusive aware UTC break start, paired with
            break_ends_at.
        break_ends_at: Optional exclusive aware UTC break end.
        auctions: Immutable tuple of owned auction windows, in time order.
    """

    session_label: date
    opens_at: datetime
    closes_at: datetime
    kind: SessionKind = SessionKind.REGULAR
    break_starts_at: datetime | None = None
    break_ends_at: datetime | None = None
    auctions: tuple[AuctionWindow, ...] = ()

    @field_validator("auctions", mode="before")
    @classmethod
    def typed_auctions(cls, value: object) -> object:
        """Require immutable owned auction values before nested validation.

        Args:
            value: Tuple containing only AuctionWindow instances; an empty tuple is admitted.

        Returns:
            The original tuple for subsequent validation.

        Raises:
            VenueCalendarValidationError: The value is not a tuple of AuctionWindow instances.
        """
        if not isinstance(value, tuple) or not all(
            isinstance(auction, AuctionWindow) for auction in value
        ):
            raise VenueCalendarValidationError(
                "session auctions must be an immutable tuple of AuctionWindow values"
            )
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate ordered session, break, and auction boundaries.

        Raises:
            VenueCalendarValidationError: The label, kind or UTC bounds are invalid; a break is
                unpaired or not strictly internal; or auctions are unordered, overlapping or
                outside the session.
        """
        VenueCalendarModel._require_date(self.session_label, field_name="session_label")
        opens_at = VenueCalendarModel._require_utc_datetime(
            self.opens_at, field_name="session opens_at"
        )
        closes_at = VenueCalendarModel._require_utc_datetime(
            self.closes_at, field_name="session closes_at"
        )
        if closes_at <= opens_at:
            raise VenueCalendarValidationError("session closes_at must be after opens_at")
        if not isinstance(self.kind, SessionKind):
            raise VenueCalendarValidationError("session kind must be a SessionKind")
        if (self.break_starts_at is None) != (self.break_ends_at is None):
            raise VenueCalendarValidationError(
                "session break_starts_at and break_ends_at must be provided together"
            )
        if self.break_starts_at is not None and self.break_ends_at is not None:
            break_start = VenueCalendarModel._require_utc_datetime(
                self.break_starts_at, field_name="session break_starts_at"
            )
            break_end = VenueCalendarModel._require_utc_datetime(
                self.break_ends_at, field_name="session break_ends_at"
            )
            if not opens_at < break_start < break_end < closes_at:
                raise VenueCalendarValidationError(
                    "session break must lie strictly inside the session"
                )
        if not isinstance(self.auctions, tuple) or not all(
            isinstance(auction, AuctionWindow) for auction in self.auctions
        ):
            raise VenueCalendarValidationError(
                "session auctions must be an immutable tuple of AuctionWindow values"
            )
        prior_end: datetime | None = None
        for auction in self.auctions:
            if not opens_at <= auction.starts_at < auction.ends_at <= closes_at:
                raise VenueCalendarValidationError("auction must lie inside its session")
            if prior_end is not None and auction.starts_at < prior_end:
                raise VenueCalendarValidationError(
                    "auction windows must be ordered and non-overlapping"
                )
            prior_end = auction.ends_at

    def contains(self, instant: datetime) -> bool:
        """Return whether an explicit UTC instant lies in this half-open session.

        Containment includes auctions, breaks and halts; it does not determine
        continuous-trading eligibility.

        Args:
            instant: Aware datetime with a zero UTC offset.

        Returns:
            True from the inclusive start until the exclusive end defined by opens_at and
            closes_at.

        Raises:
            VenueCalendarValidationError: The input is not an aware datetime with a zero UTC
                offset.
        """
        checked = VenueCalendarModel._require_utc_datetime(instant, field_name="instant")
        return self.opens_at <= checked < self.closes_at


class ClosureKind(StrEnum):
    """Classify an explicitly attributed non-session date."""

    HOLIDAY = "holiday"
    AD_HOC = "ad_hoc"


class CalendarClosure(VenueCalendarModel):
    """Name one source-attributed date on which no session exists.

    The snapshot checks date coverage and absence of a session with that label.

    Attributes:
        calendar_date: Explicit date of the closure; datetimes are rejected.
        kind: Typed holiday or ad-hoc closure classification.
        name: Unpadded nonempty description, up to 128 characters.
        source: Stable attribution token, up to 128 characters.
        source_revision: Stable source revision token, up to 128 characters.
    """

    calendar_date: date
    kind: ClosureKind
    name: str
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Require an attributed closure date and bounded description.

        Raises:
            VenueCalendarValidationError: The date, closure kind, bounded name or attribution
                token is invalid.
        """
        VenueCalendarModel._require_date(self.calendar_date, field_name="calendar closure date")
        if not isinstance(self.kind, ClosureKind):
            raise VenueCalendarValidationError("closure kind must be a ClosureKind")
        VenueCalendarModel._require_bounded_text(
            self.name, field_name="closure name", maximum_length=128
        )
        VenueCalendarModel._require_stable_token(self.source, field_name="closure source")
        VenueCalendarModel._require_stable_token(
            self.source_revision, field_name="closure source_revision"
        )
