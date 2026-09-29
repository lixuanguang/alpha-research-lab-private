"""Keep capture provenance intact while assigning scoped occurrence identities."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import Configuration
from market_data.adapters.providers.tardis import TardisDecoder
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import Disconnect, Occurrence, SourceRequest, Trade
from market_data.storage import RawFiles
from reference_data.catalogs import CatalogSnapshot
from runtime import ImplementationIdentity
from serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()


class TestCapturedOccurrences:
    """Use unchanged public decoders for trade precision and independent disconnect scope."""

    @staticmethod
    def _bind(request: SourceRequest, path: Path) -> Occurrence:
        """Bind a saved single line using its actual bytes and retained receipt clocks."""
        origin = RawFiles.describe(
            path,
            request=request.binding,
            retrieval_reference="synthetic:mr09-captured",
            ts_received=datetime(2026, 9, 16, tzinfo=UTC),
            ts_ingested=datetime(2026, 9, 16, tzinfo=UTC),
        )
        raw = path.read_bytes()
        event = TardisDecoder(
            BinancePayloadDecoder(request.manifest.instruments), request.instrument.source
        ).decode_line(
            raw.decode().removesuffix("\n").removesuffix("\r"),
            source_sequence=0,
            local_received=origin.ts_received,
            local_ingested=origin.ts_ingested,
            source_digest=origin.sha256,
            disconnect_capture_time=request.end,
            disconnect_capture_reason="interval_end",
        )
        assert isinstance(event, (Trade, Disconnect))
        return Occurrence(request=request, origin=origin, position=0, raw=raw, event=event)

    @pytest.fixture()
    def requests(self) -> tuple[SourceRequest, ...]:
        """Resolve independent BTC and ETH subscriptions for a shared capture interval.

        Returns:
            The two first-minute instrument requests from the configured universe.
        """
        config = Configuration.read(_ROOT / "configs/data-jobs/fixture-inspection.json")
        catalog = _CODEC.decode_json(
            (_ROOT / "configs/reference/binance-spot.json").read_bytes(), CatalogSnapshot
        )
        return SourceRequest.partition(
            config.resolve(
                "both-fixture", catalog, implementation_identity=ImplementationIdentity.sha256()
            )
        )[:2]

    def test_controls_scope_identical_bytes_and_sequence_zero(
        self, tmp_path: Path, requests: tuple[SourceRequest, ...]
    ) -> None:
        """Identical instrument-less controls remain attributable to separate input bindings."""
        path = tmp_path / "disconnect.txt"
        path.write_bytes(b"\r\n")
        btc, eth = (self._bind(request, path) for request in requests)
        assert btc.position == eth.position == 0
        assert btc.origin.sha256 == eth.origin.sha256
        assert btc.event == eth.event
        assert btc.event.instrument_id is eth.event.instrument_id is None
        assert btc.event.source_stream == eth.event.source_stream == "global"
        assert btc.identity != eth.identity
        assert btc.request.instrument.symbol == "BTCUSDT"
        assert eth.request.instrument.symbol == "ETHUSDT"
        assert _CODEC.decode_json(_CODEC.encode_json(btc), Occurrence) == btc
        assert self._bind(requests[0], path).identity == btc.identity

    def test_original_precision_and_incompatible_lineage(
        self, requests: tuple[SourceRequest, ...]
    ) -> None:
        """Retain submicrosecond capture text and reject wrong binding, position or source bytes."""
        item = self._bind(requests[0], _ROOT / "tests/fixtures/market_data/tardis/btcusdt.txt")
        assert isinstance(item.event, Trade)
        assert item.event.original_capture_time == "2024-06-01T00:00:00.0041023Z"
        assert item.event.provenance.ts_source_received == item.request.start + timedelta(
            microseconds=4103
        )
        assert _CODEC.decode_json(_CODEC.encode_json(item), Occurrence) == item
        with pytest.raises(ValueError, match="lineage"):
            replace(item, position=1)
        with pytest.raises(ValueError, match="source line"):
            replace(item, raw=item.raw + b"x")
        with pytest.raises(ValueError, match="lineage"):
            replace(
                item,
                origin=replace(
                    item.origin, ts_ingested=item.origin.ts_ingested + timedelta(seconds=1)
                ),
            )
        with pytest.raises(ValueError, match="instrument"):
            replace(
                item,
                request=requests[1],
                origin=replace(item.origin, request_identity=requests[1].identity),
            )
        later = replace(item.request, offset_minutes=1)
        with pytest.raises(ValueError, match="outside request partition"):
            replace(
                item, request=later, origin=replace(item.origin, request_identity=later.identity)
            )
