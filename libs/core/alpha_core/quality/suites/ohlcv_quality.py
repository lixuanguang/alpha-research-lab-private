"""Quality expectations for silver OHLCV partitions."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

import alpha_core.quality.base as quality_base


class OHLCVRangeExpectation(quality_base.QualityExpectation):
    """low <= open, close <= high; all OHLC values in [0, 1]."""

    name = "ohlcv_range"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        required = {"open", "high", "low", "close"}
        missing = required - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns", "missing": list(missing)},
            )
        # Cast decimal128 to float64 for comparison
        o = table.column("open").cast(pa.float64())
        h = table.column("high").cast(pa.float64())
        lo = table.column("low").cast(pa.float64())
        c = table.column("close").cast(pa.float64())

        out_of_range = pc.or_(pc.less(lo, 0.0), pc.greater(h, 1.0))
        bad_open = pc.or_(pc.less(o, lo), pc.greater(o, h))
        bad_close = pc.or_(pc.less(c, lo), pc.greater(c, h))
        low_gt_high = pc.greater(lo, h)
        any_violation = pc.or_(pc.or_(out_of_range, bad_open), pc.or_(bad_close, low_gt_high))
        violations = pc.sum(any_violation).as_py()
        passed = violations == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"violation_count": violations},
        )


class VolumeNonNegativeExpectation(quality_base.QualityExpectation):
    """volume >= 0 for all candles."""

    name = "volume_non_negative"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        if table.num_rows == 0 or "volume" not in table.schema.names:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or no volume column"},
            )
        volume = table.column("volume").cast(pa.float64())
        negatives = pc.sum(pc.less(volume, 0.0)).as_py()
        passed = negatives == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"negative_volume_count": negatives},
        )


class ResolutionConsistencyExpectation(quality_base.QualityExpectation):
    """All rows in a partition must share the same resolution value."""

    name = "resolution_consistency"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        if table.num_rows == 0 or "resolution" not in table.schema.names:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or no resolution column"},
            )
        unique_resolutions: list[str] = table.column("resolution").unique().to_pylist()
        passed = len(unique_resolutions) <= 1
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"unique_resolutions": unique_resolutions},
        )


OHLCV_SUITE = quality_base.QualitySuite(
    "silver_ohlcv",
    [
        OHLCVRangeExpectation(severity="fail"),
        VolumeNonNegativeExpectation(severity="fail"),
        ResolutionConsistencyExpectation(severity="fail"),
    ],
)
