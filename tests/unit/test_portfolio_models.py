"""Unit tests for alpha_core.portfolio.models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alpha_core.portfolio.models import PortfolioState, PositionState, Side

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_ZERO = Decimal("0")
_ONE = Decimal("1")


def _position(
    instrument_id: str = "a",
    side: Side = Side.LONG,
    size: Decimal = Decimal("10"),
    entry_price: Decimal = Decimal("0.3"),
    current_price: Decimal = Decimal("0.3"),
    unrealised_pnl: Decimal = _ZERO,
    realised_pnl: Decimal = _ZERO,
) -> PositionState:
    return PositionState(
        instrument_id=instrument_id,
        side=side,
        size=size,
        entry_price=entry_price,
        current_price=current_price,
        unrealised_pnl=unrealised_pnl,
        realised_pnl=realised_pnl,
        fees_paid=_ZERO,
        opened_at=_T0,
        last_updated=_T0,
    )


class TestSide:
    def test_values(self) -> None:
        assert Side.LONG.value == "long"
        assert Side.SHORT.value == "short"

    def test_str_enum(self) -> None:
        assert isinstance(Side.LONG, str)


class TestPositionState:
    def test_long_construction(self) -> None:
        pos = _position(side=Side.LONG, size=Decimal("5"), entry_price=Decimal("0.4"))
        assert pos.side == Side.LONG
        assert pos.size == Decimal("5")
        assert pos.entry_price == Decimal("0.4")

    def test_short_construction(self) -> None:
        pos = _position(side=Side.SHORT, size=Decimal("3"), entry_price=Decimal("0.7"))
        assert pos.side == Side.SHORT

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            PositionState(
                instrument_id="x",
                side=Side.LONG,
                size=Decimal("1"),
                entry_price=Decimal("0.5"),
                current_price=Decimal("0.5"),
                fees_paid=_ZERO,
                opened_at=_T0,
                last_updated=_T0,
                unknown_field="bad",  # type: ignore[call-arg]
            )

    def test_price_bounds_lower(self) -> None:
        with pytest.raises(ValidationError):
            PositionState(
                instrument_id="x",
                side=Side.LONG,
                size=Decimal("1"),
                entry_price=Decimal("-0.1"),
                current_price=Decimal("0.5"),
                fees_paid=_ZERO,
                opened_at=_T0,
                last_updated=_T0,
            )

    def test_price_bounds_upper(self) -> None:
        with pytest.raises(ValidationError):
            PositionState(
                instrument_id="x",
                side=Side.LONG,
                size=Decimal("1"),
                entry_price=Decimal("1.1"),
                current_price=Decimal("0.5"),
                fees_paid=_ZERO,
                opened_at=_T0,
                last_updated=_T0,
            )

    def test_decimal_precision_retained(self) -> None:
        pos = _position(entry_price=Decimal("0.123456789"))
        assert pos.entry_price == Decimal("0.123456789")

    def test_size_zero_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            PositionState(
                instrument_id="x",
                side=Side.LONG,
                size=Decimal("-1"),
                entry_price=Decimal("0.5"),
                current_price=Decimal("0.5"),
                fees_paid=_ZERO,
                opened_at=_T0,
                last_updated=_T0,
            )


class TestPortfolioState:
    def test_empty_positions_equity_equals_cash(self) -> None:
        state = PortfolioState(
            timestamp=_T0,
            cash=Decimal("10000"),
            positions={},
            total_pnl=_ZERO,
            total_fees=_ZERO,
            equity=Decimal("10000"),
        )
        assert state.equity == state.cash

    def test_with_positions(self) -> None:
        pos = _position(unrealised_pnl=Decimal("50"))
        state = PortfolioState(
            timestamp=_T0,
            cash=Decimal("9000"),
            positions={"a": pos},
            total_pnl=Decimal("50"),
            total_fees=_ZERO,
            equity=Decimal("9050"),  # cash + unrealised
        )
        assert state.positions["a"].side == Side.LONG

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioState(
                timestamp=_T0,
                cash=Decimal("100"),
                equity=Decimal("100"),
                mystery="field",  # type: ignore[call-arg]
            )

    def test_serialisation_round_trip(self) -> None:
        state = PortfolioState(
            timestamp=_T0,
            cash=Decimal("500"),
            positions={},
            total_pnl=_ZERO,
            total_fees=_ZERO,
            equity=Decimal("500"),
        )
        dumped = state.model_dump(mode="json")
        restored = PortfolioState.model_validate(dumped)
        assert restored.cash == state.cash
