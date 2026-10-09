"""Keep the journey's first reconciliation of a phase at each account's first market."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import cast

# third party library imports
from journey_paper import JourneyPaper, JourneyPaperArguments

# project library imports
from execution import SocketPaperAccount


class _RecordedReconciler(JourneyPaper):
    """Reconcile authored accounts whose first markets arrive at authored offsets.

    Each account's first market is accepted ``markets[account]`` seconds after the
    reconciler starts, or never; reconciliations are recorded, not sent, and the
    reconciler stops after ``rounds`` of them.
    """

    def __init__(
        self, arguments: JourneyPaperArguments, markets: dict[str, float], rounds: int
    ) -> None:
        """Bind the authored market offsets, the stopping count and an empty record."""
        super().__init__(arguments)
        self.markets, self.rounds = markets, rounds
        self.started = time.monotonic()
        self.reconciled: list[tuple[str, float, datetime | None]] = []

    def served_accounts(self) -> dict[str, SocketPaperAccount]:
        """Name every authored account; no socket client is used."""
        return {account_id: cast(SocketPaperAccount, None) for account_id in self.markets}

    def accepted_market(self, account_id: str) -> datetime | None:
        """Report an accepted market once its authored offset has passed."""
        elapsed = time.monotonic() - self.started
        return datetime.now(UTC) if elapsed >= self.markets[account_id] else None

    def reconcile_account(self, installed: SocketPaperAccount, account_id: str, log: Path) -> None:
        """Record when each account was reconciled and the market it was stamped at."""
        self.reconciled.append(
            (account_id, time.monotonic() - self.started, self.accepted_market(account_id))
        )
        if len(self.reconciled) == self.rounds:
            self.arguments.stop.touch()

    def times(self, account_id: str) -> list[tuple[float, bool]]:
        """Return one account's reconciliation offsets and whether each was stamped at a market."""
        return [
            (at, market is not None) for name, at, market in self.reconciled if name == account_id
        ]


class TestJourneyReconciler:
    """Reconcile as the phase starts and on each account's own clock after."""

    @staticmethod
    def _arguments(tmp_path: Path) -> JourneyPaperArguments:
        """Bind a two-second period and a stop file under the test root."""
        arguments = JourneyPaperArguments()
        arguments.plan, arguments.stop, arguments.period = tmp_path, tmp_path / "stop", 2.0
        return arguments

    def test_each_account_is_reconciled_at_its_first_market(self, tmp_path: Path) -> None:
        """A live account reconciles at once although a quiet account sorts before it.

        The quiet account, whose market never arrives, is reconciled at its own clock
        when one period has passed.
        """
        reconciler = _RecordedReconciler(
            self._arguments(tmp_path), {"a-quiet": float("inf"), "b-live": 0.0}, rounds=3
        )
        reconciler.reconcile()
        live, quiet = reconciler.times("b-live"), reconciler.times("a-quiet")
        assert live[0][0] < 1.0 and live[0][1]
        assert 2.0 <= quiet[0][0] < 3.0 and not quiet[0][1]
        assert 2.0 <= live[1][0] - live[0][0] < 2.8

    def test_a_late_market_and_each_period_follow_the_account_s_own_clock(
        self, tmp_path: Path
    ) -> None:
        """A market after the first period is reconciled at once; periods do not drift.

        The late account is reconciled at its own clock after a period, then at its
        first market three seconds in; the live account every period from its own
        previous reconciliation.
        """
        reconciler = _RecordedReconciler(
            self._arguments(tmp_path), {"a-late": 3.0, "b-live": 0.0}, rounds=6
        )
        reconciler.reconcile()
        late, live = reconciler.times("a-late"), reconciler.times("b-live")
        assert 2.0 <= late[0][0] < 3.0 and not late[0][1]
        assert 3.0 <= late[1][0] < 3.8 and late[1][1]
        assert all(2.0 <= later - earlier < 2.8 for (earlier, _), (later, _) in pairwise(live))
