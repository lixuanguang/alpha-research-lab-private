"""Unit tests for silver OHLCV quality expectations."""

from __future__ import annotations

import pyarrow as pa

from alpha_core.quality.suites.ohlcv_quality import (
    OHLCV_SUITE,
    OHLCVRangeExpectation,
    ResolutionConsistencyExpectation,
    VolumeNonNegativeExpectation,
)


def _ohlcv_table(
    *,
    open_: float = 0.50,
    high: float = 0.60,
    low: float = 0.40,
    close: float = 0.55,
    volume: float = 100.0,
    resolution: str = "1h",
    n: int = 1,
) -> pa.Table:
    return pa.table(
        {
            "open": pa.array([open_] * n, type=pa.float64()),
            "high": pa.array([high] * n, type=pa.float64()),
            "low": pa.array([low] * n, type=pa.float64()),
            "close": pa.array([close] * n, type=pa.float64()),
            "volume": pa.array([volume] * n, type=pa.float64()),
            "resolution": pa.array([resolution] * n),
        }
    )


# ---------------------------------------------------------------------------
# OHLCVRangeExpectation
# ---------------------------------------------------------------------------


def test_ohlcv_range_pass_valid() -> None:
    result = OHLCVRangeExpectation().validate(_ohlcv_table())
    assert result.passed is True


def test_ohlcv_range_fail_high_above_one() -> None:
    tbl = _ohlcv_table(high=1.1, open_=0.5, low=0.3, close=0.9)
    result = OHLCVRangeExpectation().validate(tbl)
    assert result.passed is False


def test_ohlcv_range_fail_low_below_zero() -> None:
    tbl = _ohlcv_table(low=-0.1, open_=0.5, high=0.8, close=0.5)
    result = OHLCVRangeExpectation().validate(tbl)
    assert result.passed is False


def test_ohlcv_range_fail_open_outside_low_high() -> None:
    tbl = _ohlcv_table(open_=0.9, high=0.8, low=0.3, close=0.5)
    result = OHLCVRangeExpectation().validate(tbl)
    assert result.passed is False


def test_ohlcv_range_fail_close_outside_low_high() -> None:
    tbl = _ohlcv_table(close=0.9, high=0.8, low=0.3, open_=0.5)
    result = OHLCVRangeExpectation().validate(tbl)
    assert result.passed is False


def test_ohlcv_range_pass_boundary_values() -> None:
    tbl = _ohlcv_table(open_=0.0, high=1.0, low=0.0, close=1.0)
    result = OHLCVRangeExpectation().validate(tbl)
    assert result.passed is True


def test_ohlcv_range_pass_empty_table() -> None:
    tbl = pa.table(
        {
            "open": pa.array([], type=pa.float64()),
            "high": pa.array([], type=pa.float64()),
            "low": pa.array([], type=pa.float64()),
            "close": pa.array([], type=pa.float64()),
        }
    )
    result = OHLCVRangeExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# VolumeNonNegativeExpectation
# ---------------------------------------------------------------------------


def test_volume_non_negative_pass() -> None:
    result = VolumeNonNegativeExpectation().validate(_ohlcv_table(volume=50.0))
    assert result.passed is True


def test_volume_non_negative_pass_zero_volume() -> None:
    result = VolumeNonNegativeExpectation().validate(_ohlcv_table(volume=0.0))
    assert result.passed is True


def test_volume_non_negative_fail_negative() -> None:
    tbl = pa.table({"volume": pa.array([-1.0], type=pa.float64())})
    result = VolumeNonNegativeExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["negative_volume_count"] == 1


def test_volume_non_negative_pass_empty_table() -> None:
    tbl = pa.table({"volume": pa.array([], type=pa.float64())})
    result = VolumeNonNegativeExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# ResolutionConsistencyExpectation
# ---------------------------------------------------------------------------


def test_resolution_consistency_pass_single() -> None:
    result = ResolutionConsistencyExpectation().validate(_ohlcv_table(n=3, resolution="1h"))
    assert result.passed is True


def test_resolution_consistency_fail_mixed() -> None:
    tbl = pa.table({"resolution": pa.array(["1h", "1d"])})
    result = ResolutionConsistencyExpectation().validate(tbl)
    assert result.passed is False
    assert len(result.details["unique_resolutions"]) == 2


def test_resolution_consistency_pass_empty_table() -> None:
    tbl = pa.table({"resolution": pa.array([], type=pa.string())})
    result = ResolutionConsistencyExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# OHLCV_SUITE integration
# ---------------------------------------------------------------------------


def test_ohlcv_suite_passes_clean_data() -> None:
    report = OHLCV_SUITE.validate(_ohlcv_table(n=5))
    assert report.passed is True
    assert report.suite_name == "silver_ohlcv"


def test_ohlcv_suite_fails_invalid_range() -> None:
    tbl = _ohlcv_table(open_=1.5, high=1.8, low=1.2, close=1.5)
    report = OHLCV_SUITE.validate(tbl)
    assert report.passed is False
