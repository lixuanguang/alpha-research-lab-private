"""Test the C01 canonical instrument-identity and temporal-symbology contract."""

from __future__ import annotations

# standard library imports
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import cast
from uuid import UUID

# third party library imports
import pytest
from hypothesis import given, settings, strategies
from pydantic import BaseModel, ValidationError

# project library imports
from alpha_research.instrument_identity import (
    AmbiguousIdentifierError,
    ExternalIdentifier,
    IdentifierQuery,
    IdentifierScheme,
    InstrumentId,
    InstrumentIdentity,
    InstrumentIdentityValidationError,
    InstrumentKind,
    MappingId,
    SymbologyCatalog,
    SymbologyMapping,
    UnknownIdentifierError,
    UnknownInstrumentError,
)

INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_PATH = (
    Path(__file__).parents[1] / "golden/instrument_identity/c01_symbology.json"
)


def _fixture_object_rows(
    fixture_document: dict[str, object], field_name: str
) -> list[dict[str, object]]:
    """Read a required fixture array after checking its rows are mappings.

    Args:
        fixture_document: Parsed golden document containing the requested array.
        field_name: Required array key.

    Returns:
        Original list of row dictionaries, without copying or validating row fields.

    Raises:
        KeyError: The array key is absent.
        AssertionError: The value is not a list of dictionaries.
    """
    field_value = fixture_document[field_name]
    assert isinstance(field_value, list)
    assert all(isinstance(fixture_row, dict) for fixture_row in field_value)
    return cast(list[dict[str, object]], field_value)


def _required_fixture_text(fixture_row: dict[str, object], field_name: str) -> str:
    """Read a required string field, asserting its type without coercion."""
    field_value = fixture_row[field_name]
    assert isinstance(field_value, str)
    return field_value


def _optional_fixture_text(fixture_row: dict[str, object], field_name: str) -> str | None:
    """Read a string or null field, treating a missing key as null."""
    field_value = fixture_row.get(field_name)
    assert field_value is None or isinstance(field_value, str)
    return field_value


def _parse_fixture_utc_datetime(utc_datetime_text: str) -> datetime:
    """Parse ISO fixture text, translating a trailing Z to an explicit UTC offset."""
    return datetime.fromisoformat(utc_datetime_text.replace("Z", "+00:00"))


def _load_instrument_identity_golden_catalog() -> tuple[dict[str, object], SymbologyCatalog]:
    """Load the synthetic C01 JSON and construct its validated identity graph.

    Returns:
        Parsed fixture document and catalog retaining the listed correction history.

    Raises:
        OSError: The checked-in fixture cannot be read.
        ValueError: JSON, date, enum or owned identity validation fails.
        KeyError: A consumed required fixture field is absent.
        AssertionError: A consumed fixture container or text field has the wrong type.
    """
    parsed_fixture: object = json.loads(
        INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8")
    )
    assert isinstance(parsed_fixture, dict)
    fixture_document = cast(dict[str, object], parsed_fixture)
    instrument_identities = tuple(
        InstrumentIdentity(
            instrument_id=InstrumentId.from_canonical_text(
                _required_fixture_text(fixture_row, "instrument_id")
            ),
            instrument_kind=InstrumentKind(_required_fixture_text(fixture_row, "instrument_kind")),
            economic_instrument_id=InstrumentId.from_canonical_text(
                _required_fixture_text(fixture_row, "economic_instrument_id")
            ),
        )
        for fixture_row in _fixture_object_rows(fixture_document, "identities")
    )
    symbology_mappings = tuple(
        SymbologyMapping(
            mapping_id=MappingId.from_canonical_text(
                _required_fixture_text(fixture_row, "mapping_id")
            ),
            instrument_id=InstrumentId.from_canonical_text(
                _required_fixture_text(fixture_row, "instrument_id")
            ),
            external_identifier=ExternalIdentifier(
                scheme=IdentifierScheme(_required_fixture_text(fixture_row, "identifier_scheme")),
                value=_required_fixture_text(fixture_row, "identifier_value"),
                namespace=_optional_fixture_text(fixture_row, "identifier_namespace"),
            ),
            valid_from=_parse_fixture_utc_datetime(
                _required_fixture_text(fixture_row, "valid_from")
            ),
            valid_to=(
                None
                if _optional_fixture_text(fixture_row, "valid_to") is None
                else _parse_fixture_utc_datetime(
                    cast(str, _optional_fixture_text(fixture_row, "valid_to"))
                )
            ),
            source=_required_fixture_text(fixture_row, "source"),
            source_revision=_required_fixture_text(fixture_row, "source_revision"),
            supersedes_mapping_id=(
                None
                if _optional_fixture_text(fixture_row, "supersedes_mapping_id") is None
                else MappingId.from_canonical_text(
                    cast(
                        str,
                        _optional_fixture_text(fixture_row, "supersedes_mapping_id"),
                    )
                )
            ),
            correction_reason=_optional_fixture_text(fixture_row, "correction_reason"),
        )
        for fixture_row in _fixture_object_rows(fixture_document, "mappings")
    )
    return fixture_document, SymbologyCatalog(
        identities=instrument_identities,
        mappings=symbology_mappings,
    )


def _build_economic_instrument_and_listing() -> tuple[InstrumentIdentity, InstrumentIdentity]:
    """Build a stable economic instrument and the listing that references it."""
    economic_instrument_id = InstrumentId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"))
    listing_instrument_id = InstrumentId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"))
    return (
        InstrumentIdentity(
            economic_instrument_id,
            InstrumentKind.ECONOMIC_INSTRUMENT,
            economic_instrument_id,
        ),
        InstrumentIdentity(
            listing_instrument_id,
            InstrumentKind.LISTING,
            economic_instrument_id,
        ),
    )


def _build_venue_symbol_mapping(
    mapping_sequence: int,
    instrument_id: InstrumentId,
    *,
    valid_from: datetime = datetime(2020, 1, 1, tzinfo=UTC),
    valid_to: datetime | None = None,
    supersedes_mapping_id: MappingId | None = None,
    source_revision: str = "revision-001",
    identifier_value: str = "SYNTH",
) -> SymbologyMapping:
    """Build an attributed venue-symbol assertion for temporal graph tests.

    Args:
        mapping_sequence: Nonzero integer encoded as the mapping UUID.
        instrument_id: Identity referenced by the assertion.
        valid_from: Inclusive UTC start; invalid inputs exercise model rejection.
        valid_to: Exclusive UTC end, or None for an open interval.
        supersedes_mapping_id: Retained predecessor, if this is a correction.
        source_revision: Revision of the fixed synthetic exchange source.
        identifier_value: Symbol in the fixed fixture-venue namespace.

    Returns:
        Validated mapping with a correction reason only when a predecessor is given.

    Raises:
        ValueError: The UUID integer or owned mapping contract is invalid.
    """
    return SymbologyMapping(
        mapping_id=MappingId(UUID(int=mapping_sequence)),
        instrument_id=instrument_id,
        external_identifier=ExternalIdentifier(
            IdentifierScheme.VENUE_SYMBOL,
            identifier_value,
            "fixture-venue",
        ),
        valid_from=valid_from,
        valid_to=valid_to,
        source="fixture.exchange",
        source_revision=source_revision,
        supersedes_mapping_id=supersedes_mapping_id,
        correction_reason=(
            "Corrected retained fixture assertion." if supersedes_mapping_id else None
        ),
    )


def test_golden_fixture_resolves_temporal_mappings_and_round_trips() -> None:
    """Resolve every golden query and recover the same mapping through both lookup paths."""
    fixture_document, symbology_catalog = _load_instrument_identity_golden_catalog()

    assert fixture_document["schema_version"] == 1
    assert fixture_document["synthetic"] is True
    for expected_resolution in _fixture_object_rows(fixture_document, "expected_resolutions"):
        identifier_query = IdentifierQuery(
            IdentifierScheme(_required_fixture_text(expected_resolution, "identifier_scheme")),
            _required_fixture_text(expected_resolution, "identifier_value"),
            _optional_fixture_text(expected_resolution, "identifier_namespace"),
        )
        valid_at = _parse_fixture_utc_datetime(
            _required_fixture_text(expected_resolution, "valid_at")
        )
        resolved_mapping = symbology_catalog.resolve_identifier_at(
            identifier_query, valid_at=valid_at
        )
        expected_instrument_id = InstrumentId.from_canonical_text(
            _required_fixture_text(expected_resolution, "instrument_id")
        )

        assert resolved_mapping.instrument_id == expected_instrument_id
        assert resolved_mapping in symbology_catalog.get_identifier_mappings_for_instrument(
            expected_instrument_id, valid_at=valid_at
        )
        assert symbology_catalog.resolve_identifier_at(
            IdentifierQuery.for_exact_identifier(resolved_mapping.external_identifier),
            valid_at=valid_at,
        ) == (resolved_mapping)


def test_golden_fixture_covers_distinct_concepts_and_all_identifier_schemes() -> None:
    """Cover every instrument kind and identifier scheme with valid economic references."""
    _, symbology_catalog = _load_instrument_identity_golden_catalog()

    assert {identity.instrument_kind for identity in symbology_catalog.identities} == set(
        InstrumentKind
    )
    assert {mapping.external_identifier.scheme for mapping in symbology_catalog.mappings} == set(
        IdentifierScheme
    )
    for identity in symbology_catalog.identities:
        economic_instrument = symbology_catalog.get_instrument_identity(
            identity.economic_instrument_id
        )
        assert economic_instrument.instrument_kind is InstrumentKind.ECONOMIC_INSTRUMENT


def test_symbol_ambiguity_delisting_gap_and_unknown_instrument_fail_closed() -> None:
    """Distinguish ambiguous symbols, unmapped delisting intervals and unknown identities."""
    fixture_document, symbology_catalog = _load_instrument_identity_golden_catalog()
    ambiguous_query_fixture = cast(dict[str, object], fixture_document["ambiguous_query"])
    delisting_gap_query_fixture = cast(dict[str, object], fixture_document["delisting_gap_query"])

    with pytest.raises(AmbiguousIdentifierError, match="ambiguous across 2 mappings"):
        symbology_catalog.resolve_identifier_at(
            IdentifierQuery(
                IdentifierScheme(
                    _required_fixture_text(ambiguous_query_fixture, "identifier_scheme")
                ),
                _required_fixture_text(ambiguous_query_fixture, "identifier_value"),
                _optional_fixture_text(ambiguous_query_fixture, "identifier_namespace"),
            ),
            valid_at=_parse_fixture_utc_datetime(
                _required_fixture_text(ambiguous_query_fixture, "valid_at")
            ),
        )
    with pytest.raises(UnknownIdentifierError, match="no venue_symbol mapping"):
        symbology_catalog.resolve_identifier_at(
            IdentifierQuery(
                IdentifierScheme(
                    _required_fixture_text(delisting_gap_query_fixture, "identifier_scheme")
                ),
                _required_fixture_text(delisting_gap_query_fixture, "identifier_value"),
                _optional_fixture_text(delisting_gap_query_fixture, "identifier_namespace"),
            ),
            valid_at=_parse_fixture_utc_datetime(
                _required_fixture_text(delisting_gap_query_fixture, "valid_at")
            ),
        )
    with pytest.raises(UnknownInstrumentError, match="unknown instrument ID"):
        symbology_catalog.get_instrument_identity(
            InstrumentId(UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"))
        )


def test_vendor_correction_changes_projection_without_erasing_history() -> None:
    """Retain ordered vendor corrections while excluding superseded assertions from projection."""
    fixture_document, symbology_catalog = _load_instrument_identity_golden_catalog()
    correction_history_fixture = cast(dict[str, object], fixture_document["correction_history"])
    corrected_external_identifier = ExternalIdentifier(
        IdentifierScheme(_required_fixture_text(correction_history_fixture, "identifier_scheme")),
        _required_fixture_text(correction_history_fixture, "identifier_value"),
        _optional_fixture_text(correction_history_fixture, "identifier_namespace"),
    )
    expected_mapping_ids = correction_history_fixture["mapping_ids"]
    assert isinstance(expected_mapping_ids, list)

    correction_history = symbology_catalog.get_mapping_history_for_identifier(
        corrected_external_identifier
    )

    assert [str(mapping.mapping_id) for mapping in correction_history] == expected_mapping_ids
    assert correction_history[1].supersedes_mapping_id == correction_history[0].mapping_id
    assert correction_history[0] not in symbology_catalog.current_projection_mappings()
    assert correction_history[1].source == correction_history[0].source == "fixture.vendor"


@pytest.mark.parametrize(
    ("identifier_scheme", "identifier_value", "expected_error_message"),
    [
        (IdentifierScheme.ISIN, "US0378331004", "checksum"),
        (IdentifierScheme.CUSIP, "037833101", "checksum"),
        (IdentifierScheme.SEDOL, "2046252", "checksum"),
        (IdentifierScheme.ISIN, "us0378331005", "uppercase"),
    ],
)
def test_standard_identifiers_reject_invalid_format_or_checksum(
    identifier_scheme: IdentifierScheme,
    identifier_value: str,
    expected_error_message: str,
) -> None:
    """Reject invalid identifier checksums and noncanonical letter casing."""
    with pytest.raises(InstrumentIdentityValidationError, match=expected_error_message):
        ExternalIdentifier(identifier_scheme, identifier_value)


@pytest.mark.parametrize(
    ("invalid_value_factory", "expected_error_message"),
    [
        (
            lambda: InstrumentId.from_canonical_text("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
            "canonical UUID",
        ),
        (
            lambda: ExternalIdentifier(IdentifierScheme.VENDOR, "symbol", None),
            "namespace is required",
        ),
        (
            lambda: ExternalIdentifier(IdentifierScheme.TICKER, " symbol ", "xnas"),
            "surrounding whitespace",
        ),
        (
            lambda: ExternalIdentifier(IdentifierScheme.ISIN, "US0378331005", "vendor-a"),
            "cannot carry a provider namespace",
        ),
    ],
)
def test_value_object_boundaries_reject_unsafe_input(
    invalid_value_factory: Callable[[], object], expected_error_message: str
) -> None:
    """Reject noncanonical UUIDs, unsafe namespaces and whitespace at their constructors."""
    with pytest.raises(InstrumentIdentityValidationError, match=expected_error_message):
        invalid_value_factory()


def test_instrument_identity_models_are_strict_frozen_pydantic_boundaries() -> None:
    """Reject coercion, extra fields, assignment and unchecked nested nil identities."""
    model_types = (
        InstrumentId,
        MappingId,
        InstrumentIdentity,
        ExternalIdentifier,
        IdentifierQuery,
        SymbologyMapping,
        SymbologyCatalog,
    )
    assert all(issubclass(model_type, BaseModel) for model_type in model_types)

    instrument_id = InstrumentId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"))
    with pytest.raises(ValidationError):
        InstrumentId.model_validate({"uuid_value": str(instrument_id.uuid_value)})
    with pytest.raises(ValidationError):
        InstrumentId.model_validate({"uuid_value": instrument_id.uuid_value, "unexpected": True})
    with pytest.raises(ValidationError):
        instrument_id.uuid_value = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")  # type: ignore[misc]  # [owner=platform; rationale=exercise frozen-field runtime rejection at the original assignment; expires=2027-03-01]

    tampered_id = InstrumentId.model_construct(uuid_value=UUID(int=0))
    with pytest.raises(InstrumentIdentityValidationError, match="non-nil UUID"):
        InstrumentIdentity(
            tampered_id,
            InstrumentKind.ECONOMIC_INSTRUMENT,
            tampered_id,
        )


def test_temporal_boundaries_require_utc_and_positive_half_open_interval() -> None:
    """Reject non-UTC or empty validity intervals and unattributed correction reasons."""
    _, listing_identity = _build_economic_instrument_and_listing()
    non_utc_datetime = datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=8)))

    with pytest.raises(InstrumentIdentityValidationError, match="valid_from must use UTC"):
        _build_venue_symbol_mapping(
            1,
            listing_identity.instrument_id,
            valid_from=non_utc_datetime,
        )
    with pytest.raises(InstrumentIdentityValidationError, match="valid_at must be timezone-aware"):
        _build_venue_symbol_mapping(1, listing_identity.instrument_id).is_valid_at(
            datetime(2020, 1, 1)
        )
    with pytest.raises(InstrumentIdentityValidationError, match="later than valid_from"):
        _build_venue_symbol_mapping(
            1,
            listing_identity.instrument_id,
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            valid_to=datetime(2020, 1, 1, tzinfo=UTC),
        )

    with pytest.raises(InstrumentIdentityValidationError, match="correction_reason is permitted"):
        SymbologyMapping(
            mapping_id=MappingId(UUID(int=1)),
            instrument_id=listing_identity.instrument_id,
            external_identifier=ExternalIdentifier(
                IdentifierScheme.VENUE_SYMBOL,
                "SYNTH",
                "fixture-venue",
            ),
            valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            valid_to=None,
            source="fixture.exchange",
            source_revision="revision-001",
            correction_reason="unexpected",
        )


def test_catalog_rejects_duplicate_unregistered_and_overlapping_records() -> None:
    """Reject duplicate identities, unregistered mapping targets and overlapping projections."""
    instrument_identities = _build_economic_instrument_and_listing()
    initial_mapping = _build_venue_symbol_mapping(
        1,
        instrument_identities[1].instrument_id,
        valid_to=datetime(2022, 1, 1, tzinfo=UTC),
    )
    overlapping_mapping = _build_venue_symbol_mapping(
        2,
        instrument_identities[1].instrument_id,
        valid_from=datetime(2021, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(InstrumentIdentityValidationError, match="instrument IDs must be unique"):
        SymbologyCatalog(
            identities=(instrument_identities[0], instrument_identities[0]),
            mappings=(),
        )
    with pytest.raises(
        InstrumentIdentityValidationError, match="mapped instrument is not registered"
    ):
        SymbologyCatalog(
            identities=instrument_identities,
            mappings=(
                _build_venue_symbol_mapping(
                    1,
                    InstrumentId(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")),
                ),
            ),
        )
    with pytest.raises(InstrumentIdentityValidationError, match="overlapping current mappings"):
        SymbologyCatalog(
            identities=instrument_identities,
            mappings=(initial_mapping, overlapping_mapping),
        )


def test_catalog_rejects_missing_changed_forked_and_cyclic_correction_history() -> None:
    """Reject missing predecessors, changed symbols, forks and cycles in correction history."""
    instrument_identities = _build_economic_instrument_and_listing()
    original_mapping = _build_venue_symbol_mapping(1, instrument_identities[1].instrument_id)
    missing_predecessor_correction = _build_venue_symbol_mapping(
        2,
        instrument_identities[1].instrument_id,
        supersedes_mapping_id=MappingId(UUID(int=99)),
        source_revision="revision-002",
    )
    changed_identifier_correction = _build_venue_symbol_mapping(
        2,
        instrument_identities[1].instrument_id,
        supersedes_mapping_id=original_mapping.mapping_id,
        source_revision="revision-002",
        identifier_value="OTHER",
    )
    first_correction = _build_venue_symbol_mapping(
        2,
        instrument_identities[1].instrument_id,
        supersedes_mapping_id=original_mapping.mapping_id,
        source_revision="revision-002",
    )
    forked_correction = _build_venue_symbol_mapping(
        3,
        instrument_identities[1].instrument_id,
        supersedes_mapping_id=original_mapping.mapping_id,
        source_revision="revision-003",
    )
    first_cyclic_correction = _build_venue_symbol_mapping(
        4,
        instrument_identities[1].instrument_id,
        supersedes_mapping_id=MappingId(UUID(int=5)),
        source_revision="revision-004",
    )
    second_cyclic_correction = _build_venue_symbol_mapping(
        5,
        instrument_identities[1].instrument_id,
        supersedes_mapping_id=first_cyclic_correction.mapping_id,
        source_revision="revision-005",
    )

    for invalid_mapping_history, expected_error_message in (
        (
            (original_mapping, missing_predecessor_correction),
            "superseded mapping is not retained",
        ),
        (
            (original_mapping, changed_identifier_correction),
            "must preserve identifier and source",
        ),
        (
            (original_mapping, first_correction, forked_correction),
            "correction history cannot fork",
        ),
        (
            (first_cyclic_correction, second_cyclic_correction),
            "correction history cannot contain a cycle",
        ),
    ):
        with pytest.raises(InstrumentIdentityValidationError, match=expected_error_message):
            SymbologyCatalog(
                identities=instrument_identities,
                mappings=invalid_mapping_history,
            )


@settings(max_examples=50, derandomize=True, deadline=None, database=None)
@given(
    identifier_namespace=strategies.from_regex(r"[a-z][a-z0-9]{0,12}", fullmatch=True),
    identifier_value=strategies.from_regex(r"[A-Z0-9][A-Z0-9./_-]{0,31}", fullmatch=True),
    days_after_valid_from=strategies.integers(min_value=1, max_value=10_000),
)
def test_property_exact_identifier_round_trip_is_stable(
    identifier_namespace: str,
    identifier_value: str,
    days_after_valid_from: int,
) -> None:
    """Resolve generated vendor identifiers consistently through exact and instrument lookup."""
    instrument_identities = _build_economic_instrument_and_listing()
    vendor_mapping = SymbologyMapping(
        mapping_id=MappingId(UUID(int=1)),
        instrument_id=instrument_identities[1].instrument_id,
        external_identifier=ExternalIdentifier(
            IdentifierScheme.VENDOR,
            identifier_value,
            identifier_namespace,
        ),
        valid_from=datetime(2000, 1, 1, tzinfo=UTC),
        valid_to=None,
        source="fixture.property",
        source_revision="property-001",
    )
    symbology_catalog = SymbologyCatalog(
        identities=instrument_identities, mappings=(vendor_mapping,)
    )
    valid_at = vendor_mapping.valid_from + timedelta(days=days_after_valid_from)

    resolved_mapping = symbology_catalog.resolve_identifier_at(
        IdentifierQuery.for_exact_identifier(vendor_mapping.external_identifier),
        valid_at=valid_at,
    )

    assert resolved_mapping == vendor_mapping
    assert symbology_catalog.get_identifier_mappings_for_instrument(
        vendor_mapping.instrument_id, valid_at=valid_at
    ) == (vendor_mapping,)


@settings(max_examples=50, derandomize=True, deadline=None, database=None)
@given(days_until_symbol_reuse=strategies.integers(min_value=1, max_value=20_000))
def test_property_symbol_reuse_obeys_half_open_boundaries(
    days_until_symbol_reuse: int,
) -> None:
    """Switch symbol ownership exactly at the prior mapping's exclusive validity end."""
    first_economic_instrument, first_listing = _build_economic_instrument_and_listing()
    second_economic_instrument_id = InstrumentId(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"))
    second_listing_instrument_id = InstrumentId(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"))
    second_economic_instrument = InstrumentIdentity(
        second_economic_instrument_id,
        InstrumentKind.ECONOMIC_INSTRUMENT,
        second_economic_instrument_id,
    )
    second_listing = InstrumentIdentity(
        second_listing_instrument_id,
        InstrumentKind.LISTING,
        second_economic_instrument_id,
    )
    validity_start = datetime(2000, 1, 1, tzinfo=UTC)
    symbol_reuse_boundary = validity_start + timedelta(days=days_until_symbol_reuse)
    original_symbol_mapping = _build_venue_symbol_mapping(
        1,
        first_listing.instrument_id,
        valid_from=validity_start,
        valid_to=symbol_reuse_boundary,
    )
    reused_symbol_mapping = _build_venue_symbol_mapping(
        2,
        second_listing.instrument_id,
        valid_from=symbol_reuse_boundary,
    )
    symbology_catalog = SymbologyCatalog(
        identities=(
            first_economic_instrument,
            first_listing,
            second_economic_instrument,
            second_listing,
        ),
        mappings=(original_symbol_mapping, reused_symbol_mapping),
    )
    identifier_query = IdentifierQuery.for_exact_identifier(
        original_symbol_mapping.external_identifier
    )

    assert (
        symbology_catalog.resolve_identifier_at(
            identifier_query,
            valid_at=symbol_reuse_boundary - timedelta(microseconds=1),
        )
        == original_symbol_mapping
    )
    assert (
        symbology_catalog.resolve_identifier_at(identifier_query, valid_at=symbol_reuse_boundary)
        == reused_symbol_mapping
    )


@pytest.mark.performance
def test_golden_resolution_workload_stays_within_local_budget() -> None:
    """Keep ten thousand golden symbol resolutions within the local 1,000 ms budget."""
    _, symbology_catalog = _load_instrument_identity_golden_catalog()
    identifier_query = IdentifierQuery(IdentifierScheme.VENUE_SYMBOL, "ABC", "xnas")
    valid_at = datetime(2022, 1, 1, tzinfo=UTC)

    started_at = perf_counter()
    for _ in range(10_000):
        symbology_catalog.resolve_identifier_at(identifier_query, valid_at=valid_at)
    elapsed_ms = (perf_counter() - started_at) * 1_000

    assert elapsed_ms <= 1_000, (
        f"10,000 golden resolutions took {elapsed_ms:.1f} ms; local budget is 1,000 ms"
    )
