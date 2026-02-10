"""
tests.test_splits
~~~~~~~~~~~~~~~~~
Acceptance tests for ``lab.backtest.splits``.

Criteria
--------
1. Splits are time-ordered — ``train.max() < test.min()``.
2. No overlap — ``len(train & test) == 0``.
3. Test strictly after train.
4. ``single_split`` yields exactly one split with ~70/30 proportions.
5. ``expanding_splits`` and ``rolling_splits`` yield ≥1 split each on a
   20-year date range.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lab.backtest.splits import expanding_splits, rolling_splits, single_split


@pytest.fixture()
def dates() -> pd.DatetimeIndex:
    """Five years of business days — enough for all generators."""
    return pd.bdate_range("2010-01-04", "2024-12-31")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _assert_split_invariants(train: pd.DatetimeIndex, test: pd.DatetimeIndex) -> None:
    """Check the three core invariants for every split."""
    # 1. Both non-empty
    assert len(train) > 0, "Train set is empty."
    assert len(test) > 0, "Test set is empty."
    # 2. Time-ordered: train ends before test begins
    assert train.max() < test.min(), f"Train max {train.max()} is NOT before test min {test.min()}"
    # 3. No overlap
    overlap = train.intersection(test)
    assert len(overlap) == 0, f"Train/test overlap on {len(overlap)} dates."


# ── single_split ──────────────────────────────────────────────────────────────


class TestSingleSplit:
    def test_yields_exactly_one_split(self, dates: pd.DatetimeIndex) -> None:
        splits = list(single_split(dates))
        assert len(splits) == 1

    def test_invariants(self, dates: pd.DatetimeIndex) -> None:
        for train, test in single_split(dates):
            _assert_split_invariants(train, test)

    def test_proportions_70_30(self, dates: pd.DatetimeIndex) -> None:
        ((train, test),) = single_split(dates)
        total = len(train) + len(test)
        assert total == len(dates)
        train_frac = len(train) / total
        assert 0.69 <= train_frac <= 0.71, f"Train fraction = {train_frac:.3f}"

    def test_custom_fraction(self, dates: pd.DatetimeIndex) -> None:
        ((train, test),) = single_split(dates, train_frac=0.5)
        total = len(train) + len(test)
        frac = len(train) / total
        assert 0.49 <= frac <= 0.51

    def test_covers_all_dates(self, dates: pd.DatetimeIndex) -> None:
        """Train ∪ test == full date index."""
        ((train, test),) = single_split(dates)
        combined = train.append(test).sort_values()
        pd.testing.assert_index_equal(combined, dates)

    def test_bad_train_frac_raises(self, dates: pd.DatetimeIndex) -> None:
        with pytest.raises(ValueError):
            list(single_split(dates, train_frac=0.0))
        with pytest.raises(ValueError):
            list(single_split(dates, train_frac=1.0))

    def test_tiny_index(self) -> None:
        """Two-element index still works."""
        tiny = pd.DatetimeIndex(["2020-01-01", "2020-01-02"])
        ((train, test),) = single_split(tiny)
        assert len(train) == 1
        assert len(test) == 1
        _assert_split_invariants(train, test)

    def test_duplicate_dates_raise(self) -> None:
        dup = pd.DatetimeIndex(["2020-01-01", "2020-01-01", "2020-01-02"])
        with pytest.raises(ValueError, match="strictly increasing and unique"):
            list(single_split(dup))


# ── expanding_splits ─────────────────────────────────────────────────────────


class TestExpandingSplits:
    def test_at_least_one_split(self, dates: pd.DatetimeIndex) -> None:
        splits = list(expanding_splits(dates, train_years=5, test_years=1, min_train_years=5))
        assert len(splits) >= 1

    def test_invariants(self, dates: pd.DatetimeIndex) -> None:
        for train, test in expanding_splits(dates, train_years=5, test_years=1, min_train_years=5):
            _assert_split_invariants(train, test)

    def test_expanding_train(self, dates: pd.DatetimeIndex) -> None:
        """Each successive train set is strictly larger."""
        splits = list(expanding_splits(dates, train_years=5, test_years=1, min_train_years=5))
        if len(splits) >= 2:
            for i in range(1, len(splits)):
                assert len(splits[i][0]) > len(splits[i - 1][0])

    def test_train_years_affects_first_split(self, dates: pd.DatetimeIndex) -> None:
        short = list(expanding_splits(dates, train_years=2, test_years=1, min_train_years=1))
        long = list(expanding_splits(dates, train_years=6, test_years=1, min_train_years=1))
        assert len(short) > 0 and len(long) > 0
        assert len(short[0][0]) < len(long[0][0])
        assert short[0][1].min() < long[0][1].min()

    def test_bad_years_raise(self, dates: pd.DatetimeIndex) -> None:
        with pytest.raises(ValueError):
            list(expanding_splits(dates, train_years=0, test_years=1, min_train_years=1))

    def test_duplicate_dates_raise(self) -> None:
        dup = pd.DatetimeIndex(["2020-01-01", "2020-01-01", "2020-01-02"])
        with pytest.raises(ValueError, match="strictly increasing and unique"):
            list(expanding_splits(dup, train_years=1, test_years=1, min_train_years=1))


# ── rolling_splits ───────────────────────────────────────────────────────────


class TestRollingSplits:
    def test_at_least_one_split(self, dates: pd.DatetimeIndex) -> None:
        splits = list(rolling_splits(dates, train_years=5, test_years=1))
        assert len(splits) >= 1

    def test_invariants(self, dates: pd.DatetimeIndex) -> None:
        for train, test in rolling_splits(dates, train_years=5, test_years=1):
            _assert_split_invariants(train, test)

    def test_no_overlap_between_folds(self, dates: pd.DatetimeIndex) -> None:
        """Adjacent test folds do not overlap."""
        splits = list(rolling_splits(dates, train_years=5, test_years=1))
        for i in range(1, len(splits)):
            prev_test = splits[i - 1][1]
            curr_test = splits[i][1]
            assert len(prev_test.intersection(curr_test)) == 0

    def test_duplicate_dates_raise(self) -> None:
        dup = pd.DatetimeIndex(["2020-01-01", "2020-01-01", "2020-01-02"])
        with pytest.raises(ValueError, match="strictly increasing and unique"):
            list(rolling_splits(dup, train_years=1, test_years=1))
