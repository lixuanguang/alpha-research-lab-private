"""Stream study markets from a published capture larger than the in-memory admission bound."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig, UniverseSelection
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.books import BookProjection, CaptureReplay
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from market_data.datasets import CaptureInput, DatasetPublication
from market_data.query import BookQuery
from market_data.storage import CaptureJournal, RawStore
from research.experiments import TimeWindow
from research.exploration import (
    BookSelection,
    ResearchReader,
    ResearchSelection,
    SavedDecisionSource,
)
from research.observations import InputRequirement, LiveBookDecisionSource, NumericField
from research.studies import CapturedStudyMarket
from simulation import IntentMarket

_ROOT = Path(__file__).resolve().parents[3]
_ACK = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'
_UPDATES = 10_100
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_START_NS = 1_790_164_800_000_000_000
_LIMIT = 256_000_000


class CapturedMarketFixture:
    """Author an OKX books capture with more updates than in-memory admission allows."""

    @staticmethod
    def frame(action: str, previous: int, sequence: int, bids: str, asks: str) -> bytes:
        """Build one OKX books message with explicit sequence linkage."""
        return (
            f'{{"arg":{{"channel":"books","instId":"BTC-USDT"}},"action":"{action}",'
            f'"data":[{{"prevSeqId":{previous},"seqId":{sequence},'
            f'"bids":{bids},"asks":{asks}}}]}}'
        ).encode()

    @classmethod
    def records(cls, *, updates: int, spacing_ns: int) -> tuple[CaptureRecord, ...]:
        """Author the session, snapshot, size updates and end, ``spacing_ns`` apart."""
        bids = '[["100","1","0","1"],["99","1","0","1"],["98","1","0","1"]]'
        asks = '[["101","1","0","1"],["102","1","0","1"],["103","1","0","1"]]'
        records = [
            CaptureRecord(kind="session", epoch=0, received_ns=_START_NS),
            CaptureRecord(kind="frame", epoch=0, received_ns=_START_NS + 1, raw=_ACK),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=_START_NS + 2,
                raw=cls.frame("snapshot", -1, 10, bids, asks),
            ),
        ]
        for index in range(updates):
            size = "2" if index % 2 else "3"
            records.append(
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=_START_NS + spacing_ns * (index + 1),
                    raw=cls.frame(
                        "update", 10 + index, 11 + index, f'[["100","{size}","0","1"]]', "[]"
                    ),
                )
            )
        end = _START_NS + spacing_ns * (updates + 2)
        records.append(CaptureRecord(kind="end", epoch=0, received_ns=end, reason="message_limit"))
        return tuple(records)

    @classmethod
    def capture(cls, root: Path, *, updates: int = _UPDATES, spacing_ns: int = 1_000_000) -> Path:
        """Write the OKX books capture with ``updates`` size changes ``spacing_ns`` apart."""
        config = replace(
            CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"),
            max_messages=20_000,
            max_bytes=_LIMIT,
        )
        selected = (config.instrument_id,)
        request = CaptureRequest(
            config=config,
            recording_id="00000000-0000-0000-0000-000000000021",
            implementation_identity="a" * 64,
            universes=UniverseSelection(
                collection=selected, research=selected, strategy=(), authorized_trading=()
            ),
        )
        capture = root / "capture"
        journal = CaptureJournal(capture, request)
        journal.start()
        for record in cls.records(updates=updates, spacing_ns=spacing_ns):
            journal.append(record)
        journal.finish(_START_NS)
        return capture

    @classmethod
    def publish(cls, root: Path) -> tuple[Path, RawStore, str, str]:
        """Publish the capture and return its snapshot and request identities."""
        capture = cls.capture(root)
        (root / "raw").mkdir()
        (root / "snapshots").mkdir()
        raw = RawStore(root / "raw")
        identity = (
            DatasetPublication(SourceAdapters(), "b" * 64)
            .publish_captures(
                (capture,), raw, root / "snapshots", max_records=20_000, max_bytes=_LIMIT
            )
            .book
        )
        selection = CaptureInput.read(capture, max_records=20_000)
        return root / "snapshots", raw, identity, selection.request.identity

    @staticmethod
    def at(ns: int) -> datetime:
        """Round Unix nanoseconds up to the microsecond clock."""
        return _EPOCH + timedelta(microseconds=(ns + 999) // 1000)


class TestCapturedStudyMarket:
    """Read bounded windows without loading the capture into memory."""

    @staticmethod
    def book(row: IntentMarket) -> BookObservation:
        """Return a market's book, which every captured row carries."""
        if row.book is None:
            raise AssertionError("captured market row has no book")
        return row.book

    def test_streams_one_window_with_a_declared_depth_bound(self, tmp_path: Path) -> None:
        """Only the window's books are projected, each with at most two levels a side."""
        snapshots, raw, snapshot_id, request_identity = CapturedMarketFixture.publish(tmp_path)
        assert CaptureInput.read(tmp_path / "capture", max_records=20_000).max_records > 10_000
        market = CapturedStudyMarket(
            snapshots,
            raw,
            readers=SourceAdapters(),
            snapshot_id=snapshot_id,
            request_identity=request_identity,
            max_bytes=_LIMIT,
            clock_assumption="receipt-as-matching",
            max_levels=2,
        )
        start = CapturedMarketFixture.at(_START_NS + 1_000_000 * 10_000)
        window = TimeWindow(start=start, end=start + timedelta(milliseconds=50))
        rows = market.read(window)
        assert len(rows) == 51
        assert all(window.start <= row.known_at <= window.end for row in rows)
        assert all(len(self.book(row).bids) == 2 and len(self.book(row).asks) == 2 for row in rows)
        prices = [price for price, _ in self.book(rows[0]).bids]
        assert prices == sorted(prices, reverse=True)
        full = CapturedStudyMarket(
            snapshots,
            raw,
            readers=SourceAdapters(),
            snapshot_id=snapshot_id,
            request_identity=request_identity,
            max_bytes=_LIMIT,
            clock_assumption="receipt-as-matching",
        )
        assert full.identity != market.identity
        assert len(self.book(full.read(window)[0]).bids) == 3

    def test_refuses_an_undeclared_depth_bound(self, tmp_path: Path) -> None:
        """A depth bound must be positive; it is refused before any snapshot I/O."""
        (tmp_path / "raw").mkdir()
        with pytest.raises(ValueError, match="depth bound"):
            CapturedStudyMarket(
                tmp_path / "absent",
                RawStore(tmp_path / "raw"),
                readers=SourceAdapters(),
                snapshot_id="0" * 64,
                request_identity="0" * 64,
                max_bytes=_LIMIT,
                clock_assumption="receipt-as-matching",
                max_levels=0,
            )


class TestSavedBookFields:
    """Read imbalance and the touch from a published book exactly as the live source does."""

    def test_live_and_saved_book_fields_agree(self, tmp_path: Path) -> None:
        """Every field matches at cutoffs between, on and after updates."""
        spacing = 100_000_000
        capture = CapturedMarketFixture.capture(tmp_path, updates=40, spacing_ns=spacing)
        (tmp_path / "raw").mkdir()
        (tmp_path / "snapshots").mkdir()
        raw = RawStore(tmp_path / "raw")
        snapshot = (
            DatasetPublication(SourceAdapters(), "b" * 64)
            .publish_captures(
                (capture,), raw, tmp_path / "snapshots", max_records=20_000, max_bytes=_LIMIT
            )
            .book
        )
        request = CaptureInput.read(capture, max_records=20_000).capture
        assert request is not None
        requirements = tuple(
            InputRequirement(
                name="book",
                family="book",
                clock="receipt",
                field=NumericField(name=name, units=units),
                max_age_us=1_000_000,
            )
            for name, units in (
                ("imbalance", "dimensionless"),
                ("ask", "quote/base"),
                ("bid", "quote/base"),
                ("ask_size", "base"),
                ("bid_size", "base"),
            )
        )
        start = CapturedMarketFixture.at(_START_NS)
        saved = SavedDecisionSource(
            ResearchReader(tmp_path / "snapshots", raw, readers=SourceAdapters()),
            ResearchSelection(
                inputs=(
                    BookSelection(
                        name="book",
                        query=BookQuery(
                            snapshot_id=snapshot,
                            request_identity=request.identity,
                            instrument=request.config.instrument_id,
                            start=start - timedelta(minutes=1),
                            end=start + timedelta(minutes=1),
                            known_at=start + timedelta(seconds=10),
                            columns=("bids", "asks"),
                            batch_size=1000,
                            max_bytes=_LIMIT,
                        ),
                    ),
                )
            ),
            requirements,
        )
        live = LiveBookDecisionSource(request, requirements, history_capacity=1000)
        replay = CaptureReplay(request.config, book_factory=BookAdapters.create)
        records = CapturedMarketFixture.records(updates=40, spacing_ns=spacing)
        entity = str(request.config.instrument_id)
        index, present = 0, 0
        for step in range(1, 90):
            at = start + timedelta(milliseconds=50 * step)
            while (
                index < len(records) and CapturedMarketFixture.at(records[index].received_ns) <= at
            ):
                record = records[index]
                live.accept(
                    record, BookProjection.capture(index, record, replay.apply(record), replay)
                )
                index += 1
            expected = [row.value for row in live.read(entity, at).observations]
            assert [row.value for row in saved.read(entity, at).observations] == expected, at
            present += sum(value is not None for value in expected)
        assert present > 200
