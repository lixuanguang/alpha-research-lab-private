"""Exercise strict data-job definitions and actual resolved universe identities."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from configuration import Configuration, DataJob, ResolvedManifest, Universe
from reference_data.catalogs import CatalogSnapshot, SpotInstrument
from reference_data.instruments import InstrumentId
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[2]
_CONFIG = _ROOT / "configs/data-jobs/fixture-inspection.json"
_CATALOG = _ROOT / "configs/reference/binance-spot.json"
_CODEC = DomainCodec()


class TestConfiguration:
    """Protect definition/activation separation and fail-closed complete-interval resolution."""

    def test_two_selections_share_resolution_and_do_not_activate_the_catalog(self) -> None:
        """Select either supported listing or both without changing implementation."""
        configuration = Configuration.read(_CONFIG)
        catalog = _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        for job, symbols in (
            ("btc-fixture", ("BTCUSDT",)),
            ("eth-fixture", ("ETHUSDT",)),
            ("both-fixture", ("BTCUSDT", "ETHUSDT")),
        ):
            manifest = configuration.resolve(
                job, catalog, implementation_identity=ImplementationIdentity.sha256()
            )
            assert tuple(item.symbol for item in manifest.instruments) == symbols
            assert (
                manifest.catalog.identity
                == "3125723d3760b4a35238b75a493e1d1e2a6956c66566ac7231c35a0afb59bad6"
            )
            assert _CODEC.decode_json(_CODEC.encode_json(manifest), ResolvedManifest) == manifest
            assert manifest.job.rights_reference == "synthetic-local-fixtures"
            with pytest.raises(AttributeError):
                setattr(manifest, "implementation_identity", "b" * 64)

    def test_stable_resolution_tracks_actual_universe_catalog_and_code(self) -> None:
        """Formatting and definition order are irrelevant; changed actual inputs remain visible."""
        configuration = Configuration.read(_CONFIG)
        catalog = _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        original = configuration.resolve(
            "both-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
        )
        jobs: tuple[DataJob, ...] = tuple(reversed(configuration.jobs))
        universes: tuple[Universe, ...] = tuple(
            Universe(name=item.name, instrument_ids=tuple(reversed(item.instrument_ids)))
            for item in reversed(configuration.universes)
        )
        reordered = replace(configuration, jobs=jobs, universes=universes)
        assert (
            reordered.resolve(
                "both-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            ).identity
            == original.identity
        )
        assert (
            Configuration.read(_CONFIG)
            .resolve(
                "both-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
            .identity
            == original.identity
        )
        narrowed: tuple[Universe, ...] = tuple(
            replace(item, instrument_ids=item.instrument_ids[:1]) if item.name == "both" else item
            for item in configuration.universes
        )
        changed = replace(configuration, universes=narrowed)
        assert (
            changed.resolve(
                "both-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            ).identity
            != original.identity
        )
        revised = replace(catalog, evidence="Another authored assumption")
        assert (
            configuration.resolve(
                "both-fixture", revised, implementation_identity=ImplementationIdentity.sha256()
            ).identity
            != original.identity
        )
        assert replace(original, implementation_identity="f" * 64).identity != original.identity
        assert (
            replace(original, job=replace(original.job, source_revision="synthetic")).identity
            != original.identity
        )
        assert (
            replace(
                original, job=replace(original.job, rights_reference="different-terms")
            ).identity
            != original.identity
        )

    @pytest.mark.parametrize(
        ("before", "after", "message"),
        [
            ('"schema_version": "1"', '"schema_version": "2"', "schema_version"),
            ('"product": "spot"', '"product": "future"', "product"),
            ('"provider": "tardis"', '"provider": "unknown"', "provider"),
            ('"mode": "fixture"', '"mode": "live"', "mode"),
            ('"pipeline": "dataset.inspect"', '"pipeline": "unknown"', "pipeline"),
            ('"stream": "trade"', '"stream": "depth@100ms"', "stream"),
            ('"universe": "btc"', '"universe": "absent"', "missing universe binding"),
            (
                '"rights_reference": "synthetic-local-fixtures"',
                '"unknown": "value"',
                "unknown field",
            ),
            ('"rights_reference": "synthetic-local-fixtures",', "", "rights_reference"),
            ("2024-06-01T01:00:00Z", "2024-06-01T00:00:00Z", "nonempty"),
            ("2024-06-01T01:00:00Z", "2024-06-01T00:00:00.000001Z", "minute-aligned"),
            ("2024-06-01T00:00:00Z", "2024-06-01T00:00:00", "timezone-aware"),
            ("2024-06-01T00:00:00Z", "2024-06-01T00:00:00+01:00", "UTC"),
        ],
    )
    def test_invalid_json_definitions(self, before: str, after: str, message: str) -> None:
        """Reject unsupported selections and missing/unknown fields at the JSON boundary."""
        payload = _CONFIG.read_text().replace(before, after, 1)
        with pytest.raises(ValueError, match=message):
            _CODEC.decode_json(payload, Configuration)

    def test_missing_ids_and_incomplete_catalog_intervals_fail(self) -> None:
        """Require every selected listing for the entire job before source access."""
        configuration = Configuration.read(_CONFIG)
        catalog = _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        with pytest.raises(ValueError, match="unknown data-job binding"):
            configuration.resolve(
                "absent", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
        instruments: tuple[SpotInstrument, ...] = tuple(
            replace(item, valid_to=item.valid_from + timedelta(minutes=59))
            for item in catalog.instruments
        )
        short = replace(catalog, instruments=instruments)
        with pytest.raises(ValueError, match="complete requested interval"):
            configuration.resolve(
                "btc-fixture", short, implementation_identity=ImplementationIdentity.sha256()
            )
        unknown = InstrumentId.from_canonical_text("33333333-3333-4333-8333-333333333333")
        unbound: tuple[Universe, ...] = (
            Universe(name="btc", instrument_ids=(unknown,)),
            *configuration.universes[1:],
        )
        changed = replace(configuration, universes=unbound)
        with pytest.raises(ValueError, match="absent from the catalog"):
            changed.resolve(
                "btc-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            )

    def test_constructor_and_unsafe_mutation_validation(self) -> None:
        """Direct constructors and unsafe copies cannot bypass immutable domain invariants."""
        configuration = Configuration.read(_CONFIG)
        catalog = _CODEC.decode_json(_CATALOG.read_bytes(), CatalogSnapshot)
        with pytest.raises(ValueError, match="duplicate"):
            replace(configuration, jobs=(configuration.jobs[0], configuration.jobs[0]))
        with pytest.raises(ValueError, match="duplicate instrument"):
            replace(
                configuration.universes[0],
                instrument_ids=(catalog.instruments[0].instrument_id,) * 2,
            )
        with pytest.raises(ValueError, match="UTC"):
            replace(configuration.jobs[0], start=datetime(2024, 6, 1))
        with pytest.raises(ValueError, match="at most one day"):
            replace(configuration.jobs[0], end=datetime(2024, 6, 3, tzinfo=UTC))
        manifest = configuration.resolve(
            "btc-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
        )
        with pytest.raises(ValueError, match="differs from its catalog"):
            replace(
                manifest, instruments=(replace(manifest.instruments[0], price_tick=Decimal("0.1")),)
            )
        msgspec.structs.force_setattr(manifest.job, "product", "future")
        with pytest.raises(ValueError, match="unsupported source/product"):
            _ = manifest.identity

    def test_oversized_config_is_rejected(self, tmp_path: Path) -> None:
        """Bound local configuration reads before parsing."""
        path = tmp_path / "oversized.json"
        path.write_bytes(b" " * 1_048_577)
        with pytest.raises(ValueError, match="exceeds one MiB"):
            Configuration.read(path)
