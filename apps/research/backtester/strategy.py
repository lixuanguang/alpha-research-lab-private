"""Strategy ABC and StrategyState for the event-driven backtester.

Defines the pluggable strategy interface used by :class:`EventBacktestEngine`:

- :class:`StrategyState` — snapshot of market + portfolio state visible to the
  strategy at each event.
- :class:`Strategy` — abstract base class every backtest strategy must implement.

Framework alignment
-------------------
:class:`Strategy` is intentionally distinct from the live-plane
``alpha_core.strategy_framework`` protocol set.  The backtester's simpler
callback model maps cleanly onto the live-plane later by implementing the
five framework protocols inside each live strategy class — the research
contract and live contract stay loosely coupled without forcing premature
complexity on research strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

import alpha_core.execution.models as exec_models
import alpha_core.portfolio.models as portfolio_models


class StrategyState(BaseModel):
    """Read-only view of the world available to the strategy at one event.

    ``features`` maps ``instrument_id → {feature_name → value}``.  It is
    ``None`` when no pre-computed feature set was supplied to the engine.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    timestamp: datetime
    portfolio: portfolio_models.PortfolioState
    latest_prices: dict[str, Decimal]
    """Most recent observed trade price per instrument ID."""
    features: dict[str, dict[str, float]] | None = None
    """Per-instrument feature values, or ``None`` if no feature set loaded."""
    universe: list[str]
    """Canonical instrument IDs active in the current simulation window."""


class Strategy(ABC):
    """Abstract base class for all event-driven backtest strategies.

    Lifecycle callbacks:

    1. :meth:`on_init` — called once before replay starts.
    2. :meth:`on_data` — called on each trade event with current world state.
    3. :meth:`on_resolution` — called when a market resolves (0 or 1 payoff).

    Strategies return :class:`~alpha_core.execution.models.BacktestOrderIntent`
    objects from :meth:`on_data`.  The engine simulates fills, updates the
    portfolio, and passes the updated :class:`StrategyState` to the next call.

    Example::

        class BuyAndHold(Strategy):
            name = "buy_and_hold"

            def on_init(self, universe): pass

            def on_data(self, timestamp, state):
                if not state.portfolio.positions:
                    return [BacktestOrderIntent(
                        instrument_id=state.universe[0],
                        side=Side.LONG, size=Decimal("10"),
                        order_type="market",
                    )]
                return []

            def on_resolution(self, instrument_id, resolved_price): pass
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy identifier."""

    @abstractmethod
    def on_init(self, universe: list[str]) -> None:
        """Called once with the full instrument universe before replay starts."""

    @abstractmethod
    def on_data(
        self,
        timestamp: datetime,
        state: StrategyState,
    ) -> list[exec_models.BacktestOrderIntent]:
        """Called on each trade event.

        Args:
            timestamp: Event timestamp (``ts_event`` from the trade table).
            state: Current portfolio and market state.

        Returns:
            List of order intents to attempt.  Empty list = no action.
        """

    @abstractmethod
    def on_resolution(
        self,
        instrument_id: str,
        resolved_price: Decimal,
    ) -> None:
        """Called when a prediction-market resolves.

        Args:
            instrument_id: Canonical instrument ID that just resolved.
            resolved_price: Resolution payoff — ``Decimal("0")`` or ``Decimal("1")``.
        """


__all__ = ["Strategy", "StrategyState"]
