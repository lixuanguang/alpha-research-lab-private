"""Verify public quote matching through exact shared account reservations and attribution."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
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
    PaperExecutionScenario,
)
from execution import (
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    NetFeeCorrection,
    OrderDecision,
    OrderEvent,
    OrderState,
    PaperMarket,
    PortfolioBatch,
    PortfolioCommit,
    PortfolioContext,
    PortfolioDecision,
)
from execution.paper import PaperFeeSchedule
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from serialization import DomainCodec
from strategies import OrderIntent


class _ReserveBlindFeeSchedule(PaperFeeSchedule):
    """Model a defective fee schedule that ignores each order's remaining fee reserve."""

    def affordable(
        self, order: OrderState, size: Fraction, price: Price, lot: Fraction
    ) -> Fraction:
        """Return every whole lot, as a model without the reserve bound would."""
        return (size // lot) * lot


class TestAccountPaperMatching:
    """Compare modeled public fills with hand-calculated physical and child effects."""

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)

    @classmethod
    def _money(cls, value: str) -> Money:
        """Build exact quote currency for an independent paper account."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Build exact base units for a fixed public market."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Build exact quote currency per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Fund two independently limited instances in one shared spot account."""
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="shared", cash=(cls._money("1000"),)),),
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
                accounts=(AccountLimit(account_id="shared", maximum=cls._money("1000")),),
                instances=tuple(
                    InstanceLimit(
                        instance_id=instance,
                        account_id="shared",
                        maximum=cls._money("1000"),
                        instruments=(cls.dimension.instrument_id,),
                    )
                    for instance in ("alpha", "beta")
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=2000,
                max_order_notional=cls._money("1000"),
            ),
        )

    @classmethod
    def _scenario(
        cls,
        *,
        fee_rate: str = "0.005",
        entry_delay_us: int = 0,
        cancel_delay_us: int = 0,
    ) -> PaperExecutionScenario:
        """Declare a finite OKX public feed scenario with explicit off-chain gas."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=entry_delay_us,
            cancel_delay_us=cancel_delay_us,
            adverse=cls._price("0.01"),
            fee_rate=Decimal(fee_rate),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot order matching",
        )

    @classmethod
    def _market(cls, identity: str, at: datetime, *, ask_quantity: str = "3") -> PaperMarket:
        """Bound one received top-of-book snapshot by displayed touch size."""
        return PaperMarket(
            identity=identity,
            at=at,
            bid=cls._price("0.90"),
            ask=cls._price("1.00"),
            bid_quantity=cls._quantity("3"),
            ask_quantity=cls._quantity(ask_quantity),
        )

    @classmethod
    def _ready(cls, path: Path, scenario: PaperExecutionScenario) -> AccountJournal:
        """Reconcile independently supplied opening cash and bind before orders."""
        journal = AccountJournal(path, cls._config())
        journal.bind_paper_scenario("shared", scenario)
        assert journal.reconcile(
            AccountObservation(
                identity="opening",
                at=cls.opening_at,
                snapshot=AccountSnapshot(
                    account_id="shared",
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
        )
        return journal

    @classmethod
    def _decision(
        cls,
        instance_id: str,
        identity: str,
        at: datetime,
        *,
        maximum_fee: str = "0.50",
        limit: str = "1.10",
    ) -> AccountDecision:
        """Build an owned buy with a fee reserve and independent quote."""
        return AccountDecision(
            account_id="shared",
            instance_id=instance_id,
            decision=OrderDecision(
                identity=identity,
                at=at,
                intent=OrderIntent(
                    side="buy",
                    quantity=cls._quantity("3"),
                    limit=cls._price(limit),
                    time_in_force="gtc",
                ),
            ),
            quote=AccountQuote(price=cls._price("1.00"), at=at),
            maximum_fee=cls._money(maximum_fee),
            checkpoint=identity.encode(),
        )

    @classmethod
    def _order(
        cls,
        identity: str,
        at: datetime,
        *,
        side: Literal["buy", "sell"],
        quantity: str,
        limit: str,
        time_in_force: Literal["gtc", "ioc"],
        maximum_fee: str,
    ) -> AccountDecision:
        """Build one owned alpha order with an explicit side, lifetime and fee reserve."""
        return AccountDecision(
            account_id="shared",
            instance_id="alpha",
            decision=OrderDecision(
                identity=identity,
                at=at,
                intent=OrderIntent(
                    side=side,
                    quantity=cls._quantity(quantity),
                    limit=cls._price(limit),
                    time_in_force=time_in_force,
                ),
            ),
            quote=AccountQuote(price=cls._price("1.00"), at=at),
            maximum_fee=cls._money(maximum_fee),
            checkpoint=identity.encode(),
        )

    @classmethod
    def _coordinate_two(cls, journal: AccountJournal, at: datetime) -> PortfolioCommit:
        """Create one compatible physical parent with two independent owners."""
        decisions = tuple(
            PortfolioDecision(
                request=cls._decision(instance, f"{instance}-decision", at),
                context=PortfolioContext(
                    portfolio_id="reference",
                    strategy_id=instance,
                    model_revision="v1",
                    config_revision="v1",
                    horizon="one-minute",
                    reason="paper-acceptance",
                    venue="OKX",
                    settlement="spot-immediate",
                    risk_bucket="spot",
                    authority_scope="paper",
                ),
            )
            for instance in ("alpha", "beta")
        )
        return journal.coordinate(
            PortfolioBatch(
                identity="shared-batch",
                at=at + timedelta(microseconds=1),
                decisions=decisions,
            )
        )

    def test_direct_fill_trace_liquidity_debt_restart_and_reporting(self, tmp_path: Path) -> None:
        """Same-price quotes only add displayed peak and repeated input adds nothing."""
        path = tmp_path / "direct-paper.sqlite3"
        scenario = self._scenario()
        journal = self._ready(path, scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        admitted = journal.admit(self._decision("alpha", "direct", decision_at))
        assert admitted.status == "committed"
        first_market = self._market("book-1", decision_at + timedelta(seconds=1), ask_quantity="2")
        first = journal.match_public_market("shared", first_market, scenario)
        assert tuple(event.kind for event in first.physical_events) == (
            "request_ack",
            "accepted",
            "fill",
        )
        assert tuple(
            event.fill.quantity.value for event in first.child_fill_events if event.fill
        ) == (Decimal("2"),)
        second_market = self._market("book-2", decision_at + timedelta(seconds=2))
        second = journal.match_public_market("shared", second_market, scenario)
        assert tuple(event.kind for event in second.physical_events) == ("fill",)
        assert journal.orders()[0].order.status == "filled"
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.cash == (self._money("996.95485"),)
        assert snapshot.positions == (self._quantity("3"),)
        assert snapshot.fees == (self._money("0.01515"),)
        assert journal.match_public_market("shared", second_market, scenario) == second
        with pytest.raises(ValueError, match="identity reused"):
            journal.match_public_market(
                "shared", replace(second_market, ask_quantity=self._quantity("4")), scenario
            )
        with pytest.raises(ValueError, match="availability regressed"):
            journal.match_public_market(
                "shared",
                self._market("late-old-book", first_market.at + timedelta(microseconds=1)),
                scenario,
            )
        third = journal.match_public_market(
            "shared", self._market("book-3", decision_at + timedelta(seconds=3)), scenario
        )
        assert third.physical_events == ()
        restarted = AccountJournal(path, self._config())
        assert restarted.paper_traces("shared") == (first, second, third)
        assert restarted.match_public_market("shared", first_market, scenario) == first
        assert AccountLedger(restarted.accounts()[0].ledger).snapshot() == snapshot
        fills, costs = restarted.paper_report_facts("shared")
        assert tuple(fill.fill.quantity.value for fill in fills) == (Decimal("2"), Decimal("1"))
        assert tuple(cost.amount.value for cost in costs) == (
            Decimal("0.0101"),
            Decimal("0.00505"),
        )
        assert tuple(fill.instance_id for fill in fills) == ("alpha", "alpha")

    def test_net_parent_allocates_one_finite_public_fill_to_both_strategies(
        self, tmp_path: Path
    ) -> None:
        """Physical fills and cents reconcile exactly to tagged child ledgers."""
        scenario = self._scenario()
        journal = self._ready(tmp_path / "net-paper.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        committed = self._coordinate_two(journal, decision_at)
        assert committed.status == "committed" and len(committed.net_orders) == 1
        market = self._market("net-book", decision_at + timedelta(seconds=1))
        trace = journal.match_public_market("shared", market, scenario)
        assert tuple(event.kind for event in trace.physical_events) == (
            "request_ack",
            "accepted",
            "fill",
        )
        physical_fill = trace.physical_events[-1].fill
        assert physical_fill is not None and physical_fill.quantity == self._quantity("3")
        assert (
            sum(event.fill.quantity.value for event in trace.child_fill_events if event.fill) == 3
        )
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot().positions == (self._quantity("3"),)
        assert ledger.snapshot().fees == (self._money("0.01515"),)
        assert sum(
            ledger.snapshot(instance_id=instance).positions[0].value
            for instance in ("alpha", "beta")
        ) == Decimal("3")
        fills, costs = journal.paper_report_facts("shared")
        assert {fill.instance_id for fill in fills} == {"alpha", "beta"}
        assert sum(cost.amount.value for cost in costs) == Decimal("0.01515")
        assert journal.match_public_market("shared", market, scenario) == trace
        journal.correct_net_fee(
            NetFeeCorrection(
                identity="paper-fee-void",
                physical_fill_id=physical_fill.identity,
                corrected_fee=self._money("0"),
                known_at=market.at + timedelta(seconds=1),
            )
        )
        corrected_fills, corrected_costs = journal.paper_report_facts("shared")
        assert corrected_fills == fills
        assert all(cost.posting_id is None and cost.amount.value == 0 for cost in corrected_costs)

    def test_independent_reconciliation_rejects_wrong_physical_cumulative(
        self, tmp_path: Path
    ) -> None:
        """Hand-authored cash, fee and order facts reject a bad parent observation."""
        scenario = self._scenario()
        journal = self._ready(tmp_path / "reconciled-net-paper.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        committed = self._coordinate_two(journal, decision_at)
        assert committed.status == "committed" and len(committed.net_orders) == 1
        parent = committed.net_orders[0]
        market = self._market("reconciled-net-book", decision_at + timedelta(seconds=1))
        journal.match_public_market("shared", market, scenario)

        # Compute identities from the declared source and allocation contracts,
        # while cash, position, fees and parent cumulative are independent goldens.
        codec = DomainCodec()
        physical_fill_id = hashlib.sha256(
            codec.encode_json(
                (
                    "paper-match",
                    "shared",
                    scenario.identity,
                    market.identity,
                    parent.order.identity,
                    "fill",
                )
            )
        ).hexdigest()
        child_fill_ids = tuple(
            hashlib.sha256(
                codec.encode_json(
                    ("allocated-physical-fill", physical_fill_id, item.child_order_id)
                )
            ).hexdigest()
            for item in parent.allocations
        )
        posting_ids = (
            "opening:USDT",
            *(
                posting_id
                for fill_id in child_fill_ids
                for posting_id in (fill_id, f"fee:{fill_id}")
            ),
        )
        expected_snapshot = AccountSnapshot(
            account_id="shared",
            instance_id=None,
            cash=(self._money("996.95485"),),
            positions=(self._quantity("3"),),
            fees=(self._money("0.01515"),),
            rebates=(self._money("0"),),
            transfers=(self._money("1000"),),
            fill_ids=child_fill_ids,
            posting_ids=posting_ids,
        )
        expected_parent = replace(
            parent.order,
            status="partial",
            filled=self._quantity("3"),
            paid_fee=self._money("0.01515"),
            request_acknowledged=True,
            accepted=True,
        )
        assert not journal.reconcile(
            AccountObservation(
                identity="incorrect-paper-parent",
                at=market.at + timedelta(microseconds=1),
                snapshot=expected_snapshot,
                open_orders=(replace(expected_parent, filled=self._quantity("2")),),
            )
        )
        assert journal.accounts()[0].fault == "account_break"
        assert journal.reconcile(
            AccountObservation(
                identity="independent-paper-parent",
                at=market.at + timedelta(microseconds=2),
                snapshot=expected_snapshot,
                open_orders=(expected_parent,),
            )
        )
        assert journal.accounts()[0].fault is None
        assert AccountLedger(journal.accounts()[0].ledger).snapshot() == expected_snapshot

    def test_cancel_delay_and_unknown_reservations_survive_restart(self, tmp_path: Path) -> None:
        """Only a later eligible quote confirms cancel; unknown never auto-fills."""
        path = tmp_path / "delayed-cancel.sqlite3"
        scenario = self._scenario(cancel_delay_us=1_000_000)
        journal = self._ready(path, scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        for instance in ("alpha", "beta"):
            admitted = journal.admit(
                self._decision(instance, f"{instance}-resting", decision_at, limit="0.95")
            )
            assert admitted.status == "committed"
        accepted_at = decision_at + timedelta(seconds=1)
        journal.match_public_market("shared", self._market("resting", accepted_at), scenario)
        by_instance = {item.instance_id: item.order for item in journal.orders()}
        assert {name: order.status for name, order in by_instance.items()} == {
            "alpha": "accepted",
            "beta": "accepted",
        }
        request_at = accepted_at + timedelta(seconds=1)
        journal.apply_event(
            OrderEvent(
                identity="alpha-cancel-request",
                order_id=by_instance["alpha"].identity,
                at=request_at,
                kind="cancel_requested",
            )
        )
        journal.apply_event(
            OrderEvent(
                identity="beta-unknown",
                order_id=by_instance["beta"].identity,
                at=request_at,
                kind="unknown",
            )
        )
        early = journal.match_public_market(
            "shared",
            self._market("cancel-early", request_at + timedelta(microseconds=500_000)),
            scenario,
        )
        assert early.physical_events == ()
        reopened = AccountJournal(path, self._config())
        due = reopened.match_public_market(
            "shared", self._market("cancel-due", request_at + timedelta(seconds=1)), scenario
        )
        assert tuple(event.kind for event in due.physical_events) == ("cancelled",)
        statuses = {item.instance_id: item.order.status for item in reopened.orders()}
        assert statuses == {"alpha": "cancelled", "beta": "unknown"}
        assert tuple(order.identity for order in reopened.physical_open_orders("shared")) == (
            by_instance["beta"].identity,
        )
        assert reopened.paper_traces("shared")[-1] == due

    def test_capped_ioc_buy_fills_only_what_its_fee_reserve_pays(self, tmp_path: Path) -> None:
        """An admitted buy whose full fill costs more than its reserve fills the affordable lots."""
        scenario = self._scenario(fee_rate="0.10")
        journal = self._ready(tmp_path / "capped-buy.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        admitted = journal.admit(
            self._order(
                "capped-buy",
                decision_at,
                side="buy",
                quantity="3",
                limit="1.10",
                time_in_force="ioc",
                maximum_fee="0.21",
            )
        )
        assert admitted.status == "committed"
        # At 1.01 after adverse cost each unit pays 0.101, so 0.21 covers two units.
        market = self._market("capped-book", decision_at + timedelta(seconds=1))
        trace = journal.match_public_market("shared", market, scenario)
        assert trace.status == "committed"
        fills = [event.fill for event in trace.physical_events if event.fill is not None]
        assert [(fill.quantity.value, fill.fee.value) for fill in fills] == [
            (Decimal("2"), Decimal("0.202"))
        ]
        order = journal.orders()[0].order
        assert (order.status, order.filled.value) == ("cancelled", Decimal("2"))
        assert order.paid_fee.value <= order.maximum_fee.value
        assert journal.accounts()[0].fault is None

    def test_sell_filling_above_its_limit_cancels_its_unfillable_remainder(
        self, tmp_path: Path
    ) -> None:
        """A fill above the limit that leaves too little reserve for one more lot ends the order."""
        scenario = self._scenario(fee_rate="0.10")
        journal = self._ready(tmp_path / "capped-sell.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        bought = journal.admit(
            self._order(
                "inventory",
                decision_at,
                side="buy",
                quantity="3",
                limit="1.10",
                time_in_force="ioc",
                maximum_fee="0.50",
            )
        )
        assert bought.status == "committed"
        inventory = self._market("inventory-book", decision_at + timedelta(seconds=1))
        journal.match_public_market("shared", inventory, scenario)
        sell_at = decision_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price("1.00"), at=sell_at))
        # Two units at the 0.85 limit cost exactly 0.17 in fees.
        sold = journal.admit(
            self._order(
                "limit-sized-sell",
                sell_at,
                side="sell",
                quantity="2",
                limit="0.85",
                time_in_force="gtc",
                maximum_fee="0.17",
            )
        )
        assert sold.status == "committed"
        # The 0.90 bid fills at 0.89 after adverse cost: 0.089 per unit, so one unit fits.
        market = self._market("sell-book", sell_at + timedelta(seconds=1))
        trace = journal.match_public_market("shared", market, scenario)
        fills = [event.fill for event in trace.physical_events if event.fill is not None]
        assert [(fill.quantity.value, fill.fee.value) for fill in fills] == [
            (Decimal("-1"), Decimal("0.089"))
        ]
        order = next(
            item.order
            for item in journal.orders()
            if item.order.decision_identity == "limit-sized-sell"
        )
        # 0.081 is left, below the 0.085 fee of one unit even at the limit, so the
        # remainder can never fill: it is cancelled instead of reserved forever.
        assert [event.kind for event in trace.physical_events][-1] == "cancelled"
        assert (order.status, order.filled.value) == ("cancelled", Decimal("1"))
        assert order.paid_fee.value <= order.maximum_fee.value
        assert journal.accounts()[0].fault is None

    def test_sell_reserved_below_one_lot_fee_is_cancelled_but_a_buy_rests(
        self, tmp_path: Path
    ) -> None:
        """Only a sell's cheapest fee is known (at its limit); a buy may still fill lower."""
        scenario = self._scenario(fee_rate="0.10")
        journal = self._ready(tmp_path / "unfillable.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        inventory = self._order(
            "inventory",
            decision_at,
            side="buy",
            quantity="3",
            limit="1.10",
            time_in_force="ioc",
            maximum_fee="0.50",
        )
        assert journal.admit(inventory).status == "committed"
        journal.match_public_market(
            "shared", self._market("inventory-book", decision_at + timedelta(seconds=1)), scenario
        )
        # One unit at the 0.85 limit costs 0.085; at 1.01 a buy unit costs 0.101.
        # The sell goes first: a resting buy at 1.10 would be a self-trade.
        phases: tuple[tuple[str, Literal["buy", "sell"], str], ...] = (
            ("thin-sell", "sell", "0.85"),
            ("thin-buy", "buy", "1.10"),
        )
        for step, (identity, side, limit) in enumerate(phases):
            at = decision_at + timedelta(seconds=2 + 2 * step)
            journal.observe(AccountQuote(price=self._price("1.00"), at=at))
            decision = self._order(
                identity,
                at,
                side=side,
                quantity="2",
                limit=limit,
                time_in_force="gtc",
                maximum_fee="0.08",
            )
            assert journal.admit(decision).status == "committed"
            market = self._market(f"{identity}-book", at + timedelta(seconds=1))
            journal.match_public_market("shared", market, scenario)
            (order,) = (
                item.order for item in journal.orders() if item.order.decision_identity == identity
            )
            expected = "cancelled" if side == "sell" else "accepted"
            assert (order.status, order.filled.value) == (expected, Decimal("0"))
        assert journal.accounts()[0].fault is None

    def test_fee_cap_failure_blocks_without_partial_lifecycle_or_economics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reserve-blind model's unaffordable fill is refused and rolled back whole."""
        monkeypatch.setattr("execution.paper.PaperFeeSchedule", _ReserveBlindFeeSchedule)
        scenario = self._scenario(fee_rate="0.10")
        journal = self._ready(tmp_path / "fee-cap.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        admitted = journal.admit(self._decision("alpha", "fee-cap", decision_at, maximum_fee="0"))
        assert admitted.status == "committed"
        before = AccountLedger(journal.accounts()[0].ledger).snapshot()
        market = self._market("fee-cap-book", decision_at + timedelta(seconds=1))
        assert journal.paper_market_seen("shared", market.identity) is False
        with pytest.raises(ValueError, match="account blocked"):
            journal.match_public_market("shared", market, scenario)
        reopened = AccountJournal(journal.path, self._config())
        assert AccountLedger(reopened.accounts()[0].ledger).snapshot() == before
        assert reopened.orders()[0].order.status == "intent"
        assert reopened.accounts()[0].fault == "order_event_break"
        (trace,) = reopened.paper_traces("shared")
        assert trace.status == "failed" and trace.physical_events == ()
        assert journal.paper_market_seen("shared", market.identity) is True
        assert reopened.paper_market_seen("shared", market.identity) is True
        assert trace.rejected_event is not None and trace.rejected_event.kind == "fill"
        with pytest.raises(ValueError, match="account blocked"):
            reopened.match_public_market("shared", market, scenario)
