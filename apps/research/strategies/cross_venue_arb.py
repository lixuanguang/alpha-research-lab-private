"""CrossVenueArbStrategy — event-driven cross-venue spread arbitrage.

Signal logic:

    spread = max_price(venues for same question) - min_price(venues for same question)

When ``spread > threshold``:

* BUY the cheapest venue's instrument (long)
* SELL the most expensive venue's instrument (short)

Instrument IDs are expected to follow the ``venue:question_slug`` convention
(split on ``:``) so the strategy can group the same question across venues.

Compatible with :class:`~apps.research.backtester.engine.EventBacktestEngine`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import alpha_core.execution.models as exec_models
import alpha_core.portfolio.models as portfolio_models
from apps.research.backtester.strategy import Strategy, StrategyState

_ZERO = Decimal("0")
_DEFAULT_SIZE = Decimal("5")


def _question_slug(instrument_id: str) -> str:
    """Return the question part of a ``venue:question_slug`` instrument ID.

    Falls back to the full instrument ID if no ``:`` separator is present.
    """
    _, _, slug = instrument_id.partition(":")
    return slug if slug else instrument_id


class CrossVenueArbStrategy(Strategy):
    """Buy cheaper / sell more expensive when the cross-venue spread exceeds *threshold*.

    Args:
        spread_threshold: Minimum bid-ask spread (in probability units) that
            triggers an arb trade.
        size: Number of contracts per leg.
    """

    def __init__(
        self,
        spread_threshold: float = 0.05,
        size: Decimal = _DEFAULT_SIZE,
    ) -> None:
        self._threshold = Decimal(str(spread_threshold))
        self._size = size

    @property
    def name(self) -> str:
        return f"cross_venue_arb_t{self._threshold}"

    # ------------------------------------------------------------------
    # Strategy lifecycle
    # ------------------------------------------------------------------

    def on_init(self, universe: list[str]) -> None:
        pass  # stateless per-event strategy

    def on_data(
        self,
        timestamp: datetime,
        state: StrategyState,
    ) -> list[exec_models.BacktestOrderIntent]:
        # Group active instruments by question slug
        by_question: dict[str, dict[str, Decimal]] = defaultdict(dict)
        for inst_id in state.universe:
            price = state.latest_prices.get(inst_id)
            if price is not None:
                by_question[_question_slug(inst_id)][inst_id] = price

        orders: list[exec_models.BacktestOrderIntent] = []

        for _slug, venue_prices in by_question.items():
            if len(venue_prices) < 2:
                continue  # need at least two venues to arb

            cheap_id = min(venue_prices, key=lambda k: venue_prices[k])
            dear_id = max(venue_prices, key=lambda k: venue_prices[k])

            spread = venue_prices[dear_id] - venue_prices[cheap_id]
            if spread <= self._threshold:
                continue

            # Only trade if we don't already hold both legs
            cheap_pos = state.portfolio.positions.get(cheap_id)
            dear_pos = state.portfolio.positions.get(dear_id)

            if cheap_pos is None or cheap_pos.side != portfolio_models.Side.LONG:
                orders.append(
                    exec_models.BacktestOrderIntent(
                        instrument_id=cheap_id,
                        side=portfolio_models.Side.LONG,
                        size=self._size,
                        order_type="market",
                    )
                )

            if dear_pos is None or dear_pos.side != portfolio_models.Side.SHORT:
                orders.append(
                    exec_models.BacktestOrderIntent(
                        instrument_id=dear_id,
                        side=portfolio_models.Side.SHORT,
                        size=self._size,
                        order_type="market",
                    )
                )

        return orders

    def on_resolution(self, instrument_id: str, resolved_price: Decimal) -> None:
        pass  # no per-instrument state to clean up


__all__ = ["CrossVenueArbStrategy"]
