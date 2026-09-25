"""Operate the shared local account boundary through the installed execution CLI."""

from __future__ import annotations

# standard library imports
from pathlib import Path
from typing import Literal

# project library imports
from accounting import AccountPosting
from configuration import AccountConfiguration
from execution import (
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    AccountView,
    OrderEvent,
    OrderState,
    StepCommit,
    TaggedOrder,
)
from serialization import DomainCodec, WireRecord


class AccountExecutionRequest(WireRecord, frozen=True):
    """Select exactly one durable account operation without executable authority."""

    action: Literal["inspect", "admit", "event", "post", "reconcile", "block", "quote"]
    decision: AccountDecision | None = None
    event: OrderEvent | None = None
    posting: AccountPosting | None = None
    observation: AccountObservation | None = None
    quote: AccountQuote | None = None
    account_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Reject missing, extra and ambiguous operation payloads."""
        fields = {
            "admit": self.decision,
            "event": self.event,
            "post": self.posting,
            "reconcile": self.observation,
            "quote": self.quote,
        }
        if self.action not in (*fields, "inspect", "block"):
            raise ValueError("invalid account action")
        for action, payload in fields.items():
            if (action == self.action) != (payload is not None):
                raise ValueError("account action has missing or extraneous payload")
            if payload is not None:
                payload.__post_init__()
        if self.action == "block":
            if not self.account_id or not self.reason:
                raise ValueError("account block requires account and reason")
        elif self.account_id is not None or self.reason is not None:
            raise ValueError("account control fields require a block action")


class AccountExecutionResult(WireRecord, frozen=True):
    """Return current exact accounts, tagged orders and the operation outcome."""

    accounts: tuple[AccountView, ...]
    orders: tuple[TaggedOrder, ...]
    failed_events: tuple[OrderEvent, ...] = ()
    failed_postings: tuple[AccountPosting, ...] = ()
    admission: StepCommit | None = None
    order: OrderState | None = None
    reconciled: bool | None = None
    submission_attempted: bool = False

    def __post_init__(self) -> None:
        """Keep result authority closed and validate its retained financial records."""
        if self.submission_attempted is not False:
            raise ValueError("account application cannot submit")
        for account in self.accounts:
            account.__post_init__()
        for order in self.orders:
            order.__post_init__()
        for event in self.failed_events:
            event.__post_init__()
        for posting in self.failed_postings:
            posting.__post_init__()
        if self.admission is not None:
            self.admission.__post_init__()
        if self.order is not None:
            self.order.__post_init__()
        if self.reconciled is not None and type(self.reconciled) is not bool:
            raise ValueError("reconciliation result must be Boolean")


class AccountExecutionApplication:
    """Bind bounded installed request files to the authoritative account journal."""

    def run(
        self, *, config_path: Path, journal_path: Path, request_path: Path | None = None
    ) -> AccountExecutionResult:
        """Validate configuration/request bytes before any persistent operation."""
        codec = DomainCodec()
        config = codec.decode_json(self._read(config_path), AccountConfiguration)
        request = (
            AccountExecutionRequest(action="inspect")
            if request_path is None
            else codec.decode_json(self._read(request_path), AccountExecutionRequest)
        )
        request.__post_init__()
        journal = AccountJournal(journal_path, config)
        admission: StepCommit | None = None
        order: OrderState | None = None
        reconciled: bool | None = None
        if request.decision is not None:
            admission = journal.admit(request.decision)
        elif request.event is not None:
            order = journal.apply_event(request.event)
        elif request.posting is not None:
            journal.post(request.posting)
        elif request.observation is not None:
            reconciled = journal.reconcile(request.observation)
        elif request.quote is not None:
            journal.observe(request.quote)
        elif request.action == "block":
            if request.account_id is None or request.reason is None:
                raise ValueError("account block is incomplete")
            journal.block(request.account_id, request.reason)
        return AccountExecutionResult(
            accounts=journal.accounts(),
            orders=journal.orders(),
            failed_events=journal.failed_events(),
            failed_postings=journal.failed_postings(),
            admission=admission,
            order=order,
            reconciled=reconciled,
        )

    @staticmethod
    def _read(path: Path) -> bytes:
        """Read a bounded exact wire document before decoding it."""
        payload = path.read_bytes()
        if len(payload) > 1_048_576:
            raise ValueError("account request or configuration exceeds one MiB")
        return payload
