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
    """Join validation messages in field order, retaining translated domain causes."""
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
    """Preserve strict immutable value semantics at the C02 boundary.

    Normal construction validates defaults and nested instances, rejects extra
    fields, and translates Pydantic failures to VenueCalendarValidationError.
    Freezing prevents field assignment. Inherited ``model_construct`` and
    ``model_copy(update=...)`` are trusted-data operations without field validation;
    construct a new model when replacement data must be checked.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
        strict=True,
        validate_default=True,
    )

    def __init__(self, **data: object) -> None:
        """Validate supplied fields and translate framework validation failures.

        Args:
            data: Fields of the concrete calendar model; unknown fields are rejected.

        Raises:
            VenueCalendarValidationError: A field or model invariant fails validation.
        """
        try:
            super().__init__(**data)
        except ValidationError as error:
            raise VenueCalendarValidationError(_validation_error_message(error)) from error


_STABLE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")
_MIC_PATTERN = re.compile(r"^[A-Z0-9]{4}$")


def _require_bounded_text(candidate: object, *, field_name: str, maximum_length: int) -> str:
    """Reject empty, padded, overlong text and Unicode control, format or surrogate characters."""
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
    """Require a 128-character ASCII token starting with a letter or digit and using ._:/+-."""
    identifier_text = _require_bounded_text(candidate, field_name=field_name, maximum_length=128)
    if _STABLE_TOKEN_PATTERN.fullmatch(identifier_text) is None:
        raise VenueCalendarValidationError(f"{field_name} must be a stable token")
    return identifier_text


def require_utc_datetime(candidate: object, *, field_name: str) -> datetime:
    """Require an aware UTC instant without consulting host-local timezone state.

    Args:
        candidate: Value to check; its UTC offset must be zero at that instant.
        field_name: Field label included in validation failures.

    Returns:
        The original datetime without timezone conversion or replacement.

    Raises:
        VenueCalendarValidationError: The value is not an aware datetime with a zero UTC
            offset.
    """
    if not isinstance(candidate, datetime) or candidate.tzinfo is None:
        raise VenueCalendarValidationError(f"{field_name} must be timezone-aware UTC")
    if candidate.utcoffset() != timedelta(0):
        raise VenueCalendarValidationError(f"{field_name} must use UTC")
    return candidate


def _require_date(candidate: object, *, field_name: str) -> date:
    """Require a date value, explicitly rejecting datetime subclasses."""
    if not isinstance(candidate, date) or isinstance(candidate, datetime):
        raise VenueCalendarValidationError(f"{field_name} must be a date")
    return candidate


def _require_timezone_name(candidate: object, *, field_name: str) -> str:
    """Validate a bounded timezone name against the available IANA timezone database."""
    timezone_name = _require_bounded_text(candidate, field_name=field_name, maximum_length=128)
    try:
        ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise VenueCalendarValidationError(
            f"{field_name} must name an available IANA timezone"
        ) from error
    return timezone_name


def _require_non_nil_uuid(candidate: object, *, field_name: str) -> UUID:
    """Require a UUID instance other than the all-zero identifier."""
    if not isinstance(candidate, UUID) or candidate.int == 0:
        raise VenueCalendarValidationError(f"{field_name} must be a non-nil UUID")
    return candidate


class VenueId(_VenueCalendarModel):
    """Hold one opaque repository-issued stable venue identifier.

    Attributes:
        uuid_value: Typed non-nil UUID; construction does not issue IDs or check registry
            membership.
    """

    uuid_value: UUID

    def model_post_init(self, _context: object, /) -> None:
        """Validate the opaque identity after strict field validation.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: The stored UUID is invalid or all-zero.
        """
        _require_non_nil_uuid(self.uuid_value, field_name="venue_id")

    @classmethod
    def from_canonical_text(cls, value: str) -> VenueId:
        """Parse the canonical lower-case UUID representation.

        Args:
            value: Exact lowercase hyphenated text for a non-nil venue UUID.

        Returns:
            A validated venue identifier.

        Raises:
            VenueCalendarValidationError: The text is malformed, noncanonical or represents the
                all-zero UUID.
        """
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
        """Render the venue ID as lowercase hyphenated UUID text.

        Returns:
            The canonical string representation of uuid_value.
        """
        return str(self.uuid_value)


class MarketIdentifierCode(_VenueCalendarModel):
    """Represent one exact ISO 10383 MIC-shaped identifier.

    Validation checks four uppercase ASCII letters or digits; it does not verify
    assignment in an external MIC registry.

    Attributes:
        value: Exact four-character MIC-shaped token, preserved without normalization.
    """

    value: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate the exact MIC shape without normalization.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: The value is not exactly four uppercase ASCII letters
                or digits.
        """
        if not isinstance(self.value, str) or _MIC_PATTERN.fullmatch(self.value) is None:
            raise VenueCalendarValidationError(
                "market_identifier_code must contain four uppercase ASCII letters or digits"
            )

    def __str__(self) -> str:
        """Render the exact MIC-shaped token without normalization.

        Returns:
            The stored four-character value.
        """
        return self.value


class Venue(_VenueCalendarModel):
    """Bind one stable venue identity to exact MIC and timezone metadata.

    Attributes:
        venue_id: Owned stable venue identifier.
        mic: Owned MIC-shaped identifier for this venue.
        operating_mic: Owned MIC-shaped identifier for its operator; no registry linkage is
            checked.
        name: Unpadded nonempty display name, up to 128 characters.
        timezone_name: Available IANA timezone name used for explicit local-time conversion.
    """

    venue_id: VenueId
    mic: MarketIdentifierCode
    operating_mic: MarketIdentifierCode
    name: str
    timezone_name: str

    @field_validator("venue_id", "mic", "operating_mic", mode="before")
    @classmethod
    def typed_identity_fields(cls, value: object, info: ValidationInfo[object]) -> object:
        """Require owned identity values rather than coercing nested mappings.

        Args:
            value: Candidate VenueId or MarketIdentifierCode.
            info: Pydantic metadata selecting venue_id, mic or operating_mic.

        Returns:
            The supplied owned value for subsequent field validation.

        Raises:
            VenueCalendarValidationError: The value does not have the owned type required by the
                selected field.
        """
        expected_type = VenueId if info.field_name == "venue_id" else MarketIdentifierCode
        if not isinstance(value, expected_type):
            raise VenueCalendarValidationError(
                f"{info.field_name} must be a {expected_type.__name__}"
            )
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate owned venue metadata after strict field validation.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: An identity type, bounded name or available IANA
                timezone is invalid.
        """
        if not isinstance(self.venue_id, VenueId):
            raise VenueCalendarValidationError("venue_id must be a VenueId")
        if not isinstance(self.mic, MarketIdentifierCode):
            raise VenueCalendarValidationError("mic must be a MarketIdentifierCode")
        if not isinstance(self.operating_mic, MarketIdentifierCode):
            raise VenueCalendarValidationError("operating_mic must be a MarketIdentifierCode")
        _require_bounded_text(self.name, field_name="venue name", maximum_length=128)
        _require_timezone_name(self.timezone_name, field_name="venue timezone_name")

    def local_time(self, instant: datetime) -> datetime:
        """Convert an explicit UTC instant to the venue's IANA timezone.

        Args:
            instant: Aware datetime with a zero UTC offset.

        Returns:
            A new aware datetime in the venue timezone, preserving the instant and DST fold.

        Raises:
            VenueCalendarValidationError: The input is not an aware datetime with a zero UTC
                offset.
        """
        return require_utc_datetime(instant, field_name="instant").astimezone(
            ZoneInfo(self.timezone_name)
        )


class CalendarAuthority(StrEnum):
    """Declare the bounded authority available to repository calendar snapshots."""

    REFERENCE_ONLY = "reference_only"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class CalendarSourceVersion(_VenueCalendarModel):
    """Identify a deterministic base source and optional override revision.

    Attributes:
        calendar_version: Stable token identifying the complete projected calendar version.
        base_source: Stable base-provider token.
        base_source_revision: Exact base revision token.
        adapter_name: Stable adapter identity token.
        adapter_version: Exact adapter version token.
        authority: Typed reference-only or synthetic-fixture authority declaration.
        override_source: Optional override-provider token; requires override_revision.
        override_revision: Optional exact override revision; requires override_source.
    """

    calendar_version: str
    base_source: str
    base_source_revision: str
    adapter_name: str
    adapter_version: str
    authority: CalendarAuthority
    override_source: str | None = None
    override_revision: str | None = None

    def model_post_init(self, _context: object, /) -> None:
        """Require exact source identity and paired override attribution.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: A source token or authority is invalid, or override
                source and revision are unpaired.
        """
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

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: The auction kind is invalid or bounds are not aware
                UTC instants in increasing order.
        """
        if not isinstance(self.kind, AuctionKind):
            raise VenueCalendarValidationError("auction kind must be an AuctionKind")
        start = require_utc_datetime(self.starts_at, field_name="auction starts_at")
        end = require_utc_datetime(self.ends_at, field_name="auction ends_at")
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
        checked = require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class TradingSession(_VenueCalendarModel):
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

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: The label, kind or UTC bounds are invalid; a break is
                unpaired or not strictly internal; or auctions are unordered, overlapping or
                outside the session.
        """
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
        checked = require_utc_datetime(instant, field_name="instant")
        return self.opens_at <= checked < self.closes_at


class ClosureKind(StrEnum):
    """Classify an explicitly attributed non-session date."""

    HOLIDAY = "holiday"
    AD_HOC = "ad_hoc"


class CalendarClosure(_VenueCalendarModel):
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

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: The date, closure kind, bounded name or attribution
                token is invalid.
        """
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
    """Represent one source-attributed half-open halt interval.

    The snapshot checks that the halt lies in exactly one session and does not
    overlap other halts. Halts can overlap auctions, breaks and price limits.

    Attributes:
        interruption_id: Stable token identifying the halt.
        kind: Typed interruption classification, currently HALT.
        starts_at: Inclusive aware UTC start.
        ends_at: Exclusive aware UTC end strictly after the start.
        reason: Unpadded nonempty explanation, up to 256 characters.
        source: Stable attribution token.
        source_revision: Stable source revision token.
    """

    interruption_id: str
    kind: InterruptionKind
    starts_at: datetime
    ends_at: datetime
    reason: str
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Validate the halt interval and its source attribution.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: An ID, kind, bounded reason, attribution token or
                increasing UTC interval is invalid.
        """
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
        """Return whether an explicit UTC instant lies in this half-open interruption.

        Args:
            instant: Aware datetime with a zero UTC offset.

        Returns:
            True from the inclusive start until the exclusive end defined by starts_at and
            ends_at.

        Raises:
            VenueCalendarValidationError: The input is not an aware datetime with a zero UTC
                offset.
        """
        checked = require_utc_datetime(instant, field_name="instant")
        return self.starts_at <= checked < self.ends_at


class PriceLimitState(StrEnum):
    """Describe the explicit price-limit state observed for a venue."""

    NONE = "none"
    LIMIT_UP = "limit_up"
    LIMIT_DOWN = "limit_down"
    LOCKED = "locked"


class PriceLimitWindow(_VenueCalendarModel):
    """Represent one source-attributed half-open non-normal limit interval.

    The snapshot checks single-session containment and non-overlap with other
    price-limit windows. A price limit can coexist with an auction, break or halt.

    Attributes:
        limit_id: Stable token identifying the limit window.
        state: Typed non-NONE price-limit state.
        starts_at: Inclusive aware UTC start.
        ends_at: Exclusive aware UTC end strictly after the start.
        source: Stable attribution token.
        source_revision: Stable source revision token.
    """

    limit_id: str
    state: PriceLimitState
    starts_at: datetime
    ends_at: datetime
    source: str
    source_revision: str

    def model_post_init(self, _context: object, /) -> None:
        """Require a non-normal attributed price-limit interval.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: An ID or attribution token is invalid, state is
                untyped or NONE, or UTC bounds are invalid.
        """
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
        """Return whether an explicit UTC instant lies in this half-open price-limit window.

        Args:
            instant: Aware datetime with a zero UTC offset.

        Returns:
            True from the inclusive start until the exclusive end defined by starts_at and
            ends_at.

        Raises:
            VenueCalendarValidationError: The input is not an aware datetime with a zero UTC
                offset.
        """
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
    """Return schedule, auction, halt, and independent price-limit state together.

    Attributes:
        status: Typed schedule state. CLOSED forbids session, auction, halt and limit
            metadata.
        price_limit_state: Independent typed limit state, always NONE when closed.
        session_label: Required date for every non-CLOSED state, including BREAK and HALTED.
        auction_kind: Present exactly when status is AUCTION.
        interruption_id: Stable halt token present exactly when status is HALTED.
    """

    status: MarketStatus
    price_limit_state: PriceLimitState
    session_label: date | None = None
    auction_kind: AuctionKind | None = None
    interruption_id: str | None = None

    def model_post_init(self, _context: object, /) -> None:
        """Reject incoherent schedule, auction, halt, or limit state.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: Types or metadata violate the CLOSED, session-label,
                auction-kind or halt-ID coupling rules.
        """
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
    """Describe one source-attributed, versioned change to a base session.

    Construction validates the instruction; the adapter applies it to the base
    calendar. A snapshot checks that the recorded result matches the instruction.

    Attributes:
        override_id: Stable override token, unique within a snapshot.
        action: Typed ADD, REPLACE or REMOVE instruction.
        session_label: Date of the targeted session.
        reason: Unpadded nonempty explanation, up to 256 characters.
        source: Stable token matching the snapshot override source.
        source_revision: Stable token matching the snapshot override revision.
        replacement: Same-label owned session required for ADD/REPLACE and forbidden for
            REMOVE.
    """

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
        """Require an owned replacement session when one is present.

        Args:
            value: Candidate TradingSession, or None for a removal.

        Returns:
            The original session or None; action-specific presence is checked later.

        Raises:
            VenueCalendarValidationError: A supplied value is not a TradingSession.
        """
        if value is not None and not isinstance(value, TradingSession):
            raise VenueCalendarValidationError("replacement must be a TradingSession")
        return value

    def model_post_init(self, _context: object, /) -> None:
        """Validate action, replacement label, and override attribution.

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: An ID, date, reason, action or attribution is invalid;
                or replacement presence or label disagrees with the action.
        """
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

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: Metadata or coverage is invalid, or eligible dates are
                not an immutable, unique, strictly increasing tuple within coverage.
        """
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
        """Return whether a date is explicitly eligible for settlement.

        Args:
            candidate: Date within inclusive settlement coverage; datetimes are rejected.

        Returns:
            True only if the date is recorded as eligible; False for other covered dates.

        Raises:
            VenueCalendarValidationError: The candidate is not a date or is a datetime.
            UnknownSettlementDateError: The candidate lies outside settlement coverage.
        """
        checked = _require_date(candidate, field_name="candidate settlement date")
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
    """Hold one immutable, bounded projection of venue and settlement state.

    Coverage bounds are inclusive session-label dates. When no session contains
    a queried instant, coverage is checked using its venue-local date. A session
    that crosses midnight can contain instants outside those local-date bounds.
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

        Args:
            _context: Pydantic initialization context; unused by this invariant check.

        Raises:
            VenueCalendarValidationError: Owned types, coverage, session ordering,
                closure/override consistency, attribution or overlay containment is invalid.
        """
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
        """Reject unordered, overlapping or duplicate-label sessions and labels outside coverage."""
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
        checked = _require_date(session_label, field_name="session_label")
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
        """Resolve deterministic venue state at an explicit UTC instant.

        Containing sessions take precedence over the local-date coverage fallback,
        including sessions crossing midnight. Session close and each overlay end are
        exclusive; auction state takes precedence when an auction overlaps a break.

        Args:
            instant: Aware datetime with zero UTC offset, tested against half-open session and
                overlay intervals.

        Returns:
            HALTED, AUCTION, BREAK or CONTINUOUS in that precedence order within a session, with
            an independent price-limit state; CLOSED with no limit outside sessions on covered
            venue-local dates.

        Raises:
            VenueCalendarValidationError: The instant is not an aware datetime with a zero UTC
                offset.
            CalendarCoverageError: No session contains the instant and its venue-local date is
                outside coverage.
        """
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
