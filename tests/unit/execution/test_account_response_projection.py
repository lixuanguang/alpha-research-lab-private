"""Verify bounded account responses preserve exact full inspection semantics."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace
from test_account_journal import TestAccountJournal as _AccountFixture
from test_account_paper_matching import TestAccountPaperMatching as _MatchingFixture

# project library imports
from applications.execute import AccountExecutionApplication
from configuration import AccountConfiguration, OpeningAccount
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountQuote,
    InstalledPaperAccount,
    PaperOwner,
)
from risk import AccountLimit
from serialization import DomainCodec


class _ProjectedAccount(InstalledPaperAccount):
    """Exercise inherited convenience routing against the actual journal projection."""

    def __init__(self, config: AccountConfiguration, journal: AccountJournal) -> None:
        """Keep the transport boundary transparent to request selection."""
        self.config = config
        self.paper_owner = journal.paper_owner
        self.journal = journal
        self.seen_requests: list[AccountExecutionRequest] = []

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Return the same typed projection the installed application would send."""
        self.seen_requests.append(request)
        return self.journal.result_snapshot(request)


class TestAccountMarketMembership:
    """Keep the small membership response fresh, exact and account scoped."""

    def test_membership_observes_other_writer_and_scopes_same_market(self, tmp_path: Path) -> None:
        """A warm reader sees durable traces without borrowing another account's history."""
        fixture = _MatchingFixture
        initial = fixture._config()
        opening_accounts: tuple[OpeningAccount, ...] = (
            *initial.accounts,
            OpeningAccount(account_id="separate", cash=(fixture._money("1000"),)),
        )
        account_limits: tuple[AccountLimit, ...] = (
            *initial.budgets.accounts,
            AccountLimit(account_id="separate", maximum=fixture._money("1000")),
        )
        config = replace(
            initial,
            accounts=opening_accounts,
            budgets=replace(
                initial.budgets,
                firm_maximum=fixture._money("2000"),
                accounts=account_limits,
            ),
        )
        path = tmp_path / "membership.sqlite3"
        writer = AccountJournal(path, config)
        reader = AccountJournal(path, config)
        account = _ProjectedAccount(config, reader)
        scenario = fixture._scenario()
        market = fixture._market("seen-book", fixture.opening_at + timedelta(seconds=1))
        writer.bind_paper_scenario("shared", scenario)
        opening = replace(
            _AccountFixture._opening_snapshot(),
            cash=(fixture._money("1000"),),
            transfers=(fixture._money("1000"),),
        )
        assert writer.reconcile(
            _AccountFixture._observation("shared-opening", fixture.opening_at, opening)
        )
        assert writer.reconcile(
            _AccountFixture._observation(
                "separate-opening", fixture.opening_at, replace(opening, account_id="separate")
            )
        )
        assert reader.paper_market_seen("shared", market.identity) is False
        assert account.paper_market_seen("shared", market.identity) is False

        trace = writer.match_public_market("shared", market, scenario)
        assert trace.status == "committed"
        assert reader.paper_market_seen("shared", market.identity) is True
        assert account.paper_market_seen("shared", market.identity) is True
        request = account.seen_requests[-1]
        assert request == AccountExecutionRequest(
            action="inspect",
            account_id="shared",
            query_market=market.identity,
            projection="market_membership",
        )
        result = reader.result_snapshot(request)
        assert result == AccountExecutionResult(accounts=(), orders=(), market_seen=True)
        assert (
            DomainCodec().decode_json(DomainCodec().encode_json(result), AccountExecutionResult)
            == result
        )
        assert account.paper_market_seen("separate", market.identity) is False
        assert reader.paper_market_seen("shared", "seen-book-suffix") is False
        with pytest.raises(ValueError, match="unknown account"):
            account.paper_market_seen("absent", market.identity)

        writer.bind_paper_scenario("separate", scenario)
        writer.match_public_market("separate", market, scenario)
        assert account.paper_market_seen("separate", market.identity) is True
        reopened = AccountJournal(path, config)
        assert reopened.paper_market_seen("shared", market.identity) is True
        assert reopened.paper_market_seen("separate", market.identity) is True

    @pytest.mark.parametrize(
        ("payload", "message"),
        (
            (
                b'{"action":"inspect","projection":"market_membership","query_market":"book"}',
                "market membership requires account and market identities",
            ),
            (
                b'{"action":"inspect","projection":"market_membership","account_id":"shared"}',
                "market membership requires account and market identities",
            ),
            (
                b'{"action":"inspect","projection":"market_membership",'
                b'"account_id":"shared","query_market":""}',
                "market membership requires account and market identities",
            ),
            (
                b'{"action":"inspect","projection":"market_membership",'
                b'"account_id":"shared","query_market":false}',
                "Expected",
            ),
            (
                b'{"action":"inspect","account_id":"shared","query_market":"book"}',
                "market query requires the membership projection",
            ),
            (
                b'{"action":"inspect","projection":"market_membership",'
                b'"account_id":"shared","query_market":"book","query_instance":"alpha"}',
                "market membership requires only an account and market query",
            ),
            (
                b'{"action":"quote","projection":"market_membership",'
                b'"account_id":"shared","query_market":"book"}',
                "account state projection requires inspection",
            ),
        ),
    )
    def test_membership_rejects_malformed_or_ambiguous_queries(
        self, payload: bytes, message: str
    ) -> None:
        """The installed boundary requires one explicit account and exact market identity."""
        with pytest.raises(ValueError, match=message):
            DomainCodec().decode_json(payload, AccountExecutionRequest)

    def test_membership_request_rejects_another_owners_account(self) -> None:
        """An explicit owner cannot query a different configured account."""
        owner = PaperOwner(
            account_id="separate",
            deployment_sha256="a" * 64,
            authorization_id="bounded-session",
            release_identity="b" * 64,
            owner_id="current-worker",
            generation=1,
        )
        with pytest.raises(ValueError, match="market membership account differs from its owner"):
            AccountExecutionRequest(
                action="inspect",
                projection="market_membership",
                account_id="shared",
                query_market="book",
                paper_owner=owner,
            )


def test_fresh_internal_projections_match_complete_inspection(tmp_path: Path) -> None:
    """Each internal reader gets current exact data without unrelated history fields."""
    fixture = _AccountFixture
    config = fixture._config()
    at = fixture.opening_at + timedelta(seconds=1)
    journal = AccountJournal(tmp_path / "account.sqlite3", config, clock=lambda: at)
    assert journal.reconcile(
        fixture._observation("opening", fixture.opening_at, fixture._opening_snapshot())
    )
    quote = AccountQuote(price=fixture._price("100"), at=at)
    journal.observe(quote)
    committed = journal.admit(fixture._decision("pending", "alpha", at, quantity="1", limit="100"))
    assert committed.status == "committed"
    full = journal.result_snapshot(AccountExecutionRequest(action="inspect"))
    assert len(full.orders) == 1
    account = _ProjectedAccount(config, journal)

    assert account.accounts() == full.accounts
    assert account.orders() == full.orders
    assert account.net_orders() == full.net_orders
    assert account.paper_restore_quarantined() == full.paper_restore_quarantined
    assert account.paper_activations() == full.paper_activations
    assert account.paper_reductions() == full.paper_reductions
    assert account.paper_traces("shared") == full.paper_traces
    assert account.paper_report_facts("shared") == (full.paper_fills, full.paper_costs)
    assert account.portfolio_residuals("shared") == full.residuals
    assert account.checkpoint("alpha") == b"candidate-state"
    assert account.portfolio_batch("absent") is None
    assert tuple(request.projection for request in account.seen_requests) == (
        "accounts",
        "orders",
        "net_orders",
        "quarantine",
        "paper_activations",
        "reductions",
        "traces",
        "facts",
        "residuals",
        "checkpoint",
        "saved_batch",
    )
    assert all(request.action == "inspect" for request in account.seen_requests)

    selected = journal.result_snapshot(
        AccountExecutionRequest(action="inspect", projection="orders")
    )
    assert selected.orders == full.orders
    assert selected.accounts == ()
    assert selected.paper_traces == ()
    assert selected.paper_fills == ()

    account.observe(quote)
    assert account.seen_requests[-1].projection == "operation"
    assert account.seen_requests[-1].action == "quote"


def test_operation_projection_skips_state_read_and_default_inspection_stays_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operation receipt needs no second read; operator inspect remains complete."""
    fixture = _AccountFixture
    config = fixture._config()
    journal_path = tmp_path / "account.sqlite3"
    journal = AccountJournal(journal_path, config)
    journal.reconcile(
        fixture._observation("opening", fixture.opening_at, fixture._opening_snapshot())
    )
    config_path = tmp_path / "config.json"
    request_path = tmp_path / "inspect.json"
    codec = DomainCodec()
    config_path.write_bytes(codec.encode_json(config))
    request_path.write_bytes(codec.encode_json(AccountExecutionRequest(action="inspect")))
    operator_result = AccountExecutionApplication().run(
        config_path=config_path, journal_path=journal_path, request_path=request_path
    )
    expected = journal.result_snapshot(AccountExecutionRequest(action="inspect"))
    assert operator_result == expected
    assert operator_result.accounts == journal.accounts()
    assert operator_result.journal_path == str(journal_path)
    assert codec.decode_json(b'{"action":"inspect"}', AccountExecutionRequest).projection == "full"

    def forbidden_read() -> None:
        """Fail if an operation-only result asks for a second state read."""
        raise AssertionError("operation response read the journal again")

    monkeypatch.setattr(journal._store, "read", forbidden_read)
    operation = AccountExecutionRequest(
        action="quote",
        quote=AccountQuote(
            price=fixture._price("100"), at=fixture.opening_at + timedelta(seconds=1)
        ),
        projection="operation",
    )
    assert journal.result_snapshot(operation) == AccountExecutionResult(accounts=(), orders=())
    with pytest.raises(ValueError, match="inspection requires a state projection"):
        AccountExecutionRequest(action="inspect", projection="operation")
