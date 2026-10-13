"""Keep account history in its own tables, consistent with the committed head."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import sqlite3
from collections.abc import Callable
from compression import zstd
from contextlib import closing
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import cast

# third party library imports
import pytest
from msgspec.structs import replace
from paper_books import PaperBooks
from test_account_paper_matching import TestAccountPaperMatching as _Matching

# project library imports
from execution import (
    AccountJournal,
    AccountPaperTrace,
    AccountQuote,
    HistoryDigest,
    PaperTracePage,
    StepCommit,
)
from execution.account_state import AccountStateStore, FirmHead, FirmState, SavedDecision
from execution.records import ORDER_EVENT_KINDS
from serialization import DomainCodec, ReferenceFrames


class AccountHistoryFixture:
    """Operate, read and alter one account journal on disk."""

    @staticmethod
    def operate(path: Path) -> dict[str, object]:
        """Admit, coordinate, match and retry, then project from a fresh process view."""
        scenario = _Matching._scenario()
        journal = _Matching._ready(path, scenario)
        at = _Matching.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Matching._price("1.00"), at=at))
        direct = journal.admit(_Matching._decision("alpha", "direct", at))
        assert journal.admit(_Matching._decision("alpha", "direct", at)) == direct
        with pytest.raises(ValueError, match="different content"):
            journal.admit(_Matching._decision("alpha", "direct", at, limit="1.05"))
        batch = _Matching._coordinate_two(journal, at)
        assert _Matching._coordinate_two(journal, at) == batch
        markets = tuple(
            _Matching._market(f"book-{index}", at + timedelta(seconds=1 + index), ask_quantity="2")
            for index in range(3)
        )
        traces = tuple(PaperBooks.apply(journal, "shared", market, scenario) for market in markets)
        assert PaperBooks.apply(journal, "shared", markets[0], scenario) == traces[0]
        reopened = AccountJournal(path, _Matching._config())
        return {
            "traces": traces,
            "reopened_traces": tuple(reopened.iter_paper_traces()),
            "account_traces": tuple(reopened.iter_paper_traces("shared")),
            "checkpoints": tuple(
                reopened.checkpoint(instance) for instance in ("alpha", "beta", "absent")
            ),
            "batch": reopened.portfolio_batch("shared-batch"),
            "absent_batch": reopened.portfolio_batch("absent"),
            "market_traces": (
                reopened.paper_trace("shared", "book-0"),
                reopened.paper_trace("shared", "absent"),
            ),
        }

    @staticmethod
    def payload(path: Path) -> bytes:
        """Read the stored firm payload."""
        with closing(sqlite3.connect(path)) as connection:
            row = cast(
                tuple[bytes], connection.execute("SELECT payload FROM firm WHERE id=1").fetchone()
            )
        return row[0]

    @staticmethod
    def execute(path: Path, statement: str) -> None:
        """Apply one out-of-band change to a stored journal."""
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(statement)
            connection.commit()

    @staticmethod
    def frames(path: Path) -> tuple[ReferenceFrames, list[tuple[int, bytes]]]:
        """Read the reference trace's frames and every stored trace frame, in order."""
        with closing(sqlite3.connect(path)) as connection:
            reference = cast(
                tuple[bytes],
                connection.execute("SELECT payload FROM paper_trace_reference").fetchone(),
            )[0]
            rows = cast(
                list[tuple[int, bytes]],
                connection.execute("SELECT seq, frame FROM paper_traces ORDER BY seq").fetchall(),
            )
        frames = ReferenceFrames(reference, maximum_bytes=1 << 26, label="test trace")
        return frames, rows

    @staticmethod
    def retrace(path: Path, seq: int, old: bytes, new: bytes) -> None:
        """Replace text inside one stored trace, re-framed against the same reference."""
        frames, rows = AccountHistoryFixture.frames(path)
        payload = frames.decode(dict(rows)[seq])
        assert old in payload
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE paper_traces SET frame=? WHERE seq=?",
                (frames.encode(payload.replace(old, new)), seq),
            )
            connection.commit()

    @staticmethod
    def reframe(path: Path, seq: int, change: Callable[[ReferenceFrames, bytes], bytes]) -> None:
        """Replace one stored trace frame with ``change`` applied to it and the reference."""
        frames, rows = AccountHistoryFixture.frames(path)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE paper_traces SET frame=? WHERE seq=?",
                (change(frames, dict(rows)[seq]), seq),
            )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @staticmethod
    def count(path: Path, table: str) -> int:
        """Count one history table's rows."""
        with closing(sqlite3.connect(path)) as connection:
            row = cast(tuple[int], connection.execute(f"SELECT count(*) FROM {table}").fetchone())
        return row[0]


class TestAccountHistory:
    """Keep account journal history in rows behind a verified head."""

    def test_history_lookups_after_reopen_equal_committed_results(self, tmp_path: Path) -> None:
        """A fresh process reads the same decisions, batches, traces and checkpoints."""
        path = tmp_path / "reopen.sqlite3"
        result = AccountHistoryFixture.operate(path)
        assert result["reopened_traces"] == result["account_traces"] == result["traces"]
        assert result["checkpoints"] == (b"alpha-decision", b"beta-decision", None)
        assert result["batch"] is not None and result["absent_batch"] is None
        traces = cast(tuple[AccountPaperTrace, ...], result["traces"])
        assert result["market_traces"] == (traces[0], None)
        assert len(AccountJournal.verify(path, _Matching._config())) == 1

    def test_history_digests_name_the_committed_history_and_move_with_it(
        self, tmp_path: Path
    ) -> None:
        """A read-only snapshot's digests count each table and change with any commit.

        Graders bind a stopped journal to the history retained at its cutoff with them.
        """
        path, config = tmp_path / "digests.sqlite3", _Matching._config()
        AccountHistoryFixture.operate(path)
        journal = AccountJournal(path, config)
        with AccountJournal.read_history(path, config) as history:
            decisions, batches, traces = history.digests()
        assert (decisions.count, batches.count, traces.count) == (
            AccountHistoryFixture.count(path, "decisions"),
            AccountHistoryFixture.count(path, "portfolio_batches"),
            AccountHistoryFixture.count(path, "paper_traces"),
        )
        assert traces == journal.paper_trace_history()
        with AccountJournal.read_history(path, config) as history:
            assert history.digests() == (decisions, batches, traces)
        later = _Matching.opening_at + timedelta(seconds=10)
        journal.observe(AccountQuote(price=_Matching._price("1.00"), at=later))
        journal.admit(_Matching._decision("beta", "later", later))
        with AccountJournal.read_history(path, config) as history:
            moved = history.digests()
        assert moved[0].count == decisions.count + 1 and moved[0] != decisions
        assert (moved[1], moved[2]) == (batches, traces)

    def test_commit_writes_head_and_rows_and_open_decodes_only_head(self, tmp_path: Path) -> None:
        """History stays out of the head, and the head is its exact full encoding."""
        path, config, codec = tmp_path / "head.sqlite3", _Matching._config(), DomainCodec()
        AccountHistoryFixture.operate(path)

        assert (
            AccountHistoryFixture.count(path, "decisions"),
            AccountHistoryFixture.count(path, "portfolio_batches"),
        ) == (4, 2)
        assert AccountHistoryFixture.count(path, "paper_traces") == 3
        payload = AccountHistoryFixture.payload(path)
        head = codec.decode_json(payload, FirmHead)
        assert codec.encode_json(head) == payload
        assert b"book-0" not in payload
        assert (head.history.decisions.count, head.history.paper_traces.count) == (4, 3)
        assert {item.instance_id: item.checkpoint for item in head.history.checkpoints} == {
            "alpha": b"alpha-decision",
            "beta": b"beta-decision",
        }
        store = AccountStateStore(path, config, codec)
        state = store.read()
        assert (state.decisions, state.portfolio_batches, state.paper_traces) == ((), (), ())
        with store.snapshot() as snapshot:
            assert snapshot.latest_checkpoint("alpha") == b"alpha-decision"
            saved = snapshot.find_decision("alpha", "direct")
            assert saved is not None and saved.result.status == "committed"
            newest = next(snapshot.iter_traces("shared", newest_first=True))
            assert newest.market.identity == "book-2"

    def test_rollback_inserts_no_rows(self, tmp_path: Path) -> None:
        """A failed transaction leaves neither history rows nor a changed head."""
        path, config, codec = tmp_path / "rollback.sqlite3", _Matching._config(), DomainCodec()
        store = AccountStateStore(path, config, codec)
        before = AccountHistoryFixture.payload(path)
        at = _Matching.opening_at + timedelta(seconds=1)
        saved = SavedDecision(
            request=_Matching._decision("alpha", "staged", at),
            result=StepCommit(status="rejected", reason="staged", orders=()),
        )
        with pytest.raises(RuntimeError, match="discard"):
            with store.write() as transaction:
                transaction.append_decisions(saved)
                assert transaction.find_decision("alpha", "staged") == saved
                assert transaction.latest_checkpoint("alpha") == b"staged"
                raise RuntimeError("discard")
        assert (
            AccountHistoryFixture.count(path, "decisions"),
            AccountHistoryFixture.payload(path),
        ) == (0, before)
        with store.write() as transaction:
            prior = transaction.state
            transaction.append_decisions(saved)
            transaction.state = prior
        assert AccountHistoryFixture.count(path, "decisions") == 0
        with store.snapshot() as snapshot:
            assert snapshot.latest_checkpoint("alpha") is None

    @pytest.mark.parametrize(
        ("tamper", "reason"),
        (
            (
                "UPDATE decisions SET payload=CAST('{}' AS BLOB) WHERE seq=0",
                "missing required field",
            ),
            ("DELETE FROM paper_traces WHERE seq=2", "history differs"),
            ("UPDATE paper_traces SET market_identity='other' WHERE seq=1", "history differs"),
            ("UPDATE portfolio_batches SET seq=5 WHERE seq=0", "history differs"),
            ("DELETE FROM decisions WHERE seq=2", "history differs"),
        ),
    )
    def test_verify_rejects_history_that_differs_from_its_head(
        self, tmp_path: Path, tamper: str, reason: str
    ) -> None:
        """Rows, key columns, counts and digests must all agree with the head."""
        path, config = tmp_path / "tampered.sqlite3", _Matching._config()
        AccountHistoryFixture.operate(path)
        AccountJournal.verify(path, config)
        AccountHistoryFixture.execute(path, tamper)
        with pytest.raises(ValueError, match=reason):
            AccountJournal.verify(path, config)

    def test_verify_rejects_head_checkpoint_that_differs_from_decisions(
        self, tmp_path: Path
    ) -> None:
        """The head's restart checkpoints must equal each instance's latest decision."""
        path, config = tmp_path / "checkpoint.sqlite3", _Matching._config()
        AccountHistoryFixture.operate(path)
        payload = AccountHistoryFixture.payload(path)
        original, changed = (
            base64.b64encode(value).decode().encode()
            for value in (b"beta-decision", b"beta-decisioX")
        )
        assert payload.count(original) == 1
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE firm SET payload=? WHERE id=1", (payload.replace(original, changed),)
            )
            connection.commit()
        with pytest.raises(ValueError, match="history differs"):
            AccountJournal.verify(path, config)

    @pytest.mark.parametrize(
        "vocabulary",
        [None, tuple(kind for kind in ORDER_EVENT_KINDS if kind != "cancelled_on_request")],
        ids=["before-terminal-causes", "other-vocabulary"],
    )
    def test_journal_from_another_event_vocabulary_is_refused_unchanged(
        self, tmp_path: Path, vocabulary: tuple[str, ...] | None
    ) -> None:
        """A head that predates stated cancellation causes, or names others, is refused.

        Its ``cancelled`` facts could mean a requested cancellation, so neither the
        journal nor its verifier rereads it under the current vocabulary, and the
        refused open leaves the file's bytes as they were.
        """
        path, config, codec = tmp_path / "vocabulary.sqlite3", _Matching._config(), DomainCodec()
        AccountHistoryFixture.operate(path)
        payload = AccountHistoryFixture.payload(path)
        current = b'"event_kinds":' + codec.encode_json(ORDER_EVENT_KINDS) + b","
        assert payload.count(current) == 1
        replacement = (
            b"" if vocabulary is None else b'"event_kinds":' + codec.encode_json(vocabulary) + b","
        )
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE firm SET payload=? WHERE id=1", (payload.replace(current, replacement),)
            )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = path.read_bytes()
        with pytest.raises(ValueError, match="unsupported account journal state schema"):
            AccountJournal(path, config)
        with pytest.raises(ValueError, match="unsupported account journal state schema"):
            AccountJournal.verify(path, config)
        assert path.read_bytes() == before

    def test_whole_state_documents_and_document_readers_fail_closed(self, tmp_path: Path) -> None:
        """A whole-state document is refused, and a document reader refuses the head."""
        path, config, codec = tmp_path / "document.sqlite3", _Matching._config(), DomainCodec()
        store = AccountStateStore(path, config, codec)
        head = AccountHistoryFixture.payload(path)
        assert b'"schema_version":"account-journal"' in head
        with pytest.raises(ValueError):
            codec.decode_json(head, FirmState)

        document = codec.encode_json(store.read())
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE firm SET payload=? WHERE id=1", (document,))
            connection.commit()
        with pytest.raises(ValueError):
            AccountStateStore(path, config, codec)
        with pytest.raises(ValueError):
            AccountJournal.verify(path, config)


class TestBoundedTraceReads:
    """Read and export the growing trace history in bounded pages, checked by its chain."""

    @staticmethod
    def _chain(payloads: list[bytes]) -> str:
        """Compute the head's trace chain independently from exact trace bytes."""
        digest = b""
        for payload in payloads:
            digest = hashlib.sha256(digest + payload).digest()
        return digest.hex() if payloads else ""

    def test_pages_join_into_exactly_the_history_their_chain_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pages of two follow positions to the end; their bytes extend the head's chain."""
        path = tmp_path / "pages.sqlite3"
        result = AccountHistoryFixture.operate(path)
        traces = cast(tuple[AccountPaperTrace, ...], result["traces"])
        journal = AccountJournal(path, _Matching._config())
        codec = DomainCodec()
        history = journal.paper_trace_history()
        assert history == HistoryDigest(
            count=3, sha256=self._chain([codec.encode_json(trace) for trace in traces])
        )
        monkeypatch.setattr(PaperTracePage, "maximum", 2)
        first = journal.paper_trace_page("shared")
        assert (first.after, first.traces, first.next_after) == (-1, traces[:2], 1)
        second = journal.paper_trace_page("shared", after=1)
        assert (second.traces, second.next_after, second.history) == (traces[2:], None, history)
        assert tuple(journal.iter_paper_traces("shared")) == traces
        assert tuple(journal.iter_paper_traces(after=0)) == traces[1:]
        assert journal.paper_trace_page(after=2).traces == ()
        assert journal.latest_paper_traces("shared") == (traces[-1],)
        for after in (-2, 3):
            with pytest.raises(ValueError, match="outside the committed history"):
                journal.paper_trace_page(after=after)
        with pytest.raises(ValueError, match="unknown account"):
            journal.paper_trace_page("absent")
        with pytest.raises(ValueError, match="invalid paper trace page"):
            PaperTracePage(after=-1, traces=traces[:2], next_after=None, history=history)

    def test_pages_also_stop_at_their_byte_bound_and_continue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A page holds its first trace whatever its size, then stops before the byte bound."""
        path = tmp_path / "byte-pages.sqlite3"
        result = AccountHistoryFixture.operate(path)
        traces = cast(tuple[AccountPaperTrace, ...], result["traces"])
        journal = AccountJournal(path, _Matching._config())
        sizes = [len(DomainCodec().encode_json(trace)) for trace in traces]
        monkeypatch.setattr(PaperTracePage, "maximum_bytes", sizes[0] + sizes[1] - 1)
        first = journal.paper_trace_page("shared")
        assert (first.traces, first.next_after) == (traces[:1], 0)
        assert tuple(journal.iter_paper_traces("shared")) == traces
        monkeypatch.setattr(PaperTracePage, "maximum_bytes", 1)
        assert journal.paper_trace_page("shared", after=1).traces == traces[2:]
        assert tuple(journal.iter_paper_traces("shared")) == traces

    def test_export_is_the_codec_encoding_and_refuses_a_changed_history(
        self, tmp_path: Path
    ) -> None:
        """The streamed document equals the encoded tuple; altered history leaves no file."""
        path = tmp_path / "export.sqlite3"
        AccountHistoryFixture.operate(path)
        journal = AccountJournal(path, _Matching._config())
        destination = tmp_path / "execution-traces.json"
        assert journal.export_paper_traces(destination, "shared") == 3
        assert destination.read_bytes() == DomainCodec().encode_json(
            tuple(journal.iter_paper_traces("shared"))
        )
        with pytest.raises(ValueError, match="absent absolute destination"):
            journal.export_paper_traces(destination, "shared")
        # A well-formed frame of other bytes: only the history chain can refuse it.
        AccountHistoryFixture.retrace(path, 1, b'"matched"', b'"matcheD"')
        altered = tmp_path / "altered.json"
        with pytest.raises(ValueError, match="history differs"):
            AccountJournal(path, _Matching._config()).export_paper_traces(altered, "shared")
        assert not altered.exists() and not tuple(tmp_path.glob(".altered.json.*"))
        with pytest.raises(ValueError, match="history differs"):
            AccountJournal.verify(path, _Matching._config())

    def test_verification_refuses_bytes_whose_fill_flag_differs_from_its_column(
        self, tmp_path: Path
    ) -> None:
        """A key column must equal what the row's own bytes say, the fill flag included."""
        path = tmp_path / "flag.sqlite3"
        AccountHistoryFixture.operate(path)
        AccountJournal.verify(path, _Matching._config())
        AccountHistoryFixture.execute(path, "UPDATE paper_traces SET filled=1-filled WHERE seq=0")
        with pytest.raises(ValueError, match="history differs"):
            AccountJournal.verify(path, _Matching._config())


class TestTraceFrames:
    """Store each trace as a frame of its exact bytes against the journal's first trace."""

    def test_rows_are_frames_of_the_exact_encodings_and_the_chain_covers_those_bytes(
        self, tmp_path: Path
    ) -> None:
        """The reference is the first trace; frames decode to every trace's exact encoding."""
        path = tmp_path / "frames.sqlite3"
        AccountHistoryFixture.operate(path)
        journal = AccountJournal(path, _Matching._config())
        codec = DomainCodec()
        encoded = [codec.encode_json(trace) for trace in journal.iter_paper_traces()]
        frames, rows = AccountHistoryFixture.frames(path)
        assert frames.reference == encoded[0]
        assert [seq for seq, _ in rows] == list(range(len(encoded)))
        assert [frames.decode(frame) for _, frame in rows] == encoded
        assert all(len(frame) < len(payload) for (_, frame), payload in zip(rows, encoded))
        chain = HistoryDigest(count=0, sha256="")
        for payload in encoded:
            chain = chain.extend(payload)
        assert journal.paper_trace_history() == chain

    def test_a_damaged_frame_or_a_missing_or_other_reference_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A frame must decode against the journal's own reference to the chained bytes."""
        path = tmp_path / "damaged.sqlite3"
        AccountHistoryFixture.operate(path)
        config = _Matching._config()
        AccountJournal.verify(path, config)
        _, rows = AccountHistoryFixture.frames(path)
        frame = rows[1][1]
        damaged = frame[:-5] + bytes([frame[-5] ^ 1]) + frame[-4:]
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE paper_traces SET frame=? WHERE seq=1", (damaged,))
            connection.commit()
        with pytest.raises(ValueError, match="paper trace frame is malformed"):
            AccountJournal.verify(path, config)
        with pytest.raises(ValueError, match="paper trace frame is malformed"):
            tuple(AccountJournal(path, config).iter_paper_traces())
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE paper_traces SET frame=? WHERE seq=1", (frame,))
            connection.execute(
                "UPDATE paper_trace_reference SET payload=CAST(replace(CAST(payload AS TEXT), "
                "'shared', 'sharEd') AS BLOB)"
            )
            connection.commit()
        with pytest.raises(ValueError, match=r"paper trace frame is malformed|history differs"):
            AccountJournal.verify(path, config)
        AccountHistoryFixture.execute(path, "DELETE FROM paper_trace_reference")
        with pytest.raises(ValueError, match="paper trace reference is missing"):
            AccountJournal.verify(path, config)
        with pytest.raises(ValueError, match="paper trace reference is missing"):
            AccountJournal(path, config).paper_trace("shared", "book-0")

    def test_verification_requires_the_reference_to_be_the_first_trace(
        self, tmp_path: Path
    ) -> None:
        """A reference that is not the first trace's exact bytes fails verification."""
        path = tmp_path / "reference.sqlite3"
        AccountHistoryFixture.operate(path)
        config = _Matching._config()
        frames, rows = AccountHistoryFixture.frames(path)
        second = frames.decode(rows[1][1])
        with closing(sqlite3.connect(path)) as connection:
            # Re-frame every row against the second trace, so every frame still decodes.
            other = ReferenceFrames(second, maximum_bytes=1 << 26, label="test trace")
            for seq, frame in rows:
                connection.execute(
                    "UPDATE paper_traces SET frame=? WHERE seq=?",
                    (other.encode(frames.decode(frame)), seq),
                )
            connection.execute("UPDATE paper_trace_reference SET payload=?", (second,))
            connection.commit()
        with pytest.raises(ValueError, match="reference differs from its first trace"):
            AccountJournal.verify(path, config)

    def test_a_rolled_back_first_trace_leaves_no_reference_behind(self, tmp_path: Path) -> None:
        """The reference commits with its first trace; a later first trace writes its own."""
        scenario = _Matching._scenario()
        at = _Matching.opening_at + timedelta(seconds=1)
        source = _Matching._ready(tmp_path / "source.sqlite3", scenario)
        trace = PaperBooks.apply(source, "shared", _Matching._market("book-0", at), scenario)
        path = tmp_path / "rollback.sqlite3"
        _Matching._ready(path, scenario)
        store = AccountStateStore(path, _Matching._config(), DomainCodec())
        altered = replace(trace, reason="matched-again")
        with pytest.raises(RuntimeError, match="abandon"), store.write() as transaction:
            transaction.append_trace(altered)
            raise RuntimeError("abandon the first trace")
        assert AccountHistoryFixture.count(path, "paper_trace_reference") == 0
        assert AccountHistoryFixture.count(path, "paper_traces") == 0
        with store.write() as transaction:
            transaction.append_trace(trace)
        store.close()
        frames, rows = AccountHistoryFixture.frames(path)
        assert frames.reference == DomainCodec().encode_json(trace)
        assert [seq for seq, _ in rows] == [0]
        assert frames.decode(rows[0][1]) == frames.reference
        AccountJournal.verify(path, _Matching._config())

    @staticmethod
    def _varied(path: Path) -> tuple[AccountJournal, tuple[AccountPaperTrace, ...]]:
        """Match a partial fill, consumed, resized and repriced liquidity, then quiet books.

        Alpha's resting buy of three at 1.10 meets one displayed unit, the same unit again,
        two displayed units, a 1.05 ask, and then two identical books with nothing left
        to fill; the first book is retried exactly.
        """
        scenario = _Matching._scenario()
        journal = _Matching._ready(path, scenario)
        at = _Matching.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=_Matching._price("1.00"), at=at))
        assert journal.admit(_Matching._decision("alpha", "buy", at)).status == "committed"
        sizes = ("1", "1", "2", "3", "3", "3")
        markets = [
            _Matching._market(f"book-{index}", at + timedelta(seconds=1 + index), ask_quantity=size)
            for index, size in enumerate(sizes)
        ]
        markets[3] = replace(markets[3], ask=_Matching._price("1.05"))
        traces = tuple(PaperBooks.apply(journal, "shared", market, scenario) for market in markets)
        assert PaperBooks.apply(journal, "shared", markets[0], scenario) == traces[0]
        return journal, traces

    def test_every_frame_is_the_exact_encoding_of_the_trace_every_read_returns(
        self, tmp_path: Path
    ) -> None:
        """Frames decode to the committed traces' bytes; every read and the export agree."""
        path = tmp_path / "frames.sqlite3"
        _, traces = self._varied(path)
        assert any(trace.filled for trace in traces)
        assert any(not trace.physical_events for trace in traces)
        codec = DomainCodec()
        frames, rows = AccountHistoryFixture.frames(path)
        assert [seq for seq, _ in rows] == list(range(len(traces)))
        for (_, frame), trace in zip(rows, traces, strict=True):
            assert frames.decode(frame) == codec.encode_json(trace)
            assert len(frame) < len(codec.encode_json(trace))
        reopened = AccountJournal(path, _Matching._config())
        assert tuple(reopened.iter_paper_traces("shared")) == traces
        assert (
            tuple(reopened.paper_trace("shared", trace.market.identity) for trace in traces)
            == traces
        )
        assert reopened.latest_paper_traces("shared") == (traces[-1],)
        destination = tmp_path / "traces.json"
        assert reopened.export_paper_traces(destination, "shared") == len(traces)
        assert destination.read_bytes() == codec.encode_json(traces)
        AccountJournal.verify(path, _Matching._config())

    @staticmethod
    def _all(journal: AccountJournal) -> tuple[AccountPaperTrace, ...]:
        """Read every trace of the shared account."""
        return tuple(journal.iter_paper_traces("shared"))

    @staticmethod
    def _flipped(frames: ReferenceFrames, frame: bytes) -> bytes:
        """Flip one bit near the end of the compressed content."""
        return frame[:-5] + bytes([frame[-5] ^ 1]) + frame[-4:]

    @staticmethod
    def _truncated(frames: ReferenceFrames, frame: bytes) -> bytes:
        """Keep the first half of the frame."""
        return frame[: len(frame) // 2]

    @staticmethod
    def _empty(frames: ReferenceFrames, frame: bytes) -> bytes:
        """Store no bytes at all."""
        return b""

    @staticmethod
    def _uncompressed(frames: ReferenceFrames, frame: bytes) -> bytes:
        """Store the trace's encoded bytes without a frame."""
        return frames.decode(frame)

    @staticmethod
    def _unchecksummed(frames: ReferenceFrames, frame: bytes) -> bytes:
        """Store a valid frame of the exact original bytes that declares no checksum."""
        payload = frames.decode(frame)
        dictionary = zstd.ZstdDict(cast(bytes, frames.reference), is_raw=True)
        unchecked = zstd.compress(
            payload,
            options={zstd.CompressionParameter.checksum_flag: 0},
            zstd_dict=dictionary,
        )
        assert zstd.decompress(unchecked, zstd_dict=dictionary) == payload
        return unchecked

    @staticmethod
    def _doubled(frames: ReferenceFrames, frame: bytes) -> bytes:
        """Store two concatenated frames."""
        return frame + frame

    @pytest.mark.parametrize(
        "name",
        (
            "_flipped",
            "_truncated",
            "_empty",
            "_uncompressed",
            "_unchecksummed",
            "_doubled",
        ),
    )
    def test_a_corrupt_or_missing_frame_is_refused_by_every_read(
        self, tmp_path: Path, name: str
    ) -> None:
        """No read returns a trace from a damaged frame, and refusing it changes nothing."""
        path = tmp_path / "damaged.sqlite3"
        _, traces = self._varied(path)
        change = cast(Callable[[ReferenceFrames, bytes], bytes], getattr(self, name))
        AccountHistoryFixture.reframe(path, 2, change)
        before = path.read_bytes()
        journal = AccountJournal(path, _Matching._config())
        reads: tuple[Callable[[], object], ...] = (
            partial(self._all, journal),
            partial(journal.paper_trace, "shared", traces[2].market.identity),
            partial(journal.export_paper_traces, tmp_path / "export.json", "shared"),
            partial(AccountJournal.verify, path, _Matching._config()),
        )
        for read in reads:
            with pytest.raises(ValueError, match="paper trace frame is malformed"):
                read()
        assert not (tmp_path / "export.json").exists()
        journal.close()
        assert path.read_bytes() == before
