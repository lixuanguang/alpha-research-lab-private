"""Unit tests for the quality suite base framework."""

from __future__ import annotations

from datetime import UTC
from typing import Literal

import pyarrow as pa

from alpha_core.quality.base import (
    QualityExpectation,
    QualityResult,
    QualitySuite,
)

# ---------------------------------------------------------------------------
# Stub expectation
# ---------------------------------------------------------------------------


class _AlwaysPassExpectation(QualityExpectation):
    name = "always_pass"

    def __init__(self, severity: Literal["warn", "fail"] = "fail") -> None:
        self.severity = severity

    def validate(self, table: pa.Table) -> QualityResult:
        return QualityResult(expectation_name=self.name, passed=True, severity=self.severity)


class _AlwaysFailExpectation(QualityExpectation):
    name = "always_fail"

    def __init__(self, severity: Literal["warn", "fail"] = "fail") -> None:
        self.severity = severity

    def validate(self, table: pa.Table) -> QualityResult:
        return QualityResult(
            expectation_name=self.name,
            passed=False,
            severity=self.severity,
            details={"reason": "stub"},
        )


_EMPTY_TABLE = pa.table({"x": pa.array([], type=pa.int32())})
_SMALL_TABLE = pa.table({"x": pa.array([1, 2, 3])})


# ---------------------------------------------------------------------------
# Suite aggregation
# ---------------------------------------------------------------------------


def test_suite_all_pass() -> None:
    suite = QualitySuite(
        "test", [_AlwaysPassExpectation(), _AlwaysPassExpectation(severity="warn")]
    )
    report = suite.validate(_SMALL_TABLE)
    assert report.passed is True
    assert report.degraded is False
    assert len(report.results) == 2


def test_suite_fail_severity_blocks() -> None:
    suite = QualitySuite(
        "test", [_AlwaysPassExpectation(), _AlwaysFailExpectation(severity="fail")]
    )
    report = suite.validate(_SMALL_TABLE)
    assert report.passed is False
    assert report.degraded is False


def test_suite_warn_severity_degrades_only() -> None:
    suite = QualitySuite(
        "test", [_AlwaysPassExpectation(), _AlwaysFailExpectation(severity="warn")]
    )
    report = suite.validate(_SMALL_TABLE)
    assert report.passed is True
    assert report.degraded is True


def test_suite_both_fail_and_warn() -> None:
    suite = QualitySuite(
        "test",
        [_AlwaysFailExpectation(severity="fail"), _AlwaysFailExpectation(severity="warn")],
    )
    report = suite.validate(_SMALL_TABLE)
    assert report.passed is False
    assert report.degraded is True


def test_suite_empty_table() -> None:
    suite = QualitySuite("test", [_AlwaysPassExpectation(), _AlwaysFailExpectation()])
    report = suite.validate(_EMPTY_TABLE)
    assert report.row_count == 0


def test_suite_row_count() -> None:
    suite = QualitySuite("test", [_AlwaysPassExpectation()])
    report = suite.validate(_SMALL_TABLE)
    assert report.row_count == 3


def test_suite_partition_info_propagated() -> None:
    suite = QualitySuite("test", [_AlwaysPassExpectation()])
    report = suite.validate(_SMALL_TABLE, partition_info={"venue": "kalshi", "date": "2026-03-01"})
    assert report.partition_info == {"venue": "kalshi", "date": "2026-03-01"}


def test_suite_validated_at_is_utc() -> None:
    suite = QualitySuite("test", [_AlwaysPassExpectation()])
    report = suite.validate(_SMALL_TABLE)
    assert report.validated_at.tzinfo == UTC


def test_suite_name_stored_on_report() -> None:
    suite = QualitySuite("my_suite", [_AlwaysPassExpectation()])
    report = suite.validate(_SMALL_TABLE)
    assert report.suite_name == "my_suite"


def test_suite_no_expectations() -> None:
    suite = QualitySuite("empty", [])
    report = suite.validate(_SMALL_TABLE)
    assert report.passed is True
    assert report.degraded is False
    assert report.results == []
