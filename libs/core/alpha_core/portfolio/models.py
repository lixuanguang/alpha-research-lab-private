"""Portfolio state models.

Defines the typed objects that describe position and portfolio state:

- :class:`Side` — direction enum (LONG / SHORT)
- :class:`PositionState` — single-instrument position snapshot
- :class:`PortfolioState` — complete portfolio snapshot at one point in time

All monetary values use :class:`~decimal.Decimal` for exact arithmetic.
Timestamps are always UTC-aware :class:`~datetime.datetime` objects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Side(StrEnum):
    """Directional side of a position or fill."""

    LONG = "long"
    """Bought contracts — profit when price rises to 1 at resolution."""

    SHORT = "short"
    """Sold contracts — profit when price falls to 0 at resolution."""


class PositionState(BaseModel):
    """Current state of an open position in one prediction-market outcome.

    Prices are in probability space ``[0, 1]``.  Sizes are in contracts
    (typically integers but stored as :class:`~decimal.Decimal` for
    arithmetic convenience).

    ``unrealised_pnl`` is always computed as:

    * **LONG:**  ``size × (current_price − entry_price)``
    * **SHORT:** ``size × (entry_price − current_price)``
    """

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    side: Side
    size: Decimal = Field(ge=Decimal("0"), description="Number of contracts (positive).")
    entry_price: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Volume-weighted average fill price.",
    )
    current_price: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Most recent market price used for mark-to-market.",
    )
    unrealised_pnl: Decimal = Field(
        default=Decimal("0"),
        description="Open PnL at current_price.",
    )
    realised_pnl: Decimal = Field(
        default=Decimal("0"),
        description="Closed PnL from partially or fully closing the position.",
    )
    fees_paid: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
    )
    opened_at: datetime
    last_updated: datetime


class PortfolioState(BaseModel):
    """Complete portfolio snapshot at a point in time.

    ``equity = cash + sum(unrealised_pnl over all open positions) − total_fees``
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    cash: Decimal = Field(description="Remaining cash balance after all fills.")
    positions: dict[str, PositionState] = Field(
        default_factory=dict,
        description="Open positions keyed by canonical instrument ID.",
    )
    total_pnl: Decimal = Field(
        default=Decimal("0"),
        description="Realised + unrealised PnL across all positions.",
    )
    total_fees: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
    )
    equity: Decimal = Field(
        description="cash + unrealised_pnl across all open positions.",
    )


__all__ = ["PortfolioState", "PositionState", "Side"]
