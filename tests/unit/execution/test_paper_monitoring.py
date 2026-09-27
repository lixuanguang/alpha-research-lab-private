"""Verify exact and causal paper monitoring from committed account evidence."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import (
    AccountLedger,
    AccountSnapshot,
    AttributedPaperFill,
    PaperAccountReporter,
    PaperCostEvidence,
    PaperGasPolicy,
    PaperPositionMark,
)
from configuration import AccountConfiguration, OpeningAccount, PaperExecutionScenario
from execution import (
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    PaperMarket,
    PaperMonitoring,
    PortfolioBatch,
    PortfolioContext,
    PortfolioDecision,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from strategies import OrderIntent
from telemetry import MonitoringEvent, MonitoringQuery, TelemetryStore


class TestPaperMonitoring:
    """Reconcile shared attributed economics and real monitoring receipt clocks."""

    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )

    @classmethod
    def _money(cls, value: str) -> Money:
        """Construct an exact quote-currency amount."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Construct an exact base-unit amount."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Construct an exact quote price per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Pin a shared paper account with two separately budgeted strategies."""
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
    def _scenario(cls) -> PaperExecutionScenario:
        """Pin the modeled public spot matching and off-chain gas policy."""
        return PaperExecutionScenario(
            venue="okx",
            instrument_id=cls.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=cls._price("0.01"),
            fee_rate=Decimal("0.005"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot paper order",
        )

    @classmethod
    def _ready(cls, path: Path, scenario: PaperExecutionScenario) -> AccountJournal:
        """Reconcile independent opening cash before portfolio admission."""
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
    def _coordinate(cls, journal: AccountJournal, at: datetime) -> None:
        """Admit two child orders under one physical parent."""
        journal.observe(AccountQuote(price=cls._price("1.00"), at=at))
        decisions = tuple(
            PortfolioDecision(
                request=AccountDecision(
                    account_id="shared",
                    instance_id=instance,
                    decision=OrderDecision(
                        identity=f"{instance}-decision",
                        at=at,
                        intent=OrderIntent(
                            side="buy",
                            quantity=cls._quantity("3"),
                            limit=cls._price("1.10"),
                            time_in_force="gtc",
                        ),
                    ),
                    quote=AccountQuote(price=cls._price("1.00"), at=at),
                    maximum_fee=cls._money("0.50"),
                    checkpoint=instance.encode(),
                ),
                context=PortfolioContext(
                    portfolio_id="reference",
                    strategy_id=instance,
                    model_revision="v1",
                    config_revision="v1",
                    horizon="one-minute",
                    reason="monitoring-acceptance",
                    venue="OKX",
                    settlement="spot-immediate",
                    risk_bucket="spot",
                    authority_scope="paper",
                ),
            )
            for instance in ("alpha", "beta")
        )
        result = journal.coordinate(
            PortfolioBatch(
                identity="shared-batch", at=at + timedelta(microseconds=1), decisions=decisions
            )
        )
        assert result.status == "committed" and len(result.net_orders) == 1

    @staticmethod
    def _event(events: tuple[MonitoringEvent, ...], scope: str, name: str) -> MonitoringEvent:
        """Require one named fact in one explicit monitoring scope."""
        selected = tuple(
            event for event in events if event.context.scope == scope and event.name == name
        )
        assert len(selected) == 1
        return selected[0]

    @classmethod
    def _value(cls, events: tuple[MonitoringEvent, ...], scope: str, name: str) -> Fraction:
        """Recover one exact scalar while rejecting missing observations."""
        event = cls._event(events, scope, name)
        assert event.value is not None
        return Fraction(int(event.value.numerator), int(event.value.denominator))

    @staticmethod
    def _ratio(event: MonitoringEvent) -> Fraction:
        """Recover one exact event scalar without floating conversion."""
        assert event.value is not None
        return Fraction(int(event.value.numerator), int(event.value.denominator))

    def test_shared_pending_and_missing_report_are_exact(self, tmp_path: Path) -> None:
        """Physical orders and child reservations retain separate counts and units."""
        journal = self._ready(tmp_path / "pending.sqlite3", self._scenario())
        decision_at = self.opening_at + timedelta(seconds=1)
        self._coordinate(journal, decision_at)
        with pytest.raises(ValueError, match="follows monitoring receipt"):
            PaperMonitoring().account(
                journal,
                account_id="shared",
                observed_at=self.opening_at,
                sample="backdated",
            )
        observed_at = decision_at + timedelta(seconds=1)
        events = PaperMonitoring("installed-release").account(
            journal,
            account_id="shared",
            observed_at=observed_at,
            sample="pending",
            source="public-book",
            venue="okx",
        )
        instrument = str(self.dimension.instrument_id)
        account = "account:shared"
        assert self._value(events, account, "execution.orders") == 1
        assert self._value(events, account, f"execution.pending_quantity.{instrument}") == 6
        assert self._value(events, account, "execution.pending_fee.USDT") == 1
        for instance in ("alpha", "beta"):
            scope = f"account:shared:strategy:{instance}"
            assert self._value(events, scope, f"execution.pending_quantity.{instrument}") == 3
            assert self._value(events, scope, "execution.pending_fee.USDT") == Fraction(1, 2)
            assert self._event(events, scope, "paper.net_pnl.USDT").missing_reason == (
                "report_unavailable"
            )
        assert self._event(events, account, "paper.gas_applicable").missing_reason == (
            "report_unavailable"
        )
        assert self._value(events, account, "account.reconciliation_failed") == 0
        assert self._value(events, account, "paper.fees.USDT") == 0
        assert self._value(events, account, "paper.rebates.USDT") == 0
        assert all(event.context.account == "shared" for event in events)
        assert all(event.context.source == "public-book" for event in events)

        assert not journal.reconcile(
            AccountObservation(
                identity="incorrect-open-orders",
                at=observed_at + timedelta(seconds=1),
                snapshot=AccountLedger(journal.accounts()[0].ledger).snapshot(),
                open_orders=(),
            )
        )
        failed = PaperMonitoring().account(
            journal,
            account_id="shared",
            observed_at=observed_at + timedelta(seconds=2),
            sample="reconciliation-break",
        )
        assert self._value(failed, account, "account.reconciliation_failed") == 1
        assert self._value(failed, account, "risk.blocked") == 1
        assert self._value(failed, account, f"execution.pending_quantity.{instrument}") == 6

    def test_report_omission_means_unposted_strategy_has_zero_economics(
        self, tmp_path: Path
    ) -> None:
        """No-trade strategies retain explicit report-cutoff zero without a fill claim."""
        scenario = self._scenario()
        journal = self._ready(tmp_path / "no-trade.sqlite3", scenario)
        report = PaperAccountReporter().build(
            journal.accounts()[0].ledger,
            cutoff=self.opening_at,
            max_mark_age=timedelta(seconds=1),
            marks=(),
            fills=(),
            costs=(),
            gas_policy=PaperGasPolicy(
                scenario_id=scenario.identity,
                applicable=False,
                reason=scenario.gas_inapplicable_reason,
            ),
        )
        assert report.instances == ()
        events = PaperMonitoring().account(
            journal,
            account_id="shared",
            observed_at=self.opening_at + timedelta(seconds=1),
            sample="no-trade",
            report=report,
        )
        for instance in ("alpha", "beta"):
            scope = f"account:shared:strategy:{instance}"
            assert self._value(events, scope, "paper.net_pnl.USDT") == 0
            assert self._value(events, scope, "paper.fees.USDT") == 0
            assert self._value(events, scope, "paper.gas_applicable") == 0
            assert self._event(events, scope, "paper.net_pnl.USDT").at == self.opening_at

    def test_native_currencies_remain_separate_without_conversion(self, tmp_path: Path) -> None:
        """A multi-currency report yields exact currency-keyed NAV, never merged FX."""
        config = replace(
            self._config(),
            accounts=(
                OpeningAccount(
                    account_id="shared",
                    cash=(
                        self._money("1000"),
                        Money(value=Decimal("50"), currency=Currency.from_code("USD")),
                    ),
                ),
            ),
        )
        journal = AccountJournal(tmp_path / "native-currencies.sqlite3", config)
        scenario = self._scenario()
        report = PaperAccountReporter().build(
            journal.accounts()[0].ledger,
            cutoff=self.opening_at,
            max_mark_age=timedelta(seconds=1),
            marks=(),
            fills=(),
            costs=(),
            gas_policy=PaperGasPolicy(
                scenario_id=scenario.identity,
                applicable=False,
                reason=scenario.gas_inapplicable_reason,
            ),
        )
        events = PaperMonitoring().account(
            journal,
            account_id="shared",
            observed_at=self.opening_at + timedelta(seconds=1),
            sample="two-currencies",
            report=report,
        )
        account = "account:shared"
        assert self._value(events, account, "paper.nav.USDT") == 1000
        assert self._value(events, account, "paper.nav.USD") == 50
        assert self._value(events, account, "paper.net_pnl.USDT") == 0
        assert self._value(events, account, "paper.net_pnl.USD") == 0
        assert self._event(events, account, "paper.nav.USDT").units == "USDT"
        assert self._event(events, account, "paper.nav.USD").units == "USD"
        assert not any(event.name == "paper.nav" for event in events)

        one_currency = self._ready(tmp_path / "single-currency.sqlite3", scenario)
        with pytest.raises(ValueError, match="differs from account"):
            PaperMonitoring().account(
                one_currency,
                account_id="shared",
                observed_at=self.opening_at + timedelta(seconds=1),
                sample="wrong-report",
                report=report,
            )

    def test_report_and_trace_reconcile_to_independent_exact_economics(
        self, tmp_path: Path
    ) -> None:
        """Attributed child fills sum once and report costs do not debit net twice."""
        scenario = self._scenario()
        journal = self._ready(tmp_path / "economics.sqlite3", scenario)
        decision_at = self.opening_at + timedelta(seconds=1)
        self._coordinate(journal, decision_at)
        market_at = decision_at + timedelta(seconds=1)
        market = PaperMarket(
            identity="book-1",
            at=market_at,
            bid=self._price("0.99"),
            ask=self._price("1.00"),
            bid_quantity=self._quantity("3"),
            ask_quantity=self._quantity("3"),
        )
        trace = journal.match_public_market("shared", market, scenario)
        assert trace.status == "committed"
        fills, costs = journal.paper_report_facts("shared")
        report = PaperAccountReporter().build(
            journal.accounts()[0].ledger,
            cutoff=market_at,
            max_mark_age=timedelta(seconds=1),
            marks=(
                PaperPositionMark(
                    identity="mark-1", available_at=market_at, price=self._price("1.02")
                ),
            ),
            fills=tuple(
                AttributedPaperFill(
                    instance_id=item.instance_id, order_id=item.order_id, fill=item.fill
                )
                for item in fills
            ),
            costs=tuple(
                PaperCostEvidence(
                    source_fill_id=item.source_fill_id,
                    posting_id=item.posting_id,
                    amount=item.amount,
                )
                for item in costs
            ),
            gas_policy=PaperGasPolicy(
                scenario_id=scenario.identity,
                applicable=False,
                reason=scenario.gas_inapplicable_reason,
            ),
        )
        receipt = market_at + timedelta(seconds=5)
        monitoring = PaperMonitoring("installed-release")
        events = monitoring.account(
            journal,
            account_id="shared",
            observed_at=receipt,
            sample="report",
            report=report,
            source="public-book",
            venue="okx",
        )
        account = "account:shared"
        assert self._value(events, account, "paper.net_pnl.USDT") == (Fraction(1485, 100000))
        assert self._value(events, account, "paper.fees.USDT") == (Fraction(1515, 100000))
        assert self._value(events, account, "paper.slippage.USDT") == (Fraction(3, 100))
        assert self._value(events, account, "paper.gross_pnl.USDT") == (Fraction(6, 100))
        assert self._value(events, account, "paper.gas_applicable") == 0
        assert self._event(events, account, "paper.net_pnl.USDT").at == market_at
        assert self._event(events, account, "paper.net_pnl.USDT").recorded_at == receipt
        assert sum(
            self._value(events, f"account:shared:strategy:{instance}", "paper.net_pnl.USDT")
            for instance in ("alpha", "beta")
        ) == Fraction(1485, 100000)

        trace_events = monitoring.trace(
            trace,
            observed_at=receipt,
            source="public-book",
            children=journal.orders(),
        )
        instrument = str(self.dimension.instrument_id)
        assert (
            sum(
                self._ratio(event)
                for event in trace_events
                if event.context.scope == account
                and event.name == f"execution.event.fill_quantity.{instrument}"
            )
            == 3
        )
        assert all(event.at == market_at and event.recorded_at == receipt for event in trace_events)
        assert all(event.clock_quality == "modeled" for event in trace_events)

        store = TelemetryStore(tmp_path / "monitor.sqlite3")
        assert store.append((*events, *trace_events)) == len(events) + len(trace_events)
        assert TelemetryStore(tmp_path / "monitor.sqlite3").append((*events, *trace_events)) == 0
        before = MonitoringQuery(
            scope=account,
            mode="paper",
            start=market_at - timedelta(microseconds=1),
            end=market_at + timedelta(microseconds=1),
            as_of=market_at + timedelta(microseconds=1),
        )
        assert store.query(before) == ()
        after = MonitoringQuery(
            scope=account,
            mode="paper",
            start=before.start,
            end=before.end,
            as_of=receipt,
        )
        assert self._event(store.query(after), account, "paper.net_pnl.USDT").recorded_at == (
            receipt
        )
        with pytest.raises(ValueError, match="different bytes"):
            store.append(
                monitoring.trace(
                    trace,
                    observed_at=receipt + timedelta(seconds=1),
                    source="public-book",
                    children=journal.orders(),
                )
            )
