"""Test Binance payload decoding without provider framing dependencies."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

# third party library imports
import pytest

# project library imports
from alpha_research.data.decoders import DecodeContext
from alpha_research.data.venues.binance.events import DepthSnapshot, DepthUpdate, Trade
from alpha_research.data.venues.binance.payloads import BinancePayloadDecoder
from alpha_research.financial_units import Currency
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import SpotInstrument

_CAPTURE_TEXT = "2024-06-01T00:00:00.0041023Z"
_CAPTURE_TIME = datetime(2024, 6, 1, 0, 0, 0, 4103, tzinfo=UTC)
_RECEIVED = datetime(2026, 1, 1, tzinfo=UTC)
_START = datetime(2024, 6, 1, tzinfo=UTC)


def _instrument(symbol: str, identifier: str) -> SpotInstrument:
    """Build one explicit Binance spot mapping for a fixture."""
    return SpotInstrument(
        instrument_id=InstrumentId(UUID(identifier)),
        symbol=symbol,
        quote_currency=Currency.from_code("USDT"),
        price_tick=Decimal("0.01"),
        valid_from=_START,
        valid_to=datetime(2100, 1, 1, tzinfo=UTC),
    )


_INSTRUMENTS: tuple[SpotInstrument, ...] = (
    _instrument("BTCUSDT", "11111111-1111-4111-8111-111111111111"),
    _instrument("ETHUSDT", "22222222-2222-4222-8222-222222222222"),
)
_ALL_INSTRUMENTS: tuple[SpotInstrument, ...] = (
    *_INSTRUMENTS,
    _instrument("SOLUSDT", "33333333-3333-4333-8333-333333333333"),
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
_UPDATE_PAYLOAD = (
    '{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":1717199999995,'
    '"s":"BTCUSDT","U":10,"u":11,"b":[["1.00","0"]],"a":[]}}'
)


def _context(payload: str) -> DecodeContext:
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


def test_payload_decoder_decodes_trade_without_tardis_timestamp() -> None:
    """Decode native Binance JSON and retain generic provenance identity."""
    event = BinancePayloadDecoder(_INSTRUMENTS).decode_payload(
        _TRADE_PAYLOAD, _context(_TRADE_PAYLOAD)
    )

    assert isinstance(event, Trade)
    assert event.original_capture_time == _CAPTURE_TEXT
    assert event.provenance.source_id == "fixture.provider"
    assert event.provenance.source_sequence == 4
    assert event.provenance.ts_event == datetime(2024, 5, 31, 23, 59, 59, 993000, tzinfo=UTC)
    assert event.instrument_id == _INSTRUMENTS[0].instrument_id
    assert str(event.price) == "67540.01000000"


def test_payload_decoder_accepts_snapshot_without_exchange_fields() -> None:
    """Use capture time as an explicit snapshot proxy without exchange fields."""
    event = BinancePayloadDecoder(_INSTRUMENTS).decode_payload(
        _SNAPSHOT_PAYLOAD, _context(_SNAPSHOT_PAYLOAD)
    )

    assert isinstance(event, DepthSnapshot)
    assert event.event_time_basis == "capture_proxy"
    assert event.provenance.ts_event == _CAPTURE_TIME
    assert event.last_update_id == 9


def test_payload_decoder_resolves_configured_symbol_and_depth_fields() -> None:
    """Resolve a configured symbol and retain exact depth sequence and levels."""
    payload = _SNAPSHOT_PAYLOAD.replace("btcusdt", "solusdt")
    event = BinancePayloadDecoder(_ALL_INSTRUMENTS).decode_payload(payload, _context(payload))

    assert isinstance(event, DepthSnapshot)
    assert event.symbol == "SOLUSDT"
    assert event.instrument_id == _ALL_INSTRUMENTS[2].instrument_id
    assert event.bids == ((Decimal("1.00"), Decimal("2.00")),)


def test_payload_decoder_rejects_invalid_depth_and_quantity() -> None:
    """Reject malformed Binance sequence intervals and negative quantities."""
    decoder = BinancePayloadDecoder(_INSTRUMENTS)
    with pytest.raises(ValueError, match="last_update_id"):
        invalid_payload = _UPDATE_PAYLOAD.replace('"u":11', '"u":9')
        decoder.decode_payload(invalid_payload, _context(invalid_payload))
    with pytest.raises(ValueError, match="nonnegative"):
        invalid_payload = _UPDATE_PAYLOAD.replace('"0"]', '"-1"]')
        decoder.decode_payload(invalid_payload, _context(invalid_payload))


def test_payload_decoder_returns_depth_update() -> None:
    """Decode a valid incremental depth payload without provider framing."""
    event = BinancePayloadDecoder(_INSTRUMENTS).decode_payload(
        _UPDATE_PAYLOAD, _context(_UPDATE_PAYLOAD)
    )

    assert isinstance(event, DepthUpdate)
    assert event.first_update_id == 10
    assert event.last_update_id == 11


def test_payload_decoder_rejects_non_binance_json_object() -> None:
    """Reject a valid JSON object that does not have Binance envelope fields."""
    payload = '{"table":"synthetic","action":"insert","data":{}}'
    with pytest.raises(ValueError, match="valid Binance envelope"):
        BinancePayloadDecoder(_INSTRUMENTS).decode_payload(payload, _context(payload))
