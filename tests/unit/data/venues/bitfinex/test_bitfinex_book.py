"""Exercise exact R0 state, native subscription and sequence boundaries."""

# standard library imports
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research.data.live.config import CaptureConfig
from alpha_research.data.venues.bitfinex.book import BitfinexBook

_ROOT = Path(__file__).parents[5]


class TestBitfinexBook:
    """Check lifecycle semantics independently of the live transport."""

    @staticmethod
    def book() -> BitfinexBook:
        """Negotiate the same sequenced R0 subscription as the collector.

        Returns:
            Fresh acknowledged decoder for the synthetic protocol case.
        """
        book = BitfinexBook(CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"))
        book.apply(b'{"event":"conf","status":"OK","flags":65536}')
        book.apply(
            b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCU'
            b'SD","prec":"R0","freq":"F0","len":"25"}'
        )
        return book

    def test_exact_snapshot_update_delete(self) -> None:
        """Preserve big order IDs, long decimal tokens, signs and absent source time."""
        book = self.book()
        assert (
            book.apply(
                b"[7,[[9007199254740993,60000.123456789012345678,0.123456789012345678],[2,60001,-2]],1]"
            )
            == "snapshot"
        )
        assert book.orders["9007199254740993"].price == Decimal("60000.123456789012345678")
        assert book.orders["2"].side == "sell"
        book.apply(b"[7,[2,60002,-1.5],2]")
        assert book.orders["2"].size == Decimal("1.5")
        book.apply(b"[7,[2,0,-1],3]")
        assert "2" not in book.orders
        assert book.apply(b'[7,"hb",4]') == "heartbeat"
        assert book.source_time is None

    @pytest.mark.parametrize(
        "raw",
        [
            b"bad json",
            b"[7,[1,3,0],2]",
            b"[7,[1,0,2],2]",
            b'[7,"hb",3]',
            b'[7,"hb",1]',
            b'[8,"hb",2]',
            b"[7,[1,1e400,2],2]",
        ],
    )
    def test_invalid_frames(self, raw: bytes) -> None:
        """Reject malformed numbers, deletion flags, channels, gaps and duplicates."""
        book = self.book()
        book.apply(b"[7,[[1,3,2]],1]")
        with pytest.raises(ValueError):
            book.apply(raw)

    def test_reject_aggregate_acknowledgement(self) -> None:
        """Never accept P0 as a substitute for order-level R0."""
        book = self.book()
        with pytest.raises(ValueError, match="subscription mismatch"):
            book.apply(
                b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCU'
                b'SD","prec":"P0","freq":"F0","len":"25"}'
            )

    @pytest.mark.parametrize("version", [b"3", b'"2"', b"2.0", b"null", b"true"])
    def test_reject_unsupported_version(self, version: bytes) -> None:
        """Reject incompatible or malformed advertised versions before book admission."""
        book = self.book()
        with pytest.raises(ValueError, match="unsupported Bitfinex WebSocket version"):
            book.apply(b'{"event":"info","version":' + version + b"}")

    def test_supported_version_and_heartbeat_before_ack(self) -> None:
        """A sequenced heartbeat proves liveness but cannot authorize market data."""
        book = BitfinexBook(CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"))
        assert book.apply(b'{"event":"info","version":2,"platform":{"status":1}}') == "control"
        book.apply(b'{"event":"conf","status":"OK","flags":65536}')
        assert book.apply(b'[7,"hb",1]') == "heartbeat"
        assert not book.ready and not book.acknowledged
        with pytest.raises(ValueError, match="before subscription acknowledgement"):
            book.apply(b"[7,[[1,100,2]],2]")
