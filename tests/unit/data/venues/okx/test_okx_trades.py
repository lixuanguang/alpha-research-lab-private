"""Exercise the OKX public trades tape through the common capture replay."""

from __future__ import annotations

# standard library imports
from decimal import Decimal
from uuid import UUID

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions
from market_data.adapters.venues.okx import OKXTrades
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import CaptureRecord, PublicTrade
from reference_data.instruments import InstrumentId
from serialization import DomainCodec

_ACK = b'{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT"},"connId":"a"}'


class TestOKXTrades:
    """Check acknowledgement, aggressor sides, repeats and refusals on hand-authored frames."""

    @staticmethod
    def config() -> CaptureConfig:
        """Select the OKX BTC-USDT public trades feed."""
        return CaptureConfig(
            venue="okx",
            symbol="BTC-USDT",
            instrument_id=InstrumentId(UUID("00000000-0000-4000-8000-000000000001")),
            base_currency="BTC",
            quote_currency="USDT",
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
            clock_interval_ms=250,
        )

    @staticmethod
    def push(*trades: tuple[str, str, str, str, str]) -> bytes:
        """Encode one trades push of ``(id, ms, price, size, side)`` rows."""
        return DomainCodec().encode_json(
            {
                "arg": {"channel": "trades", "instId": "BTC-USDT"},
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "tradeId": trade_id,
                        "ts": ms,
                        "px": price,
                        "sz": size,
                        "side": side,
                        "count": "1",
                    }
                    for trade_id, ms, price, size, side in trades
                ],
            }
        )

    def test_trades_follow_acknowledgement_and_repeats_apply_once(self) -> None:
        """A tape is ready at its acknowledgement and applies each trade ID once."""
        tape = OKXTrades("BTC-USDT")
        assert tape.apply(_ACK) == "acknowledgement" and tape.ready
        assert (
            tape.apply(
                self.push(
                    ("11", "1790164800200", "100.2", "0.3", "sell"),
                    ("10", "1790164800100", "100.1", "0.2", "buy"),
                )
            )
            == "update"
        )
        assert tape.trades == (
            PublicTrade(
                trade_id="11",
                event_ms=1790164800200,
                price=Decimal("100.2"),
                quantity=Decimal("0.3"),
                side="sell",
            ),
            PublicTrade(
                trade_id="10",
                event_ms=1790164800100,
                price=Decimal("100.1"),
                quantity=Decimal("0.2"),
                side="buy",
            ),
        )
        assert (tape.sequence, tape.source_time) == (11, "1790164800200")
        identity = tape.identity
        assert tape.apply(self.push(("10", "1790164800100", "100.1", "0.2", "buy"))) == (
            "duplicate"
        )
        assert not tape.trades and tape.identity == identity and tape.applied == 2
        assert tape.apply(b"pong") == "heartbeat"

    @pytest.mark.parametrize(
        "frame",
        [
            b'{"arg":{"channel":"trades","instId":"ETH-USDT"},"data":[]}',
            b'{"event":"error","code":"60012","msg":"bad"}',
            b'{"arg":{"channel":"trades","instId":"BTC-USDT"},"data":[]}',
        ],
    )
    def test_foreign_error_and_empty_frames_are_refused(self, frame: bytes) -> None:
        """Another instrument, a service error or an empty push is invalid."""
        tape = OKXTrades("BTC-USDT")
        tape.apply(_ACK)
        with pytest.raises(ValueError):
            tape.apply(frame)

    def test_unacknowledged_trades_and_snapshots_are_refused(self) -> None:
        """Trades before the acknowledgement and REST snapshots do not apply."""
        tape = OKXTrades("BTC-USDT")
        with pytest.raises(ValueError, match="unacknowledged"):
            tape.apply(self.push(("1", "1790164800100", "1", "1", "buy")))
        with pytest.raises(ValueError, match="no snapshot"):
            tape.apply(_ACK, snapshot=True)

    def test_capture_replay_projects_trade_boundaries_without_depth(self) -> None:
        """The durable replay sees an empty-depth tape whose quality follows its trades."""
        config = self.config()
        assert VenueSubscriptions()(config) == (
            {"op": "subscribe", "args": [{"channel": "trades", "instId": "BTC-USDT"}]},
        )
        assert BookAdapters.capability(config).representation == "trades"
        replay = CaptureReplay(config, book_factory=BookAdapters.create)
        records = (
            CaptureRecord(kind="session", epoch=0, received_ns=1),
            CaptureRecord(kind="frame", epoch=0, received_ns=2, raw=_ACK),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=3,
                raw=self.push(("10", "1790164800100", "100.1", "0.2", "buy")),
            ),
        )
        rows = []
        for position, record in enumerate(records):
            rows.append(BookProjection.capture(position, record, replay.apply(record), replay))
        assert [(row.outcome, row.status) for row in rows] == [
            ("session", "recovering"),
            ("acknowledgement", "recovering"),
            ("update", "degraded"),
        ]
        assert not (rows[-1].bids or rows[-1].asks or rows[-1].orders)
        summary = replay.summary()
        assert (summary["representation"], summary["trades"], summary["gaps"]) == (
            "trades",
            1,
            [],
        )

    def test_trade_feeds_require_supported_venues_and_no_depth(self) -> None:
        """Only OKX and Bitfinex offer a trades feed, and it declares no depth."""
        config = self.config()
        with pytest.raises(ValueError, match="depth"):
            replace(config, depth=400)
        with pytest.raises(ValueError, match="venue/channel"):
            replace(config, venue="coinbase", symbol="BTC-USD", quote_currency="USD")
