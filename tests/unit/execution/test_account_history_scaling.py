"""Measure shared account journal costs as retained paper history grows."""

from __future__ import annotations

# standard library imports
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest

# project library imports
from accounting import AccountSnapshot
from configuration import AccountConfiguration, OpeningAccount, PaperExecutionScenario
from execution import (
    AccountDecision,
    AccountJournal,
    AccountObservation,
    AccountQuote,
    OrderDecision,
    PaperMarket,
)
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import AccountLimit, BudgetPolicy, InstanceLimit, SpotLimits
from strategies import OrderIntent


class _SharedFirmHistory:
    """Grow one busy account's paper history beside a quiet account in one firm journal."""

    currency = Currency.from_code("USDT")
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )
    opening_at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    accounts = ("busy", "quiet")

    def __init__(self, path: Path) -> None:
        """Open, bind and reconcile both accounts before any market."""
        self.scenario = PaperExecutionScenario(
            venue="okx",
            instrument_id=self.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=self._price("0.01"),
            fee_rate=Decimal("0.001"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot order matching",
        )
        self.journal = AccountJournal(path, self._config())
        for account in self.accounts:
            self.journal.bind_paper_scenario(account, self.scenario)
            assert self.journal.reconcile(self._opening(account))
        self.at = self.opening_at + timedelta(seconds=1)
        self.markets = 0
        self.orders = 0

    def tick(self, account_id: str) -> None:
        """Match one never-seen public market for an account."""
        self.at += timedelta(milliseconds=1)
        self.markets += 1
        # Alternating touches start a fresh displayed-size segment on each market.
        is_odd = self.markets % 2 == 1
        market = PaperMarket(
            identity=f"market-{self.markets}",
            at=self.at,
            bid=self._price("0.89" if is_odd else "0.90"),
            ask=self._price("1.01" if is_odd else "1.00"),
            bid_quantity=self._quantity("3"),
            ask_quantity=self._quantity("3"),
        )
        self.journal.match_public_market(account_id, market, self.scenario)

    def round_trip(self) -> None:
        """Fill one IOC buy and one IOC sell of a single unit for the busy account."""
        for side, limit in (("buy", "1.10"), ("sell", "0.80")):
            self.at += timedelta(milliseconds=1)
            self.orders += 1
            quote = AccountQuote(price=self._price("1.00"), at=self.at)
            self.journal.observe(quote)
            admitted = self.journal.admit(
                AccountDecision(
                    account_id="busy",
                    instance_id="busy-alpha",
                    decision=OrderDecision(
                        identity=f"order-{self.orders}",
                        at=self.at,
                        intent=OrderIntent(
                            side="buy" if side == "buy" else "sell",
                            quantity=self._quantity("1"),
                            limit=self._price(limit),
                            time_in_force="ioc",
                        ),
                    ),
                    quote=quote,
                    maximum_fee=self._money("0.01"),
                    checkpoint=f"order-{self.orders}".encode(),
                )
            )
            assert admitted.status == "committed", admitted.reason
            self.tick("busy")

    def busy_tick(self) -> None:
        """Match one idle market for the busy account."""
        self.tick("busy")

    def busy_report(self) -> int:
        """Project the busy account's owned fills and their cost links."""
        fills, costs = self.journal.paper_report_facts("busy")
        return len(fills) + len(costs)

    def quiet_traces(self) -> int:
        """Read every retained trace of the quiet account."""
        return len(self.journal.paper_traces("quiet"))

    @staticmethod
    def median_seconds(operation: Callable[[], object], repeats: int = 31) -> float:
        """Time an operation repeatedly and return its median wall-clock seconds."""
        samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            operation()
            samples.append(time.perf_counter() - started)
        return sorted(samples)[repeats // 2]

    @classmethod
    def _money(cls, value: str) -> Money:
        """Build exact quote currency."""
        return Money(value=Decimal(value), currency=cls.currency)

    @classmethod
    def _price(cls, value: str) -> Price:
        """Build an exact quote price per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Build exact base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)

    @classmethod
    def _config(cls) -> AccountConfiguration:
        """Fund two independently limited accounts in one firm journal."""
        return AccountConfiguration(
            mode="paper",
            opening_at=cls.opening_at,
            accounts=tuple(
                OpeningAccount(account_id=account, cash=(cls._money("1000"),))
                for account in cls.accounts
            ),
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
                firm_maximum=cls._money("2000"),
                accounts=tuple(
                    AccountLimit(account_id=account, maximum=cls._money("1000"))
                    for account in cls.accounts
                ),
                instances=tuple(
                    InstanceLimit(
                        instance_id=f"{account}-alpha",
                        account_id=account,
                        maximum=cls._money("1000"),
                        instruments=(cls.dimension.instrument_id,),
                    )
                    for account in cls.accounts
                ),
                max_quote_age_us=1_000_000,
                max_state_age_us=86_400_000_000,
                max_price_deviation_bps=2000,
                max_order_notional=cls._money("1000"),
            ),
        )

    @classmethod
    def _opening(cls, account_id: str) -> AccountObservation:
        """Author each account's independent opening cash observation."""
        return AccountObservation(
            identity=f"opening-{account_id}",
            at=cls.opening_at,
            snapshot=AccountSnapshot(
                account_id=account_id,
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


class TestAccountHistoryScaling:
    """Bound per-operation growth with another account's retained history."""

    @pytest.mark.performance
    def test_one_account_trace_read_ignores_other_accounts_history(self, tmp_path: Path) -> None:
        """Reading a quiet account's traces stays flat while a busy account's history grows."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        history.tick("quiet")
        medians: list[float] = []
        for size in (500, 4000):
            while history.markets - 1 < size:
                history.tick("busy")
            medians.append(history.median_seconds(history.quiet_traces))
        print(f"quiet trace read at 500/4000 busy traces: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Scanning every account's rows grows about eightfold here; the index stays flat.
        assert medians[1] < 2 * medians[0]

    @pytest.mark.performance
    def test_idle_paper_tick_ignores_terminal_order_history(self, tmp_path: Path) -> None:
        """An idle tick stays near flat while filled orders and their events accumulate."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        medians: list[float] = []
        for orders in (40, 200):
            while history.orders < orders:
                history.round_trip()
            medians.append(history.median_seconds(history.busy_tick, repeats=21))
        print(f"idle tick at 40/200 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Re-validating every order and event against every order grew about 11x here.
        assert medians[1] < 3 * medians[0]

    @pytest.mark.performance
    def test_report_facts_grow_no_faster_than_their_fills(self, tmp_path: Path) -> None:
        """Report projection decodes each trace once and joins through maps, not scans."""
        history = _SharedFirmHistory(tmp_path / "firm.sqlite3")
        medians: list[float] = []
        for orders in (40, 200):
            while history.orders < orders:
                history.round_trip()
            medians.append(history.median_seconds(history.busy_report, repeats=9))
        print(f"report facts at 40/200 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Five times the fills may cost at most about five times as much.
        assert medians[1] < 7 * medians[0]
