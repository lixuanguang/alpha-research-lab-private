"""Unit tests for alpha_core.execution.models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alpha_core.execution.models import BacktestOrderIntent, FeeSchedule, SimulatedFill
from alpha_core.portfolio.models import Side

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_ZERO = Decimal("0")


class TestBacktestOrderIntent:
    def test_market_order_no_limit_price_ok(self) -> None:
        o = BacktestOrderIntent(
            instrument_id="a",
            side=Side.LONG,
            size=Decimal("5"),
            order_type="market",
        )
        assert o.order_type == "market"
        assert o.limit_price is None

    def test_limit_order_requires_limit_price(self) -> None:
        with pytest.raises(ValidationError, match="limit_price"):
            BacktestOrderIntent(
                instrument_id="a",
                side=Side.LONG,
                size=Decimal("5"),
                order_type="limit",
                limit_price=None,
            )

    def test_limit_order_with_price_ok(self) -> None:
        o = BacktestOrderIntent(
            instrument_id="a",
            side=Side.SHORT,
            size=Decimal("10"),
            order_type="limit",
            limit_price=Decimal("0.7"),
        )
        assert o.limit_price == Decimal("0.7")

    def test_size_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            BacktestOrderIntent(
                instrument_id="a",
                side=Side.LONG,
                size=Decimal("0"),
                order_type="market",
            )

    def test_limit_price_clamped_to_0_1(self) -> None:
        with pytest.raises(ValidationError):
            BacktestOrderIntent(
                instrument_id="a",
                side=Side.LONG,
                size=Decimal("1"),
                order_type="limit",
                limit_price=Decimal("1.5"),
            )

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            BacktestOrderIntent(
                instrument_id="a",
                side=Side.LONG,
                size=Decimal("1"),
                order_type="market",
                unknown="bad",  # type: ignore[call-arg]
            )

    def test_tif_default(self) -> None:
        o = BacktestOrderIntent(
            instrument_id="a",
            side=Side.LONG,
            size=Decimal("1"),
            order_type="market",
        )
        assert o.time_in_force == "ioc"


class TestFeeSchedule:
    def test_defaults_all_zero(self) -> None:
        fs = FeeSchedule()
        assert fs.maker_fee_bps == _ZERO
        assert fs.taker_fee_bps == _ZERO
        assert fs.per_contract_fee == _ZERO
        assert fs.resolution_fee_bps == _ZERO

    def test_taker_fee_calculation(self) -> None:
        fs = FeeSchedule(taker_fee_bps=Decimal("20"))
        # notional = 5.0; fee = 5.0 * 20 / 10000 = 0.01
        fee = fs.taker_fee(Decimal("5"))
        assert fee == Decimal("0.010000")

    def test_maker_fee_calculation(self) -> None:
        fs = FeeSchedule(maker_fee_bps=Decimal("10"))
        fee = fs.maker_fee(Decimal("10"))
        assert fee == Decimal("0.010000")

    def test_resolution_fee_calculation(self) -> None:
        fs = FeeSchedule(resolution_fee_bps=Decimal("50"))
        # payoff = 10; fee = 10 * 50 / 10000 = 0.05
        fee = fs.resolution_fee(Decimal("10"))
        assert fee == Decimal("0.050000")

    def test_negative_bps_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            FeeSchedule(taker_fee_bps=Decimal("-1"))


class TestSimulatedFill:
    def test_construction(self) -> None:
        order = BacktestOrderIntent(
            instrument_id="a",
            side=Side.LONG,
            size=Decimal("5"),
            order_type="market",
        )
        fill = SimulatedFill(
            order=order,
            fill_price=Decimal("0.5"),
            fill_size=Decimal("5"),
            fee=Decimal("0.01"),
            timestamp=_T0,
            slippage=Decimal("0.001"),
        )
        assert fill.fill_price == Decimal("0.5")
        assert fill.order.side == Side.LONG

    def test_fill_price_in_range(self) -> None:
        with pytest.raises(ValidationError):
            order = BacktestOrderIntent(
                instrument_id="a", side=Side.LONG, size=Decimal("1"), order_type="market"
            )
            SimulatedFill(
                order=order,
                fill_price=Decimal("1.5"),
                fill_size=Decimal("1"),
                timestamp=_T0,
            )
