"""Exercise shared physical netting through the authoritative account journal."""

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
from paper_books import PaperBooks

# project library imports
from accounting import Fill
from accounting.accounts import AccountLedger, AccountSnapshot
from applications.execute import AccountExecutionApplication
from configuration import PaperExecutionScenario
from configuration.accounts import AccountConfiguration, InstrumentFeeRate, OpeningAccount
from execution import (
    AccountControl,
    AccountDecision,
    AccountExecutionRequest,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    EventKind,
    MarketTouch,
    NetFeeCorrection,
    OrderDecision,
    OrderEvent,
    PaperMarket,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
    PortfolioResidual,
)
from execution.account_state import AccountStateStore
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk.budgets import AccountLimit, BudgetPolicy, InstanceLimit
from risk.spot import SpotLimits
from serialization import DomainCodec
from strategies import ExposureIntent, OrderIntent, QuoteIntent, TargetIntent


class TestPortfolioAccounts:
    """Own fixed independent paper goldens for two strategy instances."""

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)

    @classmethod
    def _money(cls, amount: str) -> Money:
        """Build exact account-currency money."""
        return Money(value=Decimal(amount), currency=cls.currency)

    @classmethod
    def _quantity(cls, amount: str) -> Quantity:
        """Build exact base inventory."""
        return Quantity(value=Decimal(amount), dimension=cls.dimension)

    @classmethod
    def _price(cls, amount: str = "100") -> Price:
        """Build an exact spot quote."""
        return Price(value=Decimal(amount), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls, instances: tuple[str, ...] = ("alpha", "beta")) -> AccountConfiguration:
        """Give two strategy instances separate 9,000 caps under a 10,000 account."""
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("200"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
        )
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("50000"),)),),
            instruments=spot_limits,
            fee_rates=tuple(
                InstrumentFeeRate(
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal(0)
                )
                for limits in spot_limits
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.currency,
                firm_maximum=cls._money("10000"),
                accounts=(AccountLimit(account_id="shared", maximum=cls._money("10000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=name,
                        account_id="shared",
                        maximum=cls._money("9000"),
                        instruments=(cls.dimension.instrument_id,),
                    )
                    for name in instances
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_residual_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("9000"),
            ),
        )

    @classmethod
    def _opening(cls) -> AccountSnapshot:
        """Specify initial physical cash without consulting implementation state."""
        return AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(cls._money("50000"),),
            positions=(),
            fees=(cls._money("0"),),
            rebates=(cls._money("0"),),
            transfers=(cls._money("50000"),),
            fill_ids=(),
            posting_ids=("opening:USDT",),
        )

    @classmethod
    def _ready(cls, path: Path, instances: tuple[str, ...] = ("alpha", "beta")) -> AccountJournal:
        """Open and independently reconcile one paper account."""
        journal = AccountJournal(path, cls._config(instances))
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
    def _decision(
        cls,
        *,
        instance: str,
        identity: str,
        at: datetime,
        side: str = "buy",
        quantity: str = "2",
        maximum_fee: str = "1",
        bucket: str = "spot",
        price: str = "100",
    ) -> PortfolioDecision:
        """Create a tagged order at the quote with complete strategy and netting authority."""
        if side == "buy":
            intent = OrderIntent(
                side="buy",
                quantity=cls._quantity(quantity),
                limit=cls._price(price),
                time_in_force="gtc",
            )
        elif side == "sell":
            intent = OrderIntent(
                side="sell",
                quantity=cls._quantity(quantity),
                limit=cls._price(price),
                time_in_force="gtc",
            )
        else:
            raise ValueError("unsupported test side")
        return PortfolioDecision(
            request=AccountDecision(
                account_id="shared",
                instance_id=instance,
                decision=OrderDecision(identity=identity, at=at, intent=intent),
                quote=AccountQuote(price=cls._price(price), at=at),
                maximum_fee=cls._money(maximum_fee),
                checkpoint=f"{instance}:{identity}".encode(),
            ),
            context=PortfolioContext(
                portfolio_id="portfolio",
                strategy_id=instance,
                model_revision="model-1",
                config_revision="config-1",
                horizon="one-minute",
                reason="reference-order",
                venue="OKX",
                settlement="spot-immediate",
                risk_bucket=bucket,
                authority_scope="paper",
            ),
        )

    @classmethod
    def _fill(
        cls, identity: str, decision_at: datetime, at: datetime, quantity: str, fee: str
    ) -> Fill:
        """Construct one independent modeled physical execution fact."""
        return Fill(
            identity=identity,
            decision_at=decision_at,
            filled_at=at,
            quantity=cls._quantity(quantity),
            reference=cls._price(),
            effective=cls._price(),
            fee=cls._money(fee),
        )

    @classmethod
    def _holding(
        cls,
        path: Path,
        *,
        quantity: str = "85",
        deviation_bps: int = 1000,
        instances: tuple[str, ...] = ("alpha", "beta"),
    ) -> AccountJournal:
        """Leave alpha holding ``quantity`` bought at 100, by default 85 with 10% price checks.

        Marked at 110, 85 are worth 9,350: over alpha's 9,000 ceiling with no new
        order, while the account and firm ceilings (10,000 each) still hold.
        """
        config = cls._config(instances)
        config = replace(
            config, budgets=replace(config.budgets, max_price_deviation_bps=deviation_bps)
        )
        journal = AccountJournal(path, config)
        assert journal.reconcile(
            AccountObservation(
                identity="opening",
                at=cls.opening_at,
                snapshot=cls._opening(),
                open_orders=(),
            )
        )
        bought_at = cls.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=cls._price(), at=bought_at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="alpha-holding",
                at=bought_at + timedelta(microseconds=1),
                decisions=(
                    cls._decision(
                        instance="alpha",
                        identity="alpha-holding",
                        at=bought_at,
                        quantity=quantity,
                        maximum_fee="0",
                    ),
                ),
            )
        ).net_orders[0]
        filled_at = bought_at + timedelta(milliseconds=100)
        journal.apply_net_event(
            OrderEvent(
                identity="alpha-holding-receipt",
                order_id=parent.order.identity,
                at=filled_at,
                kind="fill",
                fill=cls._fill(
                    "alpha-holding-fill", parent.order.decision_at, filled_at, quantity, "0"
                ),
            )
        )
        return journal

    @classmethod
    def _cancelled_pair(cls, journal: AccountJournal, at: datetime) -> datetime:
        """Leave alpha and beta each a residual buy of 2 at 100 and return its cancellation.

        Gamma shares their physical order; its selective stop requests that order's
        cancellation, which leaves the other strategies' children to reissue. An
        operator account cancel would withdraw them instead.
        """
        journal.observe(AccountQuote(price=cls._price(), at=at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    cls._decision(instance=name, identity=f"{name}-buy", at=at, maximum_fee="0")
                    for name in ("alpha", "beta", "gamma")
                ),
            )
        ).net_orders[0]
        cancel_at = at + timedelta(seconds=1)
        journal.stop_instance("gamma", cancel_at)
        cancelled_at = cancel_at + timedelta(milliseconds=100)
        journal.apply_net_event(
            OrderEvent(
                identity="pair-cancelled",
                order_id=parent.order.identity,
                at=cancelled_at,
                kind="cancelled_on_request",
            )
        )
        return cancelled_at

    def test_partial_net_fill_retry_stop_and_other_strategy_reissue(self, tmp_path: Path) -> None:
        """Shared fills conserve cash and stopping alpha leaves beta's residual owned."""
        path = tmp_path / "portfolio.sqlite3"
        journal = self._ready(path)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=decision_at))
        batch = PortfolioBatch(
            identity="two-strategy-order",
            at=decision_at + timedelta(microseconds=1),
            decisions=(
                self._decision(instance="alpha", identity="alpha-buy", at=decision_at),
                self._decision(instance="beta", identity="beta-buy", at=decision_at),
            ),
        )
        committed = journal.coordinate(batch)
        assert committed.status == "committed"
        assert len(committed.children) == 2
        assert len(committed.net_orders) == 1
        assert committed.net_orders[0].order.intent.quantity == self._quantity("4")
        reopened = AccountJournal(path, self._config())
        assert reopened.coordinate(batch) == committed
        with pytest.raises(ValueError, match="different content"):
            reopened.coordinate(replace(batch, at=batch.at + timedelta(microseconds=1)))
        parent = committed.net_orders[0]
        first_at = batch.at + timedelta(seconds=1)
        first = OrderEvent(
            identity="physical-partial-receipt",
            order_id=parent.order.identity,
            at=first_at,
            kind="fill",
            fill=self._fill("physical-partial", parent.order.decision_at, first_at, "2", "0.02"),
        )
        partial = reopened.apply_net_event(first)
        assert partial.order.remaining == self._quantity("2")
        assert reopened.apply_net_event(first) == partial
        ledger = AccountLedger(reopened.accounts()[0].ledger)
        physical = ledger.snapshot()
        assert physical.cash == (self._money("49799.98"),)
        assert physical.positions == (self._quantity("2"),)
        assert physical.fees == (self._money("0.02"),)
        assert ledger.snapshot(instance_id="alpha").positions == (self._quantity("1"),)
        assert ledger.snapshot(instance_id="beta").positions == (self._quantity("1"),)
        assert ledger.snapshot(instance_id="alpha").fees == (self._money("0.01"),)
        assert ledger.snapshot(instance_id="beta").fees == (self._money("0.01"),)
        stopped = reopened.stop_instance("alpha", first_at + timedelta(seconds=1))
        assert len(stopped) == 1
        assert stopped[0].order.status == "cancel_requested"
        assert reopened.net_orders()[0].order.remaining == self._quantity("2")
        cancel_at = first_at + timedelta(seconds=2)
        reopened.apply_net_event(
            OrderEvent(
                identity="physical-cancel-confirmed",
                order_id=parent.order.identity,
                at=cancel_at,
                kind="cancelled_on_request",
            )
        )
        assert {child.instance_id: child.order.status for child in reopened.orders()} == {
            "alpha": "cancelled",
            "beta": "partial",
        }
        assert reopened.physical_open_orders("shared") == ()
        retry_at = cancel_at + timedelta(microseconds=1)
        reopened.observe(AccountQuote(price=self._price(), at=retry_at))
        before_orders = reopened.orders()
        with pytest.raises(ValueError, match="reissue_requires_current_reconciliation"):
            reopened.reissue_pending("shared", retry_at)
        assert reopened.orders() == before_orders
        assert len(reopened.net_orders()) == 1
        assert reopened.reconcile(
            AccountObservation(
                identity="after-cancel",
                at=cancel_at,
                snapshot=physical,
                open_orders=(),
            )
        )
        reopened.observe(
            AccountQuote(price=self._price(), at=cancel_at + timedelta(microseconds=1))
        )
        reissued = reopened.reissue_pending("shared", cancel_at + timedelta(microseconds=1))
        assert len(reissued) == 1
        assert reissued[0].order.intent.quantity == self._quantity("1")
        assert next(iter(reissued[0].allocations)).child_order_id == next(
            child.order.identity for child in reopened.orders() if child.instance_id == "beta"
        )
        beta_at = cancel_at + timedelta(seconds=1)
        reopened.apply_net_event(
            OrderEvent(
                identity="beta-reissue-fill-receipt",
                order_id=reissued[0].order.identity,
                at=beta_at,
                kind="fill",
                fill=self._fill(
                    "beta-reissue-fill", reissued[0].order.decision_at, beta_at, "1", "0.01"
                ),
            )
        )
        final = AccountLedger(reopened.accounts()[0].ledger)
        assert final.snapshot().cash == (self._money("49699.97"),)
        assert final.snapshot().positions == (self._quantity("3"),)
        assert final.snapshot().fees == (self._money("0.03"),)
        assert final.snapshot(instance_id="alpha").positions == (self._quantity("1"),)
        assert final.snapshot(instance_id="beta").positions == (self._quantity("2"),)
        assert final.snapshot(instance_id="beta").fees == (self._money("0.02"),)

    def test_each_paper_decision_replaces_its_instance_working_orders(self, tmp_path: Path) -> None:
        """Abstaining or deciding again cancels the instance's orders; a refused decision does not.

        A decision refused before it replaces anything, here on an unobserved quote,
        leaves the working order alone. One that replaces it waits for the
        cancellation, as research's plan does, and reports ``replacement_pending``.
        """
        journal = self._ready(tmp_path / "replace.sqlite3")
        first_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=first_at))
        first = journal.coordinate(
            PortfolioBatch(
                identity="alpha-first",
                at=first_at + timedelta(microseconds=1),
                decisions=(self._decision(instance="alpha", identity="alpha-1", at=first_at),),
            )
        )
        assert first.status == "committed" and len(first.net_orders) == 1
        parent = first.net_orders[0].order.identity
        second_at = first_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=second_at))
        refused = journal.coordinate(
            PortfolioBatch(
                identity="alpha-unobserved",
                at=second_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha", identity="alpha-unobserved", at=second_at, price="101"
                    ),
                ),
            )
        )
        assert (refused.status, refused.reason) == ("rejected", "unobserved_quote")
        assert not journal.net_orders()[0].order.cancel_requested
        abstain = self._decision(instance="alpha", identity="alpha-abstain", at=second_at)
        abstain = replace(
            abstain,
            request=replace(
                abstain.request, decision=replace(abstain.request.decision, intent=None)
            ),
        )
        abstained = journal.coordinate(
            PortfolioBatch(
                identity="alpha-abstains",
                at=second_at + timedelta(microseconds=2),
                decisions=(abstain,),
            )
        )
        assert (abstained.status, abstained.reason) == ("committed", "replacement_pending")
        (replaced,) = journal.net_orders()
        assert replaced.order.identity == parent and replaced.order.status == "cancel_requested"
        # The replaced child ends with its parent: it is never a residual to reissue,
        # so another instance's next decision needs no newer reconciliation.
        journal.apply_net_event(
            OrderEvent(
                identity="replaced-cancel-confirmed",
                order_id=parent,
                at=second_at + timedelta(microseconds=3),
                kind="cancelled_on_request",
            )
        )
        assert [item.order.status for item in journal.orders() if item.instance_id == "alpha"] == [
            "cancelled"
        ]
        other_at = second_at + timedelta(milliseconds=500)
        journal.observe(AccountQuote(price=self._price(), at=other_at))
        other = journal.coordinate(
            PortfolioBatch(
                identity="beta-after-replacement",
                at=other_at + timedelta(microseconds=1),
                decisions=(self._decision(instance="beta", identity="beta-1", at=other_at),),
            )
        )
        assert other.status == "committed", other.reason
        assert len(journal.net_orders()) == 2
        target_at = second_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=target_at))
        target = self._decision(instance="alpha", identity="alpha-target", at=target_at)
        target = replace(
            target,
            request=replace(
                target.request,
                decision=replace(
                    target.request.decision, intent=TargetIntent(quantity=self._quantity("1"))
                ),
                touch=MarketTouch(bid=self._price("99.99"), ask=self._price()),
            ),
        )
        held = journal.coordinate(
            PortfolioBatch(
                identity="alpha-target",
                at=target_at + timedelta(microseconds=1),
                decisions=(target,),
            )
        )
        assert held.status == "committed", held.reason

    @pytest.mark.parametrize(
        "ending",
        [("request_ack", "accepted", "cancelled"), ("request_ack", "rejected")],
        ids=["immediate-expiry", "post-only-rejection"],
    )
    def test_order_ended_on_its_own_terms_ends_its_child(
        self, tmp_path: Path, ending: tuple[EventKind, ...]
    ) -> None:
        """A parent ended without a cancel request leaves no residual awaiting reissue."""
        journal = self._ready(tmp_path / "immediate.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        decision = self._decision(instance="alpha", identity="alpha-ioc", at=at)
        intent = decision.request.decision.intent
        assert isinstance(intent, OrderIntent)
        decision = replace(
            decision,
            request=replace(
                decision.request,
                decision=replace(
                    decision.request.decision, intent=replace(intent, time_in_force="ioc")
                ),
            ),
        )
        sent = journal.coordinate(
            PortfolioBatch(
                identity="alpha-immediate", at=at + timedelta(microseconds=1), decisions=(decision,)
            )
        )
        assert sent.status == "committed" and len(sent.net_orders) == 1
        # Paper matching expires an unfilled IOC order, or rejects a crossing post-only one.
        for step, kind in enumerate(ending, start=2):
            journal.apply_net_event(
                OrderEvent(
                    identity=f"immediate-{kind}",
                    order_id=sent.net_orders[0].order.identity,
                    at=at + timedelta(microseconds=step),
                    kind=kind,
                )
            )
        assert [item.order.is_terminal for item in journal.orders()] == [True]
        later = at + timedelta(milliseconds=500)
        journal.observe(AccountQuote(price=self._price(), at=later))
        other = journal.coordinate(
            PortfolioBatch(
                identity="beta-after-immediate",
                at=later + timedelta(microseconds=1),
                decisions=(self._decision(instance="beta", identity="beta-1", at=later),),
            )
        )
        assert other.status == "committed", other.reason
        assert len(journal.net_orders()) == 2

    @classmethod
    def _delayed_scenario(cls) -> PaperExecutionScenario:
        """Model a 1 ms entry delay and a 5 ms cancel delay with no costs."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=1_000,
            cancel_delay_us=5_000,
            adverse=cls._price("0"),
            fee_rate=Decimal(0),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot matching",
        )

    @classmethod
    def _bound(cls, path: Path, instances: tuple[str, ...] = ("alpha", "beta")) -> AccountJournal:
        """Bind the delayed scenario, then independently reconcile opening cash."""
        journal = AccountJournal(path, cls._config(instances))
        journal.bind_paper_scenario("shared", cls._delayed_scenario())
        assert journal.reconcile(
            AccountObservation(
                identity="opening", at=cls.opening_at, snapshot=cls._opening(), open_orders=()
            )
        )
        return journal

    @classmethod
    def _book(cls, identity: str, at: datetime, ask: str) -> PaperMarket:
        """Offer ten units at ``ask`` and ten at a 99.50 bid."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price("99.50"),
            ask=cls._price(ask),
            bid_quantity=cls._quantity("10"),
            ask_quantity=cls._quantity("10"),
        )

    @classmethod
    def _lasting(
        cls,
        decision: PortfolioDecision,
        time_in_force: Literal["gtc", "ioc", "post-only"],
        *,
        portfolio: str = "portfolio",
    ) -> PortfolioDecision:
        """Give a decision's order another lifetime and its context another portfolio."""
        intent = decision.request.decision.intent
        assert isinstance(intent, OrderIntent)
        return replace(
            decision,
            request=replace(
                decision.request,
                decision=replace(
                    decision.request.decision, intent=replace(intent, time_in_force=time_in_force)
                ),
            ),
            context=replace(decision.context, portfolio_id=portfolio),
        )

    @classmethod
    def _abstention(cls, instance: str, identity: str, at: datetime) -> PortfolioDecision:
        """Decide no order, which under paper replacement cancels the instance's orders."""
        decision = cls._decision(instance=instance, identity=identity, at=at)
        return replace(
            decision,
            request=replace(
                decision.request, decision=replace(decision.request.decision, intent=None)
            ),
        )

    @staticmethod
    def _statuses(journal: AccountJournal) -> dict[str, str]:
        """Map each instance to its only strategy order's status."""
        return {item.instance_id: item.order.status for item in journal.orders()}

    @classmethod
    def _target(
        cls, instance: str, identity: str, at: datetime, quantity: str
    ) -> PortfolioDecision:
        """Ask for an absolute holding, decided on a 99.50 bid and 100 ask."""
        decision = cls._decision(instance=instance, identity=identity, at=at)
        return replace(
            decision,
            request=replace(
                decision.request,
                decision=replace(
                    decision.request.decision, intent=TargetIntent(quantity=cls._quantity(quantity))
                ),
                touch=MarketTouch(bid=cls._price("99.50"), ask=cls._price()),
            ),
        )

    @staticmethod
    def _outcomes(journal: AccountJournal, since: datetime) -> list[tuple[str, timedelta, str]]:
        """List each saved decision's instance, time after ``since`` and reason, in order."""
        return [
            (item.instance_id, item.decided_at - since, item.reason)
            for item in journal.result_snapshot(
                AccountExecutionRequest(action="inspect", projection="decisions")
            ).decision_outcomes
        ]

    @staticmethod
    def _physical_fills(journal: AccountJournal) -> list[tuple[datetime, Decimal]]:
        """List each modeled physical fill's market time and signed quantity, in order."""
        return [
            (event.fill.filled_at, event.fill.quantity.value)
            for trace in journal.iter_paper_traces("shared")
            for event in trace.physical_events
            if event.fill is not None
        ]

    @pytest.mark.parametrize("reopened", (False, True), ids=("live", "reopened"))
    def test_a_target_replacing_a_partly_filled_bid_buys_only_what_is_missing(
        self, tmp_path: Path, reopened: bool
    ) -> None:
        """The replacement is sized after the replaced bid's last fill, as research's is.

        Entry takes 1 ms and cancellation 5 ms. Alpha's ``gtc`` bid for two at 100, decided at 1 s,
        arrives at +1 ms and rests below the +2 ms book's 101 ask. Its +3 ms target of two requests
        the bid's cancellation, effective from +8 ms, and waits. The +4 ms book offers one unit at
        100, which fills half the bid inside that window. The +8 ms book confirms the cancellation,
        so the target arrives at +9 ms, one entry delay later; the +9 ms book is known to it, and
        the +10 ms book's command admits it against the one unit then held: one unit at the +9 ms
        ask of 100, which the +10 ms book fills. Holding 2, not 3. Reopening the journal while the
        target waits changes nothing, and exact retries of the deferring batch and of the sending
        book write nothing.
        """
        scenario = self._delayed_scenario()
        path = tmp_path / "partial.sqlite3"
        journal = self._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        bid = journal.coordinate(
            PortfolioBatch(
                identity="bid",
                at=at + timedelta(microseconds=1),
                decisions=(self._decision(instance="alpha", identity="alpha-bid", at=at),),
            )
        )
        assert bid.reason == "arrival_pending"
        PaperBooks.apply(
            journal, "shared", self._book("above", at + timedelta(milliseconds=2), "101"), scenario
        )
        target_at = at + timedelta(milliseconds=3)
        journal.observe(AccountQuote(price=self._price(), at=target_at))
        batch = PortfolioBatch(
            identity="target",
            at=target_at + timedelta(microseconds=1),
            decisions=(self._target("alpha", "alpha-target", target_at, "2"),),
        )
        pending = journal.coordinate(batch)
        assert (pending.status, pending.reason, pending.children) == (
            "committed",
            "replacement_pending",
            (),
        )
        if reopened:
            journal.close()
            journal = AccountJournal(path, self._config())
        one = replace(
            self._book("one-at-limit", at + timedelta(milliseconds=4), "100"),
            ask_quantity=self._quantity("1"),
        )
        PaperBooks.apply(journal, "shared", one, scenario)
        books = {
            name: self._book(name, at + timedelta(milliseconds=after), "100")
            for name, after in (("cancels", 8), ("sends", 9), ("fills", 10))
        }
        for book in books.values():
            PaperBooks.apply(journal, "shared", book, scenario)

        assert self._physical_fills(journal) == [
            (at + timedelta(milliseconds=4), Decimal(1)),
            (at + timedelta(milliseconds=10), Decimal(1)),
        ]
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot(instance_id="alpha").positions == (self._quantity("2"),)
        outcomes = self._outcomes(journal, at)
        assert outcomes == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(milliseconds=1), "reserved"),
            ("alpha", timedelta(milliseconds=3), "replacement_pending"),
            ("alpha", timedelta(milliseconds=9), "reserved"),
        ]
        (sent,) = (item.order for item in journal.orders() if item.order.decision_at > target_at)
        assert sent.intent.quantity == self._quantity("1")
        assert journal.coordinate(batch) == pending
        before = PaperBooks.apply(journal, "shared", books["sends"], scenario)
        assert PaperBooks.apply(journal, "shared", books["sends"], scenario) == before
        assert self._outcomes(journal, at) == outcomes

    @classmethod
    def _touch(cls, identity: str, at: datetime, bid: str, ask: str) -> PaperMarket:
        """Offer ten units on each side of an authored touch."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price(bid),
            ask=cls._price(ask),
            bid_quantity=cls._quantity("10"),
            ask_quantity=cls._quantity("10"),
        )

    def _replaced_at_three(
        self, journal: AccountJournal, at: datetime, decision: PortfolioDecision
    ) -> None:
        """Rest alpha's two-unit bid at 99.50 from 1 s, then replace it at +3 ms."""
        journal.observe(AccountQuote(price=self._price(), at=at))
        journal.coordinate(
            PortfolioBatch(
                identity="alpha-rests",
                at=at + timedelta(microseconds=1),
                decisions=(self._below("alpha", at, "2"),),
            )
        )
        decided = decision.request.decision.at
        journal.observe(AccountQuote(price=self._price(), at=decided))
        pending = journal.coordinate(
            PortfolioBatch(
                identity="alpha-replaces",
                at=decided + timedelta(microseconds=1),
                decisions=(decision,),
            )
        )
        assert pending.reason == "replacement_pending"

    @pytest.mark.parametrize(
        ("kind", "quantity"),
        (("target", "2"), ("exposure", "2")),
        ids=("target", "exposure"),
    )
    def test_a_replacement_is_priced_and_sized_on_the_book_known_at_its_arrival(
        self, tmp_path: Path, kind: str, quantity: str
    ) -> None:
        """A quote change inside the entry delay prices and sizes the replacement.

        Entry takes 1 ms and cancellation 5 ms. Alpha's +3 ms decision replaces its
        resting bid; the +8 ms book (99.50/100) ends that bid, so the decision arrives
        at +9 ms. The +8.5 ms book moves the touch to 99.70/100.20. At arrival a target
        of two buys two through the 100.20 ask, and an exposure of 299.50 is two lots
        at the 99.95 midpoint, not three at the +8 ms midpoint of 99.75. The +10 ms
        book's command admits it and that book fills it at 100.20.
        """
        scenario = self._delayed_scenario()
        journal = self._bound(tmp_path / f"arrival-{kind}.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        decided = at + timedelta(milliseconds=3)
        decision = self._target("alpha", "alpha-replaces", decided, "2")
        if kind == "exposure":
            decision = replace(
                decision,
                request=replace(
                    decision.request,
                    decision=replace(
                        decision.request.decision,
                        intent=ExposureIntent(exposure=self._money("299.50")),
                    ),
                ),
            )
        self._replaced_at_three(journal, at, decision)
        for name, after, bid, ask in (
            ("cancels", 8_000, "99.50", "100"),
            ("moves", 8_500, "99.70", "100.20"),
            ("admits", 10_000, "99.70", "100.20"),
        ):
            PaperBooks.apply(
                journal,
                "shared",
                self._touch(name, at + timedelta(microseconds=after), bid, ask),
                scenario,
            )

        (sent,) = (item.order for item in journal.orders() if item.order.decision_at > decided)
        assert (sent.intent.quantity, sent.intent.limit) == (
            self._quantity(quantity),
            self._price("100.20"),
        )
        assert self._outcomes(journal, at)[-1] == (
            "alpha",
            timedelta(milliseconds=9),
            "reserved",
        )
        assert self._physical_fills(journal) == [
            (at + timedelta(milliseconds=10), Decimal(quantity))
        ]

    @pytest.mark.parametrize(
        ("beta_us", "expected", "admitted"),
        (
            (
                7_500,
                [
                    ("beta", 7_500, "arrival_pending"),
                    ("beta", 8_500, "reserved"),
                    ("alpha", 9_000, "account_limit"),
                ],
                ["beta"],
            ),
            (
                9_000,
                [
                    ("alpha", 9_000, "reserved"),
                    ("beta", 9_000, "arrival_pending"),
                    ("beta", 10_000, "account_limit"),
                ],
                ["alpha"],
            ),
        ),
        ids=("beta-arrives-first", "beta-decides-at-alpha-arrival"),
    )
    def test_a_replacement_and_another_strategy_share_capacity_in_arrival_order(
        self,
        tmp_path: Path,
        beta_us: int,
        expected: list[tuple[str, int, str]],
        admitted: list[str],
    ) -> None:
        """Plans reserve in arrival order, and an arrival precedes a same-time decision.

        Entry takes 1 ms and cancellation 5 ms; the account may commit 10,000. Alpha's
        +3 ms target of twelve replaces its bid, which the +8 ms book ends, so it arrives
        at +9 ms needing twelve at the 100.50 ask (1,206). Beta asks for 89 at 100.50
        (8,944.50), arriving one entry delay after its decision; the two exceed 10,000.
        Decided at +7.5 ms, beta arrives at +8.5 ms and reserves first, and alpha's
        arrival is refused on the account limit. Decided at exactly +9 ms, beta's command
        first admits alpha's arrival due then, as research processes an arrival before a
        new decision at the same timestamp; beta arrives at +10 ms, meets alpha's still
        unfilled reservation, with no book in between, and is refused. Reopening the
        journal and retrying beta's batch change nothing.
        """
        scenario = self._delayed_scenario()
        path = tmp_path / "funding.sqlite3"
        journal = self._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        self._replaced_at_three(
            journal,
            at,
            self._target("alpha", "alpha-replaces", at + timedelta(milliseconds=3), "12"),
        )
        cancels = self._touch("cancels", at + timedelta(milliseconds=8), "99.50", "100.50")
        if beta_us > 8_000:
            PaperBooks.apply(journal, "shared", cancels, scenario)
        journal.close()
        journal = AccountJournal(path, self._config())
        beta_at = at + timedelta(microseconds=beta_us)
        journal.observe(AccountQuote(price=self._price("100.50"), at=beta_at))
        batch = PortfolioBatch(
            identity="beta-takes-capacity",
            at=beta_at + timedelta(microseconds=1),
            decisions=(
                self._decision(
                    instance="beta",
                    identity="beta-buy",
                    at=beta_at,
                    quantity="89",
                    price="100.50",
                ),
            ),
        )
        beta = journal.coordinate(batch)
        assert journal.coordinate(batch) == beta
        assert beta.reason == "arrival_pending"
        if beta_us < 8_000:
            PaperBooks.apply(journal, "shared", cancels, scenario)
        # No book follows, so alpha's admitted buy still holds its reservation when beta
        # arrives; time alone resolves both arrivals.
        journal.advance_paper(at + timedelta(milliseconds=11))

        assert self._outcomes(journal, at)[3:] == [
            (instance, timedelta(microseconds=after), reason)
            for instance, after, reason in expected
        ]
        assert [
            item.instance_id
            for item in journal.orders()
            if item.order.decision_at > at + timedelta(milliseconds=8)
        ] == admitted

    @pytest.mark.parametrize(
        ("decided_us", "result"),
        (
            (9_500, ("rejected", "decision_precedes_account_state")),
            (10_000, ("committed", "arrival_pending")),
        ),
        ids=("before-observed-acceptance", "after-observed-acceptance"),
    )
    def test_a_replacement_orders_observed_events_bound_later_decisions(
        self, tmp_path: Path, decided_us: int, result: tuple[str, str]
    ) -> None:
        """Only an arrival's coordination clock is synthetic; its observed events are not.

        Entry takes 1 ms and cancellation 5 ms. Alpha's +3 ms decision to bid again at
        99.50 replaces its resting bid, which the +8 ms book ends, so it arrives at +9
        ms. The +10 ms book, asking 100.50, is matched after that arrival: it
        acknowledges and accepts the new bid, which keeps resting, both observed at +10
        ms. A beta decision dated +9.5 ms therefore precedes known account state and is
        refused at once; one dated +10 ms is accepted and waits for its arrival.
        Reopening and retrying change nothing.
        """
        scenario = self._delayed_scenario()
        path = tmp_path / "observed.sqlite3"
        journal = self._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        rebid = self._below("alpha", at + timedelta(milliseconds=3), "1")
        rebid = replace(
            rebid,
            request=replace(
                rebid.request,
                decision=replace(rebid.request.decision, identity="alpha-rebid"),
            ),
        )
        self._replaced_at_three(journal, at, rebid)
        for name, after, ask in (("cancels", 8, "100"), ("accepts", 10, "100.50")):
            PaperBooks.apply(
                journal,
                "shared",
                self._touch(name, at + timedelta(milliseconds=after), "99.50", ask),
                scenario,
            )
        journal.close()
        journal = AccountJournal(path, self._config())
        decided = at + timedelta(microseconds=decided_us)
        request = self._decision(
            instance="beta", identity="beta-late", at=decided, quantity="1", price="100.50"
        )
        request = replace(
            request,
            request=replace(
                request.request,
                quote=AccountQuote(price=self._price("100.50"), at=at + timedelta(milliseconds=10)),
            ),
        )
        batch = PortfolioBatch(
            identity="beta-late", at=decided + timedelta(microseconds=1), decisions=(request,)
        )
        refused = journal.coordinate(batch)
        assert journal.coordinate(batch) == refused

        assert self._outcomes(journal, at)[3] == ("alpha", timedelta(milliseconds=9), "reserved")
        (accepted,) = (
            parent.order
            for parent in journal.net_orders()
            if parent.order.decision_at == at + timedelta(microseconds=9_001)
        )
        assert accepted.accepted and not accepted.is_terminal
        assert (refused.status, refused.reason) == result

    def test_every_arrival_at_a_time_precedes_a_new_decision_at_that_time(
        self, tmp_path: Path
    ) -> None:
        """Two replacements arriving together both reserve before a same-time decision.

        Entry takes 1 ms and cancellation 5 ms; the account may commit 10,000. Alpha and
        beta each rest a bid, and at +3 ms each targets forty units, replacing it. The
        +8 ms book ends both bids, so both arrive at +9 ms and reserve forty at the 100
        ask (4,000 each), alpha first, in decision order. Admitting alpha's arrival
        coordinates its order at +9.001 ms, which does not postpone beta's. Gamma's
        decision for thirty (3,000) at exactly +9 ms follows both arrivals; with no book
        in between, it arrives at +10 ms against both reservations and is refused on the
        account limit. Reopening and retrying gamma's batch change nothing.
        """
        instances = ("alpha", "beta", "gamma")
        scenario = self._delayed_scenario()
        path = tmp_path / "together.sqlite3"
        journal = self._bound(path, instances)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        journal.coordinate(
            PortfolioBatch(
                identity="both-rest",
                at=at + timedelta(microseconds=1),
                decisions=(self._below("alpha", at, "2"), self._below("beta", at, "2")),
            )
        )
        decided = at + timedelta(milliseconds=3)
        journal.observe(AccountQuote(price=self._price(), at=decided))
        pending = journal.coordinate(
            PortfolioBatch(
                identity="both-replace",
                at=decided + timedelta(microseconds=1),
                decisions=(
                    self._target("alpha", "alpha-target", decided, "40"),
                    self._target("beta", "beta-target", decided, "40"),
                ),
            )
        )
        assert pending.reason == "replacement_pending"
        PaperBooks.apply(
            journal,
            "shared",
            self._touch("cancels", at + timedelta(milliseconds=8), "99.50", "100"),
            scenario,
        )
        journal.close()
        journal = AccountJournal(path, self._config(instances))
        arrival = at + timedelta(milliseconds=9)
        journal.observe(AccountQuote(price=self._price(), at=arrival))
        batch = PortfolioBatch(
            identity="gamma-at-arrival",
            at=arrival + timedelta(microseconds=1),
            decisions=(
                self._decision(instance="gamma", identity="gamma-buy", at=arrival, quantity="30"),
            ),
        )
        gamma = journal.coordinate(batch)
        assert journal.coordinate(batch) == gamma
        journal.advance_paper(at + timedelta(milliseconds=11))

        assert self._outcomes(journal, at)[6:] == [
            ("alpha", timedelta(milliseconds=9), "reserved"),
            ("beta", timedelta(milliseconds=9), "reserved"),
            ("gamma", timedelta(milliseconds=9), "arrival_pending"),
            ("gamma", timedelta(milliseconds=10), "account_limit"),
        ]
        assert (gamma.status, gamma.reason) == ("committed", "arrival_pending")

    def _quiet_target(self, path: Path) -> tuple[AccountJournal, datetime]:
        """Rest alpha's bid below a +2 ms book, then target two at +3 ms with no later book."""
        journal = self._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        journal.coordinate(
            PortfolioBatch(
                identity="alpha-rests",
                at=at + timedelta(microseconds=1),
                decisions=(self._below("alpha", at, "2"),),
            )
        )
        PaperBooks.apply(
            journal,
            "shared",
            self._touch("above", at + timedelta(milliseconds=2), "99.50", "101"),
            self._delayed_scenario(),
        )
        decided = at + timedelta(milliseconds=3)
        journal.observe(AccountQuote(price=self._price("101"), at=decided))
        target = self._target("alpha", "alpha-target", decided, "2")
        target = replace(
            target,
            request=replace(
                target.request,
                quote=AccountQuote(price=self._price("101"), at=decided),
                touch=MarketTouch(bid=self._price("99.50"), ask=self._price("101")),
            ),
        )
        pending = journal.coordinate(
            PortfolioBatch(
                identity="alpha-target",
                at=decided + timedelta(microseconds=1),
                decisions=(target,),
            )
        )
        assert pending.reason == "replacement_pending"
        return journal, at

    @pytest.mark.parametrize(
        ("crossing_us", "first", "outcome"),
        (
            (None, None, ("alpha", 9_000, "reserved")),
            (7_999, 7_999, ("alpha", 9_000, "target_matched")),
            (8_000, None, ("alpha", 9_000, "reserved")),
        ),
        ids=("quiet", "fills-before-deadline", "book-at-deadline"),
    )
    def test_a_quiet_market_ends_a_cancellation_and_admits_its_replacement_on_time(
        self,
        tmp_path: Path,
        crossing_us: int | None,
        first: int | None,
        outcome: tuple[str, int, str],
    ) -> None:
        """Requested cancellations end at their deadline whether or not a book arrives.

        Entry takes 1 ms and cancellation 5 ms. Alpha's bid for two rests at 99.50 below
        the +2 ms book's 101 ask; its +3 ms target of two requests the bid's
        cancellation, effective at +8 ms, and arrives at +9 ms. With no book after +2 ms,
        advancing the account to +9.5 ms ends the bid at +8 ms, releasing its
        reservation, and admits the target at +9 ms through the 101 ask of the +2 ms
        book, still fresh. A book offering ten at 99.50 just before +8 ms fills the bid
        instead, so the target then needs nothing; one at exactly +8 ms ends the bid
        before it can fill. Afterwards a +10 ms book at 99.50 cannot fill the cancelled
        bid, fills the replacement, the first book after its arrival, and does not move
        the arrival. Reopening and retrying the advance and that book change nothing.
        """
        scenario = self._delayed_scenario()
        path = tmp_path / "quiet.sqlite3"
        journal, at = self._quiet_target(path)
        if crossing_us is not None:
            PaperBooks.apply(
                journal,
                "shared",
                self._touch("crossing", at + timedelta(microseconds=crossing_us), "99", "99.50"),
                scenario,
            )
        journal.advance_paper(at + timedelta(microseconds=9_500))
        (bid,) = (
            item.order
            for item in journal.orders()
            if item.order.decision_at == at + timedelta(milliseconds=1)
        )
        assert bid.status == ("filled" if first is not None else "cancelled")
        assert self._outcomes(journal, at)[-1] == (
            outcome[0],
            timedelta(microseconds=outcome[1]),
            outcome[2],
        )
        journal.close()
        journal = AccountJournal(path, self._config())
        journal.advance_paper(at + timedelta(microseconds=9_500))
        later = self._touch("later", at + timedelta(milliseconds=10), "99", "99.50")
        trace = PaperBooks.apply(journal, "shared", later, scenario)
        outcomes = self._outcomes(journal, at)
        assert PaperBooks.apply(journal, "shared", later, scenario) == trace
        journal.advance_paper(at + timedelta(milliseconds=11))
        assert self._outcomes(journal, at) == outcomes

        assert outcomes[-1] == (outcome[0], timedelta(microseconds=outcome[1]), outcome[2])
        expected = [] if first is None else [(at + timedelta(microseconds=first), Decimal(2))]
        if first is None:
            expected.append((at + timedelta(milliseconds=10), Decimal(2)))
        assert self._physical_fills(journal) == expected
        cancellations = [
            saved.event.at
            for saved in AccountStateStore(path, self._config(), DomainCodec()).read().net_events
            if saved.event.kind == "cancelled_on_request"
        ]
        assert cancellations == ([] if first is not None else [at + timedelta(milliseconds=8)])

    def test_a_quiet_market_does_not_revive_withdrawn_intent_or_end_unknown_orders(
        self, tmp_path: Path
    ) -> None:
        """Elapsed time ends known requested orders only; a stop's withdrawal stays final.

        Alpha's +3 ms target waits for its bid's cancellation. Beta's +4 ms bid arrives
        at +5 ms and its outcome then becomes unknown. Stopping both at +6 ms withdraws
        alpha's target before its +9 ms arrival. Advancing through the quiet interval
        ends alpha's bid at +8 ms and admits nothing, across a reopen and a repeated
        advance. Beta's bid keeps its unknown outcome and reservation however much time
        passes.
        """
        path = tmp_path / "quiet-controls.sqlite3"
        journal, at = self._quiet_target(path)
        beta_at = at + timedelta(milliseconds=4)
        journal.observe(AccountQuote(price=self._price(), at=beta_at))
        beta = journal.coordinate(
            PortfolioBatch(
                identity="beta-rests",
                at=beta_at + timedelta(microseconds=1),
                decisions=(self._below("beta", beta_at, "1"),),
            )
        )
        assert beta.reason == "arrival_pending"
        journal.advance_paper(at + timedelta(microseconds=5_500))
        (beta_parent,) = (
            parent for parent in journal.net_orders() if parent.order.decision_at > beta_at
        )
        journal.apply_net_event(
            OrderEvent(
                identity="beta-unknown",
                order_id=beta_parent.order.identity,
                at=at + timedelta(microseconds=5_500),
                kind="unknown",
            )
        )
        journal.stop_instance("alpha", at + timedelta(milliseconds=6))
        journal.stop_instance("beta", at + timedelta(milliseconds=6))
        journal.advance_paper(at + timedelta(milliseconds=20))
        journal.close()
        journal = AccountJournal(path, self._config())
        journal.advance_paper(at + timedelta(milliseconds=30))

        assert self._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(milliseconds=1), "reserved"),
            ("alpha", timedelta(milliseconds=3), "replacement_pending"),
            ("beta", timedelta(milliseconds=4), "arrival_pending"),
            ("beta", timedelta(milliseconds=5), "reserved"),
            ("alpha", timedelta(milliseconds=6), "withdrawn_by_instance_stop"),
        ]
        statuses = {item.instance_id: item.order.status for item in journal.orders()}
        assert statuses["alpha"] == "cancelled"
        (unknown,) = journal.net_orders()[-1:]
        assert (unknown.order.status, unknown.order.cancel_requested) == ("unknown", True)

    def _fresh(
        self, path: Path, scenario: PaperExecutionScenario | None = None
    ) -> tuple[AccountJournal, datetime]:
        """Open an account bound to ``scenario`` (by default 1 ms entry, 5 ms cancel)."""
        journal = AccountJournal(path, self._config())
        journal.bind_paper_scenario("shared", scenario or self._delayed_scenario())
        assert journal.reconcile(
            AccountObservation(
                identity="opening", at=self.opening_at, snapshot=self._opening(), open_orders=()
            )
        )
        return journal, self.opening_at + timedelta(seconds=1)

    @pytest.mark.parametrize(
        ("kind", "path"),
        (("target", "coordinated"), ("target", "direct"), ("exposure", "coordinated")),
    )
    def test_a_decision_replacing_nothing_is_sized_on_the_book_known_at_its_arrival(
        self, tmp_path: Path, kind: str, path: str
    ) -> None:
        """With nothing outstanding the plan arrives an entry delay later and is sized then.

        Entry takes 1 ms; there is no cancellation to wait for. Alpha decides at 1 s on a
        99.50/100 touch and the decision waits as ``arrival_pending``. The +0.5 ms book
        moves the touch to 99.70/100.20, so at the +1 ms arrival a target of two buys two
        through 100.20 and an exposure of 299.50 is two lots at the 99.95 midpoint, not
        three at 99.75. The strategy is not run again. The +2 ms book's command admits
        it, by the coordinated or the direct path, and that book fills it at 100.20.
        """
        scenario = self._delayed_scenario()
        journal, at = self._fresh(tmp_path / f"{kind}-{path}.sqlite3")
        journal.observe(AccountQuote(price=self._price(), at=at))
        decision = self._target("alpha", "alpha-target", at, "2")
        if kind == "exposure":
            decision = replace(
                decision,
                request=replace(
                    decision.request,
                    decision=replace(
                        decision.request.decision,
                        intent=ExposureIntent(exposure=self._money("299.50")),
                    ),
                ),
            )
        if path == "direct":
            pending = journal.admit(decision.request).reason
        else:
            pending = journal.coordinate(
                PortfolioBatch(
                    identity="alpha-target",
                    at=at + timedelta(microseconds=1),
                    decisions=(decision,),
                )
            ).reason
        assert pending == "arrival_pending"
        assert journal.orders() == ()
        for name, after in (("moves", 500), ("admits", 2_000)):
            PaperBooks.apply(
                journal,
                "shared",
                self._touch(name, at + timedelta(microseconds=after), "99.70", "100.20"),
                scenario,
            )

        (sent,) = (item.order for item in journal.orders())
        assert (sent.decision_at, sent.intent.quantity, sent.intent.limit) == (
            at + timedelta(milliseconds=1),
            self._quantity("2"),
            self._price("100.20"),
        )
        assert self._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(milliseconds=1), "reserved"),
        ]
        assert self._physical_fills(journal) == [(at + timedelta(milliseconds=2), Decimal(2))]

    def test_a_plan_replacing_nothing_meets_capacity_reserved_by_an_earlier_arrival(
        self, tmp_path: Path
    ) -> None:
        """Plans reserve at their arrivals, in arrival order, not at their decisions.

        The account may commit 10,000. Beta decides 0.5 ms before alpha for 89 at 100.50
        (8,944.50) and alpha decides at 1 s for twelve (1,206); each arrives 1 ms later.
        With no book in between, beta reserves first at +0.5 ms and alpha's arrival at
        +1 ms is refused on the account limit. Reopening and retrying change nothing.
        """
        path = tmp_path / "earlier-arrival.sqlite3"
        journal, at = self._fresh(path)
        beta_at = at - timedelta(microseconds=500)
        for instance, decided, quantity in (("beta", beta_at, "89"), ("alpha", at, "12")):
            journal.observe(AccountQuote(price=self._price("100.50"), at=decided))
            batch = PortfolioBatch(
                identity=f"{instance}-buys",
                at=decided + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance=instance,
                        identity=f"{instance}-buy",
                        at=decided,
                        quantity=quantity,
                        price="100.50",
                    ),
                ),
            )
            assert journal.coordinate(batch).reason == "arrival_pending"
        journal.close()
        journal = AccountJournal(path, self._config())
        journal.advance_paper(at + timedelta(milliseconds=2))
        assert journal.coordinate(batch).reason == "arrival_pending"
        journal.advance_paper(at + timedelta(milliseconds=2))

        assert self._outcomes(journal, at) == [
            ("beta", timedelta(microseconds=-500), "arrival_pending"),
            ("alpha", timedelta(0), "arrival_pending"),
            ("beta", timedelta(microseconds=500), "reserved"),
            ("alpha", timedelta(milliseconds=1), "account_limit"),
        ]

    @pytest.mark.parametrize("intervention", ("decision", "stop"))
    def test_an_intervention_before_arrival_withdraws_a_plan_replacing_nothing(
        self, tmp_path: Path, intervention: str
    ) -> None:
        """A newer decision or a stop before arrival withdraws the waiting plan for good.

        Entry takes 5 ms and cancellation 1 ms. Alpha's 1 s bid would arrive at +5 ms.
        A newer +2 ms decision for a 99.40 bid requests cancellation from +3 ms, before
        that arrival, so the first plan is withdrawn at +5 ms and the newer one, released
        at +3 ms, arrives at +8 ms. A stop at +2 ms instead withdraws the first plan at
        once. Reopening, retrying and advancing time revive neither.
        """
        scenario = replace(self._delayed_scenario(), entry_delay_us=5_000, cancel_delay_us=1_000)
        path = tmp_path / f"{intervention}.sqlite3"
        journal, at = self._fresh(path, scenario)
        journal.observe(AccountQuote(price=self._price(), at=at))
        first = PortfolioBatch(
            identity="alpha-bid",
            at=at + timedelta(microseconds=1),
            decisions=(self._below("alpha", at, "1"),),
        )
        assert journal.coordinate(first).reason == "arrival_pending"
        later = at + timedelta(milliseconds=2)
        if intervention == "stop":
            journal.stop_instance("alpha", later)
        else:
            journal.observe(AccountQuote(price=self._price(), at=later))
            newer = self._below("alpha", later, "1")
            intent = newer.request.decision.intent
            assert isinstance(intent, OrderIntent)
            newer = replace(
                newer,
                request=replace(
                    newer.request,
                    decision=replace(
                        newer.request.decision,
                        identity="alpha-rebid",
                        intent=replace(intent, limit=self._price("99.40")),
                    ),
                ),
            )
            assert (
                journal.coordinate(
                    PortfolioBatch(
                        identity="alpha-rebid",
                        at=later + timedelta(microseconds=1),
                        decisions=(newer,),
                    )
                ).reason
                == "replacement_pending"
            )
        journal.close()
        journal = AccountJournal(path, self._config())
        journal.advance_paper(at + timedelta(milliseconds=20))
        assert journal.coordinate(first).reason == "arrival_pending"
        journal.advance_paper(at + timedelta(milliseconds=30))

        expected = (
            [
                ("alpha", timedelta(0), "arrival_pending"),
                ("alpha", timedelta(milliseconds=2), "withdrawn_by_instance_stop"),
            ]
            if intervention == "stop"
            else [
                ("alpha", timedelta(0), "arrival_pending"),
                ("alpha", timedelta(milliseconds=2), "replacement_pending"),
                ("alpha", timedelta(milliseconds=5), "replaced_before_arrival"),
                ("alpha", timedelta(milliseconds=8), "reserved"),
            ]
        )
        assert self._outcomes(journal, at) == expected
        assert [item.order.intent.limit for item in journal.orders()] == (
            [] if intervention == "stop" else [self._price("99.40")]
        )

    @pytest.mark.parametrize(
        ("entry_us", "advance_ms", "outcomes"),
        (
            (1_000, 2, [(0, "arrival_pending"), (1, "reserved")]),
            (1_500_000, 2_000, [(0, "arrival_pending"), (1_500, "no_fresh_book_at_arrival")]),
            (0, None, [(0, "reserved")]),
        ),
        ids=("quiet-arrival", "stale-at-arrival", "no-entry-delay"),
    )
    def test_a_plan_replacing_nothing_arrives_on_time_in_a_quiet_market(
        self,
        tmp_path: Path,
        entry_us: int,
        advance_ms: int | None,
        outcomes: list[tuple[int, str]],
    ) -> None:
        """Time alone resolves an arrival on the facts known then; no delay means no wait.

        Quotes stay usable for 1 s. With a 1 ms entry delay and no book, advancing the
        account admits the 1 s bid at +1 ms on its own fresh decision quote. With a 1.5 s
        entry delay the decision's quote is stale by its arrival, which records
        ``no_fresh_book_at_arrival`` and places nothing. With no entry delay the decision
        is admitted at once, as before.
        """
        scenario = replace(self._delayed_scenario(), entry_delay_us=entry_us)
        journal, at = self._fresh(tmp_path / f"quiet-{entry_us}.sqlite3", scenario)
        journal.observe(AccountQuote(price=self._price(), at=at))
        journal.coordinate(
            PortfolioBatch(
                identity="alpha-bid",
                at=at + timedelta(microseconds=1),
                decisions=(self._below("alpha", at, "1"),),
            )
        )
        if advance_ms is not None:
            journal.advance_paper(at + timedelta(milliseconds=advance_ms))

        assert self._outcomes(journal, at) == [
            ("alpha", timedelta(milliseconds=after), reason) for after, reason in outcomes
        ]
        assert len(journal.orders()) == (0 if "no_fresh" in outcomes[-1][1] else 1)

    def test_a_direct_arrival_does_not_overtake_an_earlier_coordinated_one(
        self, tmp_path: Path
    ) -> None:
        """Plans arriving together reserve in decision order, whatever their admission path.

        The account may commit 10,000. Alpha's coordinated decision and then beta's direct
        decision, both at 1 s, each ask for 60 at 100 with no fee reserve, and both arrive
        at +1 ms. Alpha's, decided first, reserves 6,000; beta's would take the account to
        12,000 and is refused on the account limit. Reopening and retrying both decisions
        change nothing.
        """
        path = tmp_path / "priority.sqlite3"
        journal, at = self._fresh(path)
        journal.observe(AccountQuote(price=self._price(), at=at))
        batch = PortfolioBatch(
            identity="alpha-coordinated",
            at=at + timedelta(microseconds=1),
            decisions=(
                self._decision(
                    instance="alpha", identity="alpha-buy", at=at, quantity="60", maximum_fee="0"
                ),
            ),
        )
        direct = self._decision(
            instance="beta", identity="beta-buy", at=at, quantity="60", maximum_fee="0"
        ).request
        assert journal.coordinate(batch).reason == "arrival_pending"
        assert journal.admit(direct).reason == "arrival_pending"
        journal.close()
        journal = AccountJournal(path, self._config())
        assert journal.coordinate(batch).reason == "arrival_pending"
        assert journal.admit(direct).reason == "arrival_pending"
        journal.advance_paper(at + timedelta(milliseconds=2))
        journal.advance_paper(at + timedelta(milliseconds=2))

        assert self._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("beta", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(milliseconds=1), "reserved"),
            ("beta", timedelta(milliseconds=1), "account_limit"),
        ]
        assert [item.instance_id for item in journal.orders()] == ["alpha"]

    @pytest.mark.parametrize(
        ("crossing_us", "fills"),
        (
            (11_999, {"alpha": Decimal(2), "beta": Decimal(2)}),
            (13_000, {"beta": Decimal(2)}),
            (14_000, {}),
        ),
        ids=("before-both-deadlines", "between-deadlines", "at-the-later-deadline"),
    )
    def test_arrivals_with_different_deadlines_keep_their_own_lifetimes(
        self, tmp_path: Path, crossing_us: int, fills: dict[str, Decimal]
    ) -> None:
        """A superseded arrival keeps its own cancellation deadline; it is not netted away.

        Entry and cancellation both take 10 ms. Alpha and beta each decide at 1 s to buy two
        at 100, arriving at +10 ms. Alpha decides again at +2 ms, so its first plan must end
        by +12 ms; beta decides again at +4 ms, so beta's must end by +14 ms. Both first plans
        arrive at +10 ms, before their deadlines, as two separate physical orders, each with
        its own deadline. A book offering ten at 100 just before +12 ms fills both; one at
        +13 ms fills only beta's, alpha's having ended at +12 ms without a book; one at
        +14 ms fills neither. Reopening the journal and retrying the book change nothing.
        """
        scenario = replace(self._delayed_scenario(), entry_delay_us=10_000, cancel_delay_us=10_000)
        path = tmp_path / "deadlines.sqlite3"
        journal, at = self._fresh(path, scenario)
        journal.observe(AccountQuote(price=self._price(), at=at))
        both = journal.coordinate(
            PortfolioBatch(
                identity="both-buy",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    self._decision(instance=name, identity=f"{name}-first", at=at)
                    for name in ("alpha", "beta")
                ),
            )
        )
        assert both.reason == "arrival_pending"
        for name, after in (("alpha", 2), ("beta", 4)):
            decided = at + timedelta(milliseconds=after)
            journal.observe(AccountQuote(price=self._price(), at=decided))
            again = journal.coordinate(
                PortfolioBatch(
                    identity=f"{name}-again",
                    at=decided + timedelta(microseconds=1),
                    decisions=(self._below(name, decided, "1"),),
                )
            )
            assert again.reason == "replacement_pending"
        journal.advance_paper(at + timedelta(microseconds=10_500))
        parents = journal.net_orders()
        assert [len(parent.allocations) for parent in parents] == [1, 1]
        journal.close()
        journal = AccountJournal(path, self._config())
        crossing = self._book("crossing", at + timedelta(microseconds=crossing_us), "100")
        trace = PaperBooks.apply(journal, "shared", crossing, scenario)
        assert PaperBooks.apply(journal, "shared", crossing, scenario) == trace

        ledger = AccountLedger(journal.accounts()[0].ledger)
        held = {
            name: position.value
            for name in ("alpha", "beta")
            for position in ledger.snapshot(instance_id=name).positions
        }
        assert held == fills
        first = {
            item.instance_id: item.order
            for item in journal.orders()
            if item.order.decision_at == at + timedelta(milliseconds=10)
        }
        assert {name: order.status for name, order in first.items()} == {
            name: "filled" if name in fills else "cancelled" for name in ("alpha", "beta")
        }

    @pytest.mark.parametrize(
        ("fresh_ms", "reason"),
        ((None, "no_fresh_book_at_arrival"), (1_000, "reserved")),
        ids=("stale-at-arrival", "refreshed-before-arrival"),
    )
    def test_quote_freshness_is_judged_at_the_replacements_arrival(
        self, tmp_path: Path, fresh_ms: int | None, reason: str
    ) -> None:
        """A book fresh when the cancellation completes may be stale by arrival.

        Entry takes 1.5 s and cancellation 5 ms; quotes stay usable for 1 s. Alpha's +3
        ms target replaces its bid, which the +8 ms book ends, so it arrives at +1.508 s.
        With no later book the +8 ms book is then 1.5 s old: the arrival records
        ``no_fresh_book_at_arrival``. A book at +1 s is fresh at arrival and admits it.
        Both are resolved by the +2 s book's command.
        """
        scenario = replace(self._delayed_scenario(), entry_delay_us=1_500_000)
        journal = AccountJournal(tmp_path / "fresh.sqlite3", self._config())
        journal.bind_paper_scenario("shared", scenario)
        assert journal.reconcile(
            AccountObservation(
                identity="opening", at=self.opening_at, snapshot=self._opening(), open_orders=()
            )
        )
        at = self.opening_at + timedelta(seconds=1)
        self._replaced_at_three(
            journal,
            at,
            self._target("alpha", "alpha-replaces", at + timedelta(milliseconds=3), "2"),
        )
        books = [("cancels", 8)] + ([] if fresh_ms is None else [("fresh", fresh_ms)])
        for name, after in (*books, ("later", 2_000)):
            PaperBooks.apply(
                journal,
                "shared",
                self._book(name, at + timedelta(milliseconds=after), "100"),
                scenario,
            )

        assert self._outcomes(journal, at)[-1] == (
            "alpha",
            timedelta(milliseconds=1_508),
            reason,
        )

    @pytest.mark.parametrize(
        ("moved_us", "limit"),
        ((9_000, "100.20"), (9_001, "100")),
        ids=("book-at-arrival", "book-after-arrival"),
    )
    def test_a_book_at_the_arrival_informs_it_and_a_later_book_does_not(
        self, tmp_path: Path, moved_us: int, limit: str
    ) -> None:
        """Equal-time order is market before arrival; reopen and retries keep the outcome.

        Entry takes 1 ms and cancellation 5 ms. Alpha's +3 ms target replaces its bid,
        which the +8 ms book (ask 100) ends, so it arrives at +9 ms. The journal is
        reopened while the target is in flight. A book moving the ask to 100.20 at
        exactly +9 ms is known at arrival, which buys through 100.20; one at +9.001 ms
        comes after the arrival, whose command resolves the target first, through 100.
        Retrying that book and the next one changes nothing.
        """
        scenario = self._delayed_scenario()
        path = tmp_path / "equal-time.sqlite3"
        journal = self._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        self._replaced_at_three(
            journal,
            at,
            self._target("alpha", "alpha-replaces", at + timedelta(milliseconds=3), "2"),
        )
        PaperBooks.apply(
            journal,
            "shared",
            self._touch("cancels", at + timedelta(milliseconds=8), "99.50", "100"),
            scenario,
        )
        journal.close()
        journal = AccountJournal(path, self._config())
        books = (
            self._touch("moves", at + timedelta(microseconds=moved_us), "99.70", "100.20"),
            self._touch("next", at + timedelta(microseconds=9_500), "99.70", "100.30"),
        )
        traces = [PaperBooks.apply(journal, "shared", book, scenario) for book in books]
        outcomes = self._outcomes(journal, at)
        assert [PaperBooks.apply(journal, "shared", book, scenario) for book in books] == traces
        assert self._outcomes(journal, at) == outcomes

        assert outcomes[-1] == ("alpha", timedelta(milliseconds=9), "reserved")
        (sent,) = (
            item.order
            for item in journal.orders()
            if item.order.decision_at > at + timedelta(milliseconds=3)
        )
        assert sent.intent.limit == self._price(limit)

    @pytest.mark.parametrize(
        ("second_ms", "expected"),
        (
            (
                2,
                [
                    ("alpha", 0, "arrival_pending"),
                    ("alpha", 1, "reserved"),
                    ("alpha", 1, "replacement_pending"),
                    ("alpha", 2, "replacement_pending"),
                    ("alpha", 7, "replaced_before_arrival"),
                    ("alpha", 8, "reserved"),
                ],
            ),
            (
                4,
                [
                    ("alpha", 0, "arrival_pending"),
                    ("alpha", 1, "reserved"),
                    ("alpha", 1, "replacement_pending"),
                    ("alpha", 4, "replacement_pending"),
                    ("alpha", 7, "reserved"),
                    ("alpha", 10, "reserved"),
                ],
            ),
        ),
        ids=("withdrawn", "arrives-then-cancelled"),
    )
    def test_a_waiting_plan_enters_only_before_a_later_decisions_cancellation(
        self, tmp_path: Path, second_ms: int, expected: list[tuple[str, int, str]]
    ) -> None:
        """An unsent plan behind a later decision enters only if it enters before that cancel.

        Entry takes 1 ms and cancellation 5 ms. A bid at 99, decided at 1 s, arrives at +1 ms; the
        +1 ms decision's command admits it first, and that decision bids 99.10 and waits for the old
        bid's cancellation, which the +6 ms book confirms, so it would arrive at +7 ms. A second
        decision bids 99.20 and requests cancellation from its own date plus 5 ms. Decided at +2 ms,
        that cancellation falls at +7 ms, so the first plan is withdrawn at its +7 ms arrival, as
        research withdraws a plan arriving at or after its cancellation; the second is released at
        its +7 ms deadline and arrives at +8 ms, admitted by the +12 ms book's command. Decided at
        +4 ms, the cancellation falls at +9 ms: the first plan arrives at +7 ms, admitted by the +8
        ms book's command, and its bid's cancellation takes effect at +9 ms although no book arrives
        then; the second plan is released at +9 ms and arrives at +10 ms, and the +12 ms book's
        command settles all three in order before matching.
        """
        scenario = self._delayed_scenario()
        journal = self._bound(tmp_path / "ordering.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        bids = (
            ("alpha-99", 0, "99"),
            ("alpha-99.10", 1, "99.10"),
            ("alpha-99.20", second_ms, "99.20"),
        )
        for identity, after, price in bids:
            decided = at + timedelta(milliseconds=after)
            journal.observe(AccountQuote(price=self._price(price), at=decided))
            journal.coordinate(
                PortfolioBatch(
                    identity=identity,
                    at=decided + timedelta(microseconds=1),
                    decisions=(
                        self._decision(
                            instance="alpha",
                            identity=identity,
                            at=decided,
                            quantity="1",
                            price=price,
                        ),
                    ),
                )
            )
        for after in (6, 7, 8, 12, 13, 14):
            PaperBooks.apply(
                journal,
                "shared",
                self._book(f"book-{after}", at + timedelta(milliseconds=after), "100"),
                scenario,
            )

        assert self._outcomes(journal, at) == [
            (instance, timedelta(milliseconds=after), reason)
            for instance, after, reason in expected
        ]
        live = {
            str(item.order.intent.limit.value): not item.order.is_terminal
            for item in journal.orders()
        }
        assert live == (
            {"99": False, "99.20": True}
            if second_ms == 2
            else {"99": False, "99.10": False, "99.20": True}
        )
        assert self._physical_fills(journal) == []

    def test_a_replacement_without_a_fresh_book_at_its_send_places_nothing(
        self, tmp_path: Path
    ) -> None:
        """A send whose latest book is older than the quote bound records that, and no order.

        Entry takes 1 ms and cancellation 2 s; quotes stay usable for 1 s. Alpha's bid
        for two, decided at 1 s, rests from +1 ms, and its +3 ms target of three waits
        until +2.003 s. The
        +4 ms book fills the bid. No book follows until +3 s, whose command resolves the
        target at its arrival, +2.004 s, one entry delay after its +2.003 s deadline: the
        newest book, from +4 ms, is then 2 s old, so the target is recorded as
        ``no_fresh_book_at_arrival`` and buys nothing, as research's arrival without a
        fresh book does.
        """
        scenario = replace(self._delayed_scenario(), cancel_delay_us=2_000_000)
        journal = AccountJournal(tmp_path / "stale.sqlite3", self._config())
        journal.bind_paper_scenario("shared", scenario)
        assert journal.reconcile(
            AccountObservation(
                identity="opening", at=self.opening_at, snapshot=self._opening(), open_orders=()
            )
        )
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        journal.coordinate(
            PortfolioBatch(
                identity="bid",
                at=at + timedelta(microseconds=1),
                decisions=(self._decision(instance="alpha", identity="alpha-bid", at=at),),
            )
        )
        PaperBooks.apply(
            journal, "shared", self._book("above", at + timedelta(milliseconds=2), "101"), scenario
        )
        target_at = at + timedelta(milliseconds=3)
        journal.observe(AccountQuote(price=self._price(), at=target_at))
        journal.coordinate(
            PortfolioBatch(
                identity="target",
                at=target_at + timedelta(microseconds=1),
                decisions=(self._target("alpha", "alpha-target", target_at, "3"),),
            )
        )
        for name, after in (("fills", timedelta(milliseconds=4)), ("late", timedelta(seconds=3))):
            PaperBooks.apply(journal, "shared", self._book(name, at + after, "100"), scenario)

        assert self._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(milliseconds=1), "reserved"),
            ("alpha", timedelta(milliseconds=3), "replacement_pending"),
            ("alpha", timedelta(milliseconds=2004), "no_fresh_book_at_arrival"),
        ]
        assert len(journal.orders()) == 1
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot(instance_id="alpha").positions == (self._quantity("2"),)

    @pytest.mark.parametrize(
        ("crossing_us", "filled"),
        ((8_999, True), (9_000, False), (10_000, False)),
        ids=("before-deadline", "at-deadline", "between-deadlines"),
    )
    def test_a_plan_sent_after_being_replaced_ends_at_the_later_decisions_deadline(
        self, tmp_path: Path, crossing_us: int, filled: bool
    ) -> None:
        """An obsolete plan's order keeps the replacing decision's deadline, not a fresh delay.

        Entry takes 1 ms and cancellation 5 ms. A bid at 99 rests from 1 s; the +1 ms
        decision to bid 99.10 waits for it, and the +4 ms decision to bid 99.20 replaces
        that plan with a cancellation deadline of +9 ms. The +6 ms book ends the old bid,
        so the 99.10 plan arrives at +7 ms, before +9 ms, and the +7.5 ms book's command
        admits it. Its cancellation is requested at that admission, +7.001 ms, and still
        takes effect at +9 ms, not at +12.001 ms. After a journal reopen, a book offering
        ten at 99.10 just before +9 ms fills it; one at exactly +9 ms, or at +10 ms
        between the two deadlines, ends it instead. Retrying that book changes nothing.
        """
        scenario = self._delayed_scenario()
        path = tmp_path / "deadline.sqlite3"
        journal = self._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        for identity, after, price in (
            ("alpha-99", 0, "99"),
            ("alpha-99.10", 1, "99.10"),
            ("alpha-99.20", 4, "99.20"),
        ):
            decided = at + timedelta(milliseconds=after)
            journal.observe(AccountQuote(price=self._price(price), at=decided))
            journal.coordinate(
                PortfolioBatch(
                    identity=identity,
                    at=decided + timedelta(microseconds=1),
                    decisions=(
                        self._decision(
                            instance="alpha",
                            identity=identity,
                            at=decided,
                            quantity="1",
                            price=price,
                        ),
                    ),
                )
            )
        for after in (6_000, 7_000, 7_500):
            PaperBooks.apply(
                journal,
                "shared",
                self._book(f"book-{after}", at + timedelta(microseconds=after), "100"),
                scenario,
            )
        (obsolete,) = (
            item.order
            for item in journal.orders()
            if item.order.intent.limit == self._price("99.10")
        )
        assert obsolete.cancel_requested
        journal.close()
        journal = AccountJournal(path, self._config())
        crossing = PaperMarket(
            identity="crossing",
            at=at + timedelta(microseconds=crossing_us),
            bid=self._price("99"),
            ask=self._price("99.10"),
            bid_quantity=self._quantity("10"),
            ask_quantity=self._quantity("10"),
        )
        trace = PaperBooks.apply(journal, "shared", crossing, scenario)
        assert PaperBooks.apply(journal, "shared", crossing, scenario) == trace

        crossed_at = at + timedelta(microseconds=crossing_us)
        assert self._physical_fills(journal) == ([(crossed_at, Decimal(1))] if filled else [])
        (ended,) = (
            item.order
            for item in journal.orders()
            if item.order.intent.limit == self._price("99.10")
        )
        assert ended.status == ("filled" if filled else "cancelled")
        if not filled:
            # At the deadline the book's own match ends it; after it, the cancellation
            # already took effect at +9 ms, before that book, without one.
            (cancelled,) = (
                saved.event
                for saved in AccountStateStore(path, self._config(), DomainCodec())
                .read()
                .net_events
                if saved.event.kind == "cancelled_on_request"
                and saved.result.order.intent.limit == self._price("99.10")
            )
            assert cancelled.at == at + timedelta(milliseconds=9)

    def test_a_strategy_stop_withdraws_its_waiting_replacement_for_good(
        self, tmp_path: Path
    ) -> None:
        """A selective stop withdraws intent: its waiting plan never sends, even after restart.

        Entry takes 1 ms and cancellation 5 ms. Alpha and beta each rest a bid, decided at 1 s and
        arriving at +1 ms, and at +3 ms each targets a holding, so both decisions wait for their
        bids' cancellations. Alpha is stopped at +5 ms: its plan is withdrawn and retained as
        ``withdrawn_by_instance_stop``, while its bid keeps its reservation until the +8 ms book
        ends it. Across a journal reopen, beta's target arrives at +9 ms, is admitted by the +9.5 ms
        book's command on the +9 ms book, and that +9.5 ms book fills it. Alpha restarts at +10 ms
        and the +11 ms book sends nothing for it: a new decision would be needed.
        """
        scenario = self._delayed_scenario()
        path = tmp_path / "stop-withdraws.sqlite3"
        journal = self._bound(path)
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        journal.coordinate(
            PortfolioBatch(
                identity="both-rest",
                at=at + timedelta(microseconds=1),
                decisions=(self._below("alpha", at, "2"), self._below("beta", at, "1")),
            )
        )
        decided = at + timedelta(milliseconds=3)
        journal.observe(AccountQuote(price=self._price(), at=decided))
        journal.coordinate(
            PortfolioBatch(
                identity="both-target",
                at=decided + timedelta(microseconds=1),
                decisions=(
                    self._target("alpha", "alpha-target", decided, "2"),
                    self._target("beta", "beta-target", decided, "1"),
                ),
            )
        )
        journal.stop_instance("alpha", at + timedelta(milliseconds=5))
        (alpha_bid,) = (item.order for item in journal.orders() if item.instance_id == "alpha")
        assert not alpha_bid.is_terminal and alpha_bid.cancel_requested
        journal.close()
        journal = AccountJournal(path, self._config())
        for name, after in (("cancels", 8_000), ("sends", 9_000), ("fills", 9_500)):
            PaperBooks.apply(
                journal,
                "shared",
                self._book(name, at + timedelta(microseconds=after), "100"),
                scenario,
            )
        restart_at = at + timedelta(milliseconds=10)
        assert journal.reconcile(
            AccountObservation(
                identity="before-restart",
                at=restart_at,
                snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                open_orders=(),
            )
        )
        journal.restart_instance("alpha", restart_at)
        PaperBooks.apply(
            journal, "shared", self._book("after", at + timedelta(milliseconds=11), "100"), scenario
        )

        assert self._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("beta", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(milliseconds=1), "reserved"),
            ("beta", timedelta(milliseconds=1), "reserved"),
            ("alpha", timedelta(milliseconds=3), "replacement_pending"),
            ("beta", timedelta(milliseconds=3), "replacement_pending"),
            ("alpha", timedelta(milliseconds=5), "withdrawn_by_instance_stop"),
            ("beta", timedelta(milliseconds=9), "reserved"),
        ]
        assert [item.order.status for item in journal.orders() if item.instance_id == "alpha"] == [
            "cancelled"
        ]
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot(instance_id="alpha").positions == ()
        assert ledger.snapshot(instance_id="beta").positions == (self._quantity("1"),)

    def test_one_strategys_replacement_neither_waits_for_nor_cancels_another(
        self, tmp_path: Path
    ) -> None:
        """Alpha's target waits for its own bid's cancellation alone; beta trades at once.

        Entry takes 1 ms and cancellation 5 ms. Alpha's bid at 99.50 rests from +1 ms. At +3 ms
        alpha targets two units and beta bids 99.50 in the same batch: alpha's decision waits for
        its bid's cancellation, while beta's bid, replacing nothing, arrives at +4 ms and is never
        cancelled. The +8 ms book confirms alpha's cancellation, so alpha's target arrives at +9 ms,
        and the +10 ms book's command admits it while beta's bid still rests.
        """
        scenario = self._delayed_scenario()
        journal = self._bound(tmp_path / "isolation.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        rests = journal.coordinate(
            PortfolioBatch(
                identity="alpha-rests",
                at=at + timedelta(microseconds=1),
                decisions=(self._below("alpha", at, "2"),),
            )
        )
        assert rests.reason == "arrival_pending"
        decided = at + timedelta(milliseconds=3)
        journal.observe(AccountQuote(price=self._price(), at=decided))
        mixed = journal.coordinate(
            PortfolioBatch(
                identity="mixed",
                at=decided + timedelta(microseconds=1),
                decisions=(
                    self._target("alpha", "alpha-target", decided, "2"),
                    self._below("beta", decided, "1"),
                ),
            )
        )
        assert (mixed.status, mixed.reason, mixed.children) == (
            "committed",
            "replacement_pending",
            (),
        )
        for after in (8, 9, 10):
            PaperBooks.apply(
                journal,
                "shared",
                self._book(f"book-{after}", at + timedelta(milliseconds=after), "100"),
                scenario,
            )

        assert self._outcomes(journal, at) == [
            ("alpha", timedelta(0), "arrival_pending"),
            ("alpha", timedelta(milliseconds=1), "reserved"),
            ("alpha", timedelta(milliseconds=3), "replacement_pending"),
            ("beta", timedelta(milliseconds=3), "arrival_pending"),
            ("beta", timedelta(milliseconds=4), "reserved"),
            ("alpha", timedelta(milliseconds=9), "reserved"),
        ]
        beta = next(item.order for item in journal.orders() if item.instance_id == "beta")
        assert not beta.is_terminal and not beta.cancel_requested

    @classmethod
    def _below(cls, instance: str, at: datetime, quantity: str) -> PortfolioDecision:
        """Rest a ``gtc`` bid at 99.50, below the 100 quote and ask."""
        decision = cls._decision(
            instance=instance, identity=f"{instance}-bid", at=at, quantity=quantity
        )
        intent = decision.request.decision.intent
        assert isinstance(intent, OrderIntent)
        return replace(
            decision,
            request=replace(
                decision.request,
                decision=replace(
                    decision.request.decision, intent=replace(intent, limit=cls._price("99.50"))
                ),
            ),
        )

    def test_an_order_expiring_under_a_pending_account_cancel_ends_its_child(
        self, tmp_path: Path
    ) -> None:
        """An IOC that expires before an account cancel takes effect is never re-sent.

        Entry takes 1 ms and cancellation 5 ms. The IOC, decided at 1 s, arrives at +1 ms; the
        account cancel at +2 ms first settles that arrival, so it requests the IOC's cancellation,
        still pending at the +3 ms book, whose 101 ask is above the 100 limit, so the IOC expires on
        its own terms. Nothing is left to reissue: the next batch on the account sends nothing, and
        a later book at the limit leaves the account exactly at its opening cash.
        """
        scenario = self._delayed_scenario()
        journal = self._bound(tmp_path / "expired-under-cancel.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        sent = journal.coordinate(
            PortfolioBatch(
                identity="alpha-ioc",
                at=at + timedelta(microseconds=1),
                decisions=(
                    self._lasting(
                        self._decision(instance="alpha", identity="alpha-ioc", at=at), "ioc"
                    ),
                ),
            )
        )
        assert (sent.status, sent.reason, sent.net_orders) == ("committed", "arrival_pending", ())
        cancel = journal.control(
            AccountControl(
                identity="operator-cancel",
                account_id="shared",
                kind="cancel",
                at=at + timedelta(milliseconds=2),
            )
        )
        assert cancel.status == "applied"
        expiry = PaperBooks.apply(
            journal, "shared", self._book("expiry", at + timedelta(milliseconds=3), "101"), scenario
        )
        assert [event.kind for event in expiry.physical_events] == [
            "request_ack",
            "accepted",
            "cancelled",
        ]
        assert self._statuses(journal) == {"alpha": "cancelled"}
        assert journal.portfolio_residuals("shared") == ()
        reconciled_at = at + timedelta(milliseconds=10)
        assert journal.reconcile(
            AccountObservation(
                identity="after-expiry",
                at=reconciled_at,
                snapshot=self._opening(),
                open_orders=(),
            )
        )
        next_at = reconciled_at + timedelta(milliseconds=10)
        journal.observe(AccountQuote(price=self._price(), at=next_at))
        abstained = journal.coordinate(
            PortfolioBatch(
                identity="beta-abstains",
                at=next_at + timedelta(microseconds=1),
                decisions=(self._abstention("beta", "beta-abstains", next_at),),
            )
        )
        assert (abstained.status, abstained.net_orders) == ("committed", ())
        PaperBooks.apply(
            journal,
            "shared",
            self._book("at-limit", next_at + timedelta(milliseconds=3), "100"),
            scenario,
        )
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == self._opening()

    def test_a_shared_order_expiring_after_another_strategy_replaces_ends_both_children(
        self, tmp_path: Path
    ) -> None:
        """Alpha's replacement requests the shared IOC's cancel; the IOC expires first.

        Alpha's and beta's IOCs, decided together at 1 s, arrive together at +1 ms and are
        coordinated together into one shared parent. The +3 ms book (ask 101 above the 100 limit)
        ends the parent on its own terms, before alpha's +2 ms request takes effect at +7 ms. Beta's
        child ends with it, so alpha's next order needs no newer reconciliation. Alpha's abstention
        is still waiting at +7 ms, so the new two-unit IOC replaces it: it is released at +12 ms,
        after that decision's cancel delay, arrives at +13 ms and is admitted by the +14 ms book's
        command, and ten units at the 100 limit on that book fill it: alpha holds 2, beta 0.
        """
        scenario = self._delayed_scenario()
        journal = self._bound(tmp_path / "expired-shared.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        pair = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    self._lasting(
                        self._decision(instance=name, identity=f"{name}-ioc", at=at), "ioc"
                    )
                    for name in ("alpha", "beta")
                ),
            )
        )
        assert (pair.status, pair.reason, pair.net_orders) == ("committed", "arrival_pending", ())
        replace_at = at + timedelta(milliseconds=2)
        journal.observe(AccountQuote(price=self._price(), at=replace_at))
        replaced = journal.coordinate(
            PortfolioBatch(
                identity="alpha-replaces",
                at=replace_at + timedelta(microseconds=1),
                decisions=(self._abstention("alpha", "alpha-abstains", replace_at),),
            )
        )
        assert (replaced.status, replaced.reason) == ("committed", "replacement_pending")
        (shared,) = journal.net_orders()
        assert len(shared.allocations) == 2 and shared.order.cancel_requested
        expiry = PaperBooks.apply(
            journal,
            "shared",
            self._book("expiry", replace_at + timedelta(milliseconds=1), "101"),
            scenario,
        )
        assert [event.kind for event in expiry.physical_events] == [
            "request_ack",
            "accepted",
            "cancelled",
        ]
        assert self._statuses(journal) == {"alpha": "cancelled", "beta": "cancelled"}
        buy_at = replace_at + timedelta(milliseconds=5)
        journal.observe(AccountQuote(price=self._price(), at=buy_at))
        bought = journal.coordinate(
            PortfolioBatch(
                identity="alpha-buys-again",
                at=buy_at + timedelta(microseconds=1),
                decisions=(
                    self._lasting(
                        self._decision(instance="alpha", identity="alpha-again", at=buy_at),
                        "ioc",
                        portfolio="other-portfolio",
                    ),
                ),
            )
        )
        assert (bought.status, bought.reason) == ("committed", "replacement_pending")
        for name, after in (("sends", 6), ("at-limit", 7)):
            PaperBooks.apply(
                journal,
                "shared",
                self._book(name, buy_at + timedelta(milliseconds=after), "100"),
                scenario,
            )
        (sent,) = (
            parent.order for parent in journal.net_orders() if parent.order.decision_at > buy_at
        )
        assert sent.intent.quantity == self._quantity("2")
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot(instance_id="alpha").positions == (self._quantity("2"),)
        assert ledger.snapshot(instance_id="beta").positions == ()

    def test_a_post_only_order_rejected_under_a_pending_cancel_ends_its_children(
        self, tmp_path: Path
    ) -> None:
        """A shared post-only buy crossing at its first eligible book is rejected outright.

        Alpha's and beta's post-only buys arrive together at +1 ms as one parent.
        Alpha's +2 ms replacement is still pending at the +3 ms book, whose ask equals
        the 100 limit, so the order would take liquidity: it is rejected on its own
        terms and beta's child ends with it. Beta's next batch sends nothing.
        """
        scenario = self._delayed_scenario()
        journal = self._bound(tmp_path / "post-only.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        pair = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    self._lasting(
                        self._decision(instance=name, identity=f"{name}-maker", at=at),
                        "post-only",
                    )
                    for name in ("alpha", "beta")
                ),
            )
        )
        assert (pair.status, pair.reason, pair.net_orders) == ("committed", "arrival_pending", ())
        replace_at = at + timedelta(milliseconds=2)
        journal.observe(AccountQuote(price=self._price(), at=replace_at))
        journal.coordinate(
            PortfolioBatch(
                identity="alpha-replaces",
                at=replace_at + timedelta(microseconds=1),
                decisions=(self._abstention("alpha", "alpha-abstains", replace_at),),
            )
        )
        crossed = PaperBooks.apply(
            journal,
            "shared",
            self._book("crossing", replace_at + timedelta(milliseconds=1), "100"),
            scenario,
        )
        assert [event.kind for event in crossed.physical_events] == ["request_ack", "rejected"]
        assert self._statuses(journal) == {"alpha": "cancelled", "beta": "cancelled"}
        next_at = replace_at + timedelta(milliseconds=5)
        journal.observe(AccountQuote(price=self._price(), at=next_at))
        abstained = journal.coordinate(
            PortfolioBatch(
                identity="beta-abstains",
                at=next_at + timedelta(microseconds=1),
                decisions=(self._abstention("beta", "beta-abstains", next_at),),
            )
        )
        assert (abstained.status, abstained.net_orders) == ("committed", ())

    def test_a_shared_order_cancelled_for_a_stop_leaves_the_other_child_to_reissue(
        self, tmp_path: Path
    ) -> None:
        """A cancel that takes effect keeps the documented reissue of unaffected children.

        Both resting buys arrive together at +1 ms as one parent and sit below the 101
        ask. Alpha's stop at +3 ms requests the
        shared parent's cancel, which the +8 ms book honours as a requested
        cancellation. Beta's two units stay reserved and, once a reconciliation covers
        that outcome, are reissued alone at the original limit.
        """
        scenario = self._delayed_scenario()
        journal = self._bound(tmp_path / "stopped-shared.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        pair = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    self._decision(instance=name, identity=f"{name}-resting", at=at)
                    for name in ("alpha", "beta")
                ),
            )
        )
        assert pair.reason == "arrival_pending"
        resting = PaperBooks.apply(
            journal,
            "shared",
            self._book("resting", at + timedelta(milliseconds=2), "101"),
            scenario,
        )
        (parent,) = journal.net_orders()
        parent_id = parent.order.identity
        assert [event.kind for event in resting.physical_events] == ["request_ack", "accepted"]
        stop_at = at + timedelta(milliseconds=3)
        assert [parent.order.identity for parent in journal.stop_instance("alpha", stop_at)] == [
            parent_id
        ]
        early = PaperBooks.apply(
            journal,
            "shared",
            self._book("early", stop_at + timedelta(milliseconds=4), "101"),
            scenario,
        )
        assert early.physical_events == ()
        due_at = stop_at + timedelta(milliseconds=5)
        due = PaperBooks.apply(journal, "shared", self._book("due", due_at, "101"), scenario)
        assert [event.kind for event in due.physical_events] == ["cancelled_on_request"]
        beta = next(item.order for item in journal.orders() if item.instance_id == "beta")
        assert self._statuses(journal)["alpha"] == "cancelled"
        assert not beta.is_terminal and beta.remaining == self._quantity("2")
        retry_at = due_at + timedelta(microseconds=1)
        journal.observe(AccountQuote(price=self._price(), at=retry_at))
        with pytest.raises(ValueError, match="reissue_requires_current_reconciliation"):
            journal.reissue_pending("shared", retry_at)
        assert journal.reconcile(
            AccountObservation(
                identity="after-stop", at=due_at, snapshot=self._opening(), open_orders=()
            )
        )
        reissued = journal.reissue_pending("shared", retry_at)
        assert [
            (parent.order.intent.quantity, parent.order.intent.limit) for parent in reissued
        ] == [(self._quantity("2"), self._price())]
        assert [item.child_order_id for item in reissued[0].allocations] == [beta.identity]

    @pytest.mark.parametrize(
        ("kind", "beta_survives"),
        [("cancelled_on_request", True), ("cancelled", False)],
        ids=["requested-cancellation", "unattributed-cancellation"],
    )
    def test_only_a_requested_cancellation_keeps_the_other_child(
        self, tmp_path: Path, kind: EventKind, beta_survives: bool
    ) -> None:
        """A stop's request is pending on the shared parent; the terminal fact decides.

        An external producer, such as an unmanaged application or a venue gateway,
        states the cause by kind. A cause-neutral ``cancelled`` ends beta's child even
        though a request was pending, and alpha's ends in both cases.
        """
        journal = self._ready(tmp_path / f"{kind}.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    self._decision(instance=name, identity=f"{name}-buy", at=at)
                    for name in ("alpha", "beta")
                ),
            )
        ).net_orders[0]
        journal.stop_instance("alpha", at + timedelta(seconds=1))
        journal.apply_net_event(
            OrderEvent(
                identity="parent-ended",
                order_id=parent.order.identity,
                at=at + timedelta(seconds=2),
                kind=kind,
            )
        )
        statuses = self._statuses(journal)
        assert statuses["alpha"] == "cancelled"
        assert (statuses["beta"] != "cancelled") is beta_survives

    def test_a_reconciled_cancellation_ends_every_child(self, tmp_path: Path) -> None:
        """Reconciliation resolves an unknown parent's end without stating its cause."""
        journal = self._ready(tmp_path / "reconciled.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        parent_id = (
            journal.coordinate(
                PortfolioBatch(
                    identity="pair",
                    at=at + timedelta(microseconds=1),
                    decisions=tuple(
                        self._decision(instance=name, identity=f"{name}-buy", at=at)
                        for name in ("alpha", "beta")
                    ),
                )
            )
            .net_orders[0]
            .order.identity
        )
        journal.apply_net_event(
            OrderEvent(
                identity="lost-ack",
                order_id=parent_id,
                at=at + timedelta(seconds=1),
                kind="unknown",
            )
        )
        # Alpha's stop leaves a request pending beside the unknown outcome.
        journal.stop_instance("alpha", at + timedelta(seconds=2))
        journal.apply_net_event(
            OrderEvent(
                identity="found-cancelled",
                order_id=parent_id,
                at=at + timedelta(seconds=3),
                kind="reconcile_cancelled",
            )
        )
        assert self._statuses(journal) == {"alpha": "cancelled", "beta": "cancelled"}

    def test_a_requested_cancellation_without_a_request_is_refused(self, tmp_path: Path) -> None:
        """A fact claiming a requested cancellation must have a request to name."""
        journal = self._ready(tmp_path / "unrequested.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    self._decision(instance=name, identity=f"{name}-buy", at=at)
                    for name in ("alpha", "beta")
                ),
            )
        ).net_orders[0]
        claimed = OrderEvent(
            identity="unrequested",
            order_id=parent.order.identity,
            at=at + timedelta(seconds=1),
            kind="cancelled_on_request",
        )
        with pytest.raises(ValueError, match="requires a pending cancel request"):
            journal.apply_net_event(claimed)
        assert journal.failed_net_events() == (claimed,)
        assert not any(item.order.is_terminal for item in journal.orders())
        assert not journal.net_orders()[0].order.is_terminal

    def test_reconciliation_projection_states_the_accounts_knowledge_clock(
        self, tmp_path: Path
    ) -> None:
        """An observation matches at the stated clock, which covers a working decision."""
        journal = self._ready(tmp_path / "known.sqlite3")
        market_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=market_at))
        decided_at = market_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price(), at=decided_at))
        working = journal.coordinate(
            PortfolioBatch(
                identity="working",
                at=decided_at + timedelta(microseconds=1),
                decisions=(self._decision(instance="alpha", identity="bid", at=decided_at),),
                crossing="internal_at_quote",
            )
        )
        facts = journal.result_snapshot(
            AccountExecutionRequest(
                action="inspect", account_id="shared", projection="reconciliation"
            )
        )
        assert working.status == "committed"
        assert facts.known_at is not None and facts.known_at >= decided_at
        assert [parent.order for parent in facts.net_orders] == [
            parent.order for parent in working.net_orders
        ]
        snapshot = AccountLedger(facts.accounts[0].ledger).snapshot()
        open_orders = tuple(parent.order for parent in facts.net_orders)
        # Stamped before the account's knowledge clock, an observation is stale: it is
        # refused without recording a mismatch or faulting the account.
        with pytest.raises(ValueError, match="observation_precedes_account_state"):
            journal.reconcile(
                AccountObservation(
                    identity="at-market", at=market_at, snapshot=snapshot, open_orders=open_orders
                )
            )
        assert journal.accounts()[0].fault is None
        assert journal.reconcile(
            AccountObservation(
                identity="at-knowledge",
                at=facts.known_at,
                snapshot=snapshot,
                open_orders=open_orders,
            )
        )
        with pytest.raises(ValueError, match="requires an account"):
            AccountExecutionRequest(action="inspect", projection="reconciliation")

    def test_quote_legs_are_admitted_independently(self, tmp_path: Path) -> None:
        """A flat instance's quote rests its bid and drops its unfunded ask, as research does."""
        journal = self._ready(tmp_path / "quote.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        quote = self._decision(instance="alpha", identity="alpha-quote", at=at)
        bid = OrderIntent(
            side="buy", quantity=self._quantity("1"), limit=self._price("99"), time_in_force="gtc"
        )
        ask = OrderIntent(
            side="sell", quantity=self._quantity("1"), limit=self._price("101"), time_in_force="gtc"
        )
        quote = replace(
            quote,
            request=replace(
                quote.request,
                decision=replace(quote.request.decision, intent=QuoteIntent(bid=bid, ask=ask)),
            ),
        )
        committed = journal.coordinate(
            PortfolioBatch(
                identity="alpha-quotes", at=at + timedelta(microseconds=1), decisions=(quote,)
            )
        )
        assert committed.status == "committed"
        assert [child.order.intent.side for child in committed.children] == ["buy"]
        dedicated = self._ready(tmp_path / "dedicated.sqlite3")
        dedicated.observe(AccountQuote(price=self._price(), at=at))
        step = dedicated.admit(quote.request)
        assert (step.status, [order.intent.side for order in step.orders]) == ("committed", ["buy"])
        assert [(leg.leg, leg.reason) for leg in step.dropped] == [
            ("ask", "insufficient_owned_inventory")
        ]
        unfunded = replace(
            quote,
            request=replace(
                quote.request,
                decision=replace(
                    quote.request.decision,
                    identity="alpha-unfunded",
                    intent=QuoteIntent(
                        bid=replace(bid, quantity=self._quantity("1000")),
                        ask=ask,
                    ),
                ),
            ),
        )
        refused = journal.coordinate(
            PortfolioBatch(
                identity="alpha-unfunded-quotes",
                at=at + timedelta(microseconds=2),
                decisions=(unfunded,),
            )
        )
        assert refused.status == "rejected"
        codec = DomainCodec()
        config_path, request_path = tmp_path / "config.json", tmp_path / "request.json"
        config_path.write_bytes(codec.encode_json(self._config()))
        for identity, outcome in (("alpha-quotes", committed), ("alpha-unfunded-quotes", refused)):
            request = AccountExecutionRequest(
                action="inspect",
                account_id="shared",
                projection="saved_batch",
                query_batch=identity,
            )
            request_path.write_bytes(codec.encode_json(request))
            # The installed command answers exactly what the journal's projection reads.
            for inspected in (
                journal.result_snapshot(request),
                AccountExecutionApplication().run(
                    config_path=config_path,
                    journal_path=tmp_path / "quote.sqlite3",
                    request_path=request_path,
                ),
            ):
                assert inspected.saved_batch is not None
                assert (inspected.saved_batch.identity, inspected.portfolio) == (
                    identity,
                    outcome,
                )
        # One read returns every decision's outcome, with its reason and dropped legs.
        request = AccountExecutionRequest(
            action="inspect", account_id="shared", projection="decisions"
        )
        request_path.write_bytes(codec.encode_json(request))
        for inspected in (
            journal.result_snapshot(request),
            AccountExecutionApplication().run(
                config_path=config_path,
                journal_path=tmp_path / "quote.sqlite3",
                request_path=request_path,
            ),
        ):
            assert [
                (
                    item.instance_id,
                    item.decision_identity,
                    item.status,
                    item.reason,
                    [(leg.leg, leg.reason) for leg in item.dropped],
                )
                for item in inspected.decision_outcomes
            ] == [
                (
                    "alpha",
                    "alpha-quote",
                    "committed",
                    "reserved",
                    [("ask", "insufficient_owned_inventory")],
                ),
                ("alpha", "alpha-unfunded", "rejected", refused.reason, []),
            ]

    def test_conflicting_physical_facts_persist_and_block_new_batches(self, tmp_path: Path) -> None:
        """Physical receipt and fill conflicts survive restart without new economics."""
        path = tmp_path / "physical-event-conflict.sqlite3"
        journal = self._ready(path)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=decision_at))
        committed = journal.coordinate(
            PortfolioBatch(
                identity="physical-conflict-source",
                at=decision_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(instance="alpha", identity="conflict-alpha", at=decision_at),
                    self._decision(instance="beta", identity="conflict-beta", at=decision_at),
                ),
            )
        )
        parent = committed.net_orders[0]
        fill_at = parent.order.decision_at + timedelta(seconds=1)
        source_fill = self._fill(
            "physical-conflicting-fill", parent.order.decision_at, fill_at, "2", "0.02"
        )
        source = OrderEvent(
            identity="physical-source-receipt",
            order_id=parent.order.identity,
            at=fill_at,
            kind="fill",
            fill=source_fill,
        )
        partial = journal.apply_net_event(source)
        assert journal.apply_net_event(source) == partial
        later_at = fill_at + timedelta(microseconds=1)
        later = OrderEvent(
            identity="physical-later-receipt",
            order_id=parent.order.identity,
            at=later_at,
            kind="fill",
            fill=self._fill("physical-later-fill", parent.order.decision_at, later_at, "1", "0.01"),
        )
        latest = journal.apply_net_event(later)
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        mixed_identity_conflict = replace(source, identity=later.identity, at=later.at)
        with pytest.raises(ValueError, match="different content"):
            journal.apply_net_event(mixed_identity_conflict)
        changed_receipt = replace(source, at=fill_at + timedelta(microseconds=2))
        with pytest.raises(ValueError, match="different content"):
            journal.apply_net_event(changed_receipt)
        conflicting_economics = OrderEvent(
            identity="physical-second-receipt",
            order_id=parent.order.identity,
            at=fill_at + timedelta(microseconds=3),
            kind="fill",
            fill=replace(source_fill, quantity=self._quantity("1")),
        )
        with pytest.raises(ValueError, match="different economics"):
            journal.apply_net_event(conflicting_economics)
        with pytest.raises(ValueError, match="different content"):
            journal.apply_net_event(changed_receipt)

        recovered = AccountJournal(path, self._config())
        assert recovered.failed_net_events() == (
            mixed_identity_conflict,
            changed_receipt,
            conflicting_economics,
        )
        assert recovered.accounts()[0].fault == "physical_event_break"
        assert recovered.net_orders()[0] == latest
        assert AccountLedger(recovered.accounts()[0].ledger).snapshot() == snapshot
        assert recovered.apply_net_event(source) == partial
        assert recovered.net_orders()[0] == latest
        assert recovered.accounts()[0].fault == "physical_event_break"
        assert AccountLedger(recovered.accounts()[0].ledger).snapshot() == snapshot

        blocked_at = fill_at + timedelta(seconds=1)
        recovered.observe(AccountQuote(price=self._price(), at=blocked_at))
        blocked = recovered.coordinate(
            PortfolioBatch(
                identity="batch-after-physical-conflict",
                at=blocked_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha", identity="alpha-after-conflict", at=blocked_at
                    ),
                ),
            )
        )
        assert (blocked.status, blocked.reason) == ("rejected", "physical_event_break")
        assert not recovered.reconcile(
            AccountObservation(
                identity="matching-after-physical-conflict",
                at=blocked_at + timedelta(microseconds=1),
                snapshot=snapshot,
                open_orders=(latest.order,),
            )
        )
        restarted = AccountJournal(path, self._config())
        assert restarted.failed_net_events() == (
            mixed_identity_conflict,
            changed_receipt,
            conflicting_economics,
        )
        assert restarted.accounts()[0].fault == "account_break"
        assert AccountLedger(restarted.accounts()[0].ledger).snapshot() == snapshot

    def test_physical_receipt_identity_collision_alone_blocks_reconciliation(
        self, tmp_path: Path
    ) -> None:
        """A receipt identity cannot borrow an accepted fill from another receipt."""
        path = tmp_path / "physical-receipt-identity-conflict.sqlite3"
        journal = self._ready(path)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=decision_at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="receipt-identity-parent",
                at=decision_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha",
                        identity="receipt-identity-alpha",
                        at=decision_at,
                        quantity="4",
                    ),
                ),
            )
        ).net_orders[0]
        first_at = parent.order.decision_at + timedelta(seconds=1)
        source = OrderEvent(
            identity="receipt-identity-source",
            order_id=parent.order.identity,
            at=first_at,
            kind="fill",
            fill=self._fill(
                "receipt-identity-source-fill",
                parent.order.decision_at,
                first_at,
                "1",
                "0.01",
            ),
        )
        journal.apply_net_event(source)
        later_at = first_at + timedelta(microseconds=1)
        later = OrderEvent(
            identity="receipt-identity-later",
            order_id=parent.order.identity,
            at=later_at,
            kind="fill",
            fill=self._fill(
                "receipt-identity-later-fill",
                parent.order.decision_at,
                later_at,
                "1",
                "0.01",
            ),
        )
        latest = journal.apply_net_event(later)
        assert latest.order.remaining == self._quantity("2")
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.cash == (self._money("49799.98"),)
        assert snapshot.positions == (self._quantity("2"),)
        assert snapshot.fees == (self._money("0.02"),)

        collision = replace(source, identity=later.identity, at=later.at)
        with pytest.raises(ValueError, match="different content"):
            journal.apply_net_event(collision)

        recovered = AccountJournal(path, self._config())
        assert recovered.failed_net_events() == (collision,)
        assert recovered.accounts()[0].fault == "physical_event_break"
        assert recovered.net_orders()[0] == latest
        assert AccountLedger(recovered.accounts()[0].ledger).snapshot() == snapshot
        observed_at = later_at + timedelta(seconds=1)
        assert not recovered.reconcile(
            AccountObservation(
                identity="matching-after-receipt-identity-conflict",
                at=observed_at,
                snapshot=snapshot,
                open_orders=(latest.order,),
            )
        )

        restarted = AccountJournal(path, self._config())
        assert restarted.failed_net_events() == (collision,)
        assert restarted.accounts()[0].fault == "account_break"
        decision_after_conflict = observed_at + timedelta(seconds=1)
        restarted.observe(AccountQuote(price=self._price(), at=decision_after_conflict))
        blocked = restarted.coordinate(
            PortfolioBatch(
                identity="batch-after-receipt-identity-conflict",
                at=decision_after_conflict + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="beta",
                        identity="beta-after-receipt-identity-conflict",
                        at=decision_after_conflict,
                    ),
                ),
            )
        )
        assert (blocked.status, blocked.reason) == ("rejected", "account_break")
        assert restarted.net_orders() == (latest,)

    def test_failed_physical_receipt_accepted_identically_can_reconcile(
        self, tmp_path: Path
    ) -> None:
        """A later-valid physical receipt permits restart reconciliation and new risk."""
        path = tmp_path / "repaired-physical-event.sqlite3"
        journal = self._ready(path)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=decision_at))
        committed = journal.coordinate(
            PortfolioBatch(
                identity="repairable-physical-parent",
                at=decision_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(instance="alpha", identity="repairable-alpha", at=decision_at),
                ),
            )
        )
        parent = committed.net_orders[0]
        receipt_at = decision_at + timedelta(seconds=1)
        acknowledgement = OrderEvent(
            identity="early-physical-cancel-ack",
            order_id=parent.order.identity,
            at=receipt_at,
            kind="cancel_ack",
        )
        with pytest.raises(ValueError, match="cancel acknowledgement requires"):
            journal.apply_net_event(acknowledgement)
        assert journal.failed_net_events() == (acknowledgement,)
        assert not journal.reconcile(
            AccountObservation(
                identity="before-physical-repair",
                at=receipt_at,
                snapshot=self._opening(),
                open_orders=(parent.order,),
            )
        )
        assert journal.accounts()[0].fault == "account_break"
        journal.apply_net_event(
            OrderEvent(
                identity="physical-cancel-request",
                order_id=parent.order.identity,
                at=receipt_at,
                kind="cancel_requested",
            )
        )
        acknowledged = journal.apply_net_event(acknowledgement)
        assert acknowledged.order.status == "cancel_ack"

        recovered = AccountJournal(path, self._config())
        assert recovered.failed_net_events() == (acknowledgement,)
        assert recovered.net_orders()[0] == acknowledged
        assert recovered.reconcile(
            AccountObservation(
                identity="repaired-physical-observation",
                at=receipt_at,
                snapshot=self._opening(),
                open_orders=(acknowledged.order,),
            )
        )
        assert recovered.accounts()[0].fault is None

        next_at = receipt_at + timedelta(seconds=1)
        recovered.observe(AccountQuote(price=self._price(), at=next_at))
        resumed = recovered.coordinate(
            PortfolioBatch(
                identity="batch-after-physical-repair",
                at=next_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(instance="beta", identity="beta-after-repair", at=next_at),
                ),
            )
        )
        assert resumed.status == "committed"
        assert len(resumed.net_orders) == 1

    def test_explicit_internal_cross_preserves_physical_account(self, tmp_path: Path) -> None:
        """Opposite owned intents exchange inventory with zero physical trade."""
        journal = self._ready(tmp_path / "cross.sqlite3")
        first_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=first_at))
        funding = journal.coordinate(
            PortfolioBatch(
                identity="alpha-inventory",
                at=first_at + timedelta(microseconds=1),
                decisions=(self._decision(instance="alpha", identity="seed", at=first_at),),
                crossing="internal_at_quote",
            )
        )
        parent = funding.net_orders[0]
        fill_at = first_at + timedelta(seconds=1)
        journal.apply_net_event(
            OrderEvent(
                identity="seed-receipt",
                order_id=parent.order.identity,
                at=fill_at,
                kind="fill",
                fill=self._fill("seed-physical", parent.order.decision_at, fill_at, "2", "0"),
            )
        )
        before = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert before.cash == (self._money("49800"),)
        assert before.positions == (self._quantity("2"),)
        assert journal.reconcile(
            AccountObservation(
                identity="seed-observed", at=fill_at, snapshot=before, open_orders=()
            )
        )
        cross_at = fill_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=cross_at))
        crossed = journal.coordinate(
            PortfolioBatch(
                identity="inventory-transfer",
                at=cross_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha",
                        identity="alpha-sell",
                        at=cross_at,
                        side="sell",
                        quantity="1",
                    ),
                    self._decision(instance="beta", identity="beta-buy", at=cross_at, quantity="1"),
                ),
                crossing="internal_at_quote",
            )
        )
        assert crossed.status == "committed"
        assert crossed.net_orders == ()
        assert len(crossed.internal_fill_ids) == 2
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot().cash == before.cash
        assert ledger.snapshot().positions == before.positions
        assert ledger.snapshot(instance_id="alpha").positions == (self._quantity("1"),)
        assert ledger.snapshot(instance_id="beta").positions == (self._quantity("1"),)
        assert (
            journal.coordinate(
                PortfolioBatch(
                    identity="scope-change",
                    at=cross_at + timedelta(seconds=1),
                    decisions=(
                        self._decision(
                            instance="beta",
                            identity="another-buy",
                            at=cross_at + timedelta(microseconds=2),
                        ),
                    ),
                    crossing="reject",
                )
            ).reason
            == "portfolio_crossing_policy_changed"
        )

    def test_physical_price_improvement_keeps_independent_decision_quote(
        self, tmp_path: Path
    ) -> None:
        """A better physical fill price allocates valid cash at its own benchmark."""
        journal = self._ready(tmp_path / "better-price.sqlite3")
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=decision_at))
        committed = journal.coordinate(
            PortfolioBatch(
                identity="improved-fill",
                at=decision_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(instance="alpha", identity="improved-alpha", at=decision_at),
                    self._decision(instance="beta", identity="improved-beta", at=decision_at),
                ),
            )
        )
        parent = committed.net_orders[0]
        at = parent.order.decision_at + timedelta(seconds=1)
        improved = self._price("99")
        journal.apply_net_event(
            OrderEvent(
                identity="improved-receipt",
                order_id=parent.order.identity,
                at=at,
                kind="fill",
                fill=Fill(
                    identity="improved-physical",
                    decision_at=parent.order.decision_at,
                    filled_at=at,
                    quantity=self._quantity("4"),
                    reference=improved,
                    effective=improved,
                    fee=self._money("0"),
                ),
            )
        )
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot().cash == (self._money("49604"),)
        assert ledger.snapshot().positions == (self._quantity("4"),)
        assert ledger.snapshot(instance_id="alpha").cash == (self._money("-198"),)
        assert ledger.snapshot(instance_id="beta").cash == (self._money("-198"),)

    def test_shared_fee_correction_void_restore_and_exact_retry(self, tmp_path: Path) -> None:
        """Physical cost revisions conserve child amounts and follow current ledger IDs."""
        path = tmp_path / "fee-revision.sqlite3"
        journal = self._ready(path)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=decision_at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="fee-allocation",
                at=decision_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(instance="alpha", identity="fee-alpha", at=decision_at),
                    self._decision(instance="beta", identity="fee-beta", at=decision_at),
                ),
            )
        ).net_orders[0]
        fill_at = parent.order.decision_at + timedelta(seconds=1)
        journal.apply_net_event(
            OrderEvent(
                identity="physical-fee-receipt",
                order_id=parent.order.identity,
                at=fill_at,
                kind="fill",
                fill=self._fill(
                    "physical-cost-source", parent.order.decision_at, fill_at, "4", "0.02"
                ),
            )
        )
        for offset, total, expected_cash, expected_child_fee in (
            (1, "0.04", "49599.96", "0.02"),
            (2, "0", "49600", "0"),
            (3, "0.03", "49599.97", "0.015"),
        ):
            correction = NetFeeCorrection(
                identity=f"physical-cost-revision-{offset}",
                physical_fill_id="physical-cost-source",
                corrected_fee=self._money(total),
                known_at=fill_at + timedelta(seconds=offset),
            )
            updated = journal.correct_net_fee(correction)
            assert updated.order.paid_fee == self._money(total)
            assert journal.correct_net_fee(correction) == updated
            recovered = AccountJournal(path, self._config())
            ledger = AccountLedger(recovered.accounts()[0].ledger)
            assert ledger.snapshot().cash == (self._money(expected_cash),)
            assert ledger.snapshot().fees == (self._money(total),)
            for instance in ("alpha", "beta"):
                assert ledger.snapshot(instance_id=instance).fees == (
                    self._money(expected_child_fee),
                )
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert journal.reconcile(
            AccountObservation(
                identity="physical-cost-reconciled",
                at=fill_at + timedelta(seconds=3),
                snapshot=snapshot,
                open_orders=(),
            )
        )
        assert journal.accounts()[0].fault is None

    def test_checkpoint_compare_and_swap_and_rejected_continuation(self, tmp_path: Path) -> None:
        """Stale strategy evaluation cannot overwrite the current saved continuation."""
        journal = self._ready(tmp_path / "checkpoint.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        expected_empty = hashlib.sha256(b"").hexdigest()
        first = self._decision(instance="alpha", identity="alpha-first", at=at)
        first = replace(first, expected_checkpoint_sha256=expected_empty)
        batch = PortfolioBatch(
            identity="alpha-first-batch",
            at=at + timedelta(microseconds=1),
            decisions=(first,),
        )
        assert journal.coordinate(batch).status == "committed"
        saved_checkpoint = first.request.checkpoint
        assert journal.checkpoint("alpha") == saved_checkpoint
        assert journal.coordinate(batch).status == "committed"
        stale = self._decision(
            instance="alpha",
            identity="alpha-stale",
            at=at + timedelta(microseconds=2),
        )
        stale = replace(stale, expected_checkpoint_sha256=expected_empty)
        rejected = journal.coordinate(
            PortfolioBatch(
                identity="alpha-stale-batch",
                at=at + timedelta(microseconds=3),
                decisions=(stale,),
            )
        )
        assert (rejected.status, rejected.reason) == ("rejected", "stale_strategy_checkpoint")
        assert journal.checkpoint("alpha") == saved_checkpoint
        assert len(journal.orders()) == 1
        # Beta has no working order to replace, so its risk refusal is immediate and
        # still saves its continuation.
        fresh = self._decision(
            instance="beta",
            identity="beta-risk",
            at=at + timedelta(microseconds=2),
            quantity="90",
        )
        fresh = replace(fresh, expected_checkpoint_sha256=expected_empty)
        journal.observe(AccountQuote(price=self._price(), at=fresh.request.decision.at))
        risk_rejected = journal.coordinate(
            PortfolioBatch(
                identity="beta-risk-batch",
                at=at + timedelta(microseconds=4),
                decisions=(fresh,),
            )
        )
        assert risk_rejected.status == "rejected"
        assert risk_rejected.reason == "instance_limit"
        assert journal.checkpoint("beta") == fresh.request.checkpoint
        assert journal.checkpoint("alpha") == saved_checkpoint

    def test_old_decision_cannot_route_after_quote_expires(self, tmp_path: Path) -> None:
        """Admission-time risk alone cannot authorize a later physical send."""
        journal = self._ready(tmp_path / "late-batch.sqlite3")
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=decision_at))
        decision = self._decision(instance="alpha", identity="late-child", at=decision_at)
        result = journal.coordinate(
            PortfolioBatch(
                identity="late-batch",
                at=decision_at + timedelta(seconds=2),
                decisions=(decision,),
            )
        )
        assert (result.status, result.reason) == ("rejected", "stale_quote")
        assert journal.orders() == ()
        assert journal.net_orders() == ()
        assert journal.checkpoint("alpha") == decision.request.checkpoint

    def test_child_event_guard_and_empty_stop_clock(self, tmp_path: Path) -> None:
        """A child cannot bypass its parent; an empty stop still fences old restart time."""
        journal = self._ready(tmp_path / "child-guard.sqlite3")
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        committed = journal.coordinate(
            PortfolioBatch(
                identity="guard-parent",
                at=at + timedelta(microseconds=1),
                decisions=(self._decision(instance="alpha", identity="guard-child", at=at),),
            )
        )
        child = committed.children[0]
        with pytest.raises(ValueError, match="physical parent routing"):
            journal.apply_event(
                OrderEvent(
                    identity="direct-child-cancel",
                    order_id=child.order.identity,
                    at=at + timedelta(microseconds=2),
                    kind="cancelled",
                )
            )
        assert journal.orders()[0].order.remaining == self._quantity("2")
        assert journal.net_orders()[0].order.remaining == self._quantity("2")
        empty = self._ready(tmp_path / "empty-stop.sqlite3")
        stop_at = self.opening_at + timedelta(seconds=5)
        assert empty.stop_instance("alpha", stop_at) == ()
        assert empty.stopped_instances() == ("alpha",)
        with pytest.raises(ValueError, match="instance_restart_requires_reconciliation"):
            empty.restart_instance("alpha", stop_at)
        assert empty.reconcile(
            AccountObservation(
                identity="after-empty-stop",
                at=stop_at,
                snapshot=self._opening(),
                open_orders=(),
            )
        )
        with pytest.raises(ValueError, match="instance_restart_requires_reconciliation"):
            empty.restart_instance("alpha", stop_at - timedelta(microseconds=1))
        empty.restart_instance("alpha", stop_at)
        assert empty.stopped_instances() == ()

    def test_filled_child_fee_tail_stays_in_gross_budget(self, tmp_path: Path) -> None:
        """An attached filled child keeps unused fee capacity until parent completion."""
        base = self._config()
        instance_limits: tuple[InstanceLimit, ...] = tuple(
            replace(owner, maximum=self._money("330")) for owner in base.budgets.instances
        )
        budgets = replace(
            base.budgets,
            firm_maximum=self._money("330"),
            accounts=(AccountLimit(account_id="shared", maximum=self._money("330")),),
            instances=instance_limits,
        )
        config = replace(base, budgets=budgets)
        journal = AccountJournal(tmp_path / "fee-tail.sqlite3", config)
        assert journal.reconcile(
            AccountObservation(
                identity="opening",
                at=self.opening_at,
                snapshot=self._opening(),
                open_orders=(),
            )
        )
        at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="tail-parent",
                at=at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha",
                        identity="tail-alpha",
                        at=at,
                        quantity="1",
                        maximum_fee="20",
                    ),
                    self._decision(
                        instance="beta", identity="tail-beta", at=at, quantity="1", maximum_fee="20"
                    ),
                ),
            )
        ).net_orders[0]
        fill_at = parent.order.decision_at + timedelta(milliseconds=100)
        journal.apply_net_event(
            OrderEvent(
                identity="tail-first-receipt",
                order_id=parent.order.identity,
                at=fill_at,
                kind="fill",
                fill=self._fill(
                    "tail-first-fill",
                    parent.order.decision_at,
                    fill_at,
                    "1.999999999999999999",
                    "0",
                ),
            )
        )
        filled_child = next(child for child in journal.orders() if child.order.is_terminal)
        next_at = fill_at + timedelta(milliseconds=100)
        journal.observe(AccountQuote(price=self._price(), at=next_at))
        blocked = journal.coordinate(
            PortfolioBatch(
                identity="tail-extra-batch",
                at=next_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance=filled_child.instance_id,
                        identity="tail-extra",
                        at=next_at,
                        quantity="1",
                        maximum_fee="0",
                    ),
                ),
            )
        )
        assert (blocked.status, blocked.reason) == ("rejected", "account_limit")
        assert journal.net_orders()[0].order.remaining == self._quantity("0.000000000000000001")

    def test_stopping_a_strategy_keeps_an_unknown_direct_order_unknown(
        self, tmp_path: Path
    ) -> None:
        """A stop requests cancellation but only reconciliation resolves an unknown order."""
        journal = self._ready(tmp_path / "stop-unknown-direct.sqlite3")
        scenario = PaperExecutionScenario(
            venue="okx",
            instrument_id=self.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=self._price("0.01"),
            fee_rate=Decimal(0),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot matching",
        )
        journal.bind_paper_scenario("shared", scenario)
        decided_at = self.opening_at + timedelta(seconds=1)
        alpha = self._decision(instance="alpha", identity="alpha-buy", at=decided_at).request
        journal.observe(alpha.quote)
        order_id = journal.admit(alpha).orders[0].identity
        journal.apply_event(
            OrderEvent(
                identity="lost-ack",
                order_id=order_id,
                at=decided_at + timedelta(seconds=1),
                kind="unknown",
            )
        )
        journal.stop_instance("alpha", decided_at + timedelta(seconds=2))
        stopped = next(item.order for item in journal.orders() if item.order.identity == order_id)
        assert (stopped.status, stopped.cancel_requested) == ("unknown", True)
        beta_at = decided_at + timedelta(seconds=3)
        beta = self._decision(instance="beta", identity="beta-buy", at=beta_at).request
        journal.observe(beta.quote)
        refused = journal.admit(beta)
        assert (refused.status, refused.reason) == ("rejected", "order_outcome_unknown")
        # The touch is above the buy limit, so only a lifecycle effect could appear.
        PaperBooks.apply(
            journal,
            "shared",
            PaperMarket(
                identity="after-stop",
                at=decided_at + timedelta(seconds=4),
                bid=self._price("100.50"),
                ask=self._price("101"),
                bid_quantity=self._quantity("100"),
                ask_quantity=self._quantity("100"),
            ),
            scenario,
        )
        unmatched = next(item.order for item in journal.orders() if item.order.identity == order_id)
        assert (unmatched.status, unmatched.is_terminal) == ("unknown", False)
        journal.apply_event(
            OrderEvent(
                identity="still-open",
                order_id=order_id,
                at=decided_at + timedelta(seconds=5),
                kind="reconcile_open",
            )
        )
        reconciled = next(
            item.order for item in journal.orders() if item.order.identity == order_id
        )
        assert reconciled.status == "cancel_requested"

    def test_stopping_a_strategy_keeps_an_unknown_physical_parent_unknown(
        self, tmp_path: Path
    ) -> None:
        """A stop requests the parent's cancellation without resolving its unknown outcome."""
        journal = self._ready(tmp_path / "stop-unknown-parent.sqlite3")
        decided_at = self.opening_at + timedelta(seconds=1)
        decisions = tuple(
            self._decision(instance=name, identity=f"{name}-buy", at=decided_at)
            for name in ("alpha", "beta")
        )
        journal.observe(decisions[0].request.quote)
        parent_id = (
            journal.coordinate(
                PortfolioBatch(
                    identity="pair",
                    at=decided_at + timedelta(microseconds=1),
                    decisions=decisions,
                )
            )
            .net_orders[0]
            .order.identity
        )
        journal.apply_net_event(
            OrderEvent(
                identity="lost-ack",
                order_id=parent_id,
                at=decided_at + timedelta(seconds=1),
                kind="unknown",
            )
        )
        journal.stop_instance("alpha", decided_at + timedelta(seconds=2))
        parent = next(net.order for net in journal.net_orders() if net.order.identity == parent_id)
        assert (parent.status, parent.cancel_requested) == ("unknown", True)

    def test_a_strategy_over_its_ceiling_by_marks_alone_can_still_sell(
        self, tmp_path: Path
    ) -> None:
        """Alpha's 85 marked at 110 exceed its 9,000 ceiling: it can sell but not buy."""
        rally_at = self.opening_at + timedelta(seconds=2)
        rally = AccountQuote(price=self._price("110"), at=rally_at)
        direct = self._holding(tmp_path / "direct.sqlite3")
        direct.observe(rally)
        buy = self._decision(
            instance="alpha", identity="alpha-buy", at=rally_at, quantity="1", price="110"
        )
        refused = direct.admit(buy.request)
        assert (refused.status, refused.reason) == ("rejected", "instance_limit")
        sell = self._decision(
            instance="alpha",
            identity="alpha-sell",
            at=rally_at,
            side="sell",
            quantity="10",
            price="110",
        )
        admitted = direct.admit(sell.request)
        assert (admitted.status, admitted.reason) == ("committed", "reserved")
        coordinated = self._holding(tmp_path / "coordinated.sqlite3")
        coordinated.observe(rally)
        committed = coordinated.coordinate(
            PortfolioBatch(
                identity="alpha-sell-batch",
                at=rally_at + timedelta(microseconds=1),
                decisions=(sell,),
            )
        )
        assert committed.status == "committed"
        assert committed.net_orders[0].order.intent.quantity == self._quantity("10")

    def test_a_strategy_over_its_ceiling_does_not_freeze_its_neighbour(
        self, tmp_path: Path
    ) -> None:
        """Beta's 220 buy fits beta and the account (9,570) while alpha is over its own."""
        journal = self._holding(tmp_path / "neighbour.sqlite3")
        rally_at = self.opening_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price("110"), at=rally_at))
        committed = journal.coordinate(
            PortfolioBatch(
                identity="beta-buy-batch",
                at=rally_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="beta",
                        identity="beta-buy",
                        at=rally_at,
                        maximum_fee="0",
                        price="110",
                    ),
                ),
            )
        )
        assert committed.status == "committed"
        assert committed.net_orders[0].order.intent.quantity == self._quantity("2")

    def test_a_strategy_over_its_ceiling_holds_back_only_its_own_residual_buy(
        self, tmp_path: Path
    ) -> None:
        """Alpha's residual buy waits visibly while the account restarts and beta trades on."""
        journal = self._holding(tmp_path / "residual.sqlite3", instances=("alpha", "beta", "gamma"))
        cancelled_at = self._cancelled_pair(journal, self.opening_at + timedelta(seconds=2))
        # Marked at 110, alpha holds 9,350 and still reserves its 200 residual buy: 9,550
        # against its 9,000 ceiling, while the account (9,750) stays within 10,000.
        stop_at = cancelled_at + timedelta(seconds=1)
        stopped = journal.control(
            AccountControl(
                identity="stop-1",
                account_id="shared",
                kind="stop",
                at=stop_at,
                reason="operator protection",
            )
        )
        assert stopped.status == "applied"
        restart_at = stop_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("110"), at=restart_at))
        assert journal.reconcile(
            AccountObservation(
                identity="after-stop",
                at=restart_at,
                snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                open_orders=(),
            )
        )
        restarted = journal.control(
            AccountControl(
                identity="restart-1",
                account_id="shared",
                kind="restart",
                at=restart_at,
                expected_control_identity="stop-1",
            )
        )
        assert (restarted.status, restarted.reason) == ("applied", None)
        reissued = journal.reissue_pending("shared", restart_at + timedelta(microseconds=1))
        children = {child.order.identity: child for child in journal.orders()}
        assert [
            (children[allocation.child_order_id].instance_id, allocation.quantity)
            for parent in reissued
            for allocation in parent.allocations
        ] == [("beta", self._quantity("2"))]
        alpha_residual = next(
            child.order
            for child in journal.orders()
            if child.instance_id == "alpha" and not child.order.is_terminal
        )
        assert journal.portfolio_residuals("shared") == (
            PortfolioResidual(
                account_id="shared",
                instance_id="alpha",
                child_order_id=alpha_residual.identity,
                remaining=self._quantity("2"),
                reason="instance_limit",
            ),
        )
        # The venue refuses beta's reissued order, so beta's next decision replaces no
        # working order and is admitted at once.
        (beta_parent,) = reissued
        journal.apply_net_event(
            OrderEvent(
                identity="beta-reissue-refused",
                order_id=beta_parent.order.identity,
                at=restart_at + timedelta(microseconds=2),
                kind="rejected",
            )
        )
        # Beta's 220 buy fits beta and the account (9,550 + 200 + 220 = 9,970).
        trade_at = restart_at + timedelta(milliseconds=1)
        journal.observe(AccountQuote(price=self._price("110"), at=trade_at))
        traded = journal.coordinate(
            PortfolioBatch(
                identity="beta-more",
                at=trade_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="beta",
                        identity="beta-more",
                        at=trade_at,
                        maximum_fee="0",
                        price="110",
                    ),
                ),
            )
        )
        assert traded.status == "committed"
        assert [parent.order.intent.quantity for parent in traded.net_orders] == [
            self._quantity("2")
        ]
        assert [item.instance_id for item in journal.portfolio_residuals("shared")] == ["alpha"]

    def test_a_strategy_over_its_ceiling_does_not_block_account_restart(
        self, tmp_path: Path
    ) -> None:
        """A stopped account restarts though marks alone keep alpha over its ceiling."""
        journal = self._holding(tmp_path / "restart.sqlite3")
        stop_at = self.opening_at + timedelta(seconds=2)
        stopped = journal.control(
            AccountControl(
                identity="stop-1",
                account_id="shared",
                kind="stop",
                at=stop_at,
                reason="operator protection",
            )
        )
        assert stopped.status == "applied"
        restart_at = stop_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("110"), at=restart_at))
        assert journal.reconcile(
            AccountObservation(
                identity="after-stop",
                at=restart_at,
                snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                open_orders=(),
            )
        )
        restarted = journal.control(
            AccountControl(
                identity="restart-1",
                account_id="shared",
                kind="restart",
                at=restart_at + timedelta(microseconds=1),
                expected_control_identity="stop-1",
            )
        )
        assert (restarted.status, restarted.phase) == ("applied", "running")

    def test_a_target_enters_at_the_ask_and_exits_at_the_bid(self, tmp_path: Path) -> None:
        """Targets of 85 then 80 buy at the 100.50 ask, then sell 5 at the 99.50 bid; both fill."""
        journal = self._ready(tmp_path / "target-exit.sqlite3")
        scenario = PaperExecutionScenario(
            venue="okx",
            instrument_id=self.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=self._price("0"),
            fee_rate=Decimal(0),
            take_fraction=Decimal(1),
            gas_inapplicable_reason="off-chain spot matching",
        )
        journal.bind_paper_scenario("shared", scenario)
        touch = MarketTouch(bid=self._price("99.50"), ask=self._price("100.50"))
        orders: list[OrderIntent] = []
        holdings: list[tuple[Quantity, ...]] = []
        for step, target in enumerate(("85", "80"), start=1):
            decided_at = self.opening_at + timedelta(seconds=step)
            journal.observe(AccountQuote(price=touch.ask, at=decided_at))
            decision = self._decision(
                instance="alpha",
                identity=f"alpha-target-{target}",
                at=decided_at,
                maximum_fee="0",
                price="100.50",
            )
            request = replace(
                decision.request,
                decision=replace(
                    decision.request.decision, intent=TargetIntent(quantity=self._quantity(target))
                ),
                touch=touch,
            )
            committed = journal.coordinate(
                PortfolioBatch(
                    identity=f"alpha-target-{target}-batch",
                    at=decided_at + timedelta(microseconds=1),
                    decisions=(replace(decision, request=request),),
                )
            )
            orders.append(committed.net_orders[0].order.intent)
            PaperBooks.apply(
                journal,
                "shared",
                PaperMarket(
                    identity=f"after-target-{target}",
                    at=decided_at + timedelta(milliseconds=500),
                    bid=touch.bid,
                    ask=touch.ask,
                    bid_quantity=self._quantity("100"),
                    ask_quantity=self._quantity("100"),
                ),
                scenario,
            )
            ledger = AccountLedger(journal.accounts()[0].ledger)
            holdings.append(ledger.snapshot(instance_id="alpha").positions)
        assert orders == [
            OrderIntent(
                side="buy", quantity=self._quantity("85"), limit=touch.ask, time_in_force="ioc"
            ),
            OrderIntent(
                side="sell", quantity=self._quantity("5"), limit=touch.bid, time_in_force="ioc"
            ),
        ]
        assert holdings == [(self._quantity("85"),), (self._quantity("80"),)]

    def test_a_decision_mark_outside_its_touch_is_refused(self) -> None:
        """The valuation mark lies within the bid and ask that a target crosses."""
        request = self._decision(instance="alpha", identity="outside", at=self.opening_at).request
        with pytest.raises(ValueError, match="outside its touch"):
            AccountDecision(
                account_id=request.account_id,
                instance_id=request.instance_id,
                decision=request.decision,
                quote=request.quote,
                maximum_fee=request.maximum_fee,
                touch=MarketTouch(bid=self._price("101"), ask=self._price("102")),
            )

    def test_a_residual_whose_limit_drifted_is_held_back_and_freezes_no_one(
        self, tmp_path: Path
    ) -> None:
        """A 1.5% rally strands both residuals beyond the 1% price bound; nothing freezes.

        Alpha's 88 at 101.50 (8,932) plus its 200 residual exceed its 9,000 ceiling, and
        each residual's limit of 100 lies 148 basis points from the quote.
        """
        journal = self._holding(
            tmp_path / "drift.sqlite3",
            quantity="88",
            deviation_bps=100,
            instances=("alpha", "beta", "gamma"),
        )
        cancelled_at = self._cancelled_pair(journal, self.opening_at + timedelta(seconds=2))
        stop_at = cancelled_at + timedelta(seconds=1)
        assert (
            journal.control(
                AccountControl(
                    identity="stop-1",
                    account_id="shared",
                    kind="stop",
                    at=stop_at,
                    reason="operator protection",
                )
            ).status
            == "applied"
        )
        restart_at = stop_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("101.50"), at=restart_at))
        assert journal.reconcile(
            AccountObservation(
                identity="after-stop",
                at=restart_at,
                snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                open_orders=(),
            )
        )
        restarted = journal.control(
            AccountControl(
                identity="restart-1",
                account_id="shared",
                kind="restart",
                at=restart_at,
                expected_control_identity="stop-1",
            )
        )
        assert (restarted.status, restarted.reason) == ("applied", None)
        trade_at = restart_at + timedelta(milliseconds=1)
        journal.observe(AccountQuote(price=self._price("101.50"), at=trade_at))
        traded = journal.coordinate(
            PortfolioBatch(
                identity="beta-at-the-new-price",
                at=trade_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="beta",
                        identity="beta-new",
                        at=trade_at,
                        maximum_fee="0",
                        price="101.50",
                    ),
                ),
            )
        )
        assert (traded.status, traded.reason) == ("committed", "reserved")
        assert [
            (item.instance_id, item.reason) for item in journal.portfolio_residuals("shared")
        ] == [("alpha", "price_deviation")]
        # Alpha's residual is not this batch's, so beta's abstention reports itself: it
        # replaces beta's new order and waits for that cancellation.
        abstain_at = trade_at + timedelta(milliseconds=1)
        journal.observe(AccountQuote(price=self._price("101.50"), at=abstain_at))
        abstention = self._decision(
            instance="beta", identity="beta-abstains", at=abstain_at, price="101.50"
        )
        abstained = journal.coordinate(
            PortfolioBatch(
                identity="beta-abstains",
                at=abstain_at + timedelta(microseconds=1),
                decisions=(
                    replace(
                        abstention,
                        request=replace(
                            abstention.request,
                            decision=replace(abstention.request.decision, intent=None),
                        ),
                    ),
                ),
            )
        )
        assert (abstained.status, abstained.reason) == ("committed", "replacement_pending")

    def test_a_strategy_refused_in_a_batch_leaves_the_others_to_commit(
        self, tmp_path: Path
    ) -> None:
        """Alpha, over its ceiling at 110, is refused; beta's buy in the same batch commits."""
        journal = self._holding(tmp_path / "separate.sqlite3")
        rally_at = self.opening_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price("110"), at=rally_at))
        alpha, beta = (
            self._decision(
                instance=name,
                identity=f"{name}-buy",
                at=rally_at,
                quantity=quantity,
                maximum_fee="0",
                price="110",
            )
            for name, quantity in (("alpha", "1"), ("beta", "2"))
        )
        batch = PortfolioBatch(
            identity="mixed",
            at=rally_at + timedelta(microseconds=1),
            decisions=(alpha, beta),
        )
        committed = journal.coordinate(batch)
        assert (committed.status, committed.reason) == ("committed", "reserved")
        # An exact retry returns the durable outcome, refusal included.
        assert journal.coordinate(batch) == committed
        assert [child.instance_id for child in committed.children] == ["beta"]
        assert [parent.order.intent.quantity for parent in committed.net_orders] == [
            self._quantity("2")
        ]
        assert [(item.instance_id, item.status, item.reason) for item in committed.refused] == [
            ("alpha", "rejected", "instance_limit")
        ]
        # The refused decision's continuation is retained, as for a refused batch.
        assert journal.checkpoint("alpha") == alpha.request.checkpoint

    def test_a_residual_older_than_its_age_bound_is_retired_not_sent(self, tmp_path: Path) -> None:
        """With a 2 s residual age, reissue at 1.3 s sends both residuals; at 3 s retires them.

        Gamma's child ended with its stopped instance's share of the cancelled order.
        """
        config = self._config(("alpha", "beta", "gamma"))
        config = replace(config, budgets=replace(config.budgets, max_residual_age_us=2_000_000))
        decided_at = self.opening_at + timedelta(seconds=1)
        outcomes: list[tuple[int, list[str]]] = []
        for name, reissue_after in (
            ("young", timedelta(seconds=1.3)),
            ("old", timedelta(seconds=3)),
        ):
            journal = AccountJournal(tmp_path / f"{name}.sqlite3", config)
            assert journal.reconcile(
                AccountObservation(
                    identity="opening",
                    at=self.opening_at,
                    snapshot=self._opening(),
                    open_orders=(),
                )
            )
            self._cancelled_pair(journal, decided_at)
            reissue_at = decided_at + reissue_after
            journal.observe(AccountQuote(price=self._price(), at=reissue_at))
            assert journal.reconcile(
                AccountObservation(
                    identity="after-cancel",
                    at=reissue_at,
                    snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                    open_orders=(),
                )
            )
            reissued = journal.reissue_pending("shared", reissue_at + timedelta(microseconds=1))
            outcomes.append((len(reissued), [child.order.status for child in journal.orders()]))
            assert journal.portfolio_residuals("shared") == ()
        assert outcomes == [
            (1, ["intent", "intent", "cancelled"]),
            (0, ["cancelled", "cancelled", "cancelled"]),
        ]

    def test_opposing_strategies_under_the_reject_policy_are_refused_together(
        self, tmp_path: Path
    ) -> None:
        """Alpha's sell and beta's buy at 100 would cross, so the whole cohort is refused."""
        journal = self._holding(tmp_path / "opposing.sqlite3")
        decided_at = self.opening_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price(), at=decided_at))
        refused = journal.coordinate(
            PortfolioBatch(
                identity="opposing",
                at=decided_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha", identity="alpha-sell", at=decided_at, side="sell"
                    ),
                    self._decision(instance="beta", identity="beta-buy", at=decided_at),
                ),
                crossing="reject",
            )
        )
        assert (refused.status, refused.reason) == ("rejected", "self_trade_conflict")
        assert (refused.children, refused.refused) == ((), ())

    def test_strategies_may_share_a_decision_name_within_a_batch(self, tmp_path: Path) -> None:
        """Refusals belong to a strategy's own decision, even when names coincide."""
        rally_at = self.opening_at + timedelta(seconds=2)
        outcomes: list[tuple[str, list[str], list[str]]] = []
        for name, beta_quantity in (("one-refused", "2"), ("both-refused", "100")):
            journal = self._holding(tmp_path / f"{name}.sqlite3")
            journal.observe(AccountQuote(price=self._price("110"), at=rally_at))
            committed = journal.coordinate(
                PortfolioBatch(
                    identity=name,
                    at=rally_at + timedelta(microseconds=1),
                    decisions=tuple(
                        self._decision(
                            instance=instance,
                            identity="d",
                            at=rally_at,
                            quantity=quantity,
                            maximum_fee="0",
                            price="110",
                        )
                        for instance, quantity in (("alpha", "1"), ("beta", beta_quantity))
                    ),
                )
            )
            outcomes.append(
                (
                    committed.status,
                    [child.instance_id for child in committed.children],
                    [f"{item.instance_id}:{item.reason}" for item in committed.refused],
                )
            )
        # Alpha is over its ceiling at 110; beta's 11,000 buy exceeds the order notional.
        assert outcomes == [
            ("committed", ["beta"], ["alpha:instance_limit"]),
            ("rejected", [], ["alpha:instance_limit", "beta:order_notional_limit"]),
        ]

    def test_a_conflict_with_an_earlier_order_refuses_only_its_own_strategy(
        self, tmp_path: Path
    ) -> None:
        """Alpha's sell crosses beta's resting buy from an earlier batch; beta still decides.

        A strategy's next decision replaces its own resting order rather than crossing
        it, so the earlier order belongs to the other strategy. Beta's decision in the
        same batch replaces that buy and commits, waiting for its cancellation.
        """
        journal = self._holding(tmp_path / "earlier-conflict.sqlite3")
        first_at = self.opening_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price(), at=first_at))
        resting = journal.coordinate(
            PortfolioBatch(
                identity="beta-rests",
                at=first_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="beta",
                        identity="beta-rest",
                        at=first_at,
                        quantity="1",
                        maximum_fee="0",
                    ),
                ),
            )
        )
        assert resting.status == "committed"
        second_at = first_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price(), at=second_at))
        committed = journal.coordinate(
            PortfolioBatch(
                identity="alpha-sells-beta-buys",
                at=second_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha",
                        identity="alpha-sell",
                        at=second_at,
                        side="sell",
                        maximum_fee="0",
                    ),
                    self._decision(
                        instance="beta",
                        identity="beta-buy",
                        at=second_at,
                        quantity="1",
                        maximum_fee="0",
                    ),
                ),
            )
        )
        assert (committed.status, committed.reason, committed.children) == (
            "committed",
            "replacement_pending",
            (),
        )
        assert [(item.instance_id, item.reason) for item in committed.refused] == [
            ("alpha", "self_trade_conflict")
        ]

    def test_a_batch_whose_own_decision_outlived_the_residual_age_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """Exactly at the 2 s bound a batch still sends; one microsecond later it is refused."""
        config = self._config()
        config = replace(
            config,
            budgets=replace(
                config.budgets, max_quote_age_us=5_000_000, max_residual_age_us=2_000_000
            ),
        )
        decided_at = self.opening_at + timedelta(seconds=1)
        outcomes: list[tuple[str, str]] = []
        for name, delay in (
            ("at-bound", timedelta(seconds=2)),
            ("past-bound", timedelta(seconds=2, microseconds=1)),
        ):
            journal = AccountJournal(tmp_path / f"{name}.sqlite3", config)
            assert journal.reconcile(
                AccountObservation(
                    identity="opening",
                    at=self.opening_at,
                    snapshot=self._opening(),
                    open_orders=(),
                )
            )
            journal.observe(AccountQuote(price=self._price(), at=decided_at))
            result = journal.coordinate(
                PortfolioBatch(
                    identity=name,
                    at=decided_at + delay,
                    decisions=(self._decision(instance="alpha", identity="late", at=decided_at),),
                )
            )
            outcomes.append((result.status, result.reason))
        assert outcomes == [("committed", "reserved"), ("rejected", "expired_decision")]
