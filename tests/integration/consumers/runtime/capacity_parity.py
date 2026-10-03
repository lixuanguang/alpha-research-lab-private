"""Replay retained capacity deliveries into fresh local paper journals.

This is a software economic reference over the signed run's exact selected
deliveries. The replay has no deployment, authorization, owner, or submission
authority. Its result must agree with the separately retained signed facts.
"""

from __future__ import annotations

# standard library imports
import argparse
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar

# third party library imports
import msgspec
from capacity_inputs import CapacityWorkload

# project library imports
from accounting import AccountLedger, AccountState
from applications.execute.service_inputs import ServiceBookInputs
from configuration import (
    BookRegistryConfiguration,
    BookSelection,
    PaperServiceAccount,
    PaperServiceConfiguration,
    PaperServiceInstance,
    PaperServiceSource,
)
from execution import AccountExecutionRequest, AccountExecutionResult, AccountJournal, AccountQuote
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.contracts import RecordingRequest
from market_data.storage import CaptureRecording
from portfolio import PortfolioContext
from research.observations import LiveBookDecisionSource
from runtime import (
    InstalledIdentity,
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
)
from serialization import DomainCodec
from strategies import reference_policy


class _TrialSummary(msgspec.Struct):
    """Read the installed implementation selected for the measured trial."""

    implementation: str


class _Arguments(argparse.Namespace):
    """Carry three absolute paths for an offline parity invocation."""

    root: Path
    trial: Path
    output: Path
    baseline: Path | None


class _ObservationKind(msgspec.Struct, frozen=True):
    """Select immutable account-fact observations without interpreting unrelated rows."""

    kind: str


class _AccountFacts(msgspec.Struct, frozen=True):
    """Read exact continuation bytes frozen after the supervisor stopped."""

    label: str
    account: str
    checkpoints: dict[str, bytes | None]


class _AccountFactsObservation(msgspec.Struct, frozen=True):
    """Decode the original account-fact envelope and its retained checkpoints."""

    values: _AccountFacts


class CapacityEconomicParity:
    """Compare every retained economic fact to a fresh unmanaged replay."""

    fields: ClassVar[tuple[str, ...]] = (
        "ledger",
        "orders",
        "net_orders",
        "paper_fills",
        "paper_costs",
        "paper_traces",
        "checkpoints",
    )

    def __init__(self, root: Path, trial: Path) -> None:
        """Bind one prepared selection and one completed installed trial."""
        if not root.is_absolute() or not trial.is_absolute():
            raise ValueError("capacity economic parity requires absolute input paths")
        self.root, self.trial = root, trial
        self.codec = DomainCodec()
        self.prepared = self.codec.decode_json(
            (root / "preparation/services-initial.json").read_bytes(),
            PaperServiceConfiguration,
        )
        self.service = self.codec.decode_json(
            (trial / "configuration.json").read_bytes(), PaperServiceConfiguration
        )
        if (
            self.service.accounts != self.prepared.accounts
            or self.service.sources != self.prepared.sources
            or self.service.instances != self.prepared.instances
            or self.service.active != self.prepared.active
        ):
            raise ValueError("trial economic selection differs from prepared input")
        self.implementation = self.codec.decode_json(
            (trial / "summary.json").read_bytes(), _TrialSummary
        ).implementation
        if len(self.implementation) != 64 or any(
            character not in "0123456789abcdef" for character in self.implementation
        ):
            raise ValueError("trial has no installed implementation identity")
        self.replay_implementation = InstalledIdentity.sha256()
        runs_root = trial / "operating/runs"
        run_directories = tuple(path for path in runs_root.iterdir() if path.is_dir())
        if len(run_directories) != 1:
            raise ValueError("capacity parity requires one retained supervisor run")
        self.run_directory = run_directories[0]
        mode = self.service.accounts[0].configuration.mode
        if mode not in ("paper", "shadow"):
            raise ValueError("capacity parity requires paper or shadow account mode")
        self.workload = CapacityWorkload(
            opening_at=self.service.accounts[0].configuration.opening_at,
            socket_root=Path(self.service.accounts[0].socket_path).parent,
            mode=mode,
        )

    def _bindings(
        self, account: PaperServiceAccount, source: PaperServiceSource
    ) -> tuple[SharedStrategyBinding, ...]:
        """Rebuild exactly the installed reference policy identities and context."""
        bindings: list[SharedStrategyBinding] = []
        for instance in self.service.instances:
            if instance.account_id != account.account_id:
                continue
            if instance.source != source.name or instance.instance_id not in self.service.active:
                raise ValueError("capacity account has a changed source or active cohort")
            bindings.append(self._binding(account, source, instance))
        if len(bindings) != 2:
            raise ValueError("capacity account lacks two selected reference instances")
        return tuple(bindings)

    def _binding(
        self,
        account: PaperServiceAccount,
        source: PaperServiceSource,
        instance: PaperServiceInstance,
    ) -> SharedStrategyBinding:
        """Use the service's exact policy constructor arguments without a worker."""
        policy = reference_policy(
            instance.policy,
            instance.quantity,
            source.scenario.adverse.currency,
            instance.lot,
            tick=self.service.instance_limits(instance).tick,
            implementation=self.implementation,
        )
        return SharedStrategyBinding(
            instance_id=instance.instance_id,
            account_id=account.account_id,
            entity=str(source.scenario.instrument_id),
            policy=policy,
            context=PortfolioContext(
                portfolio_id="reference",
                strategy_id=instance.instance_id,
                model_revision="rule-only",
                config_revision="paper-services",
                horizon="capture",
                reason="engineering-reference",
                venue=source.capture.venue,
                settlement="spot",
                risk_bucket="cash",
                authority_scope=account.configuration.mode,
            ),
            maximum_fee=instance.maximum_fee,
        )

    def _streams(
        self, account_id: str, source: PaperServiceSource
    ) -> tuple[tuple[RecordingRequest, tuple[SharedBookDelivery, ...]], ...]:
        """Verify complete canonical logs and exact request/source identities."""
        source_directory = self.run_directory / source.name
        paths = tuple(source_directory.glob(f"*-{account_id}.jsonl"))
        if not paths:
            raise ValueError(f"capacity account has no retained delivery stream: {account_id}")
        streams: list[tuple[RecordingRequest, tuple[SharedBookDelivery, ...]]] = []
        for path in paths:
            # A single recording or a whole segment chain, named by its recording key.
            key = path.name.removesuffix(f"-{account_id}.jsonl")
            request = CaptureRecording.read(source_directory / key / key).request
            if (
                request.recording_key != key
                or request.config != source.capture
                or request.implementation_identity != self.implementation
            ):
                raise ValueError("retained delivery request differs from signed source")
            raw = path.read_bytes()
            if not raw or not raw.endswith(b"\n"):
                raise ValueError("retained capacity delivery stream is incomplete")
            deliveries = tuple(
                self.codec.decode_json(line, SharedBookDelivery) for line in raw.splitlines()
            )
            if any(
                self.codec.encode_json(delivery) != line
                for delivery, line in zip(deliveries, raw.splitlines(), strict=True)
            ):
                raise ValueError("capacity delivery differs from canonical event bytes")
            streams.append((request, deliveries))
        streams.sort(key=self._stream_start)
        return tuple(streams)

    @staticmethod
    def _stream_start(
        item: tuple[RecordingRequest, tuple[SharedBookDelivery, ...]],
    ) -> datetime:
        """Order each reconnect stream by its retained first availability."""
        return item[1][0].source.available_at

    def _signed_checkpoints(
        self, account: PaperServiceAccount, original: AccountExecutionResult
    ) -> dict[str, bytes | None]:
        """Prefer immutable final observations over a journal reused by later recovery."""
        observed = self._observed_checkpoints(account)
        if observed is not None:
            return observed
        if original.journal_path is None:
            raise ValueError("signed final state has no account journal path")
        path = Path(original.journal_path)
        if not path.is_file():
            raise ValueError("signed final account journal is unavailable")
        signed = AccountJournal(path, account.configuration)
        return {
            instance.instance_id: signed.checkpoint(instance.instance_id)
            for instance in self.service.instances
            if instance.account_id == account.account_id
        }

    def _observed_checkpoints(self, account: PaperServiceAccount) -> dict[str, bytes | None] | None:
        """Select one complete post-shutdown checkpoint cohort for this exact account."""
        path = self.trial / "observations.jsonl"
        if not path.is_file():
            return None
        cohorts: list[dict[str, bytes | None]] = []
        for line in path.read_bytes().splitlines():
            if self.codec.decode_json(line, _ObservationKind).kind != "account_facts":
                continue
            observed = self.codec.decode_json(line, _AccountFactsObservation).values
            if observed.label == "post_shutdown" and observed.account == account.account_id:
                cohorts.append(observed.checkpoints)
        expected = {
            instance.instance_id
            for instance in self.service.instances
            if instance.account_id == account.account_id
        }
        if len(cohorts) != 1 or set(cohorts[0]) != expected:
            raise ValueError("signed final checkpoint observation is absent or ambiguous")
        return cohorts[0]

    def _fresh_journal(
        self,
        account: PaperServiceAccount,
        source: PaperServiceSource,
        original: AccountExecutionResult,
        path: Path,
    ) -> AccountJournal:
        """Recreate opening facts without copying final signed state or authority."""
        if len(original.accounts) != 1 or original.accounts[0].reconciled_at is None:
            raise ValueError("signed final account lacks an opening reconciliation")
        journal = AccountJournal(path, account.configuration)
        initial_at = original.accounts[0].reconciled_at
        venue = self.workload.venue_workload(source.capture.venue)
        journal.observe(
            AccountQuote(
                price=venue.price("100", source.scenario.adverse.per),
                at=initial_at - timedelta(microseconds=1),
            )
        )
        if not journal.reconcile(venue.opening_observation(account.account_id, initial_at)):
            raise ValueError("fresh capacity replay opening reconciliation failed")
        return journal

    def _replay(
        self,
        account: PaperServiceAccount,
        source: PaperServiceSource,
        original: AccountExecutionResult,
        path: Path,
    ) -> tuple[dict[str, object], int, tuple[dict[str, object], ...]]:
        """Apply each selected delivery and original clock to a fresh local account."""
        journal = self._fresh_journal(account, source, original, path)
        replayed, selections = self._replay_into(account, source, journal)
        return self._journal_facts(account, journal), replayed, selections

    def _replay_into(
        self,
        account: PaperServiceAccount,
        source: PaperServiceSource,
        journal: AccountJournal,
    ) -> tuple[int, tuple[dict[str, object], ...]]:
        """Recompute native source selections before applying original causal deliveries."""
        bindings = self._bindings(account, source)
        inputs = ServiceBookInputs(
            tuple(binding.instance_id for binding in bindings),
            source.freshness_us,
            source.market_interval_us,
        )
        replayed = 0
        selections: list[dict[str, object]] = []
        for request, stream in self._streams(account.account_id, source):
            books = BookRegistry(
                BookRegistryConfiguration(
                    selections=(
                        BookSelection.from_capture(
                            request.config,
                            source_id=request.identity,
                            capability=BookAdapters.capability(request.config),
                            max_age_ns=source.freshness_us * 1000,
                            allow_degraded=True,
                        ),
                    ),
                    equivalences=(),
                    history_capacity=1000,
                )
            )
            observer = SharedPaperCaptureObserver(
                source=LiveBookDecisionSource(request, inputs.requirement, history_capacity=1000),
                books=books,
                journal=journal,
                runtime=SharedDecisionRuntime(journal, bindings),
                account_id=account.account_id,
                scenario=source.scenario,
                inputs=inputs,
                delivery_path=None,
                market_interval_us=source.market_interval_us,
            )
            for delivery in stream:
                selected = self._apply_selected_delivery(observer, delivery)
                if selected:
                    selections.append(
                        {
                            "request_identity": request.identity,
                            "recording_id": request.recording_key,
                            "position": delivery.source.book.position,
                            "received_ns": delivery.source.record.received_ns,
                            "available_at": delivery.source.available_at,
                            "coordinated_at": delivery.coordinated_at,
                            "instances": tuple(item.instance_id for item in delivery.inputs),
                            "inputs_sha256": hashlib.sha256(
                                self.codec.encode_json(delivery.inputs)
                            ).hexdigest(),
                        }
                    )
                replayed += 1
        return replayed, tuple(selections)

    @staticmethod
    def _apply_selected_delivery(
        observer: SharedPaperCaptureObserver, delivery: SharedBookDelivery
    ) -> bool:
        """Reject changed cadence, skipped decisions and substituted exact feature values."""
        delivery.__post_init__()
        market = observer._market(delivery.source)
        selected = market is not None and observer._select_market(market.at)
        expected = (
            observer.inputs.build(
                observer.source.read(str(observer.scenario.instrument_id), market.at), market
            )
            if selected and market is not None
            else ()
        )
        if delivery.inputs != expected or (
            market is not None and delivery.market_effects != selected
        ):
            raise ValueError("retained source selection or exact feature values differ")
        observer._apply(delivery, market)
        return selected

    def _journal_facts(
        self, account: PaperServiceAccount, journal: AccountJournal
    ) -> dict[str, object]:
        """Read the complete comparable economic facts and continuation cohort."""
        fills, costs = journal.paper_report_facts(account.account_id)
        return {
            "ledger": journal.accounts()[0].ledger,
            "orders": journal.orders(),
            "net_orders": journal.net_orders(),
            "paper_fills": fills,
            "paper_costs": costs,
            "paper_traces": journal.paper_traces(),
            "checkpoints": {
                instance.instance_id: journal.checkpoint(instance.instance_id)
                for instance in self.service.instances
                if instance.account_id == account.account_id
            },
        }

    def _signed_facts(
        self, account: PaperServiceAccount, original: AccountExecutionResult
    ) -> dict[str, object]:
        """Read retained final economics without using the mutable journal as an oracle."""
        if len(original.accounts) != 1:
            raise ValueError("signed final state lacks exactly one account")
        return {
            "ledger": original.accounts[0].ledger,
            "orders": original.orders,
            "net_orders": original.net_orders,
            "paper_fills": original.paper_fills,
            "paper_costs": original.paper_costs,
            "paper_traces": original.paper_traces,
            "checkpoints": self._signed_checkpoints(account, original),
        }

    @classmethod
    def _compare(
        cls, signed: dict[str, object], replay: dict[str, object]
    ) -> dict[str, dict[str, object]]:
        """Retain both complete values whenever any economic field differs."""
        codec = DomainCodec()
        results: dict[str, dict[str, object]] = {}
        for field in cls.fields:
            signed_bytes = codec.encode_json(signed[field])
            replay_bytes = codec.encode_json(replay[field])
            equal = signed_bytes == replay_bytes
            results[field] = {
                "equal": equal,
                "signed_sha256": hashlib.sha256(signed_bytes).hexdigest(),
                "replay_sha256": hashlib.sha256(replay_bytes).hexdigest(),
                "signed": None if equal else signed[field],
                "replay": None if equal else replay[field],
            }
        return results

    def write(self, output: Path) -> dict[str, object]:
        """Retain all comparisons and failures without granting any paper authority."""
        if not output.is_absolute() or output.exists():
            raise ValueError("capacity parity requires a fresh absolute output path")
        output.parent.mkdir(parents=True, exist_ok=True)
        replay_root = output.with_suffix("")
        replay_root.mkdir(parents=True, exist_ok=False)
        accounts: list[dict[str, object]] = []
        for account in self.service.accounts:
            source = next(
                source
                for source in self.service.sources
                if any(
                    instance.account_id == account.account_id and instance.source == source.name
                    for instance in self.service.instances
                )
            )
            expected: dict[str, object] | None = None
            try:
                original = self.codec.decode_json(
                    (self.trial / f"final-{account.account_id}.json").read_bytes(),
                    AccountExecutionResult,
                )
                signed_facts = self._signed_facts(account, original)
                expected = signed_facts
                actual, replayed, selections = self._replay(
                    account, source, original, replay_root / f"{account.account_id}.sqlite3"
                )
                comparisons = self._compare(signed_facts, actual)
                original_snapshot = AccountLedger(original.accounts[0].ledger).snapshot()
                replay_ledger = actual["ledger"]
                if not isinstance(replay_ledger, AccountState):
                    raise TypeError("fresh replay lacks a typed account ledger")
                actual_snapshot = AccountLedger(replay_ledger).snapshot()
                oracle = self.workload.first_touch_oracle()[account.account_id]
                oracle_equal = (
                    original_snapshot.cash,
                    original_snapshot.fees,
                    original_snapshot.positions,
                    actual_snapshot.cash,
                    actual_snapshot.fees,
                    actual_snapshot.positions,
                ) == (
                    (oracle[0],),
                    (oracle[1],),
                    oracle[2],
                    (oracle[0],),
                    (oracle[1],),
                    oracle[2],
                )
                accounts.append(
                    {
                        "account": account.account_id,
                        "source": source.name,
                        "replayed_deliveries": replayed,
                        "verified_source_selections": selections,
                        "comparisons": comparisons,
                        "oracle_equal": oracle_equal,
                        "signed_snapshot": original_snapshot,
                        "replay_snapshot": actual_snapshot,
                        "qualified": oracle_equal
                        and all(result["equal"] is True for result in comparisons.values()),
                    }
                )
            except (OSError, ValueError, TypeError) as error:
                accounts.append(
                    {
                        "account": account.account_id,
                        "source": source.name,
                        "qualified": False,
                        "failure": f"{type(error).__name__}: {error}",
                        "signed": expected,
                        "replay_journal": str(replay_root / f"{account.account_id}.sqlite3"),
                    }
                )
        report: dict[str, object] = {
            "schema_version": "runtime-capacity-economic-parity",
            "evidence_class": "unmanaged_software_replay_of_signed_deliveries",
            "signed_trial": str(self.trial),
            "prepared_selection": self.prepared.identity,
            "installed_implementation": self.implementation,
            "replay_installed_implementation": self.replay_implementation,
            "installed_identity_match": self.replay_implementation == self.implementation,
            "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "accounts": tuple(accounts),
            "qualified": self.replay_implementation == self.implementation
            and all(account["qualified"] is True for account in accounts),
        }
        output.write_bytes(self.codec.encode_json(report))
        return report


class CapacityRecoveryEconomicParity(CapacityEconomicParity):
    """Independently rebuild a baseline and replay its exact recovery suffix.

    The local journals receive no deployment, grant or owner. Original operator
    requests reproduce economic and continuation transitions only; the earlier
    signed owner-fencing evidence continues to own authority qualification.
    """

    def __init__(self, root: Path, trial: Path, baseline: Path) -> None:
        """Require a prior compatible signed trial with immutable checkpoints."""
        super().__init__(root, trial)
        self.baseline = CapacityEconomicParity(root, baseline)
        if (
            self.baseline.implementation != self.implementation
            or self.baseline.prepared != self.prepared
            or self.baseline.service.accounts != self.service.accounts
            or self.baseline.service.sources != self.service.sources
            or self.baseline.service.instances != self.service.instances
            or self.baseline.service.active != self.service.active
        ):
            raise ValueError("recovery suffix differs from baseline implementation or selection")

    @staticmethod
    def _request_at(request: AccountExecutionRequest) -> datetime:
        """Read the operation's original clock without filesystem-time substitution."""
        if request.control is not None:
            return request.control.at
        if request.quote is not None:
            return request.quote.at
        if request.market is not None:
            return request.market.at
        if request.observation is not None:
            return request.observation.at
        if request.action == "restart_instance" and request.at is not None:
            return request.at
        raise ValueError("retained recovery operation has no original clock")

    def _operator_requests(
        self, account: PaperServiceAccount
    ) -> tuple[tuple[Path, AccountExecutionRequest, AccountExecutionResult], ...]:
        """Admit complete canonical operator requests with successful retained receipts."""
        root = self.trial / "admin" / account.account_id
        operations: list[tuple[Path, AccountExecutionRequest, AccountExecutionResult]] = []
        for path in root.glob("*.json"):
            if path.name.endswith(".result.json"):
                continue
            payload = path.read_bytes()
            request = self.codec.decode_json(payload, AccountExecutionRequest)
            if request.action in ("inspect", "checkpoint"):
                continue
            if (
                path.stem != hashlib.sha256(payload).hexdigest()
                or self.codec.encode_json(request) != payload
            ):
                raise ValueError("retained recovery operator request identity differs")
            receipts = tuple(root.glob(f"{path.stem}.*.result.json"))
            if not receipts:
                # The deliberate stale-owner quote has only a failed receipt;
                # it supplies fencing evidence and has no economic effect.
                if request.action != "quote" or not tuple(root.glob(f"{path.stem}.*.stderr")):
                    raise ValueError("recovery operator operation has no completed receipt")
                continue
            if request.action not in (
                "control",
                "quote",
                "paper_market",
                "reconcile",
                "claim_paper",
                "restart_instance",
            ):
                raise ValueError("unsupported retained recovery operator action")
            results = tuple(
                self.codec.decode_json(receipt.read_bytes(), AccountExecutionResult)
                for receipt in receipts
            )
            if any(result != results[0] for result in results):
                raise ValueError("retained recovery operator receipts disagree")
            operations.append((path, request, results[0]))
        # The public market and valuation quote intentionally share one clock.
        # The original driver applies the valuation first, then matches.
        operations.sort(key=self._operation_order)
        if not operations or sum(item[1].action == "claim_paper" for item in operations) != 1:
            raise ValueError("recovery requires one completed replacement request per account")
        return tuple(operations)

    @classmethod
    def _operation_order(
        cls, item: tuple[Path, AccountExecutionRequest, AccountExecutionResult]
    ) -> tuple[datetime, int, str]:
        """Preserve shared-clock valuation-before-matching order from the driver."""
        priorities = {"quote": 0, "paper_market": 1}
        return cls._request_at(item[1]), priorities.get(item[1].action, 2), item[0].name

    @staticmethod
    def _apply_operator(
        journal: AccountJournal, request: AccountExecutionRequest, signed: AccountExecutionResult
    ) -> None:
        """Apply exact economic controls while leaving managed paper authority absent."""
        if request.action in ("control", "claim_paper") and request.control is not None:
            actual = journal.control(request.control)
            if actual.status != "applied":
                raise ValueError(f"unmanaged recovery control refused: {actual.reason}")
            if request.action == "control" and (
                signed.control is None
                or (actual.status, actual.phase, actual.cancel_order_ids)
                != (
                    signed.control.status,
                    signed.control.phase,
                    signed.control.cancel_order_ids,
                )
            ):
                raise ValueError("unmanaged recovery control outcome differs")
            if request.action == "claim_paper" and signed.claimed_owner is None:
                raise ValueError("signed replacement request has no owner result")
        elif request.action == "quote" and request.quote is not None:
            journal.observe(request.quote)
        elif (
            request.action == "paper_market"
            and request.account_id is not None
            and request.market is not None
            and request.scenario is not None
        ):
            actual_trace = journal.match_public_market(
                request.account_id, request.market, request.scenario
            )
            if actual_trace != signed.matched_market:
                raise ValueError("independent recovery settlement trace differs")
        elif request.action == "reconcile" and request.observation is not None:
            if signed.reconciled is not True or not journal.reconcile(request.observation):
                raise ValueError("independent recovery facts do not reconcile")
        elif (
            request.action == "restart_instance"
            and request.instance_id is not None
            and request.at is not None
        ):
            journal.restart_instance(request.instance_id, request.at)
        else:
            raise ValueError("retained recovery operator request is incomplete")

    def write(self, output: Path) -> dict[str, object]:
        """Retain full baseline/suffix comparisons and every original selection identity."""
        if not output.is_absolute() or output.exists():
            raise ValueError("capacity recovery parity requires a fresh absolute output path")
        output.parent.mkdir(parents=True, exist_ok=True)
        replay_root = output.with_suffix("")
        replay_root.mkdir(parents=True, exist_ok=False)
        accounts: list[dict[str, object]] = []
        for account in self.service.accounts:
            source = next(
                source
                for source in self.service.sources
                if any(
                    instance.account_id == account.account_id and instance.source == source.name
                    for instance in self.service.instances
                )
            )
            path = replay_root / f"{account.account_id}.sqlite3"
            try:
                if self.baseline._observed_checkpoints(account) is None:
                    raise ValueError("baseline lacks immutable checkpoint observations")
                initial = self.codec.decode_json(
                    (self.baseline.trial / f"final-{account.account_id}.json").read_bytes(),
                    AccountExecutionResult,
                )
                journal = self.baseline._fresh_journal(account, source, initial, path)
                prefix_count, prefix_selections = self.baseline._replay_into(
                    account, source, journal
                )
                prefix_comparisons = self._compare(
                    self.baseline._signed_facts(account, initial),
                    self._journal_facts(account, journal),
                )
                if any(result["equal"] is not True for result in prefix_comparisons.values()):
                    accounts.append(
                        {
                            "account": account.account_id,
                            "source": source.name,
                            "qualified": False,
                            "failure": "independent baseline replay differs",
                            "baseline_comparisons": prefix_comparisons,
                        }
                    )
                    continue
                operations = self._operator_requests(account)
                for _, request, result in operations:
                    self._apply_operator(journal, request, result)
                first_suffix = min(
                    stream[0].source.available_at
                    for _, stream in self._streams(account.account_id, source)
                )
                if self._request_at(operations[-1][1]) >= first_suffix:
                    raise ValueError("recovery operator request overlaps the replay suffix")
                suffix_count, suffix_selections = self._replay_into(account, source, journal)
                final = self.codec.decode_json(
                    (self.trial / f"final-{account.account_id}.json").read_bytes(),
                    AccountExecutionResult,
                )
                comparisons = self._compare(
                    self._signed_facts(account, final), self._journal_facts(account, journal)
                )
                accounts.append(
                    {
                        "account": account.account_id,
                        "source": source.name,
                        "baseline_deliveries": prefix_count,
                        "suffix_deliveries": suffix_count,
                        "baseline_comparisons": prefix_comparisons,
                        "comparisons": comparisons,
                        "baseline_source_selections": prefix_selections,
                        "suffix_source_selections": suffix_selections,
                        "operator_requests": tuple(
                            {
                                "path": str(request_path),
                                "sha256": request_path.stem,
                                "action": request.action,
                                "at": self._request_at(request),
                            }
                            for request_path, request, _ in operations
                        ),
                        "qualified": bool(suffix_selections)
                        and all(result["equal"] is True for result in comparisons.values()),
                    }
                )
            except (OSError, ValueError, TypeError) as error:
                accounts.append(
                    {
                        "account": account.account_id,
                        "source": source.name,
                        "qualified": False,
                        "failure": f"{type(error).__name__}: {error}",
                        "replay_journal": str(path),
                    }
                )
        report: dict[str, object] = {
            "schema_version": "runtime-capacity-recovery-suffix-parity",
            "evidence_class": "independent_unmanaged_baseline_operator_and_suffix_replay",
            "signed_trial": str(self.trial),
            "baseline_trial": str(self.baseline.trial),
            "prepared_selection": self.prepared.identity,
            "installed_implementation": self.implementation,
            "replay_installed_implementation": self.replay_implementation,
            "installed_identity_match": self.replay_implementation == self.implementation,
            "consumer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "authority": "absent_from_replay_existing_signed_fencing_evidence_reused",
            "accounts": tuple(accounts),
            "qualified": self.replay_implementation == self.implementation
            and all(account["qualified"] is True for account in accounts),
        }
        output.write_bytes(self.codec.encode_json(report))
        return report


def main() -> None:
    """Replay one completed retained capacity trial and publish exact comparisons."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(namespace=_Arguments())
    replay = (
        CapacityEconomicParity(args.root, args.trial)
        if args.baseline is None
        else CapacityRecoveryEconomicParity(args.root, args.trial, args.baseline)
    )
    report = replay.write(args.output)
    print(
        DomainCodec()
        .encode_json({"qualified": report["qualified"], "output": str(args.output)})
        .decode()
    )
    if report["qualified"] is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
