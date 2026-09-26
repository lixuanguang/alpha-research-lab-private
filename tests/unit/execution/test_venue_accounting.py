"""Check native spot charges and independent physical wallet reconciliation."""

from __future__ import annotations

# standard library imports
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from accounting import AccountLedger
from configuration.accounts import AccountConfiguration, OpeningAccount
from execution.account_records import NativeFill, PhysicalAccountObservation
from execution.accounts import (
    AccountDecision,
    AccountJournal,
    AccountQuote,
    NetOrder,
    PortfolioBatch,
    PortfolioDecision,
)
from execution.records import OrderDecision, OrderEvent, OrderState
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from portfolio import PortfolioContext
from reference_data.instruments import InstrumentId
from risk.budgets import AccountLimit, BudgetPolicy, InstanceLimit
from risk.spot import SpotLimits
from strategies import OrderIntent


class TestVenueAccounting:
    """Keep native source costs and wallet evidence distinct from local IDs."""

    quote = Currency.from_code("USDT")
    base = Currency(code="QBTC", minor_unit=Decimal("0.00000001"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)

    @classmethod
    def _money(cls, value: str, currency: Currency | None = None) -> Money:
        """Create exact quote or base wallet amounts."""
        return Money(value=Decimal(value), currency=currency or cls.quote)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Create exact signed base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _price(cls, value: str = "100") -> Price:
        """Create one exact quote per base unit."""
        return Price(value=Decimal(value), currency=cls.quote, per=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Pin one account, instrument and independent 500 quote cap."""
        return AccountConfiguration(
            mode="venue_test",
            opening_at=cls.opening_at,
            accounts=(OpeningAccount(account_id="venue", cash=(cls._money("1000"),)),),
            instruments=(
                SpotLimits(
                    maximum=cls._quantity("10"),
                    lot=cls._quantity("1"),
                    tick=cls._price("0.01"),
                    product="spot",
                ),
            ),
            budgets=BudgetPolicy(
                valuation_currency=cls.quote,
                firm_maximum=cls._money("500"),
                accounts=(AccountLimit(account_id="venue", maximum=cls._money("500")),),
                instances=(
                    InstanceLimit(
                        instance_id="alpha",
                        account_id="venue",
                        maximum=cls._money("500"),
                        instruments=(cls.dimension.instrument_id,),
                    ),
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=100,
                max_order_notional=cls._money("500"),
            ),
        )

    @classmethod
    def _observation(
        cls,
        identity: str,
        at: datetime,
        quote: str,
        base: str,
        orders: tuple[OrderState, ...] = (),
    ) -> PhysicalAccountObservation:
        """State independent wallet totals without any local posting identifiers."""
        balances: tuple[Money, ...] = (cls._money(quote),)
        if Decimal(base):
            balances = (*balances, cls._money(base, cls.base))
        return PhysicalAccountObservation(
            identity=identity,
            account_id="venue",
            at=at,
            balances=balances,
            instrument_currencies=((cls.dimension, cls.base),),
            open_orders=orders,
        )

    @classmethod
    def _ready(cls, path: Path) -> AccountJournal:
        """Reconcile the authorized opening wallet before sending orders."""
        journal = AccountJournal(path, cls._config())
        assert journal.reconcile_venue(cls._observation("opening", cls.opening_at, "1000", "0"))
        return journal

    @classmethod
    def _buy(cls, journal: AccountJournal, at: datetime, identity: str = "buy") -> OrderState:
        """Admit a two-unit purchase with a one-quote-unit maximum fee."""
        quote = AccountQuote(price=cls._price(), at=at)
        journal.observe(quote)
        result = journal.admit(
            AccountDecision(
                account_id="venue",
                instance_id="alpha",
                decision=OrderDecision(
                    identity=identity,
                    at=at,
                    intent=OrderIntent(
                        side="buy",
                        quantity=cls._quantity("2"),
                        limit=cls._price(),
                        time_in_force="gtc",
                    ),
                ),
                quote=quote,
                maximum_fee=cls._money("1"),
            )
        )
        assert result.status == "committed"
        return result.orders[0]

    @classmethod
    def _native(
        cls,
        order: OrderState,
        at: datetime,
        *,
        identity: str = "venue-trade-1",
        fee: str = "0.01",
        fee_currency: Currency | None = None,
    ) -> NativeFill:
        """Describe a signed actual trade with a native asset fee or rebate."""
        return NativeFill(
            identity=identity,
            order_id=order.identity,
            at=at,
            filled_at=at - timedelta(microseconds=1),
            quantity=cls._quantity("2"),
            price=cls._price(),
            fee=cls._money(fee, fee_currency or cls.base),
            base_currency=cls.base,
        )

    def test_base_fee_restart_retry_wallet_break_and_conflicting_trade(
        self, tmp_path: Path
    ) -> None:
        """A base charge removes inventory and an actual wallet break blocks recovery."""
        path = tmp_path / "venue.sqlite3"
        journal = self._ready(path)
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at)
        # An admitted but unsent local intent is absent from the venue open set.
        assert journal.reconcile_venue(self._observation("before-send", decision_at, "1000", "0"))
        source = self._native(order, decision_at + timedelta(seconds=1))
        filled = journal.apply_native_fill(source)
        assert isinstance(filled, OrderState) and filled.status == "filled"
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert tuple(item.value for item in snapshot.cash) == (Decimal("800"), Decimal(0))
        assert snapshot.positions[0].value == Decimal("1.99")
        assert tuple(item.value for item in snapshot.fees) == (Decimal(0), Decimal("0.01"))
        assert snapshot.fill_ids == (source.identity,)
        reopened = AccountJournal(path, self._config())
        assert reopened.apply_native_fill(source) == filled
        assert AccountLedger(reopened.accounts()[0].ledger).snapshot() == snapshot
        observed_at = source.at + timedelta(seconds=1)
        assert not reopened.reconcile_venue(
            self._observation("wrong-base", observed_at, "800", "2")
        )
        assert reopened.accounts()[0].fault == "account_break"
        assert reopened.reconcile_venue(
            self._observation("exact-wallet", observed_at, "800", "1.99")
        )
        reopened.block("venue", "operator-stop")
        assert reopened.reconcile_venue(
            self._observation("still-stopped", observed_at, "800", "1.99")
        )
        assert reopened.accounts()[0].operator_block == "operator-stop"
        with pytest.raises(ValueError, match="native fill identity reused"):
            reopened.apply_native_fill(replace(source, fee=self._money("0.02", self.base)))
        assert AccountLedger(reopened.accounts()[0].ledger).snapshot() == snapshot
        assert not reopened.reconcile_venue(
            self._observation(
                "conflicting-source", observed_at + timedelta(seconds=1), "800", "1.99"
            )
        )

    def test_quote_rebate_and_dispatch_guard(self, tmp_path: Path) -> None:
        """Quote rebate credits cash; stopped dispatch is fenced while cancel stays open."""
        journal = self._ready(tmp_path / "rebate.sqlite3")
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at)
        unknown_at = decision_at + timedelta(microseconds=1)
        journal.apply_event(
            OrderEvent(
                identity="pending-send", order_id=order.identity, at=unknown_at, kind="unknown"
            )
        )
        with journal.execution_guard("venue", order.identity, unknown_at) as guarded:
            assert guarded.identity == order.identity
        source = self._native(
            order,
            decision_at + timedelta(seconds=1),
            fee="-0.25",
            fee_currency=self.quote,
        )
        journal.apply_native_fill(source)
        snapshot = AccountLedger(journal.accounts()[0].ledger).snapshot()
        assert snapshot.cash[0].value == Decimal("800.25")
        assert snapshot.positions[0].value == Decimal("2")
        assert snapshot.rebates[0].value == Decimal("0.25")
        assert journal.reconcile_venue(
            self._observation("rebated", source.at + timedelta(seconds=1), "800.25", "2")
        )
        second_at = source.at + timedelta(seconds=2)
        second = self._buy(journal, second_at, identity="second")
        journal.block("venue", "operator-stop")
        with pytest.raises(ValueError, match="dispatch is blocked"):
            with journal.execution_guard("venue", second.identity, second_at):
                pass
        with journal.execution_guard("venue", second.identity, second_at, cancel=True):
            pass
        journal.invalidate_venue("venue", "private-disconnect")
        assert journal.accounts()[0].reconciled_at is None
        assert journal.accounts()[0].operator_block == "operator-stop"

    def test_partial_base_fees_cannot_reuse_the_same_quote_reservation(
        self, tmp_path: Path
    ) -> None:
        """Two 0.8 and 0.3 quote-equivalent charges exceed the one-unit cap."""
        journal = self._ready(tmp_path / "partial.sqlite3")
        decision_at = self.opening_at + timedelta(seconds=1)
        order = self._buy(journal, decision_at)
        first_at = decision_at + timedelta(seconds=1)
        first = NativeFill(
            identity="partial-1",
            order_id=order.identity,
            at=first_at,
            filled_at=first_at - timedelta(microseconds=1),
            quantity=self._quantity("1"),
            price=self._price(),
            fee=self._money("0.008", self.base),
            base_currency=self.base,
        )
        first_result = journal.apply_native_fill(first)
        assert isinstance(first_result, OrderState) and first_result.status == "partial"
        before = journal.accounts()[0].ledger
        second_at = first_at + timedelta(seconds=1)
        second = replace(
            first,
            identity="partial-2",
            at=second_at,
            filled_at=second_at - timedelta(microseconds=1),
            fee=self._money("0.003", self.base),
        )
        with pytest.raises(ValueError, match="fee exceeds child reservations"):
            journal.apply_native_fill(second)
        assert journal.accounts()[0].ledger == before
        assert journal.accounts()[0].fault == "native_fill_break"
        assert not journal.reconcile_venue(
            self._observation("partial-wallet", second_at, "900", "0.992", (first_result,))
        )

    def test_net_parent_base_fee_is_exactly_attributed_to_both_children(
        self, tmp_path: Path
    ) -> None:
        """A physical four-unit fill charges each two-unit child 0.01 base."""
        initial = self._config()
        second_owner = InstanceLimit(
            instance_id="beta",
            account_id="venue",
            maximum=self._money("500"),
            instruments=(self.dimension.instrument_id,),
        )
        instance_limits: tuple[InstanceLimit, ...] = (
            *initial.budgets.instances,
            second_owner,
        )
        config = replace(
            initial,
            budgets=replace(
                initial.budgets,
                instances=instance_limits,
            ),
        )
        journal = AccountJournal(tmp_path / "net.sqlite3", config)
        assert journal.reconcile_venue(self._observation("opening", self.opening_at, "1000", "0"))
        decision_at = self.opening_at + timedelta(seconds=1)
        quote = AccountQuote(price=self._price(), at=decision_at)
        journal.observe(quote)
        decisions: list[PortfolioDecision] = []
        for instance in ("alpha", "beta"):
            decisions.append(
                PortfolioDecision(
                    request=AccountDecision(
                        account_id="venue",
                        instance_id=instance,
                        decision=OrderDecision(
                            identity=f"{instance}-buy",
                            at=decision_at,
                            intent=OrderIntent(
                                side="buy",
                                quantity=self._quantity("2"),
                                limit=self._price(),
                                time_in_force="gtc",
                            ),
                        ),
                        quote=quote,
                        maximum_fee=self._money("1"),
                    ),
                    context=PortfolioContext(
                        portfolio_id="portfolio",
                        strategy_id=instance,
                        model_revision="reference",
                        config_revision="reference",
                        horizon="one-minute",
                        reason="native-account-test",
                        venue="OKX",
                        settlement="spot-immediate",
                        risk_bucket="spot",
                        authority_scope="venue-test",
                    ),
                )
            )
        batch = PortfolioBatch(
            identity="two-buyers",
            at=decision_at + timedelta(microseconds=1),
            decisions=tuple(decisions),
        )
        committed = journal.coordinate(batch)
        assert committed.status == "committed"
        parent = committed.net_orders[0]
        assert parent.order.intent.quantity.value == Decimal("4")
        source_at = batch.at + timedelta(seconds=1)
        source = NativeFill(
            identity="physical-trade",
            order_id=parent.order.identity,
            at=source_at,
            filled_at=source_at - timedelta(microseconds=1),
            quantity=self._quantity("4"),
            price=self._price(),
            fee=self._money("0.02", self.base),
            base_currency=self.base,
        )
        result = journal.apply_native_fill(source)
        assert isinstance(result, NetOrder) and result.order.status == "filled"
        ledger = AccountLedger(journal.accounts()[0].ledger)
        snapshot = ledger.snapshot()
        assert snapshot.cash[0].value == Decimal("600")
        assert snapshot.positions[0].value == Decimal("3.98")
        assert snapshot.fees[1].value == Decimal("0.02")
        assert ledger.snapshot("alpha").positions[0].value == Decimal("1.99")
        assert ledger.snapshot("beta").positions[0].value == Decimal("1.99")
        assert journal.reconcile_venue(
            self._observation("net-wallet", source_at + timedelta(seconds=1), "600", "3.98")
        )
