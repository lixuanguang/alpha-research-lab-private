"""Keep held paper positions fresh by reconciling each owner from its own settled facts."""

from __future__ import annotations

# standard library imports
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol
from uuid import uuid4

# project library imports
from accounting import AccountLedger
from execution import AccountExecutionRequest, AccountExecutionResult, AccountObservation


class ReconcilingAccount(Protocol):
    """Read complete account facts and reconcile an observation through one owner."""

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Return the account's complete current facts."""
        ...

    def reconcile(self, observation: AccountObservation) -> bool:
        """Compare independent facts and return whether they matched."""
        ...


class AccountReconciler:
    """Reconcile every account on a fixed cadence and stop at the first mismatch.

    Paper facts are the account's own settled ledger and open physical orders, as
    the four-owner recovery uses. They are read through the ``accounts`` and
    ``net_orders`` projections: a full inspection carries every paper trace, grows
    with the run and exceeds the owner socket's one MiB response bound. A mismatch
    faults the account (``account_break``), so it is retained as a failure and never
    retried.

    Each observation is stamped with the account's last accepted market instant, never
    the wall clock: a reconciliation advances the account's knowledge clock, and a
    selected market already in flight but available before that clock would be
    refused (``paper market precedes current account knowledge``), faulting the
    account. Markets are delivered to an account in order, so its last accepted one
    is never later than any market still to arrive.
    """

    def __init__(
        self,
        accounts: Mapping[str, ReconcilingAccount],
        *,
        period_seconds: float,
        record: Callable[[str, object], None],
        knowledge: Callable[[str], datetime | None],
    ) -> None:
        """Bind each owner's client, cadence, evidence writer and accepted-market clock."""
        if period_seconds <= 0 or not accounts:
            raise ValueError("reconciliation requires accounts and a positive cadence")
        self.accounts, self.period_seconds, self._record = dict(accounts), period_seconds, record
        self._knowledge = knowledge
        self.failures: list[str] = []
        self.attempts = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def reconcile(self, account_id: str) -> bool:
        """Read one account's facts, reconcile them under a fresh identity and retain both.

        Without an accepted market yet the round is skipped and retained as skipped.
        """
        client = self.accounts[account_id]
        at = self._knowledge(account_id)
        if at is None:
            self._record("account_reconcile_skipped", {"account": account_id})
            return True
        started = time.monotonic()
        accounts = client.execute(
            AccountExecutionRequest(action="inspect", account_id=account_id, projection="accounts")
        ).accounts
        orders = client.execute(
            AccountExecutionRequest(
                action="inspect", account_id=account_id, projection="net_orders"
            )
        ).net_orders
        ledger = next(item.ledger for item in accounts if item.ledger.account_id == account_id)
        observation = AccountObservation(
            identity=f"sustained-reconcile-{uuid4().hex}",
            at=at,
            snapshot=AccountLedger(ledger).snapshot(),
            open_orders=tuple(
                item.order
                for item in orders
                if item.account_id == account_id and not item.order.is_terminal
            ),
        )
        matched = client.reconcile(observation)
        self.attempts += 1
        self._record(
            "account_reconciled",
            {
                "account": account_id,
                "identity": observation.identity,
                "at": observation.at,
                "seconds": time.monotonic() - started,
                "matched": matched,
                "open_orders": len(observation.open_orders),
            },
        )
        if not matched:
            self.failures.append(f"reconciliation mismatch faulted {account_id}")
        return matched

    def start(self) -> None:
        """Begin the cadence; the first round runs one period after start."""
        self._thread = threading.Thread(target=self._run, name="sustained-reconciler")
        self._thread.start()

    def stop(self) -> None:
        """Stop after any round in progress and join the owned thread."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(30)
            if self._thread.is_alive():
                raise TimeoutError("bounded reconciler did not stop")

    def _run(self) -> None:
        """Reconcile every account once per period until stopped or failed."""
        while not self._stop.wait(self.period_seconds):
            for account_id in sorted(self.accounts):
                if self._stop.is_set():
                    return
                try:
                    matched = self.reconcile(account_id)
                except Exception as error:
                    self.failures.append(f"reconcile {account_id}: {type(error).__name__}: {error}")
                    self._record("account_reconcile_failure", self.failures[-1])
                    return
                if not matched:
                    return
