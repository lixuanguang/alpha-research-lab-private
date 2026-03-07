"""VecStrategy ABC — vectorized strategy interface for the DataFrame-native backtester.

:class:`VecStrategy` is the pluggable strategy contract for
:class:`~apps.research.backtester.vec_engine.VecBacktestEngine`.  It operates
on cross-sectional ``pd.DataFrame`` objects rather than single event callbacks,
enabling fast vectorized computation over entire rebalance periods.

Usage::

    class MyStrategy(VecStrategy):
        name = "my_strategy"

        def generate_signals(self, features, universe):
            # features has columns: [ts_event, instrument_id, feat_a, feat_b, ...]
            # Return DataFrame with: instrument_id, signal
            df = features.groupby("instrument_id").last().reset_index()
            df["signal"] = df["feat_a"].clip(-1, 1)
            return df[["instrument_id", "signal"]]

        def size_positions(self, signals, portfolio_value, max_positions):
            # signals has columns: instrument_id, signal
            # Return DataFrame with: instrument_id, target_weight
            from alpha_core.portfolio.sizing import EqualWeightSizer
            return EqualWeightSizer().size(signals, portfolio_value, max_positions)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

import pandas as pd


class VecStrategy(ABC):
    """Abstract base class for vectorized backtest strategies.

    The engine calls :meth:`generate_signals` at each rebalance point with
    a feature snapshot, then calls :meth:`size_positions` to convert signals
    into target portfolio weights.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique human-readable strategy identifier."""

    @abstractmethod
    def generate_signals(
        self,
        features: pd.DataFrame,
        universe: list[str],
    ) -> pd.DataFrame:
        """Generate trading signals from the current feature snapshot.

        Args:
            features: Feature matrix for the current rebalance period.
                Columns include ``instrument_id`` plus all registered features.
                Contains only rows up to the current rebalance timestamp
                (no look-ahead).
            universe: Canonical list of active instrument IDs at this time.

        Returns:
            DataFrame with columns:

            * ``instrument_id`` (str) — canonical instrument identifier.
            * ``signal`` (float) — directional signal.  Positive = long,
              negative = short, 0 = flat.  Should be in ``[-1, 1]`` but the
              sizer will normalise if required.
        """

    @abstractmethod
    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        """Convert signals into target portfolio weights.

        Args:
            signals: DataFrame returned by :meth:`generate_signals`
                (columns: ``instrument_id``, ``signal``).
            portfolio_value: Current portfolio equity in dollars.
            max_positions: Maximum simultaneous open positions from config.

        Returns:
            DataFrame with columns:

            * ``instrument_id`` (str) — canonical instrument identifier.
            * ``target_weight`` (float) — fraction of portfolio to allocate.
              Positive = long, negative = short.  Sum of absolute weights
              should be ≤ 1.0.
        """


__all__ = ["VecStrategy"]
