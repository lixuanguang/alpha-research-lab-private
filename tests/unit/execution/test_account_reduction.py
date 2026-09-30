"""Prove paper reductions reserve only attributable uncommitted spot inventory."""

from __future__ import annotations

# standard library imports
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
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    PaperAuthorization,
    PaperDeployment,
    PaperExecutionScenario,
    PaperStrategyIdentity,
)
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountControl,
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    OrderEvent,
    PaperMarket,
    PaperReductionRequest,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


class _PaperClock:
    """Advance actual admission time independently of reduction request time."""

    def __init__(self, at: datetime) -> None:
        """Start the local UTC clock."""
        self.at = at

    def __call__(self) -> datetime:
        """Return the time sampled inside each economic transaction."""
        return self.at


class TestAccountReduction:
    """Exercise local controls, full ownership and finite public matching."""

    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _at(cls, seconds: int) -> datetime:
        """Use a monotonic local paper clock."""
        return cls.opening_at + timedelta(seconds=seconds)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Build exact quote-currency account money."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Build exact attributable spot units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Build exact spot price on the configured tick."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Bound two independent strategies in one funded paper account."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("20"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("1000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("1000"),
                accounts=(AccountLimit(account_id="shared", maximum=cls._money("1000")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="shared",
                        maximum=cls._money("1000"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                    InstanceLimit(
                        instance_id="beta",
                        account_id="shared",
                        maximum=cls._money("1000"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=10_000_000,
                max_state_age_us=60_000_000,
                max_price_deviation_bps=200,
                max_order_notional=cls._money("1000"),
            ),
        )

    @classmethod
    def _scenario(cls) -> PaperExecutionScenario:
        """Declare one finite public top-of-book paper matcher."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=cls._price("0.01"),
            fee_rate=Decimal(0),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot matching",
        )

    @classmethod
    def _market(cls, identity: str, at: datetime, *, bid_quantity: str = "5") -> PaperMarket:
        """Provide finite bid liquidity without manufacturing any fill."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price("9.95"),
            ask=cls._price("10.05"),
            bid_quantity=cls._quantity(bid_quantity),
            ask_quantity=cls._quantity("5"),
        )

    @classmethod
    def _opening(cls) -> AccountSnapshot:
        """State the independent initial cash and posting identity."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(cls._money("1000"),),
            positions=(),
            fees=(cls._money("0"),),
            rebates=(cls._money("0"),),
            transfers=(cls._money("1000"),),
            fill_ids=(),
            posting_ids=("opening:USDT",),
        )

    @classmethod
    def _ready(cls, path: Path) -> AccountJournal:
        """Bind a scenario and reconcile opening cash before any order."""
        journal = AccountJournal(path, cls._config())
        journal.bind_paper_scenario("shared", cls._scenario())
        assert journal.reconcile(
            AccountObservation(
                identity="opening",
                at=cls.opening_at,
                snapshot=cls._opening(),
                open_orders=(),
            )
        )
        return journal

    @classmethod
    def _request(
        cls,
        identity: str,
        at: datetime,
        quote: AccountQuote,
        *,
        instance_id: str = "alpha",
        quantity: str = "1",
        limit: str = "9.90",
    ) -> PaperReductionRequest:
        """Request an IOC sale with a visible operator minimum price."""
        return PaperReductionRequest(
            identity=identity,
            account_id="shared",
            instance_id=instance_id,
            quantity=cls._quantity(quantity),
            quote=quote,
            limit=cls._price(limit),
            maximum_fee=cls._money("0"),
            at=at,
        )

    @classmethod
    def _funded(cls, path: Path) -> AccountJournal:
        """Buy five alpha units through the matcher and reconcile actual economics."""
        journal = cls._ready(path)
        quote = AccountQuote(price=cls._price("10"), at=cls._at(1))
        journal.observe(quote)
        admitted = journal.admit(
            AccountDecision(
                account_id="shared",
                instance_id="alpha",
                decision=OrderDecision(
                    identity="alpha-buy",
                    at=cls._at(1),
                    intent=OrderIntent(
                        side="buy",
                        quantity=cls._quantity("5"),
                        limit=cls._price("10.10"),
                        time_in_force="ioc",
                    ),
                ),
                quote=quote,
                maximum_fee=cls._money("0"),
            )
        )
        assert admitted.status == "committed"
        buy_market = PaperMarket(
            identity="buy-market",
            at=cls._at(2),
            bid=cls._price("9.95"),
            ask=cls._price("10"),
            bid_quantity=cls._quantity("5"),
            ask_quantity=cls._quantity("5"),
        )
        journal.match_public_market("shared", buy_market, cls._scenario())
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.cash == (cls._money("949.95"),)
        assert snapshot.positions == (cls._quantity("5"),)
        assert len(snapshot.fill_ids) == 1
        assert journal.reconcile(
            AccountObservation(
                identity="after-buy",
                at=cls._at(3),
                snapshot=snapshot,
                open_orders=(),
            )
        )
        return journal

    @classmethod
    def _managed_funded(cls, path: Path) -> tuple[AccountJournal, _PaperClock]:
        """Claim a managed owner after reconciling five attributable units."""
        cls._funded(path)
        config = cls._config()
        clock = _PaperClock(cls._at(10))
        admin = AccountJournal(path, config, clock=clock)
        deployment = PaperDeployment(
            account_id="shared",
            configuration_sha256=hashlib.sha256(DomainCodec().encode_json(config)).hexdigest(),
            releases=("a" * 64,),
            strategies=(
                PaperStrategyIdentity(
                    instance_id="alpha",
                    policy_identity="policy-alpha",
                    candidate_identity="candidate-alpha",
                    model_identity="no-model",
                    feature_identity="feature-alpha",
                ),
            ),
            input_identity="public-okx-book",
            scenario=cls._scenario(),
            state_identity="paper-account-state",
        )
        admin.install_paper(deployment)
        clock.at = cls._at(11)
        admin.authorize_paper(
            PaperAuthorization(
                identity="bounded-reduction-session",
                deployment_sha256=deployment.identity,
                valid_from=cls._at(11),
                expires_at=cls._at(30),
                quantities=(cls._quantity("5"),),
                maximum_order_notional=cls._money("100"),
                maximum_orders=5,
            )
        )
        snapshot = AccountLedger(admin.accounts()[0].ledger).snapshot()
        assert admin.reconcile(
            AccountObservation(
                identity="after-managed-install",
                at=cls._at(12),
                snapshot=snapshot,
                open_orders=(),
            )
        )
        admin.observe(AccountQuote(price=cls._price("10"), at=cls._at(12)))
        clock.at = cls._at(13)
        owner = admin.claim_paper(
            "shared",
            "reduction-worker",
            "a" * 64,
            AccountControl(
                identity="claim-reduction-worker",
                account_id="shared",
                kind="restart",
                at=cls._at(13),
                expected_control_identity=f"paper-deployment:{deployment.identity}",
            ),
        )
        worker = AccountJournal(path, config, paper_owner=owner, clock=clock)
        assert worker.reconcile(
            AccountObservation(
                identity="after-managed-claim",
                at=cls._at(13),
                snapshot=snapshot,
                open_orders=(),
            )
        )
        return worker, clock

    @pytest.mark.parametrize(
        ("quote_second", "market_second", "request_second", "admission_second", "reason"),
        (
            (14, 14, 23, 32, "stale_quote"),
            (23, 14, 23, 32, "stale_paper_market"),
            (64, 64, 65, 74, "stale_state"),
        ),
    )
    def test_managed_reduction_freshness_uses_serialized_admission_time(
        self,
        tmp_path: Path,
        quote_second: int,
        market_second: int,
        request_second: int,
        admission_second: int,
        reason: str,
    ) -> None:
        """A recent request cannot carry old quote, book or account state into an order."""
        worker, clock = self._managed_funded(tmp_path / "managed-freshness.sqlite3")
        clock.at = self._at(market_second)
        worker.match_public_market(
            "shared", self._market("freshness-book", clock.at), self._scenario()
        )
        clock.at = self._at(quote_second)
        quote = AccountQuote(price=self._price("10"), at=clock.at)
        worker.observe(quote)
        before_orders = worker.orders()
        before_ledger = worker.accounts()[0].ledger
        request = self._request("freshness-reduction", self._at(request_second), quote)
        clock.at = self._at(admission_second)
        result = worker.reduce_paper(request)
        assert (result.status, result.reason, result.orders) == ("rejected", reason, ())
        assert worker.orders() == before_orders
        assert worker.accounts()[0].ledger == before_ledger
        assert worker.paper_reductions() == (result,)

    def test_managed_reduction_retry_replays_after_input_and_grant_expiry(
        self, tmp_path: Path
    ) -> None:
        """The current owner can retrieve one original reservation without a second order."""
        worker, clock = self._managed_funded(tmp_path / "managed-retry.sqlite3")
        clock.at = self._at(14)
        worker.match_public_market(
            "shared", self._market("reduction-book", clock.at), self._scenario()
        )
        quote = AccountQuote(price=self._price("10"), at=clock.at)
        worker.observe(quote)
        request = self._request("durable-reduction", clock.at, quote)
        result = worker.reduce_paper(request)
        assert result.status == "accepted"
        before_orders = worker.orders()
        clock.at = self._at(35)
        assert worker.reduce_paper(request) == result
        assert worker.orders() == before_orders
        assert worker.paper_reductions() == (result,)
        with pytest.raises(ValueError, match="different content"):
            worker.reduce_paper(replace(request, quantity=self._quantity("2")))

    @pytest.mark.parametrize("kind", ("stop", "fault"))
    def test_controlled_reduction_is_request_until_finite_market_fill(
        self, tmp_path: Path, kind: Literal["stop", "fault"]
    ) -> None:
        """A stopped or faulted phase permits safe reduction but claims no immediate sale."""
        path = tmp_path / f"{kind}.sqlite3"
        journal = self._funded(path)
        control = journal.control(
            AccountControl(
                identity=f"{kind}-account",
                account_id="shared",
                kind=kind,
                at=self._at(4),
                reason="operator requested protective control",
            )
        )
        assert control.status == "applied"
        stale = journal.reduce_paper(
            self._request(
                "before-control-reconciliation",
                self._at(4),
                AccountQuote(price=self._price("10"), at=self._at(1)),
            )
        )
        assert (stale.status, stale.reason) == ("rejected", "account_reconciliation_stale")
        journal.match_public_market(
            "shared", self._market("pre-reduction", self._at(5)), self._scenario()
        )
        before = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert journal.reconcile(
            AccountObservation(
                identity=f"after-{kind}",
                at=self._at(5),
                snapshot=before,
                open_orders=(),
            )
        )
        quote = AccountQuote(price=self._price("10"), at=self._at(5))
        journal.observe(quote)
        request = self._request("reduce-alpha", self._at(6), quote, quantity="4")
        result = journal.reduce_paper(request)
        assert (result.status, result.reason) == ("accepted", "reserved")
        assert len(result.orders) == 1
        assert result.orders[0].status == "intent"
        assert result.orders[0].intent.side == "sell"
        assert result.orders[0].intent.limit == self._price("9.90")
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == before
        assert AccountJournal(path, self._config()).reduce_paper(request) == result
        assert len(journal.paper_reductions()) == 2
        with pytest.raises(ValueError, match="different content"):
            journal.reduce_paper(replace(request, quantity=self._quantity("3")))

        journal.match_public_market(
            "shared",
            self._market("partial-sale", self._at(7), bid_quantity="2"),
            self._scenario(),
        )
        sold = journal.orders()[-1].order
        assert sold.status == "cancelled"
        assert sold.filled == self._quantity("2")
        after = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert after.cash == (self._money("969.83"),)
        assert after.positions == (self._quantity("3"),)
        assert AccountJournal(path, self._config()).reduce_paper(request) == result

    def test_stopped_instance_can_request_its_own_reduction(self, tmp_path: Path) -> None:
        """Selective strategy stop fences new exposure while retaining owned reduction."""
        journal = self._funded(tmp_path / "instance.sqlite3")
        assert journal.stop_instance("alpha", self._at(4)) == ()
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert journal.reconcile(
            AccountObservation(
                identity="after-instance-stop",
                at=self._at(5),
                snapshot=snapshot,
                open_orders=(),
            )
        )
        journal.match_public_market(
            "shared", self._market("after-instance-stop", self._at(5)), self._scenario()
        )
        quote = AccountQuote(price=self._price("10"), at=self._at(5))
        journal.observe(quote)
        result = journal.reduce_paper(self._request("stopped-alpha", self._at(6), quote))
        assert result.status == "accepted"
        assert result.orders[0].intent.quantity == self._quantity("1")
        assert len(journal.paper_reductions()) == 1

    def test_portfolio_sell_reservation_and_other_strategy_inventory_are_excluded(
        self, tmp_path: Path
    ) -> None:
        """A child reserved by a net parent counts against alpha despite shared cash."""
        journal = self._funded(tmp_path / "portfolio.sqlite3")
        quote = AccountQuote(price=self._price("10"), at=self._at(4))
        journal.observe(quote)
        journal.match_public_market(
            "shared", self._market("pre-portfolio", self._at(4)), self._scenario()
        )
        portfolio = PortfolioDecision(
            request=AccountDecision(
                account_id="shared",
                instance_id="alpha",
                decision=OrderDecision(
                    identity="alpha-portfolio-sale",
                    at=self._at(5),
                    intent=OrderIntent(
                        side="sell",
                        quantity=self._quantity("4"),
                        limit=self._price("9.90"),
                        time_in_force="gtc",
                    ),
                ),
                quote=quote,
                maximum_fee=self._money("0"),
            ),
            context=PortfolioContext(
                portfolio_id="shared-portfolio",
                strategy_id="alpha",
                model_revision="model-one",
                config_revision="config-one",
                horizon="one-minute",
                reason="inventory-control",
                venue="OKX",
                settlement="spot-immediate",
                risk_bucket="spot",
                authority_scope="paper",
            ),
        )
        batch = PortfolioBatch(
            identity="reserved-portfolio-sale",
            at=self._at(5) + timedelta(microseconds=1),
            decisions=(portfolio,),
        )
        result = journal.coordinate(batch)
        assert result.status == "committed"
        assert len(result.net_orders) == 1
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert journal.reconcile(
            AccountObservation(
                identity="with-portfolio-sale",
                at=self._at(6),
                snapshot=snapshot,
                open_orders=(result.net_orders[0].order,),
            )
        )
        fresh_quote = AccountQuote(price=self._price("10"), at=self._at(6))
        journal.observe(fresh_quote)
        other = journal.reduce_paper(
            self._request("beta-cannot-sell-alpha", self._at(7), fresh_quote, instance_id="beta")
        )
        assert (other.status, other.reason) == (
            "rejected",
            "reduction_exceeds_uncommitted_owned_inventory",
        )
        excess = journal.reduce_paper(
            self._request("alpha-overcommits", self._at(7), fresh_quote, quantity="2")
        )
        assert (excess.status, excess.reason) == (
            "rejected",
            "reduction_exceeds_uncommitted_owned_inventory",
        )
        exact = journal.reduce_paper(self._request("alpha-last-unit", self._at(7), fresh_quote))
        assert exact.status == "accepted"
        assert len(journal.net_orders()) == 1
        assert snapshot == AccountLedger(journal.accounts()[0].ledger).snapshot()

    def test_unreconciled_disconnected_stale_and_uncertain_are_explicit(
        self, tmp_path: Path
    ) -> None:
        """Each independent safety input produces a persisted named rejection."""
        journal = AccountJournal(tmp_path / "gates.sqlite3", self._config())
        quote = AccountQuote(price=self._price("10"), at=self._at(1))
        assert journal.reduce_paper(self._request("unreconciled", self._at(1), quote)).reason == (
            "account_not_reconciled"
        )
        journal.bind_paper_scenario("shared", self._scenario())
        assert journal.reconcile(
            AccountObservation(
                identity="opening",
                at=self.opening_at,
                snapshot=self._opening(),
                open_orders=(),
            )
        )
        journal.observe(quote)
        assert journal.reduce_paper(self._request("disconnected", self._at(2), quote)).reason == (
            "paper_market_disconnected"
        )
        journal.match_public_market(
            "shared", self._market("connected", self._at(2)), self._scenario()
        )
        assert journal.reduce_paper(self._request("stale-quote", self._at(20), quote)).reason == (
            "stale_quote"
        )

        pending = journal.admit(
            AccountDecision(
                account_id="shared",
                instance_id="alpha",
                decision=OrderDecision(
                    identity="uncertain-buy",
                    at=self._at(3),
                    intent=OrderIntent(
                        side="buy",
                        quantity=self._quantity("1"),
                        limit=self._price("10"),
                        time_in_force="gtc",
                    ),
                ),
                quote=quote,
                maximum_fee=self._money("0"),
            )
        )
        assert pending.status == "committed"
        journal.apply_event(
            OrderEvent(
                identity="uncertain-receipt",
                order_id=pending.orders[0].identity,
                at=self._at(4),
                kind="unknown",
            )
        )
        uncertain = journal.reduce_paper(self._request("unknown-outcome", self._at(5), quote))
        assert (uncertain.status, uncertain.reason) == ("rejected", "order_outcome_uncertain")
        assert not journal.reconcile(
            AccountObservation(
                identity="broken-unknown-reconciliation",
                at=self._at(6),
                snapshot=self._opening(),
                open_orders=(journal.orders()[-1].order,),
            )
        )
        faulted = journal.reduce_paper(self._request("economic-break", self._at(7), quote))
        assert (faulted.status, faulted.reason) == (
            "rejected",
            "economic_reconciliation_fault",
        )

    def test_protective_admission_cannot_bypass_phase_for_a_buy(self, tmp_path: Path) -> None:
        """The internal protective switch validates sell intent on every call."""
        journal = self._funded(tmp_path / "protective.sqlite3")
        journal.control(
            AccountControl(
                identity="stop-buy",
                account_id="shared",
                kind="stop",
                at=self._at(4),
                reason="operator stopped new exposure",
            )
        )
        quote = AccountQuote(price=self._price("10"), at=self._at(4))
        journal.observe(quote)
        buy = AccountDecision(
            account_id="shared",
            instance_id="alpha",
            decision=OrderDecision(
                identity="illicit-protective-buy",
                at=self._at(5),
                intent=OrderIntent(
                    side="buy",
                    quantity=self._quantity("1"),
                    limit=self._price("10"),
                    time_in_force="ioc",
                ),
            ),
            quote=quote,
            maximum_fee=self._money("0"),
        )
        with journal._store.write() as transaction:
            with pytest.raises(ValueError, match="protective_admission_requires_direct_sell"):
                journal._admission.admit(transaction, buy, protective=True)

    def test_protective_bound_counts_unknown_sell_commitment(self, tmp_path: Path) -> None:
        """An uncertain existing sale retains all unfilled attributable inventory."""
        journal = self._funded(tmp_path / "unknown-reservation.sqlite3")
        quote = AccountQuote(price=self._price("10"), at=self._at(4))
        journal.observe(quote)
        committed = journal.admit(
            AccountDecision(
                account_id="shared",
                instance_id="alpha",
                decision=OrderDecision(
                    identity="pending-alpha-sale",
                    at=self._at(4),
                    intent=OrderIntent(
                        side="sell",
                        quantity=self._quantity("4"),
                        limit=self._price("9.90"),
                        time_in_force="gtc",
                    ),
                ),
                quote=quote,
                maximum_fee=self._money("0"),
            )
        )
        assert committed.status == "committed"
        journal.apply_event(
            OrderEvent(
                identity="unknown-alpha-sale",
                order_id=committed.orders[0].identity,
                at=self._at(5),
                kind="unknown",
            )
        )
        second = AccountDecision(
            account_id="shared",
            instance_id="alpha",
            decision=OrderDecision(
                identity="overcommitted-protective-sale",
                at=self._at(6),
                intent=OrderIntent(
                    side="sell",
                    quantity=self._quantity("2"),
                    limit=self._price("9.90"),
                    time_in_force="ioc",
                ),
            ),
            quote=quote,
            maximum_fee=self._money("0"),
        )
        with journal._store.write() as transaction:
            with pytest.raises(ValueError, match="reduction_exceeds_uncommitted_owned_inventory"):
                journal._admission.admit(transaction, second, protective=True)
