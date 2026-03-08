"""Unit tests for alpha_core.features.primitives."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest

from alpha_core.features.primitives import (
    EWM,
    Diff,
    Lag,
    Rank,
    Return,
    RollingMean,
    RollingStd,
    Volatility,
    ZScore,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _table(
    prices: list[float],
    instrument: str = "a",
    sizes: list[float] | None = None,
) -> pa.Table:
    n = len(prices)
    ts = [_T0 + timedelta(minutes=i) for i in range(n)]
    return pa.table(
        {
            "instrument_id": [instrument] * n,
            "price": pa.array(prices, type=pa.float64()),
            "size": pa.array(sizes or [1.0] * n, type=pa.float64()),
            "ts_event": pa.array(ts, type=pa.timestamp("us", tz="UTC")),
        }
    )


def _multi_table(prices_a: list[float], prices_b: list[float]) -> pa.Table:
    """Interleaved two-instrument table."""
    na, nb = len(prices_a), len(prices_b)
    ts_a = [_T0 + timedelta(minutes=i) for i in range(na)]
    ts_b = [_T0 + timedelta(minutes=i) for i in range(nb)]
    return pa.table(
        {
            "instrument_id": ["a"] * na + ["b"] * nb,
            "price": pa.array(prices_a + prices_b, type=pa.float64()),
            "size": pa.array([1.0] * (na + nb), type=pa.float64()),
            "ts_event": pa.array(ts_a + ts_b, type=pa.timestamp("us", tz="UTC")),
        }
    )


# ---------------------------------------------------------------------------
# RollingMean
# ---------------------------------------------------------------------------


class TestRollingMean:
    def test_correct_output_sufficient_history(self) -> None:
        t = _table([1.0, 2.0, 3.0, 4.0, 5.0])
        result = RollingMean(window=3).compute(t)
        assert result.name == "rolling_mean_price_3"
        # First three rows are warm-up because the rolling window is lagged.
        assert math.isnan(result.values[0])
        assert math.isnan(result.values[1])
        assert math.isnan(result.values[2])
        assert result.values[3] == pytest.approx(2.0)
        assert result.values[4] == pytest.approx(3.0)

    def test_window_larger_than_data_all_nan(self) -> None:
        t = _table([1.0, 2.0])
        result = RollingMean(window=5).compute(t)
        assert all(math.isnan(v) for v in result.values)

    def test_empty_table_returns_empty(self) -> None:
        t = pa.table(
            {
                "instrument_id": pa.array([], type=pa.string()),
                "price": pa.array([], type=pa.float64()),
                "size": pa.array([], type=pa.float64()),
                "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            }
        )
        result = RollingMean(window=3).compute(t)
        assert len(result.values) == 0

    def test_two_instruments_independent(self) -> None:
        t = _multi_table([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
        result = RollingMean(window=2).compute(t)
        # Row 0/1 and row 3/4 are NaN because the lagged window needs two full observations.
        assert math.isnan(result.values[0])
        assert math.isnan(result.values[3])
        assert math.isnan(result.values[1])
        assert math.isnan(result.values[4])
        assert result.values[2] == pytest.approx(1.5)  # (1+2)/2
        assert result.values[5] == pytest.approx(15.0)  # (10+20)/2

    def test_params_snapshot(self) -> None:
        f = RollingMean(window=10, source_col="size")
        assert f.params == {"window": 10, "source_col": "size"}
        assert f.name == "rolling_mean_size_10"


# ---------------------------------------------------------------------------
# RollingStd
# ---------------------------------------------------------------------------


class TestRollingStd:
    def test_std_known_values(self) -> None:
        t = _table([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        result = RollingStd(window=4).compute(t)
        # Lagged window at index 4 is [2,4,4,4].
        assert result.values[4] == pytest.approx(1.0, rel=1e-4)

    def test_window_larger_all_nan(self) -> None:
        result = RollingStd(window=10).compute(_table([1.0, 2.0, 3.0]))
        assert all(math.isnan(v) for v in result.values)

    def test_constant_series_std_zero_or_nan(self) -> None:
        t = _table([5.0] * 5)
        result = RollingStd(window=3).compute(t)
        assert result.values[4] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# EWM
# ---------------------------------------------------------------------------


class TestEWM:
    def test_second_value_equals_first_price(self) -> None:
        t = _table([0.3, 0.5, 0.7])
        result = EWM(span=2).compute(t)
        assert math.isnan(result.values[0])
        assert result.values[1] == pytest.approx(0.3)

    def test_empty_returns_empty(self) -> None:
        t = pa.table(
            {
                "instrument_id": pa.array([], pa.string()),
                "price": pa.array([], pa.float64()),
                "size": pa.array([], pa.float64()),
                "ts_event": pa.array([], pa.timestamp("us", tz="UTC")),
            }
        )
        result = EWM(span=5).compute(t)
        assert len(result.values) == 0

    def test_params(self) -> None:
        f = EWM(span=10)
        assert f.params["span"] == 10


# ---------------------------------------------------------------------------
# ZScore
# ---------------------------------------------------------------------------


class TestZScore:
    def test_zscore_zero_at_mean(self) -> None:
        # Constant series → mean = value, std = 0 → NaN (not 0).
        t = _table([1.0] * 5)
        result = ZScore(window=3).compute(t)
        # std=0 → division returns NaN.
        assert math.isnan(result.values[4])

    def test_zscore_known_value(self) -> None:
        t = _table([1.0, 2.0, 3.0, 4.0])
        result = ZScore(window=3).compute(t)
        assert result.values[3] == pytest.approx(1.0, rel=1e-3)

    def test_warm_up_nan(self) -> None:
        t = _table([1.0, 2.0, 3.0, 4.0])
        result = ZScore(window=3).compute(t)
        assert math.isnan(result.values[0])
        assert math.isnan(result.values[1])
        assert math.isnan(result.values[2])


# ---------------------------------------------------------------------------
# Rank
# ---------------------------------------------------------------------------


class TestRank:
    def test_time_series_rank_basic(self) -> None:
        # Lagged history at the last row is [1,2,3,4], so the rank is 1.0.
        t = _table([1.0, 2.0, 3.0, 4.0, 5.0])
        result = Rank(window=4, method="time_series").compute(t)
        assert result.values[4] == pytest.approx(1.0)

    def test_cross_sectional_rank(self) -> None:
        # Two instruments at same timestamps: a=0.3, b=0.7
        # b should have higher percentile rank.
        t = pa.table(
            {
                "instrument_id": ["a", "b"],
                "price": pa.array([0.3, 0.7], pa.float64()),
                "size": pa.array([1.0, 1.0], pa.float64()),
                "ts_event": pa.array([_T0, _T0], pa.timestamp("us", tz="UTC")),
            }
        )
        result = Rank(window=2, method="cross_sectional").compute(t)
        assert result.values[0] < result.values[1]

    def test_invalid_method_raises(self) -> None:
        with pytest.raises(ValueError, match="method"):
            Rank(method="unknown")


# ---------------------------------------------------------------------------
# Lag
# ---------------------------------------------------------------------------


class TestLag:
    def test_lag_one(self) -> None:
        t = _table([10.0, 20.0, 30.0])
        result = Lag(periods=1).compute(t)
        assert math.isnan(result.values[0])
        assert result.values[1] == pytest.approx(10.0)
        assert result.values[2] == pytest.approx(20.0)

    def test_lag_n(self) -> None:
        t = _table([1.0, 2.0, 3.0, 4.0])
        result = Lag(periods=2).compute(t)
        assert math.isnan(result.values[0])
        assert math.isnan(result.values[1])
        assert result.values[2] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


class TestDiff:
    def test_diff_one(self) -> None:
        t = _table([1.0, 3.0, 6.0])
        result = Diff(periods=1).compute(t)
        assert math.isnan(result.values[0])
        assert math.isnan(result.values[1])
        assert result.values[2] == pytest.approx(2.0)

    def test_empty_input(self) -> None:
        t = pa.table(
            {
                "instrument_id": pa.array([], pa.string()),
                "price": pa.array([], pa.float64()),
                "size": pa.array([], pa.float64()),
                "ts_event": pa.array([], pa.timestamp("us", tz="UTC")),
            }
        )
        result = Diff().compute(t)
        assert len(result.values) == 0


# ---------------------------------------------------------------------------
# Return
# ---------------------------------------------------------------------------


class TestReturn:
    def test_pct_return_known(self) -> None:
        t = _table([1.0, 1.5, 2.0])
        result = Return(periods=1).compute(t)
        assert math.isnan(result.values[0])
        assert math.isnan(result.values[1])
        assert result.values[2] == pytest.approx(0.5)

    def test_zero_lagged_price_is_nan(self) -> None:
        t = _table([0.0, 1.0])
        result = Return(periods=1).compute(t)
        assert math.isnan(result.values[1])


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


class TestVolatility:
    def test_constant_returns_zero_vol(self) -> None:
        t = _table([1.0] * 10)
        result = Volatility(window=5).compute(t)
        # constant prices → zero returns → zero vol.
        assert result.values[-1] == pytest.approx(0.0)

    def test_warm_up_rows_nan(self) -> None:
        t = _table([1.0, 1.1, 1.2, 1.3, 1.4])
        result = Volatility(window=4).compute(t)
        # Need at least window+1 rows for the first vol calculation.
        nan_count = sum(1 for v in result.values if math.isnan(v))
        assert nan_count > 0
