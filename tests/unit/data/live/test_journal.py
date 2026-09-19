"""Prove append acknowledgements against disk faults, corruption and process loss."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters
from market_data.contracts import CaptureCursor, CaptureRecord, CaptureRequest
from market_data.replay import SavedCapture
from market_data.storage import CaptureJournal
from serialization import DomainCodec

_ROOT = Path(__file__).parents[4]
_SESSION = CaptureRecord(kind="session", epoch=0, received_ns=1789663921432175123)
_FRAME = CaptureRecord(
    kind="frame", epoch=0, received_ns=1789663921432175124, raw=b'{"event":"info","version":2}'
)


class TestCaptureJournal:
    """Verify the actual disk boundary independently of downstream book state."""

    @staticmethod
    def journal(root: Path) -> CaptureJournal:
        """Create one isolated bounded recording for an append/failure scenario.

        Args:
            root: New directory owned exclusively by this test.

        Returns:
            Started journal with an empty durable cursor.
        """
        request = CaptureRequest(
            config=CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"),
            recording_id="00000000-0000-4000-8000-000000000023",
            implementation_identity="a" * 64,
        )
        journal = CaptureJournal(root, request)
        journal.start()
        return journal

    def test_exact_prefix_and_same_directory_refusal(self, tmp_path: Path) -> None:
        """Keep exact message grouping, receipt nanoseconds, ordinal and request binding."""
        journal = self.journal(tmp_path / "capture")
        journal.append(_SESSION)
        journal.append(_FRAME)
        cursor = journal.codec.decode_json(
            (journal.root / "cursor.json").read_bytes(), CaptureCursor
        )
        raw = (journal.root / "journal.jsonl").read_bytes()
        assert cursor == CaptureCursor(
            journal.request.identity, len(raw), 2, hashlib.sha256(raw).hexdigest()
        )
        assert list(journal.records(completed=False))[:-1] == [_SESSION, _FRAME]
        with pytest.raises(FileExistsError):
            CaptureJournal(journal.root, journal.request).start()
        assert (journal.root / "journal.jsonl").read_bytes() == raw

    @pytest.mark.parametrize("sync_number", [1, 2, 3, 4])
    def test_sync_failure_never_exposes_unsynced_frame(
        self, tmp_path: Path, sync_number: int
    ) -> None:
        """Fail journal, pending cursor, pending directory or published directory fsync."""
        journal = self.journal(tmp_path / "capture")
        journal.append(_SESSION)
        failures: list[OSError | None] = [None] * (sync_number - 1)
        failures.append(OSError("disk full"))
        with patch("market_data.storage.journal.os.fsync", side_effect=failures):
            with pytest.raises(OSError, match="disk full"):
                journal.append(_FRAME)
        assert not (journal.root / "manifest.json").exists()
        with pytest.raises(OSError, match="not active"):
            journal.append(_FRAME)
        with pytest.raises(OSError, match="not active"):
            journal.finish(_SESSION.received_ns)
        records = list(journal.records(completed=False))
        # Rename may already expose the new cursor only after journal fsync succeeded.
        assert records[:-1] == ([_SESSION, _FRAME] if sync_number == 4 else [_SESSION])
        assert records[-1].reason == "interrupted_persistence_unknown_tail"
        assert SavedCapture.read(
            journal.root, book_factory=BookAdapters.create, completed=False
        ).invalid

    def test_failed_cursor_rename(self, tmp_path: Path) -> None:
        """Complete unacknowledged JSON lines remain excluded by the preceding cursor."""
        journal = self.journal(tmp_path / "capture")
        journal.append(_SESSION)
        with patch("market_data.storage.journal.os.replace", side_effect=OSError("rename failed")):
            with pytest.raises(OSError, match="rename failed"):
                journal.append(_FRAME)
        assert list(journal.records(completed=False))[:-1] == [_SESSION]
        assert (journal.root / "journal.jsonl").stat().st_size > journal.codec.decode_json(
            (journal.root / "cursor.json").read_bytes(), CaptureCursor
        ).offset

    @pytest.mark.parametrize("tail", [b'{"kind":', DomainCodec().encode_json(_FRAME) + b"\n"])
    def test_uncommitted_tail_is_never_replayed(self, tmp_path: Path, tail: bytes) -> None:
        """Both torn lines and complete uncommitted lines remain behind the cursor."""
        journal = self.journal(tmp_path / "capture")
        journal.append(_SESSION)
        with (journal.root / "journal.jsonl").open("ab") as output:
            output.write(tail)
        records = list(journal.records(completed=False))
        assert records[:-1] == [_SESSION]
        assert records[-1].reason == "interrupted_persistence_unknown_tail"

    @pytest.mark.parametrize("mutation", ["truncate", "bytes", "request", "offset", "count"])
    def test_corrupt_committed_prefix_fails_before_yield(
        self, tmp_path: Path, mutation: str
    ) -> None:
        """Reject damaged or wrongly bound committed input before exposing a single record."""
        journal = self.journal(tmp_path / "capture")
        journal.append(_SESSION)
        raw_path, cursor_path = journal.root / "journal.jsonl", journal.root / "cursor.json"
        raw = raw_path.read_bytes()
        cursor = journal.codec.decode_json(cursor_path.read_bytes(), CaptureCursor)
        if mutation == "truncate":
            raw_path.write_bytes(raw[:-1])
        elif mutation == "bytes":
            raw_path.write_bytes(raw.replace(b'"epoch":0', b'"epoch":1'))
        else:
            cursor = replace(
                cursor,
                **(
                    {"request_identity": "b" * 64}
                    if mutation == "request"
                    else {"offset": journal.request.config.max_bytes + 1}
                    if mutation == "offset"
                    else {"records": 2}
                ),
            )
            cursor_path.write_bytes(journal.codec.encode_json(cursor))
        with pytest.raises(ValueError, match=r"prefix|cursor"):
            next(journal.records(completed=False))

    @pytest.mark.parametrize("with_end", [False, True])
    def test_interrupted_before_session_or_after_end(self, tmp_path: Path, with_end: bool) -> None:
        """An empty cursor and an unpublished end both report an unavailable interrupted run."""
        journal = self.journal(tmp_path / "capture")
        if with_end:
            journal.append(_SESSION)
            journal.append(CaptureRecord(kind="end", epoch=0, received_ns=_SESSION.received_ns))
        replay = SavedCapture.read(journal.root, book_factory=BookAdapters.create, completed=False)
        assert not replay.ended and replay.invalid and replay.gaps

    def test_legacy_completed_and_interrupted_reading(self, tmp_path: Path) -> None:
        """Retain old capture bytes and explicit legacy-prefix inspection without a cursor."""
        journal = self.journal(tmp_path / "capture")
        journal.append(_SESSION)
        journal.append(_FRAME)
        journal.append(CaptureRecord(kind="end", epoch=0, received_ns=_FRAME.received_ns))
        journal.finish(_SESSION.received_ns)
        (journal.root / "cursor.json").unlink()
        assert SavedCapture.read(journal.root, book_factory=BookAdapters.create).messages == 1
        assert SavedCapture.read(
            journal.root, book_factory=BookAdapters.create, completed=False
        ).invalid

    def test_process_death(self, tmp_path: Path) -> None:
        """Kill a child after acknowledgement and an unsynced tail; retain exactly the cursor."""
        journal = self.journal(tmp_path / "capture")
        # The child owns its new writer; use installed imports and no parent cleanup path.
        code = """
import os, signal, sys
from pathlib import Path
from market_data.contracts import CaptureRequest, CaptureRecord
from market_data.storage import CaptureJournal
from serialization import DomainCodec
root = Path(sys.argv[1])
request = DomainCodec().decode_json(Path(sys.argv[2]).read_bytes(), CaptureRequest)
journal = CaptureJournal(root, request)
journal.start()
journal.append(CaptureRecord(kind='session', epoch=0, received_ns=1789663921432175123))
with (root / 'journal.jsonl').open('ab') as output:
    output.write(b'{"kind":"frame"')
    output.flush()
os.kill(os.getpid(), signal.SIGKILL)
"""
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                code,
                str(tmp_path / "child"),
                str(journal.root / "request.json"),
            ],
            cwd=tmp_path,
            check=False,
        )
        assert result.returncode == -9
        child = CaptureJournal(tmp_path / "child", journal.request)
        assert list(child.records(completed=False))[:-1] == [_SESSION]
        assert SavedCapture.read(
            child.root, book_factory=BookAdapters.create, completed=False
        ).invalid
        assert not (child.root / "manifest.json").exists()

    @pytest.mark.parametrize(
        "payload",
        [
            b'{"kind":"frame","epoch":true,"received_ns":1}',
            b'{"kind":"frame","epoch":0,"received_ns":1.5}',
            b'{"kind":"other","epoch":0,"received_ns":1}',
        ],
    )
    def test_invalid_record_wire(self, payload: bytes) -> None:
        """Reject wrong clock types and unknown record kinds at the cached typed boundary."""
        with pytest.raises(ValueError):
            DomainCodec().decode_json(payload, CaptureRecord)

    def test_unsafe_record_copy(self, tmp_path: Path) -> None:
        """Revalidate a deliberately corrupted frozen record before touching the journal."""
        journal = self.journal(tmp_path / "capture")
        record = replace(_FRAME)
        force_setattr(record, "received_ns", True)
        with pytest.raises(ValueError, match="capture record"):
            journal.append(record)
        assert (journal.root / "journal.jsonl").read_bytes() == b""

    @pytest.mark.parametrize(
        "payload",
        [
            b'{"request_identity":"x","offset":0,"records":0,"sha256":"x"}',
            b'{"request_identity":"'
            + b"a" * 64
            + b'","offset":true,"records":0,"sha256":"'
            + b"a" * 64
            + b'"}',
        ],
    )
    def test_invalid_cursor_wire(self, payload: bytes) -> None:
        """Reject malformed digests and boolean byte coordinates in persisted cursors."""
        with pytest.raises(ValueError):
            DomainCodec().decode_json(payload, CaptureCursor)

    def test_oversized_metadata_and_legacy_input(self, tmp_path: Path) -> None:
        """Keep cursor metadata and legacy inspection bounded without silently clipping."""
        journal = self.journal(tmp_path / "capture")
        cursor_path = journal.root / "cursor.json"
        cursor_path.write_bytes(cursor_path.read_bytes() + b" " * 1024)
        with pytest.raises(ValueError, match="metadata bound"):
            next(journal.records(completed=False))
        cursor_path.unlink()
        with (journal.root / "journal.jsonl").open("wb") as output:
            output.truncate(journal.request.config.max_bytes + 1)
        with pytest.raises(ValueError, match="storage bound"):
            next(journal.records(completed=False))

    def test_new_parent_directory_sync_failure(self, tmp_path: Path) -> None:
        """Do not acknowledge writes when a newly created ancestor is not durably named."""
        request = self.journal(tmp_path / "reference").request

        class ParentFailureJournal(CaptureJournal):
            """Fail only the newly created output directory's parent synchronization."""

            @staticmethod
            def _sync_directory(path: Path) -> None:
                """Inject a failure above the recording directory and its direct parent."""
                if path == tmp_path:
                    raise OSError("parent sync failed")
                CaptureJournal._sync_directory(path)

        journal = ParentFailureJournal(tmp_path / "new-output" / "capture", request)
        with pytest.raises(OSError, match="parent sync failed"):
            journal.start()
        with pytest.raises(OSError, match="not active"):
            journal.append(_SESSION)
        assert SavedCapture.read(
            journal.root, book_factory=BookAdapters.create, completed=False
        ).invalid
