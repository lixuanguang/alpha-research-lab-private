"""Verify canonical L3 admission at its first saved-input consumer."""

# standard library imports
from decimal import Decimal
from pathlib import Path

# project library imports
from alpha_research.data.book_datasets import BookHistory, BookInput
from alpha_research.data.live.config import CaptureConfig, CaptureRequest
from alpha_research.data.live.journal import CaptureJournal, CaptureRecord
from alpha_research.data.raw_store import RawStore
from alpha_research.serialization import DomainCodec

_ROOT = Path(__file__).parents[3]
_CODEC = DomainCodec()
_LIMIT = 1_048_576


class TestBookInputs:
    """Check observable admission and refusal without credentials or network access."""

    def test_coinbase_native_lifecycle_is_not_trade_deduplicated(self, tmp_path: Path) -> None:
        """Retain the native maker ID and both raw matches while applying the match once."""
        config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        request = CaptureRequest(
            config=config,
            recording_id="00000000-0000-0000-0000-000000000002",
            implementation_identity="a" * 64,
        )
        root = tmp_path / "coinbase"
        journal = CaptureJournal(root, request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=1))
        for index, record in enumerate(
            (
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=2,
                    raw=(_ROOT / "tests/fixtures/l3/coinbase-schema.json").read_bytes(),
                ),
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=3,
                    raw=b'{"type":"subscriptions","channels":[{"name":"level3","product_ids":["BTC-USD"]}]}',
                ),
                CaptureRecord(
                    kind="frame", epoch=0, received_ns=4, raw=b'["noop","BTC-USD","11",null]'
                ),
                CaptureRecord(
                    kind="snapshot",
                    epoch=0,
                    received_ns=5,
                    raw=(_ROOT / "tests/fixtures/l3/coinbase-snapshot.json").read_bytes(),
                ),
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=6,
                    raw=b'["match","BTC-USD","12","maker","taker","100","0.1",null]',
                ),
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=7,
                    raw=b'["match","BTC-USD","12","maker","taker","100","0.1",null]',
                ),
                CaptureRecord(kind="end", epoch=0, received_ns=8, reason="message_limit"),
            )
        ):
            journal.append(record)
        journal.finish(1)
        report = BookInput.read(root, max_records=32).admit(RawStore(root), max_bytes=_LIMIT)
        history = _CODEC.decode_json(report.require_canonical(), BookHistory)
        match = history.observations[-3]
        assert match.orders[0].order_id == "maker"
        assert match.orders[0].size == Decimal("0.200000000000000001")
        assert history.observations[-2].outcome == "duplicate"
        assert report.duplicate_count == 1
        assert history.observations[4].status == "degraded"
