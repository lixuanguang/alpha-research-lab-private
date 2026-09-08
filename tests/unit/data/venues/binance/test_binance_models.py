"""Protect the Binance compatibility facade and canonical event codecs."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

# project library imports
from alpha_research.core import EventProvenance
from alpha_research.data.events import Disconnect, MarketEventError
from alpha_research.data.models import (
    DepthSnapshot as LegacyDepthSnapshot,
)
from alpha_research.data.models import (
    DepthUpdate as LegacyDepthUpdate,
)
from alpha_research.data.models import (
    Disconnect as LegacyDisconnect,
)
from alpha_research.data.models import (
    MarketEvent as LegacyMarketEvent,
)
from alpha_research.data.models import (
    MarketEventError as LegacyMarketEventError,
)
from alpha_research.data.models import (
    Trade as LegacyTrade,
)
from alpha_research.data.models import (
    decode_market_event as legacy_decode_market_event,
)
from alpha_research.data.models import (
    encode_market_event as legacy_encode_market_event,
)
from alpha_research.data.models import (
    validate_market_event as legacy_validate_market_event,
)
from alpha_research.data.venues.binance.codecs import (
    MarketEvent,
    decode_market_event,
    encode_market_event,
    validate_market_event,
)
from alpha_research.data.venues.binance.events import DepthSnapshot, DepthUpdate, Trade
from alpha_research.instrument_identity import InstrumentId

_BASE_TIME = datetime(2024, 6, 1, tzinfo=UTC)
_INSTRUMENT_ID = InstrumentId(UUID(int=7))


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


def _trade() -> Trade:
    """Build a deterministic Binance trade for compatibility and codec tests."""
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


def test_legacy_models_facade_reexports_canonical_classes_and_codecs() -> None:
    """Keep old imports exact while retaining the established event tag bytes."""
    assert LegacyDepthSnapshot is DepthSnapshot
    assert LegacyDepthUpdate is DepthUpdate
    assert LegacyDisconnect is Disconnect
    assert LegacyTrade is Trade
    assert LegacyMarketEvent is MarketEvent
    assert LegacyMarketEventError is MarketEventError
    assert legacy_decode_market_event is decode_market_event
    assert legacy_encode_market_event is encode_market_event
    assert legacy_validate_market_event is validate_market_event

    event = _trade()
    encoded = encode_market_event(event)
    assert b'"event_type":"trade"' in encoded
    assert legacy_encode_market_event(event) == encoded
    assert legacy_decode_market_event(encoded) == event
