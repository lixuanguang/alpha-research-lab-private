"""Verify bounded account responses preserve exact full inspection semantics."""

from __future__ import annotations

# standard library imports
from datetime import timedelta
from pathlib import Path

# third party library imports
import pytest
from test_account_journal import TestAccountJournal as _AccountFixture

# project library imports
from applications.execute import AccountExecutionApplication
from configuration import AccountConfiguration
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountQuote,
    InstalledPaperAccount,
)
from serialization import DomainCodec


class _ProjectedAccount(InstalledPaperAccount):
    """Exercise inherited convenience routing against the actual journal projection."""

    def __init__(self, config: AccountConfiguration, journal: AccountJournal) -> None:
        """Keep the transport boundary transparent to request selection."""
        self.config = config
        self.paper_owner = None
        self.journal = journal
        self.seen_requests: list[AccountExecutionRequest] = []

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Return the same typed projection the installed application would send."""
        self.seen_requests.append(request)
        return self.journal.result_snapshot(request)


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
