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
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk.budgets import AccountLimit, BudgetPolicy, InstanceLimit
from risk.spot import SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent, QuoteIntent, TargetIntent


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
    def _config(cls) -> AccountConfiguration:
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
                    for name in ("alpha", "beta")
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
    def _ready(cls, path: Path) -> AccountJournal:
        """Open and independently reconcile one paper account."""
        journal = AccountJournal(path, cls._config())
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
        cls, path: Path, *, quantity: str = "85", deviation_bps: int = 1000
    ) -> AccountJournal:
        """Leave alpha holding ``quantity`` bought at 100, by default 85 with 10% price checks.

        Marked at 110, 85 are worth 9,350: over alpha's 9,000 ceiling with no new
        order, while the account and firm ceilings (10,000 each) still hold.
        """
        config = cls._config()
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
        """Leave alpha and beta each a residual buy of 2 at 100 and return its cancellation."""
        journal.observe(AccountQuote(price=cls._price(), at=at))
        parent = journal.coordinate(
            PortfolioBatch(
                identity="pair",
                at=at + timedelta(microseconds=1),
                decisions=tuple(
                    cls._decision(instance=name, identity=f"{name}-buy", at=at, maximum_fee="0")
                    for name in ("alpha", "beta")
                ),
            )
        ).net_orders[0]
        cancel_at = at + timedelta(seconds=1)
        journal.control(
            AccountControl(identity="cancel-pair", account_id="shared", kind="cancel", at=cancel_at)
        )
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
        """Abstaining or deciding again cancels the instance's orders; a rejection does not."""
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
                identity="alpha-too-large",
                at=second_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha", identity="alpha-big", at=second_at, quantity="200"
                    ),
                ),
            )
        )
        assert refused.status == "rejected"
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
        assert (abstained.status, abstained.reason) == ("committed", "no_intent")
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
    def _bound(cls, path: Path) -> AccountJournal:
        """Bind the delayed scenario, then independently reconcile opening cash."""
        journal = AccountJournal(path, cls._config())
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

    def test_an_order_expiring_under_a_pending_account_cancel_ends_its_child(
        self, tmp_path: Path
    ) -> None:
        """An IOC that expires before an account cancel takes effect is never re-sent.

        Entry takes 1 ms and cancellation 5 ms. The account cancel at +2 ms is still
        pending at the +3 ms book, whose 101 ask is above the 100 limit, so the IOC
        expires on its own terms. Nothing is left to reissue: the next batch on the
        account sends nothing, and a later book at the limit leaves the account exactly
        at its opening cash.
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
        assert sent.status == "committed" and len(sent.net_orders) == 1
        cancel = journal.control(
            AccountControl(
                identity="operator-cancel",
                account_id="shared",
                kind="cancel",
                at=at + timedelta(milliseconds=2),
            )
        )
        assert cancel.status == "applied"
        expiry = journal.match_public_market(
            "shared", self._book("expiry", at + timedelta(milliseconds=3), "101"), scenario
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
        journal.match_public_market(
            "shared", self._book("at-limit", next_at + timedelta(milliseconds=3), "100"), scenario
        )
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == self._opening()

    def test_a_shared_order_expiring_after_another_strategy_replaces_ends_both_children(
        self, tmp_path: Path
    ) -> None:
        """Alpha's replacement requests the shared IOC's cancel; the IOC expires first.

        The +3 ms book (ask 101 above the 100 limit) ends the parent on its own terms,
        before alpha's +2 ms request takes effect at +7 ms. Beta's child ends with it,
        so alpha's next order needs no newer reconciliation. At the +10 ms book, ten
        units at the 100 limit fill alpha's new two-unit IOC: alpha holds 2, beta 0.
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
        assert pair.status == "committed" and len(pair.net_orders) == 1
        replace_at = at + timedelta(milliseconds=2)
        journal.observe(AccountQuote(price=self._price(), at=replace_at))
        replaced = journal.coordinate(
            PortfolioBatch(
                identity="alpha-replaces",
                at=replace_at + timedelta(microseconds=1),
                decisions=(self._abstention("alpha", "alpha-abstains", replace_at),),
            )
        )
        assert (replaced.status, replaced.reason) == ("committed", "no_intent")
        assert journal.net_orders()[0].order.cancel_requested
        expiry = journal.match_public_market(
            "shared", self._book("expiry", replace_at + timedelta(milliseconds=1), "101"), scenario
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
        assert bought.status == "committed", bought.reason
        assert [parent.order.intent.quantity for parent in bought.net_orders] == [
            self._quantity("2")
        ]
        journal.match_public_market(
            "shared", self._book("at-limit", buy_at + timedelta(milliseconds=3), "100"), scenario
        )
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot(instance_id="alpha").positions == (self._quantity("2"),)
        assert ledger.snapshot(instance_id="beta").positions == ()

    def test_a_post_only_order_rejected_under_a_pending_cancel_ends_its_children(
        self, tmp_path: Path
    ) -> None:
        """A shared post-only buy crossing at its first eligible book is rejected outright.

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
        assert pair.status == "committed" and len(pair.net_orders) == 1
        replace_at = at + timedelta(milliseconds=2)
        journal.observe(AccountQuote(price=self._price(), at=replace_at))
        journal.coordinate(
            PortfolioBatch(
                identity="alpha-replaces",
                at=replace_at + timedelta(microseconds=1),
                decisions=(self._abstention("alpha", "alpha-abstains", replace_at),),
            )
        )
        crossed = journal.match_public_market(
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

        Both resting buys sit below the 101 ask. Alpha's stop at +3 ms requests the
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
        parent_id = pair.net_orders[0].order.identity
        resting = journal.match_public_market(
            "shared", self._book("resting", at + timedelta(milliseconds=2), "101"), scenario
        )
        assert [event.kind for event in resting.physical_events] == ["request_ack", "accepted"]
        stop_at = at + timedelta(milliseconds=3)
        assert [parent.order.identity for parent in journal.stop_instance("alpha", stop_at)] == [
            parent_id
        ]
        early = journal.match_public_market(
            "shared", self._book("early", stop_at + timedelta(milliseconds=4), "101"), scenario
        )
        assert early.physical_events == ()
        due_at = stop_at + timedelta(milliseconds=5)
        due = journal.match_public_market("shared", self._book("due", due_at, "101"), scenario)
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
        fresh = self._decision(
            instance="alpha",
            identity="alpha-risk",
            at=at + timedelta(microseconds=2),
            quantity="90",
        )
        fresh = replace(
            fresh, expected_checkpoint_sha256=hashlib.sha256(saved_checkpoint).hexdigest()
        )
        journal.observe(AccountQuote(price=self._price(), at=fresh.request.decision.at))
        risk_rejected = journal.coordinate(
            PortfolioBatch(
                identity="alpha-risk-batch",
                at=at + timedelta(microseconds=4),
                decisions=(fresh,),
            )
        )
        assert risk_rejected.status == "rejected"
        assert risk_rejected.reason == "instance_limit"
        assert journal.checkpoint("alpha") == fresh.request.checkpoint

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
        journal.match_public_market(
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
        journal = self._holding(tmp_path / "residual.sqlite3")
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
            journal.match_public_market(
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
        journal = self._holding(tmp_path / "drift.sqlite3", quantity="88", deviation_bps=100)
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
        # Alpha's residual is not this batch's, so beta's abstention reports itself.
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
        assert (abstained.status, abstained.reason) == ("committed", "no_intent")

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
        """With a 2 s residual age, reissue at 1.3 s sends both residuals; at 3 s retires them."""
        config = self._config()
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
        assert outcomes == [(1, ["intent", "intent"]), (0, ["cancelled", "cancelled"])]

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
        """Alpha's sell crosses its own resting buy from an earlier batch; beta still trades."""
        journal = self._holding(tmp_path / "earlier-conflict.sqlite3")
        first_at = self.opening_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price(), at=first_at))
        resting = journal.coordinate(
            PortfolioBatch(
                identity="alpha-rests",
                at=first_at + timedelta(microseconds=1),
                decisions=(
                    self._decision(
                        instance="alpha", identity="alpha-buy", at=first_at, maximum_fee="0"
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
        assert (committed.status, [child.instance_id for child in committed.children]) == (
            "committed",
            ["beta"],
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
