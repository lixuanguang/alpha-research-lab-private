"""Test Binance payload decoding without provider framing dependencies."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

# third party library imports
import pytest

# project library imports
from financial_units import Currency
from market_data.adapters.venues.binance import BinancePayloadDecoder
from market_data.contracts import DecodeContext, DepthSnapshot, Trade
from reference_data.catalogs import SpotInstrument
from reference_data.instruments import InstrumentId

_CAPTURE_TEXT = "2024-06-01T00:00:00.0041023Z"
_CAPTURE_TIME = datetime(2024, 6, 1, 0, 0, 0, 4103, tzinfo=UTC)
_RECEIVED = datetime(2026, 1, 1, tzinfo=UTC)
_START = datetime(2024, 6, 1, tzinfo=UTC)


class TestBinancePayloadDecoder:
    """Decode Binance payloads through the configured instrument."""

    def test_payload_decoder_decodes_trade_without_tardis_timestamp(self) -> None:
        """Decode native Binance JSON and retain generic provenance identity."""
        event = BinancePayloadDecoder(_INSTRUMENTS).decode_payload(
            _TRADE_PAYLOAD, BinanceDecoderFixture.context(_TRADE_PAYLOAD)
        )

        assert isinstance(event, Trade)
        assert event.original_capture_time == _CAPTURE_TEXT
        assert event.provenance.source_id == "fixture.provider"
        assert event.provenance.source_sequence == 4
        assert event.provenance.ts_event == datetime(2024, 5, 31, 23, 59, 59, 993000, tzinfo=UTC)
        assert event.instrument_id == _INSTRUMENTS[0].instrument_id
        assert str(event.price) == "67540.01000000"

    def test_payload_decoder_resolves_configured_symbol_and_depth_fields(self) -> None:
        """Resolve a configured symbol and retain exact depth sequence and levels."""
        payload = _SNAPSHOT_PAYLOAD.replace("btcusdt", "solusdt")
        event = BinancePayloadDecoder(_ALL_INSTRUMENTS).decode_payload(
            payload, BinanceDecoderFixture.context(payload)
        )

        assert isinstance(event, DepthSnapshot)
        assert event.symbol == "SOLUSDT"
        assert event.instrument_id == _ALL_INSTRUMENTS[2].instrument_id
        assert event.bids == ((Decimal("1.00"), Decimal("2.00")),)

    def test_payload_decoder_rejects_non_binance_json_object(self) -> None:
        """Reject a valid JSON object that does not have Binance envelope fields."""
        payload = '{"table":"synthetic","action":"insert","data":{}}'
        with pytest.raises(ValueError, match="valid Binance envelope"):
            BinancePayloadDecoder(_INSTRUMENTS).decode_payload(
                payload, BinanceDecoderFixture.context(payload)
            )


class BinanceDecoderFixture:
    """Build the Binance decode context and instrument."""

    @staticmethod
    def instrument(symbol: str, identifier: str) -> SpotInstrument:
        """Build one explicit Binance spot mapping for a fixture."""
        return SpotInstrument(
            instrument_id=InstrumentId(UUID(identifier)),
            symbol=symbol,
            quote_currency=Currency.from_code("USDT"),
            price_tick=Decimal("0.01"),
            valid_from=_START,
            valid_to=datetime(2100, 1, 1, tzinfo=UTC),
        )

    @staticmethod
    def context(payload: str) -> DecodeContext:
        """Build generic source context for direct payload tests."""
        return DecodeContext(
            capture_text=_CAPTURE_TEXT,
            capture_time=_CAPTURE_TIME,
            raw_line=payload,
            source_sequence=4,
            local_received=_RECEIVED,
            local_ingested=None,
            source_digest=None,
            source_id="fixture.provider",
        )


_INSTRUMENTS: tuple[SpotInstrument, ...] = (
    BinanceDecoderFixture.instrument("BTCUSDT", "11111111-1111-4111-8111-111111111111"),
    BinanceDecoderFixture.instrument("ETHUSDT", "22222222-2222-4222-8222-222222222222"),
)
_ALL_INSTRUMENTS: tuple[SpotInstrument, ...] = (
    *_INSTRUMENTS,
    BinanceDecoderFixture.instrument("SOLUSDT", "33333333-3333-4333-8333-333333333333"),
)
_TRADE_PAYLOAD = (
    '{"stream":"btcusdt@trade","data":{"e":"trade","E":1717199999994,'
    '"s":"BTCUSDT","t":7,"p":"67540.01000000","q":"0.00146000",'
    '"T":1717199999993,"m":false}}'
)
_SNAPSHOT_PAYLOAD = (
    '{"stream":"btcusdt@depthSnapshot","generated":true,"data":'
    '{"lastUpdateId":9,"bids":[["1.00","2.00"]],"asks":[["1.01","3.00"]]}}'
)
