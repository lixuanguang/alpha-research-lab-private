"""Prove public paper source faults and real coordination clocks fail closed."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
import pytest
from msgspec.structs import force_setattr, replace

# project library imports
from accounting import AccountLedger, AccountSnapshot
from applications.paper import run_live_shared_paper
from applications.paper.monitoring import retain_public_paper_monitoring
from configuration import (
    AccountConfiguration,
    BookRegistryConfiguration,
    BookSelection,
    CaptureConfig,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperStrategyIdentity,
)
from execution import (
    AccountControl,
    AccountControlResult,
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    PaperMarket,
    PortfolioContext,
)
from financial_units import Currency, Dimension, ExactRatio, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookAsOfIndex, BookRegistry
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest, Level
from reference_data.instruments import InstrumentId
from research.features import FeatureVector
from research.observations import (
    DecisionInputs,
    InputRequirement,
    LiveBookDecisionSource,
    NumericField,
)
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from runtime import (
    SharedBookDelivery,
    SharedDecisionRuntime,
    SharedPaperCaptureObserver,
    SharedStrategyBinding,
    SharedStrategyInput,
)
from runtime.live_paper import LiveBookDelivery
from runtime.shared_paper import _ObservedLiveBookDelivery, _ObservedSharedBookDelivery
from serialization import DomainCodec
from strategies import ConfirmedSignal, DecisionContext, OrderIntent
from telemetry import RuntimeMeasurementJournal


class _NoDecisionInputs:
    """Keep source and matching tests free of a strategy-generated order."""

    @property
    def identity(self) -> str:
        """Identify the no-decision source adapter."""
        return "no-decision-public-book"

    def build(self, inputs: DecisionInputs, market: PaperMarket) -> tuple[SharedStrategyInput, ...]:
        """Ignore an eligible book while preserving the observer's market effects."""
        return ()


class _SignalInputs:
    """Supply an exact positive signal only when the observer selects a book."""

    def __init__(self) -> None:
        """Count only book boundaries used to construct policy input."""
        self.calls = 0

    @property
    def identity(self) -> str:
        """Pin this deterministic test feature formula."""
        return "signal-public-book"

    def build(self, inputs: DecisionInputs, market: PaperMarket) -> tuple[SharedStrategyInput, ...]:
        """Provide one causal positive signal at the selected book cutoff."""
        self.calls += 1
        at = inputs.decision_at
        vector = FeatureVector(
            entity=inputs.entity,
            decision_at=at,
            event_at=at,
            information_start=at,
            available_at=at,
            expires_at=at + timedelta(seconds=1),
            definition=self.identity,
            fields=(NumericField(name="signal", units="score"),),
            values=(ExactRatio(numerator="1", denominator="1"),),
            reasons=("native-book",),
            input_identity=inputs.identity,
        )
        return (
            SharedStrategyInput(
                instance_id="alpha",
                context=DecisionContext(features=vector, prediction=None),
                quote=AccountQuote(price=market.ask, at=at),
            ),
        )


class _SequenceClock:
    """Return authored actual-clock observations in order for a bounded retry."""

    def __init__(self, times: tuple[datetime, ...]) -> None:
        """Keep the last clock value after the supplied sequence is exhausted."""
        self.times = times
        self.index = 0

    def __call__(self) -> datetime:
        """Read the next scripted UTC clock value."""
        result = self.times[min(self.index, len(self.times) - 1)]
        self.index += 1
        return result


class TestSharedPublicPaper:
    """Exercise durable invalidation, ordinary control flow and refusal boundaries."""

    at = datetime(2025, 1, 1, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("4476df8e-6342-4417-839e-e41b88f41446"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _money(cls, value: str) -> Money:
        """Create exact USDT account cash."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Create exact selected base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Create exact selected quote per base."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _capture(cls) -> CaptureConfig:
        """Load the maintained public OKX selection without making a connection."""
        root = Path(__file__).parents[3]
        return CaptureConfig.read(root / "configs/live/okx-btc-usdt.json")

    @classmethod
    def _request(cls) -> CaptureRequest:
        """Bind a fixed valid recording identity for saved native boundaries."""
        return CaptureRequest(
            config=cls._capture(),
            recording_id="11111111-1111-4111-8111-111111111111",
            implementation_identity="a" * 64,
        )

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Fund one isolated account under bounded paper risk policy."""
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.at - timedelta(seconds=1),
            accounts=(OpeningAccount(account_id="paper", cash=(cls._money("1000"),)),),
            instruments=(
                SpotLimits(
                    maximum=cls._quantity("10"),
                    lot=cls._quantity("1"),
                    tick=cls._price("0.01"),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("1000"),
                accounts=(AccountLimit(account_id="paper", maximum=cls._money("1000")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="paper",
                        maximum=cls._money("900"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=5_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=500,
                max_order_notional=cls._money("900"),
            ),
        )

    @classmethod
    def _binding(cls) -> SharedStrategyBinding:
        """Select one inert configured policy for the shared runtime contract."""
        return SharedStrategyBinding(
            instance_id="alpha",
            account_id="paper",
            entity=str(cls.dimension.instrument_id),
            policy=ConfirmedSignal(
                field=NumericField(name="signal", units="score"),
                quantity=cls._quantity("1"),
                confirmations=1,
            ),
            context=PortfolioContext(
                portfolio_id="test-portfolio",
                strategy_id="alpha",
                model_revision="rule-only",
                config_revision="test-v1",
                horizon="short",
                reason="public-paper-test",
                venue="okx",
                settlement="spot",
                risk_bucket="cash",
                authority_scope="paper",
            ),
            maximum_fee=cls._money("1"),
        )

    @classmethod
    def _scenario(cls) -> PaperExecutionScenario:
        """Declare off-chain paper costs for the selected instrument."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=1000,
            cancel_delay_us=2000,
            adverse=cls._price("0"),
            fee_rate=Decimal("0"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="public spot paper matching has no blockchain activity",
        )

    @classmethod
    def _requirement(cls) -> InputRequirement:
        """Use receipt freshness so authored rows need no exchange source clock."""
        return InputRequirement(
            name="book",
            family="book",
            field=NumericField(name="imbalance", units="dimensionless"),
            clock="receipt",
            max_age_us=5_000_000,
        )

    @classmethod
    def _opening(cls) -> AccountObservation:
        """Author the independent opening cash and no-order observation."""
        return AccountObservation(
            identity="opening",
            at=cls.at - timedelta(seconds=1),
            snapshot=AccountSnapshot(
                account_id="paper",
                instance_id=None,
                cash=(cls._money("1000"),),
                positions=(),
                fees=(cls._money("0"),),
                rebates=(cls._money("0"),),
                transfers=(cls._money("1000"),),
                fill_ids=(),
                posting_ids=("opening:USDT",),
            ),
            open_orders=(),
        )

    @classmethod
    def _observer(
        cls,
        path: Path,
        *,
        scenario: PaperExecutionScenario | None = None,
        clock: _SequenceClock | None = None,
        market_interval_us: int = 0,
        retain: bool = False,
        inputs: _SignalInputs | None = None,
        measurements: RuntimeMeasurementJournal | None = None,
        index: BookAsOfIndex | None = None,
    ) -> tuple[SharedPaperCaptureObserver, AccountJournal]:
        """Construct the actual source, registry, account and decision owners."""
        request = cls._request()
        requirement = cls._requirement()
        source = LiveBookDecisionSource(request, requirement, history_capacity=20)
        books = BookRegistry(
            BookRegistryConfiguration(
                selections=(
                    BookSelection.from_capture(
                        request.config,
                        source_id=request.identity,
                        capability=BookAdapters.capability(request.config),
                        max_age_ns=5_000_000_000,
                        allow_degraded=True,
                    ),
                ),
                equivalences=(),
                history_capacity=20,
            )
        )
        journal = AccountJournal(path, cls._config())
        runtime = SharedDecisionRuntime(journal, (cls._binding(),))
        observer = SharedPaperCaptureObserver(
            source=source,
            books=books,
            journal=journal,
            runtime=runtime,
            account_id="paper",
            scenario=scenario or cls._scenario(),
            inputs=inputs if inputs is not None else _NoDecisionInputs(),
            delivery_path=path.with_suffix(".jsonl") if retain else None,
            clock=clock,
            market_interval_us=market_interval_us,
            measurements=measurements,
            index=index,
        )
        return observer, journal

    @classmethod
    def _delivery(
        cls,
        position: int,
        *,
        seconds: int,
        kind: Literal["session", "frame", "gap", "session_end", "end"],
        outcome: str,
        status: str,
        reason: str,
        market: bool = False,
        state_identity: str = "1" * 64,
    ) -> SharedBookDelivery:
        """Author a canonical received control or two-sided market boundary."""
        at = cls.at + timedelta(seconds=seconds)
        received_ns = int(at.timestamp()) * 1_000_000_000
        record = CaptureRecord(
            kind=kind,
            epoch=0,
            received_ns=received_ns,
            raw=b"{}" if kind == "frame" else b"",
            reason=reason if kind not in ("frame", "session") else "",
        )
        level = Level(size=Decimal("4"), order_count=1)
        row = BookObservation(
            position=position,
            epoch=0,
            received_ns=received_ns,
            source_time=str(received_ns // 1_000_000) if market else None,
            sequence=None,
            outcome=outcome,
            status=status,
            reason=reason,
            state_identity=state_identity,
            bids=((Decimal("99"), level),) if market else (),
            asks=((Decimal("100"), level),) if market else (),
        )
        return SharedBookDelivery(
            source=LiveBookDelivery(record=record, book=row, available_at=at),
            inputs=(),
            coordinated_at=None,
        )

    def test_market_interval_retains_every_book_but_only_selected_effects(
        self, tmp_path: Path
    ) -> None:
        """Intermediate native updates advance source state without pricing or matching."""
        path = tmp_path / "sampled.sqlite3"
        times = tuple(self.at + timedelta(seconds=seconds) for seconds in range(5))
        clock = _SequenceClock(
            (
                times[0],
                times[1],
                times[1] + timedelta(microseconds=1),
                times[2],
                times[3],
                times[4],
                times[4] + timedelta(microseconds=1),
            )
        )
        inputs = _SignalInputs()
        measurement_path = tmp_path / "paper-measurements.jsonl"
        measurements = RuntimeMeasurementJournal(measurement_path, sync_every=1)
        as_of = BookAsOfIndex.create(path.with_suffix(".index.sqlite3"))
        observer, journal = self._observer(
            path,
            clock=clock,
            market_interval_us=3_000_000,
            retain=True,
            inputs=inputs,
            measurements=measurements,
            index=as_of,
        )
        assert journal.reconcile(self._opening())
        deliveries = (
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            ),
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
            self._delivery(
                2,
                seconds=2,
                kind="frame",
                outcome="update",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
            self._delivery(
                3,
                seconds=3,
                kind="frame",
                outcome="update",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
            self._delivery(
                4,
                seconds=4,
                kind="frame",
                outcome="update",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
        )
        for index, delivery in enumerate(deliveries):
            observer.observe(delivery.source.record, delivery.source.book)
            if index == 1:
                first_effects = (
                    journal.accounts(),
                    journal.orders(),
                    journal.paper_traces("paper"),
                    journal.checkpoint("alpha"),
                )
                assert first_effects[3] is not None
            if index in (2, 3):
                assert (
                    journal.accounts(),
                    journal.orders(),
                    journal.paper_traces("paper"),
                    journal.checkpoint("alpha"),
                ) == first_effects
                assert inputs.calls == 1
                assert observer.source.latest_book is not None
                assert observer.source.latest_book.position == index
                assert observer.last_market is not None
                assert observer.last_market.at == times[index]
        assert inputs.calls == 2
        assert journal.checkpoint("alpha") != first_effects[3]
        assert observer.delivered_count == len(deliveries)
        measurements.close()
        measured = tuple(
            msgspec.json.decode(line, type=dict[str, object])
            for line in measurement_path.read_bytes().splitlines()
        )
        assert len(measured) == len(deliveries)
        assert tuple(item["position"] for item in measured) == tuple(range(5))
        assert tuple(item["market_selected"] for item in measured) == (
            False,
            True,
            False,
            False,
            True,
        )
        selected_rows = tuple(item for item in measured if item["policy_selected"] is True)
        assert len(selected_rows) == 2
        assert all(item["checkpoint_acknowledged"] is True for item in selected_rows)
        assert all(
            isinstance(item["book_to_checkpoint_ns"], int) and item["book_to_checkpoint_ns"] >= 0
            for item in selected_rows
        )
        codec = DomainCodec()
        retained_bytes = path.with_suffix(".jsonl").read_bytes().splitlines()
        retained = tuple(codec.decode_json(line, SharedBookDelivery) for line in retained_bytes)
        assert len(retained) == len(deliveries)
        for payload, delivery in zip(retained_bytes, retained, strict=True):
            observed_source = _ObservedLiveBookDelivery(
                record=delivery.source.record,
                book=delivery.source.book,
                available_at=delivery.source.available_at,
            )
            observed = _ObservedSharedBookDelivery(
                source=observed_source,
                inputs=delivery.inputs,
                coordinated_at=delivery.coordinated_at,
                schema_version=delivery.schema_version,
                market_effects=delivery.market_effects,
            )
            assert codec.encode_json(observed_source) == codec.encode_json(delivery.source)
            assert codec.encode_json(observed) == codec.encode_json(delivery) == payload
        assert tuple(item.source.book.position for item in retained) == tuple(range(5))
        as_of.close()
        selection = observer.books.lookup(observer._key, cutoff_ns=0).selection
        offset = 0
        for payload, delivery in zip(retained_bytes, retained, strict=True):
            elapsed = delivery.source.available_at - datetime(1970, 1, 1, tzinfo=UTC)
            cutoff = (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000 + (
                elapsed.microseconds * 1000
            )
            lookup, selected = BookAsOfIndex(as_of.path).lookup(selection, cutoff_ns=cutoff)
            assert lookup == observer.books.lookup(observer._key, cutoff_ns=cutoff)
            target = lookup.quote if lookup.quote is not None else lookup.boundary
            assert target is not None and selected is not None
            if target.position == delivery.source.book.position:
                assert selected == (offset, len(payload) + 1)
            offset += len(payload) + 1
        assert BookAsOfIndex(as_of.path).covered_bytes() == offset
        assert tuple(item.market_effects for item in retained) == (
            msgspec.UNSET,
            msgspec.UNSET,
            False,
            False,
            msgspec.UNSET,
        )
        assert len(journal.paper_traces("paper")) == 2
        assert AccountLedger(journal.accounts()[0].ledger).snapshot().positions == (
            self._quantity("1"),
        )

        replay_inputs = _SignalInputs()
        replay, recovered = self._observer(tmp_path / "replay.sqlite3", inputs=replay_inputs)
        assert recovered.reconcile(self._opening())
        for delivery in retained:
            replay.deliver(delivery)
        assert replay_inputs.calls == 0
        assert recovered.accounts() == journal.accounts()
        assert recovered.orders() == journal.orders()
        assert recovered.paper_traces("paper") == journal.paper_traces("paper")
        assert recovered.paper_report_facts("paper") == journal.paper_report_facts("paper")
        assert recovered.checkpoint("alpha") == journal.checkpoint("alpha")

    def test_market_interval_never_delays_source_fault(self, tmp_path: Path) -> None:
        """An invalid boundary inside the interval blocks a previously priced account."""
        observer, journal = self._observer(
            tmp_path / "invalid.sqlite3", market_interval_us=3_000_000
        )
        assert journal.reconcile(self._opening())
        for delivery in (
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            ),
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
            replace(
                self._delivery(
                    2,
                    seconds=2,
                    kind="frame",
                    outcome="update",
                    status="degraded",
                    reason="visible_depth_only",
                    market=True,
                ),
                market_effects=False,
            ),
            self._delivery(
                3,
                seconds=3,
                kind="gap",
                outcome="gap",
                status="recovering",
                reason="disconnect_unknown_loss",
            ),
        ):
            observer.deliver(delivery)
        assert journal.accounts()[0].operator_block == "public_input_invalid"
        assert observer.last_market is not None
        assert observer.last_market.at == self.at + timedelta(seconds=2)

    def test_market_interval_bounds_and_legacy_wire_identity(self, tmp_path: Path) -> None:
        """The omitted selection field preserves v1 bytes; invalid cadence fails early."""
        delivery = self._delivery(
            0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
        )
        codec = DomainCodec()
        expected = codec.encode_json(
            {
                "source": delivery.source,
                "inputs": delivery.inputs,
                "coordinated_at": delivery.coordinated_at,
                "schema_version": delivery.schema_version,
            }
        )
        assert codec.encode_json(delivery) == expected
        assert b"market_effects" not in expected
        assert codec.decode_json(expected, SharedBookDelivery) == delivery
        assert hashlib.sha256(codec.encode_json(delivery)).hexdigest() == (
            hashlib.sha256(expected).hexdigest()
        )
        with pytest.raises(ValueError, match="cannot coordinate"):
            replace(delivery, market_effects=False, coordinated_at=self.at)
        for interval in (-1, True, 5_000_001, 10_000_000):
            with pytest.raises(ValueError, match="market interval"):
                self._observer(tmp_path / f"bad-{interval}.sqlite3", market_interval_us=interval)

    def test_managed_invalidations_fault_once_per_observer(self, tmp_path: Path) -> None:
        """The first bad source fact faults its owner without repeated account loads."""
        path = tmp_path / "managed-invalid.sqlite3"
        observer, original = self._observer(path)
        clock = _SequenceClock((self.at - timedelta(seconds=1),))
        admin = AccountJournal(path, original.config, clock=clock)
        deployment = PaperDeployment(
            account_id="paper",
            configuration_sha256=hashlib.sha256(
                DomainCodec().encode_json(original.config)
            ).hexdigest(),
            releases=("a" * 64,),
            strategies=(
                PaperStrategyIdentity(
                    instance_id="alpha",
                    policy_identity="test",
                    candidate_identity="test",
                    model_identity="test",
                    feature_identity="test",
                ),
            ),
            input_identity="test",
            scenario=self._scenario(),
            state_identity="paper-account-state-v1",
        )
        admin.install_paper(deployment)
        admin.authorize_paper(
            PaperAuthorization(
                identity="fault-test",
                deployment_sha256=deployment.identity,
                valid_from=self.at - timedelta(seconds=1),
                expires_at=self.at + timedelta(seconds=20),
                quantities=(self._quantity("10"),),
                maximum_order_notional=self._money("1000"),
                maximum_orders=10,
            )
        )
        observed = self.at - timedelta(microseconds=1)
        admin.observe(AccountQuote(price=self._price("100"), at=observed))
        assert admin.reconcile(replace(self._opening(), at=observed))
        clock.times = (self.at,)
        owner = admin.claim_paper(
            "paper",
            "fault-worker",
            "a" * 64,
            AccountControl(
                identity="fault-claim",
                account_id="paper",
                kind="restart",
                at=self.at,
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        clock.times = (self.at + timedelta(seconds=4),)
        worker = AccountJournal(path, original.config, paper_owner=owner, clock=clock)
        observer.journal = worker
        observer.runtime = SharedDecisionRuntime(worker, (self._binding(),))
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        first = self._delivery(
            2,
            seconds=2,
            kind="gap",
            outcome="gap",
            status="recovering",
            reason="disconnect_unknown_loss",
        )
        second = self._delivery(
            3,
            seconds=3,
            kind="gap",
            outcome="gap",
            status="recovering",
            reason="disconnect_unknown_loss",
        )
        observer.deliver(first)
        observer.deliver(second)
        controls = worker.controls()
        faults = tuple(item for item in controls if item.request.reason == "public_input_invalid")
        assert len(faults) == 1 and faults[0].status == "applied"
        assert faults[0].request.identity == (
            "public-input-fault:"
            + hashlib.sha256(DomainCodec().encode_json(first.source)).hexdigest()
        )
        observer._apply(first, None)
        assert worker.controls() == controls
        assert worker.accounts()[0].phase == "faulted"

    def test_public_fault_unknown_outcome_propagates_without_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An uncertain account write remains visible to the supervisor for fencing."""
        observer, journal = self._observer(tmp_path / "unknown-fault.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        calls = 0

        def uncertain(account_id: str, reason: str) -> None:
            """Model one account outcome whose commit result is unknown."""
            nonlocal calls
            calls += 1
            raise TimeoutError("unknown account outcome")

        monkeypatch.setattr(journal, "block", uncertain)
        with pytest.raises(TimeoutError, match="unknown account outcome"):
            observer.deliver(
                self._delivery(
                    2,
                    seconds=2,
                    kind="gap",
                    outcome="gap",
                    status="recovering",
                    reason="disconnect_unknown_loss",
                )
            )
        assert calls == 1
        assert journal.accounts()[0].operator_block is None

    def test_rejected_public_fault_is_not_confirmed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit rejected control fences the source instead of latching success."""
        observer, journal = self._observer(tmp_path / "rejected-fault.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        monkeypatch.setattr(journal, "paper_owner", object())
        calls = 0

        def reject(request: AccountControl) -> AccountControlResult:
            """Return a typed refusal without changing the account state."""
            nonlocal calls
            calls += 1
            return AccountControlResult(
                request=request,
                status="rejected",
                phase="running",
                recovery_generation=0,
                reason="test refusal",
            )

        monkeypatch.setattr(journal, "control", reject)
        with pytest.raises(ValueError, match="fault was not applied"):
            observer.deliver(
                self._delivery(
                    2,
                    seconds=2,
                    kind="gap",
                    outcome="gap",
                    status="recovering",
                    reason="disconnect_unknown_loss",
                )
            )
        assert calls == 1
        assert observer._public_faulted is False

    @pytest.mark.parametrize("is_private_wire", (False, True))
    def test_observer_rejects_mutated_nested_book_before_retention(
        self, tmp_path: Path, is_private_wire: bool
    ) -> None:
        """The public entry validates nested rows before either trusted private core."""
        path = tmp_path / "untrusted.sqlite3"
        observer, journal = self._observer(path, retain=True)
        assert journal.reconcile(self._opening())
        delivery = self._delivery(
            0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
        )
        if is_private_wire:
            delivery = _ObservedSharedBookDelivery(
                source=_ObservedLiveBookDelivery(
                    record=delivery.source.record,
                    book=delivery.source.book,
                    available_at=delivery.source.available_at,
                ),
                inputs=(),
                coordinated_at=None,
            )
        force_setattr(delivery.source.book, "state_identity", "bad")
        with pytest.raises(ValueError, match="book state or quality"):
            LiveBookDelivery(
                record=delivery.source.record,
                book=delivery.source.book,
                available_at=delivery.source.available_at,
            )
        with pytest.raises(ValueError, match="book state or quality"):
            SharedBookDelivery(source=delivery.source, inputs=(), coordinated_at=None)
        with pytest.raises(ValueError, match="book state or quality"):
            DomainCodec().decode_json(DomainCodec().encode_json(delivery), SharedBookDelivery)
        with pytest.raises(ValueError, match="book state or quality"):
            observer.observe(delivery.source.record, delivery.source.book)
        with pytest.raises(ValueError, match="book state or quality"):
            observer.deliver(delivery)
        assert not path.with_suffix(".jsonl").exists()
        assert observer.source.latest_book is None
        assert observer.delivered_count == 0

    def test_invalid_after_market_blocks_admission_and_preserves_order(
        self, tmp_path: Path
    ) -> None:
        """A gap revokes a known eligible source without releasing outstanding exposure."""
        observer, journal = self._observer(tmp_path / "account.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        assert journal.accounts()[0].operator_block is None
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        assert observer.last_market is not None
        at = self.at + timedelta(seconds=1, microseconds=1)
        order = AccountDecision(
            account_id="paper",
            instance_id="alpha",
            decision=OrderDecision(
                identity="open-order",
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=self._quantity("1"),
                    limit=self._price("100"),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=self._price("100"), at=self.at + timedelta(seconds=1)),
            maximum_fee=self._money("1"),
        )
        assert journal.admit(order).status == "committed"
        open_order = journal.orders()[0].order
        observer.deliver(
            self._delivery(
                2,
                seconds=2,
                kind="gap",
                outcome="gap",
                status="recovering",
                reason="disconnect_unknown_loss",
            )
        )
        assert AccountJournal(journal.path, journal.config).accounts()[0].operator_block == (
            "public_input_invalid"
        )
        assert journal.orders()[0].order == open_order
        later = AccountDecision(
            account_id="paper",
            instance_id="alpha",
            decision=OrderDecision(
                identity="after-gap",
                at=self.at + timedelta(seconds=2),
                intent=order.decision.intent,
            ),
            quote=order.quote,
            maximum_fee=self._money("1"),
        )
        assert journal.admit(later).status == "rejected"

    @classmethod
    def _unpriceable(
        cls, position: int, *, seconds: int, crossed: bool = False
    ) -> SharedBookDelivery:
        """Author a valid per-order boundary that is one-sided or crossed mid-update."""
        delivery = cls._delivery(
            position,
            seconds=seconds,
            kind="frame",
            outcome="update",
            status="degraded",
            reason="visible_depth_only",
            market=True,
        )
        book = delivery.source.book
        level = Level(size=Decimal("4"), order_count=1)
        book = replace(book, asks=((Decimal("98"), level),) if crossed else ())
        return replace(delivery, source=replace(delivery.source, book=book))

    def test_transient_unpriceable_book_faults_only_after_freshness(self, tmp_path: Path) -> None:
        """Intermediate per-order states are unpriced; a persistent one still faults."""
        observer, journal = self._observer(tmp_path / "transient.sqlite3")
        assert journal.reconcile(self._opening())
        opening = (
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            ),
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
        )
        for delivery in (
            *opening,
            self._unpriceable(2, seconds=2),
            self._unpriceable(3, seconds=2, crossed=True),
            self._delivery(
                4,
                seconds=3,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            ),
            self._delivery(
                5,
                seconds=4,
                kind="frame",
                outcome="update",
                status="degraded",
                reason="visible_depth_only",
                market=True,
                state_identity="2" * 64,
            ),
        ):
            observer.deliver(delivery)
        assert journal.accounts()[0].operator_block is None
        assert observer.last_market is not None
        assert observer.last_market.at == self.at + timedelta(seconds=4)
        persistent, persistent_journal = self._observer(tmp_path / "persistent.sqlite3")
        assert persistent_journal.reconcile(self._opening())
        for delivery in (*opening, self._unpriceable(2, seconds=2)):
            persistent.deliver(delivery)
        assert persistent_journal.accounts()[0].operator_block is None
        persistent.deliver(
            self._delivery(
                3,
                seconds=7,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            )
        )
        assert persistent_journal.accounts()[0].operator_block == "public_input_invalid"
        lost, lost_journal = self._observer(tmp_path / "lost.sqlite3")
        assert lost_journal.reconcile(self._opening())
        for delivery in (
            *opening,
            self._unpriceable(2, seconds=2),
            self._delivery(
                3,
                seconds=2,
                kind="gap",
                outcome="gap",
                status="recovering",
                reason="disconnect_unknown_loss",
            ),
        ):
            lost.deliver(delivery)
        assert lost_journal.accounts()[0].operator_block == "public_input_invalid"

    def test_healthy_controls_do_not_block_but_stale_progress_does(self, tmp_path: Path) -> None:
        """Heartbeat and normal finite close preserve readiness; stale input revokes it."""
        observer, journal = self._observer(tmp_path / "account.sqlite3")
        assert journal.reconcile(self._opening())
        observer.deliver(
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            )
        )
        observer.deliver(
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            )
        )
        before_control = (
            journal.accounts(),
            journal.orders(),
            journal.paper_traces("paper"),
            journal.checkpoint("alpha"),
        )
        observer.deliver(
            self._delivery(
                2,
                seconds=2,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            )
        )
        assert journal.accounts()[0].operator_block is None
        assert (
            journal.accounts(),
            journal.orders(),
            journal.paper_traces("paper"),
            journal.checkpoint("alpha"),
        ) == before_control
        observer.deliver(
            self._delivery(
                3,
                seconds=2,
                kind="session_end",
                outcome="session_end",
                status="unavailable",
                reason="message_limit",
            )
        )
        observer.deliver(
            self._delivery(
                4,
                seconds=2,
                kind="end",
                outcome="end",
                status="unavailable",
                reason="message_limit",
            )
        )
        assert journal.accounts()[0].operator_block is None
        stale, stale_journal = self._observer(tmp_path / "stale.sqlite3")
        assert stale_journal.reconcile(self._opening())
        for delivery in (
            self._delivery(
                0, seconds=0, kind="session", outcome="session", status="recovering", reason="new"
            ),
            self._delivery(
                1,
                seconds=1,
                kind="frame",
                outcome="snapshot",
                status="degraded",
                reason="visible_depth_only",
                market=True,
            ),
            self._delivery(
                2,
                seconds=7,
                kind="frame",
                outcome="heartbeat",
                status="degraded",
                reason="unchanged",
            ),
        ):
            stale.deliver(delivery)
        assert stale_journal.accounts()[0].operator_block == "public_input_invalid"

    def test_coordination_reads_real_clock_until_after_delivery(self, tmp_path: Path) -> None:
        """Equal microsecond samples retry; a frozen clock fails without inventing time."""
        later = self.at + timedelta(microseconds=1)
        observer, _ = self._observer(
            tmp_path / "account.sqlite3", clock=_SequenceClock((self.at, self.at, later))
        )
        assert observer._coordination_time(self.at) == later
        frozen, _ = self._observer(tmp_path / "frozen.sqlite3", clock=_SequenceClock((self.at,)))
        with pytest.raises(ValueError, match="did not advance"):
            frozen._coordination_time(self.at)

    @pytest.mark.parametrize("changed", ("model", "feature"))
    def test_managed_workload_identity_mismatch_precedes_capture(
        self, tmp_path: Path, changed: str
    ) -> None:
        """Refuse changed model or feature bindings before source access or economics."""
        config, binding, inputs = self._config(), self._binding(), _NoDecisionInputs()
        request, requirement = self._request(), self._requirement()
        codec = DomainCodec()
        deployment = PaperDeployment(
            account_id="paper",
            configuration_sha256=hashlib.sha256(codec.encode_json(config)).hexdigest(),
            releases=("a" * 64,),
            strategies=(
                PaperStrategyIdentity(
                    instance_id=binding.instance_id,
                    policy_identity=binding.policy.identity,
                    candidate_identity="reference-policy-v1",
                    model_identity="changed-model" if changed == "model" else "rule-only",
                    feature_identity="changed-feature" if changed == "feature" else inputs.identity,
                ),
            ),
            input_identity=hashlib.sha256(
                codec.encode_json((request.config, requirement, inputs.identity))
            ).hexdigest(),
            scenario=self._scenario(),
            state_identity="paper-account-state-v1",
        )
        path = tmp_path / "managed.sqlite3"
        admin = AccountJournal(path, config)
        admin.install_paper(deployment)
        admin.authorize_paper(
            PaperAuthorization(
                identity="bounded-workload",
                deployment_sha256=deployment.identity,
                valid_from=self.at,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                quantities=(self._quantity("2"),),
                maximum_order_notional=self._money("100"),
                maximum_orders=2,
            )
        )
        assert admin.reconcile(replace(self._opening(), at=datetime.now(UTC)))
        admin.observe(AccountQuote(price=self._price("10"), at=datetime.now(UTC)))
        owner = admin.claim_paper(
            "paper",
            "reference-worker",
            "a" * 64,
            AccountControl(
                identity="claim-reference",
                account_id="paper",
                kind="restart",
                at=datetime.now(UTC),
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        before = admin.accounts()
        with pytest.raises(ValueError, match="deployment workload bindings differ"):
            asyncio.run(
                run_live_shared_paper(
                    config,
                    account_id="paper",
                    bindings=(binding,),
                    scenario=self._scenario(),
                    requirement=requirement,
                    inputs=inputs,
                    request=request,
                    journal_path=path,
                    output=tmp_path / "capture",
                    paper_account=AccountJournal(path, config, paper_owner=owner),
                )
            )
        assert admin.accounts() == before
        assert admin.orders() == ()
        assert not (tmp_path / "capture").exists()

    def test_binding_and_opening_refusals_leave_visible_account_block(self, tmp_path: Path) -> None:
        """A foreign scenario fails before binding, and a bad opening blocks the journal."""
        with pytest.raises(ValueError, match="binding differs"):
            self._observer(
                tmp_path / "binding.sqlite3",
                scenario=PaperExecutionScenario(
                    venue="bitfinex",
                    instrument_id=self.dimension.instrument_id,
                    entry_delay_us=1000,
                    cancel_delay_us=2000,
                    adverse=self._price("0"),
                    fee_rate=Decimal("0"),
                    take_fraction=Decimal("1"),
                    gas_inapplicable_reason="off-chain",
                ),
            )
        bad = AccountObservation(
            identity="wrong-opening",
            at=self._opening().at,
            snapshot=AccountSnapshot(
                account_id="wrong",
                instance_id=None,
                cash=(self._money("1000"),),
                positions=(),
                fees=(self._money("0"),),
                rebates=(self._money("0"),),
                transfers=(self._money("1000"),),
                fill_ids=(),
                posting_ids=("opening:USDT",),
            ),
            open_orders=(),
        )
        path = tmp_path / "opening.sqlite3"
        with pytest.raises(ValueError, match="opening or recovery reconciliation failed"):
            asyncio.run(
                run_live_shared_paper(
                    self._config(),
                    account_id="paper",
                    bindings=(self._binding(),),
                    scenario=self._scenario(),
                    requirement=self._requirement(),
                    inputs=_NoDecisionInputs(),
                    request=self._request(),
                    journal_path=path,
                    output=tmp_path / "run",
                    observations=(bad,),
                )
            )
        assert AccountJournal(path, self._config()).accounts()[0].operator_block == (
            "public_paper_failure"
        )
        prior_path = tmp_path / "source-invalid.sqlite3"
        AccountJournal(prior_path, self._config()).block("paper", "public_input_invalid")
        with pytest.raises(ValueError, match="opening or recovery reconciliation failed"):
            asyncio.run(
                run_live_shared_paper(
                    self._config(),
                    account_id="paper",
                    bindings=(self._binding(),),
                    scenario=self._scenario(),
                    requirement=self._requirement(),
                    inputs=_NoDecisionInputs(),
                    request=self._request(),
                    journal_path=prior_path,
                    output=tmp_path / "prior-run",
                    observations=(bad,),
                )
            )
        assert AccountJournal(prior_path, self._config()).accounts()[0].operator_block == (
            "public_input_invalid"
        )

    def test_public_monitoring_passes_only_selected_accounts_orders(self, tmp_path: Path) -> None:
        """Ignore other accounts' orders and preserve both ledgers during monitoring."""
        base = self._config()
        account_ids = ("paper", "paper-other")
        budgets = replace(
            base.budgets,
            firm_maximum=self._money("2000"),
            accounts=(
                AccountLimit(account_id="paper", maximum=self._money("1000")),
                AccountLimit(account_id="paper-other", maximum=self._money("1000")),
            ),
            instances=(
                InstanceLimit(
                    instance_id="alpha",
                    account_id="paper",
                    maximum=self._money("900"),
                    instruments=(self.dimension.instrument_id,),
                ),
                InstanceLimit(
                    instance_id="beta",
                    account_id="paper-other",
                    maximum=self._money("900"),
                    instruments=(self.dimension.instrument_id,),
                ),
            ),
        )
        config = replace(
            base,
            accounts=(
                OpeningAccount(account_id="paper", cash=(self._money("1000"),)),
                OpeningAccount(account_id="paper-other", cash=(self._money("1000"),)),
            ),
            budgets=budgets,
        )
        journal = AccountJournal(tmp_path / "accounts.sqlite3", config)
        opening = self._opening()
        for account_id in account_ids:
            account_opening = replace(
                opening,
                identity=f"opening-{account_id}",
                snapshot=replace(
                    opening.snapshot,
                    account_id=account_id,
                ),
            )
            assert journal.reconcile(account_opening)

        scenario = self._scenario()
        journal.bind_paper_scenario("paper", scenario)
        other_order = AccountDecision(
            account_id="paper-other",
            instance_id="beta",
            decision=OrderDecision(
                identity="other-account-order",
                at=self.at,
                intent=OrderIntent(
                    side="buy",
                    quantity=self._quantity("1"),
                    limit=self._price("100"),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=self._price("100"), at=self.at),
            maximum_fee=self._money("1"),
        )
        journal.observe(other_order.quote)
        admitted = journal.admit(other_order)
        assert admitted.status == "committed", admitted.reason
        trace = journal.match_public_market(
            "paper",
            PaperMarket(
                identity="paper-market",
                at=self.at + timedelta(seconds=1),
                bid=self._price("99.99"),
                ask=self._price("100"),
                bid_quantity=self._quantity("1"),
                ask_quantity=self._quantity("1"),
            ),
            scenario,
        )
        assert trace.account_id == "paper"
        assert {item.account_id for item in journal.orders()} == {"paper-other"}
        ledgers_before = {view.ledger.account_id: view.ledger for view in journal.accounts()}
        assert set(ledgers_before) == set(account_ids)
        assert all(
            AccountLedger(ledger).snapshot().cash == (self._money("1000"),)
            for ledger in ledgers_before.values()
        )

        result = retain_public_paper_monitoring(
            journal,
            account_id="paper",
            request=self._request(),
            root=tmp_path,
            observed_at=self.at + timedelta(seconds=2),
            report=None,
            decisions=(),
            prior_trace_ids=frozenset(),
            summary={},
            processing_ns=None,
            delivered_count=0,
            alert_socket=None,
        )

        assert result.errors == ()
        assert result.dashboards
        assert {
            view.ledger.account_id: view.ledger for view in journal.accounts()
        } == ledgers_before
