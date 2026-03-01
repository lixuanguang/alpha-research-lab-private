"""Outcome selection strategy for streaming connectors."""

from __future__ import annotations

from decimal import Decimal

import alpha_core.instruments.master as instruments_master
import alpha_core.instruments.models as instrument_models


class OutcomeSelector:
    """Selects which outcomes to stream based on volume, liquidity, and lifecycle.

    Args:
        master:           Market registry to query.
        min_volume:       Minimum market volume; markets with ``None`` volume pass.
        min_liquidity:    Minimum market liquidity; markets with ``None`` liquidity pass.
        lifecycle_filter: Only markets whose lifecycle is in this list are included.
    """

    def __init__(
        self,
        master: instruments_master.MarketMaster,
        *,
        min_volume: Decimal = Decimal("0"),
        min_liquidity: Decimal = Decimal("0"),
        lifecycle_filter: list[instrument_models.MarketLifecycle] | None = None,
    ) -> None:
        self._master = master
        self._min_volume = min_volume
        self._min_liquidity = min_liquidity
        self._lifecycle_filter: list[instrument_models.MarketLifecycle] = (
            lifecycle_filter
            if lifecycle_filter is not None
            else [instrument_models.MarketLifecycle.ACTIVE]
        )

    def select(self, venue: str) -> list[str]:
        """Return canonical outcome_ids worth streaming for *venue*.

        Each lifecycle in ``lifecycle_filter`` is queried separately and the
        results are merged so that the returned list remains deterministic
        (sorted by canonical outcome id).
        """
        outcome_ids: list[str] = []
        seen: set[str] = set()

        for lifecycle in self._lifecycle_filter:
            markets = self._master.search(venue=venue, lifecycle=lifecycle)
            for market in markets:
                if not self._passes_volume(market):
                    continue
                if not self._passes_liquidity(market):
                    continue
                for outcome in market.outcomes:
                    if outcome.canonical_id not in seen:
                        seen.add(outcome.canonical_id)
                        outcome_ids.append(outcome.canonical_id)

        return sorted(outcome_ids)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _passes_volume(self, market: instrument_models.MarketSpec) -> bool:
        if market.volume is None:
            return True
        return market.volume >= self._min_volume

    def _passes_liquidity(self, market: instrument_models.MarketSpec) -> bool:
        if market.liquidity is None:
            return True
        return market.liquidity >= self._min_liquidity


__all__ = ["OutcomeSelector"]
