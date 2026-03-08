"""Position sizing models for the vectorized backtester.

Three sizers for mapping raw signal values to portfolio target weights:

- :class:`EqualWeightSizer` — equal weight across all non-zero signal positions.
- :class:`FixedSizeSizer` — each position receives a fixed notional fraction.
- :class:`KellySizer` — Kelly criterion adapted for binary prediction markets.

All sizers return a ``pd.DataFrame`` with columns ``instrument_id`` and
``target_weight`` (floats in ``[-1, 1]``; long = positive, short = negative).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

import pandas as pd

_ZERO = Decimal("0")


class PositionSizer(ABC):
    """Abstract base class: maps signals → target portfolio weights.

    Input signals DataFrame has columns ``instrument_id`` and ``signal``
    (float; positive = long, negative = short, 0 = flat).

    Output DataFrame has columns ``instrument_id`` and ``target_weight``
    (float in ``[-1, 1]``).  The sum of absolute weights must be ≤ 1.0
    (i.e. the portfolio is always fully invested or less).
    """

    @abstractmethod
    def size(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        """Compute target weights from signals.

        Args:
            signals: DataFrame with columns ``instrument_id``, ``signal``.
            portfolio_value: Current portfolio equity (used for Kelly sizing).
            max_positions: Maximum number of simultaneous positions.

        Returns:
            DataFrame with columns ``instrument_id``, ``target_weight``.
        """


class EqualWeightSizer(PositionSizer):
    """Assign equal weight to the top-N strongest (by |signal|) instruments.

    Long signals receive positive weight; short signals receive negative weight.
    The absolute weights sum to 1.0 when at least one non-zero signal exists.
    """

    def size(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        if signals.empty or "signal" not in signals.columns:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        active = signals[signals["signal"] != 0.0].copy()
        if active.empty:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        # Select top max_positions by |signal| strength.
        active = (
            active.assign(_abs_signal=active["signal"].abs())
            .sort_values("_abs_signal", ascending=False)
            .head(max_positions)
            .drop(columns=["_abs_signal"])
        )
        n = len(active)
        weight = 1.0 / n if n > 0 else 0.0

        result = pd.DataFrame(
            {
                "instrument_id": active["instrument_id"].values,
                "target_weight": [weight if s > 0 else -weight for s in active["signal"].values],
            }
        )
        return result.reset_index(drop=True)


class FixedSizeSizer(PositionSizer):
    """Assign a fixed fractional weight to each non-zero signal instrument.

    The fraction is ``1 / max_positions`` regardless of actual signal count.
    This ensures consistent notional-per-position sizing even when the
    strategy returns fewer signals than ``max_positions``.

    Args:
        fraction: Override fraction per position.  Defaults to
            ``1 / max_positions``.  Must be in ``(0, 1]``.
    """

    def __init__(self, fraction: float | None = None) -> None:
        if fraction is not None and not (0.0 < fraction <= 1.0):
            raise ValueError(f"fraction must be in (0, 1], got {fraction}")
        self._fraction = fraction

    def size(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        if signals.empty or "signal" not in signals.columns:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        active = signals[signals["signal"] != 0.0].copy()
        if active.empty:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        frac = self._fraction if self._fraction is not None else (1.0 / max_positions)
        active = active.head(max_positions)

        result = pd.DataFrame(
            {
                "instrument_id": active["instrument_id"].values,
                "target_weight": [frac if s > 0 else -frac for s in active["signal"].values],
            }
        )
        return result.reset_index(drop=True)


class KellySizer(PositionSizer):
    """Kelly criterion adapted for binary prediction markets.

    For a binary market where the signal represents the implied probability
    ``p`` of a YES outcome:

    .. math::

        f^* = \\frac{p \\cdot b - q}{b}

    where ``b = (1 - p) / p`` (fair-odds ratio) and ``q = 1 - p``.

    Simplifying: ``f* = 2p - 1`` (for binary markets at fair odds).

    The result is clamped to ``[0, max_leverage]`` for LONG signals.
    SHORT signals use ``-(2*(1-p) - 1)`` clamped to ``[-max_leverage, 0]``.

    Args:
        max_leverage: Maximum absolute weight per position (default: 1.0).
        fractional: Apply fractional Kelly (fraction of full Kelly).  E.g.
            ``0.5`` applies half-Kelly.  Default: 1.0.
    """

    def __init__(
        self,
        max_leverage: float = 1.0,
        fractional: float = 1.0,
    ) -> None:
        if max_leverage <= 0.0:
            raise ValueError(f"max_leverage must be > 0, got {max_leverage}")
        if not (0.0 < fractional <= 1.0):
            raise ValueError(f"fractional must be in (0, 1], got {fractional}")
        self._max_leverage = max_leverage
        self._fractional = fractional

    @property
    def max_leverage(self) -> float:
        return self._max_leverage

    def size(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        if signals.empty or "signal" not in signals.columns:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        active = signals[signals["signal"] != 0.0].copy().head(max_positions)
        if active.empty:
            return pd.DataFrame(columns=["instrument_id", "target_weight"])

        weights: list[float] = []
        for sig in active["signal"].values:
            p = float(abs(sig))
            # Clamp to valid probability range (avoid division by zero at p=1)
            p = max(0.001, min(0.999, p))
            # Full Kelly for binary market: f* = 2p - 1 (long bias)
            kelly = (2.0 * p - 1.0) * self._fractional
            # Clamp to [0, max_leverage]
            kelly = max(0.0, min(self._max_leverage, kelly))
            # Assign direction from signal sign
            weights.append(kelly if sig > 0 else -kelly)

        result = pd.DataFrame(
            {
                "instrument_id": active["instrument_id"].values,
                "target_weight": weights,
            }
        )
        return result.reset_index(drop=True)


__all__ = [
    "EqualWeightSizer",
    "FixedSizeSizer",
    "KellySizer",
    "PositionSizer",
]
