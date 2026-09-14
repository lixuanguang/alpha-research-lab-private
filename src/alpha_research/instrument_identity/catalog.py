"""Resolve temporal symbology through retained immutable mapping assertions."""

from __future__ import annotations

# standard library imports
from datetime import datetime
from functools import partial
from typing import Self

# third party library imports
from pydantic import field_validator, model_validator

# project library imports
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
    _InstrumentIdentityModel,
)


class UnknownInstrumentError(InstrumentIdentityValidationError):
    """Report a lookup for an unregistered canonical instrument ID."""


class UnknownIdentifierError(InstrumentIdentityValidationError):
    """Report an external identifier with no valid current assertion."""


class AmbiguousIdentifierError(InstrumentIdentityValidationError):
    """Report a lookup matching more than one canonical instrument."""


class SymbologyCatalog(_InstrumentIdentityModel):
    """Hold one immutable projection of canonical identities and mapping history.

    Corrections remain in ``mappings`` and superseded assertions are excluded from
    the current projection. Knowledge-time selection of historical catalog states
    is deliberately outside C01 and belongs to the C04 bitemporal contract.
    """

    identities: tuple[InstrumentIdentity, ...]
    mappings: tuple[SymbologyMapping, ...]

    def __init__(
        self,
        identities: tuple[InstrumentIdentity, ...],
        mappings: tuple[SymbologyMapping, ...],
        **extra: object,
    ) -> None:
        """Validate an immutable identity graph and its retained mapping assertions.

        Args:
            identities: Nonempty tuple with unique IDs and registered economic roots.
            mappings: Tuple of assertions, including superseded history; may be empty.
                Current intervals for each exact identifier must not overlap.
            **extra: Unknown constructor fields, rejected by strict validation.

        Raises:
            InstrumentIdentityValidationError: Fields, references, correction chains,
                or current mapping intervals violate the catalog invariants.
        """
        super().__init__(identities=identities, mappings=mappings, **extra)

    @field_validator("identities", mode="before")
    @classmethod
    def valid_identities(cls, value: object) -> tuple[InstrumentIdentity, ...]:
        """Require a populated immutable sequence of validated identities.

        Args:
            value: Raw identities field before nested field validation.

        Returns:
            The original nonempty tuple of InstrumentIdentity instances.

        Raises:
            InstrumentIdentityValidationError: The value is empty, is not a tuple,
                or contains an item of the wrong type.
        """
        if not isinstance(value, tuple) or not all(
            isinstance(identity, InstrumentIdentity) for identity in value
        ):
            raise InstrumentIdentityValidationError(
                "identities must be an immutable tuple of InstrumentIdentity values"
            )
        if not value:
            raise InstrumentIdentityValidationError("catalog must contain an identity")
        return value

    @field_validator("mappings", mode="before")
    @classmethod
    def valid_mappings(cls, value: object) -> tuple[SymbologyMapping, ...]:
        """Require an immutable sequence of validated mapping assertions.

        Args:
            value: Raw mappings field before nested field validation.

        Returns:
            The original tuple of SymbologyMapping instances, including an empty tuple.

        Raises:
            InstrumentIdentityValidationError: The value is not a tuple or contains
                an item of the wrong type.
        """
        if not isinstance(value, tuple) or not all(
            isinstance(mapping, SymbologyMapping) for mapping in value
        ):
            raise InstrumentIdentityValidationError(
                "mappings must be an immutable tuple of SymbologyMapping values"
            )
        return value

    @model_validator(mode="after")
    def coherent_graph(self) -> Self:
        """Validate canonical identity, mapping, interval, and correction graphs.

        Returns:
            This catalog unchanged after validating both graphs.

        Raises:
            InstrumentIdentityValidationError: IDs are duplicated; references or
                economic roots are invalid; a correction changes its identifier or
                source, lacks a new revision, forks, or cycles; or current intervals
                for an exact identifier overlap.
        """
        self._validate_identity_graph()
        self._validate_mapping_graph()
        return self

    def _validate_identity_graph(self) -> None:
        """Reject duplicate IDs and missing or incorrectly typed economic roots."""
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
        """Reject broken references, invalid correction chains, and current interval overlap."""
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
                key=self._chronological_mapping_order,
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
        """Collect every predecessor explicitly replaced by a retained correction."""
        return frozenset(
            mapping.supersedes_mapping_id
            for mapping in self.mappings
            if mapping.supersedes_mapping_id is not None
        )

    def current_projection_mappings(self) -> tuple[SymbologyMapping, ...]:
        """Return the deterministic current projection while retaining all history.

        Returns:
            Unsuperseded assertions ordered by scheme, namespace, identifier value,
            valid-from instant, and mapping ID. This removes corrected predecessors
            without filtering valid time or selecting a historical knowledge time.
            The retained ``mappings`` tuple is unchanged.
        """
        superseded_mapping_ids = self._superseded_mapping_ids()

        return tuple(
            sorted(
                (
                    mapping
                    for mapping in self.mappings
                    if mapping.mapping_id not in superseded_mapping_ids
                ),
                key=self._projection_mapping_order,
            )
        )

    def get_instrument_identity(self, instrument_id: InstrumentId) -> InstrumentIdentity:
        """Return one canonical identity, failing closed when it is unknown.

        Args:
            instrument_id: Owned canonical instrument ID to find.

        Returns:
            The registered immutable identity with that ID.

        Raises:
            InstrumentIdentityValidationError: The argument is not an InstrumentId.
            UnknownInstrumentError: No identity is registered under the ID.
        """
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

        Args:
            identifier_query: Scheme, value, and optional exact namespace to match.
            valid_at: Aware datetime with zero UTC offset; other offsets are rejected.
                Intervals include ``valid_from`` and exclude a non-null ``valid_to``.

        Returns:
            The single unsuperseded assertion matching the query at valid time.

        Raises:
            InstrumentIdentityValidationError: The query type or UTC instant is invalid.
            UnknownIdentifierError: No current assertion matches at that instant.
            AmbiguousIdentifierError: More than one current assertion matches,
                even if the assertions refer to the same instrument.
        """
        if not isinstance(identifier_query, IdentifierQuery):
            raise InstrumentIdentityValidationError("identifier_query must be an IdentifierQuery")
        valid_at_utc = _InstrumentIdentityModel._require_utc_datetime(
            valid_at, field_name="valid_at"
        )
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
        """Return current identifiers for a canonical instrument at valid time.

        Args:
            instrument_id: Registered canonical ID whose identifiers are requested.
            valid_at: Aware zero-offset UTC instant for the half-open valid intervals.
            identifier_scheme: Optional scheme filter; None includes every scheme.

        Returns:
            Matching unsuperseded assertions in current-projection order; an empty
            tuple when the registered instrument has no matching valid identifiers.

        Raises:
            InstrumentIdentityValidationError: An argument type or UTC instant is invalid.
            UnknownInstrumentError: The canonical instrument is not registered.
        """
        self.get_instrument_identity(instrument_id)
        valid_at_utc = _InstrumentIdentityModel._require_utc_datetime(
            valid_at, field_name="valid_at"
        )
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
        """Return every retained assertion for one exact identifier.

        Args:
            external_identifier: Exact scheme, value, and namespace whose history
                is requested; this does not perform a wildcard namespace search.

        Returns:
            All matching assertions, including superseded ones, ordered by valid-from
            instant, correction depth, and mapping ID. Unknown identifiers return
            an empty tuple; no valid-time or knowledge-time filtering is applied.

        Raises:
            InstrumentIdentityValidationError: The argument is not an ExternalIdentifier.
        """
        if not isinstance(external_identifier, ExternalIdentifier):
            raise InstrumentIdentityValidationError(
                "external_identifier must be an ExternalIdentifier"
            )
        mappings_by_mapping_id = {mapping.mapping_id: mapping for mapping in self.mappings}

        return tuple(
            sorted(
                (
                    mapping
                    for mapping in self.mappings
                    if mapping.external_identifier == external_identifier
                ),
                key=partial(
                    self._history_mapping_order, mappings_by_mapping_id=mappings_by_mapping_id
                ),
            )
        )

    @staticmethod
    def _chronological_mapping_order(mapping: SymbologyMapping) -> tuple[datetime, str]:
        """Order current mappings by valid-from instant and mapping ID."""
        return mapping.valid_from, str(mapping.mapping_id)

    @staticmethod
    def _projection_mapping_order(mapping: SymbologyMapping) -> tuple[str, str, str, datetime, str]:
        """Build a stable key for one current mapping assertion.

        Args:
            mapping: Mapping assertion to order within the current projection.

        Returns:
            Scheme, namespace, identifier, valid-from instant, and mapping ID.
        """
        return (
            mapping.external_identifier.scheme.value,
            mapping.external_identifier.namespace or "",
            mapping.external_identifier.value,
            mapping.valid_from,
            str(mapping.mapping_id),
        )

    @staticmethod
    def _correction_depth_for_mapping(
        mapping: SymbologyMapping, *, mappings_by_mapping_id: dict[MappingId, SymbologyMapping]
    ) -> int:
        """Count retained predecessors for ordering one validated correction chain.

        Args:
            mapping: Assertion from this catalog's validated acyclic mapping graph.
            mappings_by_mapping_id: Index local to the current history query.

        Returns:
            Zero for an original assertion, otherwise the number of predecessors.
        """
        correction_depth = 0
        current_mapping = mapping
        while current_mapping.supersedes_mapping_id is not None:
            correction_depth += 1
            current_mapping = mappings_by_mapping_id[current_mapping.supersedes_mapping_id]
        return correction_depth

    @staticmethod
    def _history_mapping_order(
        mapping: SymbologyMapping, *, mappings_by_mapping_id: dict[MappingId, SymbologyMapping]
    ) -> tuple[datetime, int, str]:
        """Build a stable key for one mapping-history assertion.

        Args:
            mapping: Mapping assertion to order within the retained history.
            mappings_by_mapping_id: Index local to the current history query.

        Returns:
            Valid-from instant, correction depth, and mapping ID.
        """
        return (
            mapping.valid_from,
            SymbologyCatalog._correction_depth_for_mapping(
                mapping, mappings_by_mapping_id=mappings_by_mapping_id
            ),
            str(mapping.mapping_id),
        )
