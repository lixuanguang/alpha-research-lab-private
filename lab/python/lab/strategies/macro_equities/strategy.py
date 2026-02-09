"""
lab.strategies.macro_equities.strategy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Registered strategy function that wires together signals → composite score →
portfolio rules.

This is the entry-point the backtest engine calls at each rebalance date.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from lab.core.logging import get_logger
from lab.core.strategy_registry import register
from lab.strategies.macro_equities.baseline_signals import (
    inverse_volatility,
    momentum_12_1,
    trend_sma,
)
from lab.strategies.macro_equities.portfolio_rules import (
    apply_regime_overlay,
    top_n_equal_weight,
)
from lab.strategies.macro_equities.regimes import dual_ma_regime

if TYPE_CHECKING:
    from lab.core.config import ExperimentConfig

log = get_logger("strategies.macro_equities")


@register("macro_equities.baseline")
def baseline_strategy(config: ExperimentConfig, prices: pd.DataFrame) -> pd.Series:
    """Composite momentum + inverse-vol + trend strategy.

    Reads signal, regime, and portfolio parameters from ``config.signal_cfg``,
    ``config.regime_cfg``, and ``config.params``.

    No-leakage guarantee
    ---------------------
    This function receives ``prices`` truncated to ``[:rebalance_date]`` by
    the backtest engine.  All internal signal computations (momentum, vol,
    trend, regime) use only this truncated history — **no future data is
    accessed**.

    Parameters
    ----------
    config : ExperimentConfig
        Full experiment configuration (flat or nested formats both work).
    prices : pd.DataFrame
        Adjusted close prices available up to the current rebalance date.
        Supplied by the engine via ``prices.loc[:dt]`` — no future data.

    Returns
    -------
    pd.Series
        Target portfolio weights (index = tickers).
    """
    # ── Read signal config ────────────────────────────────────────────────
    sig = config.signal_cfg
    sig_lookback = sig.get("lookback", 252)
    long_only = sig.get("long_only", True)

    # ── Read regime config ────────────────────────────────────────────────
    reg = config.regime_cfg
    ma_fast = reg.get("fast", 20)
    ma_slow = reg.get("slow", 60)
    risk_off_scale = reg.get("risk_off_scale", 0.3)

    # ── Read portfolio / misc params (backward-compat via config.params) ──
    p = config.params
    mom_lb = p.get("momentum_lookback", sig_lookback)
    mom_skip = p.get("momentum_skip", 21)
    vol_win = p.get("vol_window", 60)
    sma_win = p.get("sma_window", 200)
    top_n = p.get("top_n", 50)
    sw = p.get("signal_weights", {"momentum": 0.4, "inverse_vol": 0.3, "trend": 0.3})

    # Need enough history for the longest lookback
    min_rows = max(mom_lb + mom_skip, sma_win, vol_win) + 10
    if len(prices) < min_rows:
        # Not enough history yet — stay flat
        return pd.Series(0.0, index=prices.columns)

    # ── Compute signals (cross-sectional, latest row) ─────────────────────
    mom = momentum_12_1(prices, skip=mom_skip, lookback=mom_lb).iloc[-1]
    ivol = inverse_volatility(prices, window=vol_win).iloc[-1]
    trend = trend_sma(prices, window=sma_win).iloc[-1]

    # ── Regime overlay: dual-MA regime on market proxy ────────────────────
    # Use the first column as a proxy for "the market"
    market = prices.iloc[:, 0]
    regime = dual_ma_regime(market, fast_window=ma_fast, slow_window=ma_slow).iloc[-1]

    # ── Composite z-score ────────────────────────────────────────────────
    # Normalise each signal to [0, 1] cross-sectionally before combining
    def _norm(s: pd.Series) -> pd.Series:
        lo, hi = s.min(), s.max()
        if hi == lo:
            return pd.Series(0.5, index=s.index)
        return (s - lo) / (hi - lo)

    composite = (
        sw.get("momentum", 0.4) * _norm(mom.fillna(0))
        + sw.get("inverse_vol", 0.3) * _norm(ivol.fillna(0))
        + sw.get("trend", 0.3) * _norm(trend.fillna(0))
    )

    # ── Portfolio construction ───────────────────────────────────────────
    weights = top_n_equal_weight(composite, n=min(top_n, len(composite)), long_only=long_only)

    # Apply regime overlay (reduce gross exposure in risk-off)
    weights = apply_regime_overlay(weights, regime, risk_off_scale=risk_off_scale)

    return weights
