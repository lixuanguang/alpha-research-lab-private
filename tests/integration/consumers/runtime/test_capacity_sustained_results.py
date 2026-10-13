"""Prove sustained results expose window tails, prove slots and resolve commits exactly."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

# third party library imports
import msgspec
import pytest
from capacity_inputs import FixtureReceipts
from capacity_sustained import SustainedNativeFixture, SustainedWorkload
from capacity_sustained_results import (
    DecisionAdmissions,
    RollingPercentiles,
    StoppedJournal,
    SustainedResults,
    WindowBudget,
)

# project library imports
from accounting import AccountSnapshot
from applications.execute import SourceVerification
from configuration import (
    AccountConfiguration,
    CaptureRunConfig,
    InstrumentFeeRate,
    OpeningAccount,
    PaperExecutionScenario,
    PaperServiceConfiguration,
)
from execution import (
    AccountDecision,
    AccountExecutionRequest,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    MarketTouch,
    OrderDecision,
    PaperMarket,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.collection import CaptureSegmentWriter
from market_data.contracts import CaptureRecord, CaptureRunRequest
from market_data.storage import CaptureRunJournal
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent, TargetIntent
from telemetry import RuntimeMeasurementJournal

_MS = 1_000_000
_S = 1_000_000_000


class TestSustainedSlotClock:
    """Match the slot clock to the declared schedule."""

    def test_slot_clock_matches_the_declared_schedule(self) -> None:
        """Integer slot offsets equal the schedule's own clock at every period boundary."""
        for index in (0, 1, 7249, 7250, 8249, 8250, 82_499):
            assert SustainedNativeFixture.slot_ns(index) == round(
                SustainedNativeFixture.elapsed_seconds(index) * _S
            )


class SustainedResultsFixture:
    """Author sustained-result phases and files."""

    @staticmethod
    def write(path: Path, rows: list[dict[str, object]]) -> None:
        """Retain JSON-lines evidence exactly as the probes do."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(msgspec.json.encode(row) + b"\n" for row in rows))

    @staticmethod
    def phase(
        tmp_path: Path,
        *,
        slots: int,
        drop: int | None = None,
        late: int | None = None,
        verified: bool = True,
    ) -> Path:
        """Author one sustained phase: a real chain, its fixture trace, probes and reads.

        The source result is sealed with verification pending; ``verified`` adds the
        explicit verification record bound to it, standing in for the installed verifier.
        """
        trial = tmp_path / "phase"
        workload = SustainedWorkload(
            opening_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-sustained-results"),
        )
        source = workload.service_configuration().sources[0]
        fixture = SustainedNativeFixture(source)
        anchor = 10 * _S
        frames: list[tuple[int, int, bytes]] = []
        for index in range(slots):
            fixture.index = index + 1
            received = anchor + SustainedNativeFixture.slot_ns(index) + _MS
            if index == late:
                received += 3 * _S
            frames.append((index, received, fixture._native_frame(1_700_000_000_000 + index)))
        now = datetime.now(UTC)
        request = CaptureRunRequest(
            config=source.capture,
            window=CaptureRunConfig(
                start_at=now - timedelta(seconds=1),
                ready_by=now,
                stop_at=now + timedelta(hours=1),
                max_messages=100_000,
                max_bytes=1024**3,
                max_segments=4,
                max_reconnects=1,
            ),
            run_id="00000000-0000-4000-8000-0000000005a5",
            implementation_identity="a" * 64,
        )
        source_root = trial / "operating/runs/run" / source.name
        run = CaptureRunJournal(source_root / request.run_id / request.run_id, request)
        run.open(resume=False)
        try:
            writer = CaptureSegmentWriter(
                run, run.start_segment(None), previous_bytes=0, previous_records=0
            )
            asyncio.run(writer.append(CaptureRecord(kind="session", epoch=0, received_ns=1)))
            for index, received, raw in frames:
                asyncio.run(
                    writer.append(
                        CaptureRecord(kind="frame", epoch=0, received_ns=received, raw=raw)
                    )
                )
            asyncio.run(
                writer.append(
                    CaptureRecord(kind="end", epoch=0, received_ns=frames[-1][1], reason="duration")
                )
            )
            run.sealed(writer.current, writer.first_received_ns or 1)
            run.finish({"run_identity": request.identity})
        finally:
            run.close()
        verification = SourceVerification(source_root / request.run_id)
        verification.retain_sealed({"stop_reason": "duration_limit"})
        if verified:
            result = (verification.root / SourceVerification.RESULT).read_bytes()
            record: dict[str, object] = {
                "status": "verified",
                "replay_parity": True,
                "source_result_sha256": hashlib.sha256(result).hexdigest(),
            }
            (verification.root / SourceVerification.RECORD).write_bytes(msgspec.json.encode(record))
        emitted = [
            (index, received, hashlib.sha256(raw).hexdigest())
            for index, received, raw in frames
            if index != drop
        ]
        (trial / "fixture-epochs").mkdir(parents=True)
        FixtureReceipts.write(
            trial / f"fixture-epochs/{source.name}.epoch-1-receipts.jsonl",
            fixture_identity=fixture.identity,
            active_identity=fixture.identity,
            epoch=1,
            anchor_ns=anchor,
            closed_ns=frames[-1][1] + _S,
            emitted=emitted,
        )
        # The interval closes just after the last authored receipt and its durable clock.
        start, stop = anchor, anchor + SustainedNativeFixture.slot_ns(slots - 1) + 10 * _MS
        (trial / "reads").mkdir(parents=True)
        interval: dict[str, object] = {
            "started_monotonic_ns": start,
            "scheduled_stop_monotonic_ns": stop,
        }
        (trial / "reads/summary.json").write_bytes(msgspec.json.encode(interval))
        key = request.run_id
        SustainedResultsFixture.write(
            trial / f"measurements/run/{source.name}/{key}.capture.jsonl",
            [
                {
                    "schema_version": "runtime-measurement",
                    "kind": "capture_boundary",
                    "cursor": position + 2,
                    "receipt_ns": received,
                    "durable_ns": received + _MS,
                    "receipt_to_durable_ns": _MS,
                }
                for position, (_, received, _) in enumerate(frames)
            ],
        )
        SustainedResultsFixture.write(
            trial / f"measurements/run/{source.name}/{key}.okx-shared.paper.jsonl",
            [
                {
                    "schema_version": "runtime-measurement",
                    "kind": "paper_book",
                    "position": position + 1,
                    "policy_selected": position % 75 == 0,
                    "checkpoint_acknowledged": position % 75 == 0,
                    "checkpoint_status": "committed",
                    "checkpoint_reason": "reserved" if position == 0 else "target_matched",
                    "book_started_ns": received + 2 * _MS,
                    "bbo_observed_ns": received + 3 * _MS,
                    "book_to_checkpoint_ns": 40 * _MS if position % 75 == 0 else None,
                }
                for position, (_, received, _) in enumerate(frames)
            ],
        )
        SustainedResultsFixture.write(
            trial / "observations.jsonl",
            [
                {
                    "kind": "account_reconciled",
                    "values": {"account": "okx-shared", "matched": True, "seconds": 0.02},
                },
                {
                    "kind": "account_reconciled",
                    "values": {"account": "okx-shared", "matched": True, "seconds": 0.03},
                },
            ],
        )
        return trial


class TestRollingPercentiles:
    """Expose a late tail that whole-interval percentiles average away."""

    def test_a_late_window_fails_while_the_whole_interval_passes(self) -> None:
        """Twenty slow samples in one 300-second window fail it; the whole p95 stays low."""
        samples = [
            (window * 300 * _S + index * _S, 500 * _MS if window == 7 and index < 20 else 10 * _MS)
            for window in range(10)
            for index in range(100)
        ]
        result = RollingPercentiles.summarize(
            samples,
            start_ns=0,
            end_ns=3000 * _S,
            window_ns=300 * _S,
            budget=WindowBudget(p50_ns=20 * _MS, p95_ns=50 * _MS, p99_ns=1000 * _MS, minimum=50),
        )
        assert result["p95_ns"] == 10 * _MS and result["status"] == "fail"
        windows = cast(list[dict[str, object]], result["windows"])
        assert [window["status"] for window in windows].count("fail") == 1
        assert windows[7]["p95_ns"] == 500 * _MS

    def test_sparse_windows_are_unmeasured_never_passed(self) -> None:
        """A window below its minimum population cannot pass the class."""
        result = RollingPercentiles.summarize(
            [(0, _MS)],
            start_ns=0,
            end_ns=600 * _S,
            window_ns=300 * _S,
            budget=WindowBudget(p50_ns=10 * _MS, p95_ns=10 * _MS, p99_ns=10 * _MS, minimum=1),
        )
        assert result["status"] == "unmeasured"
        with pytest.raises(ValueError):
            RollingPercentiles.summarize([], start_ns=1, end_ns=1, window_ns=1)


class TestSustainedResults:
    """Join a phase's chain, fixture trace, probes and observations exactly."""

    def test_complete_phase_proves_slots_and_counts_commits(self, tmp_path: Path) -> None:
        """Every emitted slot is retained in order and on time across the recording."""
        trial = SustainedResultsFixture.phase(tmp_path, slots=600)
        results = SustainedResults(
            trial,
            budgets={
                "receipt_to_durable": WindowBudget(
                    p50_ns=50 * _MS, p95_ns=250 * _MS, p99_ns=1000 * _MS, minimum=100
                )
            },
        ).collect()
        proofs = cast(dict[str, dict[str, object]], results["fixture_proofs"])
        (proof,) = proofs.values()
        assert proof["status"] == "pass" and proof["required_slots"] == 600
        assert proof["exact_bytes_in_order"] is True
        latencies = cast(dict[str, dict[str, dict[str, object]]], results["latencies"])
        (receipt,) = latencies["receipt_to_durable"].values()
        assert receipt["status"] == "pass" and receipt["count"] == 600
        assert latencies["durable_to_bbo"]["okx-shared"]["count"] == 600
        assert results["commits"] == {
            "okx-shared": {"committed:reserved": 1, "committed:target_matched": 7}
        }
        # Without a retained configuration no decision can be resolved, and none passes.
        assert results["decisions"] == {
            "okx-shared": {"readable": False, "reason": "configuration: FileNotFoundError"}
        }
        assert results["reconciliations"] == {
            "okx-shared": {"attempts": 2, "matched": 2, "max_seconds": 0.03}
        }
        recordings = cast(dict[str, list[dict[str, object]]], results["recordings"])
        (entries,) = recordings.values()
        assert entries[0]["completed"] is True and entries[0]["replay_parity"] is True
        assert entries[0]["verification"] == "verified"

    def test_parity_comes_only_from_a_bound_verification_record(self, tmp_path: Path) -> None:
        """A sealed result, a parity claim or a stale record never reads as verified."""
        trial = SustainedResultsFixture.phase(tmp_path, slots=100, verified=False)
        (entries,) = cast(
            dict[str, list[dict[str, object]]], SustainedResults(trial).collect()["recordings"]
        ).values()
        assert entries[0]["completed"] is True and entries[0]["replay_parity"] is False
        assert entries[0]["verification"] == "missing"
        (result,) = trial.glob("operating/runs/*/*/*/source-result.json")
        # The day-counted-2 shape: a result asserting parity with no verification record.
        claim: dict[str, object] = {"replay_parity": True}
        result.write_bytes(msgspec.json.encode(claim))
        (entries,) = cast(
            dict[str, list[dict[str, object]]], SustainedResults(trial).collect()["recordings"]
        ).values()
        assert entries[0]["replay_parity"] is False
        record: dict[str, object] = {
            "status": "verified",
            "replay_parity": True,
            "source_result_sha256": "0" * 64,
        }
        (result.parent / SourceVerification.RECORD).write_bytes(msgspec.json.encode(record))
        (entries,) = cast(
            dict[str, list[dict[str, object]]], SustainedResults(trial).collect()["recordings"]
        ).values()
        assert entries[0]["replay_parity"] is False and entries[0]["verification"] == "verified"
        (result.parent / SourceVerification.RECORD).write_bytes(b"{")
        (entries,) = cast(
            dict[str, list[dict[str, object]]], SustainedResults(trial).collect()["recordings"]
        ).values()
        assert entries[0]["replay_parity"] is False
        assert entries[0]["verification"] == "unreadable"

    @pytest.mark.parametrize(("drop", "late"), ((17, None), (None, 23)))
    def test_a_missing_or_late_slot_fails_the_proof(
        self, tmp_path: Path, drop: int | None, late: int | None
    ) -> None:
        """An unemitted slot or one retained beyond two seconds is never a complete input."""
        trial = SustainedResultsFixture.phase(tmp_path, slots=100, drop=drop, late=late)
        (proof,) = cast(
            dict[str, dict[str, object]], SustainedResults(trial).collect()["fixture_proofs"]
        ).values()
        assert proof["status"] == "fail"
        if drop is not None:
            assert proof["missing_required_slots"] == 1
        else:
            assert proof["late_required_slots"] == 1


class D2Account:
    """Operate one real paper account journal with D2 arrival-time admission.

    Entry takes 1 ms and cancellation 5 ms when the scenario is bound; an account
    without it admits each decision at once.
    """

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    at = opening_at + timedelta(seconds=1)

    @classmethod
    def money(cls, amount: str) -> Money:
        """Build exact account-currency money."""
        return Money(value=Decimal(amount), currency=cls.currency)

    @classmethod
    def quantity(cls, amount: str) -> Quantity:
        """Build exact base inventory."""
        return Quantity(value=Decimal(amount), dimension=cls.dimension)

    @classmethod
    def price(cls, amount: str = "100") -> Price:
        """Build an exact spot quote."""
        return Price(value=Decimal(amount), currency=cls.currency, per=cls.dimension)

    @classmethod
    def config(cls) -> AccountConfiguration:
        """Give alpha and beta separate 9,000 caps and 9,000 orders under a 10,000 account."""
        limits = SpotLimits(
            maximum=cls.quantity("200"),
            lot=cls.quantity("1"),
            tick=cls.price("0.01"),
            product="spot",
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls.money("50000"),)),),
            instruments=(limits,),
            fee_rates=(
                InstrumentFeeRate(instrument_id=cls.dimension.instrument_id, rate=Decimal(0)),
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls.money("10000"),
                accounts=(AccountLimit(account_id="shared", maximum=cls.money("10000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=name,
                        account_id="shared",
                        maximum=cls.money("9000"),
                        instruments=(cls.dimension.instrument_id,),
                    )
                    for name in ("alpha", "beta")
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls.money("9000"),
            ),
        )

    @classmethod
    def scenario(cls) -> PaperExecutionScenario:
        """Model a 1 ms entry delay and a 5 ms cancel delay with no costs."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=1_000,
            cancel_delay_us=5_000,
            adverse=cls.price("0"),
            fee_rate=Decimal(0),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot matching",
        )

    @classmethod
    def open(cls, path: Path, *, delayed: bool) -> AccountJournal:
        """Open, optionally bind the delayed scenario, and reconcile opening cash."""
        journal = AccountJournal(path, cls.config())
        if delayed:
            journal.bind_paper_scenario("shared", cls.scenario())
        opening = AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(cls.money("50000"),),
            positions=(),
            fees=(cls.money("0"),),
            rebates=(cls.money("0"),),
            transfers=(cls.money("50000"),),
            fill_ids=(),
            posting_ids=("opening:USDT",),
        )
        assert journal.reconcile(
            AccountObservation(
                identity="opening", at=cls.opening_at, snapshot=opening, open_orders=()
            )
        )
        return journal

    @classmethod
    def target(cls, instance: str, identity: str, at: datetime, quantity: str) -> PortfolioDecision:
        """Ask for an absolute holding, decided on a 99.50 bid and 100 ask."""
        return PortfolioDecision(
            request=AccountDecision(
                account_id="shared",
                instance_id=instance,
                decision=OrderDecision(
                    identity=identity, at=at, intent=TargetIntent(quantity=cls.quantity(quantity))
                ),
                quote=AccountQuote(price=cls.price(), at=at),
                maximum_fee=cls.money("1"),
                checkpoint=b"{}",
                touch=MarketTouch(bid=cls.price("99.50"), ask=cls.price()),
            ),
            context=PortfolioContext(
                portfolio_id="portfolio",
                strategy_id=instance,
                model_revision="rule-only",
                config_revision="d2",
                horizon="capture",
                reason="engineering-reference",
                venue="okx",
                settlement="spot",
                risk_bucket="spot",
                authority_scope="paper",
            ),
        )

    @classmethod
    def resting(cls, instance: str, identity: str, at: datetime) -> PortfolioDecision:
        """Bid ``gtc`` for two at 100, so the order rests below a 101 ask."""
        decision = cls.target(instance, identity, at, "0")
        intent = OrderIntent(
            side="buy", quantity=cls.quantity("2"), limit=cls.price(), time_in_force="gtc"
        )
        return msgspec.structs.replace(
            decision,
            request=msgspec.structs.replace(
                decision.request,
                decision=msgspec.structs.replace(decision.request.decision, intent=intent),
            ),
        )

    @classmethod
    def coordinate(
        cls, journal: AccountJournal, identity: str, at: datetime, *decisions: PortfolioDecision
    ) -> str:
        """Commit one batch one microsecond after its decisions and return its reason."""
        journal.observe(AccountQuote(price=cls.price(), at=at))
        commit = journal.coordinate(
            PortfolioBatch(
                identity=identity, at=at + timedelta(microseconds=1), decisions=decisions
            )
        )
        assert commit.status == "committed", commit.reason
        return commit.reason

    @classmethod
    def book(cls, journal: AccountJournal, after_ms: int, ask: str = "100") -> None:
        """Apply one book ``after_ms`` after the first decision: ten units each side."""
        at = cls.at + timedelta(milliseconds=after_ms)
        market = PaperMarket(
            identity=f"book-{after_ms}",
            at=at,
            bid=cls.price("99.50"),
            ask=cls.price(ask),
            bid_quantity=cls.quantity("10"),
            ask_quantity=cls.quantity("10"),
        )
        journal.apply_public_market("shared", market, cls.scenario())


class TestDecisionAdmissions:
    """Resolve each decision only through its own rows in a real account journal."""

    def test_each_lifecycle_resolves_only_through_its_own_rows(self, tmp_path: Path) -> None:
        """Immediate, arrival and replacement admissions pass; refusals and waits do not.

        Without the delayed scenario both decisions are admitted at once. With it, batch
        ``opens`` commits pending: alpha's resting bid is admitted at its +1 ms arrival
        while beta's 95-unit target is refused there for its order notional, and
        alpha's admission does not resolve beta. Batch ``replaces`` decides at +3 ms
        while the bid rests, so it waits as ``replacement_pending`` for the cancellation
        effective at +8 ms, arrives at +9 ms and is admitted by the +10 ms book. Batch
        ``trails`` at +11 ms has no later command, so its arrival is unresolved.
        """
        immediate = D2Account.open(tmp_path / "immediate.sqlite3", delayed=False)
        assert (
            D2Account.coordinate(
                immediate,
                "now",
                D2Account.at,
                D2Account.target("alpha", "alpha-now", D2Account.at, "2"),
                D2Account.target("beta", "beta-now", D2Account.at, "0"),
            )
            == "reserved"
        )
        immediate.close()
        journal = D2Account.open(tmp_path / "d2.sqlite3", delayed=True)
        at = D2Account.at
        assert (
            D2Account.coordinate(
                journal,
                "opens",
                at,
                D2Account.resting("alpha", "alpha-bid", at),
                D2Account.target("beta", "beta-large", at, "95"),
            )
            == "arrival_pending"
        )
        D2Account.book(journal, 2, ask="101")
        replaced_at = at + timedelta(milliseconds=3)
        assert (
            D2Account.coordinate(
                journal,
                "replaces",
                replaced_at,
                D2Account.target("alpha", "alpha-target", replaced_at, "3"),
            )
            == "replacement_pending"
        )
        for after_ms in (8, 9, 10):
            D2Account.book(journal, after_ms)
        trailing_at = at + timedelta(milliseconds=11)
        assert (
            D2Account.coordinate(
                journal,
                "trails",
                trailing_at,
                D2Account.target("beta", "beta-trails", trailing_at, "0"),
            )
            == "arrival_pending"
        )
        journal.close()
        config = D2Account.config()
        with AccountJournal.read_history(tmp_path / "immediate.sqlite3", config) as history:
            assert DecisionAdmissions.resolve(history, "shared", ["now"]) == {
                "committed:reserved": 1,
                "committed:target_matched": 1,
            }
            # A batch from another account's journal is not evidence here.
            assert DecisionAdmissions.resolve(history, "shared", ["opens"]) == {"missing_batch": 1}
            assert DecisionAdmissions.resolve(history, "other", ["now"]) == {"other_account": 2}
        pending = "committed:arrival_pending"
        with AccountJournal.read_history(tmp_path / "d2.sqlite3", config) as history:
            assert DecisionAdmissions.resolve(history, "shared", ["opens"]) == {
                f"{pending}->committed:reserved": 1,
                f"{pending}->rejected:order_notional_limit": 1,
            }
            # An exact retry names the same decision, which counts once.
            assert DecisionAdmissions.resolve(history, "shared", ["replaces", "replaces"]) == {
                "committed:replacement_pending->committed:reserved": 1
            }
            assert DecisionAdmissions.resolve(history, "shared", ["trails"]) == {
                f"{pending}->unresolved": 1
            }
            assert DecisionAdmissions.resolve(history, "shared", ["now"]) == {"missing_batch": 1}
        admitted = DecisionAdmissions.admitted()
        assert f"{pending}->committed:reserved" in admitted
        assert "committed:replacement_pending->committed:target_matched" in admitted
        assert f"{pending}->rejected:order_notional_limit" not in admitted
        assert pending not in admitted and f"{pending}->unresolved" not in admitted


class TestSustainedDecisions:
    """Attribute each selected checkpoint's decisions through the real shared observer."""

    @staticmethod
    def _trial(tmp_path: Path) -> tuple[Path, str, list[dict[str, object]]]:
        """Run one account's minute of the sustained mix through the real D2 path.

        The shared observer retains its measurement rows as a service does; the trial
        keeps the service configuration and the stopped journal's final state.
        """
        workload = SustainedWorkload(
            opening_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
            socket_root=Path("/private/tmp/capacity-sustained-decisions"),
        )
        service = workload.service_configuration()
        account = service.accounts[0].account_id
        source = next(
            item
            for item in service.sources
            if any(
                instance.account_id == account and instance.source == item.name
                for instance in service.instances
            )
        )
        trial = tmp_path / "phase"
        path = trial / f"measurements/run/{source.name}/run.{account}.paper.jsonl"
        measurements = RuntimeMeasurementJournal(path, sync_every=1)
        scratch = tmp_path / "scratch"
        try:
            replayed = workload._replay_mix(
                service, account, source, 1, scratch, 60, measurements=measurements
            )
        finally:
            measurements.close()
        assert replayed["arrivals_waiting"] == 0
        configuration = service.accounts[0].configuration
        codec = DomainCodec()
        final = AccountJournal(scratch / "account.sqlite3", configuration)
        state = final.result_snapshot(AccountExecutionRequest(action="inspect"))
        final.close()
        (trial / f"final-{account}.json").write_bytes(codec.encode_json(state))
        assert state.journal_path is not None
        # As the trial's cleanup does: the stopped journal's history at the cutoff.
        StoppedJournal.retain(trial, account, Path(state.journal_path), configuration)
        (trial / "configuration.json").write_bytes(codec.encode_json(service))
        rows = [
            msgspec.json.decode(line, type=dict[str, object])
            for line in path.read_bytes().splitlines()
        ]
        return trial, account, rows

    @staticmethod
    def _interval(trial: Path, start: int, stop: int) -> None:
        """Retain the measured interval's monotonic clocks."""
        (trial / "reads").mkdir(exist_ok=True)
        interval: dict[str, object] = {
            "started_monotonic_ns": start,
            "scheduled_stop_monotonic_ns": stop,
        }
        (trial / "reads/summary.json").write_bytes(msgspec.json.encode(interval))

    def test_decisions_belong_to_their_checkpoint_across_the_interval_boundary(
        self, tmp_path: Path
    ) -> None:
        """Every decision resolves at its own arrival, attributed to its own checkpoint.

        Each selected book commits one batch pending, and its two decisions arrive 1 ms
        later, settled by the next book's command. An interval opening just after the
        third selected book started excludes that batch although its arrival is settled
        inside the interval, and one closing just after the ninth started includes that
        batch although its arrival is settled only after the close: exactly six batches
        and twelve decisions, every one admitted.
        """
        trial, account, rows = self._trial(tmp_path)
        selected = [row for row in rows if row["policy_selected"] is True]
        assert len(selected) >= 10
        assert all(
            row["checkpoint_status"] == "committed"
            and row["checkpoint_reason"] == "arrival_pending"
            and len(cast(list[str], row["checkpoint_batches"])) == 1
            for row in selected
        )
        last = cast(int, selected[-1]["book_started_ns"]) + 1
        self._interval(trial, cast(int, selected[0]["book_started_ns"]), last)
        results = SustainedResults(trial)
        pending = "committed:arrival_pending->committed"
        assert results.commits() == {account: {"committed:arrival_pending": len(selected)}}
        graded = results.decisions()
        journal = cast(dict[str, int], graded[account].pop("journal"))
        # Every batch's two pending decision rows and their two arrival rows.
        assert journal["decisions"] == 4 * len(selected)
        assert graded == {
            account: {
                "readable": True,
                "batches": len(selected),
                "outcomes": {
                    f"{pending}:reserved": 2,
                    f"{pending}:target_matched": 2 * len(selected) - 2,
                },
            }
        }
        start = cast(int, selected[2]["book_started_ns"]) + 1
        stop = cast(int, selected[8]["book_started_ns"]) + 1
        settling = [rows[rows.index(selected[index]) + 1] for index in (2, 8)]
        assert not any(row["policy_selected"] for row in settling)
        assert start <= cast(int, settling[0]["book_started_ns"]) < stop
        assert cast(int, settling[1]["book_started_ns"]) >= stop
        self._interval(trial, start, stop)
        assert SustainedResults(trial).decisions() == {
            account: {
                "readable": True,
                "batches": 6,
                "outcomes": {f"{pending}:target_matched": 12},
                "journal": journal,
            }
        }

    def test_missing_journal_evidence_is_reported_never_passed(self, tmp_path: Path) -> None:
        """Without the stopped journal's final state, or with an unnamed batch, nothing passes."""
        trial, account, rows = self._trial(tmp_path)
        selected = [row for row in rows if row["policy_selected"] is True]
        self._interval(
            trial,
            cast(int, selected[0]["book_started_ns"]),
            cast(int, selected[-1]["book_started_ns"]) + 1,
        )
        (measured,) = trial.glob("measurements/*/*/*.paper.jsonl")
        first = next(row for row in rows if row["policy_selected"] is True)
        first["checkpoint_batches"] = None
        measured.write_bytes(b"".join(msgspec.json.encode(row) + b"\n" for row in rows))
        facts = SustainedResults(trial).decisions()[account]
        outcomes = cast(dict[str, int], facts["outcomes"])
        assert outcomes["unnamed_batch"] == 1
        assert not set(outcomes) <= DecisionAdmissions.admitted()
        (trial / f"final-{account}.json").unlink()
        facts = SustainedResults(trial).decisions()[account]
        assert facts["readable"] is False
        assert str(facts["reason"]).startswith("FileNotFoundError")

    def test_a_journal_reused_after_its_final_state_fails_closed(self, tmp_path: Path) -> None:
        """Regression: phase B reuses phase A's journals, which phase A's grading still names.

        The uncounted ``d2-lifecycle-1`` diagnostic showed all four journals that phase A's
        final states name rewritten by phase B's recovery and trading. Grading reads a
        journal only while it holds exactly the history retained at its cutoff: one more
        committed book, or absent retained digests, is reported and never passed.
        """
        trial, account, rows = self._trial(tmp_path)
        selected = [row for row in rows if row["policy_selected"] is True]
        self._interval(
            trial,
            cast(int, selected[0]["book_started_ns"]),
            cast(int, selected[-1]["book_started_ns"]) + 1,
        )
        assert SustainedResults(trial).decisions()[account]["readable"] is True
        service = DomainCodec().decode_json(
            (trial / "configuration.json").read_bytes(), PaperServiceConfiguration
        )
        configuration = service.accounts[0].configuration
        path = tmp_path / "scratch" / "account.sqlite3"
        journal = AccountJournal(path, configuration)
        (latest,) = journal.latest_paper_traces(account)
        market = msgspec.structs.replace(
            latest.market,
            identity=f"{latest.market.identity}-later",
            at=latest.market.at + timedelta(seconds=1),
        )
        journal.apply_public_market(account, market, latest.scenario)
        journal.close()
        facts = SustainedResults(trial).decisions()[account]
        assert facts == {
            "readable": False,
            "reason": "ValueError: journal advanced past its retained final state",
        }
        StoppedJournal.path(trial, account).unlink()
        facts = SustainedResults(trial).decisions()[account]
        assert facts["readable"] is False
        assert str(facts["reason"]).startswith("FileNotFoundError")
