"""Exercise local paper supervision failure paths without starting account services."""

from __future__ import annotations

# standard library imports
import asyncio
import concurrent.futures
import multiprocessing
import os
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

# third party library imports
import msgspec
import pytest
from msgspec import Raw
from msgspec.structs import force_setattr, replace

# project library imports
from accounting import AccountLedger, AccountPosting, AccountState, Fill, PaperAccountReport
from applications.collect import collect
from applications.execute.service_candidates import PaperServiceCandidates
from applications.execute.service_monitor import (
    DiagnosticReceipt,
    PaperServiceDiagnostics,
    PaperServiceMonitor,
    ReadOnlyPaperAccount,
)
from applications.execute.services import (
    AccountHealth,
    PaperServiceControl,
    PaperServiceOwners,
    PaperServices,
    SourceChild,
)
from applications.execute.source_service import ReceivedSourceDelivery, SourceDelivery
from configuration import (
    AccountConfiguration,
    CaptureConfig,
    OpeningAccount,
    PaperExecutionScenario,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
    PaperSourceChain,
    ReferenceCandidate,
)
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountObservation,
    AccountPaperCost,
    AccountPaperFill,
    AccountView,
    PaperMarket,
    PaperOwner,
    SocketPaperAccount,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueTransport
from market_data.books import BookAsOfIndex
from market_data.contracts import (
    BookObservation,
    CaptureRecord,
    CaptureRequest,
    CaptureRunRequest,
    FeedSocket,
    Level,
    Order,
    RecordingRequest,
)
from market_data.storage import CaptureRecording
from reference_data.instruments import InstrumentId
from research.observations import InputRequirement, LiveTradeDecisionSource, NumericField
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    CandidateProcessFailure,
    InstalledIdentity,
    PaperInputs,
    ProcessCandidateExecutor,
    SharedPaperCaptureObserver,
)
from serialization import DomainCodec
from telemetry import HealthMetric, HealthMetrics, RuntimeMeasurementJournal

# A short existing root keeps AF_UNIX paths in limits on macOS and Linux.
_SOCKET_ROOT = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"


class _Constant[T]:
    """Return one fixed value on every call, standing in for a zero-argument callable."""

    def __init__(self, value: T) -> None:
        """Bind the value to return."""
        self.value = value

    def __call__(self) -> T:
        """Return the bound value."""
        return self.value


class _ScriptedBookSocket:
    """Deliver one finite OKX public book script, then drop the connection."""

    def __init__(self, frames: tuple[bytes, ...], channel: str = "books") -> None:
        """Bind the exact native frames of one connection and its subscribed channel."""
        self.frames = iter(frames)
        self.channel = channel

    async def send(self, message: str) -> None:
        """Accept the selected public subscription."""
        assert f'"{self.channel}"' in message

    async def recv(self) -> bytes:
        """Return the next frame, or end the connection with a network error."""
        await asyncio.sleep(0)
        frame = next(self.frames, None)
        if frame is None:
            raise OSError("scripted public feed disconnect")
        return frame

    async def close(self) -> None:
        """Nothing external is held by the scripted socket."""


class _ReconnectingBookTransport(VenueTransport):
    """Drop the first public connection once, then serve a recovered session."""

    _ack = b'{"event":"subscribe","arg":{"channel":"books","instId":"BTC-USDT"}}'
    _snapshot = (
        b'{"arg":{"channel":"books","instId":"BTC-USDT"},"action":"snapshot","data":[{"pre'
        b'vSeqId":-1,"seqId":10,"asks":[["101","1","0","1"]],"bids":[["100","2","0","2"]]}'
        b"]}"
    )

    async def open(self, timeout: float) -> FeedSocket:
        """Serve the same synchronized session on every connection."""
        return _ScriptedBookSocket((self._ack, self._snapshot))


class _SpawnedBookTransport:
    """Serve the reconnecting script from a spawned source child, which must pickle it."""

    async def open(self, timeout: float) -> FeedSocket:
        """Serve the same synchronized session on every connection."""
        return _ScriptedBookSocket(
            (_ReconnectingBookTransport._ack, _ReconnectingBookTransport._snapshot)
        )

    def snapshot(self) -> bytes:
        """The OKX book feed carries its own snapshot."""
        raise AssertionError("OKX capture does not fetch a REST snapshot")


class _SpawnedTradesTransport:
    """Serve one acknowledged OKX trades session from a spawned source child."""

    _ack = b'{"event":"subscribe","arg":{"channel":"trades","instId":"BTC-USDT"}}'
    _push = (
        b'{"arg":{"channel":"trades","instId":"BTC-USDT"},"data":[{"instId":"BTC-USDT",'
        b'"tradeId":"5","ts":"1790164800100","px":"100","sz":"0.5","side":"buy","count":"1"}]}'
    )

    async def open(self, timeout: float) -> FeedSocket:
        """Serve the same acknowledged trade on every connection."""
        return _ScriptedBookSocket((self._ack, self._push), channel="trades")

    def snapshot(self) -> bytes:
        """The trades feed has no REST snapshot."""
        raise AssertionError("OKX trades capture does not fetch a snapshot")


class _TradeReadingCandidates(PaperServiceCandidates):
    """Resolve the configured candidates as if one also read the source's trade flow."""

    flow = InputRequirement(
        name="trades",
        family="trade",
        clock="event",
        field=NumericField(name="signed_flow", units="BTC"),
        max_age_us=10_000_000,
    )

    def feeds(self, source: PaperServiceSource) -> PaperInputs:
        """Add the trade field to the configured book fields."""
        return PaperInputs(
            (*self.requirements(source), self.flow), has_trades=source.trades is not None
        )


class _TradeObserver(SharedPaperCaptureObserver):
    """Hold only a retained live trade source, as a trade-reading service observer does."""

    def __init__(self, request: RecordingRequest, delivery_path: Path) -> None:
        """Bind a trade source for the feed's own recording without an account."""
        self.trades = LiveTradeDecisionSource(
            request,
            (_TradeReadingCandidates.flow,),
            tapes=BookAdapters.trades,
            history_capacity=10,
        )
        self.trades_delivered = 0
        self.trades_path = delivery_path.with_name(delivery_path.stem + ".trades.jsonl")
        self._trade_bytes, self._maximum_trade_bytes = 0, request.recording_max_bytes * 4
        self._codec = DomainCodec()
        self._clock = None
        self.index = None
        self.measurements = None


class _IndexedObserver(SharedPaperCaptureObserver):
    """Hold only a delivery as-of index, as a service observer does."""

    def __init__(self, index: BookAsOfIndex) -> None:
        """Bind the open index without public inputs or an account."""
        self.index = index
        self.measurements = None


class _AliveSource(multiprocessing.Process):
    """Represent a source that remains alive while one delivered frame fails."""

    def is_alive(self) -> bool:
        """Keep source loss separate from observer uncertainty."""
        return True


class _SourceReadinessProbe:
    """Record the bounded wait set without introducing wall-clock assertions."""

    def __init__(self) -> None:
        """Start with no observed receiver wait."""
        self.receivers: list[Connection[bytes, bytes] | socket.socket] = []
        self.timeout: float | None = None

    def __call__(
        self, receivers: list[Connection[bytes, bytes] | socket.socket], timeout: float
    ) -> list[Connection[bytes, bytes] | socket.socket]:
        """Expose ready pipes while retaining the actual wait deadline."""
        self.receivers, self.timeout = receivers, timeout
        return [
            receiver
            for receiver in receivers
            if not isinstance(receiver, socket.socket) and receiver.poll()
        ]


class _CompletionReadinessProbe(_SourceReadinessProbe):
    """Observe a real completion wake while unrelated source pipes remain idle."""

    def __init__(self) -> None:
        """Retain selector entry and its actual ready descriptors."""
        super().__init__()
        self.entered = threading.Event()
        self.ready: list[Connection[bytes, bytes] | socket.socket] = []

    def __call__(
        self, receivers: list[Connection[bytes, bytes] | socket.socket], timeout: float
    ) -> list[Connection[bytes, bytes] | socket.socket]:
        """Use a finite test gate while preserving the production wait-set/deadline evidence."""
        self.receivers, self.timeout = receivers, timeout
        self.entered.set()
        self.ready = cast(
            "list[Connection[bytes, bytes] | socket.socket]", wait(receivers, timeout=2)
        )
        return self.ready


class _ClosingSource(multiprocessing.Process):
    """Expose a source fence without launching an operating-system child."""

    def __init__(self, name: str, events: list[str]) -> None:
        """Bind one fake live process and shared shutdown order."""
        self.label, self.events, self.alive = name, events, True

    @property
    def pid(self) -> int:
        """Enter the production close path for an already started source."""
        return 12345

    def is_alive(self) -> bool:
        """Expose whether the source still requires fencing."""
        return self.alive

    def terminate(self) -> None:
        """Record the protective fence before evidence closure."""
        self.events.append(f"source:{self.label}")
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        """Model bounded acknowledgement of source exit."""


class _GracefulSource(multiprocessing.Process):
    """Finish cleanly after pipe EOF without requiring a termination signal."""

    def __init__(self, events: list[str]) -> None:
        """Retain source exit ordering against account stop."""
        self.events = events
        self.alive = True

    @property
    def pid(self) -> int:
        """Represent one launched cooperative source process."""
        return 12345

    @property
    def exitcode(self) -> int | None:
        """Expose zero only after a clean process join."""
        return None if self.alive else 0

    def is_alive(self) -> bool:
        """Remain in interpreter teardown until joined after pipe EOF."""
        return self.alive

    def terminate(self) -> None:
        """Fail if shutdown kills an already completed source pipe."""
        raise AssertionError("clean source should not be terminated")

    def join(self, timeout: float | None = None) -> None:
        """Record the bounded clean exit before account shutdown."""
        self.events.append("source:joined")
        self.alive = False


class _ClosingMeasurements(RuntimeMeasurementJournal):
    """Raise one fsync-like close error after the source was already fenced."""

    def __init__(self, name: str, events: list[str], *, fail: bool) -> None:
        """Bind the diagnostic close result without creating a file."""
        self.name, self.events, self.fail = name, events, fail

    def close(self) -> None:
        """Fail the first evidence flush while preserving later cleanup calls."""
        self.events.append(f"measurement:{self.name}")
        if self.fail:
            raise OSError("injected measurement fsync failure")


class _ClosingObserver(SharedPaperCaptureObserver):
    """Expose only the source cleanup fields of one account observer."""

    def __init__(self, measurements: RuntimeMeasurementJournal) -> None:
        """Bind optional evidence and a status-safe absent market."""
        self.measurements = measurements
        self.index = None
        self.last_market = None


class _ScriptedClock:
    """Return scripted monotonic seconds in order, then repeat the last value."""

    def __init__(self, values: tuple[float, ...]) -> None:
        """Keep the script and start at its first value."""
        self.values, self.index = values, 0

    def __call__(self) -> float:
        """Read the next scripted value."""
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class _ClosingWorker(ProcessCandidateExecutor):
    """Record a policy process fence after source evidence failure."""

    def __init__(self, events: list[str]) -> None:
        """Retain one close order without starting a process."""
        self.events = events
        self.health = HealthMetrics()

    @property
    def pid(self) -> int:
        """Identify the stopped policy child in status observations."""
        return 23456

    @property
    def is_alive(self) -> bool:
        """Expose a stable fake process for retained shutdown status."""
        return False

    def close(self) -> None:
        """Record that a worker still closes after measurement fsync fails."""
        self.events.append("worker")


class _ClosingAccount(SocketPaperAccount):
    """Record owner-service shutdown after all source and worker fences."""

    def __init__(self, events: list[str], account_id: str = "shared") -> None:
        """Avoid a socket while preserving the installed shutdown signature."""
        self.events = events
        self.account_id = account_id

    def shutdown(self, control: AccountControl) -> AccountExecutionResult:
        """Require the owned stop and retain its cleanup order."""
        assert control.kind == "stop" and control.account_id == self.account_id
        self.events.append("account")
        return AccountExecutionResult(accounts=(), orders=())


class _ChangingWorker(ProcessCandidateExecutor):
    """Die after the first liveness scan to expose the observer failure branch."""

    def __init__(self) -> None:
        """Supply only the child signals used by local supervision."""
        self.health = HealthMetrics()
        self.checks = 0
        self.closed = False

    @property
    def pid(self) -> int | None:
        """Identify the policy whose isolated call can fail during delivery."""
        return 123

    @property
    def is_alive(self) -> bool:
        """Appear alive at the first check and lost during delivery failure."""
        self.checks += 1
        return self.checks == 1

    def close(self) -> None:
        """Record selective fencing without spawning a process."""
        self.closed = True


class _StableWorker(ProcessCandidateExecutor):
    """Expose only the stable status signals of a selected policy process."""

    def __init__(self) -> None:
        """Avoid spawning a process for lifecycle control tests."""
        self.health = HealthMetrics()

    @property
    def pid(self) -> int | None:
        """Represent a selected process without an operating-system child."""
        return 123

    @property
    def is_alive(self) -> bool:
        """Keep status inspection independent of restart ordering."""
        return True

    def close(self) -> None:
        """Allow explicit selective fencing without any child."""


class _UncertainObserver(SharedPaperCaptureObserver):
    """Model an ambiguous account response after a persisted source delivery."""

    def __init__(self, *, policy_failure: bool = False) -> None:
        """Keep the selected input cohort visible to the supervisor."""
        self.active = ("first",)
        self.calls = 0
        self.policy_failure = policy_failure

    def _observe_validated(
        self, record: CaptureRecord, row: BookObservation, *, received_ns: int | None = None
    ) -> None:
        """Fail after receipt without claiming whether the account committed."""
        self.calls += 1
        if self.policy_failure:
            raise CandidateProcessFailure(123, "decision policy process unavailable")
        raise TimeoutError("account response uncertain")


class _SupervisorHarness(PaperServices):
    """Capture only protective routing while using the real serialized source pipe."""

    def __init__(
        self,
        config: PaperServiceConfiguration,
        owner: PaperOwner | tuple[PaperOwner, ...],
        root: Path,
        control_socket: Path,
        events: list[str] | None = None,
    ) -> None:
        """Bind local account clients without connecting to a service."""
        owners = (owner,) if isinstance(owner, PaperOwner) else owner
        super().__init__(config, owners, root=root, control_socket=control_socket)
        self.fault_calls: list[tuple[str, str]] = []
        self.stop_calls: list[tuple[str, str]] = []
        self.events = [] if events is None else events

    def _fault_account(self, account_id: str, reason: str, detail: str) -> None:
        """Record the required fail-closed account outcome without socket I/O."""
        self.fault_calls.append((account_id, reason))
        self.faulted_accounts.add(account_id)
        self.active.difference_update(
            name for name in tuple(self.active) if self.instances[name].account_id == account_id
        )

    def _stop_instance(self, name: str, reason: str) -> None:
        """Record selective worker fencing before account-wide uncertain failure."""
        self.stop_calls.append((name, reason))
        self.workers[name].close()
        self.active.discard(name)

    def _start_instance(self, name: str) -> None:
        """Record scheduler order after a successful account restart."""
        self.events.append(f"start:{name}")
        self.workers[name] = _StableWorker()

    def _refresh_observers(self, source_name: str) -> None:
        """Record cohort refresh after process selection."""
        self.events.append(f"refresh:{source_name}")


class _DrainingServices(_SupervisorHarness):
    """Record applied controls; no child or account remains to drain."""

    def __init__(
        self,
        config: PaperServiceConfiguration,
        owner: PaperOwner,
        root: Path,
        control_socket: Path,
    ) -> None:
        """Build the real supervisor, then leave nothing for shutdown to stop."""
        super().__init__(config, owner, root, control_socket)
        self.accounts = {}
        self.applied: list[str] = []

    def apply(self, control: PaperServiceControl) -> dict[str, object]:
        """Record the control and mark an operator shutdown as the real method does."""
        self.applied.append(control.action)
        if control.action == "shutdown":
            self.is_stopping = self.shutdown_requested = True
        return {"applied": control.action}

    def _write_status(self) -> None:
        """Keep the drain test independent of status files."""


class _ObservationGate(SharedPaperCaptureObserver):
    """Expose independent account progress and the exact per-source delivery order."""

    def __init__(
        self,
        name: str,
        events: list[str],
        release: threading.Event,
        *,
        barrier: threading.Barrier | None = None,
        error: Exception | None = None,
    ) -> None:
        """Bind a bounded callback gate without account transport or public I/O."""
        self.name, self.events, self.release = name, events, release
        self.barrier, self.error = barrier, error
        self.entered, self.finished = threading.Event(), threading.Event()
        self.positions: list[int] = []
        self.callback_threads: list[int] = []
        self.active = ()
        self.last_market = None
        self.measurements = None
        self.index = None

    def _observe_validated(
        self, record: CaptureRecord, row: BookObservation, *, received_ns: int | None = None
    ) -> None:
        """Require concurrent arrival where declared, then retain the completed native position."""
        self.events.append(f"observe:{self.name}:{row.position}")
        self.callback_threads.append(threading.get_ident())
        self.entered.set()
        try:
            if self.barrier is not None:
                self.barrier.wait(timeout=2)
            if not self.release.wait(2):
                raise TimeoutError("observation gate was not released")
            self.positions.append(row.position)
            if self.error is not None:
                raise self.error
        finally:
            self.events.append(f"finished:{self.name}:{row.position}")
            self.finished.set()


class _SupervisorPass:
    """Retain one supervisor call while callbacks wait at explicit test gates."""

    def __init__(self, services: PaperServices) -> None:
        """Own the completion and failure of one finite pass."""
        self.services = services
        self.entered = threading.Event()
        self.finished = threading.Event()
        self.error: BaseException | None = None
        self.thread_id: int | None = None

    def __call__(self) -> None:
        """Expose completion only after the production supervisor returned or failed."""
        self.thread_id = threading.get_ident()
        self.entered.set()
        try:
            self.services._supervise()
        except BaseException as error:
            self.error = error
        finally:
            self.finished.set()


class _SchedulingHarness(_SupervisorHarness):
    """Retain lifecycle ordering and the thread that fences an uncertain account."""

    def __init__(
        self,
        config: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        root: Path,
        control_socket: Path,
    ) -> None:
        """Bind the normal harness and record only lifecycle thread identities."""
        super().__init__(config, owners, root, control_socket)
        self.lifecycle_threads: list[int] = []

    def _fault_account(self, account_id: str, reason: str, detail: str) -> None:
        """Observe the protective account action before returning its normal harness outcome."""
        self.events.append(f"fault:{account_id}")
        self.lifecycle_threads.append(threading.get_ident())
        super()._fault_account(account_id, reason, detail)

    def _stop_instance(self, name: str, reason: str) -> None:
        """Observe selective fencing on the supervisor rather than a callback thread."""
        self.events.append(f"stop:{name}")
        self.lifecycle_threads.append(threading.get_ident())
        super()._stop_instance(name, reason)


class _LifecycleCall:
    """Retain one real lifecycle request while native observations remain gated."""

    def __init__(
        self,
        services: PaperServices,
        operation: Literal["control", "source_fault", "shutdown"],
        listener: socket.socket,
        events: list[str],
    ) -> None:
        """Bind one concrete request and own its completion or unexpected failure."""
        self.services, self.operation, self.listener, self.events = (
            services,
            operation,
            listener,
            events,
        )
        self.entered, self.finished = threading.Event(), threading.Event()
        self.error: BaseException | None = None

    def __call__(self) -> None:
        """Complete the request only after the production lifecycle boundary returns."""
        self.entered.set()
        try:
            if self.operation == "control":
                self.services.apply(PaperServiceControl(action="shutdown", identity="stop"))
            elif self.operation == "source_fault":
                self.services._fault_source("book", "operator_source_stop")
            else:
                self.services._shutdown(self.listener)
            self.events.append(f"lifecycle:{self.operation}")
        except BaseException as error:
            self.error = error
        finally:
            self.finished.set()


class _DiagnosticAccount(SocketPaperAccount):
    """Count read-only monitor requests that fail before a report exists."""

    def __init__(self, config: AccountConfiguration, owner: PaperOwner) -> None:
        """Expose only monitor prerequisites without an account socket."""
        self.config = config
        self.paper_owner = owner
        self.calls = 0

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Fail one read-only inspection with no automatic retry."""
        self.calls += 1
        raise TimeoutError("diagnostic read failed")


class _SnapshotAccount(SocketPaperAccount):
    """Expose one inspected result and record every attempted account request."""

    def __init__(
        self, config: AccountConfiguration, owner: PaperOwner, state: AccountExecutionResult
    ) -> None:
        """Avoid transport setup while retaining the exact account contract."""
        self.config = config
        self.paper_owner = owner
        self.state = state
        self.seen_requests: list[AccountExecutionRequest] = []

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Count any diagnostic or economic command sent by the monitor."""
        self.seen_requests.append(request)
        return self.state


class _DelayedDiagnostics(PaperServiceDiagnostics):
    """Hold reports at a process boundary while the supervisor continues protection."""

    @classmethod
    def _serve(
        cls,
        configuration: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        root: Path,
        deadline: float,
        stopped: Event,
        runs: Path,
        candidates: Path | None,
    ) -> None:
        """Wait for an explicit test release before using the production reporting loop."""
        (root / "diagnostic-ready").touch()
        while not (root / "allow-reports").exists():
            if stopped.wait(0.01) or time.monotonic() >= deadline:
                return
        super()._serve(configuration, owners, root, deadline, stopped, runs, candidates)


class _StalledDiagnostics(PaperServiceDiagnostics):
    """Model a report blocked beyond cooperative shutdown."""

    @classmethod
    def _serve(
        cls,
        configuration: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        root: Path,
        deadline: float,
        stopped: Event,
        runs: Path,
        candidates: Path | None,
    ) -> None:
        """Expose startup, then ignore the stop signal until the finite deadline."""
        (root / "diagnostic-ready").touch()
        time.sleep(max(0.0, deadline - time.monotonic()))


class _CrashAfterStopDiagnostics(PaperServiceDiagnostics):
    """Model a failed report retention after cooperative shutdown has been requested."""

    @classmethod
    def _serve(
        cls,
        configuration: PaperServiceConfiguration,
        owners: tuple[PaperOwner, ...],
        root: Path,
        deadline: float,
        stopped: Event,
        runs: Path,
        candidates: Path | None,
    ) -> None:
        """Expose startup, observe stop, and fail while retaining the last report."""
        (root / "diagnostic-ready").touch()
        stopped.wait(max(0.0, deadline - time.monotonic()))
        raise OSError("diagnostic final retention failed")


class _RestartAccount(SocketPaperAccount):
    """Record the actual typed reconciliation and restart command sequence."""

    def __init__(
        self,
        config: AccountConfiguration,
        owner: PaperOwner,
        events: list[str],
        *,
        accepts_observation: bool,
    ) -> None:
        """Keep independently configured accounts distinct without sockets."""
        self.config = config
        self.paper_owner = owner
        self._restart_owner = owner
        self.events = events
        self.accepts_observation = accepts_observation

    def reconcile(self, observation: AccountObservation) -> bool:
        """Preserve the read/compare boundary before restart and scheduling."""
        observation.__post_init__()
        self.events.append(f"{self._restart_owner.account_id}:reconcile")
        return self.accepts_observation

    def execute(self, request: AccountExecutionRequest) -> AccountExecutionResult:
        """Observe one guarded account command and its owner token."""
        request.__post_init__()
        assert request.paper_owner == self.paper_owner
        self.events.append(f"{self._restart_owner.account_id}:{request.action}")
        return AccountExecutionResult(accounts=(), orders=())


class TestPaperServices:
    """Keep service sockets, observations and diagnostics distinct from authority."""

    @staticmethod
    def _implementation_identity() -> str:
        """Bind one installed identity for isolated supervisor cleanup checks."""
        return "b" * 64

    @staticmethod
    def _socket_path() -> Path:
        """Stay below the platform's AF_UNIX pathname limit."""
        return Path(_SOCKET_ROOT) / f"ps-{uuid4().hex[:12]}.sock"

    @staticmethod
    def _config(socket_path: Path) -> PaperServiceConfiguration:
        """Provision one bounded account, source and selected policy."""
        capture = CaptureConfig.read(Path("configs/live/okx-btc-usdt.json"))
        currency = Currency.from_code("USDT")
        dimension = Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)
        cash = Money(value=Decimal("1000"), currency=currency)
        quantity = Quantity(value=Decimal("1"), dimension=dimension)
        price = Price(value=Decimal("0.01"), currency=currency, per=dimension)
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(maximum=quantity, lot=quantity, tick=price, product="spot"),
        )
        account = AccountConfiguration(
            mode="paper",
            opening_at=datetime(2026, 9, 27, tzinfo=UTC),
            accounts=(OpeningAccount(account_id="shared", cash=(cash,)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal("0.001")
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=currency,
                firm_maximum=cash,
                accounts=(AccountLimit(account_id="shared", maximum=cash),),
                instances=(
                    InstanceLimit(
                        instance_id="first",
                        account_id="shared",
                        maximum=cash,
                        instruments=(capture.instrument_id,),
                    ),
                ),
                max_quote_age_us=30_000_000,
                max_state_age_us=30_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cash,
            ),
        )
        source = PaperServiceSource(
            name="book",
            capture=capture,
            freshness_us=30_000_000,
            scenario=PaperExecutionScenario(
                venue="okx",
                instrument_id=capture.instrument_id,
                entry_delay_us=1000,
                cancel_delay_us=2000,
                adverse=price,
                fee_rate=Decimal("0.001"),
                take_fraction=Decimal("0.5"),
                gas_inapplicable_reason="Off-chain spot without transfers.",
            ),
        )
        return PaperServiceConfiguration(
            accounts=(
                PaperServiceAccount(
                    account_id="shared", configuration=account, socket_path=str(socket_path)
                ),
            ),
            sources=(source,),
            instances=(
                PaperServiceInstance(
                    instance_id="first",
                    account_id="shared",
                    source="book",
                    candidate=ReferenceCandidate(
                        formula="fixed_clip",
                        cadence_us=3_000_000,
                        starts_at=datetime(2026, 1, 1, tzinfo=UTC),
                    ),
                    quantity=quantity,
                    lot=quantity,
                    maximum_fee=Money(value=Decimal("1"), currency=currency),
                ),
            ),
            active=("first",),
            revision=1,
        )

    @classmethod
    def _two_account_config(cls) -> PaperServiceConfiguration:
        """Provision another journal on the same source to test account isolation."""
        original = cls._config(cls._socket_path())
        shared = original.accounts[0].configuration
        cash = shared.accounts[0].cash[0]
        budgets = shared.budgets
        spot_limits: tuple[SpotLimits, ...] = shared.instruments
        isolated = AccountConfiguration(
            mode=shared.mode,
            opening_at=shared.opening_at,
            accounts=(OpeningAccount(account_id="isolated", cash=(cash,)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal("0.001")
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=budgets.valuation_currency,
                firm_maximum=budgets.firm_maximum,
                accounts=(AccountLimit(account_id="isolated", maximum=cash),),
                instances=(
                    InstanceLimit(
                        instance_id="other",
                        account_id="isolated",
                        maximum=cash,
                        instruments=(original.sources[0].capture.instrument_id,),
                    ),
                ),
                max_quote_age_us=budgets.max_quote_age_us,
                max_state_age_us=budgets.max_state_age_us,
                max_residual_age_us=budgets.max_residual_age_us,
                max_price_deviation_bps=budgets.max_price_deviation_bps,
                max_order_notional=budgets.max_order_notional,
            ),
        )
        first = original.instances[0]
        return PaperServiceConfiguration(
            accounts=(
                *original.accounts,
                PaperServiceAccount(
                    account_id="isolated",
                    configuration=isolated,
                    socket_path=str(cls._socket_path()),
                ),
            ),
            instances=(
                *original.instances,
                PaperServiceInstance(
                    instance_id="other",
                    account_id="isolated",
                    source=first.source,
                    candidate=first.candidate,
                    quantity=first.quantity,
                    lot=first.lot,
                    maximum_fee=first.maximum_fee,
                ),
            ),
            sources=original.sources,
            active=("first", "other"),
            revision=original.revision,
        )

    @classmethod
    def _two_source_config(cls, *, shared: bool = False) -> PaperServiceConfiguration:
        """Bind distinct native instruments to either separate or one serialized owner."""
        config = cls._two_account_config()
        source = config.sources[0]
        capture = replace(
            source.capture,
            symbol="ETH-USDT",
            base_currency="ETH",
            instrument_id=InstrumentId(uuid4()),
        )
        dimension = Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)
        quantity = Quantity(value=config.instances[0].quantity.value, dimension=dimension)
        adverse = Price(
            value=source.scenario.adverse.value,
            currency=source.scenario.adverse.currency,
            per=dimension,
        )
        other_source = replace(
            source,
            name="other-book",
            capture=capture,
            scenario=replace(source.scenario, instrument_id=capture.instrument_id, adverse=adverse),
        )
        other_instance = replace(
            config.instances[1], source=other_source.name, quantity=quantity, lot=quantity
        )
        account = config.accounts[1].configuration
        limits = replace(account.instruments[0], maximum=quantity, lot=quantity, tick=adverse)
        fee_rate = replace(account.fee_rates[0], instrument_id=capture.instrument_id)
        instance_limit = replace(account.budgets.instances[0], instruments=(capture.instrument_id,))
        accounts: tuple[PaperServiceAccount, ...]
        if shared:
            account = config.accounts[0].configuration
            other_instance = replace(other_instance, account_id="shared")
            instance_limit = replace(instance_limit, account_id="shared")
            combined_instruments: tuple[SpotLimits, ...] = (*account.instruments, limits)
            combined_instances: tuple[InstanceLimit, ...] = (
                *account.budgets.instances,
                instance_limit,
            )
            combined_fee_rates: tuple[InstrumentFeeRate, ...] = (*account.fee_rates, fee_rate)
            account = replace(
                account,
                instruments=combined_instruments,
                budgets=replace(account.budgets, instances=combined_instances),
                fee_rates=combined_fee_rates,
            )
            accounts = (replace(config.accounts[0], configuration=account),)
        else:
            account = replace(
                account,
                instruments=(limits,),
                budgets=replace(account.budgets, instances=(instance_limit,)),
                fee_rates=(fee_rate,),
            )
            accounts = (config.accounts[0], replace(config.accounts[1], configuration=account))
        return replace(
            config,
            accounts=accounts,
            sources=(source, other_source),
            instances=(config.instances[0], other_instance),
        )

    @classmethod
    @contextmanager
    def _scheduling_harness(
        cls, config: PaperServiceConfiguration, root: Path, observers: dict[str, _ObservationGate]
    ) -> Iterator[_SchedulingHarness]:
        """Own real typed pipes and fresh owner health without starting signed services."""
        owners = tuple(cls._owner(account.account_id) for account in config.accounts)
        services = _SchedulingHarness(config, owners, root, cls._socket_path())
        services.events = next(iter(observers.values())).events
        services.workers = {name: _StableWorker() for name in config.active}
        with ExitStack() as resources:
            for account_definition, owner in zip(config.accounts, owners, strict=True):
                health_path = Path(account_definition.socket_path).with_suffix(".health.json")
                resources.callback(health_path.unlink, missing_ok=True)
                health_path.write_bytes(
                    services.codec.encode_json(cls._owner_health(owner, time.monotonic_ns()))
                )
            for source_definition in config.sources:
                receiver, sender = cast(
                    "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
                    multiprocessing.get_context("spawn").Pipe(duplex=False),
                )
                resources.callback(receiver.close)
                resources.callback(sender.close)
                for position in range(2):
                    sender.send_bytes(services.codec.encode_json(cls._delivery(position)))
                account_id = next(
                    instance.account_id
                    for instance in config.instances
                    if instance.source == source_definition.name
                )
                services.sources[source_definition.name] = SourceChild(
                    definition=source_definition,
                    request=CaptureRequest(
                        config=source_definition.capture,
                        recording_id=str(uuid4()),
                        implementation_identity="b" * 64,
                    ),
                    process=cast(BaseProcess, _AliveSource()),
                    receiver=receiver,
                    health=HealthMetrics(),
                    observers={account_id: observers[source_definition.name]},
                )
            yield services

    @staticmethod
    def _owner(account_id: str = "shared") -> PaperOwner:
        """Name the current owner expected by the account heartbeat."""
        return PaperOwner(
            account_id=account_id,
            deployment_sha256="a" * 64,
            authorization_id="bounded",
            release_identity="b" * 64,
            owner_id="worker",
            generation=1,
        )

    @staticmethod
    def _owner_health(owner: PaperOwner, at_ns: int) -> AccountHealth:
        """Create a fresh complete heartbeat for identity and process-liveness fencing."""
        return AccountHealth(
            pid=os.getpid(),
            owner_id=owner.owner_id,
            generation=owner.generation,
            release_identity=owner.release_identity,
            heartbeat_at="2026-09-27T00:00:00Z",
            heartbeat_ns=at_ns,
            request_progress_ns=at_ns,
            status="ready",
        )

    @staticmethod
    def _observation(account_id: str, config: AccountConfiguration) -> AccountObservation:
        """Author a whole-account fact without inventing scheduler state."""
        currency = config.accounts[0].cash[0].currency
        ledger = AccountLedger(AccountState(account_id=account_id, currencies=(currency,)))
        return AccountObservation(
            identity=f"observation-{uuid4().hex}",
            at=datetime.now(UTC),
            snapshot=ledger.snapshot(),
            open_orders=(),
        )

    @staticmethod
    def _delivery(position: int = 0) -> SourceDelivery:
        """Pass one typed, already persisted source boundary through the pipe."""
        return SourceDelivery(
            record=CaptureRecord(kind="session", epoch=0, received_ns=position + 1),
            book=BookObservation(
                position=position,
                epoch=0,
                received_ns=position + 1,
                source_time=None,
                sequence=None,
                outcome="session",
                status="recovering",
                reason="awaiting snapshot",
                state_identity="1" * 64,
            ),
        )

    def test_one_reconnect_within_retry_budget_keeps_the_shared_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A capture that recovers one disconnect under its retries is not a source fault."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config, owner = self._config(self._socket_path()), self._owner()
        definition = config.sources[0]
        # Two synchronized connections of two messages each; the first one drops.
        capture = replace(definition.capture, max_messages=4)
        health = HealthMetrics()
        result = asyncio.run(
            collect(
                capture,
                tmp_path / "capture",
                implementation_identity="a" * 64,
                transport=_ReconnectingBookTransport(capture),
                health=health,
            )
        )
        assert result["epochs"] == 2 and result["synchronized"] is True
        assert 1 <= definition.capture.retries
        # The source child keeps running after its reconnect, so its liveness clocks
        # are current; only the recorded counts decide this supervision pass.
        now = time.monotonic_ns()
        for metric in (
            HealthMetric.HEARTBEAT,
            HealthMetric.INGESTION,
            HealthMetric.PERSISTENCE,
            HealthMetric.MARKET,
        ):
            health.set(metric, now)
        health.set(HealthMetric.FINALIZING, 0)
        values = health.snapshot()
        assert (values[HealthMetric.RECONNECTS], values[HealthMetric.GAPS]) == (1, 1)
        services = _SupervisorHarness(config, owner, tmp_path, self._socket_path())
        services.active.clear()
        health_path = Path(config.accounts[0].socket_path).with_suffix(".health.json")
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            multiprocessing.get_context("spawn").Pipe(duplex=False),
        )
        try:
            health_path.write_bytes(
                services.codec.encode_json(self._owner_health(owner, time.monotonic_ns()))
            )
            services.sources[definition.name] = SourceChild(
                definition=definition,
                request=CaptureRequest(
                    config=capture, recording_id=str(uuid4()), implementation_identity="b" * 64
                ),
                process=cast(BaseProcess, _AliveSource()),
                receiver=receiver,
                health=health,
                observers={},
            )
            assert services._supervise() is False
            assert services.fault_calls == [] and services.failures == []
            assert not receiver.closed
        finally:
            health_path.unlink(missing_ok=True)
            receiver.close()
            sender.close()

    def test_source_start_retains_a_chain_under_its_run_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A chain is one key-named recording, and its accounting counts every segment."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._config(self._socket_path())
        # One-message segments roll over at every frame; the run ends after four.
        definition = replace(
            config.sources[0],
            capture=replace(config.sources[0].capture, max_messages=1),
            chain=PaperSourceChain(max_messages=4, max_bytes=64 * 1024**2, max_segments=8),
        )
        assert definition.capture.retries >= 1
        services = _SupervisorHarness(config, self._owner(), tmp_path, self._socket_path())
        services.transports[definition.name] = _SpawnedBookTransport()
        services.measurement_root = tmp_path / "measurements"
        services._start_source(definition)
        child = services.sources[definition.name]
        assert isinstance(child.request, CaptureRunRequest)
        assert child.request.config == definition.capture
        assert child.request.window.max_reconnects == definition.capture.retries
        key = child.request.run_id
        deliveries: list[ReceivedSourceDelivery] = []
        try:
            while True:
                try:
                    payload = child.receiver.recv_bytes()
                except EOFError:
                    break
                deliveries.append(services.codec.decode_json(payload, ReceivedSourceDelivery))
            child.process.join(30)
        finally:
            if child.process.is_alive():
                child.process.kill()
                child.process.join()
        assert child.process.exitcode == 0
        child.pipe_drained, child.received_count = True, len(deliveries)

        source_root = tmp_path / "runs" / services.run_id / definition.name
        (recording,) = CaptureRecording.discover(source_root)
        assert recording.root == source_root / key / key and recording.request == child.request
        assert recording.completed and len(recording.cursor().segments) >= 3
        records = tuple(recording.records())
        assert tuple(item.record for item in deliveries) == records
        assert [item.book.position for item in deliveries] == list(range(len(records)))
        summary = msgspec.json.decode(
            (source_root / key / "source-result.json").read_bytes(), type=dict[str, object]
        )
        assert summary["replay_parity"] is True
        assert summary["segments"] == len(recording.cursor().segments)
        measured = services.measurement_root / services.run_id / definition.name
        assert (measured / f"{key}.capture.jsonl").is_file()

        services._account_source_delivery(definition.name, child)
        accounting = cast(dict[str, object], services.delivery_accounting[definition.name])
        assert accounting["status"] == "complete" and accounting["error"] is None
        assert accounting["capture_finalization"] == "completed"
        assert accounting["durable_records"] == len(records)
        assert accounting["cursor_sha256"] == recording.cursor().sha256
        assert accounting["capture_segments"] == len(recording.cursor().segments)
        child.receiver.close()

    def test_trade_reading_source_starts_a_trades_child_sharing_its_observers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The trades feed records under its own key and feeds the book child's observers."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._config(self._socket_path())
        source = config.sources[0]
        definition = replace(
            source,
            capture=replace(source.capture, max_messages=1),
            trades=replace(source.capture, channel="trades", depth=0, max_orders=1, max_messages=1),
            chain=PaperSourceChain(max_messages=4, max_bytes=64 * 1024**2, max_segments=8),
        )
        config = replace(config, sources=(definition,))
        services = _SupervisorHarness(config, self._owner(), tmp_path, self._socket_path())
        services.resolved = _TradeReadingCandidates(config, None)
        services.transports[definition.name] = _SpawnedBookTransport()
        services.transports[services.feed_key(definition.name, "trades")] = (
            _SpawnedTradesTransport()
        )
        services._start_source(definition)
        book, trades = services._children(definition.name)
        # The harness records refreshes; the trades child sees the book child's observers.
        book.observers["shared"] = _TradeObserver(trades.request, tmp_path / "trades-paper.jsonl")
        try:
            assert (book.feed, trades.feed) == ("book", "trades")
            assert trades.observers is book.observers
            assert trades.request.config == definition.trades
            deliveries: list[ReceivedSourceDelivery] = []
            while True:
                try:
                    payload = trades.receiver.recv_bytes()
                except EOFError:
                    break
                deliveries.append(services.codec.decode_json(payload, ReceivedSourceDelivery))
            trades.process.join(30)
            assert trades.process.exitcode == 0
            for delivery in deliveries:
                for observer in trades.observers.values():
                    services._deliver("trades", observer, delivery, None)
            trades.pipe_drained, trades.received_count = True, len(deliveries)
        finally:
            for child in (book, trades):
                if child.process.is_alive():
                    child.process.kill()
                child.process.join()
        key = services.feed_key(definition.name, "trades")
        services._account_source_delivery(key, trades)
        accounting = cast(dict[str, object], services.delivery_accounting[key])
        assert accounting["status"] == "complete"
        assert accounting["durable_records"] == len(deliveries)
        (observer,) = book.observers.values()
        assert observer.trades_delivered == len(deliveries)
        # Both children read one observer; the account's report is marked once.
        adverse = definition.scenario.adverse
        observer.last_market = PaperMarket(
            identity="book-1",
            at=datetime.now(UTC),
            bid=Price(value=Decimal("11"), currency=adverse.currency, per=adverse.per),
            ask=Price(value=Decimal("12"), currency=adverse.currency, per=adverse.per),
            bid_quantity=Quantity(value=Decimal("1"), dimension=adverse.per),
            ask_quantity=Quantity(value=Decimal("1"), dimension=adverse.per),
        )
        assert services.latest_markets() == {"shared": (observer.last_market,)}
        assert observer.trades_path is not None and len(
            observer.trades_path.read_bytes().splitlines()
        ) == len(deliveries)
        services._close_source(trades)
        services._close_source(book)
        unprovisioned = _TradeReadingCandidates(replace(config, sources=(source,)), None)
        with pytest.raises(ValueError, match="no provisioned feed: trades"):
            unprovisioned.feeds(source)

    def test_source_trades_must_be_the_same_instruments_trades_feed(self) -> None:
        """A trades feed for another route, a book as trades or trades as the book fail."""
        source = self._config(self._socket_path()).sources[0]
        trades = replace(source.capture, channel="trades", depth=0, max_orders=1)
        assert replace(source, trades=trades).trades == trades
        for invalid in (
            replace(trades, symbol="ETH-USDT", base_currency="ETH"),
            replace(trades, instrument_id=InstrumentId(uuid4())),
            source.capture,
        ):
            with pytest.raises(ValueError, match="same instrument's trades feed"):
                replace(source, trades=invalid)
        with pytest.raises(ValueError, match="must be a book feed"):
            replace(source, capture=trades)

    def test_an_undeclared_chain_keeps_one_finite_recording(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A source without a chain captures one journal per recording."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._config(self._socket_path())
        assert b'"chain":null' in DomainCodec().encode_json(config.sources[0])
        services = _SupervisorHarness(
            config, self._owner(), Path("/private/tmp"), self._socket_path()
        )
        request = services._capture_request(config.sources[0], config.sources[0].capture)
        assert type(request) is CaptureRequest
        assert (request.config, request.implementation_identity, request.segment) == (
            config.sources[0].capture,
            "b" * 64,
            None,
        )

    def test_supervisor_life_is_bounded_by_each_account_service_life(self) -> None:
        """Undeclared caps keep 120 s; a declared cap admits up to itself and no further."""
        config = self._config(self._socket_path())
        with pytest.raises(ValueError, match="outlives an account service life"):
            replace(config, duration_seconds=121)
        account = config.accounts[0]
        declared = replace(
            config,
            accounts=(
                replace(
                    account,
                    configuration=replace(account.configuration, service_life_seconds=3000),
                ),
            ),
            duration_seconds=3000,
        )
        assert declared.duration_seconds == 3000
        with pytest.raises(ValueError, match="outlives an account service life"):
            replace(declared, duration_seconds=3001)

    def test_diagnostic_telemetry_follows_its_declared_cadence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default one-second cadence and a declared one each wait their interval."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._config(self._socket_path())
        assert b'"telemetry_seconds":1' in DomainCodec().encode_json(config)
        assert config.telemetry_interval == 1
        for invalid in (0, 301):
            with pytest.raises(ValueError, match="bounded paper service selection"):
                replace(config, telemetry_seconds=invalid)

        class _Diagnostics:
            """Count submitted diagnostic batches."""

            def __init__(self) -> None:
                """Start with none submitted."""
                self.submitted = 0

            def submit(self, markets: dict[str, tuple[PaperMarket, ...]]) -> None:
                """Count one batch."""
                self.submitted += 1

            def poll(self) -> tuple[DiagnosticReceipt, ...]:
                """Return no completed receipts."""
                return ()

        counts: list[int] = []
        for selected in (config, replace(config, telemetry_seconds=15)):
            services = _SupervisorHarness(selected, self._owner(), tmp_path, self._socket_path())
            services.accounts.clear()
            diagnostics = _Diagnostics()
            services.diagnostics = cast(PaperServiceDiagnostics, diagnostics)
            # Three passes at 0, 0.5 and 1.2 seconds of monotonic time.
            monkeypatch.setattr(time, "monotonic", _ScriptedClock((0.0, 0.0, 0.5, 1.2, 1.2)))
            for _ in range(3):
                services._sample()
            counts.append(diagnostics.submitted)
        assert counts == [2, 1]

    def test_declared_telemetry_retries_every_pass_until_a_report_is_retained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed first report, such as a held position before its first mark, retries."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = replace(self._config(self._socket_path()), telemetry_seconds=15)
        now = datetime.now(UTC)

        class _Unreadable:
            """Refuse protection reads; the supervisor retains that as a phase failure."""

            def accounts(self) -> tuple[AccountView, ...]:
                """Fail the synchronous phase read."""
                raise ValueError("unreadable in this test")

        class _Diagnostics:
            """Count batches and return one scripted receipt status per batch."""

            def __init__(self, statuses: list[Literal["retained", "failed"]]) -> None:
                """Bind the receipts the child reports after each batch."""
                self.statuses, self.submitted, self.pending = statuses, 0, False

            def submit(self, markets: dict[str, tuple[PaperMarket, ...]]) -> None:
                """Count one batch; its receipt is collected on the next pass."""
                self.submitted += 1
                self.pending = True

            def poll(self) -> tuple[DiagnosticReceipt, ...]:
                """Return the scripted receipt for the last submitted batch."""
                if not self.pending:
                    return ()
                self.pending = False
                status = self.statuses[min(self.submitted, len(self.statuses)) - 1]
                return (
                    DiagnosticReceipt(
                        account_id="shared", requested_at=now, observed_at=now, status=status
                    ),
                )

        services = _SupervisorHarness(config, self._owner(), tmp_path, self._socket_path())
        services.accounts.clear()
        services.accounts["shared"] = cast(SocketPaperAccount, _Unreadable())
        diagnostics = _Diagnostics(["failed", "failed", "retained"])
        services.diagnostics = cast(PaperServiceDiagnostics, diagnostics)
        for _ in range(6):
            services._sample()
        # Two failed reports retry at once; the retained third starts the cadence.
        assert diagnostics.submitted == 3

    def test_closing_a_source_releases_each_book_index_writer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Source shutdown closes every observer's as-of index and its write-ahead log."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config, owner = self._config(self._socket_path()), self._owner()
        services = _SupervisorHarness(config, owner, tmp_path, self._socket_path())
        path = tmp_path / "delivery.index.sqlite3"
        index = BookAsOfIndex.create(path)
        wal = path.with_name(path.name + "-wal")
        assert wal.exists()
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            multiprocessing.get_context("spawn").Pipe(duplex=False),
        )
        try:
            services._close_source(
                SourceChild(
                    definition=config.sources[0],
                    request=CaptureRequest(
                        config=config.sources[0].capture,
                        recording_id=str(uuid4()),
                        implementation_identity="b" * 64,
                    ),
                    process=cast(BaseProcess, _AliveSource()),
                    receiver=receiver,
                    health=HealthMetrics(),
                    observers={"shared": _IndexedObserver(index)},
                )
            )
        finally:
            sender.close()
        assert receiver.closed and not wal.exists()
        assert index.covered_bytes() == 0

    def test_live_duplicate_control_socket_is_not_unlinked(self) -> None:
        """An occupied supervisor endpoint stays reachable after duplicate launch refusal."""
        path = self._socket_path()
        services = PaperServices.__new__(PaperServices)
        services.control_socket = path
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(str(path))
                listener.listen(1)
                with pytest.raises(ValueError, match="already active"):
                    services._listen()
                assert path.exists()
                listener.settimeout(1)
                accepted, _ = listener.accept()
                accepted.close()
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(path))
            finally:
                path.unlink(missing_ok=True)

    @staticmethod
    def _request(path: Path, action: str, replies: list[dict[str, object]]) -> None:
        """Send one control frame and retain the decoded reply."""
        control = PaperServiceControl(
            action=cast(Literal["inspect", "shutdown", "stop_instance"], action),
            identity=uuid4().hex,
            subject="book" if action == "stop_instance" else None,
        )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(path))
            client.sendall(DomainCodec().encode_json(control) + b"\n")
            reply = bytearray()
            while b"\n" not in reply:
                block = client.recv(65536)
                if not block:
                    break
                reply.extend(block)
        replies.append(msgspec.json.decode(bytes(reply).split(b"\n", 1)[0], type=dict[str, object]))

    def _draining(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[_DrainingServices, socket.socket]:
        """Start a real listener for a supervisor with nothing left to drain."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        path = self._socket_path()
        services = _DrainingServices(
            self._config(self._socket_path()), self._owner(), tmp_path, path
        )
        listener = services._listen()
        return services, listener

    @pytest.mark.parametrize(("duration", "reserve"), ((75, 5.0), (25, 5.0), (10, 2.0)))
    def test_drain_reserve_leaves_most_of_the_service_life_active(
        self, duration: int, reserve: float
    ) -> None:
        """A 75-second service serves its sources for 70 seconds; short ones keep a fifth."""
        assert PaperServices.drain_reserve(duration) == reserve

    def test_draining_supervisor_answers_only_inspect_and_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A drain applies inspect and shutdown and refuses every other control."""
        services, listener = self._draining(tmp_path, monkeypatch)
        try:
            replies: list[dict[str, object]] = []
            for action in ("inspect", "stop_instance", "shutdown"):
                client = threading.Thread(
                    target=self._request, args=(services.control_socket, action, replies)
                )
                client.start()
                deadline = time.monotonic() + 3
                while not services._control(listener, draining=True):
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                client.join(3)
            assert [reply["ok"] for reply in replies] == [True, False, True]
            assert "draining" in str(replies[1]["error"])
            assert services.applied == ["inspect", "shutdown"]
        finally:
            listener.close()
            services.control_socket.unlink(missing_ok=True)

    def test_self_started_drain_answers_a_late_operator_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A shutdown racing the end of the active window is answered, then the drain ends."""
        services, listener = self._draining(tmp_path, monkeypatch)
        replies: list[dict[str, object]] = []
        client = threading.Timer(
            0.3, self._request, args=(services.control_socket, "shutdown", replies)
        )
        client.start()
        started = time.monotonic()
        services._shutdown(listener, deadline=started + 5)
        client.join(3)
        assert replies == [{"ok": True, "status": {"applied": "shutdown"}}]
        assert services.shutdown_requested
        assert time.monotonic() - started < 2
        assert not services.control_socket.exists()

    def test_unrequested_drain_ends_inside_the_service_lifetime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without an operator shutdown the drain still closes before the service deadline."""
        services, listener = self._draining(tmp_path, monkeypatch)
        started = time.monotonic()
        services._shutdown(listener, deadline=started + 1)
        elapsed = time.monotonic() - started
        assert 0.4 <= elapsed < 1
        assert not services.shutdown_requested and not services.control_socket.exists()

    def test_supervise_consumes_one_delivery_per_source_on_each_productive_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backlogged sources each advance once per turn and expose an idle turn."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config, owner = self._config(self._socket_path()), self._owner()
        services = _SupervisorHarness(config, owner, tmp_path, self._socket_path())
        services.active.clear()
        services.faulted_accounts.add("shared")
        services.unavailable_accounts.add("shared")
        connections: list[Connection[bytes, bytes]] = []
        try:
            for name in ("first-source", "second-source"):
                receiver, sender = cast(
                    "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
                    multiprocessing.get_context("spawn").Pipe(duplex=False),
                )
                connections.extend((receiver, sender))
                for position in range(2):
                    sender.send_bytes(DomainCodec().encode_json(self._delivery(position)))
                services.sources[name] = SourceChild(
                    definition=config.sources[0],
                    request=CaptureRequest(
                        config=config.sources[0].capture,
                        recording_id=str(uuid4()),
                        implementation_identity="b" * 64,
                    ),
                    process=cast(BaseProcess, _AliveSource()),
                    receiver=receiver,
                    health=HealthMetrics(),
                    observers={},
                )
            assert services._supervise() is True
            assert [child.received_count for child in services.sources.values()] == [1, 1]
            assert services._supervise() is True
            assert [child.received_count for child in services.sources.values()] == [2, 2]
            assert services._supervise() is False
            assert services.failures == []
        finally:
            for connection in connections:
                connection.close()

    def test_disjoint_sources_progress_across_passes_with_one_ordered_frame_in_flight(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An independent source advances twice while a blocked source retains its first frame."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._two_source_config()
        events: list[str] = []
        barrier = threading.Barrier(2)
        first_release, other_release = threading.Event(), threading.Event()
        other_release.set()
        first = _ObservationGate("shared", events, first_release, barrier=barrier)
        other = _ObservationGate("isolated", events, other_release, barrier=barrier)
        with self._scheduling_harness(
            config, tmp_path, {"book": first, "other-book": other}
        ) as services:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                services._observation_executor = executor
                try:
                    assert services._supervise() is True
                    assert first.entered.wait(2)
                    assert other.finished.wait(2)
                    assert services._pending_observations["other-book"].result(timeout=2) == ()
                    first_future = services._pending_observations["book"]
                    assert other.positions == [0] and first.positions == []
                    assert not first.finished.is_set()
                    assert [child.received_count for child in services.sources.values()] == [1, 1]
                    assert services.fault_calls == services.stop_calls == []
                    first.barrier = other.barrier = None
                    assert services._supervise() is True
                    assert services._pending_observations["other-book"].result(timeout=2) == ()
                    assert other.positions == [0, 1] and first.positions == []
                    assert [child.received_count for child in services.sources.values()] == [1, 2]
                    assert services._supervise() is False
                    readiness = _SourceReadinessProbe()
                    monkeypatch.setattr("applications.execute.services.wait", readiness)
                    services._wait_for_source()
                    assert readiness.receivers == [services.sources["other-book"].receiver]
                    assert readiness.timeout is not None and 0 <= readiness.timeout <= 0.02
                    first_release.set()
                    assert first_future.result(timeout=2) == ()
                    assert services._supervise() is True
                    services._join_observations()
                    assert first.positions == other.positions == [0, 1]
                    assert [child.received_count for child in services.sources.values()] == [2, 2]
                    assert services._supervise() is False
                    assert all(
                        worker != threading.get_ident()
                        for worker in (*first.callback_threads, *other.callback_threads)
                    )
                finally:
                    first_release.set()
                    other_release.set()
                    services._join_observations()
                    services._observation_executor = None

    @pytest.mark.parametrize("all_pending", (False, True))
    def test_completion_wakes_idle_source_wait_and_closes_run_owned_handles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, all_pending: bool
    ) -> None:
        """A completed source wakes both mixed and all-pending waits without a new pipe frame."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._two_source_config()
        events: list[str] = []
        first_release, other_release = threading.Event(), threading.Event()
        first = _ObservationGate("shared", events, first_release)
        other = _ObservationGate("isolated", events, other_release)
        with self._scheduling_harness(
            config, tmp_path, {"book": first, "other-book": other}
        ) as services:
            if not all_pending:
                idle = services.sources["other-book"].receiver
                idle.recv_bytes()
                idle.recv_bytes()
            readiness = _CompletionReadinessProbe()
            monkeypatch.setattr("applications.execute.services.wait", readiness)
            thread = threading.Thread(target=services._wait_for_source)
            with ExitStack() as stack:
                services._start_observation_executor(stack)
                receiver, sender = (
                    services._observation_wake_receiver,
                    services._observation_wake_sender,
                )
                assert receiver is not None and sender is not None
                try:
                    assert services._supervise() is True
                    assert first.entered.wait(2)
                    if all_pending:
                        assert other.entered.wait(2)
                    first_future = services._pending_observations["book"]
                    assert not first_future.done()
                    thread.start()
                    assert readiness.entered.wait(2)
                    first_release.set()
                    thread.join(3)
                    assert not thread.is_alive()
                    assert first_future.result(timeout=2) == ()
                    assert readiness.ready == [receiver]
                    assert readiness.timeout is not None and 0 <= readiness.timeout <= 0.02
                    assert readiness.receivers == (
                        [receiver]
                        if all_pending
                        else [services.sources["other-book"].receiver, receiver]
                    )
                    if all_pending:
                        assert not services._pending_observations["other-book"].done()
                finally:
                    first_release.set()
                    other_release.set()
                    if thread.ident is not None:
                        thread.join(3)
                    services._join_observations()
            assert receiver.fileno() == sender.fileno() == -1
            assert services._observation_executor is None
            assert services._observation_wake_receiver is services._observation_wake_sender is None
            assert services._pending_observations == {}

    def test_shared_account_sources_keep_name_order_on_supervisor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A shared owner advances each source once per turn in serialized name order."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._two_source_config(shared=True)
        events: list[str] = []
        released = threading.Event()
        released.set()
        first = _ObservationGate("first-source", events, released)
        other = _ObservationGate("second-source", events, released)
        with self._scheduling_harness(
            config, tmp_path, {"book": first, "other-book": other}
        ) as services:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                services._observation_executor = executor
                readiness = _SourceReadinessProbe()
                monkeypatch.setattr("applications.execute.services.wait", readiness)
                services._wait_for_source()
                assert readiness.receivers == [
                    child.receiver for child in services.sources.values()
                ]
                assert readiness.timeout == 0.02
                assert services._supervise() is True
                assert [child.received_count for child in services.sources.values()] == [1, 1]
                assert services._supervise() is True
                assert [child.received_count for child in services.sources.values()] == [2, 2]
                assert services._supervise() is False
                assert events == [
                    "observe:first-source:0",
                    "finished:first-source:0",
                    "observe:second-source:0",
                    "finished:second-source:0",
                    "observe:first-source:1",
                    "finished:first-source:1",
                    "observe:second-source:1",
                    "finished:second-source:1",
                ]
                assert first.positions == other.positions == [0, 1]
                assert (
                    first.callback_threads == other.callback_threads == [threading.get_ident()] * 2
                )
                assert services.fault_calls == services.stop_calls == []
                assert services.failures == []
                services._observation_executor = None

    @pytest.mark.parametrize("policy_failure", (False, True))
    def test_parallel_observer_failure_waits_for_all_jobs_before_fencing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy_failure: bool
    ) -> None:
        """No failure closes workers or faults an owner until the unrelated callback has joined."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._two_source_config()
        events: list[str] = []
        barrier = threading.Barrier(2)
        released, blocked = threading.Event(), threading.Event()
        released.set()
        error = (
            CandidateProcessFailure(123, "decision policy unavailable")
            if policy_failure
            else TimeoutError("account response uncertain")
        )
        first = _ObservationGate("shared", events, released, barrier=barrier, error=error)
        other = _ObservationGate("isolated", events, blocked, barrier=barrier)
        with self._scheduling_harness(
            config, tmp_path, {"book": first, "other-book": other}
        ) as services:
            services.workers["first"] = _ChangingWorker()
            runner = _SupervisorPass(services)
            thread = threading.Thread(target=runner)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                services._observation_executor = executor
                try:
                    assert services._supervise() is True
                    assert first.finished.wait(2)
                    assert other.entered.wait(2)
                    assert services._pending_observations["book"].result(timeout=2)
                    assert not other.finished.is_set()
                    assert services.fault_calls == services.stop_calls == []
                    assert services.active == {"first", "other"}
                    # Isolate the completed failure from a later queued delivery.
                    for child in services.sources.values():
                        child.receiver.recv_bytes()
                    thread.start()
                    assert runner.entered.wait(2)
                    assert not runner.finished.wait(0.05)
                    blocked.set()
                    thread.join(3)
                    assert not thread.is_alive()
                    assert runner.error is None
                    assert first.positions == other.positions == [0]
                    assert services.stop_calls == [("first", "worker_lost_during_decision")]
                    assert services.fault_calls == (
                        [] if policy_failure else [("shared", "account_or_delivery_failure")]
                    )
                    assert services.active == {"other"}
                    assert services.lifecycle_threads == [runner.thread_id] * len(
                        services.lifecycle_threads
                    )
                    assert events.index("finished:isolated:0") < events.index("stop:first")
                finally:
                    blocked.set()
                    if thread.ident is not None:
                        thread.join(3)
                    services._join_observations()
                    services._observation_executor = None

    def test_parallel_observation_starts_after_later_source_fault_is_fenced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A later source's invalid position is fenced before an earlier ready job begins."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._two_source_config()
        events: list[str] = []
        released = threading.Event()
        released.set()
        first = _ObservationGate("shared", events, released)
        other = _ObservationGate("isolated", events, released)
        with self._scheduling_harness(
            config, tmp_path, {"book": first, "other-book": other}
        ) as services:
            services.sources["other-book"].receiver.recv_bytes()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                services._observation_executor = executor
                assert services._supervise() is True
                services._join_observations()
                assert services.fault_calls == [("isolated", "source_failure:ValueError")]
                assert events == ["fault:isolated", "observe:shared:0", "finished:shared:0"]
                assert first.positions == [0] and other.positions == []
                assert services.lifecycle_threads == [threading.get_ident()]
                services._observation_executor = None

    @pytest.mark.parametrize("operation", ("control", "source_fault", "shutdown"))
    def test_inflight_observations_join_before_lifecycle_mutations(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        operation: Literal["control", "source_fault", "shutdown"],
    ) -> None:
        """Operator stop, source protection and shutdown complete after both native callbacks."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._two_source_config()
        events: list[str] = []
        blocked, released = threading.Event(), threading.Event()
        released.set()
        first = _ObservationGate("shared", events, blocked)
        other = _ObservationGate("isolated", events, released)
        with (
            self._scheduling_harness(
                config, tmp_path, {"book": first, "other-book": other}
            ) as services,
            socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener,
        ):
            runner = _LifecycleCall(services, operation, listener, events)
            thread = threading.Thread(target=runner)
            with ExitStack() as stack:
                services._start_observation_executor(stack)
                try:
                    assert services._supervise() is True
                    assert first.entered.wait(2) and other.finished.wait(2)
                    if operation == "shutdown":
                        for name, child in services.sources.items():
                            child.process = cast(BaseProcess, _ClosingSource(name, events))
                        services.workers = {name: _ClosingWorker(events) for name in config.active}
                        services.accounts = {
                            account.account_id: _ClosingAccount(events, account.account_id)
                            for account in config.accounts
                        }
                    thread.start()
                    assert runner.entered.wait(2)
                    assert not runner.finished.wait(0.05) and not services.is_stopping
                    assert services.fault_calls == []
                    assert not any(e.startswith("source:") for e in events)
                    blocked.set()
                    thread.join(3)
                    assert not thread.is_alive() and runner.error is None
                    assert first.positions == other.positions == [0]
                    complete = max(
                        events.index(f"finished:{name}:0") for name in ("shared", "isolated")
                    )
                    boundary = (
                        events.index("fault:shared")
                        if operation == "source_fault"
                        else events.index("source:book")
                        if operation == "shutdown"
                        else events.index("lifecycle:control")
                    )
                    assert complete < boundary
                    assert services._pending_observations == {}
                finally:
                    blocked.set()
                    if thread.ident is not None:
                        thread.join(3)
                    services._join_observations()

    @pytest.mark.parametrize("target", (SourceDelivery, ReceivedSourceDelivery))
    @pytest.mark.parametrize(
        ("before", "after", "reason"),
        (
            (b"1" * 64, b"bad", "book state or quality"),
            (b'"size":"4"', b'"size":"0"', "aggregate levels"),
            (b'"received_ns":1', b'"received_ns":0', "capture record"),
        ),
    )
    def test_source_pipe_decode_validates_nested_book(
        self,
        target: type[SourceDelivery] | type[ReceivedSourceDelivery],
        before: bytes,
        after: bytes,
        reason: str,
    ) -> None:
        """Typed pipe decoding rejects malformed depth before the trusted observer path."""
        codec = DomainCodec()
        delivery = self._delivery()
        delivery = replace(
            delivery,
            book=replace(
                delivery.book,
                bids=((Decimal("99"), Level(size=Decimal("4"), order_count=1)),),
            ),
        )
        payload = codec.encode_json(delivery)
        received = codec.decode_json(payload, target)
        assert received.record == delivery.record
        assert codec.encode_json(received.book) == codec.encode_json(delivery.book)
        if target is SourceDelivery:
            assert type(received.book) is BookObservation
            assert received.book == delivery.book
        assert codec.encode_json(received) == payload
        corrupted = payload.replace(before, after)
        assert corrupted != payload
        with pytest.raises(ValueError, match=reason):
            codec.decode_json(corrupted, target)

    def test_public_source_delivery_revalidates_mutated_book(self) -> None:
        """Direct public envelope construction rejects an unsafe copied native row."""
        delivery = self._delivery()
        force_setattr(delivery.book, "state_identity", "bad")
        with pytest.raises(ValueError, match="book state or quality"):
            SourceDelivery(record=delivery.record, book=delivery.book)

    def test_received_native_depth_is_retained_exactly(self) -> None:
        """The private decoder preserves all L2 levels and L3 identities on the public wire."""
        codec = DomainCodec()
        original = self._delivery()
        l2 = replace(
            original,
            book=replace(
                original.book,
                bids=((Decimal("99"), Level(Decimal("4"), 2)),),
                asks=((Decimal("101"), Level(Decimal("5"), 3)),),
            ),
        )
        l3 = replace(
            original,
            book=replace(
                original.book,
                orders=(
                    Order("bid-native", "buy", Decimal("99"), Decimal("4")),
                    Order("ask-native", "sell", Decimal("101"), Decimal("5")),
                ),
            ),
        )
        payloads = tuple(codec.encode_json(delivery) for delivery in (l2, l3))
        for payload in payloads:
            received = codec.decode_json(payload, ReceivedSourceDelivery)
            assert codec.encode_json(received) == payload
            public = codec.decode_json(codec.encode_json(received), SourceDelivery)
            assert type(public.book) is BookObservation
            assert codec.encode_json(public) == payload

    @pytest.mark.parametrize(
        ("kind", "before", "after", "reason"),
        (
            ("l2", b'[["98",', b'[["0",', "positive exact prices"),
            ("l2", b'[["98",', b'[["NaN",', "positive exact prices"),
            ("l2", b'[["98",', b'[["99",', "duplicate native order or aggregate price"),
            ("l2", b'"order_count":2', b'"order_count":0', "aggregate levels"),
            ("l3", b'"order_id":"ask-native"', b'"order_id":"bid-native"', "duplicate native"),
            ("l3", b'"side":"buy"', b'"side":"invalid"', "order identity or side"),
            ("l3", b'"size":"4"', b'"size":"0"', "orders require positive"),
        ),
    )
    def test_received_book_rejects_invalid_prices_uniqueness_and_native_values(
        self, kind: str, before: bytes, after: bytes, reason: str
    ) -> None:
        """The private schema retains all semantic book and typed nested value checks."""
        codec = DomainCodec()
        original = self._delivery()
        l2 = replace(
            original,
            book=replace(
                original.book,
                bids=(
                    (Decimal("98"), Level(Decimal("3"), 1)),
                    (Decimal("99"), Level(Decimal("4"), 2)),
                ),
            ),
        )
        l3 = replace(
            original,
            book=replace(
                original.book,
                orders=(
                    Order("bid-native", "buy", Decimal("99"), Decimal("4")),
                    Order("ask-native", "sell", Decimal("101"), Decimal("5")),
                ),
            ),
        )
        payload = codec.encode_json(l3 if kind == "l3" else l2)
        corrupted = payload.replace(before, after)
        assert corrupted != payload
        with pytest.raises(ValueError, match=reason):
            codec.decode_json(corrupted, ReceivedSourceDelivery)

    @pytest.mark.parametrize("kind", ("level", "order"))
    def test_public_delivery_revalidates_received_nested_native_values(self, kind: str) -> None:
        """A private decoded row cannot bypass public recursive checks after unsafe mutation."""
        codec = DomainCodec()
        original = self._delivery()
        book = (
            replace(original.book, bids=((Decimal("99"), Level(Decimal("4"), 2)),))
            if kind == "level"
            else replace(
                original.book,
                orders=(Order("bid-native", "buy", Decimal("99"), Decimal("4")),),
            )
        )
        received = codec.decode_json(
            codec.encode_json(SourceDelivery(record=original.record, book=book)),
            ReceivedSourceDelivery,
        )
        if kind == "level":
            force_setattr(received.book.bids[0][1], "size", Decimal("0"))
        else:
            force_setattr(received.book.orders[0], "size", Decimal("0"))
        with pytest.raises(ValueError, match=r"aggregate levels|orders require positive"):
            SourceDelivery(record=received.record, book=received.book)

    def test_diagnostic_failure_does_not_retry_account_work(self, tmp_path: Path) -> None:
        """A failed monitor inspection records one error and no economic request."""
        config = self._config(self._socket_path())
        account = _DiagnosticAccount(config.accounts[0].configuration, self._owner())
        monitor = PaperServiceMonitor(tmp_path / "monitor")
        result = monitor.sample(account, config.sources, ())
        assert result["status"] == "failed"
        assert account.calls == 1
        assert monitor.failures == 1

    def test_monitor_uses_one_inspection_for_flat_and_marked_account(self, tmp_path: Path) -> None:
        """A received book cannot mark a flat account; a holding uses its bid once."""
        config = self._config(self._socket_path())
        currency = config.accounts[0].configuration.accounts[0].cash[0].currency
        dimension = config.instances[0].quantity.dimension
        owner = self._owner()
        now = datetime.now(UTC)
        fund = AccountPosting(
            identity="opening",
            account_id="shared",
            event_at=config.accounts[0].configuration.opening_at,
            known_at=config.accounts[0].configuration.opening_at,
            kind="transfer",
            cash=Money(value=Decimal("1000"), currency=currency),
        )
        market = PaperMarket(
            identity="book-1",
            at=now - timedelta(seconds=1),
            bid=Price(value=Decimal("11"), currency=currency, per=dimension),
            ask=Price(value=Decimal("12"), currency=currency, per=dimension),
            bid_quantity=Quantity(value=Decimal("2"), dimension=dimension),
            ask_quantity=Quantity(value=Decimal("2"), dimension=dimension),
        )
        flat = _SnapshotAccount(
            config.accounts[0].configuration,
            owner,
            AccountExecutionResult(
                accounts=(
                    AccountView(
                        ledger=AccountState(
                            account_id="shared", currencies=(currency,), postings=(fund,)
                        ),
                        reconciled_at=config.accounts[0].configuration.opening_at,
                    ),
                ),
                orders=(),
            ),
        )
        flat_sample = PaperServiceMonitor(tmp_path / "flat").sample(flat, config.sources, (market,))
        flat_report = flat_sample["report"]
        assert flat_sample["status"] == "retained"
        assert flat_sample["phase"] == "running"
        assert isinstance(flat_report, PaperAccountReport)
        assert flat_report.account.positions == ()
        assert flat_report.account.currencies[0].nav.value == Decimal("1000")
        assert [request.action for request in flat.seen_requests] == ["inspect"]

        receipt = DiagnosticReceipt(
            account_id=owner.account_id,
            requested_at=now,
            observed_at=cast(datetime, flat_sample["observed_at"]),
            status="retained",
            phase="running",
            account=Raw(DomainCodec().encode_json(flat_sample["account"])),
            activation=Raw(DomainCodec().encode_json(flat_sample["activation"])),
            report=Raw(DomainCodec().encode_json(flat_sample["report"])),
            instances=Raw(DomainCodec().encode_json(flat_sample["instances"])),
        )
        codec = DomainCodec()
        round_trip = codec.decode_json(codec.encode_json(receipt), DiagnosticReceipt)
        projected = msgspec.json.decode(codec.encode_json(round_trip), type=dict[str, Raw])
        for field in ("account", "activation", "report", "instances"):
            assert bytes(projected[field]) == codec.encode_json(flat_sample[field])

        fill = Fill(
            identity="fill-1",
            decision_at=now - timedelta(seconds=3),
            filled_at=now - timedelta(seconds=2),
            quantity=Quantity(value=Decimal("1"), dimension=dimension),
            reference=Price(value=Decimal("10"), currency=currency, per=dimension),
            effective=Price(value=Decimal("10"), currency=currency, per=dimension),
            fee=Money(value=Decimal("0"), currency=currency),
        )
        fill_posting = AccountPosting(
            identity=fill.identity,
            account_id="shared",
            event_at=fill.filled_at,
            known_at=fill.filled_at,
            kind="fill",
            cash=Money(value=Decimal("-10"), currency=currency),
            instance_id="first",
            order_id="order-1",
            quantity=fill.quantity,
            price=fill.effective,
        )
        occupied = _SnapshotAccount(
            config.accounts[0].configuration,
            owner,
            AccountExecutionResult(
                accounts=(
                    AccountView(
                        ledger=AccountState(
                            account_id="shared",
                            currencies=(currency,),
                            postings=(fund, fill_posting),
                        ),
                        reconciled_at=config.accounts[0].configuration.opening_at,
                    ),
                ),
                orders=(),
                paper_fills=(AccountPaperFill(instance_id="first", order_id="order-1", fill=fill),),
                paper_costs=(
                    AccountPaperCost(
                        posting_id=None,
                        source_fill_id=fill.identity,
                        amount=Money(value=Decimal("0"), currency=currency),
                    ),
                ),
            ),
        )
        occupied_sample = PaperServiceMonitor(tmp_path / "occupied").sample(
            occupied, config.sources, (market,)
        )
        occupied_report = occupied_sample["report"]
        assert occupied_sample["status"] == "retained"
        assert occupied_sample["phase"] == "running"
        assert isinstance(occupied_report, PaperAccountReport)
        assert occupied_report.account.positions[0].mark.identity == market.identity
        assert occupied_report.account.currencies[0].nav.value == Decimal("1001")
        assert [request.action for request in occupied.seen_requests] == ["inspect"]

    def test_launch_file_decodes_exact_typed_owner_tokens(self) -> None:
        """The deployment CLI can load a complete owner envelope without generic tuple decoding."""
        codec = DomainCodec()
        supplied = PaperServiceOwners(owners=(self._owner(),))
        assert codec.decode_json(codec.encode_json(supplied), PaperServiceOwners) == supplied
        with pytest.raises(ValueError):
            codec.decode_json(b'{"owners":[{"owner_id":"incomplete"}]}', PaperServiceOwners)

    @classmethod
    def _restart_harness(
        cls,
        root: Path,
        config: PaperServiceConfiguration,
        owners: tuple[PaperOwner, PaperOwner],
        *,
        accepts: bool,
    ) -> tuple[_SupervisorHarness, list[str]]:
        """Retain independent account and scheduler calls for one restart attempt."""
        events: list[str] = []
        root.mkdir()
        services = _SupervisorHarness(config, owners, root, cls._socket_path(), events)
        services.active.remove("first")
        services.workers["other"] = _StableWorker()
        services.accounts["shared"] = _RestartAccount(
            config.accounts[0].configuration, owners[0], events, accepts_observation=accepts
        )
        services.accounts["isolated"] = _RestartAccount(
            config.accounts[1].configuration, owners[1], events, accepts_observation=True
        )
        return services, events

    def test_restart_observation_precedes_restart_and_preserves_other_account(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One typed control reconciles before a restart, with no intervening scheduling."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._two_account_config()
        owners = (self._owner(), self._owner("isolated"))
        codec = DomainCodec()

        observation = self._observation("shared", config.accounts[0].configuration)
        control = PaperServiceControl(
            action="restart_instance",
            identity="restart-with-observation",
            subject="first",
            observation=observation,
        )
        assert codec.decode_json(codec.encode_json(control), PaperServiceControl) == control
        accepted, accepted_events = self._restart_harness(
            tmp_path / "accepted", config, owners, accepts=True
        )
        accepted.apply(control)
        assert accepted_events == [
            "shared:reconcile",
            "shared:restart_instance",
            "start:first",
            "refresh:book",
        ]
        assert accepted.active == {"first", "other"}
        assert accepted.faulted_accounts == set()
        accepted.apply(control)
        assert len(accepted_events) == 4
        with pytest.raises(ValueError, match="only an instance restart"):
            PaperServiceControl(
                action="stop_instance",
                identity="invalid-observation",
                subject="first",
                observation=observation,
            )

        mismatch, mismatch_events = self._restart_harness(
            tmp_path / "mismatch", config, owners, accepts=True
        )
        with pytest.raises(ValueError, match="another account"):
            mismatch.apply(
                PaperServiceControl(
                    action="restart_instance",
                    identity="mismatched-account",
                    subject="first",
                    observation=self._observation("isolated", config.accounts[1].configuration),
                )
            )
        assert mismatch_events == []
        assert mismatch.active == {"other"}
        assert mismatch.faulted_accounts == set()

        rejected, rejected_events = self._restart_harness(
            tmp_path / "rejected", config, owners, accepts=False
        )
        with pytest.raises(ValueError, match="instance_restart_requires_reconciliation"):
            rejected.apply(
                PaperServiceControl(
                    action="restart_instance",
                    identity="rejected-observation",
                    subject="first",
                    observation=observation,
                )
            )
        assert rejected_events == ["shared:reconcile"]
        assert rejected.active == {"other"}
        assert rejected.faulted_accounts == set()

    @pytest.mark.parametrize("policy_failure", (False, True))
    def test_observer_distinguishes_pure_policy_failure_from_account_uncertainty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy_failure: bool
    ) -> None:
        """Only a typed pre-commit policy failure permits selective cohort continuation."""
        monkeypatch.setattr(InstalledIdentity, "sha256", staticmethod(_Constant("b" * 64)))
        socket_path = self._socket_path()
        config, owner = self._config(socket_path), self._owner()
        services = _SupervisorHarness(config, owner, tmp_path, self._socket_path())
        health_path = socket_path.with_suffix(".health.json")
        health_path.write_bytes(
            DomainCodec().encode_json(
                {
                    "pid": os.getpid(),
                    "heartbeat_ns": time.monotonic_ns(),
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                    "request_progress_ns": time.monotonic_ns(),
                    "generation": owner.generation,
                    "owner_id": owner.owner_id,
                    "release_identity": owner.release_identity,
                    "status": "ready",
                }
            )
        )
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            multiprocessing.get_context("spawn").Pipe(duplex=False),
        )
        observer = _UncertainObserver(policy_failure=policy_failure)
        worker = _ChangingWorker()
        try:
            sender.send_bytes(DomainCodec().encode_json(self._delivery()))
            request = CaptureRequest(
                config=config.sources[0].capture,
                recording_id=str(uuid4()),
                implementation_identity="b" * 64,
            )
            services.workers["first"] = worker
            services.sources["book"] = SourceChild(
                definition=config.sources[0],
                request=request,
                process=cast(BaseProcess, _AliveSource()),
                receiver=receiver,
                health=HealthMetrics(),
                observers={"shared": observer},
            )
            services._supervise()
            assert observer.calls == 1
            assert services.stop_calls == [("first", "worker_lost_during_decision")]
            assert services.fault_calls == (
                [] if policy_failure else [("shared", "account_or_delivery_failure")]
            )
            assert services.active == set()
        finally:
            sender.close()
            receiver.close()
            health_path.unlink(missing_ok=True)

    def test_measurement_close_failure_still_fences_every_source_worker_and_account(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed evidence fsync cannot abort protective shutdown of other owners."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._config(self._socket_path())
        services = PaperServices(
            config,
            (self._owner(),),
            root=tmp_path,
            control_socket=self._socket_path(),
        )
        events: list[str] = []
        senders: list[Connection[bytes, bytes]] = []
        receivers: list[Connection[bytes, bytes]] = []
        for name, fail in (("first", True), ("second", False)):
            receiver, sender = cast(
                "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
                multiprocessing.get_context("spawn").Pipe(duplex=False),
            )
            receivers.append(receiver)
            senders.append(sender)
            services.sources[name] = SourceChild(
                definition=config.sources[0],
                request=CaptureRequest(
                    config=config.sources[0].capture,
                    recording_id=str(uuid4()),
                    implementation_identity="b" * 64,
                ),
                process=cast(BaseProcess, _ClosingSource(name, events)),
                receiver=receiver,
                health=HealthMetrics(),
                observers={
                    "shared": _ClosingObserver(_ClosingMeasurements(name, events, fail=fail))
                },
            )
        services.workers["first"] = _ClosingWorker(events)
        services.accounts["shared"] = _ClosingAccount(events)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            services._shutdown(listener)
            assert events == [
                "source:first",
                "measurement:first",
                "source:second",
                "measurement:second",
                "worker",
                "account",
            ]
            assert all(receiver.closed for receiver in receivers)
            assert listener.fileno() == -1
            assert [event["reason"] for event in services.failures] == ["source_close_failed"]
        finally:
            listener.close()
            for sender in senders:
                sender.close()

    def test_shutdown_joins_clean_source_eof_and_reports_missing_cursor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A clean pipe EOF is joined before accounts stop; absent raw proof stays failed."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config = self._config(self._socket_path())
        services = PaperServices(
            config, (self._owner(),), root=tmp_path, control_socket=self._socket_path()
        )
        services.active.clear()
        services.faulted_accounts.add("shared")
        events: list[str] = []
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            multiprocessing.get_context("spawn").Pipe(duplex=False),
        )
        stop = multiprocessing.get_context("spawn").Event()
        services.sources["book"] = SourceChild(
            definition=config.sources[0],
            request=CaptureRequest(
                config=config.sources[0].capture,
                recording_id=str(uuid4()),
                implementation_identity="b" * 64,
            ),
            process=cast(BaseProcess, _GracefulSource(events)),
            receiver=receiver,
            health=HealthMetrics(),
            observers={},
            stop=stop,
        )
        services.accounts["shared"] = _ClosingAccount(events)
        sender.close()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            services._shutdown(listener, deadline=time.monotonic() + 1)
            assert stop.is_set()
            assert events == ["source:joined", "source:joined", "account"]
            assert b'"status":"incomplete"' in services.codec.encode_json(
                services.delivery_accounting["book"]
            )
            assert [event["reason"] for event in services.failures] == [
                "source_delivery_incomplete"
            ]
            assert receiver.closed
        finally:
            sender.close()
            receiver.close()
            listener.close()

    @staticmethod
    def _wait_diagnostic_marker(diagnostics: PaperServiceDiagnostics) -> None:
        """Require an actual child to reach the bounded test gate."""
        deadline = time.monotonic() + 5
        while not (diagnostics.root / "diagnostic-ready").exists():
            assert diagnostics.status()["alive"] is True
            assert time.monotonic() < deadline
            time.sleep(0.01)

    def test_blocked_report_does_not_delay_account_protection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fault is detected by the existing accounts projection while full reports wait."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config, owner = self._config(self._socket_path()), self._owner()
        services = PaperServices(
            config, (owner,), root=tmp_path, control_socket=self._socket_path()
        )
        view = AccountView(
            ledger=AccountState(
                account_id=owner.account_id,
                currencies=(config.accounts[0].configuration.accounts[0].cash[0].currency,),
            ),
            reconciled_at=config.accounts[0].configuration.opening_at,
            phase="faulted",
            active_control_identity="first-protection",
            control_cutoff_at=datetime.now(UTC),
        )
        account = _SnapshotAccount(
            config.accounts[0].configuration,
            owner,
            AccountExecutionResult(accounts=(view,), orders=()),
        )
        services.accounts[owner.account_id] = account
        services.workers["first"] = _StableWorker()
        diagnostics = _DelayedDiagnostics(
            config,
            (owner,),
            root=tmp_path / "monitoring",
            deadline=time.monotonic() + 10,
            runs=tmp_path / "runs",
        )
        services.diagnostics = diagnostics
        diagnostics.start()
        try:
            self._wait_diagnostic_marker(diagnostics)
            services._sample()
            assert not (diagnostics.root / "allow-reports").exists()
            assert account.seen_requests[0].action == "inspect"
            assert account.seen_requests[0].projection == "accounts"
            assert services.faulted_accounts == {owner.account_id}
            assert services.active == set()
            phase = cast(dict[str, object], services.account_phases[owner.account_id])
            assert phase["phase"] == "faulted" and phase["status"] == "observed"
            assert isinstance(phase["observed_at"], datetime)
            assert [event["reason"] for event in services.failures] == ["account_protected"]
        finally:
            diagnostics.close(deadline=time.monotonic() + 1)
        assert diagnostics.status()["alive"] is False
        assert diagnostics.status()["exitcode"] == 0

    def test_diagnostic_latest_batch_is_bounded_and_failure_is_visible(
        self, tmp_path: Path
    ) -> None:
        """Three waiting requests become one report with two explicitly coalesced batches."""
        config, owner = self._config(self._socket_path()), self._owner()
        diagnostics = _DelayedDiagnostics(
            config,
            (owner,),
            root=tmp_path / "monitoring",
            deadline=time.monotonic() + 10,
            runs=tmp_path / "runs",
        )
        diagnostics.start()
        try:
            self._wait_diagnostic_marker(diagnostics)
            for _ in range(3):
                diagnostics.submit({owner.account_id: ()})
            assert diagnostics.status()["pending_batches"] == 1
            (diagnostics.root / "allow-reports").touch()
            deadline = time.monotonic() + 5
            receipts: tuple[DiagnosticReceipt, ...] = ()
            while not receipts:
                receipts = diagnostics.poll()
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert len(receipts) == 1
            assert receipts[0].status == "failed"
            assert receipts[0].error is not None and "FileNotFoundError" in receipts[0].error
            assert receipts[0].requested_at <= receipts[0].observed_at
            assert diagnostics.status()["completed_batches"] == 1
            assert diagnostics.status()["coalesced_batches"] == 2
            assert diagnostics.failure_count == 1
            assert diagnostics.poll() == ()
        finally:
            diagnostics.close(deadline=time.monotonic() + 1)
        status = diagnostics.status()
        assert status["alive"] is False and status["exitcode"] == 0
        assert status["pid"] is not None and status["exit_observed_at"] is not None
        assert (diagnostics.root / "diagnostic-events.jsonl").read_bytes().count(b"\n") == 1

    def test_diagnostic_stall_is_fenced_within_shared_deadline(self, tmp_path: Path) -> None:
        """A stuck report is terminated and its PID remains visible after bounded cleanup."""
        config, owner = self._config(self._socket_path()), self._owner()
        diagnostics = _StalledDiagnostics(
            config,
            (owner,),
            root=tmp_path / "monitoring",
            deadline=time.monotonic() + 10,
            runs=tmp_path / "runs",
        )
        diagnostics.start()
        try:
            self._wait_diagnostic_marker(diagnostics)
            diagnostics.close(deadline=time.monotonic() + 1)
            status = diagnostics.status()
            assert status["alive"] is False
            assert status["exitcode"] == -15
            assert status["forced_fence"] is True
            assert status["pid"] is not None
            assert diagnostics.failure_count == 1
        finally:
            diagnostics.close(deadline=time.monotonic() + 1)

    def test_diagnostic_account_rejects_mutation_before_transport(self, tmp_path: Path) -> None:
        """An economic control cannot cross the read-only diagnostic client boundary."""
        config, owner = self._config(self._socket_path()), self._owner()
        requests = tmp_path / "requests"
        account = ReadOnlyPaperAccount(
            config=config.accounts[0].configuration,
            socket_path=Path(config.accounts[0].socket_path),
            requests=requests,
            paper_owner=owner,
        )
        with pytest.raises(ValueError, match="can only inspect"):
            account.control(
                AccountControl(
                    identity="diagnostics-cannot-fault",
                    account_id=owner.account_id,
                    kind="fault",
                    at=datetime.now(UTC),
                    reason="diagnostic mutation forbidden",
                )
            )
        assert not requests.exists()

    def test_shutdown_fences_stalled_diagnostics_before_source_cleanup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blocked report leaves deadline time for EOF, source join and account stop."""
        monkeypatch.setattr(
            InstalledIdentity, "sha256", staticmethod(self._implementation_identity)
        )
        config, owner = self._config(self._socket_path()), self._owner()
        services = PaperServices(
            config, (owner,), root=tmp_path, control_socket=self._socket_path()
        )
        services.active.clear()
        services.faulted_accounts.add(owner.account_id)
        events: list[str] = []
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            multiprocessing.get_context("spawn").Pipe(duplex=False),
        )
        stop = multiprocessing.get_context("spawn").Event()
        services.sources["book"] = SourceChild(
            definition=config.sources[0],
            request=CaptureRequest(
                config=config.sources[0].capture,
                recording_id=str(uuid4()),
                implementation_identity="b" * 64,
            ),
            process=cast(BaseProcess, _GracefulSource(events)),
            receiver=receiver,
            health=HealthMetrics(),
            observers={},
            stop=stop,
        )
        services.accounts[owner.account_id] = _ClosingAccount(events)
        diagnostics = _StalledDiagnostics(
            config,
            (owner,),
            root=tmp_path / "monitoring",
            deadline=time.monotonic() + 10,
            runs=tmp_path / "runs",
        )
        services.diagnostics = diagnostics
        diagnostics.start()
        sender.close()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._wait_diagnostic_marker(diagnostics)
            deadline = time.monotonic() + 1
            services._shutdown(listener, deadline=deadline)
            assert time.monotonic() < deadline
            assert stop.is_set() and receiver.closed
            assert events == ["source:joined", "source:joined", "account"]
            assert diagnostics.status()["alive"] is False
            assert diagnostics.status()["forced_fence"] is True
            assert diagnostics.status()["exitcode"] == -15
            assert [event["reason"] for event in services.failures] == [
                "source_delivery_incomplete"
            ]
        finally:
            diagnostics.close(deadline=time.monotonic() + 1)
            sender.close()
            receiver.close()
            listener.close()

    def test_post_stop_diagnostic_crash_is_recorded_once(self, tmp_path: Path) -> None:
        """A final retention failure remains visible after stop and is never counted as a fence."""
        config, owner = self._config(self._socket_path()), self._owner()
        diagnostics = _CrashAfterStopDiagnostics(
            config,
            (owner,),
            root=tmp_path / "monitoring",
            deadline=time.monotonic() + 10,
            runs=tmp_path / "runs",
        )
        diagnostics.start()
        try:
            self._wait_diagnostic_marker(diagnostics)
            diagnostics.request_stop()
            diagnostics.close(deadline=time.monotonic() + 1)
            assert diagnostics.status()["alive"] is False
            assert diagnostics.status()["exitcode"] == 1
            assert diagnostics.status()["forced_fence"] is False
            assert diagnostics.failure_count == 1
            assert diagnostics.last_error == "diagnostic_process_exit:1"
            assert diagnostics.poll() == ()
            assert diagnostics.failure_count == 1
        finally:
            diagnostics.close(deadline=time.monotonic() + 1)
