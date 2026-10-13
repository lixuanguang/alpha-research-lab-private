"""Prove the sustained reconciler refreshes a real account and stops on a mismatch."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

# third party library imports
import msgspec
from capacity_reconciler import AccountReconciler
from capacity_sustained import SustainedWorkload
from capacity_trial import CapacityTrial
from test_capacity_sustained_results import D2Account

# project library imports
from accounting import AccountPosting
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    PortfolioBatch,
)
from financial_units import Money

_ACCOUNT = "okx-shared"


class TestCapacityReconcilerStatus:
    """Read each account's last applied market from service status."""

    def test_trial_reads_each_accounts_last_applied_market_from_status(
        self, tmp_path: Path
    ) -> None:
        """The reconciliation clock is the supervisor's last applied market for the account."""
        trial = object.__new__(CapacityTrial)
        trial.config = ReconcilerFixture.workload(datetime.now(UTC)).service_configuration()
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


class ReconcilerFixture:
    """Build reconciler journals and workloads."""

    @staticmethod
    def workload(opening: datetime) -> SustainedWorkload:
        """Select the sustained topology opened just before a reconciliation test."""
        return SustainedWorkload(opening_at=opening, socket_root=_WORKLOAD_SOCKETS)

    @staticmethod
    def journal(path: Path) -> AccountJournal:
        """Open one sustained owner's journal reconciled at its opening."""
        opening = datetime.now(UTC) - timedelta(seconds=5)
        workload = ReconcilerFixture.workload(opening - timedelta(seconds=1))
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


class _JournalClient:
    """Serve inspect and reconcile from one real journal, optionally changing it between."""

    def __init__(self, journal: AccountJournal, *, commit_between: Money | None = None) -> None:
        """Bind the journal and a transfer that lands after each read, if any."""
        self.journal, self.commit_between = journal, commit_between

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Serve the reconciliation projection, then optionally commit a transfer it lacks.

        Any other projection is refused: a full inspection carries every paper trace
        and outgrows the owner socket's one MiB response bound during a sustained run.
        """
        assert request.action == "inspect" and request.projection == "reconciliation"
        facts = self.journal.result_snapshot(request)
        if self.commit_between is not None:
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


class TestCapacityReconciler:
    """Keep account state fresh only through exact, retained reconciliations."""

    @staticmethod
    def _append_row(rows: list[tuple[str, object]], kind: str, values: object) -> None:
        """Retain one reconciler record."""
        rows.append((kind, values))

    @staticmethod
    def _wall_clock(account_id: str) -> datetime:
        """Report the current UTC wall clock as every account's knowledge time."""
        return datetime.now(UTC)

    def test_matched_reconciliation_advances_account_freshness(self, tmp_path: Path) -> None:
        """Each round reconciles the settled facts under a fresh identity."""
        journal = ReconcilerFixture.journal(tmp_path / "account.sqlite3")
        before = journal.accounts()[0].reconciled_at
        rows: list[tuple[str, object]] = []
        reconciler = AccountReconciler(
            {_ACCOUNT: _JournalClient(journal)},
            period_seconds=0.05,
            record=partial(self._append_row, rows),
            accepted_market=self._wall_clock,
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
        journal = ReconcilerFixture.journal(tmp_path / "account.sqlite3")
        rows: list[tuple[str, object]] = []
        reconciler = AccountReconciler(
            {
                _ACCOUNT: _JournalClient(
                    journal,
                    commit_between=ReconcilerFixture.workload(datetime.now(UTC))
                    .venue_workload("okx")
                    .money("-1"),
                )
            },
            period_seconds=0.05,
            record=partial(self._append_row, rows),
            accepted_market=self._wall_clock,
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

    def test_observations_carry_the_later_of_knowledge_and_accepted_market(
        self, tmp_path: Path
    ) -> None:
        """Without a market the stamp is the account's own clock; a later market leads it."""
        journal = ReconcilerFixture.journal(tmp_path / "account.sqlite3")
        known = journal.result_snapshot(
            AccountExecutionRequest(
                action="inspect", account_id=_ACCOUNT, projection="reconciliation"
            )
        ).known_at
        accepted = datetime.now(UTC) - timedelta(seconds=2)
        clock: dict[str, datetime | None] = {_ACCOUNT: None}
        rows: list[tuple[str, object]] = []
        reconciler = AccountReconciler(
            {_ACCOUNT: _JournalClient(journal)},
            period_seconds=60,
            record=partial(self._append_row, rows),
            accepted_market=clock.get,
        )
        assert reconciler.reconcile(_ACCOUNT) and reconciler.attempts == 1
        assert known is not None and journal.accounts()[0].reconciled_at == known
        assert known < accepted
        clock[_ACCOUNT] = accepted
        assert reconciler.reconcile(_ACCOUNT) and reconciler.attempts == 2
        assert journal.accounts()[0].reconciled_at == accepted


class TestReconciliationStamp:
    """Stamp a round's evidence at the account's own clocks, never at a delivery clock.

    One real D2 paper account (1 ms entry delay): a book is accepted at ``A``, then a
    grid decision dated ``T`` arrives in the delivery that crosses ``T``.
    """

    @staticmethod
    def _reconcile(journal: AccountJournal, accepted: datetime | None, identity: str) -> datetime:
        """Reconcile one snapshot's facts under the shared stamp rule; return the stamp."""
        facts = journal.result_snapshot(
            AccountExecutionRequest(
                action="inspect", account_id="shared", projection="reconciliation"
            )
        )
        observation = AccountReconciler.observation(facts, accepted, identity)
        assert journal.reconcile(observation)
        return observation.at

    @staticmethod
    def _decide(journal: AccountJournal, at: datetime, identity: str) -> tuple[str, str]:
        """Commit one strategy decision dated ``at``; return the batch status and reason."""
        journal.observe(AccountQuote(price=D2Account.price(), at=at))
        commit = journal.coordinate(
            PortfolioBatch(
                identity=identity,
                at=at + timedelta(microseconds=1),
                decisions=(D2Account.target("alpha", identity, at, "2"),),
            )
        )
        return commit.status, commit.reason

    @staticmethod
    def _arrival(journal: AccountJournal, identity: str) -> tuple[str, str] | None:
        """Return the decision's own arrival outcome, if any."""
        derived = AccountJournal.arrival_identity("shared", "alpha", identity)
        for item in journal.result_snapshot(
            AccountExecutionRequest(action="inspect", projection="decisions")
        ).decision_outcomes:
            if item.decision_identity == derived:
                return item.status, item.reason
        return None

    def test_the_shared_stamp_admits_the_crossed_decision_and_its_arrival(
        self, tmp_path: Path
    ) -> None:
        """A round stamped at the last accepted market precedes the decision it crosses.

        A pending decision places no order, so it does not advance the account's
        knowledge: another round before its arrival is stamped at the same market, and
        the arrival is still admitted at its own time.
        """
        journal = D2Account.open(tmp_path / "shared.sqlite3", delayed=True)
        accepted = D2Account.at
        D2Account.book(journal, 0)
        decided = accepted + timedelta(milliseconds=3)
        assert self._reconcile(journal, accepted, "before-crossing") == accepted
        assert self._decide(journal, decided, "crossed") == ("committed", "arrival_pending")
        assert self._reconcile(journal, accepted, "before-arrival") == accepted
        D2Account.book(journal, 5)
        assert self._arrival(journal, "crossed") == ("committed", "reserved")

    def test_a_delivery_clock_stamp_refuses_the_decision_it_has_not_processed(
        self, tmp_path: Path
    ) -> None:
        """The defect's boundary, and production's refusal of genuinely later state.

        Stamped at the crossing delivery's clock, 1 ms after the instant, the round
        asserts account state after the decision, which is refused, not admitted late.
        """
        journal = D2Account.open(tmp_path / "delivery.sqlite3", delayed=True)
        D2Account.book(journal, 0)
        decided = D2Account.at + timedelta(milliseconds=3)
        delivery = decided + timedelta(milliseconds=1)
        assert self._reconcile(journal, delivery, "delivery-clock") == delivery
        assert self._decide(journal, decided, "refused") == (
            "rejected",
            "decision_precedes_account_state",
        )
        assert self._arrival(journal, "refused") is None

    def test_equal_times_are_admitted_and_one_microsecond_later_is_not(
        self, tmp_path: Path
    ) -> None:
        """A market accepted exactly at the instant stamps the round at it; that is safe.

        The refusal is strict: a decision at the account's knowledge clock is admitted,
        one a microsecond before it is not.
        """
        journal = D2Account.open(tmp_path / "equal.sqlite3", delayed=True)
        decided = D2Account.at + timedelta(milliseconds=3)
        D2Account.book(journal, 3)
        assert self._reconcile(journal, decided, "at-instant") == decided
        assert self._decide(journal, decided, "equal") == ("committed", "arrival_pending")
        D2Account.book(journal, 5)
        assert self._arrival(journal, "equal") == ("committed", "reserved")
        later = decided + timedelta(seconds=3)
        assert self._reconcile(journal, later + timedelta(microseconds=1), "after") > later
        assert self._decide(journal, later, "earlier") == (
            "rejected",
            "decision_precedes_account_state",
        )

    def test_the_stamp_is_the_later_account_clock(self, tmp_path: Path) -> None:
        """No accepted market stamps at the knowledge clock; an earlier market never lowers it."""
        journal = D2Account.open(tmp_path / "clocks.sqlite3", delayed=True)
        facts = journal.result_snapshot(
            AccountExecutionRequest(
                action="inspect", account_id="shared", projection="reconciliation"
            )
        )
        assert facts.known_at is not None
        assert AccountReconciler.observation(facts, None, "none").at == facts.known_at
        earlier = facts.known_at - timedelta(seconds=1)
        assert AccountReconciler.observation(facts, earlier, "earlier").at == facts.known_at
        later = facts.known_at + timedelta(seconds=1)
        assert AccountReconciler.observation(facts, later, "later").at == later
        full = journal.result_snapshot(AccountExecutionRequest(action="inspect"))
        try:
            AccountReconciler.observation(full, None, "full")
        except ValueError as error:
            assert "knowledge clock" in str(error)
        else:
            raise AssertionError("a full inspection carries no knowledge clock")
