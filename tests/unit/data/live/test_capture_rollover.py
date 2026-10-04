"""Prove original native bytes, sequence state and durable gaps across finite rollover."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Protocol
from unittest.mock import patch

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from applications.collect import collect_run
from configuration import CaptureConfig, CaptureRunConfig
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.adapters.transport import VenueTransport
from market_data.contracts import CaptureRecord, CaptureRequest, CaptureRunRequest, FeedSocket
from market_data.datasets import BookSnapshot, CaptureInput, DatasetPublication
from market_data.replay import SavedCaptureRun
from market_data.storage import CaptureJournal, CaptureRunJournal, RawStore
from serialization import DomainCodec

_ROOT = Path(__file__).parents[4]
_FRAMES: tuple[bytes, ...] = (
    b'{"event":"conf","status":"OK","flags":65536}',
    b'[7,"hb",1]',
    b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCUSD","prec":"R0","freq":"F0","len":"25"}',
    b"[7,[[1,100,2],[2,101,-1]],2]",
    b"[7,[1,100,0.25],3]",
    b'[7,"hb",4]',
    b"[7,[2,101,-2],5]",
)


class _ProgressWriter(Protocol):
    """The ``CaptureRunJournal.progress`` call shape, called with the run explicitly."""

    def __call__(_writer, self: CaptureRunJournal, **values: object) -> None:
        """Write the run's progress values."""
        ...


class _SealedProgress:
    """Check that sealing exposes segment counts without changing whole-run counts.

    Installed as ``CaptureRunJournal.progress`` it binds the run like a method.
    """

    def __init__(self, progress: _ProgressWriter) -> None:
        """Bind the original progress writer with no sealed segments seen."""
        self._progress = progress
        self.sealed_records: list[int] = []

    def __get__(self, instance: CaptureRunJournal, owner: type[CaptureRunJournal]) -> partial[None]:
        """Bind the observer to the run it is called on."""
        return partial(self, instance)

    def __call__(self, run: CaptureRunJournal, **values: object) -> None:
        """Write progress as before and check counts around each seal."""
        before = (
            msgspec.json.decode(
                (run.root / "progress.json").read_bytes(), type=dict[str, msgspec.Raw]
            )
            if "sealed_sha256" in values
            else {}
        )
        self._progress(run, **values)
        if "sealed_sha256" in values:
            after = msgspec.json.decode(
                (run.root / "progress.json").read_bytes(), type=dict[str, msgspec.Raw]
            )
            assert bytes(after["committed_bytes"]) == bytes(before["committed_bytes"])
            assert bytes(after["committed_records"]) == bytes(before["committed_records"])
            self.sealed_records.append(
                msgspec.json.decode(after["segment_committed_records"], type=int)
            )
            assert msgspec.json.decode(after["segment_committed_bytes"], type=int) > 0


class _CrashBeforeSegments:
    """Fail creating the segments directory, as a crash at that point would.

    Installed as ``Path.mkdir`` it binds the path like a method.
    """

    def __init__(self, segments: Path, mkdir: Callable[[Path, int, bool, bool], None]) -> None:
        """Bind the directory that fails and the original ``mkdir``."""
        self._segments = segments
        self._mkdir = mkdir

    def __get__(self, instance: Path, owner: type[Path]) -> partial[None]:
        """Bind the replacement to the path it is called on."""
        return partial(self, instance)

    def __call__(
        self, path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """Refuse the segments directory and create any other directory as before."""
        if path == self._segments:
            raise OSError("process died before provisioning segments")
        self._mkdir(path, mode, parents, exist_ok)


class RolloverSocket:
    """Expose one independently authored finite native connection without storage mocks."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        """Bind the exact wire sequence and keep the socket open after the last message."""
        self._frames = iter(frames)
        self.sent: list[str] = []
        self.closed = False

    async def recv(self) -> bytes:
        """Yield original native messages, then wait for the collector's finite stop."""
        await asyncio.sleep(0)
        frame = next(self._frames, None)
        if frame is None:
            await asyncio.sleep(3600)
            raise AssertionError("collector failed to enforce its deadline")
        return frame

    async def send(self, message: str) -> None:
        """Retain outbound subscription count to detect an accidental rollover reconnect."""
        self.sent.append(message)

    async def close(self) -> None:
        """Expose actual collector ownership release."""
        self.closed = True


class RolloverTransport(VenueTransport):
    """Replace only public routing while preserving the installed parser and journal."""

    def __init__(self, config: CaptureConfig, frames: tuple[bytes, ...] = _FRAMES) -> None:
        """Bind one permitted connection and its original frames."""
        super().__init__(config)
        self.frames = frames
        self.sockets: list[RolloverSocket] = []

    async def open(self, timeout: float) -> FeedSocket:
        """Open a fresh native session and expose whether rollover improperly called again."""
        socket = RolloverSocket(self.frames)
        self.sockets.append(socket)
        return socket


class FailingSocket(RolloverSocket):
    """Fail receipt with an exception outside the handled transport error types."""

    async def recv(self) -> bytes:
        """Deliver the authored prefix, then raise an unexpected receiver error."""
        await asyncio.sleep(0)
        frame = next(self._frames, None)
        if frame is None:
            raise RuntimeError("unexpected receiver failure")
        return frame


class FailingTransport(RolloverTransport):
    """Open sockets whose receipt fails after their original frames."""

    async def open(self, timeout: float) -> FeedSocket:
        """Open one failing native session."""
        socket = FailingSocket(self.frames)
        self.sockets.append(socket)
        return socket


class TestCaptureRollover:
    """Exercise persistent native sequence, publication, ownership and crash-prefix recovery."""

    @staticmethod
    def _request(*, messages: int = 7, segment_messages: int = 4) -> CaptureRunRequest:
        """Declare a small finite window independently of its segment message ceiling."""
        now = datetime.now(UTC)
        config = replace(
            CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"),
            max_messages=segment_messages,
            max_bytes=32768,
            max_frame_bytes=8192,
            queue_capacity=16,
            retries=0,
        )
        return CaptureRunRequest(
            config=config,
            window=CaptureRunConfig(
                start_at=now - timedelta(seconds=1),
                ready_by=now + timedelta(seconds=30),
                stop_at=now + timedelta(seconds=60),
                max_messages=messages,
                max_bytes=1_048_576,
                max_segments=8,
                max_reconnects=2,
            ),
            run_id="00000000-0000-4000-8000-000000000030",
            implementation_identity="a" * 64,
        )

    def test_rollover_keeps_socket_snapshot_sequence_and_publication(self, tmp_path: Path) -> None:
        """A suffix without a snapshot reconstructs exactly from immutable predecessor bytes."""
        request = self._request()
        transport = RolloverTransport(request.config)
        root = tmp_path / "run"
        observe_progress = _SealedProgress(CaptureRunJournal.progress)
        sealed_records = observe_progress.sealed_records
        with patch.object(CaptureRunJournal, "progress", observe_progress):
            summary = asyncio.run(collect_run(request, root, transport=transport))
        assert len(transport.sockets) == 1 and transport.sockets[0].closed
        assert len(transport.sockets[0].sent) == 2
        assert summary["segments"] == 2
        assert summary["snapshots"] == 1 and summary["updates"] == 2
        assert summary["source_sequence"] == 5
        assert summary["replay_verification"] == "pending"
        journals = CaptureRunJournal(root, request).segments()
        assert tuple(sealed_records) == tuple(
            journal.committed_cursor().records for journal in journals
        )
        records = tuple(
            record for journal in journals for record in journal.records(completed=True)
        )
        assert tuple(record.raw for record in records if record.kind == "frame") == _FRAMES
        assert sum(record.kind == "session" for record in records) == 1
        assert all(record.epoch == 0 for record in records)
        assert journals[1].request.segment is not None
        assert journals[1].request.segment.previous_request_identity == journals[0].request.identity
        assert not any(
            record.kind in ("session", "snapshot") for record in journals[1].records(completed=True)
        )
        replay = SavedCaptureRun.read(root, book_factory=BookAdapters.create, max_seconds=30)
        assert replay.summary()["trace_identity"] == summary["trace_identity"]
        assert replay.book.orders["1"].size == Decimal("0.25")
        assert replay.book.orders["2"].size == Decimal("2")
        raw_root, snapshot_root = tmp_path / "raw", tmp_path / "snapshots"
        raw_root.mkdir()
        snapshot_root.mkdir()
        readers, raw = SourceAdapters(), RawStore(raw_root)
        identity = (
            DatasetPublication(readers, "b" * 64)
            .publish_captures(
                tuple(journal.root for journal in journals),
                raw,
                snapshot_root,
                max_records=32,
                max_bytes=1_048_576,
            )
            .book
        )
        snapshot = BookSnapshot.read(
            snapshot_root, raw, readers=readers, identity=identity, max_bytes=1_048_576
        )
        suffix = CaptureInput.read(journals[1].root, max_records=32)
        rows = tuple(snapshot.observations(suffix.request.identity))
        updates = tuple(row for row in rows if row.outcome == "update")
        assert len(updates) == 2
        assert updates[0].sequence == 3 and updates[1].sequence == 5
        assert updates[0].received_ns == next(
            record.received_ns for record in records if record.raw == _FRAMES[4]
        )
        assert updates[1].orders[0].size == Decimal("0.25")
        assert len(suffix.capture_chain()) == 2

    def test_resume_retains_original_tail_gap_and_fresh_snapshot(self, tmp_path: Path) -> None:
        """A saved cursor survives an unknown tail; recovery begins with explicit gap and epoch."""
        request = self._request(messages=12, segment_messages=20)
        now = datetime.now(UTC)
        request = replace(
            request,
            window=replace(
                request.window,
                start_at=now - timedelta(seconds=60),
                ready_by=now - timedelta(seconds=10),
                stop_at=now + timedelta(seconds=60),
            ),
        )
        root = tmp_path / "run"
        run = CaptureRunJournal(root, request)
        run.open(resume=False)
        journal = run.start_segment(None)
        at = time.time_ns() - 40_000_000_000
        original = [CaptureRecord(kind="session", epoch=0, received_ns=at)]
        original.extend(
            CaptureRecord(kind="frame", epoch=0, received_ns=at + index + 1, raw=frame)
            for index, frame in enumerate(_FRAMES[:5])
        )
        for record in original:
            journal.append(record)
        run.progress(status="collecting", actual_ready_ns=at + 4)
        run.close()
        with (journal.root / "journal.jsonl").open("ab") as output:
            output.write(b'{"kind":"frame","raw":"unacknowledged')
        retained = (journal.root / "journal.jsonl").read_bytes()
        transport = RolloverTransport(request.config)
        summary = asyncio.run(collect_run(request, root, resume=True, transport=transport))
        assert (journal.root / "journal.jsonl").read_bytes() == retained
        assert summary["retained_unknown_tail_bytes"] == len(retained) - journal.size
        assert len(transport.sockets) == 1
        replay = SavedCaptureRun.read(root, book_factory=BookAdapters.create, max_seconds=30)
        assert replay.snapshots == 2 and replay.epoch == 1
        assert replay.book.orders["1"].size == Decimal("0.25")
        assert any(gap["reason"] == "interrupted_persistence_unknown_tail" for gap in replay.gaps)
        new = CaptureRunJournal(root, request).segments()[1]
        suffix = tuple(new.records(completed=True))
        assert suffix[0].kind == "gap" and suffix[1].kind == "session"
        assert suffix[0].epoch == 0 and suffix[1].epoch == 1
        assert tuple(journal.records(completed=True)) == tuple(original)

    def test_fixed_deadline_closes_socket_with_no_rollover_gap(self, tmp_path: Path) -> None:
        """Source receipt stops at the declared UTC end while offline replay remains separate."""
        request = self._request(messages=100, segment_messages=100)
        now = datetime.now(UTC)
        request = replace(
            request,
            window=replace(
                request.window,
                ready_by=now + timedelta(seconds=0.15),
                stop_at=now + timedelta(seconds=0.3),
            ),
        )
        transport = RolloverTransport(request.config)
        started = time.monotonic()
        summary = asyncio.run(collect_run(request, tmp_path / "run", transport=transport))
        assert time.monotonic() - started < 2
        assert summary["reached_stop_deadline"] and summary["gaps"] == []
        assert summary["messages"] == 7 and transport.sockets[0].closed
        SavedCaptureRun.read(tmp_path / "run", book_factory=BookAdapters.create, max_seconds=30)

    @pytest.mark.parametrize("frames", [(), _FRAMES[:4]], ids=["immediate", "after-snapshot"])
    def test_unexpected_receiver_failure_seals_visible_gap(
        self, tmp_path: Path, frames: tuple[bytes, ...]
    ) -> None:
        """A receiver exception ends its session with a durable gap instead of blocking drain."""
        request = self._request(messages=100, segment_messages=100)
        request = replace(request, window=replace(request.window, max_reconnects=0))
        transport = FailingTransport(request.config, frames)
        started = time.monotonic()
        summary = asyncio.run(
            asyncio.wait_for(collect_run(request, tmp_path / "run", transport=transport), 10)
        )
        assert time.monotonic() - started < 5
        assert summary["stop_reason"] == "receiver_failed_unknown_loss"
        assert transport.sockets[0].closed
        replay = SavedCaptureRun.read(
            tmp_path / "run", book_factory=BookAdapters.create, max_seconds=30
        )
        assert any(gap["reason"] == "receiver_failed_unknown_loss" for gap in replay.gaps)
        assert replay.messages == len(frames)

    @pytest.mark.parametrize("interruption", ["directory", "partial-request", "no-cursor"])
    def test_resume_sets_aside_a_segment_whose_provisioning_was_interrupted(
        self, tmp_path: Path, interruption: str
    ) -> None:
        """A crash inside segment provisioning leaves no acknowledged record to lose."""
        request = self._request()
        root = tmp_path / "run"
        run = CaptureRunJournal(root, request)
        run.open(resume=False)
        first = run.start_segment(None)
        first.append(CaptureRecord(kind="session", epoch=0, received_ns=time.time_ns()))
        if interruption == "no-cursor":
            # Died after the request and empty journal, before the cursor commit.
            interrupted = run.start_segment(first).root
            (interrupted / "cursor.json").unlink()
        else:
            interrupted = root / "segments" / "11111111-1111-4111-8111-111111111111"
            interrupted.mkdir()
            if interruption == "partial-request":
                (interrupted / "request.json").write_bytes(b'{"config":')
        run.close()
        resumed = CaptureRunJournal(root, request)
        try:
            journals = resumed.open(resume=True)
            assert tuple(journal.root for journal in journals) == (first.root,)
            assert not interrupted.exists()
            assert (root / "interrupted-segments" / interrupted.name).is_dir()
        finally:
            resumed.close()

    def test_resume_finishes_a_run_interrupted_before_its_segments_directory(
        self, tmp_path: Path
    ) -> None:
        """A crash after the run request but before segments/ leaves a resumable run."""
        request = self._request()
        root = tmp_path / "run"
        run = CaptureRunJournal(root, request)
        crash = _CrashBeforeSegments(root / "segments", Path.mkdir)
        with patch.object(Path, "mkdir", crash), pytest.raises(OSError):
            run.open(resume=False)
        assert sorted(path.name for path in root.iterdir()) == ["owner.lock", "run-request.json"]
        with pytest.raises(FileExistsError):
            CaptureRunJournal(root, request).open(resume=False)
        resumed = CaptureRunJournal(root, request)
        try:
            assert resumed.open(resume=True) == ()
            assert (root / "segments").is_dir()
            assert resumed.start_segment(None).root.parent == root / "segments"
        finally:
            resumed.close()

    def test_resume_refuses_an_uncommitted_segment_holding_records(self, tmp_path: Path) -> None:
        """Only an empty, never-committed segment may be set aside on resume."""
        request = self._request()
        root = tmp_path / "run"
        run = CaptureRunJournal(root, request)
        run.open(resume=False)
        second = run.start_segment(run.start_segment(None))
        second.append(CaptureRecord(kind="session", epoch=0, received_ns=time.time_ns()))
        (second.root / "cursor.json").unlink()
        run.close()
        with pytest.raises(ValueError, match="unacknowledged"):
            CaptureRunJournal(root, request).open(resume=True)
        assert second.root.exists()

    def test_exclusive_owner_and_changed_resume_request(self, tmp_path: Path) -> None:
        """Concurrent owners and deadline changes fail before any source is opened."""
        request = self._request()
        root = tmp_path / "run"
        owner = CaptureRunJournal(root, request)
        owner.open(resume=False)
        try:
            with pytest.raises(BlockingIOError):
                CaptureRunJournal(root, request).open(resume=True)
        finally:
            owner.close()
        changed = replace(
            request,
            window=replace(request.window, stop_at=request.window.stop_at + timedelta(seconds=1)),
        )
        with pytest.raises(ValueError, match="exact retained"):
            CaptureRunJournal(root, changed).open(resume=True)

    def test_byte_limit_and_persistence_failure_remain_visible(self, tmp_path: Path) -> None:
        """A total byte refusal preserves a gap; fsync failure never becomes a transport retry."""
        request = self._request()
        request = replace(request, window=replace(request.window, max_bytes=24576))
        oversized = (*_FRAMES[:4], b" " * 8000, b" " * 8000)
        summary = asyncio.run(
            collect_run(
                request,
                tmp_path / "bounded",
                transport=RolloverTransport(request.config, oversized),
            )
        )
        assert summary["stop_reason"] == "run_byte_limit_unknown_tail"
        saved_bytes = summary["saved_bytes"]
        assert isinstance(saved_bytes, int) and saved_bytes <= request.window.max_bytes
        SavedCaptureRun.read(tmp_path / "bounded", book_factory=BookAdapters.create, max_seconds=30)
        transport = RolloverTransport(request.config)
        with patch.object(CaptureJournal, "append", side_effect=OSError("fsync unavailable")):
            with pytest.raises(OSError, match="fsync unavailable"):
                asyncio.run(collect_run(request, tmp_path / "failed", transport=transport))
        assert transport.sockets == []
        assert not (tmp_path / "failed" / "run-summary.json").exists()

    def test_explicit_wire_fields_and_fixed_profile_boundaries(self) -> None:
        """Unset lineage and scope encode as null; one-hour segment ceilings remain."""
        request = self._request()
        single = CaptureRequest(
            config=request.config,
            recording_id=request.run_id,
            implementation_identity=request.implementation_identity,
        )
        encoded = DomainCodec().encode_json(single)
        assert b'"universes":null' in encoded and b'"segment":null' in encoded
        assert single.identity == hashlib.sha256(encoded).hexdigest()
        with pytest.raises(ValueError, match="resource"):
            replace(request.config, duration_seconds=3601)
        with pytest.raises(ValueError, match="73 hours"):
            replace(
                request.window,
                stop_at=request.window.start_at + timedelta(hours=73, microseconds=1),
            )
        with pytest.raises(ValueError, match="UTC"):
            replace(request.window, start_at=request.window.start_at.replace(tzinfo=None))
        with pytest.raises(ValueError, match="resource"):
            replace(request.window, max_messages=True)
        with pytest.raises(ValueError, match="typed"):
            invalid: dict[str, str] = {}
            replace(request, config=invalid)
