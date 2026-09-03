"""Resolve temporal symbology through retained immutable mapping assertions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from alpha_research.instrument_identity.models import (
    ExternalIdentifier,
    IdentifierQuery,
    IdentifierScheme,
    InstrumentId,
    InstrumentIdentity,
    InstrumentIdentityValidationError,
    InstrumentKind,
    MappingId,
    SymbologyMapping,
    require_utc_datetime,
)


class UnknownInstrumentError(InstrumentIdentityValidationError):
    """Report a lookup for an unregistered canonical instrument ID."""


class UnknownIdentifierError(InstrumentIdentityValidationError):
    """Report an external identifier with no valid current assertion."""


class AmbiguousIdentifierError(InstrumentIdentityValidationError):
    """Report a lookup matching more than one canonical instrument."""


@dataclass(frozen=True, slots=True)
class SymbologyCatalog:
    """Hold one immutable projection of canonical identities and mapping history.

    Corrections remain in ``mappings`` and superseded assertions are excluded from
    the current projection. Knowledge-time selection of historical catalog states
    is deliberately outside C01 and belongs to the C04 bitemporal contract.
    """

    identities: tuple[InstrumentIdentity, ...]
    mappings: tuple[SymbologyMapping, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identities, tuple) or not all(
            isinstance(identity, InstrumentIdentity) for identity in self.identities
        ):
            raise InstrumentIdentityValidationError(
                "identities must be an immutable tuple of InstrumentIdentity values"
            )
        if not self.identities:
            raise InstrumentIdentityValidationError("catalog must contain an identity")
        if not isinstance(self.mappings, tuple) or not all(
            isinstance(mapping, SymbologyMapping) for mapping in self.mappings
        ):
            raise InstrumentIdentityValidationError(
                "mappings must be an immutable tuple of SymbologyMapping values"
            )
        self._validate_identity_graph()
        self._validate_mapping_graph()

    def _validate_identity_graph(self) -> None:
        identities_by_instrument_id = {
            identity.instrument_id: identity for identity in self.identities
        }
        if len(identities_by_instrument_id) != len(self.identities):
            raise InstrumentIdentityValidationError("instrument IDs must be unique")
        for identity in self.identities:
            economic_instrument = identities_by_instrument_id.get(identity.economic_instrument_id)
            if economic_instrument is None:
                raise InstrumentIdentityValidationError(
                    f"{identity.instrument_id}: economic instrument is not registered"
                )
            if economic_instrument.instrument_kind is not InstrumentKind.ECONOMIC_INSTRUMENT:
                raise InstrumentIdentityValidationError(
                    f"{identity.instrument_id}: economic root must have economic_instrument kind"
                )

    def _validate_mapping_graph(self) -> None:
        registered_instrument_ids = {identity.instrument_id for identity in self.identities}
        mappings_by_mapping_id = {mapping.mapping_id: mapping for mapping in self.mappings}
        if len(mappings_by_mapping_id) != len(self.mappings):
            raise InstrumentIdentityValidationError("mapping IDs must be unique")

        correction_successor_by_mapping_id: dict[MappingId, MappingId] = {}
        for mapping in self.mappings:
            if mapping.instrument_id not in registered_instrument_ids:
                raise InstrumentIdentityValidationError(
                    f"{mapping.mapping_id}: mapped instrument is not registered"
                )
            if mapping.supersedes_mapping_id is None:
                continue
            superseded_mapping = mappings_by_mapping_id.get(mapping.supersedes_mapping_id)
            if superseded_mapping is None:
                raise InstrumentIdentityValidationError(
                    f"{mapping.mapping_id}: superseded mapping is not retained"
                )
            if (
                superseded_mapping.external_identifier != mapping.external_identifier
                or superseded_mapping.source != mapping.source
            ):
                raise InstrumentIdentityValidationError(
                    f"{mapping.mapping_id}: a correction must preserve identifier and source"
                )
            if superseded_mapping.source_revision == mapping.source_revision:
                raise InstrumentIdentityValidationError(
                    f"{mapping.mapping_id}: a correction requires a new source revision"
                )
            if mapping.supersedes_mapping_id in correction_successor_by_mapping_id:
                raise InstrumentIdentityValidationError(
                    f"{mapping.supersedes_mapping_id}: correction history cannot fork"
                )
            correction_successor_by_mapping_id[mapping.supersedes_mapping_id] = mapping.mapping_id

        for mapping in self.mappings:
            visited_mapping_ids: set[MappingId] = set()
            current_mapping = mapping
            while current_mapping.supersedes_mapping_id is not None:
                if current_mapping.mapping_id in visited_mapping_ids:
                    raise InstrumentIdentityValidationError(
                        "correction history cannot contain a cycle"
                    )
                visited_mapping_ids.add(current_mapping.mapping_id)
                current_mapping = mappings_by_mapping_id[current_mapping.supersedes_mapping_id]

        current_projection_mappings = tuple(
            mapping
            for mapping in self.mappings
            if mapping.mapping_id not in correction_successor_by_mapping_id
        )
        mappings_by_identifier: dict[ExternalIdentifier, list[SymbologyMapping]] = {}
        for mapping in current_projection_mappings:
            mappings_by_identifier.setdefault(mapping.external_identifier, []).append(mapping)
        for external_identifier, identifier_mappings in mappings_by_identifier.items():
            chronologically_ordered_mappings = sorted(
                identifier_mappings,
                key=lambda mapping: (mapping.valid_from, str(mapping.mapping_id)),
            )
            previous_mapping: SymbologyMapping | None = None
            for mapping in chronologically_ordered_mappings:
                if previous_mapping is not None and (
                    previous_mapping.valid_to is None
                    or mapping.valid_from < previous_mapping.valid_to
                ):
                    raise InstrumentIdentityValidationError(
                        f"{external_identifier.scheme.value} "
                        f"{external_identifier.value!r} has overlapping "
                        "current mappings"
                    )
                previous_mapping = mapping

    def _superseded_mapping_ids(self) -> frozenset[MappingId]:
        return frozenset(
            mapping.supersedes_mapping_id
            for mapping in self.mappings
            if mapping.supersedes_mapping_id is not None
        )

    def current_projection_mappings(self) -> tuple[SymbologyMapping, ...]:
        """Return the deterministic current projection while retaining all history."""
        superseded_mapping_ids = self._superseded_mapping_ids()
        return tuple(
            sorted(
                (
                    mapping
                    for mapping in self.mappings
                    if mapping.mapping_id not in superseded_mapping_ids
                ),
                key=lambda mapping: (
                    mapping.external_identifier.scheme.value,
                    mapping.external_identifier.namespace or "",
                    mapping.external_identifier.value,
                    mapping.valid_from,
                    str(mapping.mapping_id),
                ),
            )
        )

    def get_instrument_identity(self, instrument_id: InstrumentId) -> InstrumentIdentity:
        """Return one canonical identity, failing closed when it is unknown."""
        if not isinstance(instrument_id, InstrumentId):
            raise InstrumentIdentityValidationError("instrument_id must be an InstrumentId")
        for identity in self.identities:
            if identity.instrument_id == instrument_id:
                return identity
        raise UnknownInstrumentError(f"unknown instrument ID {instrument_id}")

    def resolve_identifier_at(
        self, identifier_query: IdentifierQuery, *, valid_at: datetime
    ) -> SymbologyMapping:
        """Resolve an identifier at one UTC valid-time instant.

        A query without a namespace deliberately searches every namespace. If
        more than one current mapping is valid, resolution raises instead of
        selecting a provider or venue implicitly.
        """
        if not isinstance(identifier_query, IdentifierQuery):
            raise InstrumentIdentityValidationError("identifier_query must be an IdentifierQuery")
        valid_at_utc = require_utc_datetime(valid_at, field_name="valid_at")
        matching_mappings = tuple(
            mapping
            for mapping in self.current_projection_mappings()
            if identifier_query.matches_identifier(mapping.external_identifier)
            and mapping.is_valid_at(valid_at_utc)
        )
        if not matching_mappings:
            raise UnknownIdentifierError(
                f"no {identifier_query.scheme.value} mapping is valid for "
                f"{identifier_query.value!r} at {valid_at_utc.isoformat()}"
            )
        if len(matching_mappings) != 1:
            raise AmbiguousIdentifierError(
                f"{identifier_query.scheme.value} {identifier_query.value!r} is ambiguous "
                f"across {len(matching_mappings)} mappings"
            )
        return matching_mappings[0]

    def get_identifier_mappings_for_instrument(
        self,
        instrument_id: InstrumentId,
        *,
        valid_at: datetime,
        identifier_scheme: IdentifierScheme | None = None,
    ) -> tuple[SymbologyMapping, ...]:
        """Return current identifiers for a canonical instrument at valid time."""
        self.get_instrument_identity(instrument_id)
        valid_at_utc = require_utc_datetime(valid_at, field_name="valid_at")
        if identifier_scheme is not None and not isinstance(identifier_scheme, IdentifierScheme):
            raise InstrumentIdentityValidationError("identifier_scheme must be an IdentifierScheme")
        return tuple(
            mapping
            for mapping in self.current_projection_mappings()
            if mapping.instrument_id == instrument_id
            and (
                identifier_scheme is None or mapping.external_identifier.scheme is identifier_scheme
            )
            and mapping.is_valid_at(valid_at_utc)
        )

    def get_mapping_history_for_identifier(
        self, external_identifier: ExternalIdentifier
    ) -> tuple[SymbologyMapping, ...]:
        """Return every retained assertion for one exact identifier."""
        if not isinstance(external_identifier, ExternalIdentifier):
            raise InstrumentIdentityValidationError(
                "external_identifier must be an ExternalIdentifier"
            )
        mappings_by_mapping_id = {mapping.mapping_id: mapping for mapping in self.mappings}

        def correction_depth_for_mapping(mapping: SymbologyMapping) -> int:
            correction_depth = 0
            current_mapping = mapping
            while current_mapping.supersedes_mapping_id is not None:
                correction_depth += 1
                current_mapping = mappings_by_mapping_id[current_mapping.supersedes_mapping_id]
            return correction_depth

        return tuple(
            sorted(
                (
                    mapping
                    for mapping in self.mappings
                    if mapping.external_identifier == external_identifier
                ),
                key=lambda mapping: (
                    mapping.valid_from,
                    correction_depth_for_mapping(mapping),
                    str(mapping.mapping_id),
                ),
            )
        )
