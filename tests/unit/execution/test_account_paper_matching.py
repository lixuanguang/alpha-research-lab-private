"""Verify public quote matching through exact shared account reservations and attribution."""

from __future__ import annotations

# standard library imports
import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal, cast

# third party library imports
import pytest
from msgspec.structs import replace
from paper_books import PaperBooks

# project library imports
from accounting import AccountLedger, AccountSnapshot
from configuration import (
    AccountConfiguration,
    OpeningAccount,
    PaperExecutionScenario,
)
from configuration.accounts import InstrumentFeeRate
from execution import (
    AccountControl,
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


class _OverchargingFeeSchedule(_ReserveBlindFeeSchedule):
    """Model a defective fee schedule that also charges ten times its own rate."""

    def fee(self, size: Fraction, price: Price) -> Money:
        """Charge ten times the modeled fee, beyond any reserve sized for the rate."""
        modeled = super().fee(size, price)
        return Money(value=modeled.value * 10, currency=modeled.currency)


class AccountHistoryProbe:
    """Read a journal's committed head bytes; equal bytes mean no commit wrote."""

    @staticmethod
    def head(path: Path) -> bytes:
        """Return the committed firm head's bytes."""
        with closing(sqlite3.connect(path)) as connection:
            row = cast(tuple[bytes], connection.execute("SELECT payload FROM firm").fetchone())
        return row[0]


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
        spot_limits: tuple[SpotLimits, ...] = (
            SpotLimits(
                maximum=cls._quantity("10"),
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
                    instrument_id=limits.maximum.dimension.instrument_id, rate=Decimal("0.10")
                )
                for limits in spot_limits
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
                max_residual_age_us=86_400_000_000,
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
    def _context(cls, instance: str) -> PortfolioContext:
        """Tag one instance's decision for netting in the shared reference portfolio."""
        return PortfolioContext(
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
        )

    @classmethod
    def _coordinate_two(cls, journal: AccountJournal, at: datetime) -> PortfolioCommit:
        """Create one compatible physical parent with two independent owners."""
        decisions = tuple(
            PortfolioDecision(
                request=cls._decision(instance, f"{instance}-decision", at),
                context=cls._context(instance),
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
        first = PaperBooks.apply(journal, "shared", first_market, scenario)
        assert tuple(event.kind for event in first.physical_events) == (
            "request_ack",
            "accepted",
            "fill",
        )
        assert tuple(
            event.fill.quantity.value for event in first.child_fill_events if event.fill
        ) == (Decimal("2"),)
        second_market = self._market("book-2", decision_at + timedelta(seconds=2))
        second = PaperBooks.apply(journal, "shared", second_market, scenario)
        assert tuple(event.kind for event in second.physical_events) == ("fill",)
        assert journal.orders()[0].order.status == "filled"
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.cash == (self._money("996.95485"),)
        assert snapshot.positions == (self._quantity("3"),)
        assert snapshot.fees == (self._money("0.01515"),)
        assert PaperBooks.apply(journal, "shared", second_market, scenario) == second
        with pytest.raises(ValueError, match="identity reused"):
            PaperBooks.apply(
                journal,
                "shared",
                replace(second_market, ask_quantity=self._quantity("4")),
                scenario,
            )
        with pytest.raises(ValueError, match="availability regressed"):
            PaperBooks.apply(
                journal,
                "shared",
                self._market("late-old-book", first_market.at + timedelta(microseconds=1)),
                scenario,
            )
        third = PaperBooks.apply(
            journal, "shared", self._market("book-3", decision_at + timedelta(seconds=3)), scenario
        )
        assert third.physical_events == ()
        restarted = AccountJournal(path, self._config())
        assert restarted.paper_traces("shared") == (first, second, third)
        assert PaperBooks.apply(restarted, "shared", first_market, scenario) == first
        assert AccountLedger(restarted.accounts()[0].ledger).snapshot() == snapshot
        fills, costs = restarted.paper_report_facts("shared")
        assert tuple(fill.fill.quantity.value for fill in fills) == (Decimal("2"), Decimal("1"))
        assert tuple(cost.amount.value for cost in costs) == (
            Decimal("0.0101"),
            Decimal("0.00505"),
        )
        assert tuple(fill.instance_id for fill in fills) == ("alpha", "alpha")

    def test_one_command_resolves_history_before_any_effect(self, tmp_path: Path) -> None:
        """Any earlier book retries without a write; reused input or order is refused whole.

        A resting buy fills two of its three units at the first book. Three books with
        asks 1.00, 1.01 and 1.02 leave 1.02 as valuation. Retrying the first returns its
        saved outcome and leaves the committed head, and so valuation, liquidity,
        ledgers and checkpoints, byte for byte. A changed first book, an older new book,
        and a new book at the latest clock whose ask differs from the valuation are each
        refused before or with their matching, which is rolled back.
        """
        scenario = self._scenario()
        path = tmp_path / "history-retry.sqlite3"
        journal = self._ready(path, scenario)
        start = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=start))
        assert journal.admit(self._decision("alpha", "resting", start)).status == "committed"
        books = tuple(
            replace(
                self._market(f"history-book-{index}", start + timedelta(seconds=1 + index)),
                ask=self._price(f"1.0{index}"),
                ask_quantity=self._quantity("2" if index == 0 else "3"),
            )
            for index in range(3)
        )
        outcomes = tuple(journal.apply_public_market("shared", book, scenario) for book in books)
        first = journal.paper_trace("shared", books[0].identity)
        assert first is not None and len(first.child_fill_events) == 1
        assert (
            outcomes[0].trace_sha256 == hashlib.sha256(DomainCodec().encode_json(first)).hexdigest()
        )
        valuation = AccountQuote(price=books[2].ask, at=books[2].at)
        assert journal.valuation(self.dimension) == valuation
        head = AccountHistoryProbe.head(path)

        assert journal.apply_public_market("shared", books[0], scenario) == outcomes[0]
        reopened = AccountJournal(path, self._config())
        assert reopened.apply_public_market("shared", books[1], scenario) == outcomes[1]
        assert AccountHistoryProbe.head(path) == head
        assert reopened.valuation(self.dimension) == valuation

        with pytest.raises(ValueError, match="identity reused with different input"):
            journal.apply_public_market(
                "shared", replace(books[0], bid_quantity=self._quantity("4")), scenario
            )
        with pytest.raises(ValueError, match="availability regressed"):
            journal.apply_public_market(
                "shared", self._market("older-new-book", books[1].at), scenario
            )
        with pytest.raises(ValueError, match="valuation clock regressed or changed"):
            journal.apply_public_market(
                "shared", self._market("same-clock-other-ask", books[2].at), scenario
            )
        assert AccountHistoryProbe.head(path) == head
        assert reopened.paper_trace("shared", "same-clock-other-ask") is None

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
        trace = PaperBooks.apply(journal, "shared", market, scenario)
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
        assert PaperBooks.apply(journal, "shared", market, scenario) == trace
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
        PaperBooks.apply(journal, "shared", market, scenario)

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
        PaperBooks.apply(journal, "shared", self._market("resting", accepted_at), scenario)
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
        early = PaperBooks.apply(
            journal,
            "shared",
            self._market("cancel-early", request_at + timedelta(microseconds=500_000)),
            scenario,
        )
        assert early.physical_events == ()
        reopened = AccountJournal(path, self._config())
        due = PaperBooks.apply(
            reopened,
            "shared",
            self._market("cancel-due", request_at + timedelta(seconds=1)),
            scenario,
        )
        assert tuple(event.kind for event in due.physical_events) == ("cancelled_on_request",)
        statuses = {item.instance_id: item.order.status for item in reopened.orders()}
        assert statuses == {"alpha": "cancelled", "beta": "unknown"}
        assert tuple(order.identity for order in reopened.physical_open_orders("shared")) == (
            by_instance["beta"].identity,
        )
        assert reopened.paper_traces("shared")[-1] == due

    def test_scenario_charging_above_the_configured_worst_case_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Reserves are sized for the configured rate, so no scenario may charge more."""
        with pytest.raises(ValueError, match="exceeds the configured worst case"):
            self._ready(tmp_path / "over-rate.sqlite3", self._scenario(fee_rate="0.11"))

    def test_reserve_below_the_worst_case_fee_is_refused_at_admission(self, tmp_path: Path) -> None:
        """A reserve below the configured rate on the whole order at its limit is refused."""
        scenario = self._scenario(fee_rate="0.10")
        journal = self._ready(tmp_path / "sized-buy.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        # Three units at the 1.10 limit cost 0.33 at the configured 0.10 worst case.
        refused = journal.admit(
            self._order(
                "under-reserved-buy",
                decision_at,
                side="buy",
                quantity="3",
                limit="1.10",
                time_in_force="ioc",
                maximum_fee="0.33",
            )
        )
        assert (refused.status, refused.reason) == ("rejected", "fee_reserve_below_worst_case")
        admitted = journal.admit(
            self._order(
                "sized-buy",
                decision_at,
                side="buy",
                quantity="3",
                limit="1.10",
                time_in_force="ioc",
                maximum_fee="0.34",
            )
        )
        assert admitted.status == "committed"
        # A buy never fills above its limit, so the reserve pays every lot.
        market = self._market("sized-book", decision_at + timedelta(seconds=1))
        trace = PaperBooks.apply(journal, "shared", market, scenario)
        fills = [event.fill for event in trace.physical_events if event.fill is not None]
        assert [(fill.quantity.value, fill.fee.value) for fill in fills] == [
            (Decimal("3"), Decimal("0.303"))
        ]
        assert journal.orders()[-1].order.status == "filled"
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
        PaperBooks.apply(journal, "shared", inventory, scenario)
        sell_at = decision_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price("1.00"), at=sell_at))
        # The floor: 0.17 for two units at the 0.85 limit, plus one minor unit per lot.
        sold = journal.admit(
            self._order(
                "limit-sized-sell",
                sell_at,
                side="sell",
                quantity="2",
                limit="0.85",
                time_in_force="gtc",
                maximum_fee="0.17000002",
            )
        )
        assert sold.status == "committed"
        # The 0.90 bid fills at 0.89 after adverse cost: 0.089 per unit, so one unit fits.
        market = self._market("sell-book", sell_at + timedelta(seconds=1))
        trace = PaperBooks.apply(journal, "shared", market, scenario)
        fills = [event.fill for event in trace.physical_events if event.fill is not None]
        assert [(fill.quantity.value, fill.fee.value) for fill in fills] == [
            (Decimal("-1"), Decimal("0.089"))
        ]
        order = next(
            item.order
            for item in journal.orders()
            if item.order.decision_identity == "limit-sized-sell"
        )
        # About 0.081 is left, below the 0.085 fee of one unit even at the limit, so the
        # remainder can never fill: it is cancelled instead of reserved forever.
        assert [event.kind for event in trace.physical_events][-1] == "cancelled"
        assert (order.status, order.filled.value) == ("cancelled", Decimal("1"))
        assert order.paid_fee.value <= order.maximum_fee.value
        assert journal.accounts()[0].fault is None

    def test_a_shared_stranded_remainder_under_a_pending_cancel_is_not_reissued(
        self, tmp_path: Path
    ) -> None:
        """A netted sell remainder that can never fill ends with its parent and its child.

        The economics are the direct case's above: the 0.90 bid fills one unit at 0.89
        for 0.089, leaving about 0.081 of the 0.17000002 reserve, below the 0.085 fee of
        one unit at the 0.85 limit. The account cancel requested 1 ms before that book
        needs 5 ms to take effect, so the remainder ends on its own terms: alpha keeps
        two of its three units and nothing is re-sent.
        """
        scenario = self._scenario(fee_rate="0.10", cancel_delay_us=5_000)
        journal = self._ready(tmp_path / "shared-stranded.sqlite3", scenario)
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
        PaperBooks.apply(
            journal,
            "shared",
            self._market("inventory-book", decision_at + timedelta(seconds=1)),
            scenario,
        )
        sell_at = decision_at + timedelta(seconds=2)
        journal.observe(AccountQuote(price=self._price("1.00"), at=sell_at))
        sold = journal.coordinate(
            PortfolioBatch(
                identity="netted-sell",
                at=sell_at + timedelta(microseconds=1),
                decisions=(
                    PortfolioDecision(
                        request=self._order(
                            "netted-sell",
                            sell_at,
                            side="sell",
                            quantity="2",
                            limit="0.85",
                            time_in_force="gtc",
                            maximum_fee="0.17000002",
                        ),
                        context=self._context("alpha"),
                    ),
                ),
            )
        )
        assert sold.status == "committed" and len(sold.net_orders) == 1
        cancel = journal.control(
            AccountControl(
                identity="operator-cancel",
                account_id="shared",
                kind="cancel",
                at=sell_at + timedelta(milliseconds=1),
            )
        )
        assert cancel.status == "applied"
        trace = PaperBooks.apply(
            journal,
            "shared",
            self._market("sell-book", sell_at + timedelta(milliseconds=2)),
            scenario,
        )
        assert [event.kind for event in trace.physical_events] == [
            "request_ack",
            "accepted",
            "fill",
            "cancelled",
        ]
        child = next(
            item.order for item in journal.orders() if item.order.decision_identity == "netted-sell"
        )
        assert (child.status, child.filled.value) == ("cancelled", Decimal("1"))
        assert journal.portfolio_residuals("shared") == ()
        # No child awaits reissue, so another instance's batch needs no newer
        # reconciliation and creates no physical order.
        beta_at = sell_at + timedelta(milliseconds=3)
        journal.observe(AccountQuote(price=self._price("1.00"), at=beta_at))
        abstention = self._decision("beta", "beta-abstains", beta_at)
        abstained = journal.coordinate(
            PortfolioBatch(
                identity="beta-abstains",
                at=beta_at + timedelta(microseconds=1),
                decisions=(
                    PortfolioDecision(
                        request=replace(
                            abstention, decision=replace(abstention.decision, intent=None)
                        ),
                        context=self._context("beta"),
                    ),
                ),
            )
        )
        assert (abstained.status, abstained.net_orders) == ("committed", ())
        ledger = AccountLedger(journal.accounts()[0].ledger)
        assert ledger.snapshot(instance_id="alpha").positions == (self._quantity("2"),)

    def test_fee_cap_failure_blocks_without_partial_lifecycle_or_economics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A defective model's fill above an admitted reserve is refused and rolled back whole."""
        monkeypatch.setattr("execution.paper.PaperFeeSchedule", _OverchargingFeeSchedule)
        scenario = self._scenario(fee_rate="0.10")
        journal = self._ready(tmp_path / "fee-cap.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        journal.observe(AccountQuote(price=self._price("1.00"), at=decision_at))
        admitted = journal.admit(self._decision("alpha", "fee-cap", decision_at))
        assert admitted.status == "committed"
        before = AccountLedger(journal.accounts()[0].ledger).snapshot()
        market = self._market("fee-cap-book", decision_at + timedelta(seconds=1))
        assert journal.paper_trace("shared", market.identity) is None
        with pytest.raises(ValueError, match="account blocked"):
            PaperBooks.apply(journal, "shared", market, scenario)
        reopened = AccountJournal(journal.path, self._config())
        assert AccountLedger(reopened.accounts()[0].ledger).snapshot() == before
        assert reopened.orders()[0].order.status == "intent"
        assert reopened.accounts()[0].fault == "order_event_break"
        (trace,) = reopened.paper_traces("shared")
        assert trace.status == "failed" and trace.physical_events == ()
        assert journal.paper_trace("shared", market.identity) is not None
        assert reopened.paper_trace("shared", market.identity) is not None
        assert trace.rejected_event is not None and trace.rejected_event.kind == "fill"
        with pytest.raises(ValueError, match="account blocked"):
            PaperBooks.apply(reopened, "shared", market, scenario)
