"""Acceptance tests for macro signal modularization and ensembling."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lab.strategies.macro.signals import build_signal


def _toy_prices(periods: int = 320) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=periods)
    rng = np.random.default_rng(7)
    noise = rng.normal(loc=0.0, scale=0.01, size=(periods, 3))
    drift = np.array([0.0003, 0.0001, 0.0002])
    rets = drift + noise
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=["SPY", "TLT", "GLD"])


def test_trend_and_trend_only_ensemble_scores_are_identical() -> None:
    prices = _toy_prices()

    trend_cfg = {
        "name": "ts_trend",
        "method": "ma_cross",
        "fast": 20,
        "slow": 120,
        "lookback_days": 252,
    }
    ensemble_cfg = {
        "name": "ensemble",
        "signals": {
            "trend": {
                "name": "ts_trend",
                "method": "ma_cross",
                "fast": 20,
                "slow": 120,
                "lookback_days": 252,
            }
        },
        "weights": {"trend": 1.0},
    }

    trend = build_signal(trend_cfg)
    ensemble = build_signal(ensemble_cfg)

    trend_scores = trend.compute(prices, None, None)
    ensemble_scores = ensemble.compute(prices, None, None)

    pd.testing.assert_frame_equal(ensemble_scores, trend_scores)


def test_signal_scores_align_with_prices_and_have_no_post_warmup_nans() -> None:
    prices = _toy_prices()
    trend_cfg = {
        "name": "ts_trend",
        "method": "ma_cross",
        "fast": 20,
        "slow": 120,
        "lookback_days": 252,
    }
    signal = build_signal(trend_cfg)

    scores = signal.compute(prices, None, None)

    assert scores.index.equals(prices.index)
    assert list(scores.columns) == list(prices.columns)
    assert ((scores >= -1.0) & (scores <= 1.0)).all().all()

    warmup = 121  # slow MA + one-day shift
    assert not scores.iloc[warmup:].isna().any().any()

