"""
lab.backtest.splits
~~~~~~~~~~~~~~~~~~~
Train / test split generators for walk-forward validation.

All generators yield ``(train_dates, test_dates)`` tuples where:

- Both are ``pd.DatetimeIndex``.
- **Time-ordered**: ``train.max() < test.min()`` (no overlap, test strictly
  after train).
- Train and test are contiguous sub-ranges of the input date index.

Provides
--------
- ``single_split``     : one-shot 70/30 (default) train/test split.
- ``expanding_splits``  : expanding-window walk-forward.
- ``rolling_splits``    : fixed-window rolling walk-forward.
- ``purged_kfold``      : purged K-fold (stub — week-2+).
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

SplitPair = tuple[pd.DatetimeIndex, pd.DatetimeIndex]


def _validate_dates_strict(dates: pd.DatetimeIndex) -> None:
    """Require strictly increasing unique timestamps."""
    if not dates.is_monotonic_increasing or not dates.is_unique:
        raise ValueError(
            "dates must be strictly increasing and unique (no look-ahead leakage)."
        )


# ── Single split (week-1 default) ────────────────────────────────────────────


def single_split(
    dates: pd.DatetimeIndex,
    train_frac: float = 0.70,
) -> Iterator[SplitPair]:
    """Yield exactly **one** (train, test) split.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Sorted date index covering the full sample period.
    train_frac : float
        Fraction of dates assigned to training (default 0.70 → 70 / 30).

    Yields
    ------
    (train_dates, test_dates)
        ``train_dates.max() < test_dates.min()`` is guaranteed.

    Raises
    ------
    ValueError
        If *dates* has fewer than 2 entries or *train_frac* is out of (0, 1).
    """
    if len(dates) < 2:
        raise ValueError("Need at least 2 dates for a train/test split.")
    if not 0 < train_frac < 1:
        raise ValueError(f"train_frac must be in (0, 1), got {train_frac}.")

    # Enforce strict time order
    _validate_dates_strict(dates)

    split_idx = int(len(dates) * train_frac)
    # Ensure both sets are non-empty
    split_idx = max(1, min(split_idx, len(dates) - 1))

    train, test = dates[:split_idx], dates[split_idx:]
    # POST-CONDITION: train.max() < test.min()  (time-order, no overlap)
    assert train.max() < test.min(), "train/test overlap — time-order violated"
    yield train, test


def expanding_splits(
    dates: pd.DatetimeIndex,
    train_years: int = 10,
    test_years: int = 1,
    min_train_years: int = 5,
) -> Iterator[SplitPair]:
    """Yield (train_dates, test_dates) with an expanding training window.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Full sorted date index.
    train_years, test_years : int
        Durations in calendar years.
    min_train_years : int
        Minimum training history before the first split is emitted.

    Yields
    ------
    (train_dates, test_dates)
    """
    _validate_dates_strict(dates)
    if train_years <= 0 or test_years <= 0 or min_train_years <= 0:
        raise ValueError("train_years, test_years, and min_train_years must all be > 0.")

    start = dates.min()
    end = dates.max()
    first_train_years = max(train_years, min_train_years)
    test_start = start + pd.DateOffset(years=first_train_years)

    while test_start + pd.DateOffset(years=test_years) <= end:
        test_end = test_start + pd.DateOffset(years=test_years)
        train_mask = (dates >= start) & (dates < test_start)
        test_mask = (dates >= test_start) & (dates < test_end)
        train, test = dates[train_mask], dates[test_mask]
        assert train.max() < test.min(), "train/test overlap — time-order violated"
        yield train, test
        test_start = test_end


def rolling_splits(
    dates: pd.DatetimeIndex,
    train_years: int = 10,
    test_years: int = 1,
) -> Iterator[SplitPair]:
    """Yield (train_dates, test_dates) with a fixed rolling window.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Full sorted date index.
    train_years, test_years : int
        Durations in calendar years.

    Yields
    ------
    (train_dates, test_dates)
    """
    _validate_dates_strict(dates)

    start = dates.min()
    end = dates.max()
    train_start = start

    while True:
        train_end = train_start + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if test_end > end:
            break
        train_mask = (dates >= train_start) & (dates < train_end)
        test_mask = (dates >= train_end) & (dates < test_end)
        train, test = dates[train_mask], dates[test_mask]
        assert train.max() < test.min(), "train/test overlap — time-order violated"
        yield train, test
        train_start = train_end  # non-overlapping steps


def purged_kfold(
    dates: pd.DatetimeIndex,
    n_splits: int = 5,
    embargo_days: int = 5,
) -> Iterator[SplitPair]:
    """Purged K-fold cross-validation (stub).

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Sorted date index.
    n_splits : int
        Number of folds.
    embargo_days : int
        Gap between train and test to avoid leakage.

    Yields
    ------
    (train_dates, test_dates)

    Notes
    -----
    TODO(week-2): implement proper purged combinatorial K-fold.
    """
    raise NotImplementedError("purged_kfold is a stub — scheduled for week-2.")
