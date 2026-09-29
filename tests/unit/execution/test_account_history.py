"""Keep account history in its own tables, consistent with the committed head."""

from __future__ import annotations

# standard library imports
import base64
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import cast

# third party library imports
import pytest
from test_account_paper_matching import TestAccountPaperMatching as _Matching

# project library imports
from execution import AccountJournal, AccountQuote, StepCommit
from execution.account_state import AccountStateStore, _FirmHead, _FirmState, _SavedDecision
from serialization import DomainCodec


def _operate(path: Path) -> dict[str, object]:
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
    traces = tuple(journal.match_public_market("shared", market, scenario) for market in markets)
    assert journal.match_public_market("shared", markets[0], scenario) == traces[0]
    reopened = AccountJournal(path, _Matching._config())
    return {
        "traces": traces,
        "reopened_traces": reopened.paper_traces(),
        "account_traces": reopened.paper_traces("shared"),
        "checkpoints": tuple(
            reopened.checkpoint(instance) for instance in ("alpha", "beta", "absent")
        ),
        "batch": reopened.portfolio_batch("shared-batch"),
        "absent_batch": reopened.portfolio_batch("absent"),
        "membership": (
            reopened.paper_market_seen("shared", "book-0"),
            reopened.paper_market_seen("shared", "absent"),
        ),
    }


def _payload(path: Path) -> bytes:
    """Read the stored firm payload."""
    with closing(sqlite3.connect(path)) as connection:
        row = cast(
            tuple[bytes], connection.execute("SELECT payload FROM firm WHERE id=1").fetchone()
        )
    return row[0]


def _execute(path: Path, statement: str) -> None:
    """Apply one out-of-band change to a stored journal."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.commit()


def _count(path: Path, table: str) -> int:
    """Count one history table's rows."""
    with closing(sqlite3.connect(path)) as connection:
        row = cast(tuple[int], connection.execute(f"SELECT count(*) FROM {table}").fetchone())
    return row[0]


def test_history_lookups_after_reopen_equal_committed_results(tmp_path: Path) -> None:
    """A fresh process reads the same decisions, batches, traces and checkpoints."""
    path = tmp_path / "reopen.sqlite3"
    result = _operate(path)
    assert result["reopened_traces"] == result["account_traces"] == result["traces"]
    assert result["checkpoints"] == (b"alpha-decision", b"beta-decision", None)
    assert result["batch"] is not None and result["absent_batch"] is None
    assert result["membership"] == (True, False)
    assert len(AccountJournal.verify(path, _Matching._config())) == 1


def test_commit_writes_head_and_rows_and_open_decodes_only_head(tmp_path: Path) -> None:
    """History stays out of the head, and the head is its exact full encoding."""
    path, config, codec = tmp_path / "head.sqlite3", _Matching._config(), DomainCodec()
    _operate(path)

    assert (_count(path, "decisions"), _count(path, "portfolio_batches")) == (3, 1)
    assert _count(path, "paper_traces") == 3
    payload = _payload(path)
    head = codec.decode_json(payload, _FirmHead)
    assert codec.encode_json(head) == payload
    assert b"book-0" not in payload
    assert (head.history.decisions.count, head.history.paper_traces.count) == (3, 3)
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


def test_rollback_inserts_no_rows(tmp_path: Path) -> None:
    """A failed transaction leaves neither history rows nor a changed head."""
    path, config, codec = tmp_path / "rollback.sqlite3", _Matching._config(), DomainCodec()
    store = AccountStateStore(path, config, codec)
    before = _payload(path)
    at = _Matching.opening_at + timedelta(seconds=1)
    saved = _SavedDecision(
        request=_Matching._decision("alpha", "staged", at),
        result=StepCommit(status="rejected", reason="staged", orders=()),
    )
    with pytest.raises(RuntimeError, match="discard"):
        with store.write() as transaction:
            transaction.append_decisions(saved)
            assert transaction.find_decision("alpha", "staged") == saved
            assert transaction.latest_checkpoint("alpha") == b"staged"
            raise RuntimeError("discard")
    assert (_count(path, "decisions"), _payload(path)) == (0, before)
    with store.write() as transaction:
        prior = transaction.state
        transaction.append_decisions(saved)
        transaction.state = prior
    assert _count(path, "decisions") == 0
    with store.snapshot() as snapshot:
        assert snapshot.latest_checkpoint("alpha") is None


@pytest.mark.parametrize(
    ("tamper", "reason"),
    (
        ("UPDATE decisions SET payload=CAST('{}' AS BLOB) WHERE seq=0", "missing required field"),
        ("DELETE FROM paper_traces WHERE seq=2", "history differs"),
        ("UPDATE paper_traces SET market_identity='other' WHERE seq=1", "history differs"),
        ("UPDATE portfolio_batches SET seq=5", "history differs"),
        ("DELETE FROM decisions WHERE seq=2", "history differs"),
    ),
)
def test_verify_rejects_history_that_differs_from_its_head(
    tmp_path: Path, tamper: str, reason: str
) -> None:
    """Rows, key columns, counts and digests must all agree with the head."""
    path, config = tmp_path / "tampered.sqlite3", _Matching._config()
    _operate(path)
    AccountJournal.verify(path, config)
    _execute(path, tamper)
    with pytest.raises(ValueError, match=reason):
        AccountJournal.verify(path, config)


def test_verify_rejects_head_checkpoint_that_differs_from_decisions(tmp_path: Path) -> None:
    """The head's restart checkpoints must equal each instance's latest decision."""
    path, config = tmp_path / "checkpoint.sqlite3", _Matching._config()
    _operate(path)
    payload = _payload(path)
    original, changed = (
        base64.b64encode(value).decode().encode() for value in (b"beta-decision", b"beta-decisioX")
    )
    assert payload.count(original) == 1
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE firm SET payload=? WHERE id=1", (payload.replace(original, changed),)
        )
        connection.commit()
    with pytest.raises(ValueError, match="history differs"):
        AccountJournal.verify(path, config)


def test_whole_state_documents_and_document_readers_fail_closed(tmp_path: Path) -> None:
    """A whole-state document is refused, and a document reader refuses the head."""
    path, config, codec = tmp_path / "document.sqlite3", _Matching._config(), DomainCodec()
    store = AccountStateStore(path, config, codec)
    head = _payload(path)
    assert b'"schema_version":"account-journal-v4"' in head
    with pytest.raises(ValueError):
        codec.decode_json(head, _FirmState)

    document = codec.encode_json(store.read())
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE firm SET payload=? WHERE id=1", (document,))
        connection.commit()
    with pytest.raises(ValueError):
        AccountStateStore(path, config, codec)
    with pytest.raises(ValueError):
        AccountJournal.verify(path, config)
