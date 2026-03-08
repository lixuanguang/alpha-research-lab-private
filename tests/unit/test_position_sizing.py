"""Unit tests for alpha_core.portfolio.sizing."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from alpha_core.portfolio.sizing import (
    EqualWeightSizer,
    FixedSizeSizer,
    KellySizer,
    PositionSizer,
)

_PV = Decimal("10000")  # portfolio value


def _signals(*pairs: tuple[str, float]) -> pd.DataFrame:
    """Helper: build a signals DataFrame from (instrument_id, signal) pairs."""
    return pd.DataFrame({"instrument_id": [p[0] for p in pairs], "signal": [p[1] for p in pairs]})


# ---------------------------------------------------------------------------
# EqualWeightSizer
# ---------------------------------------------------------------------------


class TestEqualWeightSizer:
    def test_all_long_equal_weights(self) -> None:
        s = EqualWeightSizer()
        sig = _signals(("a", 1.0), ("b", 1.0), ("c", 1.0))
        result = s.size(sig, _PV, max_positions=50)
        assert len(result) == 3
        assert all(w == pytest.approx(1 / 3) for w in result["target_weight"])

    def test_absolute_weights_sum_to_one(self) -> None:
        s = EqualWeightSizer()
        sig = _signals(("a", 0.8), ("b", -0.5), ("c", 0.3))
        result = s.size(sig, _PV, max_positions=50)
        total = sum(abs(w) for w in result["target_weight"])
        assert total == pytest.approx(1.0)

    def test_long_positive_short_negative(self) -> None:
        s = EqualWeightSizer()
        sig = _signals(("a", 1.0), ("b", -1.0))
        result = s.size(sig, _PV, max_positions=50)
        weights = dict(zip(result["instrument_id"], result["target_weight"]))
        assert weights["a"] > 0
        assert weights["b"] < 0

    def test_flat_signals_excluded(self) -> None:
        s = EqualWeightSizer()
        sig = _signals(("a", 0.0), ("b", 1.0), ("c", 0.0))
        result = s.size(sig, _PV, max_positions=50)
        assert len(result) == 1
        assert result.iloc[0]["instrument_id"] == "b"

    def test_all_flat_returns_empty(self) -> None:
        s = EqualWeightSizer()
        sig = _signals(("a", 0.0), ("b", 0.0))
        result = s.size(sig, _PV, max_positions=50)
        assert result.empty

    def test_empty_dataframe_returns_empty(self) -> None:
        s = EqualWeightSizer()
        result = s.size(pd.DataFrame(), _PV, max_positions=50)
        assert result.empty

    def test_max_positions_limits_output(self) -> None:
        s = EqualWeightSizer()
        sig = _signals(("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6))
        result = s.size(sig, _PV, max_positions=2)
        assert len(result) <= 2

    def test_subclass_of_position_sizer(self) -> None:
        assert issubclass(EqualWeightSizer, PositionSizer)


# ---------------------------------------------------------------------------
# FixedSizeSizer
# ---------------------------------------------------------------------------


class TestFixedSizeSizer:
    def test_default_fraction_is_one_over_max_positions(self) -> None:
        s = FixedSizeSizer()
        sig = _signals(("a", 1.0), ("b", 1.0))
        result = s.size(sig, _PV, max_positions=10)
        # fraction = 1/10 = 0.1 per position
        for w in result["target_weight"]:
            assert abs(w) == pytest.approx(0.1)

    def test_custom_fraction(self) -> None:
        s = FixedSizeSizer(fraction=0.2)
        sig = _signals(("a", 1.0))
        result = s.size(sig, _PV, max_positions=10)
        assert result.iloc[0]["target_weight"] == pytest.approx(0.2)

    def test_negative_fraction_raises(self) -> None:
        with pytest.raises(ValueError):
            FixedSizeSizer(fraction=0.0)

    def test_fraction_above_one_raises(self) -> None:
        with pytest.raises(ValueError):
            FixedSizeSizer(fraction=1.1)

    def test_short_signal_gets_negative_weight(self) -> None:
        s = FixedSizeSizer(fraction=0.1)
        sig = _signals(("a", -0.7))
        result = s.size(sig, _PV, max_positions=10)
        assert result.iloc[0]["target_weight"] < 0

    def test_empty_signals_returns_empty(self) -> None:
        s = FixedSizeSizer()
        result = s.size(pd.DataFrame(), _PV, max_positions=10)
        assert result.empty


# ---------------------------------------------------------------------------
# KellySizer
# ---------------------------------------------------------------------------


class TestKellySizer:
    def test_half_probability_gets_zero_kelly(self) -> None:
        """p=0.5 → f* = 2*0.5 - 1 = 0.0 → weight=0."""
        s = KellySizer()
        sig = _signals(("a", 0.5))
        result = s.size(sig, _PV, max_positions=50)
        # p=0.5 → kelly = 0, gets filtered out (zero weight).
        # It may appear with weight ~0 or be absent.
        if not result.empty:
            w = float(result.iloc[0]["target_weight"])
            assert abs(w) < 0.001

    def test_high_probability_long_gets_large_kelly(self) -> None:
        """p=0.9 → f* = 2*0.9 - 1 = 0.8."""
        s = KellySizer()
        sig = _signals(("a", 0.9))
        result = s.size(sig, _PV, max_positions=50)
        assert not result.empty
        w = float(result.iloc[0]["target_weight"])
        assert w == pytest.approx(0.8, abs=0.001)

    def test_max_leverage_clamp(self) -> None:
        """f* is clamped to max_leverage."""
        s = KellySizer(max_leverage=0.3)
        sig = _signals(("a", 0.99))
        result = s.size(sig, _PV, max_positions=50)
        w = float(result.iloc[0]["target_weight"])
        assert w <= 0.3 + 1e-9

    def test_fractional_kelly(self) -> None:
        """Half-Kelly should halve the weight."""
        full = KellySizer(fractional=1.0)
        half = KellySizer(fractional=0.5)
        sig = _signals(("a", 0.8))
        w_full = float(full.size(sig, _PV, max_positions=50).iloc[0]["target_weight"])
        w_half = float(half.size(sig, _PV, max_positions=50).iloc[0]["target_weight"])
        assert w_half == pytest.approx(w_full * 0.5, rel=0.01)

    def test_negative_max_leverage_raises(self) -> None:
        with pytest.raises(ValueError):
            KellySizer(max_leverage=0.0)

    def test_kelly_subclass_of_position_sizer(self) -> None:
        assert issubclass(KellySizer, PositionSizer)

    def test_empty_signals_returns_empty(self) -> None:
        s = KellySizer()
        result = s.size(pd.DataFrame(), _PV, max_positions=10)
        assert result.empty

    def test_invalid_fractional_raises(self) -> None:
        with pytest.raises(ValueError):
            KellySizer(fractional=0.0)
