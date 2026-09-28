"""Verify concurrent owner preparation and eight-instance recovery evidence."""

from __future__ import annotations

# standard library imports
import hashlib
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast
from unittest.mock import patch

# third party library imports
import msgspec
import pytest
from capacity_inputs import CapacityWorkload
from capacity_recovery import CapacityRecovery, _RetainedRequest
from capacity_trial import CapacityTrial, _Child, _Status

# project library imports
from accounting import AccountPosting, Fill
from configuration import PaperServiceAccount
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountPaperCost,
    AccountPaperFill,
    AccountPaperTrace,
    InstalledPaperAccount,
    NetAllocation,
    NetOrder,
    OrderState,
    PaperLiquidityState,
    PaperMarket,
    PaperOwner,
    PaperTouchLiquidity,
    SocketPaperAccount,
    TaggedOrder,
)
from financial_units import Money, Quantity
from portfolio import PortfolioContext
from serialization import DomainCodec
from strategies import OrderIntent


class _RetentionClient:
    """Complete one native trace between the probe's separate before snapshots."""

    def __init__(
        self,
        before: AccountExecutionResult,
        after: AccountExecutionResult,
        requests: Path,
        payload: bytes,
        *,
        late: bool,
        final_checkpoint: bytes,
    ) -> None:
        """Choose whether the exact request exists before obstruction or only after restore."""
        self.before, self.after = before, after
        self.requests, self.payload, self.late = requests, payload, late
        self.final_checkpoint = final_checkpoint
        self.inspections = self.checkpoints = 0

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Expose the actual before/after facts and an optional inadmissible late request."""
        assert request.action == "inspect"
        self.inspections += 1
        if self.inspections == 1:
            return self.before
        if self.late:
            (self.requests / "market.json").write_bytes(self.payload)
        return self.after

    def checkpoint(self, instance_id: str) -> bytes:
        """Admit a legitimate market in the inspect/checkpoint gap before the rename."""
        assert instance_id == "bitfinex-shared-fixed-btc"
        self.checkpoints += 1
        if self.checkpoints == 1:
            if not self.late:
                (self.requests / "market.json").write_bytes(self.payload)
            return b"old"
        return self.final_checkpoint


class _RetentionBoundary:
    """Confirm directory obstruction before exposing account-wide worker fencing."""

    def __init__(self, status: _Status, requests: Path) -> None:
        """Bind the initial supervisor status and the original retained directory path."""
        self.initial, self.requests = status, requests
        self.fenced = False

    def status(self) -> _Status:
        """Remove the failed worker only after the obstruction has been observed."""
        if not self.fenced:
            return self.initial
        return msgspec.structs.replace(
            self.initial, active=(), faulted_accounts=("bitfinex-shared",)
        )

    def wait_until(self, condition: Callable[[], bool], seconds: float) -> None:
        """Exercise the unchanged six-second condition without wall-clock waits."""
        assert seconds == 6
        assert self.requests.is_file()
        self.fenced = True
        assert condition()


class _CheckpointClient:
    """Expose controlled committed checkpoint reads for one signed account."""

    def __init__(self, checkpoints: dict[str, bytes | None]) -> None:
        """Retain exact per-instance checkpoint responses."""
        self.checkpoints = checkpoints

    def checkpoint(self, instance_id: str) -> bytes | None:
        """Return the current observed checkpoint for one instance."""
        return self.checkpoints[instance_id]


class _ParallelRecovery(CapacityRecovery):
    """Exercise independent account scheduling without installed CLI launches."""

    def __init__(self, trial: CapacityTrial) -> None:
        """Require all four owner tasks to overlap before any can complete."""
        super().__init__(trial)
        self.barrier = threading.Barrier(4)
        self.started: set[str] = set()

    def _recover_owner(self, account: PaperServiceAccount) -> None:
        """Wait for all owner preparations and retain the earliest claim clock."""
        self.barrier.wait(timeout=5)
        with self._claim_lock:
            self.started.add(account.account_id)
            started = time.monotonic()
            if self.first_claim_started_at is None:
                self.first_claim_started_at = started


class _ExitedSupervisor:
    """Expose one failed process exit after an acknowledged shutdown."""

    def wait(self, *, timeout: float) -> int:
        """Return the actual failure status within the unchanged lifetime bound."""
        assert 0 <= timeout <= 75
        return 1


class _FiniteLauncher:
    """Release an installation fence only when its finite process exit is awaited."""

    def __init__(self, name: str, pid: int, bound: int, events: list[str]) -> None:
        """Bind one observed launcher and the shared stop/read chronology."""
        self.name, self.pid, self.bound, self.events = name, pid, bound, events
        self.exited = False

    def wait(self, *, timeout: float) -> int:
        """Observe the clean exit within the caller's remaining finite deadline."""
        assert 0 <= timeout <= self.bound
        self.events.append(f"wait:{self.name}")
        self.exited = True
        return 0


class _OfflineAccount:
    """Read controlled stopped facts after the signed launcher releases its fence."""

    def __init__(self, name: str, result: AccountExecutionResult, events: list[str]) -> None:
        """Bind immutable account facts and retained read chronology."""
        self.name, self.result, self.events = name, result, events

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Allow only the read-only account inspection used for retained evidence."""
        assert request.action == "inspect" and request.account_id == self.name
        self.events.append(f"inspect:{self.name}")
        return self.result

    def checkpoint(self, instance_id: str) -> bytes:
        """Expose an unchanged committed continuation without touching authority."""
        return instance_id.encode()


class _ShutdownBoundary:
    """Reject offline reads while any owned installation remains fenced."""

    def __init__(
        self,
        launchers: tuple[_FiniteLauncher, ...],
        accounts: dict[str, _OfflineAccount],
        events: list[str],
    ) -> None:
        """Bind all four launchers and their subsequent read-only account clients."""
        self.launchers, self.accounts, self.events = launchers, accounts, events

    def control(
        self, action: Literal["inspect", "shutdown", "restart_source"], subject: str | None = None
    ) -> None:
        """Acknowledge shutdown before any process wait or expensive account read."""
        assert action == "shutdown" and subject is None
        self.events.append("shutdown")

    def admin(self, account_id: str) -> InstalledPaperAccount:
        """Represent the installation runner's nonblocking exclusive fence."""
        if not all(launcher.exited for launcher in self.launchers):
            raise RuntimeError("installation remains fenced by an account launcher")
        return cast(InstalledPaperAccount, self.accounts[account_id])


class TestCapacityRecovery:
    """Protect the fixed first-claim clock and complete progress witness."""

    @staticmethod
    def _retention_case(
        tmp_path: Path, *, late: bool = False, final_checkpoint: bytes = b"old"
    ) -> tuple[CapacityRecovery, _RetentionClient, _RetentionBoundary]:
        """Build a validated no-fill native append on an isolated unmanaged account."""
        config = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-retention-test"),
        ).service_configuration()
        account = next(item for item in config.accounts if item.account_id == "bitfinex-shared")
        source = next(item for item in config.sources if item.name == "bitfinex-btc-book")
        price = source.scenario.adverse.model_copy(update={"value": Decimal("104")})
        bid = price.model_copy(update={"value": Decimal("99")})
        displayed = Quantity(value=Decimal("4"), dimension=price.per)
        zero = displayed.model_copy(update={"value": Decimal("0")})
        market = PaperMarket(
            identity="native-market",
            at=config.accounts[0].configuration.opening_at + timedelta(seconds=43),
            bid=bid,
            ask=price,
            bid_quantity=displayed,
            ask_quantity=displayed,
        )
        trace = AccountPaperTrace(
            account_id=account.account_id,
            market=market,
            scenario=source.scenario,
            input_sha256=hashlib.sha256(
                DomainCodec().encode_json((account.account_id, market, source.scenario))
            ).hexdigest(),
            physical_events=(),
            child_fill_events=(),
            liquidity=PaperLiquidityState(
                bid=PaperTouchLiquidity(price=bid, displayed_peak=displayed, consumed=zero),
                ask=PaperTouchLiquidity(price=price, displayed_peak=displayed, consumed=zero),
                scenario_identity=source.scenario.identity,
                last_market_identity=market.identity,
                last_market_at=market.at,
            ),
        )
        journal_path = tmp_path / "accounts.sqlite3"
        before = AccountExecutionResult(
            accounts=AccountJournal(journal_path, account.configuration).accounts(),
            orders=(),
            journal_path=str(journal_path),
        )
        after = msgspec.structs.replace(before, paper_traces=(trace,))
        owner = PaperOwner(
            account_id=account.account_id,
            deployment_sha256="a" * 64,
            authorization_id="reference-grant",
            release_identity="b" * 64,
            owner_id="reference-owner",
            generation=1,
        )
        request = AccountExecutionRequest(
            action="paper_market",
            account_id=account.account_id,
            market=market,
            scenario=source.scenario,
            paper_owner=owner,
            projection="operation",
        )
        requests = tmp_path / "service-requests"
        requests.mkdir()
        client = _RetentionClient(
            before,
            after,
            requests,
            DomainCodec().encode_json(request),
            late=late,
            final_checkpoint=final_checkpoint,
        )
        status = _Status(
            active=("bitfinex-shared-fixed-btc",),
            workers={"bitfinex-shared-fixed-btc": _Child(pid=123, alive=True)},
            sources={},
            faulted_accounts=(),
            stopping=False,
        )
        trial = object.__new__(CapacityTrial)
        trial.config, trial.output, trial.codec = config, tmp_path, DomainCodec()
        trial.clients = {account.account_id: cast(SocketPaperAccount, client)}
        return CapacityRecovery(trial), client, _RetentionBoundary(status, requests)

    def test_retention_allows_only_pre_obstruction_attributed_native_trace(
        self, tmp_path: Path
    ) -> None:
        """A retained native commit in the inspect/checkpoint gap is not an unretained effect."""
        recovery, client, boundary = self._retention_case(tmp_path)
        with (
            patch.object(CapacityTrial, "status", side_effect=boundary.status),
            patch.object(CapacityTrial, "wait_until", side_effect=boundary.wait_until),
            patch.object(CapacityRecovery, "_alive", return_value=False),
        ):
            assert (
                recovery.request_retention_failure("bitfinex-shared", "bitfinex-shared-fixed-btc")
                <= 6
            )
        assert client.inspections == client.checkpoints == 2
        assert client.requests.is_dir()
        witness = msgspec.json.decode(
            (tmp_path / "request-retention-bitfinex-shared-witness.json").read_bytes(),
            type=dict[str, object],
        )
        assert witness["passed"] is True
        assert witness["trace_prefix_equal"] is True
        comparisons = cast(dict[str, dict[str, object]], witness["comparisons"])
        assert set(comparisons) == {
            "ledger",
            "orders",
            "net_orders",
            "paper_fills",
            "paper_costs",
            "checkpoint",
        }
        assert all(item["equal"] is True for item in comparisons.values())
        appends = cast(list[dict[str, object]], witness["appended_traces"])
        assert len(appends) == 1 and appends[0]["attributed"] is True
        frozen = cast(list[dict[str, object]], witness["frozen_requests"])
        assert frozen[0]["sha256"] == hashlib.sha256(client.payload).hexdigest()
        assert frozen[0]["stable_before_cutoff"] is True

    @pytest.mark.parametrize("failure", ("late_request", "checkpoint"))
    def test_retention_rejects_late_attribution_and_checkpoint_changes_with_witness(
        self, tmp_path: Path, failure: str
    ) -> None:
        """A post-restore file cannot authorize an append, and changed bytes remain retained."""
        recovery, client, boundary = self._retention_case(
            tmp_path,
            late=failure == "late_request",
            final_checkpoint=b"changed" if failure == "checkpoint" else b"old",
        )
        with (
            patch.object(CapacityTrial, "status", side_effect=boundary.status),
            patch.object(CapacityTrial, "wait_until", side_effect=boundary.wait_until),
            patch.object(CapacityRecovery, "_alive", return_value=False),
            pytest.raises(AssertionError, match="changed committed economics or policy checkpoint"),
        ):
            recovery.request_retention_failure("bitfinex-shared", "bitfinex-shared-fixed-btc")
        assert client.checkpoints == 2
        assert client.requests.is_dir()
        witness = msgspec.json.decode(
            (tmp_path / "request-retention-bitfinex-shared-witness.json").read_bytes(),
            type=dict[str, object],
        )
        assert witness["passed"] is False
        if failure == "late_request":
            assert witness["frozen_requests"] == []
            assert (client.requests / "market.json").is_file()
        else:
            checkpoint = cast(dict[str, dict[str, object]], witness["comparisons"])["checkpoint"]
            assert checkpoint["equal"] is False
            assert checkpoint["before_sha256"] == hashlib.sha256(b"old").hexdigest()
            assert checkpoint["after_sha256"] == hashlib.sha256(b"changed").hexdigest()

    @pytest.mark.parametrize("failure", ("malformed", "unstable", "duplicate", "prefix"))
    def test_retention_rejects_unproved_or_rewritten_trace_history(
        self, tmp_path: Path, failure: str
    ) -> None:
        """Exact input bytes, a stable cutoff, uniqueness and the entire old prefix are required."""
        recovery, client, _ = self._retention_case(tmp_path)
        frozen = (
            _RetainedRequest(
                name="market.json",
                payload=b'{"action":"paper_market"}' if failure == "malformed" else client.payload,
                modified_ns=1,
                stable_before_cutoff=failure != "unstable",
            ),
        )
        before, after = client.before, client.after
        if failure == "duplicate":
            after = msgspec.structs.replace(after, paper_traces=after.paper_traces * 2)
        if failure == "prefix":
            before, after = after, before
        passed, witness = recovery._request_retention_proof(
            "bitfinex-shared", before, after, b"old", b"old", frozen
        )
        assert not passed
        assert witness["before_traces"] == before.paper_traces
        assert witness["after_traces"] == after.paper_traces

    @pytest.mark.parametrize(
        "field", ("ledger", "orders", "net_orders", "paper_fills", "paper_costs")
    )
    def test_retention_keeps_every_economic_field_exact(self, tmp_path: Path, field: str) -> None:
        """An attributed no-fill append cannot excuse any simultaneous economic mutation."""
        recovery, client, _ = self._retention_case(tmp_path)
        trace = client.after.paper_traces[0]
        quantity = trace.market.ask_quantity.model_copy(update={"value": Decimal("1")})
        zero = quantity.model_copy(update={"value": Decimal("0")})
        fee = Money(value=Decimal("0"), currency=trace.market.ask.currency)
        order = OrderState(
            identity="unexpected-order",
            decision_identity="unexpected-decision",
            decision_at=trace.market.at,
            intent=OrderIntent(
                side="buy", quantity=quantity, limit=trace.market.ask, time_in_force="gtc"
            ),
            status="intent",
            filled=zero,
            paid_fee=fee,
            maximum_fee=fee,
        )
        after = client.after
        if field == "orders":
            after = msgspec.structs.replace(
                after,
                orders=(
                    TaggedOrder(account_id=trace.account_id, instance_id="fixed", order=order),
                ),
            )
        elif field == "net_orders":
            context = PortfolioContext(
                portfolio_id="reference",
                strategy_id="fixed",
                model_revision="rule",
                config_revision="reference",
                horizon="capture",
                reason="reference",
                venue="bitfinex",
                settlement="spot",
                risk_bucket="cash",
                authority_scope="paper",
            )
            after = msgspec.structs.replace(
                after,
                net_orders=(
                    NetOrder(
                        account_id=trace.account_id,
                        order=order,
                        allocations=(
                            NetAllocation(child_order_id="child", quantity=quantity, filled=zero),
                        ),
                        context=context,
                    ),
                ),
            )
        elif field == "paper_fills":
            fill = Fill(
                identity="unexpected-fill",
                decision_at=trace.market.at,
                filled_at=trace.market.at + timedelta(microseconds=1),
                quantity=quantity,
                reference=trace.market.ask,
                effective=trace.market.ask,
                fee=fee,
            )
            after = msgspec.structs.replace(
                after,
                paper_fills=(
                    AccountPaperFill(instance_id="fixed", order_id=order.identity, fill=fill),
                ),
            )
        elif field == "paper_costs":
            after = msgspec.structs.replace(
                after,
                paper_costs=(
                    AccountPaperCost(posting_id=None, source_fill_id="unexpected-fill", amount=fee),
                ),
            )
        else:
            posting = AccountPosting(
                identity="unexpected-transfer",
                account_id=trace.account_id,
                event_at=trace.market.at,
                known_at=trace.market.at,
                kind="transfer",
                cash=fee.model_copy(update={"value": Decimal("1")}),
            )
            view = after.accounts[0]
            postings: tuple[AccountPosting, ...] = (*view.ledger.postings, posting)
            ledger = msgspec.structs.replace(view.ledger, postings=postings)
            after = msgspec.structs.replace(
                after, accounts=(msgspec.structs.replace(view, ledger=ledger),)
            )
        frozen = (
            _RetainedRequest(
                name="market.json", payload=client.payload, modified_ns=1, stable_before_cutoff=True
            ),
        )
        passed, witness = recovery._request_retention_proof(
            "bitfinex-shared", client.before, after, b"old", b"old", frozen
        )
        assert not passed
        comparison = cast(dict[str, dict[str, object]], witness["comparisons"])[field]
        assert comparison["equal"] is False
        assert comparison["before_sha256"] != comparison["after_sha256"]
        assert comparison["after"] == recovery._request_retention_fields(after)[field]

    def test_status_tracks_diagnostic_child_for_cleanup(self, tmp_path: Path) -> None:
        """An extra read-only process remains owned if the supervisor exits unexpectedly."""
        trial = object.__new__(CapacityTrial)
        trial.service_root = tmp_path
        trial.child_pids = set()
        status = _Status(
            active=(),
            workers={"policy": _Child(pid=101, alive=True)},
            sources={"source": _Child(pid=102, alive=True)},
            faulted_accounts=(),
            stopping=False,
            diagnostics=_Child(pid=103, alive=True),
        )
        (tmp_path / "status.json").write_bytes(DomainCodec().encode_json(status))
        assert trial.status() == status
        assert trial.child_pids == {101, 102, 103}

    def test_failed_supervisor_exit_cannot_pass_shutdown(self) -> None:
        """A control acknowledgment must not hide the child's final failure status."""
        trial = object.__new__(CapacityTrial)
        trial.supervisor = cast(subprocess.Popen[bytes], _ExitedSupervisor())
        trial.supervisor_started_at = time.monotonic()
        trial.failures = []
        trial.config = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-recovery-test"),
        ).service_configuration()
        status = _Status(
            active=tuple(item.instance_id for item in trial.config.instances),
            workers={
                item.instance_id: _Child(pid=123, alive=True) for item in trial.config.instances
            },
            sources={item.name: _Child(pid=123, alive=True) for item in trial.config.sources},
            faulted_accounts=(),
            stopping=False,
        )
        with (
            patch.object(CapacityTrial, "status", return_value=status),
            patch.object(CapacityTrial, "record"),
            patch.object(CapacityTrial, "retain_accounts"),
            patch.object(CapacityTrial, "control"),
            pytest.raises(RuntimeError, match="supervisor exited with status 1"),
        ):
            trial.finish_interval()

    def test_post_shutdown_snapshots_wait_for_all_installation_fences(self, tmp_path: Path) -> None:
        """Stop before account reads and still reject unfilled facts against the oracle."""
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-recovery-test"),
        )
        config = workload.service_configuration()
        events: list[str] = []
        supervisor = _FiniteLauncher("supervisor", 100, 75, events)
        launchers = tuple(
            _FiniteLauncher(account.account_id, 101 + index, 120, events)
            for index, account in enumerate(config.accounts)
        )
        clients = {
            account.account_id: _OfflineAccount(
                account.account_id,
                AccountExecutionResult(
                    accounts=AccountJournal(
                        tmp_path / f"{account.account_id}.sqlite3", account.configuration
                    ).accounts(),
                    orders=(),
                ),
                events,
            )
            for account in config.accounts
        }
        boundary = _ShutdownBoundary(launchers, clients, events)
        trial = object.__new__(CapacityTrial)
        trial.config, trial.workload = config, workload
        trial.codec = DomainCodec()
        trial.output = trial.service_root = tmp_path
        trial.clients = {}
        trial.child_pids = set()
        trial.public_venue = None
        trial.failures = []
        trial.first_service_at = trial.supervisor_started_at = time.monotonic()
        trial.supervisor = cast(subprocess.Popen[bytes], supervisor)
        trial.processes = [
            *(cast(subprocess.Popen[bytes], launcher) for launcher in launchers),
            trial.supervisor,
        ]
        status = _Status(
            active=tuple(item.instance_id for item in config.instances),
            workers={item.instance_id: _Child(pid=123, alive=True) for item in config.instances},
            sources={item.name: _Child(pid=123, alive=True) for item in config.sources},
            faulted_accounts=(),
            stopping=False,
        )
        (tmp_path / "status.json").write_bytes(msgspec.json.encode(status))
        with (
            patch.object(CapacityTrial, "control", side_effect=boundary.control),
            patch.object(CapacityTrial, "admin", side_effect=boundary.admin),
        ):
            trial.finish_interval()
        assert events == [
            "shutdown",
            "wait:supervisor",
            *(f"wait:{account.account_id}" for account in config.accounts),
            *(f"inspect:{account.account_id}" for account in config.accounts),
        ]
        assert trial.failures == [
            f"independent first-touch economics differ: {account.account_id}"
            for account in config.accounts
        ]
        assert all(
            (tmp_path / f"post_shutdown-{account.account_id}.json").is_file()
            for account in config.accounts
        )

    def test_four_owner_preparation_runs_concurrently(self, tmp_path: Path) -> None:
        """Avoid serial owner preparation that already consumed the recovery budget."""
        config = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-recovery-test"),
        ).service_configuration()
        trial = object.__new__(CapacityTrial)
        trial.config = config
        trial.variant = "base"
        trial.public_venue = None
        trial.supervisor = None
        trial.output = tmp_path
        trial.codec = DomainCodec()
        recovery = _ParallelRecovery(trial)
        first_claim = recovery.recover_four_owners()
        assert recovery.started == {account.account_id for account in config.accounts}
        assert first_claim == recovery.first_claim_started_at
        assert recovery.operator_started_at is not None
        assert recovery.operator_started_at <= first_claim

    def test_progress_requires_eight_live_changed_checkpoints(self, tmp_path: Path) -> None:
        """An absent checkpoint or stopped worker cannot appear as a fresh advance."""
        config = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-recovery-test"),
        ).service_configuration()
        clients = {
            account.account_id: _CheckpointClient(
                {
                    item.instance_id: b"old"
                    for item in config.instances
                    if item.account_id == account.account_id
                }
            )
            for account in config.accounts
        }
        trial = object.__new__(CapacityTrial)
        trial.config = config
        trial.clients = cast(dict[str, SocketPaperAccount], clients)
        trial.child_pids = set()
        trial.service_root = tmp_path
        trial.replacement_checkpoints = {}
        recovery = CapacityRecovery(trial)
        recovery.before_checkpoints = {item.instance_id: b"old" for item in config.instances}
        workers = {item.instance_id: _Child(pid=123, alive=True) for item in config.instances}
        status = _Status(
            active=tuple(item.instance_id for item in config.instances),
            workers=workers,
            sources={item.name: _Child(pid=123, alive=True) for item in config.sources},
            faulted_accounts=(),
            stopping=False,
        )
        (tmp_path / "status.json").write_bytes(msgspec.json.encode(status))
        assert not trial._replacement_progressed(recovery)
        for client in clients.values():
            for instance_id in client.checkpoints:
                client.checkpoints[instance_id] = b"new"
        first = config.instances[0]
        clients[first.account_id].checkpoints[first.instance_id] = None
        assert not trial._replacement_progressed(recovery)
        clients[first.account_id].checkpoints[first.instance_id] = b"new"
        assert trial._replacement_progressed(recovery)
        assert set(trial.replacement_checkpoints) == {item.instance_id for item in config.instances}
        missing_sources: dict[str, _Child] = {}
        (tmp_path / "status.json").write_bytes(
            msgspec.json.encode(msgspec.structs.replace(status, sources=missing_sources))
        )
        assert not trial._replacement_progressed(recovery)
        stopped_workers: dict[str, _Child] = {
            **workers,
            first.instance_id: _Child(pid=123, alive=False),
        }
        (tmp_path / "status.json").write_bytes(
            msgspec.json.encode(msgspec.structs.replace(status, workers=stopped_workers))
        )
        assert not trial._replacement_progressed(recovery)
