"""Unit tests for alpha_core.execution.slippage."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from alpha_core.execution.models import BacktestOrderIntent
from alpha_core.execution.slippage import BookDepthSlippage, FixedSlippage
from alpha_core.portfolio.models import Side

_ZERO = Decimal("0")


def _order(
    side: Side = Side.LONG,
    size: Decimal = Decimal("5"),
    limit_price: Decimal | None = Decimal("0.5"),
) -> BacktestOrderIntent:
    return BacktestOrderIntent(
        instrument_id="a",
        side=side,
        size=size,
        order_type="limit" if limit_price is not None else "market",
        limit_price=limit_price,
    )


class TestFixedSlippage:
    def test_zero_bps_returns_zero(self) -> None:
        slip = FixedSlippage(bps=_ZERO)
        assert slip.estimate_slippage(_order(), book=None) == _ZERO

    def test_ten_bps_correct_delta(self) -> None:
        slip = FixedSlippage(bps=Decimal("10"))
        order = _order(limit_price=Decimal("0.5"))
        delta = slip.estimate_slippage(order, book=None)
        # 10/10000 * 0.5 = 0.0005
        assert delta == Decimal("0.000500")

    def test_hundred_bps(self) -> None:
        slip = FixedSlippage(bps=Decimal("100"))
        order = _order(limit_price=Decimal("0.4"))
        delta = slip.estimate_slippage(order, book=None)
        # 100/10000 * 0.4 = 0.004
        assert delta == Decimal("0.004000")

    def test_negative_bps_raises(self) -> None:
        with pytest.raises(ValueError):
            FixedSlippage(bps=Decimal("-1"))

    def test_market_order_uses_half_as_ref(self) -> None:
        slip = FixedSlippage(bps=Decimal("10"))
        order = BacktestOrderIntent(
            instrument_id="a", side=Side.LONG,
            size=Decimal("1"), order_type="market",
        )
        # No limit_price → ref = 0.5; slippage = 0.5 * 10/10000 = 0.0005
        delta = slip.estimate_slippage(order, book=None)
        assert delta == Decimal("0.000500")

    def test_bps_property(self) -> None:
        slip = FixedSlippage(bps=Decimal("25"))
        assert slip.bps == Decimal("25")


class TestBookDepthSlippage:
    def test_no_book_falls_back_to_15_bps(self) -> None:
        slip = BookDepthSlippage()
        order = _order(limit_price=Decimal("0.5"))
        delta = slip.estimate_slippage(order, book=None)
        # Fallback 15 bps * 0.5 = 0.00075
        assert delta == Decimal("0.000750")

    def test_empty_asks_falls_back(self) -> None:
        slip = BookDepthSlippage()
        book = SimpleNamespace(asks=[], bids=[])
        order = _order(side=Side.LONG, limit_price=Decimal("0.5"))
        delta = slip.estimate_slippage(order, book=book)
        assert delta == Decimal("0.000750")  # fallback

    def test_long_walks_asks(self) -> None:
        slip = BookDepthSlippage()
        # Ask levels: [(0.51, 3), (0.52, 10)] — buy 5 contracts
        book = SimpleNamespace(
            asks=[(Decimal("0.51"), Decimal("3")), (Decimal("0.52"), Decimal("10"))],
            bids=[],
        )
        order = _order(side=Side.LONG, size=Decimal("5"), limit_price=Decimal("0.50"))
        # VWAP = (3*0.51 + 2*0.52) / 5 = (1.53 + 1.04) / 5 = 2.57 / 5 = 0.514
        delta = slip.estimate_slippage(order, book=book)
        assert delta == Decimal("0.014000")  # abs(0.514 - 0.50)

    def test_short_walks_bids(self) -> None:
        slip = BookDepthSlippage()
        # Bid levels: [(0.49, 5), (0.48, 10)]
        book = SimpleNamespace(
            asks=[],
            bids=[(Decimal("0.49"), Decimal("5")), (Decimal("0.48"), Decimal("10"))],
        )
        order = _order(side=Side.SHORT, size=Decimal("5"), limit_price=Decimal("0.50"))
        # VWAP = 0.49; slip = abs(0.49 - 0.50) = 0.01
        delta = slip.estimate_slippage(order, book=book)
        assert delta == Decimal("0.010000")
