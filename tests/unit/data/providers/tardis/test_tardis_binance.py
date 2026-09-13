"""Test the Tardis provider and Binance payload decoder composition."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

# third party library imports
import pytest

# project library imports
from alpha_research.data.providers.tardis.binance import BinanceTardisDecoder
from alpha_research.data.venues.binance.events import DepthSnapshot, DepthUpdate, Trade
from alpha_research.financial_units import Currency, Dimension, Price, Quantity, QuantityKind
from alpha_research.instrument_identity import InstrumentId
from alpha_research.reference_data import SpotInstrument

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
_TRADE = (
    "2024-06-01T00:00:00.0041023Z "
    '{"stream":"btcusdt@trade","data":{"e":"trade","E":1717199999994,'
    '"s":"BTCUSDT","t":7,"p":"67540.01000000","q":"0.00146000",'
    '"T":1717199999993,"m":false}}'
)
_SNAPSHOT = (
    "2024-06-01T00:00:00.0041023Z "
    '{"stream":"btcusdt@depthSnapshot","generated":true,"data":'
    '{"lastUpdateId":9,"bids":[["1.00","2.00"]],"asks":[["1.01","3.00"]]}}'
)
_UPDATE = (
    "2024-06-01T00:00:00.0050612Z "
    '{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":1717199999995,'
    '"s":"BTCUSDT","U":10,"u":11,"b":[["1.00","0"]],"a":[]}}'
)


def test_decoder_preserves_capture_order_and_ceils_submicroseconds() -> None:
    """Decode exact capture text and round knowledge upward conservatively."""
    decoder = BinanceTardisDecoder(_INSTRUMENTS)
    event = decoder.decode_line(
        _TRADE,
        source_sequence=4,
        local_received=_RECEIVED,
    )

    assert isinstance(event, Trade)
    assert event.original_capture_time == "2024-06-01T00:00:00.0041023Z"
    assert event.provenance.ts_knowledge == datetime(2024, 6, 1, 0, 0, 0, 4103, tzinfo=UTC)
    assert event.provenance.source_sequence == 4
    assert event.instrument_id == _INSTRUMENTS[0].instrument_id
    assert str(event.price) == "67540.01000000"


def test_archived_trade_keeps_local_clocks_and_point_availability_distinct() -> None:
    """Preserve acquisition clocks without turning point validity into a last-price query."""
    ingested = _RECEIVED + timedelta(seconds=1)
    decoder = BinanceTardisDecoder(_INSTRUMENTS)
    event = decoder.decode_line(
        _TRADE,
        source_sequence=0,
        local_received=_RECEIVED,
        local_ingested=ingested,
        source_digest="a" * 64,
    )
    assert isinstance(event, Trade)
    provenance = event.provenance
    capture = _START + timedelta(microseconds=4103)
    assert provenance.ts_event == _START - timedelta(milliseconds=7)
    assert provenance.ts_source_received == provenance.ts_knowledge == capture
    assert provenance.ts_received == _RECEIVED
    assert provenance.ts_ingested == ingested
    assert provenance.knowledge_basis == "source_capture"
    assert provenance.source_digest == "a" * 64
    assert provenance.source_revision == provenance.source_sequence == 0
    assert provenance.valid_from == capture
    assert provenance.valid_to == capture + timedelta(microseconds=1)
    assert provenance.is_available(capture, capture)
    assert not provenance.is_available(capture - timedelta(microseconds=1), capture)
    assert not provenance.is_available(capture, provenance.valid_to)
    later = _START + timedelta(hours=1)
    assert not provenance.is_available(later, later)
    dimension = Dimension(instrument_id=event.instrument_id, kind=QuantityKind.BASE_UNIT)
    notional = Price(
        value=event.price, currency=_INSTRUMENTS[0].quote_currency, per=dimension
    ).amount(Quantity(value=event.quantity, dimension=dimension))
    assert notional.value == Decimal("98.60841460")
    assert notional.currency.minor_unit == Decimal("0.00000001")


def test_decoder_accepts_snapshot_without_exchange_symbol_or_event_time() -> None:
    """Use capture time as an explicit snapshot proxy without inventing exchange time."""
    decoder = BinanceTardisDecoder(_INSTRUMENTS)
    event = decoder.decode_line(
        _SNAPSHOT,
        source_sequence=0,
        local_received=_RECEIVED,
    )

    assert isinstance(event, DepthSnapshot)
    assert event.event_time_basis == "capture_proxy"
    assert event.provenance.ts_event == event.provenance.ts_knowledge
    assert event.last_update_id == 9


def test_decoder_resolves_a_synthetic_configured_symbol() -> None:
    """Resolve a third configured stream without a runtime symbol whitelist."""
    synthetic_line = _SNAPSHOT.replace("btcusdt", "solusdt")
    decoder = BinanceTardisDecoder(_ALL_INSTRUMENTS)
    event = decoder.decode_line(
        synthetic_line,
        source_sequence=0,
        local_received=_RECEIVED,
    )
    assert isinstance(event, DepthSnapshot)
    assert event.symbol == "SOLUSDT"
    assert event.instrument_id == _ALL_INSTRUMENTS[2].instrument_id

    limited_decoder = BinanceTardisDecoder(_INSTRUMENTS)
    with pytest.raises(ValueError, match="unsupported stream symbol"):
        limited_decoder.decode_line(
            synthetic_line,
            source_sequence=0,
            local_received=_RECEIVED,
        )


def test_decoder_recovers_after_invalid_depth_interval_and_negative_quantity() -> None:
    """Reject malformed updates and reuse the decoder for the next valid line."""
    decoder = BinanceTardisDecoder(_INSTRUMENTS)
    with pytest.raises(ValueError, match="last_update_id"):
        decoder.decode_line(
            _UPDATE.replace('"u":11', '"u":9'),
            source_sequence=0,
            local_received=_RECEIVED,
        )
    with pytest.raises(ValueError, match="nonnegative"):
        decoder.decode_line(
            _UPDATE.replace('"0"]', '"-1"]'),
            source_sequence=1,
            local_received=_RECEIVED,
        )
    event = decoder.decode_line(
        _UPDATE,
        source_sequence=2,
        local_received=_RECEIVED,
    )
    assert isinstance(event, DepthUpdate)
    assert event.first_update_id == 10
    assert event.last_update_id == 11
    assert event.provenance.source_sequence == 2
