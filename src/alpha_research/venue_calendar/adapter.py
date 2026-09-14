"""Adapt the pinned exchange-calendars source into owned C02 values."""

from __future__ import annotations

# standard library imports
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from typing import Protocol, runtime_checkable

# third party library imports
import exchange_calendars as _exchange_calendars
import pandas as _pandas
from exchange_calendars.errors import (
    CalendarError as _ExchangeCalendarError,
)
from exchange_calendars.errors import (
    NoSessionsError as _NoSessionsError,
)

# project library imports
from alpha_research.venue_calendar.models import (
    CalendarClosure,
    CalendarSourceVersion,
    MarketInterruption,
    PriceLimitWindow,
    SessionKind,
    SessionOverride,
    SessionOverrideAction,
    SettlementCalendar,
    TradingSession,
    Venue,
    VenueCalendarError,
    VenueCalendarSnapshot,
    VenueCalendarValidationError,
)

EXCHANGE_CALENDARS_DISTRIBUTION = "exchange-calendars"
EXCHANGE_CALENDARS_VERSION = "4.13.2"


class CalendarAdapterError(VenueCalendarError):
    """Report source-library, compatibility, or override adapter failure."""


class IncompatibleCalendarLibraryError(CalendarAdapterError):
    """Report an installed source-library version outside the C02 contract."""


class _ExchangeCalendar(Protocol):
    """Describe the third-party schedule surface consumed by C02."""

    @property
    def name(self) -> str:
        """Return the source calendar's canonical name."""
        ...

    @property
    def tz(self) -> object:
        """Return the source calendar's timezone value for owned validation."""
        ...

    @property
    def sessions(self) -> Iterable[object]:
        """Return source session labels."""
        ...

    @property
    def early_closes(self) -> Iterable[object]:
        """Return source early-close labels."""
        ...

    def session_open(self, session: date) -> object:
        """Return the source opening timestamp for an eligible session label."""
        ...

    def session_close(self, session: date) -> object:
        """Return the source closing timestamp for an eligible session label."""
        ...

    def session_break_start(self, session: date) -> object:
        """Return the source break start or its missing-break sentinel."""
        ...

    def session_break_end(self, session: date) -> object:
        """Return the source break end or its missing-break sentinel."""
        ...


@runtime_checkable
class _TimestampConverter(Protocol):
    """Describe a validated source timestamp conversion callable."""

    def __call__(self) -> object:
        """Return the converted standard-library value."""
        ...


class ExchangeCalendarsAdapter:
    """Build bounded owned snapshots from exactly exchange-calendars 4.13.2."""

    @staticmethod
    def _has_exchange_calendar_surface(candidate: object) -> bool:
        """Check that a source object exposes the consumed schedule members."""
        required_members = (
            "name",
            "tz",
            "sessions",
            "early_closes",
            "session_open",
            "session_close",
            "session_break_start",
            "session_break_end",
        )
        return all(hasattr(candidate, member) for member in required_members)

    def _load_calendar(self, *, calendar_name: str, start: date, end: date) -> _ExchangeCalendar:
        """Load and validate the pinned source calendar schedule surface.

        The source constructor may extend the end date to find a session in an
        empty interval. Snapshot construction later filters labels to the original
        inclusive bounds. Aliases are resolved here; callers verify the resolved
        name and timezone against the requested venue.
        """
        if ExchangeCalendarsAdapter._calendar_library_version() != EXCHANGE_CALENDARS_VERSION:
            raise IncompatibleCalendarLibraryError(
                f"{EXCHANGE_CALENDARS_DISTRIBUTION} must be exactly {EXCHANGE_CALENDARS_VERSION}"
            )
        if (
            not isinstance(calendar_name, str)
            or not calendar_name
            or calendar_name != calendar_name.strip()
            or len(calendar_name) > 32
        ):
            raise VenueCalendarValidationError("calendar_name must be a bounded exact source name")
        try:
            constructor_end = end + timedelta(days=1) if start == end else end
            try:
                candidate = _exchange_calendars.get_calendar(
                    calendar_name,
                    start=start,
                    end=constructor_end,
                    side="left",
                )
            except _NoSessionsError:
                candidate = _exchange_calendars.get_calendar(
                    calendar_name,
                    start=start,
                    end=end + timedelta(days=31),
                    side="left",
                )
        except (_ExchangeCalendarError, KeyError, TypeError, ValueError, OverflowError) as error:
            raise CalendarAdapterError(
                f"cannot load calendar {calendar_name!r} for {start.isoformat()} "
                f"through {end.isoformat()}"
            ) from error
        if not self._has_exchange_calendar_surface(candidate):
            raise CalendarAdapterError(
                "calendar source does not expose the required schedule surface"
            )
        return candidate

    def _adapt_session(
        self, calendar: _ExchangeCalendar, *, session_label: date, kind: SessionKind
    ) -> TradingSession:
        """Query and validate one source session as an owned UTC record."""
        try:
            source_open = calendar.session_open(session_label)
            source_close = calendar.session_close(session_label)
            source_break_start = calendar.session_break_start(session_label)
            source_break_end = calendar.session_break_end(session_label)
        except (_ExchangeCalendarError, KeyError, TypeError, ValueError) as error:
            raise CalendarAdapterError(
                f"calendar source failed to query session {session_label.isoformat()}"
            ) from error
        return TradingSession(
            session_label=session_label,
            opens_at=ExchangeCalendarsAdapter._required_utc_datetime(
                source_open, field_name="session open"
            ),
            closes_at=ExchangeCalendarsAdapter._required_utc_datetime(
                source_close, field_name="session close"
            ),
            kind=kind,
            break_starts_at=ExchangeCalendarsAdapter._as_utc_datetime(
                source_break_start, field_name="session break start", optional=True
            ),
            break_ends_at=ExchangeCalendarsAdapter._as_utc_datetime(
                source_break_end, field_name="session break end", optional=True
            ),
        )

    def _adapt_sessions(
        self,
        calendar: _ExchangeCalendar,
        *,
        start: date,
        end: date,
    ) -> tuple[TradingSession, ...]:
        """Adapt source labels in the requested inclusive range."""
        early_close_labels = {
            ExchangeCalendarsAdapter._as_date(item, field_name="early-close label")
            for item in calendar.early_closes
        }
        base_sessions: list[TradingSession] = []
        for raw_label in calendar.sessions:
            session_label = ExchangeCalendarsAdapter._as_date(raw_label, field_name="session label")
            if session_label < start or session_label > end:
                continue
            base_sessions.append(
                self._adapt_session(
                    calendar,
                    session_label=session_label,
                    kind=(
                        SessionKind.HALF_DAY
                        if session_label in early_close_labels
                        else SessionKind.REGULAR
                    ),
                )
            )
        return tuple(base_sessions)

    def _apply_overrides(
        self,
        base_sessions: tuple[TradingSession, ...],
        overrides: tuple[SessionOverride, ...],
    ) -> tuple[TradingSession, ...]:
        """Apply unique add, replace, or remove instructions to copied sessions."""
        sessions_by_label = {session.session_label: session for session in base_sessions}
        if len(sessions_by_label) != len(base_sessions):
            raise CalendarAdapterError("calendar source session labels must be unique")
        seen_override_ids: set[str] = set()
        seen_labels: set[date] = set()
        for override in overrides:
            if not isinstance(override, SessionOverride):
                raise VenueCalendarValidationError(
                    "overrides must be an immutable tuple of SessionOverride values"
                )
            if override.override_id in seen_override_ids:
                raise VenueCalendarValidationError("session override IDs must be unique")
            if override.session_label in seen_labels:
                raise VenueCalendarValidationError(
                    "only one session override may target a label in a snapshot"
                )
            seen_override_ids.add(override.override_id)
            seen_labels.add(override.session_label)
            exists = override.session_label in sessions_by_label
            if override.action is SessionOverrideAction.ADD:
                if exists:
                    raise VenueCalendarValidationError(
                        "ADD override requires an absent base session"
                    )
                replacement = override.replacement
                if replacement is None:
                    raise VenueCalendarValidationError("ADD override requires a replacement")
                sessions_by_label[override.session_label] = replacement
            elif override.action is SessionOverrideAction.REPLACE:
                if not exists:
                    raise VenueCalendarValidationError(
                        "REPLACE override requires an existing base session"
                    )
                replacement = override.replacement
                if replacement is None:
                    raise VenueCalendarValidationError("REPLACE override requires a replacement")
                sessions_by_label[override.session_label] = replacement
            else:
                if not exists:
                    raise VenueCalendarValidationError(
                        "REMOVE override requires an existing base session"
                    )
                del sessions_by_label[override.session_label]
        return self._sort_sessions(sessions_by_label.values())

    @staticmethod
    def _session_sort_key(item: TradingSession) -> tuple[datetime, date]:
        """Return the stable opening-instant and label ordering for a session."""
        return item.opens_at, item.session_label

    @classmethod
    def _sort_sessions(cls, sessions: Iterable[TradingSession]) -> tuple[TradingSession, ...]:
        """Return sessions ordered by opening instant and then session label."""
        return tuple(sorted(sessions, key=cls._session_sort_key))

    def build_snapshot(
        self,
        *,
        venue: Venue,
        calendar_name: str,
        version: CalendarSourceVersion,
        start: date,
        end: date,
        overrides: tuple[SessionOverride, ...] = (),
        closures: tuple[CalendarClosure, ...] = (),
        interruptions: tuple[MarketInterruption, ...] = (),
        price_limits: tuple[PriceLimitWindow, ...] = (),
        settlement_calendar: SettlementCalendar | None = None,
    ) -> VenueCalendarSnapshot:
        """Adapt an explicit bounded source range without using host-local time.

        Read the installed library's metadata and schedule, convert session times
        to UTC, apply the supplied overrides, and validate a new owned snapshot.
        No files are written and no network requests are made by this adapter.
        Source construction may populate the third-party library's calendar cache.

        Args:
            venue: Owned venue whose IANA timezone must match the source calendar.
            calendar_name: Exact nonempty source name, at most 32 characters without
                surrounding whitespace; aliases resolving to another name fail.
            version: Attribution naming exchange_calendars as adapter and base source,
                both at the pinned version, plus override attribution when used.
            start: Inclusive first session-label date; datetimes are rejected.
            end: Inclusive last session-label date, on or after ``start``.
            overrides: Immutable add, replace, or remove instructions with unique IDs
                and labels, whose source and revision match ``version``.
            closures: Explicit closure assertions retained and checked against sessions.
            interruptions: Explicit halt or pause windows retained in the snapshot;
                the base schedule does not infer them.
            price_limits: Explicit price-limit windows retained in the snapshot;
                the base schedule does not infer them.
            settlement_calendar: Optional independently attributed settlement schedule;
                trading sessions are not used to infer settlement eligibility.

        Returns:
            A validated snapshot with the requested inclusive date coverage and UTC
            sessions, including early-close classifications and any supplied overlays.
            An interval without sessions can produce a valid empty schedule.

        Raises:
            VenueCalendarValidationError: Arguments, attribution, override actions,
                or the assembled snapshot violate owned model invariants.
            IncompatibleCalendarLibraryError: The installed calendar distribution
                is missing or differs from the pinned version.
            CalendarAdapterError: Source loading or session queries fail, required
                source members or timestamp shapes are invalid, the resolved name
                or timezone differs, or source session labels are duplicated.
        """
        if not isinstance(venue, Venue):
            raise VenueCalendarValidationError("venue must be a Venue")
        if not isinstance(version, CalendarSourceVersion):
            raise VenueCalendarValidationError("version must be a CalendarSourceVersion")
        if not isinstance(start, date) or isinstance(start, datetime):
            raise VenueCalendarValidationError("start must be a date")
        if not isinstance(end, date) or isinstance(end, datetime):
            raise VenueCalendarValidationError("end must be a date")
        if end < start:
            raise VenueCalendarValidationError("end cannot precede start")
        if version.adapter_name != "exchange_calendars":
            raise VenueCalendarValidationError(
                "calendar version adapter_name must be exchange_calendars"
            )
        if version.base_source != "exchange_calendars":
            raise VenueCalendarValidationError(
                "calendar version base_source must be exchange_calendars"
            )
        if version.base_source_revision != EXCHANGE_CALENDARS_VERSION:
            raise VenueCalendarValidationError(
                f"calendar base_source_revision must be {EXCHANGE_CALENDARS_VERSION}"
            )
        if version.adapter_version != EXCHANGE_CALENDARS_VERSION:
            raise VenueCalendarValidationError(
                f"calendar version adapter_version must be {EXCHANGE_CALENDARS_VERSION}"
            )
        if not isinstance(overrides, tuple) or not all(
            isinstance(override, SessionOverride) for override in overrides
        ):
            raise VenueCalendarValidationError(
                "overrides must be an immutable tuple of SessionOverride values"
            )
        if overrides and version.override_revision is None:
            raise VenueCalendarValidationError(
                "calendar overrides require an attributed override source and revision"
            )
        if any(
            override.source != version.override_source
            or override.source_revision != version.override_revision
            for override in overrides
        ):
            raise VenueCalendarValidationError(
                "calendar override attribution must match the calendar version"
            )
        calendar = self._load_calendar(calendar_name=calendar_name, start=start, end=end)
        if calendar.name != calendar_name:
            raise CalendarAdapterError(
                f"calendar source resolved {calendar_name!r} as unexpected {calendar.name!r}"
            )
        if str(calendar.tz) != venue.timezone_name:
            raise CalendarAdapterError(
                f"calendar timezone {calendar.tz!s} does not match venue timezone "
                f"{venue.timezone_name!r}"
            )
        base_sessions = self._adapt_sessions(calendar, start=start, end=end)
        adapted_sessions = self._apply_overrides(base_sessions, overrides)
        return VenueCalendarSnapshot(
            venue=venue,
            version=version,
            covered_from=start,
            covered_through=end,
            sessions=adapted_sessions,
            applied_overrides=overrides,
            closures=closures,
            interruptions=interruptions,
            price_limits=price_limits,
            settlement_calendar=settlement_calendar,
        )

    @staticmethod
    def _calendar_library_version() -> str:
        """Read the installed calendar distribution metadata."""
        try:
            return installed_version(EXCHANGE_CALENDARS_DISTRIBUTION)
        except PackageNotFoundError as error:
            raise IncompatibleCalendarLibraryError(
                f"{EXCHANGE_CALENDARS_DISTRIBUTION} is not installed"
            ) from error

    @staticmethod
    def _as_date(candidate: object, *, field_name: str) -> date:
        """Extract a source session label's date without applying timezone conversion."""
        if isinstance(candidate, datetime):
            return candidate.date()
        if isinstance(candidate, date):
            return candidate
        to_datetime: object = getattr(candidate, "to_pydatetime", None)
        if isinstance(to_datetime, _TimestampConverter) and callable(to_datetime):
            converted = to_datetime()
        else:
            converted = None
        if isinstance(converted, datetime):
            return converted.date()
        raise CalendarAdapterError(f"calendar source returned invalid {field_name}")

    @staticmethod
    def _as_utc_datetime(
        candidate: object, *, field_name: str, optional: bool = False
    ) -> datetime | None:
        """Normalize aware source timestamps to UTC, allowing None or NaT only if optional."""
        if optional and (candidate is None or candidate is _pandas.NaT):
            return None
        converted: object = candidate
        to_datetime: object = getattr(candidate, "to_pydatetime", None)
        if isinstance(to_datetime, _TimestampConverter) and callable(to_datetime):
            converted = to_datetime()
        if isinstance(converted, datetime) and converted.tzinfo is not None:
            try:
                return converted.astimezone(UTC)
            except (OSError, OverflowError, ValueError) as error:
                raise CalendarAdapterError(
                    f"calendar source returned invalid {field_name}"
                ) from error
        raise CalendarAdapterError(f"calendar source returned invalid {field_name}")

    @staticmethod
    def _required_utc_datetime(candidate: object, *, field_name: str) -> datetime:
        """Normalize one mandatory aware timestamp to UTC or raise CalendarAdapterError."""
        converted = ExchangeCalendarsAdapter._as_utc_datetime(candidate, field_name=field_name)
        if converted is None:
            raise CalendarAdapterError(f"calendar source returned invalid {field_name}")
        return converted
