"""Define immutable canonical instrument and external-identifier values."""

from __future__ import annotations

# standard library imports
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import UUID

# third party library imports
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)


class InstrumentIdentityError(ValueError):
    """Base class for deterministic instrument-identity failures."""


class InstrumentIdentityValidationError(InstrumentIdentityError):
    """Report an invalid canonical identity or symbology record."""


def _validation_error_message(error: ValidationError) -> str:
    messages: list[str] = []
    for detail in error.errors(include_input=False, include_url=False):
        context = detail.get("ctx")
        cause = context.get("error") if isinstance(context, dict) else None
        if isinstance(cause, InstrumentIdentityValidationError):
            messages.append(str(cause))
            continue
        location = ".".join(str(component) for component in detail["loc"])
        message = str(detail["msg"]).removeprefix("Value error, ")
        messages.append(f"{location}: {message}" if location else message)
    return "\n".join(messages)


class _InstrumentIdentityModel(BaseModel):
    """Preserve immutable value semantics with strict boundary validation."""

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
            raise InstrumentIdentityValidationError(_validation_error_message(error)) from error


class InstrumentKind(StrEnum):
    """Identify the distinct canonical concepts represented by an instrument ID."""

    ECONOMIC_INSTRUMENT = "economic_instrument"
    SHARE_CLASS = "share_class"
    LISTING = "listing"
    DERIVATIVE_SERIES = "derivative_series"
    CONTRACT = "contract"


class IdentifierScheme(StrEnum):
    """Name the external identifier families admitted at adapter boundaries."""

    VENDOR = "vendor"
    VENUE_SYMBOL = "venue_symbol"
    ISIN = "isin"
    CUSIP = "cusip"
    SEDOL = "sedol"
    TICKER = "ticker"
    CONTRACT = "contract"
    CHAIN = "chain"


_NAMESPACED_SCHEMES = frozenset(
    {
        IdentifierScheme.VENDOR,
        IdentifierScheme.VENUE_SYMBOL,
        IdentifierScheme.TICKER,
        IdentifierScheme.CONTRACT,
        IdentifierScheme.CHAIN,
    }
)
_GLOBAL_SCHEMES = frozenset({IdentifierScheme.ISIN, IdentifierScheme.CUSIP, IdentifierScheme.SEDOL})
_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ATTRIBUTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_CUSIP_PATTERN = re.compile(r"^[A-Z0-9*@#]{8}[0-9]$")
_SEDOL_PATTERN = re.compile(r"^[0-9BCDFGHJKLMNPQRSTVWXYZ]{6}[0-9]$")


def _require_non_nil_uuid(candidate_uuid: object, *, field_name: str) -> UUID:
    if not isinstance(candidate_uuid, UUID) or candidate_uuid.int == 0:
        raise InstrumentIdentityValidationError(f"{field_name} must be a non-nil UUID")
    return candidate_uuid


def _parse_canonical_uuid(uuid_text: str, *, field_name: str) -> UUID:
    if not isinstance(uuid_text, str):
        raise InstrumentIdentityValidationError(f"{field_name} must be a UUID string")
    try:
        parsed_uuid = UUID(uuid_text)
    except ValueError as error:
        raise InstrumentIdentityValidationError(f"{field_name} must be a canonical UUID") from error
    if str(parsed_uuid) != uuid_text:
        raise InstrumentIdentityValidationError(f"{field_name} must be a canonical UUID")
    return _require_non_nil_uuid(parsed_uuid, field_name=field_name)


def _require_bounded_text(candidate_text: object, *, field_name: str, maximum_length: int) -> str:
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
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in candidate_text):
        raise InstrumentIdentityValidationError(f"{field_name} contains a control character")
    return candidate_text


def _validate_identifier_namespace(
    candidate_namespace: object, *, namespace_required: bool
) -> str | None:
    if candidate_namespace is None:
        if namespace_required:
            raise InstrumentIdentityValidationError(
                "identifier namespace is required for provider-local schemes"
            )
        return None
    if (
        not isinstance(candidate_namespace, str)
        or _NAMESPACE_PATTERN.fullmatch(candidate_namespace) is None
    ):
        raise InstrumentIdentityValidationError(
            "identifier namespace must be a lower-case stable token"
        )
    return candidate_namespace


def _has_valid_luhn_checksum(decimal_digits: str) -> bool:
    checksum_total = 0
    for digit_position, digit_character in enumerate(reversed(decimal_digits)):
        digit_value = int(digit_character)
        if digit_position % 2 == 1:
            digit_value *= 2
        checksum_total += digit_value // 10 + digit_value % 10
    return checksum_total % 10 == 0


def _has_valid_isin_checksum(identifier_value: str) -> bool:
    if _ISIN_PATTERN.fullmatch(identifier_value) is None:
        return False
    expanded_digits = "".join(
        str(ord(character) - 55) if character.isalpha() else character
        for character in identifier_value
    )
    return _has_valid_luhn_checksum(expanded_digits)


def _cusip_character_numeric_value(identifier_character: str) -> int:
    if identifier_character.isdigit():
        return int(identifier_character)
    if identifier_character.isalpha():
        return ord(identifier_character) - 55
    return {"*": 36, "@": 37, "#": 38}[identifier_character]


def _has_valid_cusip_checksum(identifier_value: str) -> bool:
    if _CUSIP_PATTERN.fullmatch(identifier_value) is None:
        return False
    checksum_total = 0
    for character_position, identifier_character in enumerate(identifier_value[:8]):
        weighted_value = _cusip_character_numeric_value(identifier_character) * (
            1 if character_position % 2 == 0 else 2
        )
        checksum_total += weighted_value // 10 + weighted_value % 10
    return (10 - checksum_total % 10) % 10 == int(identifier_value[-1])


def _has_valid_sedol_checksum(identifier_value: str) -> bool:
    if _SEDOL_PATTERN.fullmatch(identifier_value) is None:
        return False
    checksum_weights = (1, 3, 1, 7, 3, 9)
    checksum_total = sum(
        _cusip_character_numeric_value(identifier_character) * checksum_weight
        for identifier_character, checksum_weight in zip(
            identifier_value[:6], checksum_weights, strict=True
        )
    )
    return (10 - checksum_total % 10) % 10 == int(identifier_value[-1])


def _validate_identifier_value(identifier_scheme: IdentifierScheme, candidate_value: object) -> str:
    identifier_value = _require_bounded_text(
        candidate_value, field_name="identifier value", maximum_length=256
    )
    checksum_validators = {
        IdentifierScheme.ISIN: (_has_valid_isin_checksum, "valid uppercase ISIN with checksum"),
        IdentifierScheme.CUSIP: (_has_valid_cusip_checksum, "valid uppercase CUSIP with checksum"),
        IdentifierScheme.SEDOL: (_has_valid_sedol_checksum, "valid uppercase SEDOL with checksum"),
    }
    checksum_validator_and_requirement = checksum_validators.get(identifier_scheme)
    if checksum_validator_and_requirement is not None:
        checksum_validator, requirement_description = checksum_validator_and_requirement
        if not checksum_validator(identifier_value):
            raise InstrumentIdentityValidationError(
                f"{identifier_scheme.value} identifier must be a {requirement_description}"
            )
    return identifier_value


def require_utc_datetime(candidate_datetime: object, *, field_name: str) -> datetime:
    """Require an aware UTC datetime without reading host-local timezone state."""
    if not isinstance(candidate_datetime, datetime) or candidate_datetime.tzinfo is None:
        raise InstrumentIdentityValidationError(f"{field_name} must be timezone-aware UTC")
    if candidate_datetime.utcoffset() != timedelta(0):
        raise InstrumentIdentityValidationError(f"{field_name} must use UTC")
    return candidate_datetime


class InstrumentId(_InstrumentIdentityModel):
    """Hold one opaque repository-issued stable instrument identifier."""

    uuid_value: UUID

    def __init__(self, uuid_value: UUID, **extra: object) -> None:
        super().__init__(uuid_value=uuid_value, **extra)

    @field_validator("uuid_value", mode="before")
    @classmethod
    def valid_uuid(cls, value: object) -> UUID:
        """Require a typed, non-nil UUID without coercion."""
        return _require_non_nil_uuid(value, field_name="instrument_id")

    @classmethod
    def from_canonical_text(cls, instrument_id_text: str) -> InstrumentId:
        """Parse the canonical lower-case UUID representation."""
        return cls(_parse_canonical_uuid(instrument_id_text, field_name="instrument_id"))

    def __str__(self) -> str:
        return str(self.uuid_value)


class MappingId(_InstrumentIdentityModel):
    """Hold the stable identity of one retained mapping assertion."""

    uuid_value: UUID

    def __init__(self, uuid_value: UUID, **extra: object) -> None:
        super().__init__(uuid_value=uuid_value, **extra)

    @field_validator("uuid_value", mode="before")
    @classmethod
    def valid_uuid(cls, value: object) -> UUID:
        """Require a typed, non-nil UUID without coercion."""
        return _require_non_nil_uuid(value, field_name="mapping_id")

    @classmethod
    def from_canonical_text(cls, mapping_id_text: str) -> MappingId:
        """Parse the canonical lower-case UUID representation."""
        return cls(_parse_canonical_uuid(mapping_id_text, field_name="mapping_id"))

    def __str__(self) -> str:
        return str(self.uuid_value)


class InstrumentIdentity(_InstrumentIdentityModel):
    """Bind a stable ID to one canonical concept and economic root."""

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
        super().__init__(
            instrument_id=instrument_id,
            instrument_kind=instrument_kind,
            economic_instrument_id=economic_instrument_id,
            **extra,
        )

    @field_validator("instrument_id", mode="before")
    @classmethod
    def valid_instrument_id(cls, value: object) -> InstrumentId:
        """Reject unvalidated canonical identifiers."""
        if not isinstance(value, InstrumentId):
            raise InstrumentIdentityValidationError("instrument_id must be an InstrumentId")
        return value

    @field_validator("instrument_kind", mode="before")
    @classmethod
    def valid_instrument_kind(cls, value: object) -> InstrumentKind:
        """Reject raw strings at the canonical identity boundary."""
        if not isinstance(value, InstrumentKind):
            raise InstrumentIdentityValidationError("instrument_kind must be an InstrumentKind")
        return value

    @field_validator("economic_instrument_id", mode="before")
    @classmethod
    def valid_economic_instrument_id(cls, value: object) -> InstrumentId:
        """Reject unvalidated economic-root identifiers."""
        if not isinstance(value, InstrumentId):
            raise InstrumentIdentityValidationError(
                "economic_instrument_id must be an InstrumentId"
            )
        return value

    @model_validator(mode="after")
    def coherent_economic_root(self) -> Self:
        """Require only an economic instrument to identify itself as its root."""
        is_economic_instrument_root = self.instrument_kind is InstrumentKind.ECONOMIC_INSTRUMENT
        if is_economic_instrument_root != (self.instrument_id == self.economic_instrument_id):
            raise InstrumentIdentityValidationError(
                "only an economic instrument may identify itself as its economic root"
            )
        return self


class ExternalIdentifier(_InstrumentIdentityModel):
    """Represent an exact adapter-boundary identifier without normalizing its value."""

    scheme: IdentifierScheme
    value: str
    namespace: str | None = None

    def __init__(
        self,
        scheme: IdentifierScheme,
        value: str,
        namespace: str | None = None,
        **extra: object,
    ) -> None:
        super().__init__(scheme=scheme, value=value, namespace=namespace, **extra)

    @field_validator("scheme", mode="before")
    @classmethod
    def valid_scheme(cls, value: object) -> IdentifierScheme:
        """Reject raw scheme strings at the adapter boundary."""
        if not isinstance(value, IdentifierScheme):
            raise InstrumentIdentityValidationError("identifier scheme must be an IdentifierScheme")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def bounded_value(cls, value: object) -> str:
        """Require an exact bounded identifier string."""
        return _require_bounded_text(value, field_name="identifier value", maximum_length=256)

    @field_validator("namespace", mode="before")
    @classmethod
    def valid_namespace_token(cls, value: object) -> str | None:
        """Require a canonical namespace token when one is supplied."""
        return _validate_identifier_namespace(value, namespace_required=False)

    @model_validator(mode="after")
    def coherent_identifier(self) -> Self:
        """Validate scheme-specific value and namespace rules."""
        _validate_identifier_value(self.scheme, self.value)
        if self.namespace is None and self.scheme in _NAMESPACED_SCHEMES:
            raise InstrumentIdentityValidationError(
                "identifier namespace is required for provider-local schemes"
            )
        if self.scheme in _GLOBAL_SCHEMES and self.namespace is not None:
            raise InstrumentIdentityValidationError(
                f"{self.scheme.value} identifiers cannot carry a provider namespace"
            )
        return self


class IdentifierQuery(_InstrumentIdentityModel):
    """Represent an exact or intentionally namespace-broad temporal lookup."""

    scheme: IdentifierScheme
    value: str
    namespace: str | None = None

    def __init__(
        self,
        scheme: IdentifierScheme,
        value: str,
        namespace: str | None = None,
        **extra: object,
    ) -> None:
        super().__init__(scheme=scheme, value=value, namespace=namespace, **extra)

    @field_validator("scheme", mode="before")
    @classmethod
    def valid_scheme(cls, value: object) -> IdentifierScheme:
        """Reject raw scheme strings at the query boundary."""
        if not isinstance(value, IdentifierScheme):
            raise InstrumentIdentityValidationError("query scheme must be an IdentifierScheme")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def bounded_value(cls, value: object) -> str:
        """Require an exact bounded query string."""
        return _require_bounded_text(value, field_name="identifier value", maximum_length=256)

    @field_validator("namespace", mode="before")
    @classmethod
    def valid_namespace_token(cls, value: object) -> str | None:
        """Require a canonical namespace token when one is supplied."""
        return _validate_identifier_namespace(value, namespace_required=False)

    @model_validator(mode="after")
    def coherent_query(self) -> Self:
        """Validate scheme-specific query value and namespace rules."""
        _validate_identifier_value(self.scheme, self.value)
        if self.scheme in _GLOBAL_SCHEMES and self.namespace is not None:
            raise InstrumentIdentityValidationError(
                f"{self.scheme.value} queries cannot carry a provider namespace"
            )
        return self

    @classmethod
    def for_exact_identifier(cls, external_identifier: ExternalIdentifier) -> IdentifierQuery:
        """Build an exact query from a validated external identifier."""
        if not isinstance(external_identifier, ExternalIdentifier):
            raise InstrumentIdentityValidationError(
                "external_identifier must be an ExternalIdentifier"
            )
        return cls(
            scheme=external_identifier.scheme,
            value=external_identifier.value,
            namespace=external_identifier.namespace,
        )

    def matches_identifier(self, external_identifier: ExternalIdentifier) -> bool:
        """Return whether the identifier is within this query's explicit scope."""
        return (
            self.scheme is external_identifier.scheme
            and self.value == external_identifier.value
            and (self.namespace is None or self.namespace == external_identifier.namespace)
        )


class SymbologyMapping(_InstrumentIdentityModel):
    """Record one immutable, validity-dated, source-attributed mapping assertion."""

    mapping_id: MappingId
    instrument_id: InstrumentId
    external_identifier: ExternalIdentifier
    valid_from: datetime
    valid_to: datetime | None
    source: str
    source_revision: str
    supersedes_mapping_id: MappingId | None = None
    correction_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def valid_raw_correction_metadata(cls, value: object) -> object:
        """Preserve correction coupling errors before primitive type validation."""
        if not isinstance(value, Mapping):
            return value
        supersedes_mapping_id = value.get("supersedes_mapping_id")
        correction_reason = value.get("correction_reason")
        if supersedes_mapping_id is None:
            if correction_reason is not None:
                raise InstrumentIdentityValidationError(
                    "correction_reason is permitted only when supersedes_mapping_id is present"
                )
        else:
            _require_bounded_text(
                correction_reason,
                field_name="correction_reason",
                maximum_length=512,
            )
        return value

    def __init__(
        self,
        mapping_id: MappingId,
        instrument_id: InstrumentId,
        external_identifier: ExternalIdentifier,
        valid_from: datetime,
        valid_to: datetime | None,
        source: str,
        source_revision: str,
        supersedes_mapping_id: MappingId | None = None,
        correction_reason: str | None = None,
        **extra: object,
    ) -> None:
        super().__init__(
            mapping_id=mapping_id,
            instrument_id=instrument_id,
            external_identifier=external_identifier,
            valid_from=valid_from,
            valid_to=valid_to,
            source=source,
            source_revision=source_revision,
            supersedes_mapping_id=supersedes_mapping_id,
            correction_reason=correction_reason,
            **extra,
        )

    @field_validator("mapping_id", mode="before")
    @classmethod
    def valid_mapping_id(cls, value: object) -> MappingId:
        """Reject unvalidated mapping identifiers."""
        if not isinstance(value, MappingId):
            raise InstrumentIdentityValidationError("mapping_id must be a MappingId")
        return value

    @field_validator("instrument_id", mode="before")
    @classmethod
    def valid_instrument_id(cls, value: object) -> InstrumentId:
        """Reject unvalidated canonical identifiers."""
        if not isinstance(value, InstrumentId):
            raise InstrumentIdentityValidationError("instrument_id must be an InstrumentId")
        return value

    @field_validator("external_identifier", mode="before")
    @classmethod
    def valid_external_identifier(cls, value: object) -> ExternalIdentifier:
        """Reject unvalidated external identifiers."""
        if not isinstance(value, ExternalIdentifier):
            raise InstrumentIdentityValidationError(
                "external_identifier must be an ExternalIdentifier"
            )
        return value

    @field_validator("valid_from", mode="before")
    @classmethod
    def valid_start(cls, value: object) -> datetime:
        """Require an aware UTC interval start."""
        return require_utc_datetime(value, field_name="valid_from")

    @field_validator("valid_to", mode="before")
    @classmethod
    def valid_end(cls, value: object) -> datetime | None:
        """Require an aware UTC interval end when supplied."""
        return None if value is None else require_utc_datetime(value, field_name="valid_to")

    @field_validator("source", "source_revision", mode="before")
    @classmethod
    def stable_attribution(cls, value: object, info: ValidationInfo) -> str:
        """Require stable source-attribution tokens."""
        if not isinstance(value, str) or _ATTRIBUTION_PATTERN.fullmatch(value) is None:
            raise InstrumentIdentityValidationError(
                f"{info.field_name} must be a stable attribution token"
            )
        return value

    @field_validator("supersedes_mapping_id", mode="before")
    @classmethod
    def valid_superseded_mapping_id(cls, value: object) -> MappingId | None:
        """Reject unvalidated correction links."""
        if value is not None and not isinstance(value, MappingId):
            raise InstrumentIdentityValidationError("supersedes_mapping_id must be a MappingId")
        return value

    @model_validator(mode="after")
    def coherent_interval_and_correction(self) -> Self:
        """Validate interval ordering and correction metadata coupling."""
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise InstrumentIdentityValidationError(
                "valid_to must be later than valid_from for a half-open interval"
            )
        if self.supersedes_mapping_id is None:
            if self.correction_reason is not None:
                raise InstrumentIdentityValidationError(
                    "correction_reason is permitted only when supersedes_mapping_id is present"
                )
        else:
            _require_bounded_text(
                self.correction_reason,
                field_name="correction_reason",
                maximum_length=512,
            )
        return self

    def is_valid_at(self, valid_at: datetime) -> bool:
        """Return whether ``valid_at`` lies in the mapping's half-open UTC interval."""
        valid_at_utc = require_utc_datetime(valid_at, field_name="valid_at")
        return self.valid_from <= valid_at_utc and (
            self.valid_to is None or valid_at_utc < self.valid_to
        )
