"""Check exact partition coverage and semantic request identities."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.configuration import Configuration
from alpha_research.data.requests import SourceRequest
from alpha_research.reference_data import CatalogSnapshot
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()


class TestSourceRequests:
    """Protect per-instrument half-open requests with fixed origins and integer offsets."""

    def test_two_instrument_minute_partitions_are_complete_and_stable(self) -> None:
        """Generate the exact 60 offsets for each listing through one shared implementation."""
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        manifest = configuration.resolve("both-fixture", catalog)
        requests = SourceRequest.partition(manifest)
        assert len(requests) == 120
        assert len({item.identity for item in requests}) == 120
        for offset in range(60):
            pair = requests[2 * offset : 2 * offset + 2]
            assert tuple(item.instrument.symbol for item in pair) == ("BTCUSDT", "ETHUSDT")
            assert all(
                item.start == manifest.job.start + timedelta(minutes=offset) for item in pair
            )
            assert all(
                item.end == manifest.job.start + timedelta(minutes=offset + 1) for item in pair
            )
            assert all(item.offset_minutes == offset for item in pair)
        assert requests[-1].end == manifest.job.end
        first = requests[0]
        assert _CODEC.decode_json(_CODEC.encode_json(first), SourceRequest) == first
        btc = SourceRequest.partition(configuration.resolve("btc-fixture", catalog))
        assert btc[0].identity == first.identity
        renamed = replace(
            manifest, job=replace(manifest.job, name="another-name", universe="another-alias")
        )
        assert SourceRequest.partition(renamed)[0].identity == first.identity
        assert replace(first, offset_minutes=1).identity != first.identity

    def test_request_rejects_wrong_bindings_and_invalid_offsets(self) -> None:
        """Reject offsets outside the job and instruments outside its resolved universe."""
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        manifest = configuration.resolve("btc-fixture", catalog)
        first = SourceRequest.partition(manifest)[0]
        for offset in (-1, 60, True):
            with pytest.raises(ValueError, match="offset"):
                replace(first, offset_minutes=offset)
        with pytest.raises(ValueError, match="outside the resolved universe"):
            replace(first, instrument=catalog.instruments[1])
        msgspec.structs.force_setattr(first, "offset_minutes", 60)
        with pytest.raises(ValueError, match="offset"):
            _ = first.identity

    def test_equal_numeric_values_cannot_hide_unsafe_instrument_types(self) -> None:
        """Revalidate selected records before equality can equate float and Decimal ticks."""
        configuration = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        instrument = replace(catalog.instruments[0], price_tick=Decimal("1"))
        catalog = replace(catalog, instruments=(instrument,))
        manifest = configuration.resolve("btc-fixture", catalog)
        unsafe = replace(instrument)
        msgspec.structs.force_setattr(unsafe, "price_tick", 1.0)
        assert unsafe == instrument
        with pytest.raises(TypeError, match="price_tick must be a Decimal"):
            replace(manifest, instruments=(unsafe,))
        with pytest.raises(TypeError, match="price_tick must be a Decimal"):
            SourceRequest(manifest=manifest, instrument=unsafe, offset_minutes=0)
