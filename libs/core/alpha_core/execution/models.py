"""Execution models for the event-driven backtester.

Defines the typed objects that flow through the R3 backtester's execution
pipeline:

- :class:`BacktestOrderIntent` — strategy's desired trade (PM-optimised schema)
- :class:`SimulatedFill` — result of simulated execution
- :class:`FeeSchedule` — per-venue fee model

These models are intentionally separate from the strategy-framework
``OrderIntent`` (which lives in ``alpha_core.strategy_framework.models``)
to avoid coupling the research backtester's simpler schema with the live
execution layer's full lifecycle model.

Prices are in prediction-market probability space ``[0, 1]``.
All monetary values use :class:`~decimal.Decimal` for exact arithmetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alpha_core.portfolio.models import Side

_ZERO = Decimal("0")
_ONE = Decimal("1")


class BacktestOrderIntent(BaseModel):
    """Strategy's desired trade in the event-driven backtester.

    ``limit_price`` must be supplied for LIMIT orders and must be in ``[0, 1]``.
    MARKET orders fill at the last-known trade price (or mid-market fallback).
    """

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    side: Side
    size: Decimal = Field(gt=_ZERO, description="Number of contracts (positive).")
    order_type: Literal["market", "limit"] = "limit"
    limit_price: Decimal | None = Field(
        default=None,
        ge=_ZERO,
        le=_ONE,
        description="Required for LIMIT orders; ignored for MARKET orders.",
    )
    time_in_force: Literal["ioc", "gtc"] = "ioc"

    @model_validator(mode="after")
    def _validate_limit_price(self) -> BacktestOrderIntent:
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders.")
        return self


class SimulatedFill(BaseModel):
    """Result of simulated order execution in the backtester.

    ``slippage = fill_price − reference_price`` (positive = adverse for longs,
    negative = adverse for shorts).
    """

    model_config = ConfigDict(extra="forbid")

    order: BacktestOrderIntent
    fill_price: Decimal = Field(ge=_ZERO, le=_ONE)
    fill_size: Decimal = Field(gt=_ZERO)
    fee: Decimal = Field(default=_ZERO, ge=_ZERO)
    timestamp: datetime
    slippage: Decimal = Field(default=_ZERO)


class FeeSchedule(BaseModel):
    """Per-venue fee model for backtesting.

    All rates are in basis points (1 bps = 0.01%).  Set to zero to simulate
    a fee-free environment.

    ``resolution_fee_bps`` is prediction-market-specific: a fee charged on the
    gross resolution payoff (size × resolved_price).
    """

    model_config = ConfigDict(extra="forbid")

    maker_fee_bps: Decimal = Field(default=_ZERO, ge=_ZERO)
    taker_fee_bps: Decimal = Field(default=_ZERO, ge=_ZERO)
    per_contract_fee: Decimal = Field(
        default=_ZERO,
        ge=_ZERO,
        description="Flat fee per contract regardless of price.",
    )
    resolution_fee_bps: Decimal = Field(
        default=_ZERO,
        ge=_ZERO,
        description="Fee (bps) charged on the gross resolution payoff.",
    )

    def taker_fee(self, notional: Decimal) -> Decimal:
        """Compute taker fee on a given notional value."""
        return (notional * self.taker_fee_bps / Decimal("10000")).quantize(
            Decimal("0.000001")
        )

    def maker_fee(self, notional: Decimal) -> Decimal:
        """Compute maker fee on a given notional value."""
        return (notional * self.maker_fee_bps / Decimal("10000")).quantize(
            Decimal("0.000001")
        )

    def resolution_fee(self, payoff: Decimal) -> Decimal:
        """Compute resolution fee on a gross resolution payoff."""
        return (payoff * self.resolution_fee_bps / Decimal("10000")).quantize(
            Decimal("0.000001")
        )


__all__ = ["BacktestOrderIntent", "FeeSchedule", "SimulatedFill"]
