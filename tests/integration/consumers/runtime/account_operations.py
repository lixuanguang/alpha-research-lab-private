"""Qualify installed account controls, crash recovery and verified workspace restoration."""

from __future__ import annotations

# standard library imports
import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# third party library imports
from msgspec.structs import replace
from portfolio_account_facts import (
    PortfolioAccountFacts,
    ReferenceLimitPolicy,
    ReferenceTargetPolicy,
)

# project library imports
from applications.execute import (
    AccountExecutionRequest,
    AccountExecutionResult,
    MonitoringConfiguration,
)
from configuration import AccountConfiguration
from execution import AccountControl, AccountJournal, AccountObservation, AccountQuote, OrderEvent
from financial_units import Currency, Dimension, ExactRatio, QuantityKind
from reference_data.instruments import InstrumentId
from runtime import AccountWorkspace, ImplementationIdentity, ProcessSupervisor
from serialization import DomainCodec
from telemetry import (
    AlertRule,
    DashboardSnapshot,
    HealthMetric,
    HealthMetrics,
    HealthPolicy,
    MonitoringQuery,
    TelemetryStore,
)


class _AccountFailureResponse:
    """Bind a watchdog failure to independent durable account protection."""

    def __init__(self, journal: AccountJournal, at: datetime) -> None:
        """Retain explicit account ownership and a modeled failure knowledge time."""
        self.journal, self.at = journal, at

    def __call__(self, reason: str) -> None:
        """Stop exposure after child termination, before alert delivery."""
        outcome = self.journal.control(
            AccountControl(
                identity=f"watchdog:{reason}",
                account_id="shared",
                kind="fault",
                at=self.at,
                reason=reason,
            )
        )
        if outcome.status != "applied":
            raise ValueError("watchdog could not persist its account protection")


class _FailureWorkload:
    """Fail a real child after a durable checkpoint or a SQLite storage quota."""

    def __init__(self, config: AccountConfiguration, journal_path: Path, mode: str) -> None:
        """Bind only local paper state and one declared engineering fault."""
        self.config, self.journal_path, self.mode = config, journal_path, mode

    def __call__(self, root: Path, health: HealthMetrics) -> None:
        """Commit an actual account event before process loss, or exhaust a local store."""
        for metric in (
            HealthMetric.HEARTBEAT,
            HealthMetric.INGESTION,
            HealthMetric.PERSISTENCE,
            HealthMetric.MARKET,
        ):
            health.set(metric, time.monotonic_ns())
        if self.mode == "process":
            # A real process exit after a committed observation exercises WAL recovery.
            AccountJournal(self.journal_path, self.config).observe(
                AccountQuote(
                    price=self.config.instruments[0].tick.model_copy(
                        update={"value": Decimal("100")}
                    ),
                    at=self.config.opening_at + timedelta(seconds=12),
                )
            )
            os._exit(17)
        with closing(sqlite3.connect(root / "full.sqlite3")) as connection:
            connection.execute("PRAGMA page_size=512")
            connection.execute("CREATE TABLE payload (value BLOB)")
            connection.execute("PRAGMA max_page_count=2")
            try:
                connection.execute("INSERT INTO payload VALUES (?)", (b"x" * 8192,))
                connection.commit()
            except sqlite3.OperationalError as error:
                if "full" not in str(error):
                    raise
                health.set(HealthMetric.PERSISTENCE_FAILED, 1)
            else:
                raise AssertionError("SQLite quota did not reject the append")
        while True:
            time.sleep(0.1)


class AccountOperationsConsumer:
    """Retain every request/result while exercising two real policies on one account."""

    opening_at = datetime(2026, 9, 26, tzinfo=UTC)

    def __init__(self, output: Path, venue: Literal["okx", "bitfinex"]) -> None:
        """Select explicit spot fixture units; neither selection grants venue authority."""
        self.output = output
        self.codec = DomainCodec()
        self.venue = venue
        currency = Currency.from_code("USDT" if venue == "okx" else "USD")
        dimension = Dimension(
            instrument_id=InstrumentId.from_canonical_text(
                "11111111-1111-4111-8111-111111111111"
                if venue == "okx"
                else "22222222-2222-4222-8222-222222222222"
            ),
            kind=QuantityKind.BASE_UNIT,
        )
        self.facts = PortfolioAccountFacts(currency, dimension, self.codec, venue, self.opening_at)
        self.config = self.facts.config()
        self.config_path = output / "configuration.json"
        self.journal_path = output / "workspace/state/accounts.sqlite3"
        self.monitoring_started_at = datetime.now(UTC)

    def _at(self, seconds: int) -> datetime:
        """Use authored causal clocks independently of the watchdog's elapsed clocks."""
        return self.opening_at + timedelta(seconds=seconds)

    def _apply(self, label: str, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Invoke the installed CLI outside the checkout and retain exact interface bytes."""
        request_path = self.output / "requests" / f"{label}.json"
        request_path.write_bytes(self.codec.encode_json(request))
        result = subprocess.run(
            [
                str(Path(sys.executable).parent / "alpha-execute"),
                "account",
                "--config",
                str(self.config_path),
                "--journal",
                str(self.journal_path),
                "--request",
                str(request_path),
                "--telemetry",
                str(self.output / "monitoring.sqlite"),
            ],
            cwd=self.output,
            capture_output=True,
            check=False,
            timeout=30,
        )
        (self.output / "results" / f"{label}.stdout").write_bytes(result.stdout)
        (self.output / "results" / f"{label}.stderr").write_bytes(result.stderr)
        assert result.returncode == 0, (label, result.stderr)
        decoded = self.codec.decode_json(result.stdout, AccountExecutionResult)
        assert decoded.submission_attempted is False
        assert decoded.telemetry_error is None
        return decoded

    def _control(
        self,
        identity: str,
        kind: Literal["startup", "stop", "fault", "restart", "cancel"],
        seconds: int,
        *,
        expected: str | None = None,
        alert: str | None = None,
    ) -> AccountExecutionResult:
        """Exercise explicit control identity, recovery precondition and local alert routing."""
        return self._apply(
            identity,
            AccountExecutionRequest(
                action="control",
                control=AccountControl(
                    identity=identity,
                    account_id="shared",
                    kind=kind,
                    at=self._at(seconds),
                    reason="reference-failure" if kind in ("stop", "fault") else "",
                    expected_control_identity=expected,
                ),
                alert_socket=alert,
            ),
        )

    def _quote(self, seconds: int) -> None:
        """Retain independently supplied fresh marks through the installed command."""
        self._apply(
            f"quote-{seconds}",
            AccountExecutionRequest(
                action="quote",
                quote=AccountQuote(price=self.facts.price(), at=self._at(seconds)),
            ),
        )

    def run(self) -> None:
        """Check exact accounting across stop, uncertain cancel, restore and crash."""
        self.output.mkdir(parents=True)
        (self.output / "requests").mkdir()
        (self.output / "results").mkdir()
        self.config_path.write_bytes(self.codec.encode_json(self.config))
        self._quote(1)
        assert self._apply(
            "opening",
            AccountExecutionRequest(
                action="reconcile",
                observation=AccountObservation(
                    identity="opening",
                    at=self._at(1),
                    snapshot=self.facts.opening(),
                    open_orders=(),
                ),
            ),
        ).reconciled
        startup = self._control("startup", "startup", 1)
        assert startup.control is not None and startup.control.status == "applied"
        self._quote(2)
        target = ReferenceTargetPolicy(self.facts.quantity("2"))
        order = ReferenceLimitPolicy("buy", self.facts.quantity("2"), self.facts.price())
        admitted = self._apply(
            "two-strategies",
            AccountExecutionRequest(
                action="coordinate",
                batch=self.facts.batch(
                    "two-strategies",
                    self._at(2),
                    (
                        self.facts.decision(
                            instance_id="alpha",
                            identity="target",
                            at=self._at(2),
                            intent=target.decide(),
                        ),
                        self.facts.decision(
                            instance_id="beta",
                            identity="limit",
                            at=self._at(2),
                            intent=order.decide(),
                        ),
                    ),
                    "reject",
                ),
            ),
        )
        assert admitted.portfolio is not None and admitted.portfolio.status == "committed"
        parent = admitted.net_orders[0].order
        self._apply(
            "accepted",
            AccountExecutionRequest(
                action="net_event",
                net_event=OrderEvent(
                    identity="accepted",
                    order_id=parent.identity,
                    at=self._at(3),
                    kind="accepted",
                ),
            ),
        )
        fill = self.facts.physical_fill(
            identity="partial",
            order_id=parent.identity,
            decision_at=parent.decision_at,
            at=self._at(4),
            quantity="2",
            fee="0.02",
        )
        partial = self._apply(
            "partial", AccountExecutionRequest(action="net_event", net_event=fill)
        )
        self.facts.verify_balances(
            partial,
            physical_cash="49799.98",
            physical_position="2",
            physical_fee="0.02",
            alpha_cash="-100.01",
            alpha_position="1",
            alpha_fee="0.01",
            beta_cash="-100.01",
            beta_position="1",
            beta_fee="0.01",
        )
        with (
            TemporaryDirectory(prefix="ops-", dir="/private/tmp") as temporary,
            socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver,
        ):
            address = str(Path(temporary) / "alerts.sock")
            receiver.bind(address)
            receiver.settimeout(5)
            fault = self._control("feed-fault", "fault", 5, alert=address)
            assert fault.alerts[-1].status == "delivered"
            assert b"account-control:" in receiver.recv(1024)
            self._apply(
                "unknown",
                AccountExecutionRequest(
                    action="net_event",
                    net_event=OrderEvent(
                        identity="unknown",
                        order_id=parent.identity,
                        at=self._at(6),
                        kind="unknown",
                    ),
                ),
            )
            cancel = self._control("cancel", "cancel", 7)
            assert cancel.control is not None and cancel.control.cancel_order_ids == (
                parent.identity,
            )
            pending = self._apply(
                "cancel-ack",
                AccountExecutionRequest(
                    action="net_event",
                    net_event=OrderEvent(
                        identity="cancel-ack",
                        order_id=parent.identity,
                        at=self._at(8),
                        kind="cancel_ack",
                    ),
                ),
            )
            assert pending.net_orders[0].order.remaining == self.facts.quantity("2")
            unsafe = self._control("unsafe-restart", "restart", 8, expected="feed-fault")
            assert unsafe.control is not None and unsafe.control.status == "rejected"
            backup = self._apply(
                "backup",
                AccountExecutionRequest(action="backup", backup_root=str(self.output / "backup")),
            )
            assert backup.recovery is not None
            restored_root = self.output / "restored"
            restored = self._apply(
                "restore",
                AccountExecutionRequest(
                    action="restore",
                    backup_root=str(self.output / "backup"),
                    restore_root=str(restored_root),
                    manifest_sha256=backup.recovery.manifest_sha256,
                ),
            )
            assert restored.orders == pending.orders and restored.net_orders == pending.net_orders
            assert restored.accounts == pending.accounts
            assert restored.alerts == fault.alerts
            self.journal_path = restored_root / "state/accounts.sqlite3"
            self._apply(
                "cancelled",
                AccountExecutionRequest(
                    action="net_event",
                    net_event=OrderEvent(
                        identity="cancelled",
                        order_id=parent.identity,
                        at=self._at(9),
                        kind="cancelled",
                    ),
                ),
            )
            fill_ids = tuple(
                self.facts.allocated_fill_id("partial", child.order.identity)
                for child in admitted.orders
            )
            expected = self.facts.snapshot(
                instance_id=None,
                cash="49799.98",
                position="2",
                fees="0.02",
                transfers="50000",
                fill_ids=fill_ids,
                posting_ids=(
                    f"opening:{self.facts.currency.code}",
                    *(posting for fill_id in fill_ids for posting in (fill_id, f"fee:{fill_id}")),
                ),
            )
            assert self._apply(
                "fresh-reconciliation",
                AccountExecutionRequest(
                    action="reconcile",
                    observation=AccountObservation(
                        identity="fresh", at=self._at(10), snapshot=expected, open_orders=()
                    ),
                ),
            ).reconciled
            self._quote(10)
            resumed = self._control("restart", "restart", 10, expected="feed-fault")
            assert resumed.control is not None and resumed.control.status == "applied"
            assert resumed.accounts[0].phase == "running"
            duplicate = self._apply(
                "old-fill-retry", AccountExecutionRequest(action="net_event", net_event=fill)
            )
            assert duplicate.accounts == resumed.accounts
            self._backup_failures(restored_root)
            evidence = self._fault_drills(address, receiver)
            lost_alert = self._control(
                "operator-stop", "stop", 15, alert=str(Path(temporary) / "missing.sock")
            )
            assert lost_alert.alerts[-1].status == "failed"
            assert lost_alert.accounts[0].phase == "stopped"
            assert lost_alert.accounts[0].ledger == resumed.accounts[0].ledger
        dashboard = self._monitor()
        summary: dict[str, object] = {
            "qualification": "local-paper-fixture",
            "venue_label": self.venue,
            "physical_venue_evidence": False,
            "submission_attempted": False,
            "cash": "49799.98",
            "position": "2",
            "fees": "0.02",
            "active_strategies": ["inventory-target", "limit-order"],
            "restored_cancel_pending_quantity": "2",
            "duplicate_fill_preserved": True,
            "backup_manifest_sha256": backup.recovery.manifest_sha256,
            "alert_delivery": ["delivered", "failed"],
            "fault_drills": evidence,
            "installed_implementation": ImplementationIdentity.sha256(),
            "dashboard_identity": dashboard.identity,
            "monitoring_preserved_account": True,
        }
        (self.output / "summary.json").write_bytes(self.codec.encode_json(summary))

    def _monitor(self) -> DashboardSnapshot:
        """Run the installed retained dashboard command over actual account observations."""
        now = datetime.now(UTC)
        query = MonitoringQuery(
            scope="account:shared",
            mode="paper",
            start=self.monitoring_started_at,
            end=now,
            as_of=now,
        )
        events = TelemetryStore(self.output / "monitoring.sqlite").query(query)
        config = MonitoringConfiguration.defaults(query, events)
        risk = next(metric for metric in config.metrics if metric.name == "risk.blocked")
        config = replace(
            config,
            dashboard=replace(
                config.dashboard,
                alerts=(
                    AlertRule(
                        identity="blocked-account",
                        metric_identity=risk.identity,
                        operator=">",
                        threshold=ExactRatio(numerator="0", denominator="1"),
                        units="boolean",
                        address="/private/tmp/mr12-absent.sock",
                    ),
                ),
            ),
        )
        config_path = self.output / "monitoring-configuration.json"
        config_path.write_bytes(self.codec.encode_json(config))
        before = AccountJournal(self.journal_path, self.config).accounts()
        command = [
            str(Path(sys.executable).parent / "alpha-execute"),
            "monitor",
            "--config",
            str(config_path),
            "--journal",
            str(self.output / "monitoring.sqlite"),
            "--output",
            str(self.output / "dashboard"),
            "--alerts",
            str(self.output / "alerts.sqlite"),
        ]
        for _ in range(2):
            result = subprocess.run(
                command, cwd=self.output, capture_output=True, check=False, timeout=30
            )
            assert result.returncode == 0, result.stderr
        snapshot = DashboardSnapshot.read(self.output / "dashboard")
        values = {result.spec.name: result.value for result in snapshot.results}
        assert values["risk.blocked"] == ExactRatio(numerator="1", denominator="1")
        assert values[f"account.cash.{self.facts.currency.code}"] == ExactRatio(
            numerator="2489999", denominator="50"
        )
        assert snapshot.alert_results[0].delivery is not None
        assert snapshot.alert_results[0].delivery.status == "failed"
        assert AccountJournal(self.journal_path, self.config).accounts() == before
        return snapshot

    def _backup_failures(self, restored_root: Path) -> None:
        """Reject running state, incompatible config and a reused restore destination."""
        workspace = AccountWorkspace(
            self.config, component="state", journal_name="accounts.sqlite3"
        )
        try:
            workspace.backup(restored_root, self.output / "running-backup")
        except ValueError as error:
            assert "stopped" in str(error)
        else:
            raise AssertionError("running account was backed up")
        incompatible = AccountWorkspace(
            replace(self.config, mode="shadow"), component="state", journal_name="accounts.sqlite3"
        )
        try:
            incompatible.restore(
                self.output / "backup",
                self.output / "bad-restore",
                expected_manifest_sha256="0" * 64,
            )
        except ValueError as error:
            assert "configuration" in str(error)
        else:
            raise AssertionError("incompatible account snapshot was restored")
        assert not (self.output / "bad-restore").exists()

    def _fault_drills(self, address: str, receiver: socket.socket) -> list[dict[str, object]]:
        """Use real child loss and bounded SQLite exhaustion before local alert delivery."""
        outcomes: list[dict[str, object]] = []
        for index, mode in enumerate(("process", "storage")):
            root = self.output / f"fault-{mode}"
            root.mkdir()
            journal = AccountJournal(self.journal_path, self.config)
            policy = HealthPolicy(
                heartbeat_seconds=5,
                progress_seconds=5,
                freshness_seconds=5,
                max_queue=8,
                max_reconnects=0,
                max_invalid=0,
                alert_socket=address,
            )
            result = ProcessSupervisor.run(
                root,
                policy,
                _FailureWorkload(self.config, self.journal_path, mode),
                duration_seconds=5,
                label="paper-account",
                implementation_identity=ImplementationIdentity.sha256(),
                protect=_AccountFailureResponse(journal, self._at(13 + index)),
            )
            assert result["stop_reason"] == (
                "collector_lost" if mode == "process" else "persistence_failed"
            )
            assert result["protection_applied"] is True and result["collector_stopped"] is True
            assert result["alert_delivered"] is True
            assert b"paper-account" in receiver.recv(1024)
            assert AccountJournal(self.journal_path, self.config).accounts()[0].phase == "faulted"
            outcomes.append(result)
        return outcomes


def main() -> None:
    """Select the retained local workload and execute its installed command sequence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venue", choices=("okx", "bitfinex"), required=True)
    options = parser.parse_args()
    output: object = options.output
    venue: object = options.venue
    if not isinstance(output, Path) or venue not in ("okx", "bitfinex"):
        raise ValueError("invalid workload selection")
    AccountOperationsConsumer(output, "okx" if venue == "okx" else "bitfinex").run()


if __name__ == "__main__":
    main()
