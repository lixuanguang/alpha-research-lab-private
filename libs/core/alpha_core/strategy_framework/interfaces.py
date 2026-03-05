"""Strategy framework protocol interfaces.

Contract-only module: implementation is deferred to Research and Live stages.
These protocols define the pluggable strategy graph shared by backtest, optimize,
and live runtimes — preventing interface drift between stages.

Usage::

    from alpha_core.strategy_framework.interfaces import AlphaModel, RiskModel
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import alpha_core.strategy_framework.models as strategy_models


@runtime_checkable
class UniverseModel(Protocol):
    """Select the tradeable instrument set given current market state.

    Returns a list of canonical instrument IDs (``venue:market_id:outcome_id``)
    that are eligible for signal generation this cycle.
    """

    def select(self, state: strategy_models.MarketState) -> list[str]: ...


@runtime_checkable
class AlphaModel(Protocol):
    """Generate directional signals for instruments in the current universe.

    Receives the market state (which already reflects the filtered universe)
    and returns zero or more :class:`Signal` objects ranked by conviction.
    """

    def generate(self, state: strategy_models.MarketState) -> list[strategy_models.Signal]: ...


@runtime_checkable
class PortfolioConstructionModel(Protocol):
    """Convert alpha signals into normalized position targets.

    The implementation maps signals onto desired allocations, handling
    sizing, diversification, and position-count constraints.
    """

    def targets(
        self,
        signals: list[strategy_models.Signal],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]: ...


@runtime_checkable
class RiskModel(Protocol):
    """Apply risk constraints to a list of position targets.

    Modifies or drops targets to enforce exposure limits, max-loss guards,
    concentration caps, and any other pre-trade risk rules.
    Returns the risk-adjusted target list (may be a strict subset).
    """

    def apply(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]: ...


@runtime_checkable
class ExecutionModel(Protocol):
    """Translate risk-adjusted targets into concrete order intents.

    Handles scheduling, slicing, and routing decisions.  The output is a
    list of :class:`OrderIntent` objects ready for pre-trade validation.
    """

    def create_orders(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.OrderIntent]: ...
