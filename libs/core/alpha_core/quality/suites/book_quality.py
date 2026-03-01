"""Quality expectations for silver books partitions."""

from __future__ import annotations

import json

import pyarrow as pa  # type: ignore[import-untyped]

import alpha_core.quality.base as quality_base


class CrossedBookExpectation(quality_base.QualityExpectation):
    """Best bid must be strictly less than best ask; no crossed books."""

    name = "crossed_book"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"bids_json", "asks_json"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns"},
            )
        crossed = 0
        for row in range(table.num_rows):
            bids = json.loads(table.column("bids_json")[row].as_py() or "[]")
            asks = json.loads(table.column("asks_json")[row].as_py() or "[]")
            if not bids or not asks:
                continue
            best_bid = max(float(b["price"]) for b in bids)
            best_ask = min(float(a["price"]) for a in asks)
            if best_bid >= best_ask:
                crossed += 1
        passed = crossed == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"crossed_rows": crossed},
        )


class EmptyBookExpectation(quality_base.QualityExpectation):
    """Warn if both bids and asks are empty in any snapshot."""

    name = "empty_book"

    def __init__(self, *, severity: str = "warn") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"bids_json", "asks_json"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns"},
            )
        empty_count = 0
        for row in range(table.num_rows):
            bids = json.loads(table.column("bids_json")[row].as_py() or "[]")
            asks = json.loads(table.column("asks_json")[row].as_py() or "[]")
            if not bids and not asks:
                empty_count += 1
        passed = empty_count == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"empty_book_rows": empty_count},
        )


class PriceLevelOrderExpectation(quality_base.QualityExpectation):
    """Bids must be descending; asks must be ascending by price."""

    name = "price_level_order"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        missing = {"bids_json", "asks_json"} - set(table.schema.names)
        if table.num_rows == 0 or missing:
            return quality_base.QualityResult(
                expectation_name=self.name,
                passed=True,
                severity=self.severity,
                details={"note": "empty table or missing columns"},
            )
        violations = 0
        for row in range(table.num_rows):
            raw_bids = table.column("bids_json")[row].as_py() or "[]"
            raw_asks = table.column("asks_json")[row].as_py() or "[]"
            bids = [float(b["price"]) for b in json.loads(raw_bids)]
            asks = [float(a["price"]) for a in json.loads(raw_asks)]
            if any(bids[i] < bids[i + 1] for i in range(len(bids) - 1)):
                violations += 1
            if any(asks[i] > asks[i + 1] for i in range(len(asks) - 1)):
                violations += 1
        passed = violations == 0
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=passed,
            severity=self.severity,
            details={"ordering_violations": violations},
        )


BOOK_SUITE = quality_base.QualitySuite(
    "silver_books",
    [
        CrossedBookExpectation(severity="fail"),
        EmptyBookExpectation(severity="warn"),
        PriceLevelOrderExpectation(severity="fail"),
    ],
)
