"""Measure dedicated paper journal matching costs as filled-order history grows."""

from __future__ import annotations

# standard library imports
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# third party library imports
import pytest

# project library imports
from accounting import LedgerState
from configuration import PaperExecutionScenario
from execution import OrderDecision, PaperMarket, PaperMatcher, PaperOrderJournal
from financial_units import Currency, Dimension, Money, Price, Quantity, QuantityKind
from reference_data.instruments import InstrumentId
from risk import SpotLimits
from strategies import OrderIntent


class _DedicatedHistory:
    """Fill single-unit round trips on one claimed dedicated journal."""

    currency = Currency(code="TEST", minor_unit=Decimal("0.01"))
    dimension = Dimension(
        instrument_id=InstrumentId.from_canonical_text("11111111-1111-4111-8111-111111111111"),
        kind=QuantityKind.BASE_UNIT,
    )

    def __init__(self, journal: PaperOrderJournal, epoch: int) -> None:
        """Bind a claimed journal and one scenario matcher."""
        self.journal, self.epoch = journal, epoch
        scenario = PaperExecutionScenario(
            venue="okx",
            instrument_id=self.dimension.instrument_id,
            entry_delay_us=0,
            cancel_delay_us=0,
            adverse=self._price("0.01"),
            fee_rate=Decimal("0.005"),
            take_fraction=Decimal("1"),
            gas_inapplicable_reason="off-chain spot orders have no on-chain settlement",
        )
        self.matcher = PaperMatcher(
            journal, fee_rate=scenario.fee_rate, lot=self._quantity("1"), scenario=scenario
        )
        self.at = datetime(2025, 1, 1, tzinfo=UTC)
        self.markets = 0
        self.orders = 0

    @classmethod
    def open(cls, root: Path) -> PaperOrderJournal:
        """Create a funded dedicated journal on a one-unit grid."""
        return PaperOrderJournal(
            root / "paper.sqlite3",
            account="paper-account",
            instance="strategy-one",
            binding_identity="a" * 64,
            mode="paper",
            limits=SpotLimits(
                maximum=cls._quantity("10"),
                lot=cls._quantity("1"),
                tick=cls._price("0.01"),
                product="spot",
            ),
            ledger_state=LedgerState(
                initial_cash=Money(value=Decimal("100000"), currency=cls.currency),
                dimension=cls.dimension,
            ),
        )

    def market(self) -> None:
        """Match one never-seen market, alternating touches to refresh liquidity."""
        self.at += timedelta(milliseconds=1)
        self.markets += 1
        is_odd = self.markets % 2 == 1
        self.matcher.match(
            PaperMarket(
                identity=f"market-{self.markets}",
                at=self.at,
                bid=self._price("0.89" if is_odd else "0.90"),
                ask=self._price("1.01" if is_odd else "1.00"),
                bid_quantity=self._quantity("3"),
                ask_quantity=self._quantity("3"),
            ),
            epoch=self.epoch,
        )

    def round_trip(self) -> None:
        """Fill one IOC buy and one IOC sell of a single unit."""
        for side, limit in (("buy", "1.10"), ("sell", "0.80")):
            self.at += timedelta(milliseconds=1)
            self.orders += 1
            committed = self.journal.commit_step(
                epoch=self.epoch,
                step_id=f"step-{self.orders}",
                checkpoint=b"checkpoint",
                decision=OrderDecision(
                    identity=f"decision-{self.orders}",
                    at=self.at,
                    intent=OrderIntent(
                        side="buy" if side == "buy" else "sell",
                        quantity=self._quantity("1"),
                        limit=self._price(limit),
                        time_in_force="ioc",
                    ),
                ),
                reference=self._price("1.00"),
                maximum_fee=Money(value=Decimal("0.50"), currency=self.currency),
            )
            assert committed.status == "committed"
            self.market()

    def median_round_trip_seconds(self, repeats: int = 9) -> float:
        """Time filled round trips and return the median wall-clock seconds."""
        samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            self.round_trip()
            samples.append(time.perf_counter() - started)
        return sorted(samples)[repeats // 2]

    def median_market_seconds(self, repeats: int = 21) -> float:
        """Time idle markets and return the median wall-clock seconds."""
        samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            self.market()
            samples.append(time.perf_counter() - started)
        return sorted(samples)[repeats // 2]

    @classmethod
    def _price(cls, value: str) -> Price:
        """Build an exact quote price per base unit."""
        return Price(value=Decimal(value), currency=cls.currency, per=cls.dimension)

    @classmethod
    def _quantity(cls, value: str) -> Quantity:
        """Build exact base units."""
        return Quantity(value=Decimal(value), dimension=cls.dimension)


class TestPaperHistoryScaling:
    """Bound per-market growth with the dedicated journal's terminal history."""

    @pytest.mark.performance
    def test_idle_scenario_market_ignores_terminal_order_history(self, tmp_path: Path) -> None:
        """An idle scenario market stays near flat while filled orders accumulate."""
        with _DedicatedHistory.open(tmp_path) as journal:
            history = _DedicatedHistory(journal, journal.claim("scaling-owner"))
            medians: list[float] = []
            for orders in (20, 100):
                while history.orders < orders:
                    history.round_trip()
                medians.append(history.median_market_seconds())
        print(f"idle market at 20/100 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Decoding and re-validating every order and event grew about fourfold here.
        assert medians[1] < 2.5 * medians[0]

    @pytest.mark.performance
    def test_filled_round_trip_does_not_replay_the_whole_ledger(self, tmp_path: Path) -> None:
        """Posting fills stays near flat while the retained fill ledger grows."""
        with _DedicatedHistory.open(tmp_path) as journal:
            history = _DedicatedHistory(journal, journal.claim("ledger-owner"))
            medians: list[float] = []
            for orders in (50, 200):
                while history.orders < orders:
                    history.round_trip()
                medians.append(history.median_round_trip_seconds())
        print(f"round trip at 50/200 filled orders: {medians[0]:.6f}s/{medians[1]:.6f}s")
        # Decoding, re-validating and replaying every fill per event grew superlinearly.
        assert medians[1] < 2.5 * medians[0]
