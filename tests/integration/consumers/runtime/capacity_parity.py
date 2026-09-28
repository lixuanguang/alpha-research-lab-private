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
from execution import AccountExecutionResult, AccountJournal, AccountQuote
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.contracts import CaptureRequest
from portfolio import PortfolioContext
from research.observations import LiveBookDecisionSource
from runtime import (
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
)
from serialization import DomainCodec
from strategies import LiquidityClipPolicy, ReferenceClipPolicy


class _TrialSummary(msgspec.Struct):
    """Read the installed implementation selected for the measured trial."""

    implementation: str


class _Arguments(argparse.Namespace):
    """Carry three absolute paths for an offline parity invocation."""

    root: Path
    trial: Path
    output: Path


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
        factory = ReferenceClipPolicy if instance.policy == "fixed_clip" else LiquidityClipPolicy
        policy = factory(
            instance.quantity,
            source.scenario.adverse.currency,
            instance.lot,
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
                config_revision="paper-services-v1",
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
    ) -> tuple[tuple[CaptureRequest, tuple[SharedBookDelivery, ...]], ...]:
        """Verify complete canonical logs and exact request/source identities."""
        source_directory = self.run_directory / source.name
        paths = tuple(source_directory.glob(f"*-{account_id}.jsonl"))
        if not paths:
            raise ValueError(f"capacity account has no retained delivery stream: {account_id}")
        streams: list[tuple[CaptureRequest, tuple[SharedBookDelivery, ...]]] = []
        for path in paths:
            recording_id = path.name.removesuffix(f"-{account_id}.jsonl")
            request_path = source_directory / recording_id / recording_id / "request.json"
            request = self.codec.decode_json(request_path.read_bytes(), CaptureRequest)
            if (
                request.recording_id != recording_id
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
        item: tuple[CaptureRequest, tuple[SharedBookDelivery, ...]],
    ) -> datetime:
        """Order each reconnect stream by its retained first availability."""
        return item[1][0].source.available_at

    def _signed_checkpoints(
        self, account: PaperServiceAccount, original: AccountExecutionResult
    ) -> dict[str, bytes | None]:
        """Read all final continuation bytes from the signed account's retained journal."""
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

    def _replay(
        self,
        account: PaperServiceAccount,
        source: PaperServiceSource,
        original: AccountExecutionResult,
        path: Path,
    ) -> tuple[dict[str, object], int]:
        """Apply each selected delivery and original clock to a fresh local account."""
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
        bindings = self._bindings(account, source)
        inputs = ServiceBookInputs(
            tuple(binding.instance_id for binding in bindings),
            source.freshness_us,
            source.market_interval_us,
        )
        replayed = 0
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
                observer.deliver(delivery)
                replayed += 1
        fills, costs = journal.paper_report_facts(account.account_id)
        return (
            {
                "ledger": journal.accounts()[0].ledger,
                "orders": journal.orders(),
                "net_orders": journal.net_orders(),
                "paper_fills": fills,
                "paper_costs": costs,
                "paper_traces": journal.paper_traces(),
                "checkpoints": {
                    binding.instance_id: journal.checkpoint(binding.instance_id)
                    for binding in bindings
                },
            },
            replayed,
        )

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
                if len(original.accounts) != 1:
                    raise ValueError("signed final state lacks exactly one account")
                signed_facts: dict[str, object] = {
                    "ledger": original.accounts[0].ledger,
                    "orders": original.orders,
                    "net_orders": original.net_orders,
                    "paper_fills": original.paper_fills,
                    "paper_costs": original.paper_costs,
                    "paper_traces": original.paper_traces,
                    "checkpoints": self._signed_checkpoints(account, original),
                }
                expected = signed_facts
                actual, replayed = self._replay(
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
            "schema_version": "runtime-capacity-economic-parity-v1",
            "evidence_class": "unmanaged_software_replay_of_signed_deliveries",
            "signed_trial": str(self.trial),
            "prepared_selection": self.prepared.identity,
            "installed_implementation": self.implementation,
            "accounts": tuple(accounts),
            "qualified": all(account["qualified"] is True for account in accounts),
        }
        output.write_bytes(self.codec.encode_json(report))
        return report


def main() -> None:
    """Replay one completed retained capacity trial and publish exact comparisons."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    report = CapacityEconomicParity(args.root, args.trial).write(args.output)
    print(
        DomainCodec()
        .encode_json({"qualified": report["qualified"], "output": str(args.output)})
        .decode()
    )
    if report["qualified"] is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
