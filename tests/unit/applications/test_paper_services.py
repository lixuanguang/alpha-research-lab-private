"""Exercise local paper supervision failure paths without starting account services."""

from __future__ import annotations

# standard library imports
import multiprocessing
import os
import socket
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import cast
from uuid import uuid4

# third party library imports
import pytest

# project library imports
from accounting import AccountLedger, AccountPosting, AccountState, Fill, PaperAccountReport
from applications.execute.service_inputs import ServiceBookInputs
from applications.execute.service_monitor import PaperServiceMonitor
from applications.execute.services import (
    PaperServiceControl,
    PaperServiceOwners,
    PaperServices,
    _SourceChild,
)
from applications.execute.source_service import SourceDelivery
from configuration import (
    AccountConfiguration,
    CaptureConfig,
    OpeningAccount,
    PaperExecutionScenario,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
)
from execution import (
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
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    InstalledIdentity,
    PolicyProcessFailure,
    ProcessDecisionPolicy,
    SharedPaperCaptureObserver,
)
from serialization import DomainCodec
from telemetry import HealthMetrics


class _AliveSource(multiprocessing.Process):
    """Represent a source that remains alive while one delivered frame fails."""

    def is_alive(self) -> bool:
        """Keep source loss separate from observer uncertainty."""
        return True


class _ChangingWorker(ProcessDecisionPolicy):
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


class _StableWorker(ProcessDecisionPolicy):
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
        self.inputs = ServiceBookInputs(("first",), 30_000_000)
        self.calls = 0
        self.policy_failure = policy_failure

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Fail after receipt without claiming whether the account committed."""
        self.calls += 1
        if self.policy_failure:
            raise PolicyProcessFailure(123, "decision policy process unavailable")
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
    def _socket_path() -> Path:
        """Stay below the platform's AF_UNIX pathname limit."""
        return Path("/private/tmp") / f"ps-{uuid4().hex[:12]}.sock"

    @staticmethod
    def _config(socket_path: Path) -> PaperServiceConfiguration:
        """Provision one bounded account, source and selected policy."""
        capture = CaptureConfig.read(Path("configs/live/okx-btc-usdt.json"))
        currency = Currency.from_code("USDT")
        dimension = Dimension(instrument_id=capture.instrument_id, kind=QuantityKind.BASE_UNIT)
        cash = Money(value=Decimal("1000"), currency=currency)
        quantity = Quantity(value=Decimal("1"), dimension=dimension)
        price = Price(value=Decimal("0.01"), currency=currency, per=dimension)
        account = AccountConfiguration(
            mode="paper",
            opening_at=datetime(2026, 9, 27, tzinfo=UTC),
            accounts=(OpeningAccount(account_id="shared", cash=(cash,)),),
            instruments=(SpotLimits(maximum=quantity, lot=quantity, tick=price, product="spot"),),
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
                    policy="fixed_clip",
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
        isolated = AccountConfiguration(
            mode=shared.mode,
            opening_at=shared.opening_at,
            accounts=(OpeningAccount(account_id="isolated", cash=(cash,)),),
            instruments=shared.instruments,
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
                    policy=first.policy,
                    quantity=first.quantity,
                    lot=first.lot,
                    maximum_fee=first.maximum_fee,
                ),
            ),
            sources=original.sources,
            active=("first", "other"),
            revision=original.revision,
        )

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
    def _delivery() -> SourceDelivery:
        """Pass one typed, already persisted source boundary through the pipe."""
        return SourceDelivery(
            record=CaptureRecord(kind="session", epoch=0, received_ns=1),
            book=BookObservation(
                position=0,
                epoch=0,
                received_ns=1,
                source_time=None,
                sequence=None,
                outcome="session",
                status="recovering",
                reason="awaiting snapshot",
                state_identity="1" * 64,
            ),
        )

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

    def test_restart_observation_precedes_restart_and_preserves_other_account(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One typed control reconciles before a restart, with no intervening scheduling."""
        monkeypatch.setattr(InstalledIdentity, "sha256", staticmethod(lambda: "b" * 64))
        config = self._two_account_config()
        owners = (self._owner(), self._owner("isolated"))
        codec = DomainCodec()

        def harness(label: str, *, accepts: bool) -> tuple[_SupervisorHarness, list[str]]:
            """Retain independent account and scheduler calls for one restart attempt."""
            events: list[str] = []
            (tmp_path / label).mkdir()
            services = _SupervisorHarness(
                config, owners, tmp_path / label, self._socket_path(), events
            )
            services.active.remove("first")
            services.workers["other"] = _StableWorker()
            services.accounts["shared"] = _RestartAccount(
                config.accounts[0].configuration, owners[0], events, accepts_observation=accepts
            )
            services.accounts["isolated"] = _RestartAccount(
                config.accounts[1].configuration, owners[1], events, accepts_observation=True
            )
            return services, events

        observation = self._observation("shared", config.accounts[0].configuration)
        control = PaperServiceControl(
            action="restart_instance",
            identity="restart-with-observation",
            subject="first",
            observation=observation,
        )
        assert codec.decode_json(codec.encode_json(control), PaperServiceControl) == control
        accepted, accepted_events = harness("accepted", accepts=True)
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

        mismatch, mismatch_events = harness("mismatch", accepts=True)
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

        rejected, rejected_events = harness("rejected", accepts=False)
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
        monkeypatch.setattr(InstalledIdentity, "sha256", staticmethod(lambda: "b" * 64))
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
            services.sources["book"] = _SourceChild(
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
