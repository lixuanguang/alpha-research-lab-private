"""Define typed installed account command and response records for external consumers."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from accounting import AccountPosting
from configuration import PaperAuthorization, PaperDeployment, PaperExecutionScenario
from execution.account_records import (
    AccountControl,
    AccountControlResult,
    AccountDecision,
    AccountObservation,
    AccountPaperCost,
    AccountPaperFill,
    AccountPaperTrace,
    AccountQuote,
    AccountView,
    NetFeeCorrection,
    NetOrder,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioResidual,
    TaggedOrder,
)
from execution.account_recovery import AccountRecoveryReceipt
from execution.account_reduction import PaperReductionRequest, PaperReductionResult
from execution.paper import PaperMarket
from execution.paper_authority import PaperActivation, PaperOwner
from execution.records import OrderEvent, OrderState, StepCommit
from serialization import DomainCodec, WireRecord
from telemetry import OperationAlert


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
        "install_paper",
        "authorize_paper",
        "revoke_paper",
        "claim_paper",
        "bind_paper_scenario",
        "paper_market",
        "reduce_paper",
    ]
    decision: AccountDecision | None = None
    event: OrderEvent | None = None
    posting: AccountPosting | None = None
    observation: AccountObservation | None = None
    quote: AccountQuote | None = None
    batch: PortfolioBatch | None = None
    net_event: OrderEvent | None = None
    net_cost: NetFeeCorrection | None = None
    deployment: PaperDeployment | None = None
    authorization: PaperAuthorization | None = None
    paper_owner: PaperOwner | None = None
    market: PaperMarket | None = None
    scenario: PaperExecutionScenario | None = None
    reduction: PaperReductionRequest | None = None
    authorization_id: str | None = None
    owner_id: str | None = None
    query_instance: str | None = None
    query_batch: str | None = None
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
            "install_paper": self.deployment,
            "authorize_paper": self.authorization,
            "paper_market": self.market,
            "reduce_paper": self.reduction,
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
            "control",
            "revoke_paper",
            "claim_paper",
            "bind_paper_scenario",
        ):
            raise ValueError("invalid account action")
        for action, payload in fields.items():
            if (action == self.action) != (payload is not None):
                raise ValueError("account action has missing or extraneous payload")
            if payload is not None:
                payload.__post_init__()
        if (self.action in ("control", "claim_paper")) != (self.control is not None):
            raise ValueError("account control action has missing or extraneous payload")
        if self.control is not None:
            self.control.__post_init__()
        if self.paper_owner is not None:
            self.paper_owner.__post_init__()
            if self.action not in (
                "inspect",
                "admit",
                "coordinate",
                "quote",
                "reconcile",
                "event",
                "net_event",
                "post",
                "net_cost",
                "block",
                "control",
                "bind_paper_scenario",
                "paper_market",
                "reduce_paper",
                "restart_instance",
                "reissue_pending",
            ):
                raise ValueError("paper owner is outside a guarded account action")
        if self.action in ("bind_paper_scenario", "paper_market"):
            if not self.account_id or self.scenario is None:
                raise ValueError("paper market requires account and scenario")
            self.scenario.__post_init__()
        elif self.scenario is not None:
            raise ValueError("paper scenario requires a binding or market action")
        if self.action == "revoke_paper":
            if not self.account_id or not self.authorization_id or self.at is None:
                raise ValueError("paper revocation requires account, authority and UTC time")
            self._require_utc(self.at, field_name="paper revocation")
        elif self.authorization_id is not None:
            raise ValueError("paper authorization identity requires revocation")
        if self.action == "claim_paper":
            if not self.account_id or not self.owner_id or self.control is None:
                raise ValueError("paper owner claim requires account, worker and recovery control")
            if self.control.kind != "restart" or self.control.account_id != self.account_id:
                raise ValueError("paper owner claim requires matching restart control")
        elif self.owner_id is not None:
            raise ValueError("paper worker identity requires owner claim")
        if self.action == "inspect":
            for value in (self.query_instance, self.query_batch):
                if value is not None and (type(value) is not str or not value):
                    raise ValueError("account inspection query requires an identity")
        elif self.query_instance is not None or self.query_batch is not None:
            raise ValueError("account query fields require inspection")
        if self.action == "block":
            if not self.account_id or not self.reason:
                raise ValueError("account block requires account and reason")
        elif self.action == "reissue_pending":
            if not self.account_id or self.at is None or self.reason is not None:
                raise ValueError("residual reissue requires account and UTC time")
            self._require_utc(self.at, field_name="residual reissue")
        elif (
            self.action
            not in (
                "inspect",
                "reissue_pending",
                "revoke_paper",
                "claim_paper",
                "bind_paper_scenario",
                "paper_market",
            )
            and self.account_id is not None
        ) or self.reason is not None:
            raise ValueError("account control fields require a block action")
        if self.action in ("stop_instance", "restart_instance"):
            if not self.instance_id or self.at is None:
                raise ValueError("instance control requires identity and UTC time")
            self._require_utc(self.at, field_name="instance control")
        elif self.instance_id is not None or (
            self.at is not None and self.action not in ("reissue_pending", "revoke_paper")
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
    paper_activations: tuple[PaperActivation, ...] = ()
    paper_restore_quarantined: bool = False
    paper_traces: tuple[AccountPaperTrace, ...] = ()
    paper_reductions: tuple[PaperReductionResult, ...] = ()
    paper_fills: tuple[AccountPaperFill, ...] = ()
    paper_costs: tuple[AccountPaperCost, ...] = ()
    checkpoint: bytes | None = None
    saved_batch: PortfolioBatch | None = None
    matched_market: AccountPaperTrace | None = None
    reduction_result: PaperReductionResult | None = None
    claimed_owner: PaperOwner | None = None

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
        for activation in self.paper_activations:
            activation.__post_init__()
        for trace in self.paper_traces:
            trace.__post_init__()
        for reduction in self.paper_reductions:
            reduction.__post_init__()
        for fill in self.paper_fills:
            fill.__post_init__()
        for cost in self.paper_costs:
            cost.__post_init__()
        if self.checkpoint is not None and type(self.checkpoint) is not bytes:
            raise ValueError("account checkpoint must be immutable bytes")
        if self.saved_batch is not None:
            self.saved_batch.__post_init__()
        if self.matched_market is not None:
            self.matched_market.__post_init__()
        if self.reduction_result is not None:
            self.reduction_result.__post_init__()
        if self.claimed_owner is not None:
            self.claimed_owner.__post_init__()
