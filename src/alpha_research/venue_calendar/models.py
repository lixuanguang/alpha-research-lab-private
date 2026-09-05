"""Define immutable C02 venue, calendar, session, and market-state values."""

from __future__ import annotations

# standard library imports
import re
import unicodedata
from bisect import bisect_right
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# third party library imports
from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, field_validator


class VenueCalendarError(ValueError):
    """Base class for deterministic venue-calendar failures."""


class VenueCalendarValidationError(VenueCalendarError):
    """Report invalid canonical venue or calendar state."""


class UnknownSessionError(VenueCalendarError):
    """Report a requested session label outside the snapshot."""


class UnknownSettlementDateError(VenueCalendarError):
    """Report an unavailable settlement date inside a bounded snapshot."""


class CalendarCoverageError(VenueCalendarError):
    """Report a query that lies outside explicit snapshot coverage."""


def _validation_error_message(error: ValidationError) -> str:
    messages: list[str] = []
    for detail in error.errors(include_input=False, include_url=False):
        context = detail.get("ctx")
        cause = context.get("error") if isinstance(context, dict) else None
        if isinstance(cause, VenueCalendarValidationError):
            messages.append(str(cause))
            continue
        location = ".".join(str(component) for component in detail["loc"])
        message = str(detail["msg"]).removeprefix("Value error, ")
        messages.append(f"{location}: {message}" if location else message)
    return "\n".join(messages)


class _VenueCalendarModel(BaseModel):
    """Preserve strict immutable value semantics at the C02 boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
        strict=True,
        validate_default=True,
    )

    def __init__(self, **data: object) -> None:
        try:
            super().__init__(**data)
        except ValidationError as error:
            raise VenueCalendarValidationError(_validation_error_message(error)) from error


_STABLE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")
_MIC_PATTERN = re.compile(r"^[A-Z0-9]{4}$")


def _require_bounded_text(candidate: object, *, field_name: str, maximum_length: int) -> str:
    if not isinstance(candidate, str) or not candidate or candidate != candidate.strip():
        raise VenueCalendarValidationError(
            f"{field_name} must be non-empty without surrounding whitespace"
        )
    if len(candidate) > maximum_length:
        raise VenueCalendarValidationError(
            f"{field_name} exceeds the {maximum_length}-character limit"
        )
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in candidate):
        raise VenueCalendarValidationError(f"{field_name} contains a control character")
    return candidate


def _require_stable_token(candidate: object, *, field_name: str) -> str:
    identifier_text = _require_bounded_text(candidate, field_name=field_name, maximum_length=128)
    if _STABLE_TOKEN_PATTERN.fullmatch(identifier_text) is None:
        raise VenueCalendarValidationError(f"{field_name} must be a stable token")
    return identifier_text


def require_utc_datetime(candidate: object, *, field_name: str) -> datetime:
    """Require an aware UTC instant without consulting host-local timezone state."""
    if not isinstance(candidate, datetime) or candidate.tzinfo is None:
        raise VenueCalendarValidationError(f"{field_name} must be timezone-aware UTC")
    if candidate.utcoffset() != timedelta(0):
        raise VenueCalendarValidationError(f"{field_name} must use UTC")
    return candidate


def _require_date(candidate: object, *, field_name: str) -> date:
    if not isinstance(candidate, date) or isinstance(candidate, datetime):
        raise VenueCalendarValidationError(f"{field_name} must be a date")
    return candidate


def _require_timezone_name(candidate: object, *, field_name: str) -> str:
    timezone_name = _require_bounded_text(candidate, field_name=field_name, maximum_length=128)
    try:
        ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise VenueCalendarValidationError(
            f"{field_name} must name an available IANA timezone"
        ) from error
    return timezone_name


def _require_non_nil_uuid(candidate: object, *, field_name: str) -> UUID:
    if not isinstance(candidate, UUID) or candidate.int == 0:
        raise VenueCalendarValidationError(f"{field_name} must be a non-nil UUID")
    return candidate


class VenueId(_VenueCalendarModel):
    """Hold one opaque repository-issued stable venue identifier."""

    uuid_value: UUID

    def model_post_init(self, _context: object, /) -> None:
        """Validate the opaque identity after strict field validation."""
        _require_non_nil_uuid(self.uuid_value, field_name="venue_id")

    @classmethod
    def from_canonical_text(cls, value: str) -> VenueId:
        """Parse the canonical lower-case UUID representation."""
        if not isinstance(value, str):
            raise VenueCalendarValidationError("venue_id must be a UUID string")
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise VenueCalendarValidationError("venue_id must be a canonical UUID") from error
        if str(parsed) != value:
            raise VenueCalendarValidationError("venue_id must be a canonical UUID")
        return cls(uuid_value=parsed)

    def __str__(self) -> str:
        return str(self.uuid_value)


class MarketIdentifierCode(_VenueCalendarModel):
    """Represent one exact ISO 10383 MIC-shaped identifier."""

    value: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate the exact MIC shape without normalization."""
        if not isinstance(self.value, str) or _MIC_PATTERN.fullmatch(self.value) is None:
            raise VenueCalendarValidationError(
                "market_identifier_code must contain four uppercase ASCII letters or digits"
            )

    def __str__(self) -> str:
        return self.value


class Venue(_VenueCalendarModel):
    """Bind one stable venue identity to exact MIC and timezone metadata."""

    venue_id: VenueId
    mic: MarketIdentifierCode
    operating_mic: MarketIdentifierCode
    name: str
    timezone_name: str

    @field_validator("venue_id", "mic", "operating_mic", mode="before")
    @classmethod
    def typed_identity_fields(cls, value: object, info: ValidationInfo) -> object:
        """Require owned identity values rather than coercing nested mappings."""
        expected_type = VenueId if info.field_name == "venue_id" else MarketIdentifierCode
        if not isinstance(value, expected_type):
            raise VenueCalendarValidationError(
                f"{info.field_name} must be a {expected_type.__name__}"
            )
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate owned venue metadata after strict field validation."""
        if not isinstance(self.venue_id, VenueId):
            raise VenueCalendarValidationError("venue_id must be a VenueId")
        if not isinstance(self.mic, MarketIdentifierCode):
            raise VenueCalendarValidationError("mic must be a MarketIdentifierCode")
        if not isinstance(self.operating_mic, MarketIdentifierCode):
            raise VenueCalendarValidationError("operating_mic must be a MarketIdentifierCode")
        _require_bounded_text(self.name, field_name="venue name", maximum_length=128)
        _require_timezone_name(self.timezone_name, field_name="venue timezone_name")

    def local_time(self, instant: datetime) -> datetime:
        """Convert an explicit UTC instant to the venue's IANA timezone."""
        return require_utc_datetime(instant, field_name="instant").astimezone(
            ZoneInfo(self.timezone_name)
        )


class CalendarAuthority(StrEnum):
    """Declare the bounded authority available to repository calendar snapshots."""

    REFERENCE_ONLY = "reference_only"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class CalendarSourceVersion(_VenueCalendarModel):
    """Identify a deterministic base source and optional override revision."""

    calendar_version: str
    base_source: str
    base_source_revision: str
    adapter_name: str
    adapter_version: str
    authority: CalendarAuthority
    override_source: str | None = None
    override_revision: str | None = None

    def model_post_init(self, _context: object, /) -> None:
        """Require exact source identity and paired override attribution."""
        _require_stable_token(self.calendar_version, field_name="calendar_version")
        _require_stable_token(self.base_source, field_name="base_source")
        _require_stable_token(self.base_source_revision, field_name="base_source_revision")
        _require_stable_token(self.adapter_name, field_name="adapter_name")
        _require_stable_token(self.adapter_version, field_name="adapter_version")
        if not isinstance(self.authority, CalendarAuthority):
            raise VenueCalendarValidationError("authority must be a CalendarAuthority")
        if (self.override_source is None) != (self.override_revision is None):
            raise VenueCalendarValidationError(
                "override_source and override_revision must be provided together"
            )
        if self.override_source is not None:
            _require_stable_token(self.override_source, field_name="override_source")
            _require_stable_token(self.override_revision, field_name="override_revision")


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


class AuctionWindow(_VenueCalendarModel):
    """Describe one half-open auction interval within a trading session."""

    kind: AuctionKind
    starts_at: datetime
    ends_at: datetime

    def model_post_init(self, _context: object, /) -> None:
        """Validate the non-empty UTC auction interval."""
        if not isinstance(self.kind, AuctionKind):
            raise VenueCalendarValidationError("auction kind must be an AuctionKind")
        start = require_utc_datetime(self.starts_at, field_name="auction starts_at")
        end = require_utc_datetime(self.ends_at, field_name="auction ends_at")
        if end <= start:
            raise VenueCalendarValidationError("auction ends_at must be after starts_at")

    def contains(self, instant: datetime) -> bool:
        """Return whether an explicit UTC instant lies in the half-open window."""
        checked = require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class TradingSession(_VenueCalendarModel):
    """Describe one venue session with optional break and auction windows."""

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
        """Require immutable owned auction values before nested validation."""
        if not isinstance(value, tuple) or not all(
            isinstance(auction, AuctionWindow) for auction in value
        ):
            raise VenueCalendarValidationError(
                "session auctions must be an immutable tuple of AuctionWindow values"
            )
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate ordered session, break, and auction boundaries."""
        _require_date(self.session_label, field_name="session_label")
        opens_at = require_utc_datetime(self.opens_at, field_name="session opens_at")
        closes_at = require_utc_datetime(self.closes_at, field_name="session closes_at")
        if closes_at <= opens_at:
            raise VenueCalendarValidationError("session closes_at must be after opens_at")
        if not isinstance(self.kind, SessionKind):
            raise VenueCalendarValidationError("session kind must be a SessionKind")
        if (self.break_starts_at is None) != (self.break_ends_at is None):
            raise VenueCalendarValidationError(
                "session break_starts_at and break_ends_at must be provided together"
            )
        if self.break_starts_at is not None and self.break_ends_at is not None:
            break_start = require_utc_datetime(
                self.break_starts_at, field_name="session break_starts_at"
            )
            break_end = require_utc_datetime(self.break_ends_at, field_name="session break_ends_at")
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
        """Return whether an explicit UTC instant lies in this half-open session."""
        checked = require_utc_datetime(instant, field_name="instant")
        return self.opens_at <= checked < self.closes_at


class ClosureKind(StrEnum):
    """Classify an explicitly attributed non-session date."""

    HOLIDAY = "holiday"
    AD_HOC = "ad_hoc"


class CalendarClosure(_VenueCalendarModel):
    """Name one source-attributed date on which no session exists."""

    calendar_date: date
    kind: ClosureKind
    name: str
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Require an attributed closure date and bounded description."""
        _require_date(self.calendar_date, field_name="calendar closure date")
        if not isinstance(self.kind, ClosureKind):
            raise VenueCalendarValidationError("closure kind must be a ClosureKind")
        _require_bounded_text(self.name, field_name="closure name", maximum_length=128)
        _require_stable_token(self.source, field_name="closure source")
        _require_stable_token(self.source_revision, field_name="closure source_revision")


class InterruptionKind(StrEnum):
    """Classify an explicitly supplied interruption of normal session state."""

    HALT = "halt"


class MarketInterruption(_VenueCalendarModel):
    """Represent one source-attributed half-open halt interval."""

    interruption_id: str
    kind: InterruptionKind
    starts_at: datetime
    ends_at: datetime
    reason: str
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate the halt interval and its source attribution."""
        _require_stable_token(self.interruption_id, field_name="interruption_id")
        if not isinstance(self.kind, InterruptionKind):
            raise VenueCalendarValidationError("interruption kind must be an InterruptionKind")
        start = require_utc_datetime(self.starts_at, field_name="interruption starts_at")
        end = require_utc_datetime(self.ends_at, field_name="interruption ends_at")
        if end <= start:
            raise VenueCalendarValidationError("interruption ends_at must be after starts_at")
        _require_bounded_text(self.reason, field_name="interruption reason", maximum_length=256)
        _require_stable_token(self.source, field_name="interruption source")
        _require_stable_token(self.source_revision, field_name="interruption source_revision")

    def contains(self, instant: datetime) -> bool:
        """Return whether an explicit UTC instant lies in the half-open interruption."""
        checked = require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class PriceLimitState(StrEnum):
    """Describe the explicit price-limit state observed for a venue."""

    NONE = "none"
    LIMIT_UP = "limit_up"
    LIMIT_DOWN = "limit_down"
    LOCKED = "locked"


class PriceLimitWindow(_VenueCalendarModel):
    """Represent one source-attributed half-open non-normal limit interval."""

    limit_id: str
    state: PriceLimitState
    starts_at: datetime
    ends_at: datetime
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Require a non-normal attributed price-limit interval."""
        _require_stable_token(self.limit_id, field_name="limit_id")
        if not isinstance(self.state, PriceLimitState) or self.state is PriceLimitState.NONE:
            raise VenueCalendarValidationError(
                "price-limit window state must be a non-NONE PriceLimitState"
            )
        start = require_utc_datetime(self.starts_at, field_name="price-limit starts_at")
        end = require_utc_datetime(self.ends_at, field_name="price-limit ends_at")
        if end <= start:
            raise VenueCalendarValidationError("price-limit ends_at must be after starts_at")
        _require_stable_token(self.source, field_name="price-limit source")
        _require_stable_token(self.source_revision, field_name="price-limit source_revision")

    def contains(self, instant: datetime) -> bool:
        """Return whether an explicit UTC instant lies in the half-open limit interval."""
        checked = require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class MarketStatus(StrEnum):
    """Describe the canonical schedule state at one instant."""

    CLOSED = "closed"
    AUCTION = "auction"
    CONTINUOUS = "continuous"
    BREAK = "break"
    HALTED = "halted"


class MarketState(_VenueCalendarModel):
    """Return schedule, auction, halt, and independent price-limit state together."""

    status: MarketStatus
    price_limit_state: PriceLimitState
    session_label: date | None = None
    auction_kind: AuctionKind | None = None
    interruption_id: str | None = None

    def model_post_init(self, _context: object, /) -> None:
        """Reject incoherent schedule, auction, halt, or limit state."""
        if not isinstance(self.status, MarketStatus):
            raise VenueCalendarValidationError("market state status must be a MarketStatus")
        if not isinstance(self.price_limit_state, PriceLimitState):
            raise VenueCalendarValidationError(
                "market state price_limit_state must be a PriceLimitState"
            )
        if self.session_label is not None:
            _require_date(self.session_label, field_name="market state session_label")
        if self.status is MarketStatus.CLOSED:
            if (
                self.session_label is not None
                or self.auction_kind is not None
                or self.interruption_id is not None
                or self.price_limit_state is not PriceLimitState.NONE
            ):
                raise VenueCalendarValidationError(
                    "closed market state cannot carry session, auction, halt, or limit state"
                )
            return
        if self.session_label is None:
            raise VenueCalendarValidationError("open market state requires a session_label")
        if (self.status is MarketStatus.AUCTION) != (self.auction_kind is not None):
            raise VenueCalendarValidationError(
                "auction_kind must be present exactly for AUCTION market state"
            )
        if self.auction_kind is not None and not isinstance(self.auction_kind, AuctionKind):
            raise VenueCalendarValidationError("auction_kind must be an AuctionKind")
        if (self.status is MarketStatus.HALTED) != (self.interruption_id is not None):
            raise VenueCalendarValidationError(
                "interruption_id must be present exactly for HALTED market state"
            )
        if self.interruption_id is not None:
            _require_stable_token(self.interruption_id, field_name="interruption_id")


class SessionOverrideAction(StrEnum):
    """Declare how an explicit override changes one base calendar label."""

    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class SessionOverride(_VenueCalendarModel):
    """Apply one source-attributed, versioned change to a base session."""

    override_id: str
    action: SessionOverrideAction
    session_label: date
    reason: str
    source: str
    source_revision: str
    replacement: TradingSession | None = None

    @field_validator("replacement", mode="before")
    @classmethod
    def typed_replacement(cls, value: object) -> object:
        """Require an owned replacement session when one is present."""
        if value is not None and not isinstance(value, TradingSession):
            raise VenueCalendarValidationError("replacement must be a TradingSession")
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate action, replacement label, and override attribution."""
        _require_stable_token(self.override_id, field_name="override_id")
        if not isinstance(self.action, SessionOverrideAction):
            raise VenueCalendarValidationError(
                "session override action must be a SessionOverrideAction"
            )
        _require_date(self.session_label, field_name="override session_label")
        _require_bounded_text(self.reason, field_name="override reason", maximum_length=256)
        _require_stable_token(self.source, field_name="override source")
        _require_stable_token(self.source_revision, field_name="override source_revision")
        if self.action is SessionOverrideAction.REMOVE:
            if self.replacement is not None:
                raise VenueCalendarValidationError(
                    "REMOVE session override cannot include a replacement"
                )
            return
        if not isinstance(self.replacement, TradingSession):
            raise VenueCalendarValidationError(
                "ADD and REPLACE session overrides require a TradingSession replacement"
            )
        if self.replacement.session_label != self.session_label:
            raise VenueCalendarValidationError(
                "session override label must match replacement session_label"
            )


class SettlementCalendar(_VenueCalendarModel):
    """Hold a bounded versioned set of eligible settlement dates."""

    calendar_id: str
    calendar_version: str
    timezone_name: str
    covered_from: date
    covered_through: date
    settlement_dates: tuple[date, ...]
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate exact settlement dates and finite source coverage."""
        _require_stable_token(self.calendar_id, field_name="settlement calendar_id")
        _require_stable_token(self.calendar_version, field_name="settlement calendar_version")
        _require_timezone_name(self.timezone_name, field_name="settlement timezone_name")
        covered_from = _require_date(self.covered_from, field_name="settlement covered_from")
        covered_through = _require_date(
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
        _require_stable_token(self.source, field_name="settlement source")
        _require_stable_token(self.source_revision, field_name="settlement source_revision")

    def is_settlement_day(self, candidate: date) -> bool:
        """Return whether a date is explicitly eligible for settlement."""
        checked = _require_date(candidate, field_name="candidate settlement date")
        if not self.covered_from <= checked <= self.covered_through:
            raise UnknownSettlementDateError(
                f"settlement date {checked.isoformat()} is outside calendar coverage"
            )
        return checked in self.settlement_dates

    def settlement_day_on_or_after(self, candidate: date) -> date:
        """Return the first recorded settlement date on or after a date."""
        checked = _require_date(candidate, field_name="candidate settlement date")
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


class VenueCalendarSnapshot(_VenueCalendarModel):
    """Hold one immutable, bounded projection of venue and settlement state."""

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

    @field_validator("venue", "version", "settlement_calendar", mode="before")
    @classmethod
    def typed_snapshot_values(cls, value: object, info: ValidationInfo) -> object:
        """Keep raw nested mappings outside the canonical snapshot boundary."""
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
    def typed_snapshot_sequences(cls, value: object, info: ValidationInfo) -> object:
        """Require immutable sequences of owned records before nested validation."""
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
        """Validate the complete immutable snapshot before publication."""
        if not isinstance(self.venue, Venue):
            raise VenueCalendarValidationError("venue must be a Venue")
        if not isinstance(self.version, CalendarSourceVersion):
            raise VenueCalendarValidationError("version must be a CalendarSourceVersion")
        covered_from = _require_date(self.covered_from, field_name="covered_from")
        covered_through = _require_date(self.covered_through, field_name="covered_through")
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
        if not isinstance(self.sessions, tuple) or not all(
            isinstance(session, TradingSession) for session in self.sessions
        ):
            raise VenueCalendarValidationError(
                "sessions must be an immutable tuple of TradingSession values"
            )
        ordered = tuple(sorted(self.sessions, key=lambda item: (item.opens_at, item.session_label)))
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
        """Return one exact session label or fail closed."""
        checked = _require_date(session_label, field_name="session_label")
        for session in self.sessions:
            if session.session_label == checked:
                return session
        raise UnknownSessionError(f"unknown session label {checked.isoformat()}")

    def closure_for_date(self, calendar_date: date) -> CalendarClosure | None:
        """Return an attributed closure when one is recorded."""
        checked = _require_date(calendar_date, field_name="calendar_date")
        if not self.covered_from <= checked <= self.covered_through:
            raise CalendarCoverageError(
                f"calendar date {checked.isoformat()} is outside snapshot coverage"
            )
        for closure in self.closures:
            if closure.calendar_date == checked:
                return closure
        return None

    def market_state_at(self, instant: datetime) -> MarketState:
        """Resolve deterministic venue state at an explicit UTC instant."""
        checked = require_utc_datetime(instant, field_name="instant")
        session_index = bisect_right(self.sessions, checked, key=lambda item: item.opens_at) - 1
        session = self.sessions[session_index] if session_index >= 0 else None
        if session is None or not session.contains(checked):
            local_date = checked.astimezone(ZoneInfo(self.venue.timezone_name)).date()
            if not self.covered_from <= local_date <= self.covered_through:
                raise CalendarCoverageError(
                    f"instant {checked.isoformat()} is outside snapshot coverage"
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
