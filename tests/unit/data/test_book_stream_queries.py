"""Protect streamed book isolation, causal cutoffs and restart equivalence."""

from __future__ import annotations

# standard library imports
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace
from test_book_datasets import TestBookDatasets as _Inputs
from test_book_replay import _View

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import CaptureRecord, CaptureRequest
from market_data.datasets import (
    BookFrameDecoder,
    BookHistory,
    BookSnapshot,
    CaptureInput,
    DatasetPublication,
    StoredBookRow,
)
from market_data.query import BookMarketRow, BookQuery, BookQueryReader
from market_data.replay import BookReplay
from market_data.storage import CaptureJournal, RawStore
from serialization import DomainCodec, FrameReader

_LIMIT = 1_048_576
_END = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=1)


class TestStreamedBookQueries:
    """Compare native streaming with in-memory admission and independent exact book values."""

    @staticmethod
    def _snapshot(tmp_path: Path) -> tuple[BookSnapshot, CaptureInput, bytes]:
        """Publish one original capture with a gap and retain independently admitted bytes."""
        capture = _Inputs._capture(tmp_path / "capture", gap=True)
        raw, snapshots = RawStore(tmp_path / "raw"), tmp_path / "snapshots"
        (tmp_path / "raw").mkdir()
        snapshots.mkdir()
        readers = SourceAdapters()
        identity = (
            DatasetPublication(readers, "a" * 64)
            .publish_captures((capture,), raw, snapshots, max_records=32, max_bytes=_LIMIT)
            .book
        )
        selected = CaptureInput.read(capture, max_records=32)
        admitted = selected.admit(raw, readers=readers, max_bytes=_LIMIT).require_canonical()
        session = BookSnapshot.read(
            snapshots, raw, readers=readers, identity=identity, max_bytes=_LIMIT
        )
        return session, selected, admitted

    def test_stream_reference_exact_states_and_cursor_restart(self, tmp_path: Path) -> None:
        """Absolute updates, deletion, gaps and nanoseconds match hand values and admission."""
        session, selected, admitted = self._snapshot(tmp_path)
        streamed = BookReplay(
            session,
            request_identity=selected.request.identity,
            terminal=_END,
            config_identity="b" * 64,
            batch_size=2,
        )
        assert (
            tuple(row for batch in streamed.batches() for row in batch)
            == DomainCodec().decode_json(admitted, BookHistory).observations
        )
        rows = tuple(row for batch in streamed.batches() for row in batch)
        assert rows[2].bids[0][1].size == Decimal("0.300000000000000001")
        assert rows[3].bids[0][1].size == Decimal("0.2")
        assert rows[4].bids == ()
        assert rows[5].status == "recovering" and rows[5].outcome == "gap"
        view = _View()
        checkpoint = streamed.step(_END, view.consume)
        assert checkpoint is not None and checkpoint.clock.microsecond == 1
        assert view.rows == list(rows) and [phase for phase, _ in view.phases] == ["source"] * len(
            rows
        ) + ["expiry", "fill", "decision", "mark"]
        resumed = BookReplay(
            session,
            request_identity=selected.request.identity,
            terminal=_END,
            config_identity="b" * 64,
            batch_size=7,
            cursor=checkpoint,
        )
        tail = _View()
        while resumed.step(_END, tail.consume):
            pass
        while streamed.step(_END, view.consume):
            pass
        assert resumed.cursor == streamed.cursor and not tail.rows
        streamed.close()
        assert streamed.cursor == resumed.cursor
        with pytest.raises(RuntimeError, match="closed"):
            streamed.step(_END, view.consume)
        with pytest.raises(ValueError, match="incompatible"):
            BookReplay(
                session,
                request_identity=selected.request.identity,
                terminal=_END,
                config_identity="c" * 64,
                batch_size=2,
                cursor=checkpoint,
            )

    def test_repeated_queries_isolate_evidence_and_preserve_cutoffs(self, tmp_path: Path) -> None:
        """A verified session serves repeats without native admission or mutable shared results."""
        session, selected, _ = self._snapshot(tmp_path)
        reader = BookQueryReader(session)
        query = BookQuery(
            snapshot_id=session.identity,
            request_identity=selected.request.identity,
            instrument=selected.request.config.instrument_id,
            start=_END - timedelta(seconds=1),
            end=_END,
            known_at=_END,
            columns=("bids", "asks"),
            batch_size=2,
            max_bytes=_LIMIT,
        )
        with patch.object(SourceAdapters, "books", side_effect=AssertionError("re-admitted raw")):
            first = tuple(reader.batches(query))
            assert sum(len(batch.rows) for batch in first) == 7
            assert all(len(batch.rows) <= 2 for batch in first)
            market = next(
                row for batch in first for row in batch.rows if isinstance(row, BookMarketRow)
            )
            level = market.values[0][0]
            assert isinstance(level, tuple)
            force_setattr(level[1], "size", Decimal("999"))
            force_setattr(first[0].evidence, "max_records", 1)
            repeated = tuple(reader.batches(query))
            assert repeated[0].evidence.max_records == 32
            market = next(
                row for batch in repeated for row in batch.rows if isinstance(row, BookMarketRow)
            )
            actual_level = market.values[0][0]
            assert isinstance(actual_level, tuple)
            assert actual_level[1].size == Decimal("0.300000000000000001")
            unknown = tuple(reader.batches(replace(query, known_at=query.start)))
            assert unknown[0].rows == ()
            controls = tuple(
                reader.batches(replace(query, start=query.start + timedelta(microseconds=1)))
            )
            assert all(
                not isinstance(row, BookMarketRow) for batch in controls for row in batch.rows
            )
            assert all(
                "no selected book values; absence does not establish an empty market"
                in batch.reasons
                for batch in controls
            )
            with pytest.raises(ValueError, match="max_bytes"):
                tuple(reader.batches(replace(query, max_bytes=1)))

    def test_pinned_file_change_rejected_before_query_delivery(self, tmp_path: Path) -> None:
        """A same-length changed canonical file cannot exploit a warm admission session."""
        session, selected, _ = self._snapshot(tmp_path)
        path = (
            tmp_path
            / "snapshots"
            / session.identity
            / session.partition(selected.request.identity).sha256
        )
        payload = path.read_bytes()
        path.chmod(0o644)
        path.write_bytes(payload.replace(b"0.300000000000000001", b"0.300000000000000002"))
        with pytest.raises(ValueError, match="changed"):
            next(session.observations(selected.request.identity))


class TestVerifiedBookReadCost:
    """Bound a verified partition read by the strict decode that it cannot avoid."""

    _root = Path(__file__).parents[3]
    _limit = 67_108_864

    @pytest.mark.performance
    def test_verified_read_validates_each_decoded_row_once(self, tmp_path: Path) -> None:
        """A read adds digest and lineage checks to decoding, not a second row validation."""
        ratios: list[float] = []
        for updates in (500, 2000):
            session, request_identity = self._publish(tmp_path / str(updates), updates)
            partition = session.partition(request_identity)
            path = tmp_path / str(updates) / "snapshots" / session.identity / partition.sha256
            with path.open("rb") as source:
                records = tuple(FrameReader.records(source))[1:]
            decode = self._median(partial(self._decode, records))
            read = self._median(partial(self._read, session, request_identity))
            print(f"{len(records)} rows: strict decode {decode:.6f}s, verified read {read:.6f}s")
            ratios.append(read / decode)
        # Re-running each decoded row's validation made reads about 1.36x the decode here.
        assert max(ratios) < 1.2

    def test_strict_row_decoding_runs_row_validation(self, tmp_path: Path) -> None:
        """Reads rely on rebuilding to refuse malformed rows, so rebuilding must validate them."""
        session, request_identity = self._publish(tmp_path, 2)
        partition = session.partition(request_identity)
        path = tmp_path / "snapshots" / session.identity / partition.sha256
        codec = DomainCodec()
        with path.open("rb") as source:
            record = tuple(FrameReader.records(source))[3][1]
        stored = codec.decode_json(record, StoredBookRow)
        assert stored.whole and stored.bids
        for field, value, message in (
            ("state_identity", "not-a-digest", "state or quality scope"),
            ("bids", (stored.bids[0], stored.bids[0]), "duplicate native order or aggregate price"),
            ("position", -1, "occurrence coordinates"),
        ):
            with pytest.raises(ValueError, match=message):
                BookFrameDecoder().decode(replace(stored, **{field: value}), frame_start=True)
        assert sum(1 for _ in session.observations(request_identity)) == 6

    @classmethod
    def _publish(cls, root: Path, updates: int) -> tuple[BookSnapshot, str]:
        """Publish a 50-level OKX snapshot followed by one-level absolute updates."""
        request = CaptureRequest(
            config=CaptureConfig.read(cls._root / "configs/live/okx-btc-usdt.json"),
            recording_id="00000000-0000-0000-0000-000000000001",
            implementation_identity="a" * 64,
        )
        journal = CaptureJournal(root / "capture", request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=1))
        journal.append(
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=2,
                raw=b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}',
            )
        )
        bids = ",".join(f'["{1000 - level}","1","0","1"]' for level in range(50))
        asks = ",".join(f'["{1001 + level}","1","0","1"]' for level in range(50))
        snapshot = _Inputs._frame("snapshot", -1, 10, f"[{bids}]", f"[{asks}]")
        journal.append(CaptureRecord(kind="frame", epoch=0, received_ns=3, raw=snapshot))
        for index in range(updates):
            size = "2" if index // 50 % 2 == 0 else "1"
            level = f'[["{1000 - index % 50}","{size}","0","1"]]'
            journal.append(
                CaptureRecord(
                    kind="frame",
                    epoch=0,
                    received_ns=4 + index * 1000,
                    raw=_Inputs._frame("update", 10 + index, 11 + index, level),
                )
            )
        journal.append(
            CaptureRecord(
                kind="end", epoch=0, received_ns=10 + updates * 1000, reason="message_limit"
            )
        )
        journal.finish(1)
        raw, snapshots = RawStore(root / "raw"), root / "snapshots"
        (root / "raw").mkdir()
        snapshots.mkdir()
        readers = SourceAdapters()
        identity = (
            DatasetPublication(readers, "a" * 64)
            .publish_captures(
                (root / "capture",), raw, snapshots, max_records=updates + 8, max_bytes=cls._limit
            )
            .book
        )
        selected = CaptureInput.read(root / "capture", max_records=updates + 8)
        session = BookSnapshot.read(
            snapshots, raw, readers=readers, identity=identity, max_bytes=cls._limit
        )
        return session, selected.request.identity

    @staticmethod
    def _decode(records: tuple[tuple[bool, bytes], ...]) -> int:
        """Strictly decode and rebuild each stored row, which validates it once."""
        codec, decoder = DomainCodec(), BookFrameDecoder()
        for frame_start, record in records:
            decoder.decode(codec.decode_json(record, StoredBookRow), frame_start=frame_start)
        return len(records)

    @staticmethod
    def _read(session: BookSnapshot, request_identity: str) -> int:
        """Read every row of a pinned partition through its verified stream."""
        return sum(1 for _ in session.observations(request_identity))

    @staticmethod
    def _median(operation: Callable[[], int], repeats: int = 7) -> float:
        """Time an operation repeatedly and return its median wall-clock seconds."""
        samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            operation()
            samples.append(time.perf_counter() - started)
        return sorted(samples)[repeats // 2]
