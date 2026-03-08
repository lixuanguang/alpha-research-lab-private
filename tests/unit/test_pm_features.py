"""Unit tests for alpha_core.features.pm_specific."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa
import pytest

from alpha_core.features.pm_specific import (
    BookImbalance,
    CategoryMomentum,
    CrossVenueSpread,
    ImpliedProbMomentum,
    ProbAcceleration,
    TimeToResolutionDecay,
    VolumeWeightedProb,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _base_table(
    instrument_ids: list[str],
    prices: list[float],
    sizes: list[float] | None = None,
    ts_offset_mins: list[int] | None = None,
    extra: dict[str, Any] | None = None,
) -> pa.Table:
    n = len(prices)
    if ts_offset_mins is None:
        ts_offset_mins = list(range(n))
    ts = [_T0 + timedelta(minutes=m) for m in ts_offset_mins]
    data: dict[str, Any] = {
        "instrument_id": instrument_ids,
        "price": pa.array(prices, pa.float64()),
        "size": pa.array(sizes or [1.0] * n, pa.float64()),
        "ts_event": pa.array(ts, pa.timestamp("us", tz="UTC")),
    }
    if extra:
        data.update(extra)
    return pa.table(data)


# ---------------------------------------------------------------------------
# ImpliedProbMomentum
# ---------------------------------------------------------------------------


class TestImpliedProbMomentum:
    def test_output_name(self) -> None:
        t = _base_table(["a"] * 5, [0.5] * 5)
        result = ImpliedProbMomentum(window=3).compute(t)
        assert result.name == "implied_prob_momentum_3"

    def test_warm_up_nan(self) -> None:
        t = _base_table(["a"] * 10, [0.5 + i * 0.01 for i in range(10)])
        result = ImpliedProbMomentum(window=5).compute(t)
        # Some leading rows must be NaN.
        assert any(math.isnan(v) for v in result.values[:5])

    def test_output_is_float(self) -> None:
        t = _base_table(["a"] * 15, [0.5 + i * 0.01 for i in range(15)])
        result = ImpliedProbMomentum(window=5).compute(t)
        non_nan = [v for v in result.values if not math.isnan(v)]
        assert all(isinstance(v, float) for v in non_nan)

    def test_empty_table_returns_empty(self) -> None:
        t = pa.table(
            {
                "instrument_id": pa.array([], pa.string()),
                "price": pa.array([], pa.float64()),
                "size": pa.array([], pa.float64()),
                "ts_event": pa.array([], pa.timestamp("us", tz="UTC")),
            }
        )
        result = ImpliedProbMomentum(window=5).compute(t)
        assert len(result.values) == 0


# ---------------------------------------------------------------------------
# CrossVenueSpread
# ---------------------------------------------------------------------------


class TestCrossVenueSpread:
    def _two_venue_table(self, price_a: float, price_b: float) -> pa.Table:
        """Two venues for the same outcome at the same timestamp."""
        ts = _T0
        return pa.table(
            {
                "instrument_id": [
                    "venueA:mkt1:outc1",
                    "venueB:mkt1:outc1",
                ],
                "price": pa.array([price_a, price_b], pa.float64()),
                "size": pa.array([1.0, 1.0], pa.float64()),
                "ts_event": pa.array([ts, ts], pa.timestamp("us", tz="UTC")),
            }
        )

    def test_two_venues_same_cross_key_non_nan_spread(self) -> None:
        t = self._two_venue_table(0.3, 0.5)
        result = CrossVenueSpread().compute(t)
        assert result.name == "cross_venue_spread"
        assert not any(math.isnan(v) for v in result.values)
        # Spread = 0.5 - 0.3 = 0.2
        assert abs(result.values[0] - 0.2) < 1e-9 or abs(result.values[1] - 0.2) < 1e-9

    def test_single_venue_all_nan(self) -> None:
        t = _base_table(["venueA:mkt1:outc1"] * 3, [0.4, 0.5, 0.6])
        result = CrossVenueSpread().compute(t)
        # Only one venue per cross_key per timestamp → spread undefined
        assert all(math.isnan(v) for v in result.values)

    def test_non_canonical_ids_all_nan(self) -> None:
        t = _base_table(["plain_id", "another_id"], [0.3, 0.7])
        result = CrossVenueSpread().compute(t)
        assert all(math.isnan(v) for v in result.values)

    def test_spread_direction(self) -> None:
        t = self._two_venue_table(0.2, 0.8)
        result = CrossVenueSpread().compute(t)
        spread_vals = [v for v in result.values if not math.isnan(v)]
        assert all(v >= 0 for v in spread_vals)

    def test_empty_table_returns_empty(self) -> None:
        t = pa.table(
            {
                "instrument_id": pa.array([], pa.string()),
                "price": pa.array([], pa.float64()),
                "size": pa.array([], pa.float64()),
                "ts_event": pa.array([], pa.timestamp("us", tz="UTC")),
            }
        )
        result = CrossVenueSpread().compute(t)
        assert len(result.values) == 0


# ---------------------------------------------------------------------------
# VolumeWeightedProb
# ---------------------------------------------------------------------------


class TestVolumeWeightedProb:
    def test_vwap_in_price_range(self) -> None:
        prices = [0.2, 0.4, 0.6, 0.8, 1.0]
        t = _base_table(["a"] * 5, prices, sizes=[10.0] * 5)
        result = VolumeWeightedProb(window=3).compute(t)
        non_nan = [v for v in result.values if not math.isnan(v)]
        assert all(min(prices) <= v <= max(prices) for v in non_nan)

    def test_missing_size_column_all_nan(self) -> None:
        t = pa.table(
            {
                "instrument_id": ["a"] * 5,
                "price": pa.array([0.5] * 5, pa.float64()),
                "ts_event": pa.array(
                    [_T0 + timedelta(minutes=i) for i in range(5)],
                    pa.timestamp("us", tz="UTC"),
                ),
            }
        )
        result = VolumeWeightedProb(window=3).compute(t)
        assert all(math.isnan(v) for v in result.values)

    def test_output_name(self) -> None:
        t = _base_table(["a"] * 5, [0.5] * 5)
        result = VolumeWeightedProb(window=10).compute(t)
        assert result.name == "volume_weighted_prob_10"

    def test_uniform_volume_vwap_equals_mean_price(self) -> None:
        prices = [0.2, 0.4, 0.6, 0.8]
        t = _base_table(["a"] * 4, prices, sizes=[1.0, 1.0, 1.0, 1.0])
        result = VolumeWeightedProb(window=3).compute(t)
        assert result.values[3] == pytest.approx(sum(prices[:3]) / 3)


# ---------------------------------------------------------------------------
# TimeToResolutionDecay
# ---------------------------------------------------------------------------


class TestTimeToResolutionDecay:
    def _table_with_resolution(self, n: int = 5, days_ahead: int = 10) -> pa.Table:
        ts_list = [_T0 + timedelta(minutes=i) for i in range(n)]
        res_date = _T0 + timedelta(days=days_ahead)
        return pa.table(
            {
                "instrument_id": ["a"] * n,
                "price": pa.array([0.5] * n, pa.float64()),
                "size": pa.array([1.0] * n, pa.float64()),
                "ts_event": pa.array(ts_list, pa.timestamp("us", tz="UTC")),
                "resolution_date": pa.array([res_date] * n, pa.timestamp("us", tz="UTC")),
            }
        )

    def test_values_in_range(self) -> None:
        t = self._table_with_resolution()
        result = TimeToResolutionDecay().compute(t)
        vals = [v for v in result.values if not math.isnan(v)]
        assert all(0.0 <= v <= 1.0 for v in vals)

    def test_missing_resolution_date_all_nan(self) -> None:
        t = _base_table(["a"] * 5, [0.5] * 5)
        result = TimeToResolutionDecay().compute(t)
        assert all(math.isnan(v) for v in result.values)

    def test_monotone_decay(self) -> None:
        """Earlier ts_event → higher decay value (more time remaining)."""
        n = 5
        t = self._table_with_resolution(n=n, days_ahead=100)
        result = TimeToResolutionDecay().compute(t)
        vals = list(result.values)
        # Later rows closer to resolution → smaller value.
        non_nan = [v for v in vals if not math.isnan(v)]
        if len(non_nan) >= 2:
            assert non_nan[0] >= non_nan[-1]

    def test_output_name(self) -> None:
        t = self._table_with_resolution()
        result = TimeToResolutionDecay().compute(t)
        assert result.name == "time_to_resolution_decay"


# ---------------------------------------------------------------------------
# CategoryMomentum
# ---------------------------------------------------------------------------


class TestCategoryMomentum:
    def _table_with_category(self) -> pa.Table:
        n = 8
        ts_list = [_T0 + timedelta(minutes=i) for i in range(n)]
        categories = ["sports", "politics"] * (n // 2)
        return pa.table(
            {
                "instrument_id": ["a", "b", "c", "d", "e", "f", "g", "h"],
                "price": pa.array([0.3, 0.7, 0.32, 0.68, 0.35, 0.65, 0.38, 0.62], pa.float64()),
                "size": pa.array([1.0] * n, pa.float64()),
                "ts_event": pa.array(ts_list, pa.timestamp("us", tz="UTC")),
                "category": pa.array(categories, pa.string()),
            }
        )

    def test_missing_category_column_all_nan(self) -> None:
        t = _base_table(["a"] * 5, [0.5] * 5)
        result = CategoryMomentum(window=3).compute(t)
        assert all(math.isnan(v) for v in result.values)

    def test_output_name(self) -> None:
        t = self._table_with_category()
        result = CategoryMomentum(window=3).compute(t)
        assert result.name == "category_momentum_3"

    def test_output_length_matches_input(self) -> None:
        t = self._table_with_category()
        result = CategoryMomentum(window=2).compute(t)
        assert len(result.values) == len(t)

    def test_empty_table(self) -> None:
        t = pa.table(
            {
                "instrument_id": pa.array([], pa.string()),
                "price": pa.array([], pa.float64()),
                "size": pa.array([], pa.float64()),
                "ts_event": pa.array([], pa.timestamp("us", tz="UTC")),
                "category": pa.array([], pa.string()),
            }
        )
        result = CategoryMomentum(window=3).compute(t)
        assert len(result.values) == 0


# ---------------------------------------------------------------------------
# BookImbalance
# ---------------------------------------------------------------------------


class TestBookImbalance:
    def _book_table(self, bid_vols: list[float], ask_vols: list[float]) -> pa.Table:
        n = len(bid_vols)
        return pa.table(
            {
                "instrument_id": ["a"] * n,
                "price": pa.array([0.5] * n, pa.float64()),
                "size": pa.array([1.0] * n, pa.float64()),
                "ts_event": pa.array(
                    [_T0 + timedelta(minutes=i) for i in range(n)],
                    pa.timestamp("us", tz="UTC"),
                ),
                "bid_volume": pa.array(bid_vols, pa.float64()),
                "ask_volume": pa.array(ask_vols, pa.float64()),
            }
        )

    def test_balanced_book_zero(self) -> None:
        t = self._book_table([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
        result = BookImbalance().compute(t)
        assert all(v == pytest.approx(0.0) for v in result.values)

    def test_all_bid_volume_one(self) -> None:
        t = self._book_table([10.0, 10.0], [0.0, 0.0])
        result = BookImbalance().compute(t)
        assert all(v == pytest.approx(1.0) for v in result.values)

    def test_all_ask_volume_minus_one(self) -> None:
        t = self._book_table([0.0, 0.0], [10.0, 10.0])
        result = BookImbalance().compute(t)
        assert all(v == pytest.approx(-1.0) for v in result.values)

    def test_missing_columns_all_nan(self) -> None:
        t = _base_table(["a"] * 3, [0.5] * 3)
        result = BookImbalance().compute(t)
        assert all(math.isnan(v) for v in result.values)

    def test_output_name(self) -> None:
        t = self._book_table([1.0], [1.0])
        assert BookImbalance(levels=3).compute(t).name == "book_imbalance_3"


# ---------------------------------------------------------------------------
# ProbAcceleration
# ---------------------------------------------------------------------------


class TestProbAcceleration:
    def test_fast_gte_slow_raises(self) -> None:
        with pytest.raises(ValueError):
            ProbAcceleration(fast=20, slow=5)

    def test_fast_equals_slow_raises(self) -> None:
        with pytest.raises(ValueError):
            ProbAcceleration(fast=10, slow=10)

    def test_output_name(self) -> None:
        t = _base_table(["a"] * 20, [0.5 + i * 0.01 for i in range(20)])
        result = ProbAcceleration(fast=5, slow=20).compute(t)
        assert result.name == "prob_acceleration_5_20"

    def test_output_is_float(self) -> None:
        t = _base_table(["a"] * 30, [0.5 + 0.01 * math.sin(i) for i in range(30)])
        result = ProbAcceleration(fast=5, slow=20).compute(t)
        non_nan = [v for v in result.values if not math.isnan(v)]
        assert all(isinstance(v, float) for v in non_nan)

    def test_empty_table_returns_empty(self) -> None:
        t = pa.table(
            {
                "instrument_id": pa.array([], pa.string()),
                "price": pa.array([], pa.float64()),
                "size": pa.array([], pa.float64()),
                "ts_event": pa.array([], pa.timestamp("us", tz="UTC")),
            }
        )
        result = ProbAcceleration(fast=5, slow=20).compute(t)
        assert len(result.values) == 0
