"""Protect whole-message book stepping, saved-state recovery and capture divergence evidence."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace
from test_book_datasets import TestBookDatasets as _Inputs

# project library imports
from alpha_research.data.book_datasets import BookCapture, BookHistory, BookInput, BookObservation
from alpha_research.data.book_replay import BookReplay
from alpha_research.data.live.journal import CaptureJournal
from alpha_research.data.raw_store import RawStore
from alpha_research.data.replay import ReplayCursor, ReplayPhase
from alpha_research.pipelines.dataset import publish_book_dataset
from alpha_research.serialization import DomainCodec

_CODEC = DomainCodec()
_END = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=1)
_LIMIT = 1_048_576


class _View:
    """Observe complete source messages and the phase sequence without applying economics."""

    def __init__(self) -> None:
        """Start independent whole-message and phase traces."""
        self.rows: list[BookObservation] = []
        self.phases: list[tuple[ReplayPhase, datetime]] = []

    def consume(self, phase: ReplayPhase, instant: datetime, row: BookObservation | None) -> None:
        """Retain source messages only when the shared clock makes them available."""
        self.phases.append((phase, instant))
        if row is not None:
            assert row.received_ns is not None
            delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
            assert (delta.seconds * 1_000_000 + delta.microseconds) * 1000 >= row.received_ns
            self.rows.append(row)


class TestBookReplay:
    """Use real journal/publication boundaries and independent nanosecond expectations."""

    @staticmethod
    def _engine(payload: bytes, size: int = 1, cursor: ReplayCursor | None = None) -> BookReplay:
        """Bind fixed consumer policy and the same terminal across batch sizes."""
        return BookReplay(
            payload,
            terminal=_END,
            config_identity="a" * 64,
            max_bytes=_LIMIT,
            batch_size=size,
            cursor=cursor,
        )

    def test_atomic_nanoseconds_equal_time_phases_and_restart(self, tmp_path: Path) -> None:
        """All seven nanosecond boundaries precede phases at the first safe microsecond."""
        root = _Inputs._capture(tmp_path / "capture", gap=True)
        payload = (
            BookInput.read(root, max_records=32)
            .admit(RawStore(root), max_bytes=_LIMIT)
            .require_canonical()
        )
        engine, view = self._engine(payload), _View()
        assert engine.cursor is None
        batches = tuple(engine.batches())
        assert len(batches) == 7 and all(len(batch) == 1 for batch in batches)
        checkpoint = engine.step(_END, view.consume)
        assert checkpoint is not None and checkpoint.clock.microsecond == 1
        assert [phase for phase, _ in view.phases] == ["source"] * 7 + [
            "expiry",
            "fill",
            "decision",
            "mark",
        ]
        assert view.rows[2].bids[0][1].size.as_tuple().exponent == -18
        assert view.rows[4].bids == () and view.rows[5].status == "recovering"
        with pytest.raises(ValueError, match="incomplete"):
            self._engine(
                payload,
                cursor=replace(checkpoint, position=(checkpoint.clock, 1, checkpoint.clock, 0, 0)),
            )
        restored = self._engine(
            payload, 8, _CODEC.decode_json(_CODEC.encode_json(checkpoint), ReplayCursor)
        )
        tail = _View()
        while restored.step(_END, tail.consume):
            pass
        assert tail.rows == []
        while engine.step(_END, view.consume):
            pass
        assert restored.cursor == engine.cursor
        full, other = self._engine(payload, 8), _View()
        while full.step(_END, other.consume):
            pass
        assert other.rows == view.rows and other.phases == view.phases

    def test_snapshot_identity_bounds_and_unknown_archive_clocks(self, tmp_path: Path) -> None:
        """Verify raw bytes on reopening; archive source times cannot acquire availability."""
        source = _Inputs._archive(tmp_path / "archive")
        raw, snapshots = tmp_path / "raw", tmp_path / "snapshots"
        raw.mkdir()
        snapshots.mkdir()
        identity = publish_book_dataset(
            (source,), RawStore(raw), snapshots, max_records=32, max_bytes=_LIMIT
        )
        selected = BookInput.read(source, max_records=32)
        engine = BookReplay.read(
            snapshots,
            RawStore(raw),
            identity=identity,
            request_identity=selected.request.identity,
            terminal=_END,
            config_identity="a" * 64,
            max_bytes=_LIMIT,
            batch_size=1,
        )
        view = _View()
        assert sum(map(len, engine.batches())) == 2
        assert engine.evidence.archive is not None
        while engine.step(_END, view.consume):
            pass
        assert view.rows == [] and len(view.phases) == 4
        assert engine.cursor is not None and engine.cursor.position is None
        payload = selected.admit(RawStore(raw), max_bytes=_LIMIT).require_canonical()
        history = _CODEC.decode_json(payload, BookHistory)
        with pytest.raises(ValueError, match="cannot invent"):
            replace(history, observations=(replace(history.observations[0], received_ns=1),))
        for size in (0, True):
            with pytest.raises(ValueError, match="batch_size"):
                self._engine(payload, size)
        with pytest.raises(ValueError, match="max_bytes"):
            BookReplay(payload, terminal=_END, config_identity="a" * 64, max_bytes=1, batch_size=1)
        with pytest.raises(ValueError, match="incompatible"):
            self._engine(payload, cursor=engine.cursor)
        (raw / selected.raw.sha256).chmod(0o644)
        (raw / selected.raw.sha256).write_bytes(b"corrupt")
        with pytest.raises(ValueError):
            BookReplay.read(
                snapshots,
                RawStore(raw),
                identity=identity,
                request_identity=selected.request.identity,
                terminal=_END,
                config_identity="a" * 64,
                max_bytes=_LIMIT,
                batch_size=1,
            )

    def test_capture_parity_retains_first_different_message(self, tmp_path: Path) -> None:
        """A changed intermediate state is located even when later absolute updates converge."""
        root = _Inputs._capture(tmp_path / "capture")
        selected = BookInput.read(root, max_records=32)
        assert selected.capture is not None
        captured = BookCapture(selected.capture.config, 32)
        for index, record in enumerate(CaptureJournal(root, selected.capture).records()):
            changed = (
                replace(record, raw=record.raw.replace(b"0.300000000000000001", b"0.4"))
                if index == 2
                else record
            )
            captured.apply(changed)
        with pytest.raises(ValueError, match="raw position 2"):
            captured.verify(root)
        assert (root / "book-prefix.json").exists()
        assert b'"0.4"' in (root / "first-divergence.json").read_bytes()
        assert b'"0.300000000000000001"' in (root / "first-divergence.json").read_bytes()

    def test_cursor_failure_and_isolation(self, tmp_path: Path) -> None:
        """Copied evidence cannot change stepping; callbacks cannot checkpoint partial work."""
        root = _Inputs._capture(tmp_path / "capture")
        payload = (
            BookInput.read(root, max_records=32)
            .admit(RawStore(root), max_bytes=_LIMIT)
            .require_canonical()
        )
        engine = self._engine(payload)
        row = next(engine.batches())[0]
        force_setattr(row, "received_ns", 999)
        view = _View()
        engine.step(_END, view.consume)
        assert view.rows[0].received_ns == 1
        failed = self._engine(payload)
        with pytest.raises(RuntimeError, match="consumer failure"):
            failed.step(_END, self._fail)
        with pytest.raises(RuntimeError, match="incomplete"):
            _ = failed.cursor

    @staticmethod
    def _fail(phase: ReplayPhase, instant: datetime, row: BookObservation | None) -> None:
        """Represent an interrupted downstream consumer."""
        raise RuntimeError("consumer failure")
