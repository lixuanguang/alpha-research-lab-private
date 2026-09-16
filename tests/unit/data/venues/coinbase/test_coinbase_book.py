"""Prove Coinbase compact schema, REST bridging and resting-order lifecycle."""

# standard library imports
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from alpha_research.data.live.config import CaptureConfig
from alpha_research.data.venues.coinbase.book import CoinbaseBook

_ROOT = Path(__file__).parents[5]
_SCHEMA = (
    b'{"type":"level3","schema":{"open":["type","product_id","sequence"'
    b',"order_id","side","price","size","time"],"done":["type","product'
    b'_id","sequence","order_id","time"],"match":["type","product_id","'
    b'sequence","maker_order_id","taker_order_id","price","size","time"'
    b'],"change":["type","product_id","sequence","order_id","price","si'
    b'ze","time"],"noop":["type","product_id","sequence","time"]}}'
)
_SNAPSHOT = b'{"sequence":10,"bids":[["100","0.300000000000000001","maker"]],"asks":[]}'


class TestCoinbaseBook:
    """Independent hand-reconciled cases; fixtures never claim Exchange account access."""

    @staticmethod
    def book() -> CoinbaseBook:
        """Admit actual compact schema and selected subscription.

        Returns:
            Fresh acknowledged decoder for the synthetic protocol case.
        """
        book = CoinbaseBook(CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json"))
        book.apply(_SCHEMA)
        book.apply(
            b'{"type":"subscriptions","channels":[{"name":"level3","product_ids":["BTC-USD"]}]}'
        )
        return book

    def test_snapshot_bridge_lifecycle(self) -> None:
        """Discard covered messages and exactly apply open, match, modify and done."""
        book = self.book()
        book.apply(b'["noop","BTC-USD","9",null]')
        book.apply(b'["noop","BTC-USD","10",null]')
        book.apply(b'["open","BTC-USD","11","other","sell","102","2",null]')
        book.apply(_SNAPSHOT, snapshot=True)
        assert book.ready
        book.apply(b'["match","BTC-USD","12","maker","taker","100","0.1",null]')
        assert book.orders["maker"].size == Decimal("0.200000000000000001")
        book.apply(b'["change","BTC-USD","13","maker","101","0.2",null]')
        assert book.orders["maker"].price == Decimal("101")
        book.apply(b'["change","BTC-USD","14","not-resting","99","0.1",null]')
        book.apply(b'["done","BTC-USD","15","not-resting",null]')
        book.apply(b'["done","BTC-USD","16","other",null]')
        assert set(book.orders) == {"maker"}
        assert book.source_time is None

    def test_snapshot_alone_is_not_bridge(self) -> None:
        """Wait for sequence snapshot+1 even if covered messages arrive after REST."""
        book = self.book()
        book.apply(_SNAPSHOT, snapshot=True)
        assert not book.ready
        assert book.apply(b'["noop","BTC-USD","10",null]') == "snapshot_covered"
        book.apply(b'["noop","BTC-USD","11",null]')
        assert book.ready

    @pytest.mark.parametrize(
        "raw",
        [
            b'["noop","BTC-USD","12",null]',
            b'["match","BTC-USD","11","unknown","taker","100","0.1",null]',
            b'["match","BTC-USD","11","maker","taker","100","0.4",null]',
            b'["match","BTC-USD","11","maker","taker","100","-1",null]',
            b'["open","BTC-USD","11","maker","buy","100","1",null]',
            b'["noop","ETH-USD","11",null]',
            b'["noop","BTC-USD"]',
        ],
    )
    def test_reject_invalid_lifecycle(self, raw: bytes) -> None:
        """Reject missing maker, overfill, negatives, wrong products and discontinuity."""
        book = self.book()
        book.apply(_SNAPSHOT, snapshot=True)
        with pytest.raises(ValueError):
            book.apply(raw)

    def test_missing_schema_and_l2_snapshot(self) -> None:
        """Do not decode guessed compact fields or aggregate depth as L3."""
        book = CoinbaseBook(CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json"))
        with pytest.raises(ValueError, match="schema missing"):
            book.apply(b'["noop","BTC-USD","1",null]')
        book = self.book()
        with pytest.raises(ValueError, match="L3 order IDs"):
            book.apply(b'{"sequence":10,"bids":[["100","1"]],"asks":[]}', snapshot=True)

    def test_bridge_gap_and_overflow(self) -> None:
        """A gap during REST fetch and a full bridge buffer cannot become a valid book."""
        book = self.book()
        book.apply(b'["noop","BTC-USD","12",null]')
        with pytest.raises(ValueError, match="sequence gap"):
            book.apply(_SNAPSHOT, snapshot=True)
        book = self.book()
        book.config = replace(book.config, queue_capacity=1)
        book.apply(b'["noop","BTC-USD","11",null]')
        with pytest.raises(ValueError, match="overflow"):
            book.apply(b'["noop","BTC-USD","12",null]')

    def test_full_match_still_validates_price(self) -> None:
        """A malformed or mismatched full-fill price cannot bypass lifecycle validation."""
        book = self.book()
        book.apply(_SNAPSHOT, snapshot=True)
        with pytest.raises(ValueError, match="price differs"):
            book.apply(b'["match","BTC-USD","11","maker","taker","99","0.300000000000000001",null]')

    def test_source_timestamp_precision_and_invalid_time(self) -> None:
        """Retain nanosecond source text and reject malformed supplied source instants."""
        book = self.book()
        book.apply(_SNAPSHOT, snapshot=True)
        book.apply(b'["noop","BTC-USD","11","2026-09-15T00:00:00.123456789Z"]')
        assert book.source_time == "2026-09-15T00:00:00.123456789Z"
        with pytest.raises(ValueError):
            book.apply(b'["noop","BTC-USD","12","not-a-time"]')

    def test_duplicate_and_heartbeat_gap(self) -> None:
        """Duplicates are retained for lineage and cause explicit resnapshot, never double apply."""
        book = self.book()
        book.apply(_SNAPSHOT, snapshot=True)
        book.apply(b'["noop","BTC-USD","11",null]')
        with pytest.raises(ValueError, match="duplicate"):
            book.apply(b'["noop","BTC-USD","11",null]')
        with pytest.raises(ValueError, match="heartbeat reveals"):
            book.apply(b'{"type":"heartbeat","product_id":"BTC-USD","sequence":12}')
