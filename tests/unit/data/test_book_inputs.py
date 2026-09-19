"""Verify canonical L3 admission at its first saved-input consumer."""

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import CaptureRecord, CaptureRequest, Order
from market_data.datasets import BookHistory, BookInput, DatasetPublication
from market_data.query import BookMarketRow, BookQuery, BookQueryReader
from market_data.storage import CaptureJournal, RawStore
from serialization import DomainCodec

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
                    raw=(
                        _ROOT / "tests/fixtures/market_data/coinbase/coinbase-schema.json"
                    ).read_bytes(),
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
                    raw=(
                        _ROOT / "tests/fixtures/market_data/coinbase/coinbase-snapshot.json"
                    ).read_bytes(),
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
        report = BookInput.read(root, max_records=32).admit(
            RawStore(root), readers=SourceAdapters(), max_bytes=_LIMIT
        )
        history = _CODEC.decode_json(report.require_canonical(), BookHistory)
        match = history.observations[-3]
        assert match.orders[0].order_id == "maker"
        assert match.orders[0].size == Decimal("0.200000000000000001")
        assert history.observations[-2].outcome == "duplicate"
        assert report.duplicate_count == 1
        assert history.observations[4].status == "degraded"
        raw_path, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw_path.mkdir()
        snapshots.mkdir()
        raw = RawStore(raw_path)
        identity = DatasetPublication(SourceAdapters(), "a" * 64).publish_books(
            (root,), raw, snapshots, max_records=32, max_bytes=_LIMIT
        )
        query = BookQuery(
            snapshot_id=identity,
            request_identity=request.identity,
            instrument=config.instrument_id,
            start=datetime(1970, 1, 1, tzinfo=UTC),
            end=datetime(1970, 1, 2, tzinfo=UTC),
            known_at=datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=1),
            columns=("orders",),
            batch_size=2,
            max_bytes=_LIMIT,
        )
        batches = BookQueryReader.read(snapshots, raw, readers=SourceAdapters(), query=query)
        market = tuple(
            row for batch in batches for row in batch.rows if isinstance(row, BookMarketRow)
        )
        assert len(market) == 2
        maker = market[-1].values[0][0]
        assert isinstance(maker, Order)
        assert maker.order_id == "maker" and maker.size == Decimal("0.200000000000000001")
        assert batches[0].evidence.request.config.quote_currency == "USD"
