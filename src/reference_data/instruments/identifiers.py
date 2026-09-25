"""Define external identifier, query, and validity-dated symbology contracts."""

from __future__ import annotations

# standard library imports
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Self

# third party library imports
from pydantic import ValidationInfo, field_validator, model_validator

# project library imports
from reference_data.instruments.identity import (
    InstrumentId,
    InstrumentIdentityValidationError,
    MappingId,
    _InstrumentIdentityModel,
)


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


class _IdentifierFields:
    """Own exact identifier checksum and namespace mechanics for records and queries."""

    @staticmethod
    def _validate_identifier_namespace(
        candidate_namespace: object, *, namespace_required: bool
    ) -> str | None:
        """Validate a lowercase namespace token, enforcing presence when requested."""
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

    @staticmethod
    def _has_valid_luhn_checksum(decimal_digits: str) -> bool:
        """Check the Luhn sum of the supplied decimal digit string."""
        checksum_total = 0
        for digit_position, digit_character in enumerate(reversed(decimal_digits)):
            digit_value = int(digit_character)
            if digit_position % 2 == 1:
                digit_value *= 2
            checksum_total += digit_value // 10 + digit_value % 10
        return checksum_total % 10 == 0

    @staticmethod
    def _has_valid_isin_checksum(identifier_value: str) -> bool:
        """Check uppercase ISIN shape and the Luhn sum of expanded characters."""
        if _ISIN_PATTERN.fullmatch(identifier_value) is None:
            return False
        expanded_digits = "".join(
            str(ord(character) - 55) if character.isalpha() else character
            for character in identifier_value
        )
        return _IdentifierFields._has_valid_luhn_checksum(expanded_digits)

    @staticmethod
    def _cusip_character_numeric_value(identifier_character: str) -> int:
        """Map an admitted CUSIP digit, uppercase letter or special character to its weight."""
        if identifier_character.isdigit():
            return int(identifier_character)
        if identifier_character.isalpha():
            return ord(identifier_character) - 55
        return {"*": 36, "@": 37, "#": 38}[identifier_character]

    @staticmethod
    def _has_valid_cusip_checksum(identifier_value: str) -> bool:
        """Check CUSIP shape and the alternating-weight check digit."""
        if _CUSIP_PATTERN.fullmatch(identifier_value) is None:
            return False
        checksum_total = 0
        for character_position, identifier_character in enumerate(identifier_value[:8]):
            weighted_value = _IdentifierFields._cusip_character_numeric_value(
                identifier_character
            ) * (1 if character_position % 2 == 0 else 2)
            checksum_total += weighted_value // 10 + weighted_value % 10
        return (10 - checksum_total % 10) % 10 == int(identifier_value[-1])

    @staticmethod
    def _has_valid_sedol_checksum(identifier_value: str) -> bool:
        """Check SEDOL shape and the weighted check digit, excluding vowels."""
        if _SEDOL_PATTERN.fullmatch(identifier_value) is None:
            return False
        checksum_weights = (1, 3, 1, 7, 3, 9)
        checksum_total = sum(
            _IdentifierFields._cusip_character_numeric_value(identifier_character) * checksum_weight
            for identifier_character, checksum_weight in zip(
                identifier_value[:6], checksum_weights, strict=True
            )
        )
        return (10 - checksum_total % 10) % 10 == int(identifier_value[-1])

    @staticmethod
    def _validate_identifier_value(
        identifier_scheme: IdentifierScheme, candidate_value: object
    ) -> str:
        """Validate bounded exact text and the checksum required by its global scheme."""
        identifier_value = _InstrumentIdentityModel._require_bounded_text(
            candidate_value, field_name="identifier value", maximum_length=256
        )
        checksum_validators = {
            IdentifierScheme.ISIN: (
                _IdentifierFields._has_valid_isin_checksum,
                "valid uppercase ISIN with checksum",
            ),
            IdentifierScheme.CUSIP: (
                _IdentifierFields._has_valid_cusip_checksum,
                "valid uppercase CUSIP with checksum",
            ),
            IdentifierScheme.SEDOL: (
                _IdentifierFields._has_valid_sedol_checksum,
                "valid uppercase SEDOL with checksum",
            ),
        }
        checksum_validator_and_requirement = checksum_validators.get(identifier_scheme)
        if checksum_validator_and_requirement is not None:
            checksum_validator, requirement_description = checksum_validator_and_requirement
            if not checksum_validator(identifier_value):
                raise InstrumentIdentityValidationError(
                    f"{identifier_scheme.value} identifier must be a {requirement_description}"
                )
        return identifier_value


class ExternalIdentifier(_InstrumentIdentityModel):
    """Represent an exact adapter-boundary identifier without normalizing its value.

    Attributes:
        scheme: Typed global or provider-local identifier family.
        value: Exact text up to 256 characters; global schemes require valid uppercase
            checksums.
        namespace: Required provider-local token; forbidden for ISIN, CUSIP and SEDOL.
    """

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
        """Validate an exact identifier and its namespace rules.

        Args:
            scheme: IdentifierScheme member; raw strings are rejected.
            value: Unpadded text up to 256 characters; global identifiers require valid
                checksums.
            namespace: Required for local schemes and forbidden for global schemes.
            extra: Additional keyword fields; rejected by the closed schema.

        Raises:
            InstrumentIdentityValidationError: A field, scheme-specific checksum or namespace
                constraint is invalid.
        """
        super().__init__(scheme=scheme, value=value, namespace=namespace, **extra)

    @field_validator("scheme", mode="before")
    @classmethod
    def valid_scheme(cls, value: object) -> IdentifierScheme:
        """Require a typed identifier scheme without coercing strings.

        Raises:
            InstrumentIdentityValidationError: The value is not an IdentifierScheme.
        """
        if not isinstance(value, IdentifierScheme):
            raise InstrumentIdentityValidationError("identifier scheme must be an IdentifierScheme")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def bounded_value(cls, value: object) -> str:
        """Require an exact bounded identifier string.

        Args:
            value: Candidate unpadded nonempty text, up to 256 characters.

        Returns:
            The original string, preserving case and internal spacing.

        Raises:
            InstrumentIdentityValidationError: The value is not bounded text or contains
                control, format or surrogate characters.
        """
        return _InstrumentIdentityModel._require_bounded_text(
            value, field_name="identifier value", maximum_length=256
        )

    @field_validator("namespace", mode="before")
    @classmethod
    def valid_namespace_token(cls, value: object) -> str | None:
        """Require a canonical namespace token when one is supplied.

        Args:
            value: None or a token starting with a lowercase ASCII letter or digit, using a-z,
                0-9 or ._-.

        Returns:
            The original namespace, up to 64 characters, or None.

        Raises:
            InstrumentIdentityValidationError: A supplied namespace does not match the token
                syntax.
        """
        return _IdentifierFields._validate_identifier_namespace(value, namespace_required=False)

    @model_validator(mode="after")
    def coherent_identifier(self) -> Self:
        """Validate scheme-specific value and namespace rules.

        Returns:
            This identifier with its value preserved exactly.

        Raises:
            InstrumentIdentityValidationError: A checksum fails, a local namespace is absent, or
                a global namespace is supplied.
        """
        _IdentifierFields._validate_identifier_value(self.scheme, self.value)
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
    """Represent an exact or intentionally namespace-broad temporal lookup.

    Omitting the namespace admits all namespaces for the same scheme and exact
    value. Matching alone does not establish uniqueness or temporal validity.

    Attributes:
        scheme: Typed external identifier family.
        value: Exact bounded text with the same checksum rules as ExternalIdentifier.
        namespace: Optional exact provider scope; forbidden for global schemes.
    """

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
        """Validate an exact query and its namespace rules.

        Args:
            scheme: IdentifierScheme member; raw strings are rejected.
            value: Unpadded text up to 256 characters; global identifiers require valid
                checksums.
            namespace: Exact local scope, or None to admit every namespace; forbidden for global
                schemes.
            extra: Additional keyword fields; rejected by the closed schema.

        Raises:
            InstrumentIdentityValidationError: A field, scheme-specific checksum or namespace
                constraint is invalid.
        """
        super().__init__(scheme=scheme, value=value, namespace=namespace, **extra)

    @field_validator("scheme", mode="before")
    @classmethod
    def valid_scheme(cls, value: object) -> IdentifierScheme:
        """Require a typed identifier scheme without coercing strings.

        Raises:
            InstrumentIdentityValidationError: The value is not an IdentifierScheme.
        """
        if not isinstance(value, IdentifierScheme):
            raise InstrumentIdentityValidationError("query scheme must be an IdentifierScheme")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def bounded_value(cls, value: object) -> str:
        """Require an exact bounded identifier string.

        Args:
            value: Candidate unpadded nonempty text, up to 256 characters.

        Returns:
            The original string, preserving case and internal spacing.

        Raises:
            InstrumentIdentityValidationError: The value is not bounded text or contains
                control, format or surrogate characters.
        """
        return _InstrumentIdentityModel._require_bounded_text(
            value, field_name="identifier value", maximum_length=256
        )

    @field_validator("namespace", mode="before")
    @classmethod
    def valid_namespace_token(cls, value: object) -> str | None:
        """Require a canonical namespace token when one is supplied.

        Args:
            value: None or a token starting with a lowercase ASCII letter or digit, using a-z,
                0-9 or ._-.

        Returns:
            The original namespace, up to 64 characters, or None.

        Raises:
            InstrumentIdentityValidationError: A supplied namespace does not match the token
                syntax.
        """
        return _IdentifierFields._validate_identifier_namespace(value, namespace_required=False)

    @model_validator(mode="after")
    def coherent_query(self) -> Self:
        """Validate scheme-specific query value and namespace rules.

        Returns:
            This query; a missing local namespace retains its broad scope.

        Raises:
            InstrumentIdentityValidationError: A global checksum fails or a global scheme
                carries a namespace.
        """
        _IdentifierFields._validate_identifier_value(self.scheme, self.value)
        if self.scheme in _GLOBAL_SCHEMES and self.namespace is not None:
            raise InstrumentIdentityValidationError(
                f"{self.scheme.value} queries cannot carry a provider namespace"
            )
        return self

    @classmethod
    def for_exact_identifier(cls, external_identifier: ExternalIdentifier) -> IdentifierQuery:
        """Build an exact query from a validated external identifier.

        Args:
            external_identifier: Owned identifier whose scheme, value and namespace are copied.

        Returns:
            A validated query restricted to that identifier.

        Raises:
            InstrumentIdentityValidationError: The input is not an ExternalIdentifier or its
                fields fail validation.
        """
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
        """Return whether the identifier is within this query's explicit scope.

        Args:
            external_identifier: Validated identifier to compare; no temporal lookup is
                performed.

        Returns:
            True when scheme and value match and the namespace is equal or unspecified.
        """
        return (
            self.scheme is external_identifier.scheme
            and self.value == external_identifier.value
            and (self.namespace is None or self.namespace == external_identifier.namespace)
        )


class SymbologyMapping(_InstrumentIdentityModel):
    """Record one immutable, validity-dated, source-attributed mapping assertion.

    The interval describes valid time, not when the assertion became known.
    Correction-chain existence, cycles and catalog consistency are checked by
    SymbologyCatalog; constructing a mapping does not resolve those references.

    Attributes:
        mapping_id: Stable identity of this retained assertion.
        instrument_id: Canonical concept to which the identifier maps.
        external_identifier: Exact identifier including any required namespace.
        valid_from: Inclusive aware UTC start of valid time.
        valid_to: Exclusive aware UTC end, or None for an unbounded future.
        source: Stable attribution token, up to 128 characters.
        source_revision: Stable revision token, up to 128 characters.
        supersedes_mapping_id: Optional link to the assertion being corrected.
        correction_reason: Required bounded explanation exactly when a correction link
            exists.
    """

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
        """Preserve correction coupling errors before primitive type validation.

        Args:
            value: Raw model input; mapping inputs expose correction metadata for checking.

        Returns:
            The original input, unchanged, for subsequent field validation.

        Raises:
            InstrumentIdentityValidationError: A reason lacks a correction link, or a linked
                correction lacks a valid reason.
        """
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
            _InstrumentIdentityModel._require_bounded_text(
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
        """Validate one assertion without resolving catalog references.

        Args:
            mapping_id: Validated stable assertion ID.
            instrument_id: Validated canonical instrument ID.
            external_identifier: Validated exact external identifier.
            valid_from: Inclusive aware UTC validity start.
            valid_to: Exclusive aware UTC end later than the start, or None.
            source: Attribution token using ASCII letters, digits and ._:/-; up to 128
                characters.
            source_revision: Revision token with the same source-token syntax.
            supersedes_mapping_id: Optional validated ID of an earlier assertion.
            correction_reason: Required with a correction link; unpadded text up to 512
                characters.
            extra: Additional keyword fields; rejected by the closed schema.

        Raises:
            InstrumentIdentityValidationError: A field, validity interval or correction-metadata
                contract is invalid.
        """
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
        """Require an owned mapping_id value without coercion.

        Args:
            value: Candidate MappingId for mapping_id.

        Returns:
            The original MappingId for subsequent validation.

        Raises:
            InstrumentIdentityValidationError: The value is not a MappingId.
        """
        if not isinstance(value, MappingId):
            raise InstrumentIdentityValidationError("mapping_id must be a MappingId")
        return value

    @field_validator("instrument_id", mode="before")
    @classmethod
    def valid_instrument_id(cls, value: object) -> InstrumentId:
        """Require an owned instrument_id value without coercion.

        Args:
            value: Candidate InstrumentId for instrument_id.

        Returns:
            The original InstrumentId for subsequent validation.

        Raises:
            InstrumentIdentityValidationError: The value is not a InstrumentId.
        """
        if not isinstance(value, InstrumentId):
            raise InstrumentIdentityValidationError("instrument_id must be an InstrumentId")
        return value

    @field_validator("external_identifier", mode="before")
    @classmethod
    def valid_external_identifier(cls, value: object) -> ExternalIdentifier:
        """Require an owned external_identifier value without coercion.

        Args:
            value: Candidate ExternalIdentifier for external_identifier.

        Returns:
            The original ExternalIdentifier for subsequent validation.

        Raises:
            InstrumentIdentityValidationError: The value is not a ExternalIdentifier.
        """
        if not isinstance(value, ExternalIdentifier):
            raise InstrumentIdentityValidationError(
                "external_identifier must be an ExternalIdentifier"
            )
        return value

    @field_validator("valid_from", mode="before")
    @classmethod
    def valid_start(cls, value: object) -> datetime:
        """Require an aware UTC interval start.

        Args:
            value: Candidate inclusive start, with zero UTC offset.

        Returns:
            The original UTC datetime.

        Raises:
            InstrumentIdentityValidationError: The value is not an aware datetime with a zero
                UTC offset.
        """
        return _InstrumentIdentityModel._require_utc_datetime(value, field_name="valid_from")

    @field_validator("valid_to", mode="before")
    @classmethod
    def valid_end(cls, value: object) -> datetime | None:
        """Require an aware UTC interval end when supplied.

        Args:
            value: Candidate exclusive end, or None for unbounded validity.

        Returns:
            The original UTC datetime or None; ordering is checked at model level.

        Raises:
            InstrumentIdentityValidationError: A supplied end is not an aware datetime with a
                zero UTC offset.
        """
        return (
            None
            if value is None
            else _InstrumentIdentityModel._require_utc_datetime(value, field_name="valid_to")
        )

    @field_validator("source", "source_revision", mode="before")
    @classmethod
    def stable_attribution(cls, value: object, info: ValidationInfo[object]) -> str:
        """Require stable source-attribution tokens.

        Args:
            value: ASCII token starting with a letter or digit and using letters, digits or
                ._:/-.
            info: Pydantic field metadata used to identify source or source_revision in errors.

        Returns:
            The original token, bounded to 128 characters.

        Raises:
            InstrumentIdentityValidationError: The value is not a string matching the
                attribution-token syntax.
        """
        if not isinstance(value, str) or _ATTRIBUTION_PATTERN.fullmatch(value) is None:
            raise InstrumentIdentityValidationError(
                f"{info.field_name} must be a stable attribution token"
            )
        return value

    @field_validator("supersedes_mapping_id", mode="before")
    @classmethod
    def valid_superseded_mapping_id(cls, value: object) -> MappingId | None:
        """Reject unvalidated correction links.

        Args:
            value: MappingId of the corrected assertion, or None for an original assertion.

        Returns:
            The supplied MappingId or None without resolving the link.

        Raises:
            InstrumentIdentityValidationError: A supplied link is not a MappingId.
        """
        if value is not None and not isinstance(value, MappingId):
            raise InstrumentIdentityValidationError("supersedes_mapping_id must be a MappingId")
        return value

    @model_validator(mode="after")
    def coherent_interval_and_correction(self) -> Self:
        """Validate interval ordering and correction metadata coupling.

        Returns:
            This mapping after checking its local invariants.

        Raises:
            InstrumentIdentityValidationError: The interval is empty or reversed, or the
                link/reason pair is invalid.
        """
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
            _InstrumentIdentityModel._require_bounded_text(
                self.correction_reason,
                field_name="correction_reason",
                maximum_length=512,
            )
        return self

    def is_valid_at(self, valid_at: datetime) -> bool:
        """Return whether ``valid_at`` lies in the mapping's half-open UTC interval.

        Args:
            valid_at: Aware UTC instant to test against valid time; no knowledge-time selection
                occurs.

        Returns:
            True at or after valid_from and strictly before any finite valid_to.

        Raises:
            InstrumentIdentityValidationError: The instant is not an aware datetime with a zero
                UTC offset.
        """
        valid_at_utc = _InstrumentIdentityModel._require_utc_datetime(
            valid_at, field_name="valid_at"
        )
        return self.valid_from <= valid_at_utc and (
            self.valid_to is None or valid_at_utc < self.valid_to
        )
