"""Prove the sustained reconciler refreshes a real account and stops on a mismatch."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

# third party library imports
import msgspec
from capacity_reconciler import AccountReconciler
from capacity_sustained import SustainedWorkload
from capacity_trial import CapacityTrial

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
            knowledge=lambda _: datetime.now(UTC),
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
            knowledge=lambda _: datetime.now(UTC),
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

    def test_observations_carry_the_accepted_market_clock_not_wall_time(
        self, tmp_path: Path
    ) -> None:
        """The account's knowledge never passes its last accepted market; none yet skips."""
        journal = _journal(tmp_path / "account.sqlite3")
        accepted = datetime.now(UTC) - timedelta(seconds=2)
        clock: dict[str, datetime | None] = {_ACCOUNT: None}
        rows: list[tuple[str, object]] = []
        reconciler = AccountReconciler(
            {_ACCOUNT: _JournalClient(journal)},
            period_seconds=60,
            record=lambda kind, values: rows.append((kind, values)),
            knowledge=clock.get,
        )
        assert reconciler.reconcile(_ACCOUNT) and reconciler.attempts == 0
        assert rows == [("account_reconcile_skipped", {"account": _ACCOUNT})]
        clock[_ACCOUNT] = accepted
        assert reconciler.reconcile(_ACCOUNT) and reconciler.attempts == 1
        assert journal.accounts()[0].reconciled_at == accepted


def test_trial_reads_each_accounts_last_applied_market_from_status(tmp_path: Path) -> None:
    """The reconciliation clock is the supervisor's last applied market for the account."""
    trial = object.__new__(CapacityTrial)
    trial.config = _workload(datetime.now(UTC)).service_configuration()
    trial.service_root = tmp_path
    at = datetime(2026, 10, 3, 12, tzinfo=UTC)
    status: dict[str, object] = {
        "sources": {
            source.name: {
                "markets": [{"identity": "m", "at": at.isoformat()}]
                if source.name == "okx-btc-book"
                else [None]
            }
            for source in trial.config.sources
        }
    }
    (tmp_path / "status.json").write_bytes(msgspec.json.encode(status))
    assert trial._accepted_market_at("okx-shared") == at
    assert trial._accepted_market_at("okx-isolated") is None
