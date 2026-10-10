"""Exercise independent economic replay and fail-closed field comparisons."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

# third party library imports
import pytest
from capacity_inputs import CapacityWorkload
from capacity_parity import (
    CapacityEconomicParity,
    CapacityRecoveryEconomicParity,
    _DeliveryStream,
)
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger
from configuration import BookRegistryConfiguration, BookSelection, CaptureRunConfig
from execution import (
    AccountControl,
    AccountExecutionRequest,
    AccountExecutionResult,
    AccountJournal,
    AccountObservation,
    AccountQuote,
)
from financial_units import ExactRatio
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.contracts import (
    BookObservation,
    CaptureRecord,
    CaptureRequest,
    CaptureRunRequest,
    Level,
)
from research.observations import LiveBookDecisionSource, NamedObservation
from runtime import (
    LiveBookDelivery,
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyInput,
)
from serialization import DomainCodec


class _SequenceClock:
    """Return authored delivery clocks in order, repeating the last one."""

    def __init__(self, times: tuple[datetime, ...]) -> None:
        """Keep the authored sequence."""
        self.times, self.index = times, 0

    def __call__(self) -> datetime:
        """Read the next authored UTC clock value."""
        value = self.times[min(self.index, len(self.times) - 1)]
        self.index += 1
        return value


class TestCapacityParity:
    """Require complete exact comparison and a separately checked oracle."""

    def test_unmanaged_replay_checks_all_accounts_and_independent_oracle(
        self, tmp_path: Path
    ) -> None:
        """Replay canonical source sessions through four fresh local journals."""
        root = tmp_path / "selection"
        root.mkdir()
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-parity-sockets"),
        )
        workload.prepare(root / "preparation")
        service = workload.service_configuration()
        codec = DomainCodec()
        trial = root / "trial"
        trial.mkdir()
        (trial / "configuration.json").write_bytes(codec.encode_json(service))
        (trial / "summary.json").write_bytes(codec.encode_json({"implementation": "f" * 64}))
        run = trial / "operating/runs/single"
        run.mkdir(parents=True)
        signed_root = trial / "signed-journals"
        signed_root.mkdir()
        reconciled_at = datetime(2026, 9, 27, 13, tzinfo=UTC)
        for account in service.accounts:
            source = next(
                source
                for source in service.sources
                if any(
                    instance.account_id == account.account_id and instance.source == source.name
                    for instance in service.instances
                )
            )
            venue = workload.venue_workload(source.capture.venue)
            signed_path = signed_root / f"{account.account_id}.sqlite3"
            signed = AccountJournal(signed_path, account.configuration)
            signed.observe(
                AccountQuote(
                    price=venue.price("100", source.scenario.adverse.per),
                    at=reconciled_at - timedelta(microseconds=1),
                )
            )
            assert signed.reconcile(venue.opening_observation(account.account_id, reconciled_at))
            final = AccountExecutionResult(
                accounts=signed.accounts(),
                orders=signed.orders(),
                net_orders=signed.net_orders(),
                paper_trace_history=signed.paper_trace_history(),
                journal_path=str(signed_path),
            )
            (trial / f"final-{account.account_id}.json").write_bytes(codec.encode_json(final))
            request = CaptureRequest(
                config=source.capture,
                recording_id=str(uuid4()),
                implementation_identity="f" * 64,
            )
            request.__post_init__()
            source_directory = run / source.name
            request_directory = source_directory / request.recording_id / request.recording_id
            request_directory.mkdir(parents=True, exist_ok=True)
            (request_directory / "request.json").write_bytes(codec.encode_json(request))
            available_at = reconciled_at + timedelta(seconds=1)
            received_ns = int(available_at.timestamp()) * 1_000_000_000
            record = CaptureRecord(kind="session", epoch=0, received_ns=received_ns)
            book = BookObservation(
                position=0,
                epoch=0,
                received_ns=received_ns,
                source_time=None,
                sequence=None,
                outcome="session",
                status="recovering",
                reason="validated snapshot required",
                state_identity="0" * 64,
            )
            delivery = SharedBookDelivery(
                source=LiveBookDelivery(record=record, book=book, available_at=available_at),
                decisions=(),
                matched=False,
            )
            (source_directory / f"{request.recording_id}-{account.account_id}.jsonl").write_bytes(
                delivery.encode(codec) + b"\n"
            )

        report = CapacityEconomicParity(root, trial).write(tmp_path / "comparison.json")
        assert report["qualified"] is False
        accounts = cast(tuple[dict[str, object], ...], report["accounts"])
        assert len(accounts) == 4
        for result in accounts:
            assert result["replayed_deliveries"] == 1
            assert result["oracle_equal"] is False
            comparisons = cast(dict[str, dict[str, object]], result["comparisons"])
            assert set(comparisons) == set(CapacityEconomicParity.fields)
            assert all(comparison["equal"] is True for comparison in comparisons.values())

        stream = next(run.rglob("*-okx-shared.jsonl"))
        stream.write_bytes(stream.read_bytes().removesuffix(b"\n"))
        invalid = CapacityEconomicParity(root, trial).write(tmp_path / "invalid.json")
        invalid_accounts = cast(tuple[dict[str, object], ...], invalid["accounts"])
        failed = next(item for item in invalid_accounts if item["account"] == "okx-shared")
        assert failed["qualified"] is False
        assert "incomplete" in cast(str, failed["failure"])
        assert failed["signed"] is not None
        assert Path(cast(str, failed["replay_journal"])).is_file()

    def test_fresh_replay_opens_at_the_opening_not_the_latest_reconciliation(
        self, tmp_path: Path
    ) -> None:
        """A periodically reconciled signed account still replays from its opening clock.

        The final account's ``reconciled_at`` is its latest reconciliation; opening the
        replay journal there would refuse every earlier market as preceding knowledge.
        """
        root = tmp_path / "selection"
        root.mkdir()
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-parity-sockets"),
        )
        workload.prepare(root / "preparation")
        service = workload.service_configuration()
        codec = DomainCodec()
        trial = root / "trial"
        trial.mkdir()
        (trial / "configuration.json").write_bytes(codec.encode_json(service))
        (trial / "summary.json").write_bytes(codec.encode_json({"implementation": "f" * 64}))
        (trial / "operating/runs/single").mkdir(parents=True)
        account = service.accounts[0]
        source = next(
            source
            for source in service.sources
            if any(
                instance.account_id == account.account_id and instance.source == source.name
                for instance in service.instances
            )
        )
        venue = workload.venue_workload(source.capture.venue)
        opening_at = datetime(2026, 9, 27, 13, tzinfo=UTC)
        later = opening_at + timedelta(minutes=10)
        signed = AccountJournal(tmp_path / "signed.sqlite3", account.configuration)
        signed.observe(
            AccountQuote(
                price=venue.price("100", source.scenario.adverse.per),
                at=opening_at - timedelta(microseconds=1),
            )
        )
        opening = venue.opening_observation(account.account_id, opening_at)
        assert signed.reconcile(opening)
        assert signed.reconcile(replace(opening, identity="periodic", at=later))
        final = AccountExecutionResult(accounts=signed.accounts(), orders=signed.orders())
        assert final.accounts[0].reconciled_at == later

        parity = CapacityEconomicParity(root, trial)
        # Without a retained opening request, the final reconciliation is the fallback.
        assert parity._opening_at(account, final) == later
        admin = trial / "admin" / account.account_id
        admin.mkdir(parents=True)

        def retain(request: AccountExecutionRequest, *, receipt: bool = True) -> Path:
            payload = codec.encode_json(request)
            path = admin / f"{hashlib.sha256(payload).hexdigest()}.json"
            path.write_bytes(payload)
            if receipt:
                (admin / f"{path.stem}.receipt.result.json").write_bytes(b"{}")
            return path

        retain(AccountExecutionRequest(action="reconcile", observation=opening))
        assert parity._opening_at(account, final) == opening_at
        fresh = parity._fresh_journal(account, source, final, tmp_path / "fresh.sqlite3")
        assert fresh.accounts()[0].reconciled_at == opening_at

        duplicate = retain(
            AccountExecutionRequest(action="reconcile", observation=replace(opening, at=later))
        )
        with pytest.raises(ValueError, match="more than one opening reconciliation"):
            parity._opening_at(account, final)
        duplicate.unlink()
        for receipt in admin.glob(f"{duplicate.stem}.*"):
            receipt.unlink()
        unconfirmed = retain(
            AccountExecutionRequest(action="reconcile", observation=replace(opening, at=later)),
            receipt=False,
        )
        with pytest.raises(ValueError, match="no completed receipt"):
            parity._opening_at(account, final)
        unconfirmed.unlink()

    def test_unmanaged_replay_reads_a_segment_chain_by_its_run_key(self, tmp_path: Path) -> None:
        """A chain's stream binds the whole-run request identity and replays every account."""
        root = tmp_path / "selection"
        root.mkdir()
        workload = CapacityWorkload(
            opening_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-chain-parity-sockets"),
        )
        workload.prepare(root / "preparation")
        service = workload.service_configuration()
        codec = DomainCodec()
        trial = root / "trial"
        trial.mkdir()
        (trial / "configuration.json").write_bytes(codec.encode_json(service))
        (trial / "summary.json").write_bytes(codec.encode_json({"implementation": "f" * 64}))
        run = trial / "operating/runs/single"
        run.mkdir(parents=True)
        reconciled_at = datetime(2026, 9, 27, 13, tzinfo=UTC)
        for account in service.accounts:
            source = next(
                source
                for source in service.sources
                if any(
                    instance.account_id == account.account_id and instance.source == source.name
                    for instance in service.instances
                )
            )
            venue = workload.venue_workload(source.capture.venue)
            signed_path = trial / f"{account.account_id}.sqlite3"
            signed = AccountJournal(signed_path, account.configuration)
            signed.observe(
                AccountQuote(
                    price=venue.price("100", source.scenario.adverse.per),
                    at=reconciled_at - timedelta(microseconds=1),
                )
            )
            assert signed.reconcile(venue.opening_observation(account.account_id, reconciled_at))
            final = AccountExecutionResult(
                accounts=signed.accounts(),
                orders=signed.orders(),
                net_orders=signed.net_orders(),
                paper_trace_history=signed.paper_trace_history(),
                journal_path=str(signed_path),
            )
            (trial / f"final-{account.account_id}.json").write_bytes(codec.encode_json(final))
            request = CaptureRunRequest(
                config=source.capture,
                window=CaptureRunConfig(
                    start_at=reconciled_at,
                    ready_by=reconciled_at + timedelta(seconds=1),
                    stop_at=reconciled_at + timedelta(minutes=1),
                    max_messages=100,
                    max_bytes=64 * 1024**2,
                    max_segments=8,
                    max_reconnects=0,
                ),
                run_id=str(uuid4()),
                implementation_identity="f" * 64,
            )
            source_directory = run / source.name
            run_directory = source_directory / request.run_id / request.run_id
            run_directory.mkdir(parents=True, exist_ok=True)
            (run_directory / "run-request.json").write_bytes(codec.encode_json(request))
            available_at = reconciled_at + timedelta(seconds=1)
            received_ns = int(available_at.timestamp()) * 1_000_000_000
            delivery = SharedBookDelivery(
                source=LiveBookDelivery(
                    record=CaptureRecord(kind="session", epoch=0, received_ns=received_ns),
                    book=BookObservation(
                        position=0,
                        epoch=0,
                        received_ns=received_ns,
                        source_time=None,
                        sequence=None,
                        outcome="session",
                        status="recovering",
                        reason="validated snapshot required",
                        state_identity="0" * 64,
                    ),
                    available_at=available_at,
                ),
                decisions=(),
                matched=False,
            )
            (source_directory / f"{request.run_id}-{account.account_id}.jsonl").write_bytes(
                delivery.encode(codec) + b"\n"
            )

        report = CapacityEconomicParity(root, trial).write(tmp_path / "comparison.json")
        accounts = cast(tuple[dict[str, object], ...], report["accounts"])
        assert len(accounts) == 4
        for result in accounts:
            assert result.get("failure") is None
            assert result["replayed_deliveries"] == 1
            comparisons = cast(dict[str, dict[str, object]], result["comparisons"])
            assert all(comparison["equal"] is True for comparison in comparisons.values())

    def test_mismatch_retains_complete_signed_and_replay_values(self) -> None:
        """A changed fill and checkpoint must survive as full reviewable evidence."""
        signed: dict[str, object] = {
            field: (field, "same") for field in CapacityEconomicParity.fields
        }
        replay = dict(signed)
        replay["paper_fills"] = ("changed-fill",)
        replay["checkpoints"] = {"fixed": b"different"}
        comparison = CapacityEconomicParity._compare(signed, replay)
        assert set(comparison) == set(CapacityEconomicParity.fields)
        assert {field for field, value in comparison.items() if value["equal"] is False} == {
            "paper_fills",
            "checkpoints",
        }
        for field in ("paper_fills", "checkpoints"):
            assert comparison[field]["signed"] == signed[field]
            assert comparison[field]["replay"] == replay[field]
            assert comparison[field]["signed_sha256"] != comparison[field]["replay_sha256"]

    def test_delivery_stream_refuses_a_replaced_format_at_its_first_line(
        self, tmp_path: Path
    ) -> None:
        """Parity reads a log's first availability only from the current delivery format."""
        at = datetime(2026, 9, 28, tzinfo=UTC)
        times = (at + timedelta(seconds=1), at + timedelta(seconds=4))
        live, request = self._observer(tmp_path, "live", clock=_SequenceClock(times))
        for position, available_at in enumerate(times):
            live.observe(*self._book(position, available_at))
        path = tmp_path / "live" / "deliveries.jsonl"
        assert list(_DeliveryStream(request, path))
        path.write_bytes(
            path.read_bytes().replace(
                b'"shared-compressed-book-delivery"', b'"shared-eligible-book-delivery"'
            )
        )
        with pytest.raises(ValueError, match="unsupported shared book delivery schema"):
            _DeliveryStream(request, path)

    @staticmethod
    def _observer(
        tmp_path: Path, name: str, *, clock: _SequenceClock | None = None
    ) -> tuple[SharedPaperCaptureObserver, CaptureRequest]:
        """Construct one prepared two-instance account observer on the reference grid."""
        at = datetime(2026, 9, 28, tzinfo=UTC)
        root = tmp_path / name
        workload = CapacityWorkload(
            opening_at=at, socket_root=Path("/private/tmp/capacity-selection-test-sockets")
        )
        workload.prepare(root / "preparation")
        service = workload.service_configuration()
        trial = root / "trial"
        (trial / "operating/runs/one").mkdir(parents=True)
        codec = DomainCodec()
        (trial / "configuration.json").write_bytes(codec.encode_json(service))
        (trial / "summary.json").write_bytes(codec.encode_json({"implementation": "f" * 64}))
        parity = CapacityEconomicParity(root, trial)
        account, source = service.accounts[0], service.sources[0]
        venue = workload.venue_workload(source.capture.venue)
        request = CaptureRequest(
            config=source.capture,
            recording_id="33333333-3333-4333-8333-333333333333",
            implementation_identity="f" * 64,
        )
        journal = AccountJournal(root / "account.sqlite3", account.configuration)
        journal.observe(
            AccountQuote(
                price=venue.price("100", source.scenario.adverse.per),
                at=at - timedelta(microseconds=1),
            )
        )
        assert journal.reconcile(venue.opening_observation(account.account_id, at))
        observer = SharedPaperCaptureObserver(
            source=LiveBookDecisionSource(
                request, venue.candidates(source).inputs, history_capacity=1000
            ),
            books=BookRegistry(
                BookRegistryConfiguration(
                    selections=(
                        BookSelection.from_capture(
                            source.capture,
                            source_id=request.identity,
                            capability=BookAdapters.capability(source.capture),
                            max_age_ns=source.freshness_us * 1000,
                            allow_degraded=True,
                        ),
                    ),
                    equivalences=(),
                    history_capacity=1000,
                )
            ),
            journal=journal,
            runtime=SharedDecisionRuntime(journal, parity._bindings(account, source)),
            account_id=account.account_id,
            scenario=source.scenario,
            delivery_path=root / "deliveries.jsonl",
            clock=clock,
        )
        return observer, request

    @staticmethod
    def _book(position: int, available_at: datetime) -> tuple[CaptureRecord, BookObservation]:
        """Author one valid two-sided OKX book boundary at an actual delivery time."""
        received_ns = int(available_at.timestamp()) * 1_000_000_000
        record = CaptureRecord(kind="frame", epoch=0, received_ns=received_ns, raw=b"{}")
        return record, BookObservation(
            position=position,
            epoch=0,
            received_ns=received_ns,
            source_time=str(received_ns // 1_000_000),
            sequence=10 + position,
            outcome="snapshot" if position == 0 else "update",
            status="degraded",
            reason="depth_without_checksum",
            state_identity="0" * 64,
            bids=((Decimal("99"), Level(size=Decimal("4"), order_count=1)),),
            asks=((Decimal("100"), Level(size=Decimal("4"), order_count=1)),),
        )

    def test_suffix_recomputes_feature_values_before_economic_effects(self, tmp_path: Path) -> None:
        """Reject a value substitution even when native lineage is unchanged.

        The reference grid has an instant at midnight; the book at 00:00:01 crosses the
        first instant and the book at 00:00:04 crosses 00:00:03, deciding from 00:00:01.
        """
        at = datetime(2026, 9, 28, tzinfo=UTC)
        times = (at + timedelta(seconds=1), at + timedelta(seconds=4))
        live, _ = self._observer(tmp_path, "live", clock=_SequenceClock(times))
        for position, available_at in enumerate(times):
            live.observe(*self._book(position, available_at))
        codec = DomainCodec()
        lines = (tmp_path / "live" / "deliveries.jsonl").read_bytes().splitlines()
        first, second = (SharedBookDelivery.decode(line, codec) for line in lines)
        assert (first.matched, first.decisions) == (True, ())
        (group,) = second.decisions
        assert group.at == at + timedelta(seconds=3)
        assert len(group.inputs) == 2
        item = group.inputs[0]
        assert item.inputs is not None
        observation = item.inputs.observations[0]
        observations: tuple[NamedObservation, ...] = (
            replace(observation, value=ExactRatio(numerator="101", denominator="1")),
            *item.inputs.observations[1:],
        )
        changed: SharedStrategyInput = replace(
            item, inputs=replace(item.inputs, observations=observations)
        )
        inputs = (changed, group.inputs[1])
        substituted = replace(second, decisions=(replace(group, inputs=inputs),))
        replay, _ = self._observer(tmp_path, "replay")
        replay.deliver(first)
        with pytest.raises(ValueError, match="substituted native input lineage"):
            replay.deliver(substituted)
        assert replay.journal.checkpoint(item.instance_id) is None
        assert replay.journal.net_orders() == ()

    def test_recovery_reconciliation_compares_independent_economics(self, tmp_path: Path) -> None:
        """Original operator clocks cannot reconcile an incorrect independently rebuilt balance."""
        at = datetime(2026, 9, 28, tzinfo=UTC)
        workload = CapacityWorkload(
            opening_at=at, socket_root=Path("/private/tmp/capacity-reconcile-test-sockets")
        )
        account = workload.service_configuration().accounts[0]
        journal = AccountJournal(tmp_path / "account.sqlite3", account.configuration)
        stopped = AccountControl(
            identity="stop",
            account_id=account.account_id,
            kind="stop",
            at=at + timedelta(seconds=1),
            reason="test independent recovery economics",
        )
        request = AccountExecutionRequest(action="control", control=stopped)
        expected = AccountExecutionResult(
            accounts=journal.accounts(), orders=(), control=journal.control(stopped)
        )
        CapacityRecoveryEconomicParity._apply_operator(journal, request, expected)
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        changed = replace(snapshot, posting_ids=("invented",))
        observation = AccountObservation(
            identity="original-observation",
            at=at + timedelta(seconds=2),
            snapshot=changed,
            open_orders=(),
        )
        request = AccountExecutionRequest(action="reconcile", observation=observation)
        with pytest.raises(ValueError, match="facts do not reconcile"):
            CapacityRecoveryEconomicParity._apply_operator(
                journal,
                request,
                AccountExecutionResult(accounts=journal.accounts(), orders=(), reconciled=True),
            )
