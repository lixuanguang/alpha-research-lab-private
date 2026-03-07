"""BacktestResult — structured output from an event-driven backtest run."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import alpha_core.execution.models as exec_models
import alpha_core.portfolio.models as portfolio_models


class BacktestResult(BaseModel):
    """Complete result of an event-driven backtest run.

    ``backtest_id`` is a deterministic SHA-256 hex digest of the serialised
    config + strategy name, making it stable and reproducible across runs with
    identical inputs.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    backtest_id: str = Field(min_length=1)
    """Deterministic hash of config + strategy name."""

    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    """Frozen serialisation of the :class:`~apps.research.backtester.engine.EventBacktestConfig`."""

    strategy_name: str
    """Name property of the :class:`~apps.research.backtester.strategy.Strategy` instance."""

    trades: list[exec_models.SimulatedFill]
    """All simulated fills in chronological order."""

    equity_curve: list[tuple[datetime, Decimal]]
    """Chronological ``(timestamp, equity)`` snapshots recorded after each event."""

    final_portfolio: portfolio_models.PortfolioState
    """Portfolio state at the end of the backtest."""

    duration_seconds: float = Field(ge=0.0)
    """Wall-clock seconds the engine took to run."""

    event_count: int = Field(ge=0)
    """Total number of trade events processed."""


def make_backtest_id(config_dict: dict[str, Any], strategy_name: str) -> str:
    """Produce a stable 16-char hex ID for a backtest configuration."""
    payload = json.dumps(
        {"config": config_dict, "strategy": strategy_name},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


__all__ = ["BacktestResult", "make_backtest_id"]
