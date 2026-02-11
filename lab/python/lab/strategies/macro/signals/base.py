"""Base interfaces and utilities for macro signal models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

SignalMeta = Mapping[str, Any] | pd.DataFrame | None
SignalState = Mapping[str, Any] | None


def align_and_clip_scores(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """Align scores to prices and enforce the score contract."""
    aligned = scores.reindex(index=prices.index, columns=prices.columns)
    cleaned = aligned.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return cleaned.clip(-1.0, 1.0).astype(float)


def normalize_scores(
    scores: pd.DataFrame,
    *,
    by: str = "row_max_abs",
) -> pd.DataFrame:
    """Normalize score magnitudes while preserving sign."""
    if by != "row_max_abs":
        raise ValueError(f"unknown normalization method: {by!r}")

    max_abs = scores.abs().max(axis=1).replace(0.0, np.nan)
    normalized = scores.div(max_abs, axis=0)
    return normalized.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-1.0, 1.0)


class Signal(ABC):
    """Stable interface for macro signals."""

    name: str = "signal"

    def __init__(self) -> None:
        self._state: SignalState = None

    @property
    def state(self) -> SignalState:
        return self._state

    def fit(
        self,
        train_prices: pd.DataFrame,
        train_macro: pd.DataFrame | None,
        meta: SignalMeta = None,
    ) -> SignalState:
        self._state = self._fit(train_prices, train_macro, meta)
        return self._state

    def _fit(
        self,
        train_prices: pd.DataFrame,
        train_macro: pd.DataFrame | None,
        meta: SignalMeta = None,
    ) -> SignalState:
        return None

    def compute(
        self,
        prices: pd.DataFrame,
        macro: pd.DataFrame | None,
        meta: SignalMeta = None,
    ) -> pd.DataFrame:
        raw = self._compute(prices, macro, meta, state=self._state)
        return align_and_clip_scores(raw, prices)

    @abstractmethod
    def _compute(
        self,
        prices: pd.DataFrame,
        macro: pd.DataFrame | None,
        meta: SignalMeta = None,
        *,
        state: SignalState = None,
    ) -> pd.DataFrame:
        """Return raw score panel before alignment/clipping."""

