"""Define immutable canonical instrument and external-identifier values."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class InstrumentIdentityError(ValueError):
    """Base class for deterministic instrument-identity failures."""


class InstrumentIdentityValidationError(InstrumentIdentityError):
    """Report an invalid canonical identity or symbology record."""


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


@dataclass(frozen=True, slots=True)
class InstrumentId:
    """Hold one opaque repository-issued stable instrument identifier."""

    uuid_value: UUID

    def __post_init__(self) -> None:
        _require_non_nil_uuid(self.uuid_value, field_name="instrument_id")

    @classmethod
    def from_canonical_text(cls, instrument_id_text: str) -> InstrumentId:
        """Parse the canonical lower-case UUID representation."""
        return cls(_parse_canonical_uuid(instrument_id_text, field_name="instrument_id"))

    def __str__(self) -> str:
        return str(self.uuid_value)


@dataclass(frozen=True, slots=True)
class MappingId:
    """Hold the stable identity of one retained mapping assertion."""

    uuid_value: UUID

    def __post_init__(self) -> None:
        _require_non_nil_uuid(self.uuid_value, field_name="mapping_id")

    @classmethod
    def from_canonical_text(cls, mapping_id_text: str) -> MappingId:
        """Parse the canonical lower-case UUID representation."""
        return cls(_parse_canonical_uuid(mapping_id_text, field_name="mapping_id"))

    def __str__(self) -> str:
        return str(self.uuid_value)


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    """Bind a stable ID to one canonical concept and economic root."""

    instrument_id: InstrumentId
    instrument_kind: InstrumentKind
    economic_instrument_id: InstrumentId

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise InstrumentIdentityValidationError("instrument_id must be an InstrumentId")
        if not isinstance(self.instrument_kind, InstrumentKind):
            raise InstrumentIdentityValidationError("instrument_kind must be an InstrumentKind")
        if not isinstance(self.economic_instrument_id, InstrumentId):
            raise InstrumentIdentityValidationError(
                "economic_instrument_id must be an InstrumentId"
            )
        is_economic_instrument_root = self.instrument_kind is InstrumentKind.ECONOMIC_INSTRUMENT
        if is_economic_instrument_root != (self.instrument_id == self.economic_instrument_id):
            raise InstrumentIdentityValidationError(
                "only an economic instrument may identify itself as its economic root"
            )


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    """Represent an exact adapter-boundary identifier without normalizing its value."""

    scheme: IdentifierScheme
    value: str
    namespace: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, IdentifierScheme):
            raise InstrumentIdentityValidationError("identifier scheme must be an IdentifierScheme")
        object.__setattr__(self, "value", _validate_identifier_value(self.scheme, self.value))
        namespace = _validate_identifier_namespace(
            self.namespace, namespace_required=self.scheme in _NAMESPACED_SCHEMES
        )
        if self.scheme in _GLOBAL_SCHEMES and namespace is not None:
            raise InstrumentIdentityValidationError(
                f"{self.scheme.value} identifiers cannot carry a provider namespace"
            )
        object.__setattr__(self, "namespace", namespace)


@dataclass(frozen=True, slots=True)
class IdentifierQuery:
    """Represent an exact or intentionally namespace-broad temporal lookup."""

    scheme: IdentifierScheme
    value: str
    namespace: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, IdentifierScheme):
            raise InstrumentIdentityValidationError("query scheme must be an IdentifierScheme")
        object.__setattr__(self, "value", _validate_identifier_value(self.scheme, self.value))
        namespace = _validate_identifier_namespace(self.namespace, namespace_required=False)
        if self.scheme in _GLOBAL_SCHEMES and namespace is not None:
            raise InstrumentIdentityValidationError(
                f"{self.scheme.value} queries cannot carry a provider namespace"
            )
        object.__setattr__(self, "namespace", namespace)

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


@dataclass(frozen=True, slots=True)
class SymbologyMapping:
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

    def __post_init__(self) -> None:
        if not isinstance(self.mapping_id, MappingId):
            raise InstrumentIdentityValidationError("mapping_id must be a MappingId")
        if not isinstance(self.instrument_id, InstrumentId):
            raise InstrumentIdentityValidationError("instrument_id must be an InstrumentId")
        if not isinstance(self.external_identifier, ExternalIdentifier):
            raise InstrumentIdentityValidationError(
                "external_identifier must be an ExternalIdentifier"
            )
        valid_from_utc = require_utc_datetime(self.valid_from, field_name="valid_from")
        valid_to_utc = (
            None
            if self.valid_to is None
            else require_utc_datetime(self.valid_to, field_name="valid_to")
        )
        if valid_to_utc is not None and valid_to_utc <= valid_from_utc:
            raise InstrumentIdentityValidationError(
                "valid_to must be later than valid_from for a half-open interval"
            )
        if not isinstance(self.source, str) or _ATTRIBUTION_PATTERN.fullmatch(self.source) is None:
            raise InstrumentIdentityValidationError("source must be a stable attribution token")
        if (
            not isinstance(self.source_revision, str)
            or _ATTRIBUTION_PATTERN.fullmatch(self.source_revision) is None
        ):
            raise InstrumentIdentityValidationError(
                "source_revision must be a stable attribution token"
            )
        if self.supersedes_mapping_id is not None and not isinstance(
            self.supersedes_mapping_id, MappingId
        ):
            raise InstrumentIdentityValidationError("supersedes_mapping_id must be a MappingId")
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

    def is_valid_at(self, valid_at: datetime) -> bool:
        """Return whether ``valid_at`` lies in the mapping's half-open UTC interval."""
        valid_at_utc = require_utc_datetime(valid_at, field_name="valid_at")
        return self.valid_from <= valid_at_utc and (
            self.valid_to is None or valid_at_utc < self.valid_to
        )
