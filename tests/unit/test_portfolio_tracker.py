"""Unit tests for alpha_core.portfolio.tracker.PortfolioTracker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alpha_core.execution.models import BacktestOrderIntent, SimulatedFill
from alpha_core.portfolio.models import Side
from alpha_core.portfolio.tracker import PortfolioTracker

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_ZERO = Decimal("0")


def _fill(
    instrument_id: str = "a",
    side: Side = Side.LONG,
    size: Decimal = Decimal("10"),
    fill_price: Decimal = Decimal("0.3"),
    fee: Decimal = _ZERO,
    ts: datetime | None = None,
) -> SimulatedFill:
    order = BacktestOrderIntent(
        instrument_id=instrument_id,
        side=side,
        size=size,
        order_type="market",
    )
    return SimulatedFill(
        order=order,
        fill_price=fill_price,
        fill_size=size,
        fee=fee,
        timestamp=ts or _T0,
        slippage=_ZERO,
    )


class TestInitialState:
    def test_initial_cash(self) -> None:
        tracker = PortfolioTracker(Decimal("5000"))
        state = tracker.state()
        assert state.cash == Decimal("5000")
        assert state.equity == Decimal("5000")
        assert state.positions == {}

    def test_default_initial_cash(self) -> None:
        tracker = PortfolioTracker()
        assert tracker.state().cash == Decimal("10000")


class TestLongFills:
    def test_long_fill_opens_position(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("5"), fill_price=Decimal("0.4")))
        state = tracker.state()
        assert "a" in state.positions
        assert state.positions["a"].side == Side.LONG
        assert state.positions["a"].size == Decimal("5")

    def test_long_fill_reduces_cash(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(
            _fill(
                side=Side.LONG,
                size=Decimal("5"),
                fill_price=Decimal("0.4"),
                fee=_ZERO,
            )
        )
        state = tracker.state()
        # cash -= 5 * 0.4 = 2.0
        assert state.cash == Decimal("998")

    def test_long_fill_with_fee(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(
            _fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.5"), fee=Decimal("0.5"))
        )
        state = tracker.state()
        # cash -= 10 * 0.5 + 0.5 = 5.5
        assert state.cash == Decimal("994.5")
        assert state.total_fees == Decimal("0.5")

    def test_add_to_long_averages_entry_price(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.2")))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.4")))
        pos = tracker.state().positions["a"]
        # Average = (10*0.2 + 10*0.4) / 20 = 0.3
        assert pos.entry_price == Decimal("0.3")
        assert pos.size == Decimal("20")


class TestShortFills:
    def test_short_fill_opens_position_and_increases_cash(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.SHORT, size=Decimal("5"), fill_price=Decimal("0.6")))
        state = tracker.state()
        assert "a" in state.positions
        assert state.positions["a"].side == Side.SHORT
        # cash += 5 * 0.6 = 3
        assert state.cash == Decimal("1003")

    def test_short_fill_with_fee_reduces_cash_received(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(
            _fill(
                side=Side.SHORT,
                size=Decimal("10"),
                fill_price=Decimal("0.5"),
                fee=Decimal("0.5"),
            )
        )
        state = tracker.state()
        # cash += 10 * 0.5 - 0.5 = 4.5
        assert state.cash == Decimal("1004.5")


class TestResolution:
    def test_long_resolves_at_one(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.3")))
        cash_before = tracker.state().cash
        tracker.apply_resolution("a", Decimal("1"))
        state = tracker.state()
        # cash += 10 * 1 = 10
        assert state.cash == cash_before + Decimal("10")
        assert "a" not in state.positions
        assert len(tracker.position_history()) == 1

    def test_long_resolves_at_zero(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.3")))
        cash_before = tracker.state().cash
        tracker.apply_resolution("a", Decimal("0"))
        state = tracker.state()
        # cash += 0 (no payoff)
        assert state.cash == cash_before
        assert "a" not in state.positions

    def test_long_resolution_pnl_correct(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.3")))
        tracker.apply_resolution("a", Decimal("1"))
        # pnl = 10 * (1 - 0.3) = 7
        hist = tracker.position_history()
        assert hist[0].realised_pnl == Decimal("7")

    def test_short_resolves_at_zero_profit(self) -> None:
        """Short at 0.7, resolves at 0: profit = 10 * (0.7 - 0) = 7."""
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.SHORT, size=Decimal("10"), fill_price=Decimal("0.7")))
        cash_before = tracker.state().cash
        tracker.apply_resolution("a", Decimal("0"))
        state = tracker.state()
        # cash -= 10 * 0 = 0 (no payout needed)
        assert state.cash == cash_before
        hist = tracker.position_history()
        assert hist[0].realised_pnl == Decimal("7")

    def test_short_resolves_at_one_loss(self) -> None:
        """Short at 0.7, resolves at 1: loss = 10 * (0.7 - 1) = -3."""
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.SHORT, size=Decimal("10"), fill_price=Decimal("0.7")))
        cash_before = tracker.state().cash
        tracker.apply_resolution("a", Decimal("1"))
        state = tracker.state()
        # cash -= 10 * 1 = 10
        assert state.cash == cash_before - Decimal("10")
        hist = tracker.position_history()
        assert hist[0].realised_pnl == Decimal("-3")

    def test_resolution_no_position_is_noop(self) -> None:
        tracker = PortfolioTracker(Decimal("500"))
        cash_before = tracker.state().cash
        tracker.apply_resolution("unknown", Decimal("1"))
        assert tracker.state().cash == cash_before


class TestMarkToMarket:
    def test_mtm_updates_unrealised_pnl(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.3")))
        tracker.mark_to_market({"a": Decimal("0.5")}, _T0 + timedelta(minutes=1))
        pos = tracker.state().positions["a"]
        # unrealised = 10 * (0.5 - 0.3) = 2.0
        assert pos.unrealised_pnl == Decimal("2.0")
        assert pos.current_price == Decimal("0.5")

    def test_mtm_records_equity_curve(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.mark_to_market({"a": Decimal("0.5")}, _T0)
        tracker.mark_to_market({"a": Decimal("0.6")}, _T0 + timedelta(minutes=1))
        curve = tracker.equity_curve()
        assert len(curve) == 2
        ts0, _eq0 = curve[0]
        ts1, _eq1 = curve[1]
        assert ts1 > ts0

    def test_mtm_missing_instrument_ignored(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(
            _fill(
                instrument_id="a",
                side=Side.LONG,
                size=Decimal("10"),
                fill_price=Decimal("0.3"),
            )
        )
        # No price for "a" in update — should not raise.
        tracker.mark_to_market({"b": Decimal("0.5")}, _T0)
        state = tracker.state()
        assert state.positions["a"].unrealised_pnl == _ZERO


class TestClosingPositions:
    def test_long_closed_by_short_fill(self) -> None:
        tracker = PortfolioTracker(Decimal("1000"))
        tracker.apply_fill(_fill(side=Side.LONG, size=Decimal("10"), fill_price=Decimal("0.3")))
        # Close with SHORT fill at higher price.
        tracker.apply_fill(_fill(side=Side.SHORT, size=Decimal("10"), fill_price=Decimal("0.6")))
        state = tracker.state()
        # Position should be closed.
        assert "a" not in state.positions
        hist = tracker.position_history()
        # realised_pnl = 10 * (0.6 - 0.3) = 3
        assert hist[0].realised_pnl == Decimal("3")
