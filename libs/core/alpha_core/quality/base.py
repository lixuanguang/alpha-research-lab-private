"""Quality suite framework — batch partition validation on PyArrow tables."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Literal

import pyarrow as pa  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field


class QualityResult(BaseModel):
    """Outcome of a single expectation check."""

    model_config = ConfigDict(extra="forbid")

    expectation_name: str
    passed: bool
    severity: Literal["warn", "fail"]
    details: dict[str, Any] = Field(default_factory=dict)


class SuiteReport(BaseModel):
    """Aggregate report produced by running a QualitySuite against a partition."""

    model_config = ConfigDict(extra="forbid")

    suite_name: str
    passed: bool          # True only if zero "fail"-severity results are failures
    degraded: bool        # True if any "warn"-severity results are failures
    results: list[QualityResult]
    validated_at: datetime
    row_count: int
    partition_info: dict[str, str] = Field(default_factory=dict)


class QualityExpectation(ABC):
    """Single quality check executed against a PyArrow table partition."""

    #: Unique name used in result reporting.
    name: str
    #: "fail" blocks the partition; "warn" marks it degraded only.
    severity: Literal["warn", "fail"]

    @abstractmethod
    def validate(self, table: pa.Table) -> QualityResult:
        """Run the expectation and return a result."""
        ...


class QualitySuite:
    """Ordered collection of expectations run against a dataset partition."""

    def __init__(
        self,
        name: str,
        expectations: list[QualityExpectation],
    ) -> None:
        self._name = name
        self._expectations = expectations

    @property
    def name(self) -> str:
        return self._name

    def validate(
        self,
        table: pa.Table,
        *,
        partition_info: dict[str, str] | None = None,
    ) -> SuiteReport:
        """Run all expectations and aggregate into a SuiteReport."""
        results: list[QualityResult] = [exp.validate(table) for exp in self._expectations]

        failed_fail = any(not r.passed and r.severity == "fail" for r in results)
        failed_warn = any(not r.passed and r.severity == "warn" for r in results)

        return SuiteReport(
            suite_name=self._name,
            passed=not failed_fail,
            degraded=failed_warn,
            results=results,
            validated_at=datetime.now(UTC),
            row_count=table.num_rows,
            partition_info=partition_info or {},
        )
