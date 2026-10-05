"""Prove consumers read a single journal or a segment chain as one recording."""

from __future__ import annotations

# standard library imports
import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from configuration import CaptureConfig, CaptureRunConfig
from market_data.collection.segments import CaptureSegmentWriter
from market_data.contracts import CaptureRecord, CaptureRequest, CaptureRunRequest
from market_data.storage import (
    CaptureJournal,
    CaptureRecording,
    CaptureRunJournal,
    RecordingFollower,
)

_ROOT = Path(__file__).parents[3]
_CONFIG = replace(
    CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"),
    max_messages=3,
    max_bytes=32768,
    max_frame_bytes=8192,
)
_RUN_ID = "00000000-0000-4000-8000-000000000051"
_OPEN: list[CaptureRunJournal] = []


class CaptureRecordingFixture:
    """Build capture runs, records and chained recordings."""

    @staticmethod
    def records(count: int) -> tuple[CaptureRecord, ...]:
        """Author a session followed by native heartbeat frames with increasing receipt."""
        frames = tuple(
            CaptureRecord(kind="frame", epoch=0, received_ns=1_000 + index, raw=b'[7,"hb"]')
            for index in range(count)
        )
        return (CaptureRecord(kind="session", epoch=0, received_ns=999), *frames)

    @staticmethod
    def run_request() -> CaptureRunRequest:
        """Declare a finite chain whose three-message segments roll over often."""
        now = datetime.now(UTC)
        return CaptureRunRequest(
            config=_CONFIG,
            window=CaptureRunConfig(
                start_at=now - timedelta(seconds=1),
                ready_by=now,
                stop_at=now + timedelta(minutes=1),
                max_messages=100,
                max_bytes=1_048_576,
                max_segments=8,
                max_reconnects=0,
            ),
            run_id=_RUN_ID,
            implementation_identity="a" * 64,
        )

    @staticmethod
    def chain(
        output: Path, records: tuple[CaptureRecord, ...], *, finish: bool
    ) -> tuple[CaptureRunJournal, CaptureSegmentWriter]:
        """Write records through the collector's writer; optionally seal and summarize the run."""
        request = CaptureRecordingFixture.run_request()
        run = CaptureRunJournal(output / request.run_id / request.run_id, request)
        run.open(resume=False)
        _OPEN.append(run)
        writer = CaptureSegmentWriter(
            run, run.start_segment(None), previous_bytes=0, previous_records=0
        )
        for record in records:
            asyncio.run(writer.append(record))
        if finish:
            run.sealed(writer.current, writer.first_received_ns or 1)
            run.finish({"run_identity": request.identity})
        return run, writer


class TestCaptureRecording:
    """Keep single recordings exact and read chains by run-wide position."""

    @pytest.fixture(autouse=True)
    def _release_runs(self) -> Iterator[None]:
        """Release each run's ownership lock once its test ends."""
        yield
        while _OPEN:
            _OPEN.pop().close()

    def test_single_recording_delegates_exactly_to_its_journal(self, tmp_path: Path) -> None:
        """Records, cursor and completion equal the journal's, interrupted and completed."""
        request = CaptureRequest(
            config=_CONFIG,
            recording_id="00000000-0000-4000-8000-000000000052",
            implementation_identity="a" * 64,
        )
        root = tmp_path / request.recording_id / request.recording_id
        journal = CaptureJournal(root, request)
        journal.start()
        for record in CaptureRecordingFixture.records(4):
            journal.append(record)
        recording = CaptureRecording.read(root)
        assert recording.key == request.recording_id and recording.identity == request.identity
        assert not recording.completed
        assert tuple(recording.records(completed=False)) == tuple(journal.records(completed=False))
        cursor = journal.committed_cursor()
        assert recording.cursor().segments == (cursor,)
        assert (recording.cursor().records, recording.cursor().sha256) == (5, cursor.sha256)
        assert recording.locate(4).position == 4 and recording.locate(4).ordinal == 0
        journal.finish(999)
        assert recording.completed
        assert tuple(recording.records()) == tuple(journal.records())
        (found,) = CaptureRecording.discover(tmp_path)
        assert (found.root, found.request) == (root, request)

    def test_chain_reads_run_wide_records_cursor_and_positions(self, tmp_path: Path) -> None:
        """Every segment's records follow in order; positions map to their own segment."""
        records = CaptureRecordingFixture.records(7)
        run, writer = CaptureRecordingFixture.chain(tmp_path, records, finish=True)
        recording = CaptureRecording.read(run.root)
        assert recording.key == _RUN_ID and recording.identity == run.request.identity
        assert recording.completed
        assert tuple(recording.records()) == records
        cursor = recording.cursor()
        assert [segment.records for segment in cursor.segments] == [4, 3, 1]
        assert (cursor.records, cursor.offset) == (len(records), writer.total_bytes)
        assert cursor.sha256 == cursor.segments[-1].sha256
        journals = run.segments()
        assert [
            (recording.locate(position).ordinal, recording.locate(position).position)
            for position in range(len(records))
        ] == [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (2, 0)]
        assert recording.locate(4).recording_id == journals[1].request.recording_id
        with pytest.raises(IndexError):
            recording.locate(len(records))
        (found,) = CaptureRecording.discover(tmp_path)
        assert found.request == run.request

    def test_interrupted_chain_ends_with_one_gap_on_the_last_real_clocks(
        self, tmp_path: Path
    ) -> None:
        """An unsealed or empty last segment never resets the tail gap's epoch or receipt."""
        records = CaptureRecordingFixture.records(6)
        run, writer = CaptureRecordingFixture.chain(tmp_path, records, finish=False)
        recording = CaptureRecording.read(run.root)
        assert not recording.completed
        with pytest.raises(ValueError, match="not complete"):
            tuple(recording.records())
        gap = CaptureRecord(
            kind="gap",
            epoch=0,
            received_ns=records[-1].received_ns,
            reason="interrupted_persistence_unknown_tail",
        )
        assert tuple(recording.records(completed=False)) == (*records, gap)
        # A seal whose successor is provisioned but empty: the journal alone would
        # report its tail at epoch 0, receipt 1.
        run.sealed(writer.current, writer.first_received_ns or 1)
        run.start_segment(writer.current)
        assert tuple(recording.records(completed=False)) == (*records, gap)
        assert recording.cursor().records == len(records)
        assert not recording.completed

    def test_chain_refuses_an_unsealed_earlier_segment(self, tmp_path: Path) -> None:
        """Only the last segment may be an interrupted prefix."""
        run, writer = CaptureRecordingFixture.chain(
            tmp_path, CaptureRecordingFixture.records(2), finish=False
        )
        run.start_segment(writer.current)
        with pytest.raises(ValueError, match="unsealed earlier segment"):
            tuple(CaptureRecording.read(run.root).records(completed=False))

    def test_recording_directories_must_be_named_by_their_key(self, tmp_path: Path) -> None:
        """A chain or journal moved under another name is not silently adopted."""
        run, _ = CaptureRecordingFixture.chain(
            tmp_path, CaptureRecordingFixture.records(2), finish=True
        )
        moved = tmp_path / "other" / "00000000-0000-4000-8000-000000000053"
        moved.parent.mkdir()
        run.root.rename(moved)
        with pytest.raises(ValueError, match="differs from its key"):
            CaptureRecording.read(moved)
        with pytest.raises(ValueError, match="exactly one request file"):
            CaptureRecording.read(tmp_path)


class TestRecordingFollower:
    """Follow a growing recording's durable records exactly, without writing."""

    @pytest.fixture(autouse=True)
    def _release_runs(self) -> Iterator[None]:
        """Release each run's ownership lock once its test ends."""
        yield
        while _OPEN:
            _OPEN.pop().close()

    @staticmethod
    def _journal(root: Path) -> CaptureJournal:
        """Start one single-journal recording under its key-named directory."""
        request = CaptureRequest(
            config=_CONFIG,
            recording_id="00000000-0000-4000-8000-000000000054",
            implementation_identity="a" * 64,
        )
        journal = CaptureJournal(root / request.recording_id / request.recording_id, request)
        journal.start()
        return journal

    def test_single_journal_is_followed_incrementally_up_to_its_cursor(
        self, tmp_path: Path
    ) -> None:
        """Polls return each durable record once, bounded, and never bytes past the cursor."""
        journal = self._journal(tmp_path)
        records = CaptureRecordingFixture.records(4)
        follower = RecordingFollower(CaptureRecording.read(journal.root))
        assert follower.poll(max_records=10) == ()
        for record in records[:3]:
            journal.append(record)
        assert follower.poll(max_records=2) == records[:2]
        with (journal.root / "journal.jsonl").open("ab") as unacknowledged:
            unacknowledged.write(b'{"kind":"frame"')
        assert follower.poll(max_records=10) == records[2:3]
        assert follower.poll(max_records=10) == ()
        with (journal.root / "journal.jsonl").open("r+b") as truncated:
            truncated.truncate(journal.size)
        for record in records[3:]:
            journal.append(record)
        journal.finish(999)
        assert follower.poll(max_records=10) == records[3:]
        assert follower.poll(max_records=10) == () and follower.position == len(records)
        with pytest.raises(ValueError, match="positive record bound"):
            follower.poll(max_records=0)

    def test_changed_durable_bytes_are_refused(self, tmp_path: Path) -> None:
        """A byte changed inside the acknowledged prefix fails the cursor digest."""
        journal = self._journal(tmp_path)
        for record in CaptureRecordingFixture.records(2):
            journal.append(record)
        path = journal.root / "journal.jsonl"
        payload = path.read_bytes()
        path.write_bytes(payload.replace(b"999", b"998", 1))
        with pytest.raises(ValueError, match="differ from the durable cursor"):
            RecordingFollower(CaptureRecording.read(journal.root)).poll(max_records=10)

    def test_chain_is_followed_across_segments_while_it_grows(self, tmp_path: Path) -> None:
        """Sealed segments are read to their end before the next; positions run on."""
        records = CaptureRecordingFixture.records(7)
        run, writer = CaptureRecordingFixture.chain(tmp_path, records[:5], finish=False)
        follower = RecordingFollower(CaptureRecording.read(run.root))
        assert follower.poll(max_records=100) == records[:5]
        for record in records[5:]:
            asyncio.run(writer.append(record))
        run.sealed(writer.current, writer.first_received_ns or 1)
        run.finish({"run_identity": run.request.identity})
        assert follower.poll(max_records=100) == records[5:]
        assert follower.position == len(records)
        assert follower.poll(max_records=100) == ()
