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
    MarketEventCodec,
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


_CODEC = MarketEventCodec()


class _BinanceEventFixture:
    """Build exact fixtures for the component boundary."""

    @staticmethod
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

    @staticmethod
    def _snapshot(*, symbol: str = "BTCUSDT") -> DepthSnapshot:
        """Build one canonical Binance snapshot fixture."""
        return DepthSnapshot(
            provenance=_BinanceEventFixture._provenance(),
            original_capture_time="2024-06-01T00:00:00.0000000Z",
            symbol=symbol,
            instrument_id=_INSTRUMENT_ID,
            source_stream="btcusdt@depthSnapshot",
            raw_line="snapshot-1",
            last_update_id=9,
            bids=((Decimal("100"), Decimal("1")),),
            asks=((Decimal("101"), Decimal("1")),),
        )

    @staticmethod
    def _update() -> DepthUpdate:
        """Build one canonical Binance depth-update fixture."""
        return DepthUpdate(
            provenance=_BinanceEventFixture._provenance(),
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

    @staticmethod
    def _trade() -> Trade:
        """Build one canonical Binance trade fixture."""
        return Trade(
            provenance=_BinanceEventFixture._provenance(),
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

    @staticmethod
    def _disconnect() -> Disconnect:
        """Build one canonical blank-line disconnect fixture."""
        return Disconnect(
            provenance=_BinanceEventFixture._provenance(), capture_proxy_reason="interval_end"
        )


class TestBinanceEvents:
    """Protect canonical Binance records and reusable strict event codecs."""

    def test_codec_recovers_after_rejected_decode_and_encode(self) -> None:
        """Keep deterministic bytes across failed calls and independent codec instances."""
        codec = MarketEventCodec()
        event = _BinanceEventFixture._trade()
        encoded = codec.encode(event)
        unsafe = _BinanceEventFixture._trade()
        msgspec.structs.force_setattr(unsafe, "event_time_basis", "capture_proxy")
        for _ in range(2):
            with pytest.raises(MarketEventError) as caught:
                codec.decode(encoded[:-1] + b',"unknown":1}')
            assert str(caught.value) == "canonical market event JSON is invalid"
            assert isinstance(caught.value.__cause__, msgspec.ValidationError)
            with pytest.raises(ValueError, match="trade event_time_basis must be source_event"):
                codec.encode(unsafe)
            assert codec.decode(encoded) == event
            assert codec.encode(event) == encoded
        assert MarketEventCodec().encode(event) == encoded

    def test_inherited_constructor_and_revalidation_dispatch_to_binance_invariants(self) -> None:
        """Apply Binance symbol checks through inherited construction and validation hooks."""
        assert issubclass(BinanceMarketEvent, MarketEventRecord)
        with pytest.raises(ValueError, match="uppercase ASCII"):
            _BinanceEventFixture._snapshot(symbol="btcusdt")

        snapshot = _BinanceEventFixture._snapshot()
        msgspec.structs.force_setattr(snapshot, "symbol", "btcusdt")
        with pytest.raises(ValueError, match="uppercase ASCII"):
            snapshot.validate()

    @pytest.mark.parametrize(
        ("factory", "expected_tag"),
        [
            (_BinanceEventFixture._snapshot, "depth_snapshot"),
            (_BinanceEventFixture._update, "depth_update"),
            (_BinanceEventFixture._trade, "trade"),
            (_BinanceEventFixture._disconnect, "disconnect"),
        ],
    )
    def test_all_canonical_events_round_trip_with_exact_tags(
        self, factory: Callable[[], MarketEvent], expected_tag: str
    ) -> None:
        """Round-trip every retained Binance event and preserve its discriminator bytes."""
        event = factory()
        encoded = _CODEC.encode(event)
        assert f'"event_type":"{expected_tag}"'.encode() in encoded
        assert _CODEC.decode(encoded) == event

    @pytest.mark.parametrize(
        ("factory", "invalid_basis"),
        [
            (_BinanceEventFixture._snapshot, "source_event"),
            (_BinanceEventFixture._update, "capture_proxy"),
            (_BinanceEventFixture._trade, "capture_proxy"),
        ],
    )
    def test_unsafe_event_mutation_revalidates_time_basis(
        self, factory: Callable[[], MarketEvent], invalid_basis: str
    ) -> None:
        """Reject wrong event-time semantics through the canonical validation boundary."""
        event = factory()
        msgspec.structs.force_setattr(event, "event_time_basis", invalid_basis)
        with pytest.raises(ValueError, match="event_time_basis"):
            _CODEC.validate(event)
