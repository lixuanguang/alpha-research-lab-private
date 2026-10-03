"""Protect authored reference-catalog validation and deterministic identity."""

from __future__ import annotations

# standard library imports
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from financial_units import Currency
from financial_units.models import FinancialUnitModel
from reference_data.catalogs import CatalogSnapshot, SpotInstrument
from serialization import DomainCodec

_CATALOG_PATH = Path(__file__).parents[2] / "configs" / "reference" / "binance-spot.json"
_START = datetime(2024, 6, 1, tzinfo=UTC)


_CODEC = DomainCodec()


class _ReferenceCatalogFixture:
    """Build exact fixtures for the component boundary."""

    @staticmethod
    def _catalog() -> CatalogSnapshot:
        """Decode the authored catalog directly at its serialization boundary."""
        return _CODEC.decode_json(_CATALOG_PATH.read_bytes(), CatalogSnapshot)

    @staticmethod
    def _unsafe_currency_copy(model: Currency, update: Mapping[str, object]) -> Currency:
        """Apply the inherited unchecked Pydantic copy for reference-boundary testing."""
        return super(FinancialUnitModel, model).model_copy(update=update)

    @staticmethod
    def _with_quote_currency(instrument: SpotInstrument, currency: Currency) -> SpotInstrument:
        """Copy one authored instrument while changing only its quote-unit identity."""
        return SpotInstrument(
            instrument_id=instrument.instrument_id,
            symbol=instrument.symbol,
            quote_currency=currency,
            price_tick=instrument.price_tick,
            valid_from=instrument.valid_from,
            valid_to=instrument.valid_to,
            venue=instrument.venue,
            product=instrument.product,
            source=instrument.source,
            metadata_basis=instrument.metadata_basis,
        )


class TestReferenceCatalog:
    """Protect authored catalog validation, coverage and deterministic identity."""

    def test_catalog_rejects_duplicate_ids_and_unsupported_product(self) -> None:
        """Keep catalog identifiers unique and admit only the authored spot product."""
        catalog = _ReferenceCatalogFixture._catalog()
        with pytest.raises(ValueError):
            replace(catalog, instruments=(catalog.instruments[0], catalog.instruments[0]))
        with pytest.raises((TypeError, ValueError)):
            invalid_currency = _ReferenceCatalogFixture._unsafe_currency_copy(
                Currency.from_code("USD"), {"code": "usd"}
            )
            invalid = replace(catalog.instruments[0], quote_currency=invalid_currency)
            invalid.validate()

        unsupported_product = _CATALOG_PATH.read_bytes().replace(
            b'"product": "spot"', b'"product": "future"', 1
        )
        with pytest.raises(ValueError):
            _CODEC.decode_json(unsupported_product, CatalogSnapshot)

    def test_catalog_resolution_rejects_incomplete_coverage(self) -> None:
        """Require a requested interval to fit wholly inside authored validity."""
        catalog = _ReferenceCatalogFixture._catalog()
        instrument = catalog.instruments[0]
        assert (
            catalog.resolve(instrument.instrument_id, instrument.valid_from, instrument.valid_to)
            == instrument
        )
        with pytest.raises(ValueError, match="complete requested interval"):
            catalog.resolve(
                instrument.instrument_id,
                _START,
                instrument.valid_to + timedelta(microseconds=1),
            )

    @pytest.mark.parametrize("tick", [Decimal("NaN"), Decimal("0"), Decimal("1e-19")])
    def test_catalog_rejects_ticks_outside_the_financial_unit_contract(self, tick: Decimal) -> None:
        """Reject metadata that could not construct a valid replay price increment."""
        catalog = _ReferenceCatalogFixture._catalog()
        with pytest.raises(ValueError):
            replace(catalog.instruments[0], price_tick=tick)

    def test_catalog_identity_is_deterministic_and_tracks_authored_currency_quantum(self) -> None:
        """Hash complete content and distinguish currencies that use different grids."""
        first = _ReferenceCatalogFixture._catalog()
        second = _ReferenceCatalogFixture._catalog()
        assert first is not second
        assert first.identity == second.identity

        changed_evidence = replace(first, evidence="A different authored assumption.")
        assert changed_evidence.identity != first.identity

        fine_currency = Currency(code="QXX", minor_unit=Decimal("0.01"))
        coarse_currency = Currency(code="QXX", minor_unit=Decimal("0.05"))
        fine_instruments: tuple[SpotInstrument, ...] = tuple(
            _ReferenceCatalogFixture._with_quote_currency(instrument, fine_currency)
            for instrument in first.instruments
        )
        coarse_instruments: tuple[SpotInstrument, ...] = tuple(
            _ReferenceCatalogFixture._with_quote_currency(instrument, coarse_currency)
            for instrument in first.instruments
        )
        fine_catalog = replace(
            first,
            instruments=fine_instruments,
        )
        coarse_catalog = replace(
            first,
            instruments=coarse_instruments,
        )
        assert fine_catalog.instruments[0].quote_currency == fine_currency
        assert coarse_catalog.instruments[0].quote_currency == coarse_currency
        assert fine_catalog.identity != coarse_catalog.identity
