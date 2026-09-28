"""Retain current service economics through existing exact reports and telemetry."""

from __future__ import annotations

# standard library imports
import hashlib
import math
import multiprocessing
import os
import signal
import time
from datetime import UTC, datetime, timedelta
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Literal
from uuid import uuid4

# third party library imports
import msgspec

# project library imports
from accounting import (
    AccountLedger,
    AttributedPaperFill,
    PaperAccountReporter,
    PaperCostEvidence,
    PaperCurrencyResult,
    PaperGasPolicy,
    PaperPositionMark,
    PaperScopeReport,
)
from configuration import AccountConfiguration, PaperServiceConfiguration, PaperServiceSource
from execution import (
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountPaperTrace,
    AccountView,
    ExecutionMonitoring,
    NetOrder,
    PaperActivation,
    PaperMarket,
    PaperMonitoring,
    PaperOwner,
    PaperReductionResult,
    SocketPaperAccount,
    TaggedOrder,
)
from serialization import DomainCodec, WireRecord
from telemetry import TelemetryStore


class _ReadOnlyPaperAccount(SocketPaperAccount):
    """Restrict the diagnostics process to installed account inspection."""

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Reject economic and lifecycle commands before retaining or sending bytes."""
        request.__post_init__()
        if request.action != "inspect":
            raise ValueError("service diagnostics can only inspect accounts")
        return super().execute(request)


class _AccountDiagnosticSample(WireRecord, frozen=True):
    """Carry the latest observed marks for one separately bound account report."""

    account_id: str
    markets: tuple[PaperMarket, ...]


class _DiagnosticBatch(WireRecord, frozen=True):
    """Name one replaceable diagnostic request without economic commands."""

    sequence: int
    requested_at: datetime
    accounts: tuple[_AccountDiagnosticSample, ...]

    def __post_init__(self) -> None:
        """Require one finite, uniquely scoped report request with its actual UTC clock."""
        self._require_utc(self.requested_at, field_name="diagnostic request")
        if (
            type(self.sequence) is not int
            or self.sequence < 1
            or type(self.accounts) is not tuple
            or not 1 <= len(self.accounts) <= 4
            or len({sample.account_id for sample in self.accounts}) != len(self.accounts)
        ):
            raise ValueError("invalid bounded diagnostic batch")


class _DiagnosticReceipt(WireRecord, frozen=True):
    """Preserve report wire fields without repeating domain reconstruction in the supervisor."""

    account_id: str
    requested_at: datetime
    observed_at: datetime
    status: Literal["retained", "failed", "cancelled"]
    phase: Literal["running", "stopped", "faulted"] | None = None
    account: msgspec.Raw = msgspec.Raw(b"null")
    activation: msgspec.Raw = msgspec.Raw(b"null")
    report: msgspec.Raw = msgspec.Raw(b"null")
    instances: msgspec.Raw = msgspec.Raw(b"null")
    snapshot_path: str | None = None
    error: str | None = None


class _DiagnosticState(WireRecord, frozen=True):
    """Retain child lifetime, bounded work counts and its latest independently timed receipts."""

    pid: int
    started_at: datetime
    observed_at: datetime
    active_sequence: int | None
    completed_sequence: int
    completed_batches: int
    coalesced_batches: int
    failures: int
    receipts: tuple[_DiagnosticReceipt, ...]


class PaperServiceDiagnostics:
    """Run full diagnostic reports in one finite, read-only spawned process.

    An atomic request file holds only the latest pending batch. The child owns
    one current batch and retains every actual receipt; overwritten requests are
    counted as coalesced diagnostics. Native deliveries and economic work never
    use this replaceable channel.
    """

    def __init__(
        self,
        configuration: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        *,
        root: Path,
        deadline: float,
    ) -> None:
        """Bind immutable account definitions, diagnostic storage and the supervisor deadline."""
        configuration.__post_init__()
        if (
            not root.is_absolute()
            or not math.isfinite(deadline)
            or not time.monotonic() < deadline <= time.monotonic() + configuration.duration_seconds
            or len(owners) != len(configuration.accounts)
            or {owner.account_id for owner in owners}
            != {account.account_id for account in configuration.accounts}
        ):
            raise ValueError("diagnostics require the current bounded supervisor envelope")
        for owner in owners:
            owner.__post_init__()
        self.configuration, self.owners, self.root, self.deadline = (
            configuration,
            owners,
            root,
            deadline,
        )
        self._codec = DomainCodec()
        self._process: BaseProcess | None = None
        self._stop: Event | None = None
        self._submitted = 0
        self._received_sequence = 0
        self._state: _DiagnosticState | None = None
        self.started_at: datetime | None = None
        self.exit_observed_at: datetime | None = None
        self.failures = 0
        self.last_error: str | None = None
        self._lost = False
        self._is_stopping = False
        self._forced_fence = False
        self._exit_failure_recorded = False

    def start(self) -> None:
        """Launch exactly one process whose account clients accept inspection only."""
        if self._process is not None:
            raise RuntimeError("service diagnostics already started")
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("diagnostic-request.json", "diagnostic-state.json"):
            (self.root / name).unlink(missing_ok=True)
        context = multiprocessing.get_context("spawn")
        self._stop = context.Event()
        self._process = context.Process(
            target=self._serve,
            args=(self.configuration, self.owners, self.root, self.deadline, self._stop),
            name="paper-service-diagnostics",
        )
        self.started_at = datetime.now(UTC)
        try:
            self._process.start()
        except BaseException:
            self._process = None
            raise

    def submit(self, markets: dict[str, tuple[PaperMarket, ...]]) -> None:
        """Replace the latest pending report without waiting for the current report."""
        if self._is_stopping or self._lost:
            return
        self._submitted += 1
        batch = _DiagnosticBatch(
            sequence=self._submitted,
            requested_at=datetime.now(UTC),
            accounts=tuple(
                _AccountDiagnosticSample(account_id=account_id, markets=values)
                for account_id, values in sorted(markets.items())
            ),
        )
        try:
            self._replace(self.root / "diagnostic-request.json", self._codec.encode_json(batch))
        except OSError as error:
            self.failures += 1
            self.last_error = f"diagnostic_request:{type(error).__name__}"

    def poll(self) -> tuple[_DiagnosticReceipt, ...]:
        """Read completed compact receipts and expose a lost child without retrying it."""
        self._refresh_state()
        latest = self._state
        if latest is None or latest.completed_sequence <= self._received_sequence:
            return ()
        self._received_sequence = latest.completed_sequence
        return latest.receipts

    def _refresh_state(self) -> None:
        """Read the latest whole child state without consuming report receipts."""
        path = self.root / "diagnostic-state.json"
        try:
            state = self._codec.decode_json(path.read_bytes(), _DiagnosticState)
            if self._process is None or state.pid != self._process.pid:
                raise ValueError("diagnostic state differs from its child")
            self._state = state
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            self.failures += 1
            self.last_error = f"diagnostic_state:{type(error).__name__}"
        process = self._process
        if process is not None and not process.is_alive():
            if self.exit_observed_at is None:
                self.exit_observed_at = datetime.now(UTC)
            fenced = self._forced_fence and process.exitcode in (-signal.SIGTERM, -signal.SIGKILL)
            if not self._exit_failure_recorded and (
                fenced or process.exitcode != 0 or not self._is_stopping
            ):
                self._exit_failure_recorded = True
                self._lost = not fenced
                self.failures += 1
                self.last_error = (
                    "diagnostic_forced_fence"
                    if fenced
                    else f"diagnostic_process_exit:{process.exitcode}"
                )

    def request_stop(self) -> None:
        """Stop accepting diagnostic work while source delivery drains independently."""
        self._is_stopping = True
        if self._stop is not None:
            self._stop.set()

    def close(self, *, deadline: float) -> None:
        """Join or fence the sole diagnostic child within the shared shutdown deadline."""
        self.request_stop()
        process = self._process
        if process is None:
            return
        process.join(max(0.0, min(2.0, deadline - time.monotonic() - 0.4)))
        if process.is_alive():
            self._forced_fence = True
            process.terminate()
            process.join(max(0.0, min(0.2, deadline - time.monotonic())))
        if process.is_alive():
            process.kill()
            process.join(max(0.0, min(0.2, deadline - time.monotonic())))
        if process.is_alive():
            raise RuntimeError("diagnostic process could not be fenced before deadline")
        self.exit_observed_at = datetime.now(UTC)
        self._refresh_state()

    def status(self) -> dict[str, object]:
        """Expose child lifetime and bounded diagnostic work for cleanup audits."""
        process, state = self._process, self._state
        completed = 0 if state is None else state.completed_sequence
        active = 0 if state is None or state.active_sequence is None else state.active_sequence
        unstarted = max(0, self._submitted - max(active, completed))
        return {
            "pid": None if process is None else process.pid,
            "alive": process is not None and process.is_alive(),
            "exitcode": None if process is None else process.exitcode,
            "started_at": self.started_at,
            "exit_observed_at": self.exit_observed_at,
            "submitted_batches": self._submitted,
            "active_sequence": None if state is None else state.active_sequence,
            "completed_sequence": completed,
            "completed_batches": 0 if state is None else state.completed_batches,
            "coalesced_batches": (0 if state is None else state.coalesced_batches)
            + max(0, unstarted - 1),
            "pending_batches": int(unstarted > 0 and not self._is_stopping),
            "pending_discarded_at_stop": int(unstarted > 0 and self._is_stopping),
            "forced_fence": self._forced_fence,
            "abandoned_sequence": active if active and (self._forced_fence or self._lost) else None,
            "failures": self.failure_count,
            "last_error": self.last_error,
        }

    @property
    def failure_count(self) -> int:
        """Count local diagnostic failures and actual child report failures once."""
        return self.failures + (0 if self._state is None else self._state.failures)

    @staticmethod
    def _replace(path: Path, payload: bytes) -> None:
        """Publish one whole diagnostic value without exposing a partial file."""
        temporary = path.with_name(f".{path.name}")
        temporary.write_bytes(payload)
        temporary.replace(path)

    @classmethod
    def _serve(
        cls,
        configuration: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        root: Path,
        deadline: float,
        stopped: Event,
    ) -> None:
        """Consume the latest batch with read-only clients and retain actual report receipts."""
        codec, monitor = DomainCodec(), PaperServiceMonitor(root)
        accounts = {
            definition.account_id: _ReadOnlyPaperAccount(
                config=definition.configuration,
                socket_path=Path(definition.socket_path),
                requests=root / "requests" / definition.account_id,
                paper_owner=next(
                    owner for owner in owners if owner.account_id == definition.account_id
                ),
                timeout_seconds=2.0,
            )
            for definition in configuration.accounts
        }
        sources = {
            account_id: tuple(
                source
                for source in configuration.sources
                if any(
                    instance.source == source.name and instance.account_id == account_id
                    for instance in configuration.instances
                )
            )
            for account_id in accounts
        }
        started = datetime.now(UTC)
        completed = completed_batches = coalesced = 0
        receipts: tuple[_DiagnosticReceipt, ...] = ()
        while not stopped.is_set() and time.monotonic() < deadline:
            try:
                batch = codec.decode_json(
                    (root / "diagnostic-request.json").read_bytes(), _DiagnosticBatch
                )
            except FileNotFoundError:
                stopped.wait(min(0.05, max(0.0, deadline - time.monotonic())))
                continue
            if batch.sequence <= completed:
                stopped.wait(min(0.05, max(0.0, deadline - time.monotonic())))
                continue
            if {item.account_id for item in batch.accounts} != set(accounts):
                raise ValueError("diagnostic request differs from configured accounts")
            coalesced += batch.sequence - completed - 1
            cls._replace(
                root / "diagnostic-state.json",
                codec.encode_json(
                    _DiagnosticState(
                        pid=os.getpid(),
                        started_at=started,
                        observed_at=datetime.now(UTC),
                        active_sequence=batch.sequence,
                        completed_sequence=completed,
                        completed_batches=completed_batches,
                        coalesced_batches=coalesced,
                        failures=monitor.failures,
                        receipts=receipts,
                    )
                ),
            )
            outcomes: list[_DiagnosticReceipt] = []
            for sample in batch.accounts:
                if stopped.is_set() or time.monotonic() >= deadline:
                    outcomes.append(
                        _DiagnosticReceipt(
                            account_id=sample.account_id,
                            requested_at=batch.requested_at,
                            observed_at=datetime.now(UTC),
                            status="cancelled",
                            error="bounded_shutdown",
                        )
                    )
                    continue
                account = accounts[sample.account_id]
                account.timeout_seconds = min(2.0, max(0.001, deadline - time.monotonic()))
                result = monitor.sample(account, sources[sample.account_id], sample.markets)
                observed_at, phase = result["observed_at"], result.get("phase")
                if not isinstance(observed_at, datetime):
                    raise ValueError("diagnostic result lacks its actual receipt clock")
                outcomes.append(
                    _DiagnosticReceipt(
                        account_id=sample.account_id,
                        requested_at=batch.requested_at,
                        observed_at=observed_at,
                        status="retained" if result["status"] == "retained" else "failed",
                        phase=phase if phase in ("running", "stopped", "faulted") else None,
                        account=msgspec.Raw(codec.encode_json(result["account"]))
                        if "account" in result
                        else msgspec.Raw(b"null"),
                        activation=msgspec.Raw(codec.encode_json(result["activation"]))
                        if "activation" in result
                        else msgspec.Raw(b"null"),
                        report=msgspec.Raw(codec.encode_json(result["report"]))
                        if "report" in result
                        else msgspec.Raw(b"null"),
                        instances=msgspec.Raw(codec.encode_json(result["instances"]))
                        if "instances" in result
                        else msgspec.Raw(b"null"),
                        snapshot_path=str(root / f"{sample.account_id}.json")
                        if result["status"] == "retained"
                        else None,
                        error=str(result["error"]) if "error" in result else None,
                    )
                )
            receipts = tuple(outcomes)
            completed, completed_batches = batch.sequence, completed_batches + 1
            state = _DiagnosticState(
                pid=os.getpid(),
                started_at=started,
                observed_at=datetime.now(UTC),
                active_sequence=None,
                completed_sequence=completed,
                completed_batches=completed_batches,
                coalesced_batches=coalesced,
                failures=monitor.failures,
                receipts=receipts,
            )
            with (root / "diagnostic-events.jsonl").open("ab") as stream:
                stream.write(codec.encode_json(state) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            cls._replace(root / "diagnostic-state.json", codec.encode_json(state))


class _InspectedPaperAccount(SocketPaperAccount):
    """Serve monitoring reads from one immutable installed account inspection."""

    def __init__(
        self, config: AccountConfiguration, owner: PaperOwner, state: AccountExecutionResult
    ) -> None:
        """Retain only the definition and inspected result; no transport is available."""
        self.config = config
        self.paper_owner = owner
        self._state = state

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Refuse any command, including another diagnostic read."""
        raise RuntimeError("monitoring snapshot cannot execute account commands")

    def accounts(self) -> tuple[AccountView, ...]:
        """Return the account views from the same inspection."""
        return self._state.accounts

    def orders(self) -> tuple[TaggedOrder, ...]:
        """Return attributable orders from the same inspection."""
        return self._state.orders

    def net_orders(self) -> tuple[NetOrder, ...]:
        """Return physical orders from the same inspection."""
        return self._state.net_orders

    def paper_restore_quarantined(self) -> bool:
        """Return the inspected restore quarantine signal."""
        return self._state.paper_restore_quarantined

    def paper_activations(self) -> tuple[PaperActivation, ...]:
        """Return inspected deployment and authority records."""
        return self._state.paper_activations

    def paper_reductions(self) -> tuple[PaperReductionResult, ...]:
        """Return the inspected reduction outcomes."""
        return self._state.paper_reductions

    def paper_traces(self, account_id: str | None = None) -> tuple[AccountPaperTrace, ...]:
        """Keep trace reads within the inspected account scope."""
        return tuple(
            trace
            for trace in self._state.paper_traces
            if account_id is None or trace.account_id == account_id
        )


class PaperServiceMonitor:
    """Observe committed state without retrying economic work after diagnostic failure."""

    def __init__(self, root: Path) -> None:
        """Bind separate diagnostic storage with no authority to alter accounts."""
        self.root = root
        self.codec = DomainCodec()
        self.failures = 0
        self.last_error: str | None = None

    @staticmethod
    def _unposted_scope(ledger: AccountLedger, instance_id: str) -> PaperScopeReport:
        """Expose a configured instance with no postings as a validated zero scope."""
        snapshot = ledger.snapshot(instance_id)
        if (
            snapshot.positions
            or snapshot.fill_ids
            or snapshot.posting_ids
            or any(
                amount.value != 0
                for amounts in (
                    snapshot.cash,
                    snapshot.fees,
                    snapshot.rebates,
                    snapshot.transfers,
                )
                for amount in amounts
            )
        ):
            raise ValueError("unreported instance has account postings")
        return PaperScopeReport(
            snapshot=snapshot,
            positions=(),
            currencies=tuple(
                PaperCurrencyResult(
                    currency=cash.currency,
                    position_value=cash - cash,
                    nav=cash,
                    net_pnl=cash - cash,
                    slippage=cash - cash,
                )
                for cash in snapshot.cash
            ),
        )

    def sample(
        self,
        account: SocketPaperAccount,
        sources: tuple[PaperServiceSource, ...],
        markets: tuple[PaperMarket, ...],
    ) -> dict[str, object]:
        """Retain one independently timestamped account/strategy snapshot and telemetry.

        Diagnostic errors return visible status. Neither a failed report nor a
        failed telemetry write repeats a decision, matching operation or control.
        """
        observed = datetime.now(UTC)
        try:
            owner = account.paper_owner
            if owner is None:
                raise ValueError("monitoring requires an identified account owner")
            state = account.execute(
                AccountExecutionRequest(action="inspect", account_id=owner.account_id)
            )
            view = next(
                item for item in state.accounts if item.ledger.account_id == owner.account_id
            )
            cutoff = datetime.now(UTC)
            ledger = AccountLedger(view.ledger)
            open_dimensions = {position.dimension for position in ledger.snapshot().positions}
            report = PaperAccountReporter().build(
                view.ledger,
                cutoff=cutoff,
                max_mark_age=timedelta(microseconds=min(item.freshness_us for item in sources)),
                marks=tuple(
                    PaperPositionMark(identity=item.identity, available_at=item.at, price=item.bid)
                    for item in markets
                    if item.bid.per in open_dimensions
                ),
                fills=tuple(
                    AttributedPaperFill(
                        instance_id=item.instance_id, order_id=item.order_id, fill=item.fill
                    )
                    for item in state.paper_fills
                ),
                costs=tuple(
                    PaperCostEvidence(
                        source_fill_id=item.source_fill_id,
                        posting_id=item.posting_id,
                        amount=item.amount,
                    )
                    for item in state.paper_costs
                ),
                gas_policy=PaperGasPolicy(
                    scenario_id=hashlib.sha256(
                        self.codec.encode_json(tuple(item.scenario for item in sources))
                    ).hexdigest(),
                    applicable=False,
                    reason="; ".join(
                        sorted({item.scenario.gas_inapplicable_reason for item in sources})
                    ),
                ),
            )
            reported = {scope.snapshot.instance_id: scope for scope in report.instances}
            instances: tuple[dict[str, object], ...] = tuple(
                {
                    "instance_id": limit.instance_id,
                    "scope": reported.get(limit.instance_id)
                    or self._unposted_scope(ledger, limit.instance_id),
                    "orders": owned_orders,
                    "reservations": tuple(
                        item for item in owned_orders if not item.order.is_terminal
                    ),
                    "residuals": tuple(
                        item
                        for item in state.residuals
                        if item.account_id == owner.account_id
                        and item.instance_id == limit.instance_id
                    ),
                    "stopped": limit.instance_id in state.stopped_instances,
                }
                for limit in account.config.budgets.instances
                if limit.account_id == owner.account_id
                for owned_orders in (
                    tuple(
                        item
                        for item in state.orders
                        if item.account_id == owner.account_id
                        and item.instance_id == limit.instance_id
                    ),
                )
            )
            activation = next(
                (
                    item
                    for item in state.paper_activations
                    if item.deployment.account_id == owner.account_id
                ),
                None,
            )
            receipt = datetime.now(UTC)
            inspected = _InspectedPaperAccount(account.config, owner, state)
            events = (
                PaperMonitoring(owner.release_identity).account(
                    inspected,
                    account_id=owner.account_id,
                    observed_at=receipt,
                    sample=uuid4().hex,
                    report=report,
                )
                if account.config.mode == "paper"
                else ExecutionMonitoring(owner.release_identity).account(
                    inspected,
                    observed_at=receipt,
                    sample=uuid4().hex,
                )
            )
            snapshot: dict[str, object] = {
                "observed_at": receipt,
                "account": state,
                "account_view": view,
                "activation": activation,
                "report": report,
                "instances": instances,
                "heartbeat_is_freshness": False,
            }
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.root / f".{owner.account_id}.json"
            temporary.write_bytes(self.codec.encode_json(snapshot))
            temporary.replace(self.root / f"{owner.account_id}.json")
            TelemetryStore(self.root / "telemetry.sqlite3").append(events)
            return {
                "observed_at": receipt,
                "report": report,
                "account": view,
                "activation": activation,
                "instances": instances,
                "phase": view.phase,
                "status": "retained",
            }
        except Exception as error:
            self.failures += 1
            self.last_error = f"{type(error).__name__}: {error}"
            return {"observed_at": observed, "status": "failed", "error": self.last_error}
