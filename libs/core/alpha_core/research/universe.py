"""Point-in-time universe management built from MarketMaster history."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

import alpha_core.instruments.master as master_mod
import alpha_core.instruments.models as instrument_models
import alpha_core.utils.time as time_utils


class UniverseSnapshot(BaseModel):
    """Point-in-time snapshot of tradeable instruments."""

    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    instruments: list[str]  # Canonical outcome IDs
    markets: list[str]  # Canonical market IDs
    venue_breakdown: dict[str, int]  # Count per venue
    filters_applied: dict[str, Any]  # Lifecycle, volume, quality filters


class UniverseManager:
    """Builds point-in-time universes from a MarketMaster registry.

    Point-in-time logic
    -------------------
    ``MarketMaster`` keeps a history of canonical market versions keyed by
    ``last_updated``. ``UniverseManager`` reconstructs the universe at time *t*
    from the latest stored version whose ``last_updated <= t``. When the market
    is already known via ``first_seen`` but the first stored snapshot arrives
    slightly later, the manager falls back to a conservative pre-snapshot
    projection that strips future liquidity/volume values.
    """

    def __init__(
        self,
        master: master_mod.MarketMaster,
        *,
        lifecycle_filter: list[instrument_models.MarketLifecycle] | None = None,
        min_volume: Decimal | None = None,
        min_liquidity: Decimal | None = None,
        venues: list[str] | None = None,
    ) -> None:
        self._master = master
        self._lifecycle_filter: list[instrument_models.MarketLifecycle] = (
            lifecycle_filter
            if lifecycle_filter is not None
            else [instrument_models.MarketLifecycle.ACTIVE]
        )
        self._min_volume = min_volume
        self._min_liquidity = min_liquidity
        self._venues: list[str] | None = (
            [v.lower().strip() for v in venues] if venues is not None else None
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot_at(self, as_of: datetime) -> UniverseSnapshot:
        """Return the universe as it would have appeared at *as_of*.

        No data discovered after *as_of* (``market.first_seen > as_of``)
        is included in the result.
        """
        as_of_utc = time_utils.ensure_utc(as_of)
        markets_in_scope = sorted(self._filter_markets(as_of_utc))

        instrument_ids: list[str] = []
        market_ids: list[str] = []
        venue_counts: dict[str, int] = defaultdict(int)

        for canonical_market_id, market in markets_in_scope:
            market_ids.append(canonical_market_id)
            venue_counts[market.venue] += len(market.outcomes)
            instrument_ids.extend(outcome.canonical_id for outcome in market.outcomes)

        return UniverseSnapshot(
            as_of=as_of_utc,
            instruments=instrument_ids,
            markets=market_ids,
            venue_breakdown=dict(venue_counts),
            filters_applied=self._describe_filters(),
        )

    def time_series(
        self,
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[UniverseSnapshot]:
        """Return a series of universe snapshots over *[start, end]*.

        Args:
            start:     Series start (inclusive).
            end:       Series end (inclusive).
            frequency: Pandas-compatible offset alias, e.g. ``"1d"``, ``"1h"``,
                       ``"6h"``.  Defaults to daily.

        Returns:
            Ordered list of :class:`UniverseSnapshot` objects, one per grid point.
        """
        import pandas as pd  # type: ignore[import-untyped]

        start_utc = time_utils.ensure_utc(start)
        end_utc = time_utils.ensure_utc(end)
        # Normalise shorthand aliases to avoid pandas DeprecationWarnings
        freq = frequency.replace("d", "D") if frequency.lower().endswith("d") else frequency
        grid = pd.date_range(start=start_utc, end=end_utc, freq=freq, tz="UTC")
        return [self.snapshot_at(ts.to_pydatetime()) for ts in grid]

    def change_points(
        self,
        start: datetime,
        end: datetime,
    ) -> list[datetime]:
        """Return the ordered timestamps where universe membership can change.

        Under the current market-master heuristic, membership changes only when
        a market is first discovered or when a resolved market reaches its
        resolution timestamp. Capturing these timestamps is sufficient for
        exact snapshot lookup without storing a daily union.
        """
        start_utc = time_utils.ensure_utc(start)
        end_utc = time_utils.ensure_utc(end)
        points: set[datetime] = {start_utc, end_utc}

        markets = self._master.snapshot()["markets"]
        if not isinstance(markets, dict):
            return sorted(points)
        for canonical_id in markets:
            for market in self._master.get_market_history(str(canonical_id)):
                for timestamp in (market.first_seen, market.last_updated, market.resolution_date):
                    if timestamp is None:
                        continue
                    timestamp_utc = time_utils.ensure_utc(timestamp)
                    if start_utc <= timestamp_utc <= end_utc:
                        points.add(timestamp_utc)

        return sorted(points)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _effective_lifecycle_at(
        self,
        market: instrument_models.MarketSpec,
        as_of: datetime,
    ) -> instrument_models.MarketLifecycle:
        """Approximate market lifecycle at *as_of* using resolution_date heuristic."""
        if (
            market.lifecycle == instrument_models.MarketLifecycle.RESOLVED
            and market.resolution_date is not None
        ):
            resolution_utc = time_utils.ensure_utc(market.resolution_date)
            if resolution_utc > as_of:
                # Market resolved after as_of — treat as ACTIVE at that point.
                return instrument_models.MarketLifecycle.ACTIVE
        return market.lifecycle

    def _filter_markets(self, as_of: datetime) -> list[tuple[str, instrument_models.MarketSpec]]:
        """Return (canonical_id, MarketSpec) pairs that pass all filters at *as_of*."""
        results: list[tuple[str, instrument_models.MarketSpec]] = []

        for canonical_id, market in self._master.iter_markets_at(as_of):
            # --- Temporal gate: only markets discovered by as_of ---
            first_seen_utc = time_utils.ensure_utc(market.first_seen)
            if first_seen_utc > as_of:
                continue

            # --- Venue filter ---
            if self._venues is not None and market.venue not in self._venues:
                continue

            # --- Lifecycle filter (heuristic point-in-time) ---
            effective_lifecycle = self._effective_lifecycle_at(market, as_of)
            if effective_lifecycle not in self._lifecycle_filter:
                continue

            # --- Volume filter ---
            if self._min_volume is not None and (
                market.volume is None or market.volume < self._min_volume
            ):
                continue

            # --- Liquidity filter ---
            if self._min_liquidity is not None and (
                market.liquidity is None or market.liquidity < self._min_liquidity
            ):
                continue

            results.append((canonical_id, market))

        return results

    def _describe_filters(self) -> dict[str, Any]:
        return {
            "lifecycle": [lc.value for lc in self._lifecycle_filter],
            "min_volume": str(self._min_volume) if self._min_volume is not None else None,
            "min_liquidity": str(self._min_liquidity) if self._min_liquidity is not None else None,
            "venues": self._venues,
        }


__all__ = ["UniverseManager", "UniverseSnapshot"]
