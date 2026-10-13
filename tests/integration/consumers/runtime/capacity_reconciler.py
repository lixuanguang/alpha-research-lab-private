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

    Paper facts are the account's own settled ledger and open physical orders, read
    with the account's knowledge clock from one snapshot through the
    ``reconciliation`` projection; a full inspection carries every paper trace, grows
    with the run and exceeds the owner socket's one MiB response bound. A mismatch
    faults the account (``account_break``), so it is retained as a failure and never
    retried.

    Each observation is stamped at the later of the account's knowledge clock
    (``known_at``) and its last accepted market, never the wall clock: a
    reconciliation advances the account's knowledge, and a market already in flight
    but earlier than the stamp would be refused, faulting the account. Neither clock
    can refuse one: the account already refuses any market before its own clock, and
    markets reach an account in order. The knowledge clock covers every working
    order's decision; the market clock keeps a quiet account's state fresh.
    """

    def __init__(
        self,
        accounts: Mapping[str, ReconcilingAccount],
        *,
        period_seconds: float,
        record: Callable[[str, object], None],
        accepted_market: Callable[[str], datetime | None],
    ) -> None:
        """Bind each owner's client, cadence, evidence writer and accepted-market clock."""
        if period_seconds <= 0 or not accounts:
            raise ValueError("reconciliation requires accounts and a positive cadence")
        self.accounts, self.period_seconds, self._record = dict(accounts), period_seconds, record
        self._accepted_market = accepted_market
        self.failures: list[str] = []
        self.attempts = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def reconcile(self, account_id: str) -> bool:
        """Read one account's facts, reconcile them under a fresh identity and retain both."""
        client = self.accounts[account_id]
        started = time.monotonic()
        facts = client.execute(
            AccountExecutionRequest(
                action="inspect", account_id=account_id, projection="reconciliation"
            )
        )
        observation = self.observation(
            facts, self._accepted_market(account_id), f"sustained-reconcile-{uuid4().hex}"
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

    @staticmethod
    def observation(
        facts: AccountExecutionResult, accepted: datetime | None, identity: str
    ) -> AccountObservation:
        """Describe one snapshot's facts at the later of its knowledge and market clocks.

        When a reconciliation is scheduled is independent of the time its evidence
        describes: the stamp is never a scheduling or delivery clock. A delivery's
        clock can pass a grid instant the account has not decided yet, and a stamp
        after that instant would refuse its decision as preceding account state; the
        last accepted market cannot, since a delivery decides every instant it
        crosses before its market is accepted.

        Raises:
            ValueError: The facts are not the ``reconciliation`` projection.
        """
        if facts.known_at is None:
            raise ValueError("reconciliation projection omitted the account's knowledge clock")
        (account,) = facts.accounts
        return AccountObservation(
            identity=identity,
            at=facts.known_at if accepted is None else max(accepted, facts.known_at),
            snapshot=AccountLedger(account.ledger).snapshot(),
            open_orders=(
                *(item.order for item in facts.orders),
                *(item.order for item in facts.net_orders),
            ),
        )

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
