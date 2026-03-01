"""Quality expectations for silver trades partitions."""

from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

import alpha_core.quality.base as quality_base


class NullRateExpectation(quality_base.QualityExpectation):
    """Fail if null rate exceeds threshold for any of the specified columns."""

    name = "null_rate"

    def __init__(
        self,
        *,
        columns: list[str],
        threshold: float = 0.0,
        severity: str = "fail",
    ) -> None:
        self._columns = columns
        self._threshold = threshold
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        if table.num_rows == 0:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table"},
            )
        violations: dict[str, float] = {}
        for col in self._columns:
            if col not in table.schema.names:
                violations[col] = 1.0
                continue
            null_count = table.column(col).null_count
            rate = null_count / table.num_rows
            if rate > self._threshold:
                violations[col] = rate
        passed = len(violations) == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"threshold": self._threshold, "violations": violations},
        )


class PriceBoundsExpectation(quality_base.QualityExpectation):
    """All trade prices must be in [0.0, 1.0]."""

    name = "price_bounds"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        if table.num_rows == 0 or "price" not in table.schema.names:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "no price column or empty table"},
            )
        # Cast to float64 for numeric comparison (decimal128 → float)
        prices = table.column("price").cast(pa.float64())
        out_of_bounds = pc.sum(pc.or_(pc.less(prices, 0.0), pc.greater(prices, 1.0))).as_py()
        passed = out_of_bounds == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"out_of_bounds_count": out_of_bounds},
        )


class MonotonicTimestampExpectation(quality_base.QualityExpectation):
    """ts_event must be non-decreasing within each instrument stream."""

    name = "monotonic_timestamp"

    def __init__(self, *, severity: str = "warn") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        if table.num_rows < 2 or "ts_event" not in table.schema.names:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "insufficient rows"},
            )
        if "instrument_id" not in table.schema.names:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "no instrument_id column"},
            )
        violations = 0
        instruments = table.column("instrument_id").unique().to_pylist()
        for inst in instruments:
            mask = pc.equal(table.column("instrument_id"), inst)
            # Check original partition order — do NOT sort (sorting would hide the violation)
            ts = table.filter(mask).column("ts_event").to_pylist()
            for i in range(1, len(ts)):
                if ts[i] < ts[i - 1]:
                    violations += 1
        passed = violations == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"non_monotonic_pairs": violations},
        )


class DuplicateTradeIdExpectation(quality_base.QualityExpectation):
    """No duplicate `(instrument_id, trade_id)` pairs within a partition."""

    name = "duplicate_trade_id"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"instrument_id", "trade_id"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "missing columns or empty table", "missing": sorted(missing)},
            )
        pairs = zip(
            table.column("instrument_id").to_pylist(),
            table.column("trade_id").to_pylist(),
            strict=True,
        )
        total = table.num_rows
        unique_pairs = set(pairs)
        duplicates = total - len(unique_pairs)
        passed = duplicates == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"duplicate_count": duplicates, "key_fields": ["instrument_id", "trade_id"]},
        )


class StaleDataExpectation(quality_base.QualityExpectation):
    """Warn if latest ts_event is older than max_age_hours."""

    name = "stale_data"

    def __init__(self, *, max_age_hours: float = 1.0, severity: str = "warn") -> None:
        self._max_age_hours = max_age_hours
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        if table.num_rows == 0 or "ts_event" not in table.schema.names:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or no ts_event"},
            )
        latest_raw = pc.max(table.column("ts_event")).as_py()
        # Ensure timezone-aware comparison
        if latest_raw is not None and latest_raw.tzinfo is None:
            latest_raw = latest_raw.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        age_hours = (now - latest_raw).total_seconds() / 3600.0 if latest_raw else float("inf")
        passed = age_hours <= self._max_age_hours
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"age_hours": round(age_hours, 4), "threshold_hours": self._max_age_hours},
        )


class BitemporalOrderExpectation(quality_base.QualityExpectation):
    """ts_event <= ts_record for all rows."""

    name = "bitemporal_order"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"ts_event", "ts_record"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns", "missing": list(missing)},
            )
        violations = pc.sum(pc.greater(table.column("ts_event"), table.column("ts_record"))).as_py()
        passed = violations == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"violation_count": violations},
        )


TRADE_SUITE = quality_base.QualitySuite(
    "silver_trades",
    [
        NullRateExpectation(
            columns=["event_id", "instrument_id", "price", "size"],
            threshold=0.0,
            severity="fail",
        ),
        PriceBoundsExpectation(severity="fail"),
        MonotonicTimestampExpectation(severity="warn"),
        DuplicateTradeIdExpectation(severity="fail"),
        StaleDataExpectation(max_age_hours=1.0, severity="warn"),
        BitemporalOrderExpectation(severity="fail"),
    ],
)
