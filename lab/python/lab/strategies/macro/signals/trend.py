"""Trend signal adapter for the macro signal interface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from lab.features.macro.ts_trend import compute_ts_trend_scores
from lab.strategies.macro.signals.base import Signal, SignalMeta, SignalState


class TrendSignal(Signal):
    """Week-2 trend model wrapped in the `Signal` interface."""

    name = "ts_trend"

    def __init__(
        self,
        *,
        method: str = "ma_cross",
        lookback_days: int = 252,
        fast: int = 20,
        slow: int = 120,
    ) -> None:
        super().__init__()
        self.method = method
        self.lookback_days = int(lookback_days)
        self.fast = int(fast)
        self.slow = int(slow)

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> TrendSignal:
        return cls(
            method=str(cfg.get("method", "ma_cross")),
            lookback_days=int(cfg.get("lookback_days", 252)),
            fast=int(cfg.get("fast", 20)),
            slow=int(cfg.get("slow", 120)),
        )

    def _compute(
        self,
        prices: pd.DataFrame,
        macro: pd.DataFrame | None,
        meta: SignalMeta = None,
        *,
        state: SignalState = None,
    ) -> pd.DataFrame:
        del macro, meta, state
        return compute_ts_trend_scores(
            prices,
            lookback_days=self.lookback_days,
            method=self.method,
            fast=self.fast,
            slow=self.slow,
        )

