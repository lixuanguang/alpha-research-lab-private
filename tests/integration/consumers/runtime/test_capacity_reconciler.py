"""Prove the sustained reconciler refreshes a real account and stops on a mismatch."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
from capacity_reconciler import AccountReconciler
from capacity_sustained import SustainedWorkload

# project library imports
from accounting import AccountPosting
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountObservation,
    AccountQuote,
)
from financial_units import Money

_ACCOUNT = "okx-shared"


class _JournalClient:
    """Serve inspect and reconcile from one real journal, optionally changing it between."""

    def __init__(self, journal: AccountJournal, *, commit_between: Money | None = None) -> None:
        """Bind the journal and a transfer that lands after each read, if any."""
        self.journal, self.commit_between = journal, commit_between

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Serve one bounded projection, then optionally commit a transfer it does not hold.

        A full inspection is refused: it carries every paper trace and outgrows the
        owner socket's one MiB response bound during a sustained run.
        """
        assert request.action == "inspect" and request.projection in ("accounts", "net_orders")
        facts = (
            AccountExecutionResult(accounts=self.journal.accounts(), orders=())
            if request.projection == "accounts"
            else AccountExecutionResult(
                accounts=(), orders=(), net_orders=self.journal.net_orders()
            )
        )
        if self.commit_between is not None and request.projection == "net_orders":
            at = datetime.now(UTC)
            self.journal.post(
                AccountPosting(
                    identity="between-read-and-reconcile",
                    account_id=_ACCOUNT,
                    kind="transfer",
                    event_at=at,
                    known_at=at,
                    cash=self.commit_between,
                )
            )
        return facts

    def reconcile(self, observation: AccountObservation) -> bool:
        """Reconcile through the journal itself."""
        return self.journal.reconcile(observation)


_WORKLOAD_SOCKETS = Path("/private/tmp/capacity-reconciler-test")


def _workload(opening: datetime) -> SustainedWorkload:
    """Select the sustained topology opened just before a reconciliation test."""
    return SustainedWorkload(opening_at=opening, socket_root=_WORKLOAD_SOCKETS)


def _journal(path: Path) -> AccountJournal:
    """Open one sustained owner's journal reconciled at its opening."""
    opening = datetime.now(UTC) - timedelta(seconds=5)
    workload = _workload(opening - timedelta(seconds=1))
    service = workload.service_configuration()
    account = next(item for item in service.accounts if item.account_id == _ACCOUNT)
    source = next(item for item in service.sources if item.capture.venue == "okx")
    venue = workload.venue_workload("okx")
    journal = AccountJournal(path, account.configuration)
    journal.observe(
        AccountQuote(
            price=venue.price("100", source.scenario.adverse.per),
            at=opening - timedelta(microseconds=1),
        )
    )
    assert journal.reconcile(venue.opening_observation(_ACCOUNT, opening))
    return journal


class TestCapacityReconciler:
    """Keep account state fresh only through exact, retained reconciliations."""

    def test_matched_reconciliation_advances_account_freshness(self, tmp_path: Path) -> None:
        """Each round reconciles the settled facts under a fresh identity."""
        journal = _journal(tmp_path / "account.sqlite3")
        before = journal.accounts()[0].reconciled_at
        rows: list[tuple[str, object]] = []
        reconciler = AccountReconciler(
            {_ACCOUNT: _JournalClient(journal)},
            period_seconds=0.05,
            record=lambda kind, values: rows.append((kind, values)),
        )
        reconciler.start()
        deadline = time.monotonic() + 5
        while reconciler.attempts < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        reconciler.stop()
        assert reconciler.attempts >= 2 and reconciler.failures == []
        after = journal.accounts()[0]
        assert before is not None and after.reconciled_at is not None
        assert after.reconciled_at > before and after.fault is None
        assert all(kind == "account_reconciled" for kind, _ in rows)
        assert all(isinstance(values, dict) and values["matched"] for _, values in rows)

    def test_a_commit_between_read_and_reconcile_faults_and_stops(self, tmp_path: Path) -> None:
        """A mismatch is retained as a failure, faults the account and is never retried."""
        journal = _journal(tmp_path / "account.sqlite3")
        rows: list[tuple[str, object]] = []
        reconciler = AccountReconciler(
            {
                _ACCOUNT: _JournalClient(
                    journal,
                    commit_between=_workload(datetime.now(UTC)).venue_workload("okx").money("-1"),
                )
            },
            period_seconds=0.05,
            record=lambda kind, values: rows.append((kind, values)),
        )
        reconciler.start()
        deadline = time.monotonic() + 5
        while not reconciler.failures and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
        reconciler.stop()
        assert reconciler.attempts == 1
        assert reconciler.failures == [f"reconciliation mismatch faulted {_ACCOUNT}"]
        assert journal.accounts()[0].fault == "account_break"
