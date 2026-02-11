"""Signal ensembling utilities for macro strategies."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from lab.strategies.macro.signals.base import (
    Signal,
    SignalMeta,
    SignalState,
    align_and_clip_scores,
    normalize_scores,
)


class EnsembleSignal(Signal):
    """Weighted combination of child signal models."""

    name = "ensemble"

    def __init__(
        self,
        signals: Mapping[str, Signal],
        *,
        weights: Mapping[str, float] | None = None,
        normalize_components: bool = True,
        risk_parity_enabled: bool = False,
        risk_parity_lookback: int = 63,
        risk_parity_min_periods: int | None = None,
    ) -> None:
        super().__init__()
        if not signals:
            raise ValueError("ensemble requires at least one component signal")

        self.signals = dict(signals)
        self.normalize_components = bool(normalize_components)
        self.risk_parity_enabled = bool(risk_parity_enabled)
        self.risk_parity_lookback = int(risk_parity_lookback)
        self.risk_parity_min_periods = (
            int(risk_parity_min_periods) if risk_parity_min_periods is not None else None
        )

        names = list(self.signals)
        if weights is None:
            resolved = pd.Series(1.0, index=names, dtype=float)
        else:
            resolved = pd.Series(0.0, index=names, dtype=float)
            for name, value in weights.items():
                if name not in resolved.index:
                    raise ValueError(f"unknown ensemble weight component '{name}'")
                resolved.loc[name] = float(value)
        if np.isclose(float(resolved.abs().sum()), 0.0):
            raise ValueError("ensemble weights must have non-zero absolute sum")
        self.weights = resolved

    def fit(
        self,
        train_prices: pd.DataFrame,
        train_macro: pd.DataFrame | None,
        meta: SignalMeta = None,
    ) -> SignalState:
        states: dict[str, SignalState] = {}
        for name, signal in self.signals.items():
            states[name] = signal.fit(train_prices, train_macro, meta)
        self._state = states
        return self._state

    def _risk_parity_scalars(
        self,
        *,
        prices: pd.DataFrame,
        component_scores: Mapping[str, pd.DataFrame],
    ) -> pd.DataFrame:
        names = list(component_scores)
        index = prices.index
        if not self.risk_parity_enabled:
            return pd.DataFrame(1.0, index=index, columns=names, dtype=float)

        returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        pnl_parts: dict[str, pd.Series] = {}
        for name, scores in component_scores.items():
            lagged = scores.shift(1).fillna(0.0)
            pnl_parts[name] = lagged.mul(returns, axis=0).mean(axis=1)

        contrib = pd.DataFrame(pnl_parts, index=index).fillna(0.0)
        min_periods = self.risk_parity_min_periods
        if min_periods is None:
            min_periods = max(2, self.risk_parity_lookback // 3)

        risk = contrib.rolling(self.risk_parity_lookback, min_periods=min_periods).std()
        inv_risk = 1.0 / risk.replace(0.0, np.nan)
        inv_risk = inv_risk.replace([np.inf, -np.inf], np.nan)

        # Normalize by row so average scaling stays around 1.0.
        inv_risk = inv_risk.div(inv_risk.mean(axis=1), axis=0)
        return inv_risk.fillna(1.0)

    def _compute(
        self,
        prices: pd.DataFrame,
        macro: pd.DataFrame | None,
        meta: SignalMeta = None,
        *,
        state: SignalState = None,
    ) -> pd.DataFrame:
        del state
        components: dict[str, pd.DataFrame] = {}
        for name, signal in self.signals.items():
            score_df = signal.compute(prices, macro, meta)
            aligned = align_and_clip_scores(score_df, prices)
            if self.normalize_components:
                aligned = normalize_scores(aligned)
            components[name] = aligned

        scalars = self._risk_parity_scalars(prices=prices, component_scores=components)

        combined = pd.DataFrame(0.0, index=prices.index, columns=prices.columns, dtype=float)
        for name, score_df in components.items():
            w = float(self.weights.loc[name])
            if self.risk_parity_enabled:
                weighted = score_df.mul(scalars[name] * w, axis=0)
            else:
                weighted = score_df * w
            combined = combined.add(weighted, fill_value=0.0)

        if self.risk_parity_enabled:
            denom = scalars.mul(self.weights.abs(), axis=1).sum(axis=1).replace(0.0, np.nan)
            combined = combined.div(denom, axis=0)
        else:
            denom = float(self.weights.abs().sum())
            combined = combined / denom

        return combined.replace([np.inf, -np.inf], np.nan).fillna(0.0)
