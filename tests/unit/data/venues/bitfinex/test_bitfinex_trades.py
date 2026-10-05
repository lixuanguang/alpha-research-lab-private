"""Exercise the sequenced Bitfinex public trades tape."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from uuid import UUID

# third party library imports
import pytest

# project library imports
from configuration import CaptureConfig
from market_data.adapters.transport import VenueSubscriptions
from market_data.adapters.venues.bitfinex import BitfinexTrades
from reference_data.instruments import InstrumentId

_CONF = b'{"event":"conf","status":"OK","flags":65536}'
_SUBSCRIBED = (
    b'{"event":"subscribed","channel":"trades","chanId":7,"symbol":"tBTCUSD","pair":"BTCUSD"}'
)


class TestBitfinexTrades:
    """Check snapshot order, execution confirmations and sequence continuity."""

    @staticmethod
    def config() -> CaptureConfig:
        """Select the Bitfinex BTC/USD public trades feed."""
        return CaptureConfig(
            venue="bitfinex",
            symbol="tBTCUSD",
            instrument_id=InstrumentId(UUID("00000000-0000-4000-8000-000000000002")),
            base_currency="BTC",
            quote_currency="USD",
            channel="trades",
            depth=0,
            duration_seconds=60,
            max_messages=1000,
            max_bytes=1_000_000,
            max_frame_bytes=100_000,
            queue_capacity=100,
            max_orders=1,
            retries=0,
            idle_seconds=30,
        )

    def tape(self) -> BitfinexTrades:
        """Return a negotiated and acknowledged tape awaiting its snapshot."""
        tape = BitfinexTrades(self.config())
        assert tape.apply(_CONF) == tape.apply(_SUBSCRIBED) == "control"
        return tape

    def test_snapshot_is_chronological_and_confirmations_repeat_executions(self) -> None:
        """The newest-first snapshot applies oldest first; ``tu`` after ``te`` is a repeat."""
        assert VenueSubscriptions()(self.config()) == (
            {"event": "conf", "flags": 65536},
            {"event": "subscribe", "channel": "trades", "symbol": "tBTCUSD"},
        )
        tape = self.tape()
        assert not tape.ready
        assert (
            tape.apply(b"[7,[[8,1790164800200,-0.15,101.2],[7,1790164800100,0.25,101.3]],1]")
            == "snapshot"
        )
        assert tape.ready
        assert [(item.trade_id, item.side, item.quantity) for item in tape.trades] == [
            ("7", "buy", Decimal("0.25")),
            ("8", "sell", Decimal("0.15")),
        ]
        assert tape.apply(b'[7,"te",[9,1790164800300,-0.5,101.1],2]') == "update"
        assert tape.source_time == "1790164800300"
        assert tape.apply(b'[7,"tu",[9,1790164800300,-0.5,101.1],3]') == "duplicate"
        assert tape.apply(b'[7,"hb",4]') == "heartbeat"
        assert tape.applied == 3 and tape.sequence == 4

    @pytest.mark.parametrize(
        "frame",
        [
            b'[7,"te",[9,1790164800300,-0.5,101.1],3]',
            b'[8,"te",[9,1790164800300,-0.5,101.1],2]',
            b'[7,"te",[9,1790164800300,0,101.1],2]',
            b'[7,"fte",[9,1790164800300,-0.5,101.1],2]',
            b"[7,[],2]",
        ],
    )
    def test_gaps_foreign_channels_and_malformed_trades_are_refused(self, frame: bytes) -> None:
        """A sequence gap, other channel, zero amount, unknown event or second snapshot fails."""
        tape = self.tape()
        tape.apply(b"[7,[],1]")
        with pytest.raises(ValueError):
            tape.apply(frame)

    def test_trades_before_acknowledgement_or_with_other_symbols_are_refused(self) -> None:
        """Negotiation must succeed for this pair before any trade applies."""
        tape = BitfinexTrades(self.config())
        with pytest.raises(ValueError, match="mismatch"):
            tape.apply(_SUBSCRIBED)
        tape.apply(_CONF)
        with pytest.raises(ValueError, match="mismatch"):
            tape.apply(_SUBSCRIBED.replace(b"tBTCUSD", b"tETHUSD"))
        with pytest.raises(ValueError, match="unacknowledged"):
            tape.apply(b"[7,[],1]")
