"""Define shared validation, venue identity, and calendar provenance contracts."""

from __future__ import annotations

# standard library imports
import re
import unicodedata
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# third party library imports
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
)

# project library imports
from reference_data._validation import _ValidationMessages


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
            raise VenueCalendarValidationError(
                _ValidationMessages.from_error(error, VenueCalendarValidationError)
            ) from error

    @staticmethod
    def _require_bounded_text(candidate: object, *, field_name: str, maximum_length: int) -> str:
        """Reject empty, padded, overlong text and Unicode control, format or surrogate codes."""
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

    @staticmethod
    def _require_stable_token(candidate: object, *, field_name: str) -> str:
        """Require a 128-character ASCII token starting with a letter or digit and using ._:/+-."""
        identifier_text = _VenueCalendarModel._require_bounded_text(
            candidate, field_name=field_name, maximum_length=128
        )
        if _STABLE_TOKEN_PATTERN.fullmatch(identifier_text) is None:
            raise VenueCalendarValidationError(f"{field_name} must be a stable token")
        return identifier_text

    @staticmethod
    def _require_utc_datetime(candidate: object, *, field_name: str) -> datetime:
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

    @staticmethod
    def _require_date(candidate: object, *, field_name: str) -> date:
        """Require a date value, explicitly rejecting datetime subclasses."""
        if not isinstance(candidate, date) or isinstance(candidate, datetime):
            raise VenueCalendarValidationError(f"{field_name} must be a date")
        return candidate

    @staticmethod
    def _require_timezone_name(candidate: object, *, field_name: str) -> str:
        """Validate a bounded timezone name against the available IANA timezone database."""
        timezone_name = _VenueCalendarModel._require_bounded_text(
            candidate, field_name=field_name, maximum_length=128
        )
        try:
            ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise VenueCalendarValidationError(
                f"{field_name} must name an available IANA timezone"
            ) from error
        return timezone_name


_STABLE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")
_MIC_PATTERN = re.compile(r"^[A-Z0-9]{4}$")


class VenueId(_VenueCalendarModel):
    """Hold one opaque repository-issued stable venue identifier.

    Attributes:
        uuid_value: Typed non-nil UUID; construction does not issue IDs or check registry
            membership.
    """

    uuid_value: UUID

    def model_post_init(self, _context: object, /) -> None:
        """Validate the opaque identity after strict field validation.

        Raises:
            VenueCalendarValidationError: The stored UUID is invalid or all-zero.
        """
        VenueId._require_non_nil_uuid(self.uuid_value, field_name="venue_id")

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

    @staticmethod
    def _require_non_nil_uuid(candidate: object, *, field_name: str) -> UUID:
        """Require a UUID instance other than the all-zero identifier."""
        if not isinstance(candidate, UUID) or candidate.int == 0:
            raise VenueCalendarValidationError(f"{field_name} must be a non-nil UUID")
        return candidate


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
        _VenueCalendarModel._require_bounded_text(
            self.name, field_name="venue name", maximum_length=128
        )
        _VenueCalendarModel._require_timezone_name(
            self.timezone_name, field_name="venue timezone_name"
        )

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
        return _VenueCalendarModel._require_utc_datetime(instant, field_name="instant").astimezone(
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

        Raises:
            VenueCalendarValidationError: A source token or authority is invalid, or override
                source and revision are unpaired.
        """
        _VenueCalendarModel._require_stable_token(
            self.calendar_version, field_name="calendar_version"
        )
        _VenueCalendarModel._require_stable_token(self.base_source, field_name="base_source")
        _VenueCalendarModel._require_stable_token(
            self.base_source_revision, field_name="base_source_revision"
        )
        _VenueCalendarModel._require_stable_token(self.adapter_name, field_name="adapter_name")
        _VenueCalendarModel._require_stable_token(
            self.adapter_version, field_name="adapter_version"
        )
        if not isinstance(self.authority, CalendarAuthority):
            raise VenueCalendarValidationError("authority must be a CalendarAuthority")
        if (self.override_source is None) != (self.override_revision is None):
            raise VenueCalendarValidationError(
                "override_source and override_revision must be provided together"
            )
        if self.override_source is not None:
            _VenueCalendarModel._require_stable_token(
                self.override_source, field_name="override_source"
            )
            _VenueCalendarModel._require_stable_token(
                self.override_revision, field_name="override_revision"
            )
