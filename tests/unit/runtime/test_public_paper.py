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
import pytest
from msgspec.structs import replace

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
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    PaperMarket,
    PortfolioContext,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from market_data.adapters.sources import BookAdapters
from market_data.books import BookRegistry
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest, Level
from reference_data.instruments import InstrumentId
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
from serialization import DomainCodec
from strategies import ConfirmedSignal, OrderIntent


class _NoDecisionInputs:
    """Keep source and matching tests free of a strategy-generated order."""

    @property
    def identity(self) -> str:
        """Identify the no-decision source adapter."""
        return "no-decision-public-book"

    def build(self, inputs: DecisionInputs, market: PaperMarket) -> tuple[SharedStrategyInput, ...]:
        """Ignore an eligible book while preserving the observer's market effects."""
        return ()


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
            inputs=_NoDecisionInputs(),
            delivery_path=None,
            clock=clock,
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
