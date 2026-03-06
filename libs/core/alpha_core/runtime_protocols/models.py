"""Runtime protocol datamodels.

Typed objects exchanged across provider/router boundaries:

- ``AccountSnapshot``  — positions, balances, buying power
- ``TopOfBook``        — best bid/ask for one instrument
- ``InstrumentStatus`` — lifecycle and tradability of an instrument
- ``OrderAck``         — venue acknowledgement that an order was received
- ``OrderReject``      — venue rejection of a submitted order
- ``OrderFill``        — partial or full execution fill event
- ``OrderStatus``      — queryable order state at the venue

All models use Pydantic v2 with ``extra="forbid"``.  Prices are ``Decimal``
bounded to ``[0, 1]`` for prediction-market probability space.  Timestamps
are always UTC-aware ``datetime`` objects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FillSide(StrEnum):
    """Direction of a fill or order."""

    BUY = "buy"
    SELL = "sell"


class OrderStatusCode(StrEnum):
    """Lifecycle state of an order tracked at the venue."""

    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Account state
# ---------------------------------------------------------------------------


class AccountSnapshot(BaseModel):
    """Point-in-time view of the account: positions, balances, and buying power."""

    model_config = ConfigDict(extra="forbid")

    positions: dict[str, Decimal] = Field(
        default_factory=dict,
        description="Canonical instrument ID → net position size (signed).",
    )
    balances: dict[str, Decimal] = Field(
        default_factory=dict,
        description="Currency or asset label → available balance.",
    )
    buying_power: Decimal = Field(
        ge=Decimal("0"),
        description="Maximum total notional available for new orders.",
    )
    ts_snapshot: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
        description="UTC timestamp when this snapshot was captured.",
    )


# ---------------------------------------------------------------------------
# Market state
# ---------------------------------------------------------------------------


class TopOfBook(BaseModel):
    """Best bid/ask for one instrument at a point in time."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    best_bid: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    best_ask: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    bid_size: Decimal | None = Field(default=None, ge=Decimal("0"))
    ask_size: Decimal | None = Field(default=None, ge=Decimal("0"))
    ts_snapshot: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class InstrumentStatus(BaseModel):
    """Lifecycle and tradability status for one instrument."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    lifecycle: str = Field(
        description="Lifecycle label: 'active', 'halted', 'resolved', or 'delisted'.",
    )
    is_tradeable: bool = Field(
        description="True when orders can currently be submitted for this instrument.",
    )
    ts_snapshot: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# ---------------------------------------------------------------------------
# Execution lifecycle events
# ---------------------------------------------------------------------------


class OrderAck(BaseModel):
    """Venue acknowledgement that an order was successfully received."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, description="Venue-assigned order ID.")
    client_order_id: str | None = Field(
        default=None,
        description="Client-assigned reference ID, if provided on submission.",
    )
    instrument_id: str = Field(min_length=1)
    ts_acked: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional venue-specific diagnostic fields.",
    )


class OrderReject(BaseModel):
    """Venue rejection of a submitted order."""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = Field(
        default=None,
        description="Venue-assigned order ID; may be absent if rejected before assignment.",
    )
    client_order_id: str | None = None
    instrument_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, description="Human-readable rejection reason.")
    error_code: str | None = Field(default=None, description="Venue-specific error code.")
    ts_rejected: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class OrderFill(BaseModel):
    """Partial or full fill event for an order."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1)
    fill_id: str = Field(min_length=1, description="Venue-assigned fill/trade ID.")
    instrument_id: str = Field(min_length=1)
    price: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    size: Decimal = Field(gt=Decimal("0"), description="Number of contracts filled.")
    side: FillSide
    fee: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    ts_filled: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderStatus(BaseModel):
    """Current queryable state of an order at the venue."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    status: OrderStatusCode
    filled_size: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    remaining_size: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    average_fill_price: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Volume-weighted average fill price; None if no fills yet.",
    )
    ts_updated: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
