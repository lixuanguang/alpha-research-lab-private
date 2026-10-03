"""Define canonical instrument identities and repository-issued identifiers."""

from __future__ import annotations

# standard library imports
import unicodedata
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import UUID

# third party library imports
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

# project library imports
from reference_data._validation import _ValidationMessages


class InstrumentIdentityError(ValueError):
    """Base class for deterministic instrument-identity failures."""


class InstrumentIdentityValidationError(InstrumentIdentityError):
    """Report an invalid canonical identity or symbology record."""


class InstrumentIdentityModel(BaseModel):
    """Preserve immutable value semantics with strict boundary validation.

    Normal construction validates defaults and existing nested instances, forbids
    extra fields, and translates Pydantic validation failures to the identity error.
    Freezing prevents field assignment; inherited ``model_construct`` and
    ``model_copy(update=...)`` accept trusted data without revalidation.
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
            data: Field values for the concrete identity model; unknown fields are rejected.

        Raises:
            InstrumentIdentityValidationError: A field or cross-field invariant fails
                validation.
        """
        try:
            super().__init__(**data)
        except ValidationError as error:
            raise InstrumentIdentityValidationError(
                _ValidationMessages.from_error(error, InstrumentIdentityValidationError)
            ) from error

    @staticmethod
    def _require_bounded_text(
        candidate_text: object, *, field_name: str, maximum_length: int
    ) -> str:
        """Reject empty, padded, overlong text and Unicode control, format or surrogate codes."""
        if (
            not isinstance(candidate_text, str)
            or not candidate_text
            or candidate_text != candidate_text.strip()
        ):
            raise InstrumentIdentityValidationError(
                f"{field_name} must be non-empty without surrounding whitespace"
            )
        if len(candidate_text) > maximum_length:
            raise InstrumentIdentityValidationError(
                f"{field_name} exceeds the {maximum_length}-character limit"
            )
        if any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in candidate_text
        ):
            raise InstrumentIdentityValidationError(f"{field_name} contains a control character")
        return candidate_text

    @staticmethod
    def _require_utc_datetime(candidate_datetime: object, *, field_name: str) -> datetime:
        """Require an aware UTC datetime without reading host-local timezone state.

        Args:
            candidate_datetime: Value to check; its UTC offset must be zero at that instant.
            field_name: Field label included in validation failures.

        Returns:
            The original datetime, without timezone conversion or replacement.

        Raises:
            InstrumentIdentityValidationError: The value is not an aware datetime with a zero
                UTC offset.
        """
        if not isinstance(candidate_datetime, datetime) or candidate_datetime.tzinfo is None:
            raise InstrumentIdentityValidationError(f"{field_name} must be timezone-aware UTC")
        if candidate_datetime.utcoffset() != timedelta(0):
            raise InstrumentIdentityValidationError(f"{field_name} must use UTC")
        return candidate_datetime


class InstrumentKind(StrEnum):
    """Identify the distinct canonical concepts represented by an instrument ID."""

    ECONOMIC_INSTRUMENT = "economic_instrument"
    SHARE_CLASS = "share_class"
    LISTING = "listing"
    DERIVATIVE_SERIES = "derivative_series"
    CONTRACT = "contract"


class _IdentityUuid:
    """Share canonical non-nil UUID parsing for distinct C01 identity types."""

    @staticmethod
    def _require_non_nil_uuid(candidate_uuid: object, *, field_name: str) -> UUID:
        """Require a UUID instance other than the all-zero identifier."""
        if not isinstance(candidate_uuid, UUID) or candidate_uuid.int == 0:
            raise InstrumentIdentityValidationError(f"{field_name} must be a non-nil UUID")
        return candidate_uuid

    @staticmethod
    def _parse_canonical_uuid(uuid_text: str, *, field_name: str) -> UUID:
        """Require non-nil, lowercase hyphenated UUID text without normalization."""
        if not isinstance(uuid_text, str):
            raise InstrumentIdentityValidationError(f"{field_name} must be a UUID string")
        try:
            parsed_uuid = UUID(uuid_text)
        except ValueError as error:
            raise InstrumentIdentityValidationError(
                f"{field_name} must be a canonical UUID"
            ) from error
        if str(parsed_uuid) != uuid_text:
            raise InstrumentIdentityValidationError(f"{field_name} must be a canonical UUID")
        return _IdentityUuid._require_non_nil_uuid(parsed_uuid, field_name=field_name)


class InstrumentId(InstrumentIdentityModel):
    """Hold one opaque repository-issued stable instrument identifier.

    Construction checks UUID representation and non-nil value; it does not issue
    an ID or establish catalog membership.

    Attributes:
        uuid_value: Typed non-nil UUID, compared by value.
    """

    uuid_value: UUID

    def __init__(self, uuid_value: UUID, **extra: object) -> None:
        """Validate a typed non-nil instrument UUID.

        Args:
            uuid_value: UUID instance; text and the all-zero UUID are rejected.
            extra: Additional keyword fields; rejected by the closed schema.

        Raises:
            InstrumentIdentityValidationError: The UUID is invalid or an unknown field is
                supplied.
        """
        super().__init__(uuid_value=uuid_value, **extra)

    @field_validator("uuid_value", mode="before")
    @classmethod
    def valid_uuid(cls, value: object) -> UUID:
        """Require a typed, non-nil UUID without coercion.

        Raises:
            InstrumentIdentityValidationError: The value is not a UUID or is the all-zero UUID.
        """
        return _IdentityUuid._require_non_nil_uuid(value, field_name="instrument_id")

    @classmethod
    def from_canonical_text(cls, instrument_id_text: str) -> InstrumentId:
        """Parse the canonical lower-case UUID representation.

        Args:
            instrument_id_text: Exact lowercase hyphenated text for a non-nil UUID.

        Returns:
            A validated instrument identifier.

        Raises:
            InstrumentIdentityValidationError: The text is malformed, noncanonical or represents
                the all-zero UUID.
        """
        return cls(
            _IdentityUuid._parse_canonical_uuid(instrument_id_text, field_name="instrument_id")
        )

    def __str__(self) -> str:
        """Render the identifier as lowercase hyphenated UUID text.

        Returns:
            The canonical string representation of uuid_value.
        """
        return str(self.uuid_value)


class MappingId(InstrumentIdentityModel):
    """Hold one opaque repository-issued stable mapping assertion identifier.

    Construction checks UUID representation and non-nil value; it does not issue
    an ID or establish catalog membership.

    Attributes:
        uuid_value: Typed non-nil UUID, compared by value.
    """

    uuid_value: UUID

    def __init__(self, uuid_value: UUID, **extra: object) -> None:
        """Validate a typed non-nil mapping assertion UUID.

        Args:
            uuid_value: UUID instance; text and the all-zero UUID are rejected.
            extra: Additional keyword fields; rejected by the closed schema.

        Raises:
            InstrumentIdentityValidationError: The UUID is invalid or an unknown field is
                supplied.
        """
        super().__init__(uuid_value=uuid_value, **extra)

    @field_validator("uuid_value", mode="before")
    @classmethod
    def valid_uuid(cls, value: object) -> UUID:
        """Require a typed, non-nil UUID without coercion.

        Raises:
            InstrumentIdentityValidationError: The value is not a UUID or is the all-zero UUID.
        """
        return _IdentityUuid._require_non_nil_uuid(value, field_name="mapping_id")

    @classmethod
    def from_canonical_text(cls, mapping_id_text: str) -> MappingId:
        """Parse the canonical lower-case UUID representation.

        Args:
            mapping_id_text: Exact lowercase hyphenated text for a non-nil UUID.

        Returns:
            A validated mapping assertion identifier.

        Raises:
            InstrumentIdentityValidationError: The text is malformed, noncanonical or represents
                the all-zero UUID.
        """
        return cls(_IdentityUuid._parse_canonical_uuid(mapping_id_text, field_name="mapping_id"))

    def __str__(self) -> str:
        """Render the identifier as lowercase hyphenated UUID text.

        Returns:
            The canonical string representation of uuid_value.
        """
        return str(self.uuid_value)


class InstrumentIdentity(InstrumentIdentityModel):
    """Bind a stable ID to one canonical concept and economic root.

    An economic instrument must identify itself as its root; every other kind
    must use a different root ID. Existence and kind of the referenced root are
    catalog-level checks.

    Attributes:
        instrument_id: Opaque ID of this canonical concept.
        instrument_kind: Typed concept classification.
        economic_instrument_id: ID of the economic root shared by related concepts.
    """

    instrument_id: InstrumentId
    instrument_kind: InstrumentKind
    economic_instrument_id: InstrumentId

    def __init__(
        self,
        instrument_id: InstrumentId,
        instrument_kind: InstrumentKind,
        economic_instrument_id: InstrumentId,
        **extra: object,
    ) -> None:
        """Validate a canonical concept and its economic-root relationship.

        Args:
            instrument_id: Validated stable ID of the concept.
            instrument_kind: InstrumentKind member; raw strings are rejected.
            economic_instrument_id: Validated root ID, equal to this ID exactly for an economic
                instrument.
            extra: Additional keyword fields; rejected by the closed schema.

        Raises:
            InstrumentIdentityValidationError: Types or the self-root relationship are invalid.
        """
        super().__init__(
            instrument_id=instrument_id,
            instrument_kind=instrument_kind,
            economic_instrument_id=economic_instrument_id,
            **extra,
        )

    @field_validator("instrument_id", mode="before")
    @classmethod
    def valid_instrument_id(cls, value: object) -> InstrumentId:
        """Require an owned instrument_id value without coercion.

        Raises:
            InstrumentIdentityValidationError: The value is not a InstrumentId.
        """
        if not isinstance(value, InstrumentId):
            raise InstrumentIdentityValidationError("instrument_id must be an InstrumentId")
        return value

    @field_validator("instrument_kind", mode="before")
    @classmethod
    def valid_instrument_kind(cls, value: object) -> InstrumentKind:
        """Require an owned instrument_kind value without coercion.

        Raises:
            InstrumentIdentityValidationError: The value is not a InstrumentKind.
        """
        if not isinstance(value, InstrumentKind):
            raise InstrumentIdentityValidationError("instrument_kind must be an InstrumentKind")
        return value

    @field_validator("economic_instrument_id", mode="before")
    @classmethod
    def valid_economic_instrument_id(cls, value: object) -> InstrumentId:
        """Require an owned economic_instrument_id value without coercion.

        Raises:
            InstrumentIdentityValidationError: The value is not a InstrumentId.
        """
        if not isinstance(value, InstrumentId):
            raise InstrumentIdentityValidationError(
                "economic_instrument_id must be an InstrumentId"
            )
        return value

    @model_validator(mode="after")
    def coherent_economic_root(self) -> Self:
        """Require only an economic instrument to identify itself as its root.

        Returns:
            This identity after checking the root relationship.

        Raises:
            InstrumentIdentityValidationError: An economic instrument has another root, or
                another kind is self-rooted.
        """
        is_economic_instrument_root = self.instrument_kind is InstrumentKind.ECONOMIC_INSTRUMENT
        if is_economic_instrument_root != (self.instrument_id == self.economic_instrument_id):
            raise InstrumentIdentityValidationError(
                "only an economic instrument may identify itself as its economic root"
            )
        return self
