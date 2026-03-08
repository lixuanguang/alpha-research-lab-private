"""ProbabilityMomentumStrategy — event-driven implied-probability momentum.

Signal logic:

    momentum_t = mid_price_t - mid_price_{t-window}

* If momentum_t > threshold  → BUY (go long)
* If momentum_t < -threshold → SELL (go short / exit long)
* Otherwise                  → no action

One open position per instrument is maintained; the strategy will not add to
an existing position in the same direction.

Compatible with :class:`~apps.research.backtester.engine.EventBacktestEngine`.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal

import alpha_core.execution.models as exec_models
import alpha_core.portfolio.models as portfolio_models
import apps.research.backtester.strategy as strategy_mod

_ZERO = Decimal("0")
_DEFAULT_SIZE = Decimal("10")


class ProbabilityMomentumStrategy(strategy_mod.Strategy):
    """Go long/short on implied-probability rate-of-change.

    Args:
        momentum_threshold: Minimum absolute momentum to trigger a trade.
        window: Look-back window (number of *trade events per instrument*)
            used to measure momentum.
        size: Number of contracts per order.
    """

    def __init__(
        self,
        momentum_threshold: float = 0.02,
        window: int = 20,
        size: Decimal = _DEFAULT_SIZE,
    ) -> None:
        self._threshold = Decimal(str(momentum_threshold))
        self._window = max(2, window)
        self._size = size
        # instrument_id → deque of recent mid-prices (bounded to window)
        self._price_history: dict[str, deque[Decimal]] = defaultdict(
            lambda: deque(maxlen=self._window)
        )

    @property
    def name(self) -> str:
        return f"prob_momentum_t{self._threshold}_w{self._window}"

    # ------------------------------------------------------------------
    # Strategy lifecycle
    # ------------------------------------------------------------------

    def on_init(self, universe: list[str]) -> None:
        for inst in universe:
            self._price_history[inst]  # pre-warm deque

    def on_data(
        self,
        timestamp: datetime,
        state: strategy_mod.StrategyState,
    ) -> list[exec_models.BacktestOrderIntent]:
        orders: list[exec_models.BacktestOrderIntent] = []

        for instrument_id, price in state.latest_prices.items():
            if instrument_id not in state.universe:
                continue

            history = self._price_history[instrument_id]
            history.append(price)

            if len(history) < self._window:
                continue  # not enough data yet

            momentum = price - history[0]

            # Current exposure
            position = state.portfolio.positions.get(instrument_id)
            current_side: portfolio_models.Side | None = position.side if position else None

            if momentum > self._threshold and current_side != portfolio_models.Side.LONG:
                orders.append(
                    exec_models.BacktestOrderIntent(
                        instrument_id=instrument_id,
                        side=portfolio_models.Side.LONG,
                        size=self._size,
                        order_type="market",
                    )
                )
            elif momentum < -self._threshold and current_side != portfolio_models.Side.SHORT:
                orders.append(
                    exec_models.BacktestOrderIntent(
                        instrument_id=instrument_id,
                        side=portfolio_models.Side.SHORT,
                        size=self._size,
                        order_type="market",
                    )
                )

        return orders

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        self._price_history.pop(instrument_id, None)


__all__ = ["ProbabilityMomentumStrategy"]
