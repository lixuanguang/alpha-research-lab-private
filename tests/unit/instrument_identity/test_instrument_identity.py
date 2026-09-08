"""Test the C01 canonical instrument-identity and temporal-symbology contract."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import NotRequired, Protocol, TypedDict
from uuid import UUID

# third party library imports
import pytest
from hypothesis import given, settings, strategies
from hypothesis.strategies import SearchStrategy
from pydantic import TypeAdapter, ValidationError

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
from alpha_research.instrument_identity import models as instrument_identity_models
from alpha_research.instrument_identity.models import _InstrumentIdentityModel


class _ExactIdentifierGiven(Protocol):
    """Type the keyword Hypothesis decorator for generated identifier fields."""

    def __call__(
        self,
        *,
        identifier_namespace: SearchStrategy[str],
        identifier_value: SearchStrategy[str],
        days_after_valid_from: SearchStrategy[int],
    ) -> Callable[[Callable[[str, str, int], None]], Callable[[], None]]:
        """Decorate a test callable with generated identifier values."""
        ...


class _SymbolReuseGiven(Protocol):
    """Type the keyword Hypothesis decorator for generated reuse intervals."""

    def __call__(
        self, *, days_until_symbol_reuse: SearchStrategy[int]
    ) -> Callable[[Callable[[int], None]], Callable[[], None]]:
        """Decorate a test callable with a generated symbol reuse interval."""
        ...


_given_exact_identifier: _ExactIdentifierGiven = given
_given_symbol_reuse: _SymbolReuseGiven = given

INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_PATH = (
    Path(__file__).parents[2] / "golden/instrument_identity/c01_symbology.json"
)


class _GoldenIdentityRow(TypedDict):
    """Describe one canonical instrument identity in the checked-in fixture."""

    instrument_id: str
    instrument_kind: str
    economic_instrument_id: str


class _GoldenMappingRow(TypedDict):
    """Describe one attributed, validity-dated identifier mapping in the fixture."""

    mapping_id: str
    instrument_id: str
    identifier_scheme: str
    identifier_value: str
    identifier_namespace: str | None
    valid_from: str
    valid_to: str | None
    source: str
    source_revision: str
    supersedes_mapping_id: NotRequired[str | None]
    correction_reason: NotRequired[str | None]


class _GoldenResolutionRow(TypedDict):
    """Describe one expected temporal identifier resolution in the fixture."""

    identifier_scheme: str
    identifier_value: str
    identifier_namespace: str | None
    valid_at: str
    instrument_id: str


class _GoldenQueryRow(TypedDict):
    """Describe one negative temporal lookup query in the fixture."""

    identifier_scheme: str
    identifier_value: str
    identifier_namespace: str | None
    valid_at: str


class _GoldenCorrectionHistory(TypedDict):
    """Describe the expected ordered history for a corrected identifier."""

    identifier_scheme: str
    identifier_value: str
    identifier_namespace: str
    mapping_ids: list[str]


class _GoldenFixtureDocument(TypedDict):
    """Describe the complete strict C01 golden fixture document."""

    schema_version: int
    fixture_id: str
    synthetic: bool
    description: str
    identities: list[_GoldenIdentityRow]
    mappings: list[_GoldenMappingRow]
    expected_resolutions: list[_GoldenResolutionRow]
    ambiguous_query: _GoldenQueryRow
    delisting_gap_query: _GoldenQueryRow
    correction_history: _GoldenCorrectionHistory


class _InstrumentIdentityGoldenFixture:
    """Own strict loading and construction of the synthetic C01 identity graph."""

    document: _GoldenFixtureDocument
    catalog: SymbologyCatalog

    def __init__(self, document: _GoldenFixtureDocument, catalog: SymbologyCatalog) -> None:
        """Bind a validated fixture document and its constructed identity graph."""
        self.document = document
        self.catalog = catalog

    @classmethod
    def load(
        cls, fixture_path: Path = INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_PATH
    ) -> _InstrumentIdentityGoldenFixture:
        """Read one strict fixture document and construct its validated identity graph."""
        document = TypeAdapter(_GoldenFixtureDocument).validate_json(
            fixture_path.read_bytes(), strict=True
        )
        return cls(document, cls._build_catalog(document))

    @staticmethod
    def _parse_utc_datetime(utc_datetime_text: str) -> datetime:
        """Parse ISO fixture text, translating a trailing Z to an explicit UTC offset."""
        return datetime.fromisoformat(utc_datetime_text.replace("Z", "+00:00"))

    @classmethod
    def _build_catalog(cls, fixture_document: _GoldenFixtureDocument) -> SymbologyCatalog:
        """Construct validated identities and mappings from the typed fixture document."""
        instrument_identities = tuple(
            InstrumentIdentity(
                instrument_id=InstrumentId.from_canonical_text(fixture_row["instrument_id"]),
                instrument_kind=InstrumentKind(fixture_row["instrument_kind"]),
                economic_instrument_id=InstrumentId.from_canonical_text(
                    fixture_row["economic_instrument_id"]
                ),
            )
            for fixture_row in fixture_document["identities"]
        )
        symbology_mappings = tuple(
            cls._mapping_from_row(fixture_row) for fixture_row in fixture_document["mappings"]
        )
        return SymbologyCatalog(
            identities=instrument_identities,
            mappings=symbology_mappings,
        )

    @classmethod
    def _mapping_from_row(cls, fixture_row: _GoldenMappingRow) -> SymbologyMapping:
        """Construct one validated mapping after narrowing optional correction fields."""
        valid_to_text = fixture_row["valid_to"]
        supersedes_mapping_id_text = fixture_row.get("supersedes_mapping_id")
        return SymbologyMapping(
            mapping_id=MappingId.from_canonical_text(fixture_row["mapping_id"]),
            instrument_id=InstrumentId.from_canonical_text(fixture_row["instrument_id"]),
            external_identifier=ExternalIdentifier(
                scheme=IdentifierScheme(fixture_row["identifier_scheme"]),
                value=fixture_row["identifier_value"],
                namespace=fixture_row["identifier_namespace"],
            ),
            valid_from=cls._parse_utc_datetime(fixture_row["valid_from"]),
            valid_to=(None if valid_to_text is None else cls._parse_utc_datetime(valid_to_text)),
            source=fixture_row["source"],
            source_revision=fixture_row["source_revision"],
            supersedes_mapping_id=(
                None
                if supersedes_mapping_id_text is None
                else MappingId.from_canonical_text(supersedes_mapping_id_text)
            ),
            correction_reason=fixture_row.get("correction_reason"),
        )

    @staticmethod
    def build_economic_instrument_and_listing() -> tuple[InstrumentIdentity, InstrumentIdentity]:
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

    @staticmethod
    def build_venue_symbol_mapping(
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


class TestGoldenSymbologyContracts:
    """Exercise strict golden loading and temporal symbology projection contracts."""

    def test_golden_fixture_resolves_temporal_mappings_and_round_trips(self) -> None:
        """Resolve every golden query and recover the same mapping through both lookup paths."""
        golden_fixture = _InstrumentIdentityGoldenFixture.load()

        assert golden_fixture.document["schema_version"] == 1
        assert golden_fixture.document["synthetic"] is True
        for expected_resolution in golden_fixture.document["expected_resolutions"]:
            identifier_query = IdentifierQuery(
                IdentifierScheme(expected_resolution["identifier_scheme"]),
                expected_resolution["identifier_value"],
                expected_resolution["identifier_namespace"],
            )
            valid_at = golden_fixture._parse_utc_datetime(expected_resolution["valid_at"])
            resolved_mapping = golden_fixture.catalog.resolve_identifier_at(
                identifier_query, valid_at=valid_at
            )
            expected_instrument_id = InstrumentId.from_canonical_text(
                expected_resolution["instrument_id"]
            )

            assert resolved_mapping.instrument_id == expected_instrument_id
            assert (
                resolved_mapping
                in golden_fixture.catalog.get_identifier_mappings_for_instrument(
                    expected_instrument_id, valid_at=valid_at
                )
            )
            assert golden_fixture.catalog.resolve_identifier_at(
                IdentifierQuery.for_exact_identifier(resolved_mapping.external_identifier),
                valid_at=valid_at,
            ) == (resolved_mapping)

    def test_golden_fixture_covers_distinct_concepts_and_all_identifier_schemes(self) -> None:
        """Cover every instrument kind and identifier scheme with valid economic references."""
        golden_fixture = _InstrumentIdentityGoldenFixture.load()
        symbology_catalog = golden_fixture.catalog

        assert {identity.instrument_kind for identity in symbology_catalog.identities} == set(
            InstrumentKind
        )
        assert {
            mapping.external_identifier.scheme for mapping in symbology_catalog.mappings
        } == set(IdentifierScheme)
        for identity in symbology_catalog.identities:
            economic_instrument = symbology_catalog.get_instrument_identity(
                identity.economic_instrument_id
            )
            assert economic_instrument.instrument_kind is InstrumentKind.ECONOMIC_INSTRUMENT

    def test_golden_fixture_rejects_malformed_fields(self, tmp_path: Path) -> None:
        """Reject malformed required fixture fields at the strict loading boundary."""
        malformed_replacements = (
            ('  "fixture_id": "c01-symbology-golden-v1",\n', "", "fixture_id"),
            ('  "schema_version": 1,\n', '  "schema_version": true,\n', "schema_version"),
            (
                '    "mapping_ids": [\n'
                '      "10000000-0000-4000-8000-000000000011",\n'
                '      "10000000-0000-4000-8000-000000000012"\n'
                "    ]",
                '    "mapping_ids": null',
                "mapping_ids",
            ),
        )
        fixture_payload = INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_PATH.read_text(encoding="utf-8")
        for case_number, (original, replacement, expected_field_name) in enumerate(
            malformed_replacements
        ):
            assert original in fixture_payload
            malformed_fixture_path = tmp_path / f"malformed-{case_number}.json"
            malformed_fixture_path.write_text(
                fixture_payload.replace(original, replacement, 1), encoding="utf-8"
            )
            with pytest.raises(ValidationError, match=expected_field_name):
                _InstrumentIdentityGoldenFixture.load(malformed_fixture_path)

    def test_symbol_ambiguity_delisting_gap_and_unknown_instrument_fail_closed(self) -> None:
        """Distinguish ambiguous symbols, unmapped delisting intervals and unknown identities."""
        golden_fixture = _InstrumentIdentityGoldenFixture.load()
        ambiguous_query_fixture = golden_fixture.document["ambiguous_query"]
        delisting_gap_query_fixture = golden_fixture.document["delisting_gap_query"]

        with pytest.raises(AmbiguousIdentifierError, match="ambiguous across 2 mappings"):
            golden_fixture.catalog.resolve_identifier_at(
                IdentifierQuery(
                    IdentifierScheme(ambiguous_query_fixture["identifier_scheme"]),
                    ambiguous_query_fixture["identifier_value"],
                    ambiguous_query_fixture["identifier_namespace"],
                ),
                valid_at=golden_fixture._parse_utc_datetime(ambiguous_query_fixture["valid_at"]),
            )
        with pytest.raises(UnknownIdentifierError, match="no venue_symbol mapping"):
            golden_fixture.catalog.resolve_identifier_at(
                IdentifierQuery(
                    IdentifierScheme(delisting_gap_query_fixture["identifier_scheme"]),
                    delisting_gap_query_fixture["identifier_value"],
                    delisting_gap_query_fixture["identifier_namespace"],
                ),
                valid_at=golden_fixture._parse_utc_datetime(
                    delisting_gap_query_fixture["valid_at"]
                ),
            )
        with pytest.raises(UnknownInstrumentError, match="unknown instrument ID"):
            golden_fixture.catalog.get_instrument_identity(
                InstrumentId(UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"))
            )

    def test_vendor_correction_changes_projection_without_erasing_history(self) -> None:
        """Retain ordered corrections while excluding superseded assertions from projection."""
        golden_fixture = _InstrumentIdentityGoldenFixture.load()
        correction_history_fixture = golden_fixture.document["correction_history"]
        corrected_external_identifier = ExternalIdentifier(
            IdentifierScheme(correction_history_fixture["identifier_scheme"]),
            correction_history_fixture["identifier_value"],
            correction_history_fixture["identifier_namespace"],
        )
        expected_mapping_ids = correction_history_fixture["mapping_ids"]

        correction_history = golden_fixture.catalog.get_mapping_history_for_identifier(
            corrected_external_identifier
        )

        assert [str(mapping.mapping_id) for mapping in correction_history] == expected_mapping_ids
        assert correction_history[1].supersedes_mapping_id == correction_history[0].mapping_id
        assert correction_history[0] not in golden_fixture.catalog.current_projection_mappings()
        assert correction_history[1].source == correction_history[0].source == "fixture.vendor"
        assert correction_history[1].correction_reason == (
            "Vendor corrected the listing assignment; the original assertion remains retained."
        )

    @pytest.mark.performance
    def test_golden_resolution_workload_stays_within_local_budget(self) -> None:
        """Keep ten thousand golden symbol resolutions within the local 1,000 ms budget."""
        symbology_catalog = _InstrumentIdentityGoldenFixture.load().catalog
        identifier_query = IdentifierQuery(IdentifierScheme.VENUE_SYMBOL, "ABC", "xnas")
        valid_at = datetime(2022, 1, 1, tzinfo=UTC)

        started_at = perf_counter()
        for _ in range(10_000):
            symbology_catalog.resolve_identifier_at(identifier_query, valid_at=valid_at)
        elapsed_ms = (perf_counter() - started_at) * 1_000

        assert elapsed_ms <= 1_000, (
            f"10,000 golden resolutions took {elapsed_ms:.1f} ms; local budget is 1,000 ms"
        )


class TestInstrumentIdentityBoundaryContracts:
    """Exercise strict value-object, model and temporal boundary contracts."""

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
        self,
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
        self, invalid_value_factory: Callable[[], object], expected_error_message: str
    ) -> None:
        """Reject noncanonical UUIDs, unsafe namespaces and whitespace at their constructors."""
        with pytest.raises(InstrumentIdentityValidationError, match=expected_error_message):
            invalid_value_factory()

    def test_instrument_identity_models_are_strict_frozen_pydantic_boundaries(self) -> None:
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
        assert all(issubclass(model_type, _InstrumentIdentityModel) for model_type in model_types)

        instrument_id = InstrumentId(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"))
        invalid_uuid_payload: dict[str, object] = {"uuid_value": str(instrument_id.uuid_value)}
        invalid_extra_payload: dict[str, object] = {
            "uuid_value": instrument_id.uuid_value,
            "unexpected": True,
        }
        with pytest.raises(ValidationError):
            InstrumentId.model_validate(invalid_uuid_payload)
        with pytest.raises(ValidationError):
            InstrumentId.model_validate(invalid_extra_payload)
        with pytest.raises(ValidationError):
            instrument_id.uuid_value = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")  # type: ignore[misc]  # [owner=platform; rationale=exercise frozen-field runtime rejection at the original assignment; expires=2027-03-01]

        tampered_id = InstrumentId.model_construct(uuid_value=UUID(int=0))
        with pytest.raises(InstrumentIdentityValidationError, match="non-nil UUID"):
            InstrumentIdentity(
                tampered_id,
                InstrumentKind.ECONOMIC_INSTRUMENT,
                tampered_id,
            )

    def test_constructor_errors_preserve_locations_and_causes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Preserve field locations for ordinary errors and messages for owned errors."""

        def _ordinary_field_failure(
            candidate_value: object, *, field_name: str, maximum_length: int
        ) -> str:
            """Raise an ordinary validator error whose field location must be retained."""
            del candidate_value, field_name, maximum_length
            raise ValueError("ordinary field failure")

        def _owned_field_failure(
            candidate_value: object, *, field_name: str, maximum_length: int
        ) -> str:
            """Raise an owned validator error whose field location is already descriptive."""
            del candidate_value, field_name, maximum_length
            raise InstrumentIdentityValidationError("owned field failure")

        monkeypatch.setattr(
            instrument_identity_models, "_require_bounded_text", _ordinary_field_failure
        )
        with pytest.raises(InstrumentIdentityValidationError) as ordinary_error:
            ExternalIdentifier(IdentifierScheme.TICKER, "SYMBOL", "xnas")
        assert str(ordinary_error.value) == "value: ordinary field failure"
        assert isinstance(ordinary_error.value.__cause__, ValidationError)

        monkeypatch.setattr(
            instrument_identity_models, "_require_bounded_text", _owned_field_failure
        )
        with pytest.raises(InstrumentIdentityValidationError) as owned_error:
            ExternalIdentifier(IdentifierScheme.TICKER, "SYMBOL", "xnas")
        assert str(owned_error.value) == "owned field failure"
        assert isinstance(owned_error.value.__cause__, ValidationError)

    def test_temporal_boundaries_require_utc_and_positive_half_open_interval(self) -> None:
        """Reject non-UTC or empty validity intervals and unattributed correction reasons."""
        _, listing_identity = (
            _InstrumentIdentityGoldenFixture.build_economic_instrument_and_listing()
        )
        non_utc_datetime = datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=8)))

        with pytest.raises(InstrumentIdentityValidationError, match="valid_from must use UTC"):
            _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
                1,
                listing_identity.instrument_id,
                valid_from=non_utc_datetime,
            )
        with pytest.raises(
            InstrumentIdentityValidationError, match="valid_at must be timezone-aware"
        ):
            _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
                1, listing_identity.instrument_id
            ).is_valid_at(datetime(2020, 1, 1))
        with pytest.raises(InstrumentIdentityValidationError, match="later than valid_from"):
            _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
                1,
                listing_identity.instrument_id,
                valid_from=datetime(2020, 1, 1, tzinfo=UTC),
                valid_to=datetime(2020, 1, 1, tzinfo=UTC),
            )

        with pytest.raises(
            InstrumentIdentityValidationError, match="correction_reason is permitted"
        ):
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


class TestSymbologyCatalogValidationContracts:
    """Exercise duplicate, overlap and correction-history catalog invariants."""

    def test_catalog_rejects_duplicate_unregistered_and_overlapping_records(self) -> None:
        """Reject duplicate identities, unregistered mapping targets and overlapping projections."""
        instrument_identities = (
            _InstrumentIdentityGoldenFixture.build_economic_instrument_and_listing()
        )
        initial_mapping = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
            1,
            instrument_identities[1].instrument_id,
            valid_to=datetime(2022, 1, 1, tzinfo=UTC),
        )
        overlapping_mapping = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
            2,
            instrument_identities[1].instrument_id,
            valid_from=datetime(2021, 1, 1, tzinfo=UTC),
        )

        with pytest.raises(
            InstrumentIdentityValidationError, match="instrument IDs must be unique"
        ):
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
                    _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
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

    def test_catalog_rejects_missing_changed_forked_and_cyclic_correction_history(self) -> None:
        """Reject missing predecessors, changed symbols, forks and cycles in correction history."""
        instrument_identities = (
            _InstrumentIdentityGoldenFixture.build_economic_instrument_and_listing()
        )
        original_mapping = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
            1, instrument_identities[1].instrument_id
        )
        missing_predecessor_correction = (
            _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
                2,
                instrument_identities[1].instrument_id,
                supersedes_mapping_id=MappingId(UUID(int=99)),
                source_revision="revision-002",
            )
        )
        changed_identifier_correction = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
            2,
            instrument_identities[1].instrument_id,
            supersedes_mapping_id=original_mapping.mapping_id,
            source_revision="revision-002",
            identifier_value="OTHER",
        )
        first_correction = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
            2,
            instrument_identities[1].instrument_id,
            supersedes_mapping_id=original_mapping.mapping_id,
            source_revision="revision-002",
        )
        forked_correction = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
            3,
            instrument_identities[1].instrument_id,
            supersedes_mapping_id=original_mapping.mapping_id,
            source_revision="revision-003",
        )
        first_cyclic_correction = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
            4,
            instrument_identities[1].instrument_id,
            supersedes_mapping_id=MappingId(UUID(int=5)),
            source_revision="revision-004",
        )
        second_cyclic_correction = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
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
@_given_exact_identifier(
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
    instrument_identities = _InstrumentIdentityGoldenFixture.build_economic_instrument_and_listing()
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
@_given_symbol_reuse(days_until_symbol_reuse=strategies.integers(min_value=1, max_value=20_000))
def test_property_symbol_reuse_obeys_half_open_boundaries(
    days_until_symbol_reuse: int,
) -> None:
    """Switch symbol ownership exactly at the prior mapping's exclusive validity end."""
    first_economic_instrument, first_listing = (
        _InstrumentIdentityGoldenFixture.build_economic_instrument_and_listing()
    )
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
    original_symbol_mapping = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
        1,
        first_listing.instrument_id,
        valid_from=validity_start,
        valid_to=symbol_reuse_boundary,
    )
    reused_symbol_mapping = _InstrumentIdentityGoldenFixture.build_venue_symbol_mapping(
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


if __name__ == "__main__":
    raise SystemExit(
        pytest.main(
            [
                __file__,
                "-q",
                "-W",
                "error",
                "--strict-markers",
                "-o",
                "markers=performance: local diagnostic timing",
                "-m",
                "not performance",
            ]
        )
    )
