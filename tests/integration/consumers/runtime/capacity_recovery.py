"""Measure finite paper-service fault fencing and four-owner local recovery."""

from __future__ import annotations

# standard library imports
import hashlib
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

# third party library imports
import msgspec

# project library imports
from accounting import AccountLedger
from configuration import PaperServiceAccount
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountObservation,
    AccountPaperTrace,
    AccountQuote,
    InstalledPaperAccount,
    PaperMarket,
    PaperOwner,
)
from financial_units import Price
from serialization import DomainCodec

if TYPE_CHECKING:
    # third party library imports
    from capacity_trial import CapacityTrial


class _SourceHealth(msgspec.Struct, frozen=True):
    """Read the minimum native source fields needed for a resynchronization witness."""

    pid: int
    alive: bool
    markets: tuple[object | None, ...]


class _SourceStatus(msgspec.Struct, frozen=True):
    """Read an atomic supervisor status without decoding unrelated telemetry."""

    sources: dict[str, _SourceHealth]


class _RetainedRequest(msgspec.Struct, frozen=True):
    """Freeze a request's exact bytes in the namespace removed by an obstruction."""

    name: str
    payload: bytes
    modified_ns: int
    stable_before_cutoff: bool


class CapacityRecovery:
    """Own one-shot fault probes and explicit four-account replacement claims.

    A probe never retries an uncertain account request. The former service must
    be stopped before replacement claims, and every accounting assertion uses
    the independently predeclared two-unit first-touch oracle.
    """

    def __init__(self, trial: CapacityTrial) -> None:
        """Bind one running or stopped trial and its retained operating paths."""
        self.trial = trial
        self.codec = DomainCodec()
        self.operator_started_at: float | None = None
        self.first_claim_started_at: float | None = None
        self.before_checkpoints: dict[str, bytes | None] = {}
        self._claim_lock = threading.Lock()
        self._record_lock = threading.Lock()

    @staticmethod
    def _alive(pid: int) -> bool:
        """Report whether an owned child identity still exists on this host."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def _instance_stopped(self, instance_id: str) -> bool:
        """Observe removal from the supervisor's active policy selection."""
        return instance_id not in self.trial.status().active

    def _account_faulted(self, account_id: str) -> bool:
        """Observe retained account-wide supervisor protection."""
        return account_id in self.trial.status().faulted_accounts

    def _accounts_faulted(self, accounts: set[str]) -> bool:
        """Observe protection of every account depending on a failed source."""
        return accounts.issubset(self.trial.status().faulted_accounts)

    def _request_fenced(self, worker_pid: int, account_id: str) -> bool:
        """Require the failed request worker gone and its owner account fenced."""
        return not self._alive(worker_pid) and self._account_faulted(account_id)

    def worker_death(self, instance_id: str) -> float:
        """Kill one policy and measure selective dependent stop within two seconds."""
        definition = next(
            (item for item in self.trial.config.instances if item.instance_id == instance_id), None
        )
        if definition is None:
            raise ValueError("unknown capacity policy for death probe")
        before = self.trial.status()
        child = before.workers.get(instance_id)
        if child is None or child.pid is None or not child.alive:
            raise ValueError("capacity policy is not alive before death probe")
        survivors = {
            item.instance_id
            for item in self.trial.config.instances
            if item.account_id == definition.account_id and item.instance_id != instance_id
        }
        if (
            instance_id not in before.active
            or not survivors.issubset(before.active)
            or definition.account_id in before.faulted_accounts
        ):
            raise ValueError("policy death requires an active unfaulted account")
        started = time.monotonic()
        os.kill(child.pid, signal.SIGKILL)
        self.trial.record(
            "policy_death_injected",
            {
                "instance": instance_id,
                "pid": child.pid,
                "injected_monotonic": started,
                "before_status": before,
            },
        )
        self.trial.wait_until(partial(self._instance_stopped, instance_id), 2)
        elapsed = time.monotonic() - started
        after = self.trial.status()
        if (
            elapsed > 2
            or not survivors.issubset(after.active)
            or definition.account_id in after.faulted_accounts
        ):
            raise AssertionError("selective policy death exceeded or broke MR14 protection")
        state = self.trial.clients[definition.account_id].execute(
            AccountExecutionRequest(action="inspect")
        )
        if instance_id not in state.stopped_instances or state.accounts[0].phase != "running":
            raise AssertionError("selective policy death did not persist a stopped instance")
        self.trial.record(
            "policy_death_fenced",
            {
                "instance": instance_id,
                "pid": child.pid,
                "response_seconds": elapsed,
                "child_exists_at_fence": self._alive(child.pid),
                "survivors": tuple(sorted(survivors)),
                "status": after,
            },
        )
        return elapsed

    def account_death(self, account_id: str) -> float:
        """Kill a signed owner process and measure account-wide stop within two seconds."""
        pid = self.trial.account_pids.get(account_id)
        if pid is None or not self._alive(pid):
            raise ValueError("signed account process is not alive before death probe")
        dependent = {
            item.instance_id
            for item in self.trial.config.instances
            if item.account_id == account_id
        }
        before = self.trial.status()
        if account_id in before.faulted_accounts or not dependent.issubset(before.active):
            raise ValueError("account owner death requires active unfaulted dependents")
        started = time.monotonic()
        os.kill(pid, signal.SIGKILL)
        self.trial.record(
            "account_owner_death_injected",
            {
                "account": account_id,
                "pid": pid,
                "injected_monotonic": started,
                "before_status": before,
            },
        )
        self.trial.wait_until(partial(self._account_faulted, account_id), 2)
        elapsed = time.monotonic() - started
        after = self.trial.status()
        if elapsed > 2 or dependent.intersection(after.active):
            raise AssertionError("signed owner death left dependent policy work active")
        self.trial.record(
            "account_owner_death_fenced",
            {
                "account": account_id,
                "pid": pid,
                "response_seconds": elapsed,
                "status": after,
            },
        )
        return elapsed

    def source_death(self, source_name: str) -> tuple[float, float]:
        """Measure two-second source fault and eight-second native resynchronization."""
        definition = next(
            (source for source in self.trial.config.sources if source.name == source_name), None
        )
        if definition is None:
            raise ValueError("unknown native source for death probe")
        before = self.trial.status()
        child = before.sources.get(source_name)
        if child is None or child.pid is None or not child.alive:
            raise ValueError("native source is not alive before death probe")
        old_pid = child.pid
        accounts = {
            item.account_id for item in self.trial.config.instances if item.source == source_name
        }
        dependent = {
            item.instance_id for item in self.trial.config.instances if item.source == source_name
        }
        if accounts.intersection(before.faulted_accounts) or not dependent.issubset(before.active):
            raise ValueError("source death requires active unfaulted dependents")
        started = time.monotonic()
        os.kill(old_pid, signal.SIGKILL)
        self.trial.record(
            "source_death_injected",
            {
                "source": source_name,
                "pid": old_pid,
                "injected_monotonic": started,
                "before_status": before,
            },
        )
        self.trial.wait_until(partial(self._accounts_faulted, accounts), 2)
        fenced = time.monotonic() - started
        after = self.trial.status()
        if fenced > 2 or dependent.intersection(after.active):
            raise AssertionError("source death left dependent paper work active")
        restarted_at = time.monotonic()
        self.trial.record(
            "source_restart_requested",
            {"source": source_name, "requested_monotonic": restarted_at},
        )
        self.trial.control("restart_source", source_name)
        self.trial.wait_until(
            partial(self._source_usable, source_name, old_pid, accounts, dependent),
            max(0.01, 8 - (time.monotonic() - restarted_at)),
        )
        usable = time.monotonic() - restarted_at
        if usable > 8:
            raise AssertionError("native source recovery exceeded eight seconds")
        self.trial.record(
            "source_death_and_protected_recovery",
            {
                "source": source_name,
                "old_pid": old_pid,
                "fault_response_seconds": fenced,
                "restart_to_usable_seconds": usable,
                "accounts_remain_protected": tuple(sorted(accounts)),
            },
        )
        return fenced, usable

    def _source_usable(
        self,
        source_name: str,
        old_pid: int,
        accounts: set[str],
        dependent: set[str],
    ) -> bool:
        """Require a new live source with a native market while all owners stay fenced."""
        status = self.trial.status()
        if not accounts.issubset(status.faulted_accounts) or dependent.intersection(status.active):
            return False
        path = self.trial.service_root / "status.json"
        parsed = msgspec.json.decode(path.read_bytes(), type=_SourceStatus)
        source = parsed.sources.get(source_name)
        return bool(
            source is not None
            and source.pid != old_pid
            and source.alive
            and any(market is not None for market in source.markets)
            and self._alive(source.pid)
        )

    def request_retention_failure(self, account_id: str, instance_id: str) -> float:
        """Obstruct one request journal and measure six-second account fencing."""
        definition = next(
            (item for item in self.trial.config.instances if item.instance_id == instance_id), None
        )
        if definition is None or definition.account_id != account_id:
            raise ValueError("request-retention target differs from selected account")
        status_before = self.trial.status()
        worker = status_before.workers.get(instance_id)
        if worker is None or worker.pid is None or not worker.alive:
            raise ValueError("request-retention target policy is not alive")
        if account_id in status_before.faulted_accounts or instance_id not in status_before.active:
            raise ValueError("request-retention fault requires an active unfaulted account")
        worker_pid = worker.pid
        client = self.trial.clients[account_id]
        before = client.execute(AccountExecutionRequest(action="inspect"))
        before_checkpoint = client.checkpoint(instance_id)
        if before.journal_path is None:
            raise ValueError("request-retention probe lacks a current account journal")
        path = Path(before.journal_path).parent / "service-requests"
        retained = path.with_name(f"service-requests-retained-{uuid4().hex}")
        marker = "capacity request-retention obstruction\n"
        path.rename(retained)
        started = time.monotonic()
        cutoff_ns = time.time_ns()
        cutoff_at = datetime.now(UTC)
        try:
            # New requests still name the original directory. Freeze its removed
            # namespace before restoration, including exact in-flight file bytes.
            frozen_names = tuple(sorted(retained.glob("*.json")))
            path.write_text(marker)
            frozen = tuple(self._freeze_retained_request(item, cutoff_ns) for item in frozen_names)
            self.trial.record(
                "request_retention_obstructed",
                {
                    "account": account_id,
                    "instance": instance_id,
                    "worker_pid": worker_pid,
                    "injected_monotonic": started,
                    "retention_cutoff_at": cutoff_at,
                    "retention_cutoff_ns": cutoff_ns,
                    "retained_path": str(retained),
                    "frozen_request_count": len(frozen),
                    "before_status": status_before,
                },
            )
            self.trial.wait_until(
                partial(self._request_fenced, worker_pid, account_id),
                6,
            )
            elapsed = time.monotonic() - started
            if elapsed > 6 or instance_id in self.trial.status().active:
                raise AssertionError("request-retention fault did not fence account in six seconds")
        finally:
            if path.is_file() and path.read_text() == marker:
                path.unlink()
            elif path.exists():
                raise RuntimeError("request-retention obstruction changed before restore")
            retained.rename(path)
        after = client.execute(AccountExecutionRequest(action="inspect"))
        after_checkpoint = client.checkpoint(instance_id)
        passed, witness = self._request_retention_proof(
            account_id, before, after, before_checkpoint, after_checkpoint, frozen
        )
        witness.update(
            account=account_id,
            instance=instance_id,
            injected_monotonic=started,
            retention_cutoff_at=cutoff_at,
            retention_cutoff_ns=cutoff_ns,
            response_seconds=elapsed,
            obstruction_restored=True,
        )
        witness_path = self.trial.output / f"request-retention-{account_id}-witness.json"
        payload = self.codec.encode_json(witness)
        with witness_path.open("xb") as stream:
            stream.write(payload)
        self.trial.record(
            "request_retention_witness",
            {
                "account": account_id,
                "passed": passed,
                "path": str(witness_path),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
        )
        if not passed:
            raise AssertionError("failed request changed committed economics or policy checkpoint")
        self.trial.record(
            "request_retention_failure_fenced",
            {
                "account": account_id,
                "instance": instance_id,
                "worker_pid": worker_pid,
                "response_seconds": elapsed,
                "economics_unchanged": True,
                "concurrent_trace_appends": len(after.paper_traces) - len(before.paper_traces),
                "trace_appends_attributed_to_frozen_requests": True,
                "obstruction_restored": True,
            },
        )
        return elapsed

    @staticmethod
    def _freeze_retained_request(path: Path, cutoff_ns: int) -> _RetainedRequest:
        """Reject attribution from a file changed after the removed directory's cutoff."""
        before = path.stat()
        payload = path.read_bytes()
        after = path.stat()
        return _RetainedRequest(
            name=path.name,
            payload=payload,
            modified_ns=after.st_mtime_ns,
            stable_before_cutoff=(
                before.st_mtime_ns == after.st_mtime_ns <= cutoff_ns
                and before.st_size == after.st_size == len(payload)
                and before.st_ino == after.st_ino
            ),
        )

    @staticmethod
    def _request_retention_fields(result: AccountExecutionResult) -> dict[str, object]:
        """Compare complete economic facts without discarding child or net order state."""
        return {
            "ledger": tuple(account.ledger for account in result.accounts),
            "orders": result.orders,
            "net_orders": result.net_orders,
            "paper_fills": result.paper_fills,
            "paper_costs": result.paper_costs,
        }

    def _request_retention_proof(
        self,
        account_id: str,
        before: AccountExecutionResult,
        after: AccountExecutionResult,
        before_checkpoint: bytes | None,
        after_checkpoint: bytes | None,
        frozen: tuple[_RetainedRequest, ...],
    ) -> tuple[bool, dict[str, object]]:
        """Attribute only benign trace appends to requests frozen at the rename boundary."""
        left, right = self._request_retention_fields(before), self._request_retention_fields(after)
        comparisons = {
            name: {
                "equal": value == right[name],
                "before": value,
                "after": right[name],
                "before_sha256": hashlib.sha256(self.codec.encode_json(value)).hexdigest(),
                "after_sha256": hashlib.sha256(self.codec.encode_json(right[name])).hexdigest(),
            }
            for name, value in left.items()
        }
        checkpoint_equal = before_checkpoint == after_checkpoint
        comparisons["checkpoint"] = {
            "equal": checkpoint_equal,
            "before": before_checkpoint,
            "after": after_checkpoint,
            "before_sha256": (
                hashlib.sha256(before_checkpoint).hexdigest()
                if before_checkpoint is not None
                else None
            ),
            "after_sha256": (
                hashlib.sha256(after_checkpoint).hexdigest()
                if after_checkpoint is not None
                else None
            ),
        }
        requests: list[dict[str, object]] = []
        decoded: list[tuple[_RetainedRequest, AccountExecutionRequest]] = []
        for item in frozen:
            evidence: dict[str, object] = {
                "name": item.name,
                "payload": item.payload,
                "sha256": hashlib.sha256(item.payload).hexdigest(),
                "modified_ns": item.modified_ns,
                "stable_before_cutoff": item.stable_before_cutoff,
            }
            try:
                request = self.codec.decode_json(item.payload, AccountExecutionRequest)
            except ValueError as error:
                evidence.update(valid=False, error=f"{type(error).__name__}: {error}")
            else:
                evidence.update(valid=True, action=request.action)
                decoded.append((item, request))
            requests.append(evidence)
        prefix_equal = after.paper_traces[: len(before.paper_traces)] == before.paper_traces
        appends = after.paper_traces[len(before.paper_traces) :]
        prior_ids = {trace.input_sha256 for trace in before.paper_traces}
        append_ids = {trace.input_sha256 for trace in appends}
        unique_appends = len(append_ids) == len(appends) and not prior_ids.intersection(append_ids)
        attribution = tuple(
            self._retained_trace_proof(account_id, trace, decoded) for trace in appends
        )
        attributed = all(item["attributed"] is True for item in attribution)
        passed = (
            all(value == right[name] for name, value in left.items())
            and checkpoint_equal
            and prefix_equal
            and unique_appends
            and attributed
        )
        return passed, {
            "schema_version": "request-retention-witness-v1",
            "passed": passed,
            "comparisons": comparisons,
            "trace_prefix_equal": prefix_equal,
            "trace_append_identities_unique": unique_appends,
            "before_traces": before.paper_traces,
            "after_traces": after.paper_traces,
            "appended_traces": attribution,
            "frozen_requests": tuple(requests),
        }

    def _retained_trace_proof(
        self,
        account_id: str,
        trace: AccountPaperTrace,
        decoded: list[tuple[_RetainedRequest, AccountExecutionRequest]],
    ) -> dict[str, object]:
        """Require exact input lineage and no modeled economic effects in an allowed append."""
        matches = tuple(
            {
                "name": item.name,
                "sha256": hashlib.sha256(item.payload).hexdigest(),
                "modified_ns": item.modified_ns,
            }
            for item, request in decoded
            if request.action == "paper_market"
            and item.stable_before_cutoff
            and request.account_id == trace.account_id == account_id
            and request.paper_owner is not None
            and request.paper_owner.account_id == account_id
            and request.market == trace.market
            and request.scenario == trace.scenario
            and hashlib.sha256(
                self.codec.encode_json((request.account_id, request.market, request.scenario))
            ).hexdigest()
            == trace.input_sha256
        )
        benign = (
            trace.status == "committed"
            and not trace.physical_events
            and not trace.child_fill_events
            and trace.rejected_event is None
        )
        return {
            "input_sha256": trace.input_sha256,
            "market_identity": trace.market.identity,
            "trace": trace,
            "retained_requests": matches,
            "no_economic_events": benign,
            "attributed": bool(matches) and benign,
        }

    def recover_four_owners(self) -> float:
        """Settle exact paper facts and claim four generations before a new service launch.

        Returns:
            Monotonic time immediately before the first actual replacement claim
            request. The caller measures all eight fresh checkpoint advances from
            this instant; operator preparation starts earlier and is reported
            separately.
        """
        if len(self.trial.config.accounts) != 4 or len(self.trial.config.instances) != 8:
            raise ValueError("four-owner recovery requires the declared capacity topology")
        if self.trial.variant != "base" or self.trial.public_venue is not None:
            raise ValueError("four-owner recovery oracle requires a successful base fixture trial")
        if self.trial.supervisor is not None and self.trial.supervisor.poll() is None:
            raise ValueError("replacement claims require the prior supervisor stopped")
        self.operator_started_at = time.monotonic()
        self.trial.record("recovery_operator_started", {"accounts": 4, "instances": 8})
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._recover_owner, account): account.account_id
                for account in self.trial.config.accounts
            }
            failures: list[Exception] = []
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as error:
                    self._record(
                        "recovery_owner_failure",
                        {"account": futures[future], "error": f"{type(error).__name__}: {error}"},
                    )
                    failures.append(error)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise ExceptionGroup("independent owner recoveries failed", failures)
        if self.first_claim_started_at is None:
            raise AssertionError("four-owner recovery issued no replacement claim")
        self.trial.record(
            "recovery_claims_prepared",
            {
                "operator_to_claims_prepared_seconds": time.monotonic() - self.operator_started_at,
                "first_claim_started_at": self.first_claim_started_at,
            },
        )
        return self.first_claim_started_at

    def _record(self, kind: str, values: object) -> None:
        """Serialize evidence append from independent owner recovery threads."""
        with self._record_lock:
            self.trial.record(kind, values)

    def _recover_owner(self, account: PaperServiceAccount) -> None:
        """Settle and replace one signed owner in its required local sequence."""
        name = account.account_id
        self._record("recovery_owner_started", {"account": name})
        admin = self.trial.admin(name)
        state = admin.execute(AccountExecutionRequest(action="inspect"))
        if len(state.paper_activations) != 1:
            raise ValueError("recovery requires one retained signed paper activation")
        old = state.paper_activations[0].owner
        if old is None:
            raise ValueError("recovery requires the prior signed account owner")
        authorization = state.paper_activations[0].authorization
        if (
            authorization is None
            or datetime.now(UTC) + timedelta(seconds=120) >= authorization.expires_at
        ):
            raise ValueError("recovery grant lacks 120-second headroom")
        names = tuple(
            item.instance_id for item in self.trial.config.instances if item.account_id == name
        )
        before = {item: admin.checkpoint(item) for item in names}
        if any(checkpoint is None for checkpoint in before.values()):
            raise ValueError("recovery requires all prior policy checkpoints")
        self.before_checkpoints.update(before)
        admin.paper_owner = old
        stop = admin.control(
            AccountControl(
                identity=uuid4().hex,
                account_id=name,
                kind="stop",
                at=datetime.now(UTC),
                reason="bounded capacity replacement claim",
            )
        )
        if stop.status != "applied":
            raise ValueError(f"recovery stop refused for {name}: {stop.reason}")
        cancel = admin.control(
            AccountControl(
                identity=uuid4().hex,
                account_id=name,
                kind="cancel",
                at=datetime.now(UTC),
                reason="settle local paper obligations",
            )
        )
        if cancel.status != "applied":
            raise ValueError(f"recovery cancellation refused for {name}: {cancel.reason}")
        # The signed paper scenario requires a two-millisecond cancel delay;
        # settle only after that interval has elapsed on the actual clock.
        time.sleep(0.01)
        deployment = state.paper_activations[0].deployment
        venue = account.account_id.split("-", maxsplit=1)[0]
        workload = self.trial.workload.venue_workload(venue)
        for scenario in deployment.scenarios:
            at = datetime.now(UTC)
            market = PaperMarket(
                identity=uuid4().hex,
                at=at,
                bid=workload.price("99", scenario.adverse.per),
                ask=workload.price("104", scenario.adverse.per),
                bid_quantity=workload.quantity("4", scenario.adverse.per),
                ask_quantity=workload.quantity("4", scenario.adverse.per),
            )
            # Keep the original 100 reference: a 104 quote makes the
            # retained 98 sell limits exceed the unchanged 5% risk band.
            admin.observe(AccountQuote(price=workload.price("100", scenario.adverse.per), at=at))
            admin.match_public_market(name, market, scenario)
        settled = admin.execute(AccountExecutionRequest(action="inspect"))
        with (self.trial.output / f"recovery-settled-{name}.json").open("xb") as stream:
            stream.write(self.codec.encode_json(settled))
        snapshot = AccountLedger(settled.accounts[0].ledger).snapshot()
        self._require_first_touch(name, settled)
        opened = tuple(item.order for item in settled.net_orders if not item.order.is_terminal)
        if any(not item.accepted or item.cancel_requested for item in opened):
            raise ValueError("recovery has unsettled or uncertain physical orders")
        if not admin.reconcile(
            AccountObservation(
                identity=uuid4().hex,
                at=datetime.now(UTC),
                snapshot=snapshot,
                open_orders=opened,
            )
        ):
            raise ValueError("recovery complete independent facts did not reconcile")
        self._record(
            "recovery_owner_reconciled",
            {"account": name, "open_order_ids": tuple(item.identity for item in opened)},
        )
        request = AccountExecutionRequest(
            action="claim_paper",
            account_id=name,
            owner_id=f"capacity-{name}-{uuid4().hex[:8]}",
            control=AccountControl(
                identity=uuid4().hex,
                account_id=name,
                kind="restart",
                at=datetime.now(UTC),
                expected_control_identity=stop.request.identity,
            ),
        )
        with self._claim_lock:
            claim_started_at = time.monotonic()
            is_first_claim = self.first_claim_started_at is None
            if is_first_claim:
                self.first_claim_started_at = claim_started_at
        try:
            claimed = admin.execute(request).claimed_owner
        finally:
            self._record(
                "replacement_claim_requested",
                {
                    "account": name,
                    "monotonic": claim_started_at,
                    "is_first": is_first_claim,
                },
            )
        if claimed is None or claimed.generation != old.generation + 1:
            raise ValueError("replacement claim did not advance the signed owner generation")
        admin.paper_owner = claimed
        for instance_id in settled.stopped_instances:
            if not admin.reconcile(
                AccountObservation(
                    identity=uuid4().hex,
                    at=datetime.now(UTC),
                    snapshot=snapshot,
                    open_orders=opened,
                )
            ):
                raise ValueError("instance restart lacks a fresh complete observation")
            admin.execute(
                AccountExecutionRequest(
                    action="restart_instance",
                    instance_id=instance_id,
                    at=datetime.now(UTC),
                    paper_owner=claimed,
                )
            )
        self._require_replaced_owner_fenced(
            admin, old, claimed, workload.price("104", deployment.scenario.adverse.per)
        )
        if {item: admin.checkpoint(item) for item in names} != {
            item: self.before_checkpoints[item] for item in names
        }:
            raise AssertionError("replacement claim changed a policy checkpoint")
        self.trial.owners[name] = claimed
        self._record(
            "recovery_owner_claimed",
            {
                "account": name,
                "old_generation": old.generation,
                "new_generation": claimed.generation,
                "snapshot": snapshot,
                "open_order_ids": tuple(item.identity for item in opened),
                "checkpoints": {item: self.before_checkpoints[item] for item in names},
            },
        )

    def _require_replaced_owner_fenced(
        self,
        admin: InstalledPaperAccount,
        old: PaperOwner,
        current: PaperOwner,
        price: Price,
    ) -> None:
        """Check the old token's exact denial and current token's installed quote path."""
        stale = AccountExecutionRequest(
            action="quote",
            quote=AccountQuote(price=price, at=datetime.now(UTC)),
            paper_owner=old,
            projection="operation",
        )
        stem = hashlib.sha256(self.codec.encode_json(stale)).hexdigest()
        prior = set(admin.requests.glob(f"{stem}.*.stderr"))
        try:
            admin.execute(stale)
        except RuntimeError:
            receipts = set(admin.requests.glob(f"{stem}.*.stderr")) - prior
            if (
                len(receipts) != 1
                or b"paper_owner_stale_or_absent" not in next(iter(receipts)).read_bytes()
            ):
                raise AssertionError("replaced owner denial had a different cause") from None
        else:
            raise AssertionError("replaced signed owner remained usable")
        admin.paper_owner = current
        admin.observe(AccountQuote(price=price, at=datetime.now(UTC)))
        self._record(
            "replaced_owner_fenced",
            {"account": old.account_id, "old_generation": old.generation},
        )

    def _require_first_touch(self, account_id: str, state: AccountExecutionResult) -> None:
        """Require the exact predeclared two-unit economics before reusing a journal."""
        snapshot = AccountLedger(state.accounts[0].ledger).snapshot()
        cash, fee, positions = self.trial.workload.first_touch_oracle()[account_id]
        if (snapshot.cash, snapshot.fees, snapshot.positions) != ((cash,), (fee,), positions):
            raise AssertionError("recovery first-touch cash, fee or position differs")
        names = {
            item.instance_id
            for item in self.trial.config.instances
            if item.account_id == account_id
        }
        fills = {item.instance_id: item.fill.quantity for item in state.paper_fills}
        if (
            set(fills) != names
            or len(state.paper_fills) != 2
            or any(quantity.value != 1 for quantity in fills.values())
        ):
            raise AssertionError("recovery attributed fill identities or quantities differ")
