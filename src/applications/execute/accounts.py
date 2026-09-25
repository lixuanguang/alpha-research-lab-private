"""Operate the shared local account boundary through the installed execution CLI."""

from __future__ import annotations

# standard library imports
from datetime import datetime
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
    NetFeeCorrection,
    NetOrder,
    OrderEvent,
    OrderState,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioResidual,
    StepCommit,
    TaggedOrder,
)
from serialization import DomainCodec, WireRecord


class AccountExecutionRequest(WireRecord, frozen=True):
    """Select exactly one durable account operation without executable authority."""

    action: Literal[
        "inspect",
        "admit",
        "event",
        "post",
        "reconcile",
        "block",
        "quote",
        "coordinate",
        "net_event",
        "stop_instance",
        "restart_instance",
        "reissue_pending",
        "net_cost",
    ]
    decision: AccountDecision | None = None
    event: OrderEvent | None = None
    posting: AccountPosting | None = None
    observation: AccountObservation | None = None
    quote: AccountQuote | None = None
    batch: PortfolioBatch | None = None
    net_event: OrderEvent | None = None
    net_cost: NetFeeCorrection | None = None
    instance_id: str | None = None
    at: datetime | None = None
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
            "coordinate": self.batch,
            "net_event": self.net_event,
            "net_cost": self.net_cost,
        }
        if self.action not in (
            *fields,
            "inspect",
            "block",
            "stop_instance",
            "restart_instance",
            "reissue_pending",
        ):
            raise ValueError("invalid account action")
        for action, payload in fields.items():
            if (action == self.action) != (payload is not None):
                raise ValueError("account action has missing or extraneous payload")
            if payload is not None:
                payload.__post_init__()
        if self.action == "block":
            if not self.account_id or not self.reason:
                raise ValueError("account block requires account and reason")
        elif self.action == "reissue_pending":
            if not self.account_id or self.at is None or self.reason is not None:
                raise ValueError("residual reissue requires account and UTC time")
            self._require_utc(self.at, field_name="residual reissue")
        elif self.account_id is not None or self.reason is not None:
            raise ValueError("account control fields require a block action")
        if self.action in ("stop_instance", "restart_instance"):
            if not self.instance_id or self.at is None:
                raise ValueError("instance control requires identity and UTC time")
            self._require_utc(self.at, field_name="instance control")
        elif self.instance_id is not None or (
            self.at is not None and self.action != "reissue_pending"
        ):
            raise ValueError("instance control fields require a stop or restart action")


class AccountExecutionResult(WireRecord, frozen=True):
    """Return current exact accounts, tagged orders and the operation outcome."""

    accounts: tuple[AccountView, ...]
    orders: tuple[TaggedOrder, ...]
    net_orders: tuple[NetOrder, ...] = ()
    portfolio: PortfolioCommit | None = None
    residuals: tuple[PortfolioResidual, ...] = ()
    stopped_instances: tuple[str, ...] = ()
    failed_net_events: tuple[OrderEvent, ...] = ()
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
        for parent in self.net_orders:
            parent.__post_init__()
        if self.portfolio is not None:
            self.portfolio.__post_init__()
        for residual in self.residuals:
            residual.__post_init__()
        if type(self.stopped_instances) is not tuple or any(
            type(instance) is not str or not instance for instance in self.stopped_instances
        ):
            raise ValueError("stopped instances must be immutable identities")
        for event in self.failed_net_events:
            event.__post_init__()
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
        portfolio: PortfolioCommit | None = None
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
        elif request.batch is not None:
            portfolio = journal.coordinate(request.batch)
        elif request.net_event is not None:
            journal.apply_net_event(request.net_event)
        elif request.net_cost is not None:
            journal.correct_net_fee(request.net_cost)
        elif request.action in ("stop_instance", "restart_instance"):
            if request.instance_id is None or request.at is None:
                raise ValueError("instance control is incomplete")
            if request.action == "stop_instance":
                journal.stop_instance(request.instance_id, request.at)
            else:
                journal.restart_instance(request.instance_id, request.at)
        elif request.action == "reissue_pending":
            if request.account_id is None or request.at is None:
                raise ValueError("residual reissue is incomplete")
            journal.reissue_pending(request.account_id, request.at)
        elif request.action == "block":
            if request.account_id is None or request.reason is None:
                raise ValueError("account block is incomplete")
            journal.block(request.account_id, request.reason)
        return AccountExecutionResult(
            accounts=journal.accounts(),
            orders=journal.orders(),
            net_orders=journal.net_orders(),
            portfolio=portfolio,
            residuals=tuple(
                residual
                for account in journal.accounts()
                for residual in journal.portfolio_residuals(account.ledger.account_id)
            ),
            stopped_instances=journal.stopped_instances(),
            failed_net_events=journal.failed_net_events(),
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
