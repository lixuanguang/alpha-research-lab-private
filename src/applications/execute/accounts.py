"""Operate the shared local account boundary through the installed execution CLI."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# third party library imports
from msgspec.structs import replace

# project library imports
from applications.execute.account_service import AccountOwnerService
from configuration import (
    AccountConfiguration,
)
from execution import (
    AccountControlResult,
    AccountJournal,
    ExecutionMonitoring,
    OrderState,
    PaperMarketOutcome,
    PaperOwner,
    PaperReductionResult,
    PortfolioCommit,
    StepCommit,
)
from execution import (
    AccountExecutionRequest as AccountExecutionRequest,
)
from execution import (
    AccountExecutionResult as AccountExecutionResult,
)
from runtime import AccountRecoveryReceipt, AccountWorkspace, InstalledIdentity
from serialization import DomainCodec
from telemetry import OperationalAlerts, TelemetryStore


class AccountExecutionApplication:
    """Bind bounded installed request files to the authoritative account journal."""

    def __init__(self) -> None:
        """Bind telemetry identity lazily for this installed application lifetime.

        The configuration decoded from one exact byte string is reused while the
        file still holds those bytes; any other bytes are decoded and validated again.
        """
        self._monitoring: ExecutionMonitoring | None = None
        self._codec = DomainCodec()
        self._configuration: tuple[bytes, AccountConfiguration] | None = None

    def run(
        self,
        *,
        config_path: Path,
        journal_path: Path,
        request_path: Path | None = None,
        request_payload: bytes | None = None,
        telemetry_path: Path | None = None,
        release_identity: str | None = None,
        opened_journal: AccountJournal | None = None,
        phases: dict[str, int] | None = None,
    ) -> AccountExecutionResult:
        """Validate configuration/request bytes before any persistent operation.

        The request is a retained file at ``request_path`` or, from the account owner
        service, the exact retained bytes in ``request_payload``; at most one is given.
        ``phases``, when given, receives opt-in monotonic clocks after each stage.
        """
        if request_path is not None and request_payload is not None:
            raise ValueError("account request has both a path and retained bytes")
        if release_identity is not None and (
            len(release_identity) != 64
            or any(character not in "0123456789abcdef" for character in release_identity)
        ):
            raise ValueError("invalid installed release identity")
        codec = self._codec
        config = self._config(self._read(config_path))
        if config.mode == "venue_test":
            raise ValueError("venue_test account requires the separate venue command")
        if request_path is not None:
            request_payload = self._read(request_path)
        elif request_payload is not None and len(request_payload) > 1_048_576:
            raise ValueError("account request or configuration exceeds one MiB")
        # Decoding and construction both run the request's own validation.
        request = (
            AccountExecutionRequest(action="inspect")
            if request_payload is None
            else codec.decode_json(request_payload, AccountExecutionRequest)
        )
        if opened_journal is not None and (
            opened_journal.path != journal_path
            or opened_journal.config != config
            or request.action in ("backup", "restore", "serve_paper")
            or (
                opened_journal.paper_owner != request.paper_owner
                and not (request.action == "inspect" and request.paper_owner is None)
            )
        ):
            raise ValueError("opened account journal differs from the validated request")
        if (
            request.action
            in (
                "install_paper",
                "authorize_paper",
                "revoke_paper",
                "claim_paper",
                "bind_paper_scenario",
                "public_market",
                "reduce_paper",
                "serve_paper",
            )
            and release_identity is None
        ):
            raise ValueError("paper activation requires an installed release identity")
        if request.deployment is not None and release_identity not in request.deployment.releases:
            raise ValueError("paper deployment excludes the installed release")
        if (
            request.paper_owner is not None
            and request.paper_owner.release_identity != release_identity
        ):
            raise ValueError("paper owner differs from the installed release")
        if (
            release_identity is not None
            and request.action
            in (
                "admit",
                "coordinate",
                "public_market",
                "post",
                "event",
                "net_event",
                "net_cost",
                "restart_instance",
                "reissue_pending",
            )
            and (request.paper_owner is None)
        ):
            raise ValueError("installed paper admission requires a claimed owner")
        if (
            release_identity is not None
            and request.action == "control"
            and request.control is not None
            and request.control.kind in ("startup", "restart")
        ):
            raise ValueError(
                "installed paper restart requires deployment authority and owner claim"
            )
        if request.action == "serve_paper":
            if (
                request.paper_owner is None
                or request.service_socket is None
                or request.service_seconds is None
                or release_identity is None
            ):
                raise ValueError("paper service startup is incomplete")
            return AccountOwnerService(
                application=self,
                config=config,
                config_path=config_path,
                journal_path=journal_path,
                telemetry_path=telemetry_path,
                release_identity=release_identity,
                paper_owner=request.paper_owner,
                socket_path=Path(request.service_socket),
                duration_seconds=request.service_seconds,
            ).serve()
        if request.action == "shutdown_paper":
            raise ValueError("paper service shutdown requires its active socket")
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
        journal = (
            AccountJournal(journal_path, config, paper_owner=request.paper_owner)
            if opened_journal is None
            else opened_journal
        )
        alert_store = OperationalAlerts(journal_path.with_suffix(".alerts.sqlite3"))
        control: AccountControlResult | None = None
        alert_error: str | None = None
        admission: StepCommit | None = None
        order: OrderState | None = None
        reconciled: bool | None = None
        portfolio: PortfolioCommit | None = None
        public_market: PaperMarketOutcome | None = None
        exported_traces: int | None = None
        reduction_result: PaperReductionResult | None = None
        claimed_owner: PaperOwner | None = None
        if request.deployment is not None:
            journal.install_paper(request.deployment)
        elif request.authorization is not None:
            if not any(
                activation.deployment.identity == request.authorization.deployment_sha256
                and release_identity in activation.deployment.releases
                for activation in journal.paper_activations()
            ):
                raise ValueError("paper authorization excludes the installed release")
            journal.authorize_paper(request.authorization)
        elif request.action == "revoke_paper":
            if request.account_id is None or request.authorization_id is None or request.at is None:
                raise ValueError("paper revocation is incomplete")
            journal.revoke_paper(request.account_id, request.authorization_id, request.at)
        elif request.action == "claim_paper":
            if (
                request.account_id is None
                or request.owner_id is None
                or request.control is None
                or release_identity is None
            ):
                raise ValueError("paper owner claim is incomplete")
            claimed_owner = journal.claim_paper(
                request.account_id, request.owner_id, release_identity, request.control
            )
        elif request.action == "bind_paper_scenario":
            if request.account_id is None or request.scenario is None:
                raise ValueError("paper scenario binding is incomplete")
            journal.bind_paper_scenario(request.account_id, request.scenario)
        elif request.market is not None:
            if request.account_id is None or request.scenario is None:
                raise ValueError("public market request is incomplete")
            public_market = journal.apply_public_market(
                request.account_id, request.market, request.scenario
            )
        elif request.action == "export_traces":
            if request.export_path is None:
                raise ValueError("trace export is incomplete")
            exported_traces = journal.export_paper_traces(
                Path(request.export_path), request.account_id
            )
        elif request.reduction is not None:
            if not any(
                item.deployment.account_id == request.reduction.account_id
                for item in journal.paper_activations()
            ):
                raise ValueError("installed paper reduction requires a deployment")
            reduction_result = journal.reduce_paper(request.reduction)
        elif request.decision is not None:
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
        if phases is not None:
            phases["journal_ns"] = time.monotonic_ns()
        try:
            alerts = alert_store.read()
        except OSError, sqlite3.Error, ValueError:
            alerts = ()
            alert_error = "alert_store_invalid"
        if phases is not None:
            phases["alerts_ns"] = time.monotonic_ns()
        snapshot = journal.result_snapshot(request)
        result = replace(
            snapshot,
            # A command's own commit is its outcome; an inspection keeps the outcome its
            # projection read, such as a saved batch's.
            portfolio=snapshot.portfolio if portfolio is None else portfolio,
            admission=admission,
            order=order,
            reconciled=reconciled,
            control=control,
            alerts=alerts,
            alert_error=alert_error,
            recovery=recovery,
            public_market=public_market,
            exported_traces=exported_traces,
            reduction_result=reduction_result,
            claimed_owner=claimed_owner,
        )
        if phases is not None:
            phases["snapshot_ns"] = time.monotonic_ns()
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
            alert_controls = journal.controls() if request.projection != "full" else result.controls
            alert_accounts = {
                saved.request.identity: saved.request.account_id for saved in alert_controls
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
                if self._monitoring is None:
                    self._monitoring = ExecutionMonitoring(InstalledIdentity.sha256())
                events = self._monitoring.account(
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
                if phases is not None:
                    phases["monitoring_ns"] = time.monotonic_ns()
                completed_at = datetime.now(UTC)
                events = tuple(
                    replace(event, available_at=completed_at, recorded_at=completed_at)
                    for event in events
                )
                TelemetryStore(telemetry_path).append(events)
                if phases is not None:
                    phases["telemetry_ns"] = time.monotonic_ns()
            except Exception as error:
                # Account controls and their alert outcomes have already committed.
                result = replace(result, telemetry_error=type(error).__name__)
        return result

    def _config(self, payload: bytes) -> AccountConfiguration:
        """Decode configuration bytes, reusing the previous decode of identical bytes."""
        cached = self._configuration
        if cached is not None and cached[0] == payload:
            return cached[1]
        config = self._codec.decode_json(payload, AccountConfiguration)
        self._configuration = payload, config
        return config

    @staticmethod
    def _read(path: Path) -> bytes:
        """Read a bounded exact wire document before decoding it."""
        payload = path.read_bytes()
        if len(payload) > 1_048_576:
            raise ValueError("account request or configuration exceeds one MiB")
        return payload
