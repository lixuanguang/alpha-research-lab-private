"""Protect streamed book isolation, causal cutoffs and restart equivalence."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import force_setattr, replace
from test_book_datasets import TestBookDatasets as _Inputs
from test_book_replay import _View

# project library imports
from market_data.adapters.sources import SourceAdapters
from market_data.datasets import BookInput, BookSnapshot, DatasetPublication
from market_data.query import BookMarketRow, BookQuery, BookQueryReader
from market_data.replay import BookReplay
from market_data.storage import RawStore

_LIMIT = 1_048_576
_END = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=1)


class TestStreamedBookQueries:
    """Compare native streaming with legacy reference and independent exact book values."""

    @staticmethod
    def _snapshot(tmp_path: Path) -> tuple[BookSnapshot, BookInput, bytes]:
        """Publish one original capture with a gap and retain independently admitted v1 bytes."""
        capture = _Inputs._capture(tmp_path / "capture", gap=True)
        raw, snapshots = RawStore(tmp_path / "raw"), tmp_path / "snapshots"
        (tmp_path / "raw").mkdir()
        snapshots.mkdir()
        readers = SourceAdapters()
        identity = DatasetPublication(readers, "a" * 64).publish_books(
            (capture,), raw, snapshots, max_records=32, max_bytes=_LIMIT
        )
        selected = BookInput.read(capture, max_records=32)
        legacy = selected.admit(raw, readers=readers, max_bytes=_LIMIT).require_canonical()
        session = BookSnapshot.read(
            snapshots, raw, readers=readers, identity=identity, max_bytes=_LIMIT
        )
        return session, selected, legacy

    def test_stream_reference_exact_states_and_cursor_restart(self, tmp_path: Path) -> None:
        """Absolute updates, deletion, gaps and nanoseconds match hand values and v1 replay."""
        session, selected, legacy = self._snapshot(tmp_path)
        streamed = BookReplay.from_snapshot(
            session,
            request_identity=selected.request.identity,
            terminal=_END,
            config_identity="b" * 64,
            batch_size=2,
        )
        reference = BookReplay(
            legacy, terminal=_END, config_identity="b" * 64, max_bytes=_LIMIT, batch_size=3
        )
        assert tuple(row for batch in streamed.batches() for row in batch) == tuple(
            row for batch in reference.batches() for row in batch
        )
        rows = tuple(row for batch in streamed.batches() for row in batch)
        assert rows[2].bids[0][1].size == Decimal("0.300000000000000001")
        assert rows[3].bids[0][1].size == Decimal("0.2")
        assert rows[4].bids == ()
        assert rows[5].status == "recovering" and rows[5].outcome == "gap"
        view, expected = _View(), _View()
        checkpoint = streamed.step(_END, view.consume)
        reference.step(_END, expected.consume)
        assert checkpoint is not None and checkpoint.clock.microsecond == 1
        assert view.rows == expected.rows and view.phases == expected.phases
        resumed = BookReplay.from_snapshot(
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
            BookReplay.from_snapshot(
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
