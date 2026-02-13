"""Tests for data QA checks and failure signaling."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lab.data.qa import QAThresholds, run_price_data_qa


def test_data_qa_fails_on_missingness_and_anomalies() -> None:
    idx = pd.bdate_range("2024-01-02", periods=30)
    close = pd.DataFrame(
        {
            "SPY": np.linspace(100.0, 110.0, len(idx)),
            "TLT": np.linspace(90.0, 95.0, len(idx)),
        },
        index=idx,
    )
    close.loc[idx[:5], "TLT"] = np.nan  # 16.7% missingness
    close.loc[idx[10], "SPY"] = close.loc[idx[9], "SPY"] * 75.0  # suspicious jump
    close.loc[idx[11], "SPY"] = 0.0  # zero price

    ohlcv_cols = pd.MultiIndex.from_product([["SPY", "TLT"], ["close", "volume"]], names=["ticker", "field"])
    ohlcv = pd.DataFrame(index=idx, columns=ohlcv_cols, dtype=float)
    ohlcv[("SPY", "close")] = close["SPY"].ffill()
    ohlcv[("TLT", "close")] = close["TLT"].ffill()
    ohlcv[("SPY", "volume")] = 1_000_000.0
    ohlcv[("TLT", "volume")] = 1_000_000.0
    ohlcv.loc[idx[15:23], ("TLT", "volume")] = 0.0

    qa = run_price_data_qa(
        close,
        ohlcv=ohlcv,
        thresholds=QAThresholds(
            max_missing_pct=5.0,
            jump_multiple=50.0,
            max_zero_volume_streak=5,
            max_missing_trading_days=0,
        ),
    )

    assert not qa.ok
    assert qa.failures
    assert not qa.jumps.empty
    assert not qa.zero_prices.empty
    assert (qa.missingness.set_index("ticker").loc["TLT", "missing_pct"]) > 5.0
    assert (qa.volume_zero_streaks.set_index("ticker").loc["TLT", "max_zero_streak"]) >= 8
