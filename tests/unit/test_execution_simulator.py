"""Unit tests for alpha_core.execution.simulator.ExecutionSimulator."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from alpha_core.execution.models import BacktestOrderIntent, FeeSchedule, SimulatedFill
from alpha_core.execution.simulator import ExecutionSimulator
from alpha_core.execution.slippage import FixedSlippage
from alpha_core.portfolio.models import Side

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_ZERO = Decimal("0")


def _market_order(
    side: Side = Side.LONG,
    size: Decimal = Decimal("10"),
    instrument_id: str = "a",
) -> BacktestOrderIntent:
    return BacktestOrderIntent(
        instrument_id=instrument_id,
        side=side,
        size=size,
        order_type="market",
    )


def _limit_order(
    side: Side = Side.LONG,
    size: Decimal = Decimal("10"),
    limit_price: Decimal = Decimal("0.5"),
    instrument_id: str = "a",
) -> BacktestOrderIntent:
    return BacktestOrderIntent(
        instrument_id=instrument_id,
        side=side,
        size=size,
        order_type="limit",
        limit_price=limit_price,
    )


class TestMarketOrderFills:
    def test_market_order_fills(self) -> None:
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=_ZERO))
        order = _market_order()
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        assert fill.fill_size == Decimal("10")

    def test_long_fill_price_above_ref(self) -> None:
        """LONG slippage is adverse — fill price > ref price."""
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=Decimal("10")))
        order = _market_order(side=Side.LONG)
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        # 10 bps of 0.5 = 0.0005 → fill = 0.5005
        assert fill.fill_price == Decimal("0.500500")

    def test_short_fill_price_below_ref(self) -> None:
        """SHORT slippage is adverse — fill price < ref price."""
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=Decimal("10")))
        order = _market_order(side=Side.SHORT)
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        # fill = 0.5 - 0.0005 = 0.4995
        assert fill.fill_price == Decimal("0.499500")

    def test_zero_slippage_fills_at_ref(self) -> None:
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=_ZERO))
        order = _market_order(side=Side.LONG)
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.6"), timestamp=_T0)
        assert fill is not None
        assert fill.fill_price == Decimal("0.600000")

    def test_no_last_trade_price_uses_half(self) -> None:
        """Falls back to 0.5 when no last_trade_price given."""
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=_ZERO))
        order = _market_order()
        fill = sim.simulate_fill(order, last_trade_price=None, timestamp=_T0)
        assert fill is not None
        assert fill.fill_price == Decimal("0.500000")

    def test_fill_price_clamped_to_unit_interval(self) -> None:
        """Slippage cannot push price above 1."""
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=Decimal("10000")))
        order = _market_order(side=Side.LONG)
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.99"), timestamp=_T0)
        assert fill is not None
        assert fill.fill_price <= Decimal("1")

    def test_timestamp_attached_to_fill(self) -> None:
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=_ZERO))
        order = _market_order()
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        assert fill.timestamp == _T0


class TestLimitOrderFills:
    def test_limit_order_fills_at_limit_price(self) -> None:
        """LIMIT orders use limit_price as the reference; always fills."""
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=_ZERO))
        order = _limit_order(limit_price=Decimal("0.5"))
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.7"), timestamp=_T0)
        assert fill is not None
        assert fill.fill_price == Decimal("0.500000")

    def test_limit_order_with_slippage(self) -> None:
        sim = ExecutionSimulator(slippage_model=FixedSlippage(bps=Decimal("10")))
        order = _limit_order(side=Side.LONG, limit_price=Decimal("0.5"))
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        # ref = limit_price = 0.5; slip = 0.0005; fill = 0.5005
        assert fill.fill_price == Decimal("0.500500")


class TestFeeApplication:
    def test_zero_fee_schedule(self) -> None:
        schedule = FeeSchedule()
        sim = ExecutionSimulator(
            fee_schedule=schedule,
            slippage_model=FixedSlippage(bps=_ZERO),
        )
        order = _market_order()
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        assert fill.fee == _ZERO

    def test_taker_fee_applied(self) -> None:
        schedule = FeeSchedule(taker_fee_bps=Decimal("20"))
        sim = ExecutionSimulator(
            fee_schedule=schedule,
            slippage_model=FixedSlippage(bps=_ZERO),
        )
        order = _market_order(size=Decimal("10"))
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        # notional = 10 * 0.5 = 5; fee = 5 * 20/10000 = 0.01
        expected_fee = Decimal("5") * Decimal("20") / Decimal("10000")
        assert fill.fee == expected_fee

    def test_per_contract_fee_added(self) -> None:
        schedule = FeeSchedule(per_contract_fee=Decimal("0.001"))
        sim = ExecutionSimulator(
            fee_schedule=schedule,
            slippage_model=FixedSlippage(bps=_ZERO),
        )
        order = _market_order(size=Decimal("10"))
        fill = sim.simulate_fill(order, last_trade_price=Decimal("0.5"), timestamp=_T0)
        assert fill is not None
        # per_contract = 10 * 0.001 = 0.01; rate_fee = 0 (taker_bps=0)
        assert fill.fee == Decimal("0.010000")
