"""Operate the shared local account boundary through the installed execution CLI."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

# third party library imports
from msgspec.structs import replace

# project library imports
from accounting import AccountPosting
from configuration import AccountConfiguration
from execution import (
    AccountControl,
    AccountControlResult,
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    AccountView,
    ExecutionMonitoring,
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
from runtime import AccountRecoveryReceipt, AccountWorkspace, InstalledIdentity
from serialization import DomainCodec, WireRecord
from telemetry import OperationalAlerts, OperationAlert, TelemetryStore


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
        "control",
        "backup",
        "restore",
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
    control: AccountControl | None = None
    alert_socket: str | None = None
    backup_root: str | None = None
    restore_root: str | None = None
    manifest_sha256: str | None = None

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
            "control": self.control,
        }
        if self.action not in (
            *fields,
            "inspect",
            "block",
            "stop_instance",
            "restart_instance",
            "reissue_pending",
            "backup",
            "restore",
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
        if self.alert_socket is not None:
            if self.control is None or self.control.kind not in ("stop", "fault"):
                raise ValueError("alerts require an explicit protective control")
            OperationAlert(
                identity=self.control.identity,
                control_sha256=hashlib.sha256(DomainCodec().encode_json(self.control)).hexdigest(),
                address=self.alert_socket,
                status="pending",
            )
        if self.action in ("backup", "restore"):
            if self.backup_root is None or not Path(self.backup_root).is_absolute():
                raise ValueError("account backup requires an absolute backup root")
            if self.action == "restore":
                if (
                    self.restore_root is None
                    or not Path(self.restore_root).is_absolute()
                    or self.manifest_sha256 is None
                    or len(self.manifest_sha256) != 64
                    or any(char not in "0123456789abcdef" for char in self.manifest_sha256)
                ):
                    raise ValueError("account restore requires destination and manifest identity")
            elif self.restore_root is not None or self.manifest_sha256 is not None:
                raise ValueError("backup cannot supply restore fields")
        elif any(
            value is not None
            for value in (self.backup_root, self.restore_root, self.manifest_sha256)
        ):
            raise ValueError("recovery fields require backup or restore action")


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
    control: AccountControlResult | None = None
    controls: tuple[AccountControlResult, ...] = ()
    alerts: tuple[OperationAlert, ...] = ()
    alert_error: str | None = None
    telemetry_error: str | None = None
    recovery: AccountRecoveryReceipt | None = None
    journal_path: str | None = None

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
        if self.control is not None:
            self.control.__post_init__()
        for control in self.controls:
            control.__post_init__()
        for alert in self.alerts:
            alert.__post_init__()
        if self.alert_error not in (None, "alert_persistence_failed", "alert_store_invalid"):
            raise ValueError("invalid alert persistence outcome")
        if self.telemetry_error is not None and (
            type(self.telemetry_error) is not str or not self.telemetry_error.isidentifier()
        ):
            raise ValueError("invalid telemetry persistence outcome")


class AccountExecutionApplication:
    """Bind bounded installed request files to the authoritative account journal."""

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        request_path: Path | None = None,
        telemetry_path: Path | None = None,
    ) -> AccountExecutionResult:
        """Validate configuration/request bytes before any persistent operation."""
        codec = DomainCodec()
        config = codec.decode_json(self._read(config_path), AccountConfiguration)
        if config.mode == "venue_test":
            raise ValueError("venue_test account requires the separate venue command")
        request = (
            AccountExecutionRequest(action="inspect")
            if request_path is None
            else codec.decode_json(self._read(request_path), AccountExecutionRequest)
        )
        request.__post_init__()
        recovery: AccountRecoveryReceipt | None = None
        if request.action in ("backup", "restore"):
            workspace = AccountWorkspace(
                config, component=journal_path.parent.name, journal_name=journal_path.name
            )
            if request.backup_root is None:
                raise ValueError("account recovery is incomplete")
            if request.action == "backup":
                recovery = workspace.backup(journal_path.parent.parent, Path(request.backup_root))
            else:
                if request.restore_root is None or request.manifest_sha256 is None:
                    raise ValueError("account restore is incomplete")
                recovery = workspace.restore(
                    Path(request.backup_root),
                    Path(request.restore_root),
                    expected_manifest_sha256=request.manifest_sha256,
                )
                journal_path = (
                    Path(request.restore_root) / journal_path.parent.name / journal_path.name
                )
        journal = AccountJournal(journal_path, config)
        alert_store = OperationalAlerts(journal_path.with_suffix(".alerts.sqlite3"))
        control: AccountControlResult | None = None
        alert_error: str | None = None
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
        elif request.control is not None:
            control = journal.control(request.control)
            if request.alert_socket is not None and control.status == "applied":
                try:
                    alert_store.send(
                        identity=request.control.identity,
                        control_sha256=hashlib.sha256(
                            codec.encode_json(request.control)
                        ).hexdigest(),
                        address=request.alert_socket,
                    )
                except OSError, sqlite3.Error:
                    alert_error = "alert_persistence_failed"
        try:
            alerts = alert_store.read()
        except OSError, sqlite3.Error, ValueError:
            alerts = ()
            alert_error = "alert_store_invalid"
        result = AccountExecutionResult(
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
            control=control,
            controls=journal.controls(),
            alerts=alerts,
            alert_error=alert_error,
            recovery=recovery,
            journal_path=str(journal_path),
        )
        if telemetry_path is not None:
            operation_account_id = (
                request.decision.account_id
                if request.decision is not None
                else request.observation.snapshot.account_id
                if request.observation is not None
                else request.control.account_id
                if request.control is not None
                else request.account_id
            )
            alert_accounts = {
                saved.request.identity: saved.request.account_id for saved in result.controls
            }
            alert_failures: dict[str, int] = {}
            for alert in alerts:
                if alert.status != "delivered" and alert.identity in alert_accounts:
                    account_id = alert_accounts[alert.identity]
                    alert_failures[account_id] = alert_failures.get(account_id, 0) + 1
            if alert_error == "alert_persistence_failed" and request.control is not None:
                account_id = request.control.account_id
                alert_failures[account_id] = alert_failures.get(account_id, 0) + 1
            try:
                events = ExecutionMonitoring(InstalledIdentity.sha256()).account(
                    journal,
                    observed_at=datetime.now(UTC),
                    sample=uuid4().hex,
                    admission=admission,
                    reconciled=reconciled,
                    control_rejected=control.status == "rejected" if control is not None else None,
                    alert_failures=alert_failures,
                    alert_store_invalid=alert_error == "alert_store_invalid",
                    operation_account_id=operation_account_id,
                )
                completed_at = datetime.now(UTC)
                events = tuple(
                    replace(event, available_at=completed_at, recorded_at=completed_at)
                    for event in events
                )
                TelemetryStore(telemetry_path).append(events)
            except Exception as error:
                # Account controls and their alert outcomes have already committed.
                result = replace(result, telemetry_error=type(error).__name__)
        return result

    @staticmethod
    def _read(path: Path) -> bytes:
        """Read a bounded exact wire document before decoding it."""
        payload = path.read_bytes()
        if len(payload) > 1_048_576:
            raise ValueError("account request or configuration exceeds one MiB")
        return payload
