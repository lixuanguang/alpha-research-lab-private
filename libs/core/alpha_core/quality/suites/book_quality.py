"""Quality expectations for silver books partitions."""

from __future__ import annotations

import json
from typing import Any, Literal

import pyarrow as pa

import alpha_core.quality.base as quality_base

_BOOK_JSON_COLUMNS = frozenset({"bids_json", "asks_json"})
_MISSING_NOTE = "empty table or missing columns"


def _skipped_result(
    *,
    expectation_name: str,
    severity: Literal["warn", "fail"],
) -> quality_base.QualityResult:
    return quality_base.QualityResult(
        expectation_name=expectation_name,
        passed=True,
        severity=severity,
        details={"note": _MISSING_NOTE},
    )


def _parsed_book_rows(
    table: pa.Table,
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None:
    if table.num_rows == 0 or not _BOOK_JSON_COLUMNS.issubset(table.schema.names):
        return None
    bids_column = table.column("bids_json").to_pylist()
    asks_column = table.column("asks_json").to_pylist()
    return [
        (_parse_levels(raw_bids), _parse_levels(raw_asks))
        for raw_bids, raw_asks in zip(bids_column, asks_column, strict=True)
    ]


def _parse_levels(raw_levels: str | None) -> list[dict[str, Any]]:
    parsed = json.loads(raw_levels or "[]")
    return parsed if isinstance(parsed, list) else []


class CrossedBookExpectation(quality_base.QualityExpectation):
    """Best bid must be strictly less than best ask; no crossed books."""

    name = "crossed_book"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        rows = _parsed_book_rows(table)
        if rows is None:
            return _skipped_result(expectation_name=self.name, severity=self.severity)
        crossed = 0
        for bids, asks in rows:
            if not bids or not asks:
                continue
            best_bid = max(float(bid["price"]) for bid in bids)
            best_ask = min(float(ask["price"]) for ask in asks)
            if best_bid >= best_ask:
                crossed += 1
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=crossed == 0,
            severity=self.severity,
            details={"crossed_rows": crossed},
        )


class EmptyBookExpectation(quality_base.QualityExpectation):
    """Warn if both bids and asks are empty in any snapshot."""

    name = "empty_book"

    def __init__(self, *, severity: str = "warn") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        rows = _parsed_book_rows(table)
        if rows is None:
            return _skipped_result(expectation_name=self.name, severity=self.severity)
        empty_count = 0
        for bids, asks in rows:
            if not bids and not asks:
                empty_count += 1
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=empty_count == 0,
            severity=self.severity,
            details={"empty_book_rows": empty_count},
        )


class PriceLevelOrderExpectation(quality_base.QualityExpectation):
    """Bids must be descending; asks must be ascending by price."""

    name = "price_level_order"

    def __init__(self, *, severity: str = "fail") -> None:
        self.severity = severity  # type: ignore[assignment]

    def validate(self, table: pa.Table) -> quality_base.QualityResult:
        rows = _parsed_book_rows(table)
        if rows is None:
            return _skipped_result(expectation_name=self.name, severity=self.severity)
        violations = 0
        for bids, asks in rows:
            bid_prices = [float(level["price"]) for level in bids]
            ask_prices = [float(level["price"]) for level in asks]
            if any(
                bid_prices[index] < bid_prices[index + 1] for index in range(len(bid_prices) - 1)
            ):
                violations += 1
            if any(
                ask_prices[index] > ask_prices[index + 1] for index in range(len(ask_prices) - 1)
            ):
                violations += 1
        return quality_base.QualityResult(
            expectation_name=self.name,
            passed=violations == 0,
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
