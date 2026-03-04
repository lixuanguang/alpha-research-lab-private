"""Minimal strategy engine orchestration skeleton.

Wires the five strategy-framework protocols into a single synchronous cycle:

  ``UniverseModel`` → ``AlphaModel`` → ``PortfolioConstructionModel``
      → ``RiskModel`` → ``ExecutionModel``

This is a *contract-level* skeleton.  Full backtest and live implementations
are deferred to the Research Plane MVP and Live Plane MVP stages respectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import alpha_core.strategy_framework.interfaces as strategy_interfaces
import alpha_core.strategy_framework.models as strategy_models


@dataclass
class StrategyEngine:
    """Typed container that wires the five strategy protocol components.

    Calling :meth:`step` runs one synchronous pipeline cycle and returns the
    list of :class:`~alpha_core.strategy_framework.models.OrderIntent` objects
    produced.  The engine does *not* submit orders — that responsibility belongs
    to the venue adapter in the Live or backtest runtime.

    Example::

        engine = StrategyEngine(
            universe=MyUniverse(),
            alpha=MyAlpha(),
            portfolio=MyPortfolio(),
            risk=MyRisk(),
            execution=MyExecution(),
        )
        orders = engine.step(state)
    """

    universe: strategy_interfaces.UniverseModel
    alpha: strategy_interfaces.AlphaModel
    portfolio: strategy_interfaces.PortfolioConstructionModel
    risk: strategy_interfaces.RiskModel
    execution: strategy_interfaces.ExecutionModel
    _cycle_count: int = field(default=0, init=False, repr=False)

    def step(self, state: strategy_models.MarketState) -> list[strategy_models.OrderIntent]:
        """Run one full strategy cycle and return the resulting order intents.

        Steps:
        1. Universe selection — narrows ``state.universe`` in place.
        2. Alpha generation — produces signals for the selected universe.
        3. Portfolio construction — maps signals to position targets.
        4. Risk application — enforces constraints on targets.
        5. Execution translation — converts targets to order intents.
        """
        state.universe = self.universe.select(state)
        signals = self.alpha.generate(state)
        targets = self.portfolio.targets(signals, state)
        targets = self.risk.apply(targets, state)
        orders = self.execution.create_orders(targets, state)
        self._cycle_count += 1
        return orders

    @property
    def cycle_count(self) -> int:
        """Number of completed pipeline cycles since engine creation."""
        return self._cycle_count
