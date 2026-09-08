"""Protect canonical market-event invariants and strict codec boundaries."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

# third party library imports
import msgspec
import pytest

# project library imports
from alpha_research.core import EventProvenance
from alpha_research.data.events import Disconnect, MarketEventError, MarketEventRecord
from alpha_research.data.venues.binance.codecs import (
    MarketEvent,
    decode_market_event,
    encode_market_event,
    validate_market_event,
)
from alpha_research.data.venues.binance.events import (
    BinanceMarketEvent,
    DepthSnapshot,
    DepthUpdate,
    Trade,
)
from alpha_research.instrument_identity import InstrumentId

_BASE_TIME = datetime(2024, 6, 1, tzinfo=UTC)
_INSTRUMENT_ID = InstrumentId(UUID(int=11))


def _provenance(sequence: int = 1) -> EventProvenance:
    """Build deterministic source-capture provenance for one event fixture."""
    return EventProvenance(
        source_id="tardis.binance.spot",
        event_id=f"event-{sequence}",
        source_revision=0,
        source_sequence=sequence,
        source_digest="0" * 64,
        ts_event=_BASE_TIME,
        ts_received=_BASE_TIME + timedelta(seconds=1),
        ts_ingested=_BASE_TIME + timedelta(seconds=1),
        ts_knowledge=_BASE_TIME,
        ts_source_received=_BASE_TIME,
        valid_from=_BASE_TIME,
        valid_to=_BASE_TIME + timedelta(microseconds=1),
        knowledge_basis="source_capture",
    )


def _snapshot(*, symbol: str = "BTCUSDT") -> DepthSnapshot:
    """Build one canonical Binance snapshot fixture."""
    return DepthSnapshot(
        provenance=_provenance(),
        original_capture_time="2024-06-01T00:00:00.0000000Z",
        symbol=symbol,
        instrument_id=_INSTRUMENT_ID,
        source_stream="btcusdt@depthSnapshot",
        raw_line="snapshot-1",
        last_update_id=9,
        bids=((Decimal("100"), Decimal("1")),),
        asks=((Decimal("101"), Decimal("1")),),
    )


def test_inherited_constructor_and_revalidation_dispatch_to_binance_invariants() -> None:
    """Apply Binance symbol checks through inherited construction and validation hooks."""
    assert issubclass(BinanceMarketEvent, MarketEventRecord)
    with pytest.raises(ValueError, match="uppercase ASCII"):
        _snapshot(symbol="btcusdt")

    snapshot = _snapshot()
    msgspec.structs.force_setattr(snapshot, "symbol", "btcusdt")
    with pytest.raises(ValueError, match="uppercase ASCII"):
        snapshot.validate()


def _update() -> DepthUpdate:
    """Build one canonical Binance depth-update fixture."""
    return DepthUpdate(
        provenance=_provenance(),
        original_capture_time="2024-06-01T00:00:00.0000000Z",
        symbol="BTCUSDT",
        instrument_id=_INSTRUMENT_ID,
        source_stream="btcusdt@depth@100ms",
        raw_line="update-1",
        first_update_id=10,
        last_update_id=11,
        bids=((Decimal("100"), Decimal("1")),),
        asks=(),
    )


def _trade() -> Trade:
    """Build one canonical Binance trade fixture."""
    return Trade(
        provenance=_provenance(),
        original_capture_time="2024-06-01T00:00:00.0000000Z",
        symbol="BTCUSDT",
        instrument_id=_INSTRUMENT_ID,
        source_stream="btcusdt@trade",
        raw_line="trade-1",
        price=Decimal("100"),
        quantity=Decimal("1"),
        trade_id=7,
        is_buyer_maker=False,
    )


def _disconnect() -> Disconnect:
    """Build one canonical blank-line disconnect fixture."""
    return Disconnect(provenance=_provenance(), capture_proxy_reason="interval_end")


@pytest.mark.parametrize(
    ("factory", "expected_tag"),
    [
        (_snapshot, "depth_snapshot"),
        (_update, "depth_update"),
        (_trade, "trade"),
        (_disconnect, "disconnect"),
    ],
)
def test_all_canonical_events_round_trip_with_exact_tags(
    factory: Callable[[], MarketEvent], expected_tag: str
) -> None:
    """Round-trip every retained Binance event and preserve its discriminator bytes."""
    event = factory()
    encoded = encode_market_event(event)
    assert f'"event_type":"{expected_tag}"'.encode() in encoded
    assert decode_market_event(encoded) == event


def test_canonical_event_decoder_rejects_unknown_fields() -> None:
    """Keep the canonical event wire schema closed at the decoding boundary."""
    encoded = encode_market_event(_trade())
    payload = encoded[:-1] + b',"unknown":1}'
    with pytest.raises(MarketEventError):
        decode_market_event(payload)


@pytest.mark.parametrize(
    ("factory", "invalid_basis"),
    [
        (_snapshot, "source_event"),
        (_update, "capture_proxy"),
        (_trade, "capture_proxy"),
    ],
)
def test_unsafe_event_mutation_revalidates_time_basis(
    factory: Callable[[], MarketEvent], invalid_basis: str
) -> None:
    """Reject wrong event-time semantics through the canonical validation boundary."""
    event = factory()
    msgspec.structs.force_setattr(event, "event_time_basis", invalid_basis)
    with pytest.raises(ValueError, match="event_time_basis"):
        validate_market_event(event)
