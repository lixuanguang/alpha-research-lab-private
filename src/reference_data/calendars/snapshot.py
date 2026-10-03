"""Define immutable venue-calendar snapshots and their point-in-time queries."""

from __future__ import annotations

# standard library imports
from bisect import bisect_right
from datetime import date, datetime

# third party library imports
from pydantic import ValidationInfo, field_validator

# project library imports
from reference_data.calendars.core import (
    CalendarCoverageError,
    CalendarSourceVersion,
    UnknownSessionError,
    Venue,
    VenueCalendarModel,
    VenueCalendarValidationError,
)
from reference_data.calendars.market_state import (
    MarketInterruption,
    MarketState,
    MarketStatus,
    PriceLimitState,
    PriceLimitWindow,
    SessionOverride,
    SessionOverrideAction,
)
from reference_data.calendars.sessions import CalendarClosure, TradingSession
from reference_data.calendars.settlement import SettlementCalendar


class VenueCalendarSnapshot(VenueCalendarModel):
    """Hold one immutable, bounded projection of venue and settlement state.

    Coverage bounds are inclusive session-label dates, not instant boundaries.
    When no session contains a queried instant, only a gap bounded by retained
    sessions establishes CLOSED. Instants before the first session or at/after
    the final close are unknown, including every instant in an empty snapshot.
    Recorded overnight sessions remain queryable outside the label-date bounds.
    Construction validates supplied records; it does not fetch source data or
    apply overrides. Optional settlement coverage is checked by that calendar
    independently and need not equal trading coverage.

    Attributes:
        venue: Validated venue identity and timezone.
        version: Validated source, adapter, authority and optional override attribution.
        covered_from: Inclusive first covered session-label date.
        covered_through: Inclusive last covered session-label date.
        sessions: Owned sessions ordered by opening instant, with unique labels and no
            overlap.
        applied_overrides: Owned instructions with unique IDs and labels, matching resulting
            sessions.
        closures: Owned closures in strictly increasing date order, disjoint from session
            labels.
        interruptions: Owned halts with unique IDs, ordered and non-overlapping within one
            session each.
        price_limits: Owned limit windows with unique IDs, ordered and non-overlapping
            within one session each.
        settlement_calendar: Optional independently bounded settlement calendar.
    """

    venue: Venue
    version: CalendarSourceVersion
    covered_from: date
    covered_through: date
    sessions: tuple[TradingSession, ...]
    applied_overrides: tuple[SessionOverride, ...] = ()
    closures: tuple[CalendarClosure, ...] = ()
    interruptions: tuple[MarketInterruption, ...] = ()
    price_limits: tuple[PriceLimitWindow, ...] = ()
    settlement_calendar: SettlementCalendar | None = None

    @staticmethod
    def _session_sort_key(session: TradingSession) -> tuple[datetime, date]:
        """Return the explicit ordering key for one owned trading session."""
        return session.opens_at, session.session_label

    @staticmethod
    def _session_opening_time(session: TradingSession) -> datetime:
        """Return one owned session's UTC opening instant for indexed lookup."""
        return session.opens_at

    @field_validator("venue", "version", "settlement_calendar", mode="before")
    @classmethod
    def typed_snapshot_values(cls, value: object, info: ValidationInfo[object]) -> object:
        """Keep raw nested mappings outside the canonical snapshot boundary.

        Args:
            value: Owned Venue, CalendarSourceVersion or SettlementCalendar; only the latter
                admits None.
            info: Pydantic metadata identifying venue, version or settlement_calendar.

        Returns:
            The original owned value or admitted None for subsequent validation.

        Raises:
            VenueCalendarValidationError: The value does not have the owned type required by the
                selected field.
        """
        if info.field_name == "settlement_calendar" and value is None:
            return None
        expected_types = {
            "venue": Venue,
            "version": CalendarSourceVersion,
            "settlement_calendar": SettlementCalendar,
        }
        expected_type = expected_types[str(info.field_name)]
        if not isinstance(value, expected_type):
            raise VenueCalendarValidationError(
                f"{info.field_name} must be a {expected_type.__name__}"
            )
        return value

    @field_validator(
        "sessions", "applied_overrides", "closures", "interruptions", "price_limits", mode="before"
    )
    @classmethod
    def typed_snapshot_sequences(cls, value: object, info: ValidationInfo[object]) -> object:
        """Require immutable sequences of owned records before nested validation.

        Args:
            value: Tuple of the owned record type selected by the field; empty tuples are
                admitted.
            info: Pydantic metadata identifying sessions, applied_overrides, closures,
                interruptions or price_limits.

        Returns:
            The original tuple for subsequent nested and cross-record validation.

        Raises:
            VenueCalendarValidationError: The value is not a tuple or contains an item of the
                wrong owned type.
        """
        expected_types = {
            "sessions": TradingSession,
            "applied_overrides": SessionOverride,
            "closures": CalendarClosure,
            "interruptions": MarketInterruption,
            "price_limits": PriceLimitWindow,
        }
        expected_type = expected_types[str(info.field_name)]
        if not isinstance(value, tuple) or not all(
            isinstance(item, expected_type) for item in value
        ):
            raise VenueCalendarValidationError(
                f"{info.field_name} must be an immutable tuple of {expected_type.__name__} values"
            )
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate the complete immutable snapshot before publication.

        Raises:
            VenueCalendarValidationError: Owned types, coverage, session ordering,
                closure/override consistency, attribution or overlay containment is invalid.
        """
        if not isinstance(self.venue, Venue):
            raise VenueCalendarValidationError("venue must be a Venue")
        if not isinstance(self.version, CalendarSourceVersion):
            raise VenueCalendarValidationError("version must be a CalendarSourceVersion")
        covered_from = VenueCalendarModel._require_date(
            self.covered_from, field_name="covered_from"
        )
        covered_through = VenueCalendarModel._require_date(
            self.covered_through, field_name="covered_through"
        )
        if covered_through < covered_from:
            raise VenueCalendarValidationError("covered_through cannot precede covered_from")
        self._validate_sessions(covered_from, covered_through)
        self._validate_overrides(covered_from, covered_through)
        self._validate_closures(covered_from, covered_through)
        self._validate_intervals()
        if self.settlement_calendar is not None and not isinstance(
            self.settlement_calendar, SettlementCalendar
        ):
            raise VenueCalendarValidationError("settlement_calendar must be a SettlementCalendar")

    def _validate_sessions(self, covered_from: date, covered_through: date) -> None:
        """Reject unordered, overlapping or duplicate-label sessions and labels outside coverage."""
        if not isinstance(self.sessions, tuple) or not all(
            isinstance(session, TradingSession) for session in self.sessions
        ):
            raise VenueCalendarValidationError(
                "sessions must be an immutable tuple of TradingSession values"
            )
        ordered = tuple(sorted(self.sessions, key=self._session_sort_key))
        if ordered != self.sessions:
            raise VenueCalendarValidationError("sessions must be ordered by opening instant")
        labels = tuple(session.session_label for session in self.sessions)
        if len(set(labels)) != len(labels):
            raise VenueCalendarValidationError("session labels must be unique")
        if any(not covered_from <= label <= covered_through for label in labels):
            raise VenueCalendarValidationError("session label lies outside snapshot coverage")
        for earlier, later in zip(self.sessions, self.sessions[1:]):
            if later.opens_at < earlier.closes_at:
                raise VenueCalendarValidationError("trading sessions cannot overlap")

    def _validate_overrides(self, covered_from: date, covered_through: date) -> None:
        """Check unique covered overrides, version attribution and their resulting session state."""
        if not isinstance(self.applied_overrides, tuple) or not all(
            isinstance(override, SessionOverride) for override in self.applied_overrides
        ):
            raise VenueCalendarValidationError(
                "applied_overrides must be an immutable tuple of SessionOverride values"
            )
        override_ids = tuple(override.override_id for override in self.applied_overrides)
        override_labels = tuple(override.session_label for override in self.applied_overrides)
        if len(set(override_ids)) != len(override_ids):
            raise VenueCalendarValidationError("applied override IDs must be unique")
        if len(set(override_labels)) != len(override_labels):
            raise VenueCalendarValidationError(
                "only one applied override may target a label in a snapshot"
            )
        if any(not covered_from <= label <= covered_through for label in override_labels):
            raise VenueCalendarValidationError("applied override lies outside snapshot coverage")
        if self.applied_overrides and self.version.override_revision is None:
            raise VenueCalendarValidationError(
                "applied overrides require an attributed override source and revision"
            )
        sessions_by_label = {session.session_label: session for session in self.sessions}
        for override in self.applied_overrides:
            if (
                override.source != self.version.override_source
                or override.source_revision != self.version.override_revision
            ):
                raise VenueCalendarValidationError(
                    "applied override attribution must match the calendar version"
                )
            resulting_session = sessions_by_label.get(override.session_label)
            if override.action is SessionOverrideAction.REMOVE:
                if resulting_session is not None:
                    raise VenueCalendarValidationError(
                        "applied REMOVE override must leave its session absent"
                    )
            elif resulting_session != override.replacement:
                raise VenueCalendarValidationError(
                    "applied ADD or REPLACE override must match its resulting session"
                )

    def _validate_closures(self, covered_from: date, covered_through: date) -> None:
        """Check unique sorted covered closure dates without colliding session labels."""
        if not isinstance(self.closures, tuple) or not all(
            isinstance(closure, CalendarClosure) for closure in self.closures
        ):
            raise VenueCalendarValidationError(
                "closures must be an immutable tuple of CalendarClosure values"
            )
        closure_dates = tuple(closure.calendar_date for closure in self.closures)
        if tuple(sorted(closure_dates)) != closure_dates or len(set(closure_dates)) != len(
            closure_dates
        ):
            raise VenueCalendarValidationError(
                "closure dates must be unique and strictly increasing"
            )
        session_labels = {session.session_label for session in self.sessions}
        if any(item in session_labels for item in closure_dates):
            raise VenueCalendarValidationError("a closure date cannot also be a session")
        if any(not covered_from <= item <= covered_through for item in closure_dates):
            raise VenueCalendarValidationError("closure date lies outside snapshot coverage")

    def _validate_intervals(self) -> None:
        """Check unique, ordered, non-overlapping halts and limits within single sessions."""
        if not isinstance(self.interruptions, tuple) or not all(
            isinstance(item, MarketInterruption) for item in self.interruptions
        ):
            raise VenueCalendarValidationError(
                "interruptions must be an immutable tuple of MarketInterruption values"
            )
        if not isinstance(self.price_limits, tuple) or not all(
            isinstance(item, PriceLimitWindow) for item in self.price_limits
        ):
            raise VenueCalendarValidationError(
                "price_limits must be an immutable tuple of PriceLimitWindow values"
            )
        for label, windows in (
            ("interruptions", self.interruptions),
            ("price_limits", self.price_limits),
        ):
            window_ids = tuple(
                window.interruption_id
                if isinstance(window, MarketInterruption)
                else window.limit_id
                for window in windows
            )
            if len(set(window_ids)) != len(window_ids):
                raise VenueCalendarValidationError(f"{label} IDs must be unique")
            prior_end: datetime | None = None
            for window in windows:
                starts_at = window.starts_at
                ends_at = window.ends_at
                if prior_end is not None and starts_at < prior_end:
                    raise VenueCalendarValidationError(
                        f"{label} must be ordered and non-overlapping"
                    )
                containing_sessions = tuple(
                    session
                    for session in self.sessions
                    if session.opens_at <= starts_at < ends_at <= session.closes_at
                )
                if len(containing_sessions) != 1:
                    raise VenueCalendarValidationError(
                        f"{label} interval must lie inside exactly one session"
                    )
                prior_end = ends_at

    def session_for_label(self, session_label: date) -> TradingSession:
        """Return one exact session label or fail closed.

        Args:
            session_label: Exact date label to find; datetimes are rejected.

        Returns:
            The recorded session with that label, without next-session adjustment.

        Raises:
            VenueCalendarValidationError: The label is not a date or is a datetime.
            UnknownSessionError: No session has the label, whether inside or outside snapshot
                coverage.
        """
        checked = VenueCalendarModel._require_date(session_label, field_name="session_label")
        for session in self.sessions:
            if session.session_label == checked:
                return session
        raise UnknownSessionError(f"unknown session label {checked.isoformat()}")

    def closure_for_date(self, calendar_date: date) -> CalendarClosure | None:
        """Return an attributed closure when one is recorded.

        Args:
            calendar_date: Date within inclusive snapshot coverage; datetimes are rejected.

        Returns:
            The recorded closure, or None for a covered date without one. Absence does not
            establish that the date is a session.

        Raises:
            VenueCalendarValidationError: The candidate is not a date or is a datetime.
            CalendarCoverageError: The date lies outside snapshot coverage.
        """
        checked = VenueCalendarModel._require_date(calendar_date, field_name="calendar_date")
        if not self.covered_from <= checked <= self.covered_through:
            raise CalendarCoverageError(
                f"calendar date {checked.isoformat()} is outside snapshot coverage"
            )
        for closure in self.closures:
            if closure.calendar_date == checked:
                return closure
        return None

    def market_state_at(self, instant: datetime) -> MarketState:
        """Resolve deterministic venue state at an explicit UTC instant.

        Containing sessions include their portions crossing midnight. Only gaps
        between retained sessions establish CLOSED; label-date coverage alone
        cannot exclude an omitted overnight session at either edge. Session close
        and each overlay end are exclusive; auctions take precedence over breaks.

        Args:
            instant: Aware datetime with zero UTC offset, tested against half-open session and
                overlay intervals.

        Returns:
            HALTED, AUCTION, BREAK or CONTINUOUS in that precedence order within a session, with
            an independent price-limit state; CLOSED with no limit in gaps bounded by retained
            sessions.

        Raises:
            VenueCalendarValidationError: The instant is not an aware datetime with a zero UTC
                offset.
            CalendarCoverageError: The instant is neither inside a retained session nor in a
                gap between retained sessions.
        """
        checked = VenueCalendarModel._require_utc_datetime(instant, field_name="instant")
        session_index = bisect_right(self.sessions, checked, key=self._session_opening_time) - 1
        session = self.sessions[session_index] if session_index >= 0 else None
        if session is None or not session.contains(checked):
            if session is None or session_index + 1 == len(self.sessions):
                raise CalendarCoverageError(
                    f"instant {checked.isoformat()} is outside snapshot coverage for market state"
                )
            return MarketState(
                status=MarketStatus.CLOSED,
                price_limit_state=PriceLimitState.NONE,
            )
        limit_state = PriceLimitState.NONE
        for limit_window in self.price_limits:
            if limit_window.contains(checked):
                limit_state = limit_window.state
                break
        for interruption in self.interruptions:
            if interruption.contains(checked):
                return MarketState(
                    status=MarketStatus.HALTED,
                    price_limit_state=limit_state,
                    session_label=session.session_label,
                    interruption_id=interruption.interruption_id,
                )
        for auction in session.auctions:
            if auction.contains(checked):
                return MarketState(
                    status=MarketStatus.AUCTION,
                    price_limit_state=limit_state,
                    session_label=session.session_label,
                    auction_kind=auction.kind,
                )
        if (
            session.break_starts_at is not None
            and session.break_ends_at is not None
            and session.break_starts_at <= checked < session.break_ends_at
        ):
            return MarketState(
                status=MarketStatus.BREAK,
                price_limit_state=limit_state,
                session_label=session.session_label,
            )
        return MarketState(
            status=MarketStatus.CONTINUOUS,
            price_limit_state=limit_state,
            session_label=session.session_label,
        )
