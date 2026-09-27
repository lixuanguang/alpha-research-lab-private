"""Keep native replay cursor order when receipt ties cross capture epochs."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
from test_book_datasets import TestBookDatasets as _Inputs

# project library imports
from configuration import CaptureConfig
from market_data.adapters.sources import SourceAdapters
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from market_data.datasets import BookInput, DatasetPublication
from market_data.replay import BookReplay, ReplayPhase
from market_data.storage import CaptureJournal, RawStore

_ROOT = Path(__file__).parents[3]
_END = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=1)
_LIMIT = 1_048_576
_ACK = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'


class _Trace:
    """Collect whole-message callbacks and shared-clock phases for comparison."""

    def __init__(self) -> None:
        """Start an independent replay trace."""
        self.events: list[tuple[ReplayPhase, datetime, int | None]] = []

    def consume(self, phase: ReplayPhase, instant: datetime, row: BookObservation | None) -> None:
        """Record the source position or one subsequent phase at its actual instant."""
        self.events.append((phase, instant, None if row is None else row.position))

    def complete(self, replay: BookReplay) -> list[tuple[ReplayPhase, datetime, int | None]]:
        """Step through terminal and return this trace for exact comparison."""
        while replay.step(_END, self.consume) is not None:
            pass
        return self.events


class TestBookReplayTies:
    """Use a saved journal with one permitted stale prior-epoch snapshot."""

    @staticmethod
    def _capture(root: Path) -> Path:
        """Save a prior-epoch response after a new session at the same receipt."""
        request = CaptureRequest(
            config=CaptureConfig.read(_ROOT / "configs/live/okx-btc-usdt.json"),
            recording_id="00000000-0000-0000-0000-000000000073",
            implementation_identity="a" * 64,
        )
        journal = CaptureJournal(root, request)
        journal.start()
        for record in (
            CaptureRecord(kind="session", epoch=0, received_ns=1),
            CaptureRecord(kind="frame", epoch=0, received_ns=2, raw=_ACK),
            CaptureRecord(
                kind="frame",
                epoch=0,
                received_ns=3,
                raw=_Inputs._frame("snapshot", -1, 1, '[["100","1","0","1"]]'),
            ),
            CaptureRecord(kind="session_end", epoch=0, received_ns=4, reason="reconnect"),
            CaptureRecord(kind="session", epoch=1, received_ns=1001),
            CaptureRecord(kind="snapshot", epoch=0, received_ns=1001, raw=b"{}"),
            CaptureRecord(kind="frame", epoch=1, received_ns=1002, raw=_ACK),
            CaptureRecord(
                kind="frame",
                epoch=1,
                received_ns=1003,
                raw=_Inputs._frame("snapshot", -1, 2, '[["101","2","0","1"]]'),
            ),
            CaptureRecord(kind="end", epoch=1, received_ns=2001, reason="message_limit"),
        ):
            journal.append(record)
        journal.finish(2001)
        return root

    def test_native_equal_receipt_epoch_sort_matches_reference_and_restart(
        self, tmp_path: Path
    ) -> None:
        """A disk-spilled v2 tie has the v1 order, phases and restart continuation."""
        capture = self._capture(tmp_path / "capture")
        selected = BookInput.read(capture, max_records=16)
        raw_root, snapshot_root = tmp_path / "raw", tmp_path / "snapshots"
        raw_root.mkdir()
        snapshot_root.mkdir()
        raw, readers = RawStore(raw_root), SourceAdapters()
        identity = DatasetPublication(readers, "a" * 64).publish_books(
            (capture,), raw, snapshot_root, max_records=16, max_bytes=_LIMIT
        )
        reference = BookReplay(
            selected.admit(raw, readers=readers, max_bytes=_LIMIT).require_canonical(),
            terminal=_END,
            config_identity="b" * 64,
            max_bytes=_LIMIT,
            batch_size=2,
        )
        streamed = BookReplay.read(
            snapshot_root,
            raw,
            readers=readers,
            identity=identity,
            request_identity=selected.request.identity,
            terminal=_END,
            config_identity="b" * 64,
            max_bytes=_LIMIT,
            batch_size=3,
        )
        observed = _Trace().complete(streamed)
        assert observed == _Trace().complete(reference)
        assert [position for phase, _, position in observed if phase == "source"] == [
            0,
            1,
            2,
            3,
            5,
            4,
            6,
            7,
            8,
        ]
        assert [phase for phase, instant, _ in observed if instant.microsecond == 2] == [
            "source",
            "source",
            "source",
            "source",
            "expiry",
            "fill",
            "decision",
            "mark",
        ]
        partial = BookReplay.read(
            snapshot_root,
            raw,
            readers=readers,
            identity=identity,
            request_identity=selected.request.identity,
            terminal=_END,
            config_identity="b" * 64,
            max_bytes=_LIMIT,
            batch_size=1,
        )
        first = _Trace()
        checkpoint = partial.step(_END, first.consume)
        assert checkpoint is not None and checkpoint.clock.microsecond == 1
        resumed = BookReplay.read(
            snapshot_root,
            raw,
            readers=readers,
            identity=identity,
            request_identity=selected.request.identity,
            terminal=_END,
            config_identity="b" * 64,
            max_bytes=_LIMIT,
            batch_size=5,
            cursor=checkpoint,
        )
        assert first.events + _Trace().complete(resumed) == observed
        assert resumed.cursor == streamed.cursor
        partial.close()
