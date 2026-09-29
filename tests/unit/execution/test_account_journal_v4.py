"""Keep v4 account journals equivalent to v3 while history lives in its own tables."""

from __future__ import annotations

# standard library imports
import base64
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Literal, cast

# third party library imports
import pytest
from test_account_journal import TestAccountJournal as _Journal
from test_account_operations import TestAccountOperations as _Operations
from test_account_paper_matching import TestAccountPaperMatching as _Matching
from test_account_reduction import TestAccountReduction as _Reduction
from test_account_response_projection import TestAccountMarketMembership as _Membership
from test_account_service import TestAccountOwnerService as _Service
from test_paper_activation import TestPaperActivation as _Activation
from test_paper_monitoring import TestPaperMonitoring as _Monitoring
from test_paper_source_scopes import TestPaperSourceScopes as _SourceScopes
from test_portfolio_accounts import TestPortfolioAccounts as _Portfolio
from test_venue_accounting import TestVenueAccounting as _VenueAccounting
from test_venue_gateway import TestVenueGateway as _VenueGateway

# project library imports
from execution import AccountJournal, AccountQuote, StepCommit, account_state
from execution.account_state import AccountStateStore, _FirmHead, _FirmState, _SavedDecision
from serialization import DomainCodec


@pytest.fixture()
def v4_journals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Create every new journal in this test with separate history tables."""
    monkeypatch.setattr(account_state, "_NEW_JOURNAL_HISTORY", "tables")


@pytest.mark.usefixtures("v4_journals")
class TestAccountJournalV4(_Journal):
    """Rerun shared admission, reconciliation and concurrency on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestAccountOperationsV4(_Operations):
    """Rerun operational control and recovery on v4."""

    @pytest.mark.skip(reason="rewrites v2/v3 single-document payload bytes")
    def test_control_clocks_inputs_and_schema_verification(self, tmp_path: Path) -> None:
        """Covered for v4 by the head, digest and fail-closed tests below."""


@pytest.mark.usefixtures("v4_journals")
class TestAccountPaperMatchingV4(_Matching):
    """Rerun public quote matching and trace idempotency on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestAccountReductionV4(_Reduction):
    """Rerun paper reductions, which read the latest trace, on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestAccountMarketMembershipV4(_Membership):
    """Rerun market membership and response projection on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestAccountOwnerServiceV4(_Service):
    """Rerun the owner service on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestPaperActivationV4(_Activation):
    """Rerun managed activation; v4 records it without promoting the schema."""

    activated_schema = "account-journal-v4"


@pytest.mark.usefixtures("v4_journals")
class TestPaperMonitoringV4(_Monitoring):
    """Rerun paper monitoring on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestPaperSourceScopesV4(_SourceScopes):
    """Rerun paper source scopes on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestPortfolioAccountsV4(_Portfolio):
    """Rerun portfolio batches, retries and checkpoints on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestVenueAccountingV4(_VenueAccounting):
    """Rerun venue accounting on v4."""


@pytest.mark.usefixtures("v4_journals")
class TestVenueGatewayV4(_VenueGateway):
    """Rerun the venue gateway's account binding on v4."""


def _create(path: Path, history: Literal["document", "tables"]) -> None:
    """Create an empty journal in an explicit format."""
    AccountStateStore(path, _Matching._config(), DomainCodec(), history=history)


def _operate(path: Path) -> tuple[object, ...]:
    """Admit, coordinate, match and retry, then project from a fresh process view."""
    scenario = _Matching._scenario()
    journal = _Matching._ready(path, scenario)
    at = _Matching.opening_at + timedelta(seconds=1)
    journal.observe(AccountQuote(price=_Matching._price("1.00"), at=at))
    direct = journal.admit(_Matching._decision("alpha", "direct", at))
    repeated = journal.admit(_Matching._decision("alpha", "direct", at))
    with pytest.raises(ValueError, match="different content"):
        journal.admit(_Matching._decision("alpha", "direct", at, limit="1.05"))
    batch = _Matching._coordinate_two(journal, at)
    retried = _Matching._coordinate_two(journal, at)
    markets = tuple(
        _Matching._market(f"book-{index}", at + timedelta(seconds=1 + index), ask_quantity="2")
        for index in range(3)
    )
    traces = tuple(journal.match_public_market("shared", market, scenario) for market in markets)
    repeated_trace = journal.match_public_market("shared", markets[0], scenario)
    reopened = AccountJournal(path, _Matching._config())
    return (
        direct,
        repeated,
        batch,
        retried,
        traces,
        repeated_trace,
        reopened.accounts(),
        reopened.orders(),
        reopened.net_orders(),
        reopened.paper_traces(),
        reopened.paper_traces("shared"),
        reopened.paper_report_facts("shared"),
        reopened.checkpoint("alpha"),
        reopened.checkpoint("beta"),
        reopened.checkpoint("absent"),
        reopened.portfolio_batch("shared-batch"),
        reopened.portfolio_batch("absent"),
        reopened.paper_market_seen("shared", "book-0"),
        reopened.paper_market_seen("shared", "absent"),
    )


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


def test_v4_matches_v3_projections_and_materialized_document(tmp_path: Path) -> None:
    """The same operations give equal projections and v3's exact document bytes."""
    config, codec = _Matching._config(), DomainCodec()
    document, tables = tmp_path / "v3.sqlite3", tmp_path / "v4.sqlite3"
    _create(document, "document")
    _create(tables, "tables")

    assert _operate(document) == _operate(tables)

    assert AccountStateStore.verify(document, config, codec) == AccountStateStore.verify(
        tables, config, codec
    )
    v3 = AccountStateStore.materialize(document, config, codec)
    assert v3 == _payload(document)
    v4 = AccountStateStore.materialize(tables, config, codec)
    assert v4.count(b'"schema_version":"account-journal-v4"') == 1
    assert (
        v4.replace(
            b'"schema_version":"account-journal-v4"', b'"schema_version":"account-journal-v2"'
        )
        == v3
    )


def test_v4_commit_writes_head_and_rows_and_open_decodes_only_head(tmp_path: Path) -> None:
    """History stays out of the head, and the head is its exact full encoding."""
    path, config, codec = tmp_path / "head.sqlite3", _Matching._config(), DomainCodec()
    _create(path, "tables")
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
    assert state.schema_version == "account-journal-v4"
    with store.snapshot() as snapshot:
        assert snapshot.latest_checkpoint("alpha") == b"alpha-decision"
        saved = snapshot.find_decision("alpha", "direct")
        assert saved is not None and saved.result.status == "committed"
        newest = next(snapshot.iter_traces("shared", newest_first=True))
        assert newest.market.identity == "book-2"


def test_v4_rollback_inserts_no_rows(tmp_path: Path) -> None:
    """A failed transaction leaves neither history rows nor a changed head."""
    path, config, codec = tmp_path / "rollback.sqlite3", _Matching._config(), DomainCodec()
    _create(path, "tables")
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
    _create(path, "tables")
    _operate(path)
    AccountJournal.verify(path, config)
    _execute(path, tamper)
    with pytest.raises(ValueError, match=reason):
        AccountJournal.verify(path, config)


def test_verify_rejects_head_checkpoint_that_differs_from_decisions(tmp_path: Path) -> None:
    """The head's restart checkpoints must equal each instance's latest decision."""
    path, config = tmp_path / "checkpoint.sqlite3", _Matching._config()
    _create(path, "tables")
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


def test_document_readers_fail_closed_on_v4_and_v4_rejects_documents(tmp_path: Path) -> None:
    """v2/v3 decoding refuses a v4 head, and neither format is read as the other."""
    config, codec = _Matching._config(), DomainCodec()
    tables = tmp_path / "v4.sqlite3"
    _create(tables, "tables")
    head = _payload(tables)
    assert b'"schema_version":"account-journal-v4"' in head
    with pytest.raises(ValueError):
        codec.decode_json(head, _FirmState)

    document = tmp_path / "v3.sqlite3"
    _create(document, "document")
    claimed = _payload(document).replace(b"account-journal-v2", b"account-journal-v4")
    with closing(sqlite3.connect(document)) as connection:
        connection.execute("UPDATE firm SET payload=? WHERE id=1", (claimed,))
        connection.commit()
    with pytest.raises(ValueError):
        AccountStateStore(document, config, codec)
    with pytest.raises(ValueError):
        AccountJournal.verify(document, config)
