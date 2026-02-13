"""Tests for snapshot-keyed macro feature store behavior."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from lab.backtest.leakage_checks import assert_no_lookahead
from lab.features.store import (
    build_macro_allocator_feature_frame,
    load_or_build_macro_allocator_feature_store,
)


def _toy_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    idx = pd.bdate_range("2022-01-03", periods=320)
    rng = np.random.default_rng(7)
    prices = pd.DataFrame(
        {
            "SPY": 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))),
            "TLT": 100.0 * np.exp(np.cumsum(rng.normal(0.0001, 0.008, len(idx)))),
        },
        index=idx,
    )
    macro_known = pd.DataFrame(
        {
            "UNRATE": np.linspace(3.5, 4.2, len(idx)),
            "CPIAUCSL": np.linspace(270.0, 320.0, len(idx)),
            "INDPRO": np.linspace(100.0, 108.0, len(idx)),
            "DFF": np.linspace(0.25, 5.0, len(idx)),
        },
        index=idx,
    )
    meta = pd.DataFrame(
        {
            "ticker": ["SPY", "TLT"],
            "bucket": ["equities", "rates"],
            "cost_bps": [3.0, 2.0],
            "per_asset_cap": [0.35, 0.35],
        }
    )
    regime = pd.Series((macro_known["UNRATE"].diff().fillna(0.0) > 0).astype(int), index=idx)
    return prices, macro_known, meta, regime


def test_feature_store_is_reproducible_for_same_snapshot(tmp_path: Path) -> None:
    prices, macro_known, meta, regime = _toy_inputs()

    features_1, path_1, from_cache_1 = load_or_build_macro_allocator_feature_store(
        snapshot_id="snap_abc",
        prices=prices,
        macro_known=macro_known,
        meta=meta,
        regime_indicator=regime,
        root=tmp_path / "features",
    )
    features_2, path_2, from_cache_2 = load_or_build_macro_allocator_feature_store(
        snapshot_id="snap_abc",
        prices=prices,
        macro_known=macro_known,
        meta=meta,
        regime_indicator=regime,
        root=tmp_path / "features",
    )

    assert path_1 == path_2
    assert path_1.exists()
    assert from_cache_1 is False
    assert from_cache_2 is True
    pd.testing.assert_frame_equal(features_1, features_2, check_freq=False)


def test_feature_store_respects_no_lookahead_contract() -> None:
    prices, macro_known, meta, regime = _toy_inputs()
    features = build_macro_allocator_feature_frame(
        prices=prices,
        macro_known=macro_known,
        meta=meta,
        regime_indicator=regime,
    )

    expected_returns = prices.pct_change().shift(1).fillna(0.0)
    stored_returns = features[[f"returns__{t}" for t in prices.columns]].copy()
    stored_returns.columns = prices.columns
    pd.testing.assert_frame_equal(stored_returns, expected_returns)

    trend = features[[f"trend_score__{t}" for t in prices.columns]].copy()
    trend.columns = prices.columns
    assert_no_lookahead(trend, prices, min_lag=1)
