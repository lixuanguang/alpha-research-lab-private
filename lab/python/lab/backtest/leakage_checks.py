"""Leakage / causality guards for walk-forward experiments."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

Fold = tuple[pd.DatetimeIndex, pd.DatetimeIndex]


def assert_no_lookahead(
    signal_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    min_lag: int = 1,
) -> None:
    """Raise if *signal_df* appears to use future returns.

    The check is intentionally conservative: it looks for near-identity between
    signal values and forward returns/signs at the same timestamps.
    """
    if min_lag < 1:
        raise ValueError("min_lag must be >= 1")

    common_idx = signal_df.index.intersection(prices_df.index)
    common_cols = signal_df.columns.intersection(prices_df.columns)
    if len(common_idx) == 0 or len(common_cols) == 0:
        return

    sig = signal_df.reindex(index=common_idx, columns=common_cols)
    future_ret = prices_df.reindex(index=common_idx, columns=common_cols).pct_change().shift(-min_lag)

    for col in common_cols:
        s = sig[col]
        f = future_ret[col]

        valid = s.notna() & f.notna()
        if valid.sum() < 20:
            continue

        s_valid = s[valid]
        f_valid = f[valid]

        exact_match_ratio = np.isclose(s_valid.to_numpy(), f_valid.to_numpy(), atol=1e-12).mean()
        sign_match_ratio = (
            np.sign(s_valid.to_numpy()) == np.sign(f_valid.to_numpy())
        ).mean()

        if exact_match_ratio > 0.98 or sign_match_ratio > 0.99:
            raise AssertionError(
                f"lookahead detected in '{col}' (exact={exact_match_ratio:.3f}, "
                f"sign={sign_match_ratio:.3f})"
            )


def assert_splits_time_ordered(folds: Iterable[Fold]) -> None:
    """Raise if any fold breaks temporal ordering or embargo separation."""
    prev_test_end: pd.Timestamp | None = None

    for i, (train, test) in enumerate(folds):
        if len(train) == 0 or len(test) == 0:
            raise AssertionError(f"fold {i} has an empty train or test partition")
        if train.max() >= test.min():
            raise AssertionError(f"fold {i} violates time ordering")
        if len(train.intersection(test)) > 0:
            raise AssertionError(f"fold {i} has train/test overlap")

        if prev_test_end is not None and test.min() <= prev_test_end:
            raise AssertionError(f"fold {i} overlaps previous test window")
        prev_test_end = test.max()
