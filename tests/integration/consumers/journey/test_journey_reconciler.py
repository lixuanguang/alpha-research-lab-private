"""Keep the journey's first reconciliation of a phase at each account's first market."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime
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
    reconciler stops after its first periodic round.
    """

    def __init__(self, arguments: JourneyPaperArguments, markets: dict[str, float]) -> None:
        """Bind the authored market offsets and an empty record."""
        super().__init__(arguments)
        self.markets = markets
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
        if len(self.reconciled) == 2 * len(self.markets):
            self.arguments.stop.touch()


class TestJourneyReconciler:
    """Reconcile as the phase starts, not one period later."""

    def test_each_account_is_reconciled_at_its_first_market(self, tmp_path: Path) -> None:
        """A live account reconciles at once although a quiet account sorts before it.

        The quiet account, whose market never arrives, is reconciled at its own clock
        when one period has passed; both are reconciled again a period after that.
        """
        arguments = JourneyPaperArguments()
        arguments.plan, arguments.stop, arguments.period = tmp_path, tmp_path / "stop", 2.0
        reconciler = _RecordedReconciler(arguments, {"a-quiet": float("inf"), "b-live": 0.0})
        reconciler.reconcile()
        first = {account: (at, market) for account, at, market in reconciler.reconciled[:2]}
        assert [account for account, _, _ in reconciler.reconciled] == [
            "b-live",
            "a-quiet",
            "a-quiet",
            "b-live",
        ]
        assert first["b-live"][0] < 1.0 and first["b-live"][1] is not None
        assert first["a-quiet"][0] >= 2.0 and first["a-quiet"][1] is None
        assert all(at >= 4.0 for _, at, _ in reconciler.reconciled[2:])
