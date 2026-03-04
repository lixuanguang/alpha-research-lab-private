"""Core strategy framework datamodels.

Defines the typed objects that flow through the strategy pipeline:
``MarketState`` → ``Signal`` → ``Target`` → ``OrderIntent``.

All models use Pydantic v2 with ``extra="forbid"`` for strict validation.
Prices and sizes use ``Decimal`` for exact arithmetic; timestamps are always
UTC-aware ``datetime`` objects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SignalDirection(StrEnum):
    """Directional conviction from an alpha model."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"  # explicit close / neutral


class OrderType(StrEnum):
    """Order type hint passed to the execution layer."""

    MARKET = "market"
    LIMIT = "limit"
    CANCEL = "cancel"


# ---------------------------------------------------------------------------
# MarketState
# ---------------------------------------------------------------------------


class InstrumentState(BaseModel):
    """Snapshot of a single instrument's market-facing data at one point in time."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    """Canonical ID ``venue:market_id:outcome_id``."""

    mid_price: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    best_bid: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    best_ask: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    last_trade_price: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    volume_24h: Decimal | None = Field(default=None, ge=Decimal("0"))
    open_interest: Decimal | None = Field(default=None, ge=Decimal("0"))


class MarketState(BaseModel):
    """Point-in-time snapshot of all relevant market data for one strategy cycle.

    Passed as a read-only context object through every stage of the pipeline —
    universe selection, signal generation, portfolio construction, risk, and
    execution.  Implementation layers may subclass this to attach additional
    fields without breaking protocol compatibility.
    """

    model_config = ConfigDict(extra="allow")

    as_of_utc: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
        description="Timestamp this state snapshot represents (always UTC).",
    )
    universe: list[str] = Field(
        default_factory=list,
        description="Canonical instrument IDs eligible this cycle.",
    )
    instruments: dict[str, InstrumentState] = Field(
        default_factory=dict,
        description="Per-instrument market data keyed by canonical instrument ID.",
    )
    portfolio: dict[str, Decimal] = Field(
        default_factory=dict,
        description="Current position sizes keyed by canonical instrument ID.",
    )


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------


class Signal(BaseModel):
    """Directional alpha signal for one instrument, produced by an :class:`AlphaModel`."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    direction: SignalDirection
    strength: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Magnitude of conviction in [0, 1]; 1 = maximum conviction.",
    )
    confidence: Decimal = Field(
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Model confidence in [0, 1]; may differ from strength.",
    )
    ts_generated: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional diagnostic or model-specific annotations.",
    )


# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------


class Target(BaseModel):
    """Desired position allocation for one instrument, produced by a
    :class:`PortfolioConstructionModel` and potentially modified by a
    :class:`RiskModel`.
    """

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    target_weight: Decimal | None = Field(
        default=None,
        ge=Decimal("-1"),
        le=Decimal("1"),
        description="Portfolio weight in [-1, 1]; None if using absolute sizing.",
    )
    target_size: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        description="Absolute contract size; None if using weight-based sizing.",
    )
    direction: SignalDirection = SignalDirection.FLAT
    source_signal_id: str | None = Field(
        default=None,
        description="Instrument ID of the originating signal (for traceability).",
    )
    ts_generated: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


# ---------------------------------------------------------------------------
# OrderIntent
# ---------------------------------------------------------------------------


class OrderIntent(BaseModel):
    """Concrete order produced by an :class:`ExecutionModel`, ready for pre-trade
    validation before being submitted to a venue adapter.
    """

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    order_type: OrderType = OrderType.LIMIT
    direction: SignalDirection
    size: Decimal = Field(gt=Decimal("0"))
    price_limit: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Required for LIMIT orders; None for MARKET.",
    )
    notes: str | None = None
    ts_created: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    source_target_instrument_id: str | None = Field(
        default=None,
        description="Instrument ID of the originating target (for traceability).",
    )
