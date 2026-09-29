"""Verify local account controls preserve exact state and fenced recovery."""

from __future__ import annotations

# standard library imports
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountSnapshot
from applications.execute.accounts import AccountExecutionApplication, AccountExecutionRequest
from configuration import AccountConfiguration, OpeningAccount
from execution import (
    AccountControl,
    AccountControlKind,
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    ExecutionMonitoring,
    OrderDecision,
    OrderEvent,
    OrderState,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent
from telemetry import MonitoringQuery
from telemetry.store import TelemetryStore


class TestAccountOperations:
    """Exercise two independent paper accounts and durable control retries."""

    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _at(cls, seconds: int) -> datetime:
        """Use an explicit monotonic fixture clock."""
        return cls.opening_at + timedelta(seconds=seconds)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Create exact valuation-currency cash."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Create exact base-unit size."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls) -> Price:
        """Create the independent spot quote used by both accounts."""
        return Price(value=Decimal("100"), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Give each instance its own cash account and 15,000 exposure cap."""
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(
                OpeningAccount(account_id="east", cash=(cls._money("20000"),)),
                OpeningAccount(account_id="west", cash=(cls._money("20000"),)),
            ),
            instruments=(
                SpotLimits(
                    maximum=cls._quantity("200"),
                    lot=cls._quantity("1"),
                    tick=Price(value=Decimal("0.01"), currency=cls.currency, per=cls.dimension),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("40000"),
                accounts=(
                    AccountLimit(account_id="east", maximum=cls._money("20000")),
                    AccountLimit(account_id="west", maximum=cls._money("20000")),
                ),
                instances=(
                    InstanceLimit(
                        instance_id="east-strategy",
                        account_id="east",
                        maximum=cls._money("15000"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                    InstanceLimit(
                        instance_id="west-strategy",
                        account_id="west",
                        maximum=cls._money("15000"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=60_000_000,
                max_state_age_us=60_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("15000"),
            ),
        )

    @classmethod
    def _opening_snapshot(cls, account_id: str) -> AccountSnapshot:
        """Supply ledger facts independent of the journal under test."""
        return AccountSnapshot(
            account_id=account_id,
            instance_id=None,
            cash=(cls._money("20000"),),
            positions=(),
            fees=(cls._money("0"),),
            rebates=(cls._money("0"),),
            transfers=(cls._money("20000"),),
            fill_ids=(),
            posting_ids=("opening:USDT",),
        )

    @classmethod
    def _observe_account(
        cls,
        journal: AccountJournal,
        account_id: str,
        identity: str,
        at: datetime,
        open_orders: tuple[OrderState, ...] = (),
    ) -> bool:
        """Reconcile a complete externally expected cash and open-order view."""
        return journal.reconcile(
            AccountObservation(
                identity=identity,
                at=at,
                snapshot=cls._opening_snapshot(account_id),
                open_orders=open_orders,
            )
        )

    @classmethod
    def _ready(cls, path: Path) -> AccountJournal:
        """Start both accounts from independently reconciled opening facts."""
        journal = AccountJournal(path, cls._config())
        for account_id in ("east", "west"):
            assert cls._observe_account(journal, account_id, f"opening:{account_id}", cls._at(1))
        journal.observe(AccountQuote(price=cls._price(), at=cls._at(2)))
        for account_id in ("east", "west"):
            result = journal.control(
                AccountControl(
                    identity=f"startup:{account_id}",
                    account_id=account_id,
                    kind="startup",
                    at=cls._at(3),
                )
            )
            assert result.status == "applied"
            assert result.recovery_generation == 1
        return journal

    @classmethod
    def _decision(cls, account_id: str, identity: str, at: datetime) -> AccountDecision:
        """Create one attributable pending buy with a candidate checkpoint."""
        return AccountDecision(
            account_id=account_id,
            instance_id=f"{account_id}-strategy",
            decision=OrderDecision(
                identity=identity,
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=cls._quantity("2"),
                    limit=cls._price(),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=cls._price(), at=cls._at(2)),
            maximum_fee=cls._money("1"),
            checkpoint=f"checkpoint:{identity}".encode(),
        )

    @staticmethod
    def _control(
        identity: str,
        account_id: str,
        kind: AccountControlKind,
        at: datetime,
        *,
        reason: str = "",
        expected: str | None = None,
    ) -> AccountControl:
        """Build a typed operation request for one account."""
        return AccountControl(
            identity=identity,
            account_id=account_id,
            kind=kind,
            at=at,
            reason=reason,
            expected_control_identity=expected,
        )

    def test_stop_preserves_pending_state_and_isolates_other_account(self, tmp_path: Path) -> None:
        """Stop one account without losing its reservations or the other account's access."""
        path = tmp_path / "accounts.sqlite3"
        first = self._ready(path)
        pending = first.admit(self._decision("east", "east-buy", self._at(4)))
        assert pending.status == "committed"
        order = pending.orders[0]
        second = AccountJournal(path, self._config())
        request = self._control("stop-east", "east", "stop", self._at(5), reason="operator stop")
        result = second.control(request)
        assert result.status == "applied"
        assert second.control(request) == result
        assert first.controls("east")[-1] == result
        assert first.orders()[0].order == order
        assert first.checkpoint("east-strategy") == b"checkpoint:east-buy"
        assert (
            next(
                account for account in first.accounts() if account.ledger.account_id == "east"
            ).phase
            == "stopped"
        )
        rejected = first.admit(self._decision("east", "east-after-stop", self._at(6)))
        assert rejected.status == "rejected"
        assert rejected.reason == "account_operationally_blocked"
        west = first.admit(self._decision("west", "west-buy", self._at(6)))
        assert west.status == "committed"
        assert len(first.orders()) == 2
        assert len(AccountJournal.verify(path, self._config())) == 2

    def test_cancel_ack_retains_exposure_until_terminal_fact_and_reconciliation(
        self, tmp_path: Path
    ) -> None:
        """A local cancel request and its acknowledgement never release the buy reserve."""
        journal = self._ready(tmp_path / "cancel.sqlite3")
        order = journal.admit(self._decision("east", "pending-buy", self._at(4))).orders[0]
        stop = journal.control(
            self._control("stop", "east", "stop", self._at(5), reason="risk hold")
        )
        assert stop.status == "applied"
        cancel = journal.control(self._control("cancel", "east", "cancel", self._at(6)))
        assert cancel.cancel_order_ids == (order.identity,)
        assert journal.orders()[0].order.status == "cancel_requested"
        acknowledged = journal.apply_event(
            OrderEvent(
                identity="cancel-ack", order_id=order.identity, at=self._at(7), kind="cancel_ack"
            )
        )
        assert acknowledged.status == "cancel_ack"
        assert acknowledged.remaining == order.remaining
        assert self._observe_account(
            journal, "east", "cancel-observation", self._at(8), (acknowledged,)
        )
        journal.observe(AccountQuote(price=self._price(), at=self._at(8)))
        blocked = journal.control(
            self._control("early-restart", "east", "restart", self._at(9), expected="stop")
        )
        assert blocked.status == "rejected"
        assert blocked.reason == "account_recovery_has_unresolved_order_outcome"
        assert journal.orders()[0].order.remaining == order.remaining
        terminal = journal.apply_event(
            OrderEvent(
                identity="cancel-confirmed",
                order_id=order.identity,
                at=self._at(10),
                kind="cancelled",
            )
        )
        assert terminal.status == "cancelled"
        assert self._observe_account(journal, "east", "terminal-observation", self._at(11))
        journal.observe(AccountQuote(price=self._price(), at=self._at(11)))
        restarted = journal.control(
            self._control("restart", "east", "restart", self._at(12), expected="stop")
        )
        assert restarted.status == "applied"
        assert restarted.recovery_generation == 2
        assert journal.orders()[0].order.status == "cancelled"
        assert journal.accounts()[0].phase == "running"

    def test_newer_stop_fences_stale_restart_and_repeated_identity(self, tmp_path: Path) -> None:
        """An old recovery compare cannot clear a later operator stop."""
        path = tmp_path / "stale.sqlite3"
        journal = self._ready(path)
        first = self._control("stop-one", "east", "stop", self._at(4), reason="first")
        assert journal.control(first).status == "applied"
        assert self._observe_account(journal, "east", "after-first", self._at(5))
        second = self._control("stop-two", "east", "stop", self._at(6), reason="second")
        assert journal.control(second).status == "applied"
        assert self._observe_account(journal, "east", "after-second", self._at(7))
        journal.observe(AccountQuote(price=self._price(), at=self._at(7)))
        reopened = AccountJournal(path, self._config())
        stale = reopened.control(
            self._control("stale-restart", "east", "restart", self._at(8), expected="stop-one")
        )
        assert stale.status == "rejected"
        assert stale.reason == "stale_account_restart_control"
        stale_startup = reopened.control(
            self._control("stale-startup", "east", "startup", self._at(8))
        )
        assert stale_startup.status == "rejected"
        assert stale_startup.reason == "startup_requires_unused_account_controls"
        assert reopened.accounts()[0].active_control_identity == "stop-two"
        assert (
            reopened.control(
                self._control("fresh-restart", "east", "restart", self._at(8), expected="stop-two")
            ).status
            == "applied"
        )
        with pytest.raises(ValueError, match="identity reused with different content"):
            journal.control(replace(first, reason="changed retry bytes"))
        assert len(reopened.controls("east")) == 6

    def test_unknown_send_survives_fault_cancel_and_reopen(self, tmp_path: Path) -> None:
        """Requesting a cancel cannot turn an uncertain send into a known outcome."""
        path = tmp_path / "unknown.sqlite3"
        journal = self._ready(path)
        order = journal.admit(self._decision("east", "uncertain-buy", self._at(4))).orders[0]
        journal.apply_event(
            OrderEvent(identity="lost-ack", order_id=order.identity, at=self._at(5), kind="unknown")
        )
        journal.control(
            self._control("fault", "east", "fault", self._at(6), reason="submission timeout")
        )
        cancelled = journal.control(self._control("cancel", "east", "cancel", self._at(7)))
        assert cancelled.cancel_order_ids == (order.identity,)
        reopened = AccountJournal(path, self._config())
        pending = reopened.orders()[0].order
        assert pending.status == "unknown"
        assert pending.cancel_requested
        assert pending.remaining == order.remaining
        assert not self._observe_account(
            reopened, "east", "uncertain-observation", self._at(8), (pending,)
        )
        recovered_open = reopened.apply_event(
            OrderEvent(
                identity="recovered-open",
                order_id=order.identity,
                at=self._at(9),
                kind="reconcile_open",
            )
        )
        assert recovered_open.status == "cancel_requested"
        assert self._observe_account(
            reopened, "east", "recovered-open-observation", self._at(10), (recovered_open,)
        )
        reopened.observe(AccountQuote(price=self._price(), at=self._at(10)))
        still_blocked = reopened.control(
            self._control(
                "pending-cancel-restart", "east", "restart", self._at(11), expected="fault"
            )
        )
        assert still_blocked.reason == "account_recovery_has_unresolved_order_outcome"
        assert reopened.orders()[0].order.remaining == order.remaining

    def test_fault_requires_fresh_quote_state_and_permanent_block_remains(
        self, tmp_path: Path
    ) -> None:
        """A matched snapshot alone cannot bypass stale inputs or permanent operator blocks."""
        journal = self._ready(tmp_path / "fault.sqlite3")
        assert (
            journal.control(
                self._control("fault", "east", "fault", self._at(4), reason="feed disconnected")
            ).status
            == "applied"
        )
        assert self._observe_account(journal, "east", "fault-observation", self._at(5))
        stale_quote = journal.control(
            self._control("stale-quote", "east", "restart", self._at(70), expected="fault")
        )
        assert stale_quote.status == "rejected"
        assert stale_quote.reason == "account_recovery_requires_fresh_reconciliation"
        assert self._observe_account(journal, "east", "fresh-state", self._at(69))
        stale_quote = journal.control(
            self._control("stale-quote-two", "east", "restart", self._at(70), expected="fault")
        )
        assert stale_quote.status == "rejected"
        assert stale_quote.reason == "account_recovery_requires_fresh_quote"
        journal.observe(AccountQuote(price=self._price(), at=self._at(69)))
        journal.block("east", "permanent block")
        blocked = journal.control(
            self._control("block-bypass", "east", "restart", self._at(70), expected="fault")
        )
        assert blocked.status == "rejected"
        assert blocked.reason == "account_blocked"
        assert journal.accounts()[0].phase == "faulted"

    def test_portfolio_and_reissue_follow_account_phase(self, tmp_path: Path) -> None:
        """Portfolio admission and reissue obey the same account stop as direct admission."""
        journal = self._ready(tmp_path / "portfolio.sqlite3")
        journal.control(self._control("stop", "east", "stop", self._at(4), reason="operator"))
        decision = self._decision("east", "portfolio-buy", self._at(5))
        batch = PortfolioBatch(
            identity="blocked-batch",
            at=self._at(6),
            decisions=(
                PortfolioDecision(
                    request=decision,
                    context=PortfolioContext(
                        portfolio_id="paper-portfolio",
                        strategy_id="east-strategy",
                        model_revision="model-1",
                        config_revision="config-1",
                        horizon="one-minute",
                        reason="paper-order",
                        venue="OKX",
                        settlement="spot-immediate",
                        risk_bucket="spot",
                        authority_scope="paper",
                    ),
                ),
            ),
        )
        result = journal.coordinate(batch)
        assert result.status == "rejected"
        assert result.reason == "account_operationally_blocked"
        with pytest.raises(ValueError, match="account_not_reconciled"):
            journal.reissue_pending("east", self._at(6))
        assert journal.net_orders() == ()

    def test_control_clocks_inputs_and_schema_verification(self, tmp_path: Path) -> None:
        """Malformed controls and unknown journal versions fail before state is trusted."""
        path = tmp_path / "schema.sqlite3"
        journal = self._ready(path)
        regressed = journal.control(
            self._control("old-stop", "east", "stop", self._at(2), reason="old clock")
        )
        assert regressed.status == "rejected"
        assert regressed.reason == "account_control_clock_regressed"
        assert journal.accounts()[0].phase == "running"
        with pytest.raises(ValueError, match="invalid account control"):
            self._control("bad", "east", "stop", self._at(4))
        with pytest.raises(ValueError, match="invalid account control"):
            self._control("bad", "east", "restart", self._at(4))
        with pytest.raises(TypeError, match="timezone-aware"):
            self._control("bad", "east", "cancel", datetime(2026, 9, 25, 12))
        with pytest.raises(ValueError, match="account journal is missing"):
            AccountJournal.verify(tmp_path / "missing.sqlite3", self._config())
        invalid = tmp_path / "invalid.sqlite3"
        invalid.write_bytes(b"not a SQLite database")
        with pytest.raises(ValueError, match="not a valid SQLite database"):
            AccountJournal.verify(invalid, self._config())
        assert invalid.read_bytes() == b"not a SQLite database"
        wrong = replace(self._config(), opening_at=self.opening_at - timedelta(seconds=1))
        with pytest.raises(ValueError, match="configuration or state schema differs"):
            AccountJournal.verify(path, wrong)
        assert len(AccountJournal.verify(path, self._config())) == 2
        with closing(sqlite3.connect(path)) as connection:
            row = cast(
                "tuple[bytes]", connection.execute("SELECT payload FROM firm WHERE id=1").fetchone()
            )
            unknown = row[0].replace(
                b'"schema_version":"account-journal-v4"',
                b'"schema_version":"unknown-account-journal"',
            )
            assert unknown != row[0]
            connection.execute("UPDATE firm SET payload=? WHERE id=1", (unknown,))
            connection.commit()
        with pytest.raises(ValueError):
            AccountJournal(path, self._config())
        with pytest.raises(ValueError):
            AccountJournal.verify(path, self._config())

    def test_snapshot_verification_is_immutable_and_live_verify_reads_wal(
        self, tmp_path: Path
    ) -> None:
        """Read live committed WAL facts and leave a standalone backup byte-identical."""
        live_path = tmp_path / "live.sqlite3"
        snapshot_path = tmp_path / "snapshot.sqlite3"
        journal = self._ready(live_path)
        with closing(sqlite3.connect(live_path)) as guard:
            guard.execute("PRAGMA wal_autocheckpoint=0")
            guard.execute("BEGIN")
            row = cast(
                "tuple[object, ...] | None",
                guard.execute("SELECT payload FROM firm WHERE id=1").fetchone(),
            )
            assert row is not None
            stopped = journal.control(
                self._control("backup-stop", "east", "stop", self._at(4), reason="backup")
            )
            assert stopped.status == "applied"
            assert live_path.with_name(f"{live_path.name}-wal").is_file()
            assert AccountJournal.verify(live_path, self._config())[0].phase == "stopped"
            with pytest.raises(ValueError, match="SQLite sidecars"):
                AccountJournal.verify(live_path, self._config(), storage="snapshot")
            with closing(sqlite3.connect(live_path)) as source:
                with closing(sqlite3.connect(snapshot_path)) as copy:
                    source.backup(copy)
        before = {
            item.name: item.read_bytes()
            for item in tmp_path.iterdir()
            if item.name.startswith(snapshot_path.name)
        }
        assert set(before) == {snapshot_path.name}
        assert (
            AccountJournal.verify(snapshot_path, self._config(), storage="snapshot")[0].phase
            == "stopped"
        )
        after = {
            item.name: item.read_bytes()
            for item in tmp_path.iterdir()
            if item.name.startswith(snapshot_path.name)
        }
        assert after == before
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = snapshot_path.with_name(f"{snapshot_path.name}{suffix}")
            sidecar.write_bytes(b"unexpected")
            with pytest.raises(ValueError, match="SQLite sidecars"):
                AccountJournal.verify(snapshot_path, self._config(), storage="snapshot")
            sidecar.unlink()

    def test_monitoring_observes_exact_balances_and_isolated_account_stop(
        self, tmp_path: Path
    ) -> None:
        """A stopped account is visible while its peer remains open and funded."""
        journal = self._ready(tmp_path / "accounts.sqlite3")
        journal.control(self._control("stop:east", "east", "stop", self._at(4), reason="operator"))
        events = ExecutionMonitoring("a" * 64).account(
            journal, observed_at=self._at(5), sample="snapshot-one"
        )
        values = {(event.context.account, event.name, event.units): event.value for event in events}
        assert values[("east", "risk.blocked", "boolean")] == ExactRatio(
            numerator="1", denominator="1"
        )
        assert values[("west", "risk.blocked", "boolean")] == ExactRatio(
            numerator="0", denominator="1"
        )
        assert values[("east", "account.cash.USDT", "USDT")] == ExactRatio(
            numerator="20000", denominator="1"
        )
        assert values[("west", "account.cash.USDT", "USDT")] == ExactRatio(
            numerator="20000", denominator="1"
        )
        assert TelemetryStore(tmp_path / "monitor.sqlite3").append(events) == len(events)

    def test_telemetry_identity_binds_to_application_lifetime(self, tmp_path: Path) -> None:
        """Repeated operations retain one fingerprint; a new application binds afresh."""
        journal_path = tmp_path / "accounts.sqlite3"
        self._ready(journal_path)
        codec = DomainCodec()
        config_path, request_path = tmp_path / "config.json", tmp_path / "request.json"
        config_path.write_bytes(codec.encode_json(self._config()))
        request_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="control",
                    control=self._control(
                        "stop:east", "east", "stop", self._at(4), reason="operator"
                    ),
                )
            )
        )
        application = AccountExecutionApplication()
        with patch(
            "applications.execute.accounts.InstalledIdentity.sha256",
            side_effect=("a" * 64, "b" * 64),
        ) as fingerprint:
            for index, current in enumerate(
                (application, application, AccountExecutionApplication())
            ):
                telemetry_path = tmp_path / f"monitor-{index}.sqlite3"
                result = current.run(
                    config_path=config_path,
                    journal_path=journal_path,
                    request_path=request_path,
                    telemetry_path=telemetry_path,
                )
                assert result.control is not None and result.control.status == "applied"
                assert result.telemetry_error is None
                cutoff = datetime.now(UTC)
                events = TelemetryStore(telemetry_path).query(
                    MonitoringQuery(
                        scope="account:east",
                        mode="paper",
                        start=self.opening_at,
                        end=cutoff,
                        as_of=cutoff,
                    )
                )
                assert events
                assert {event.context.release for event in events} == {
                    ("a" if index < 2 else "b") * 64
                }
            assert fingerprint.call_count == 2

    def test_telemetry_storage_failure_cannot_undo_applied_stop(self, tmp_path: Path) -> None:
        """An unusable monitor path is reported after the account stop commits."""
        journal_path = tmp_path / "accounts.sqlite3"
        self._ready(journal_path)
        codec = DomainCodec()
        config_path, request_path = tmp_path / "config.json", tmp_path / "request.json"
        config_path.write_bytes(codec.encode_json(self._config()))
        request_path.write_bytes(
            codec.encode_json(
                AccountExecutionRequest(
                    action="control",
                    control=self._control(
                        "stop:east", "east", "stop", self._at(4), reason="operator"
                    ),
                )
            )
        )
        with patch("applications.execute.accounts.InstalledIdentity.sha256", return_value="a" * 64):
            result = AccountExecutionApplication().run(
                config_path=config_path,
                journal_path=journal_path,
                request_path=request_path,
                telemetry_path=tmp_path,
            )
        assert result.control is not None and result.control.status == "applied"
        assert result.telemetry_error == "OperationalError"
        assert AccountJournal(journal_path, self._config()).accounts()[0].phase == "stopped"
