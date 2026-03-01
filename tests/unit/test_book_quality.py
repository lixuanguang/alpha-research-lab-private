"""Unit tests for silver book quality expectations."""

from __future__ import annotations

import json

import pyarrow as pa

from alpha_core.quality.suites.book_quality import (
    BOOK_SUITE,
    CrossedBookExpectation,
    EmptyBookExpectation,
    PriceLevelOrderExpectation,
)


def _book_table(
    *,
    bids: list[list[dict]] | None = None,
    asks: list[list[dict]] | None = None,
) -> pa.Table:
    if bids is None:
        bids = [[{"price": "0.48", "size": "10"}, {"price": "0.45", "size": "5"}]]
    if asks is None:
        asks = [[{"price": "0.52", "size": "8"}, {"price": "0.55", "size": "4"}]]
    return pa.table(
        {
            "bids_json": pa.array([json.dumps(b) for b in bids]),
            "asks_json": pa.array([json.dumps(a) for a in asks]),
        }
    )


# ---------------------------------------------------------------------------
# CrossedBookExpectation
# ---------------------------------------------------------------------------


def test_crossed_book_pass_normal() -> None:
    tbl = _book_table()
    result = CrossedBookExpectation().validate(tbl)
    assert result.passed is True


def test_crossed_book_fail_bid_equals_ask() -> None:
    tbl = _book_table(
        bids=[[{"price": "0.50", "size": "10"}]],
        asks=[[{"price": "0.50", "size": "5"}]],
    )
    result = CrossedBookExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["crossed_rows"] == 1


def test_crossed_book_fail_bid_above_ask() -> None:
    tbl = _book_table(
        bids=[[{"price": "0.60", "size": "10"}]],
        asks=[[{"price": "0.55", "size": "5"}]],
    )
    result = CrossedBookExpectation().validate(tbl)
    assert result.passed is False


def test_crossed_book_pass_empty_bids() -> None:
    """Empty bids cannot be crossed — skip those rows."""
    tbl = _book_table(bids=[[]], asks=[[{"price": "0.52", "size": "5"}]])
    result = CrossedBookExpectation().validate(tbl)
    assert result.passed is True


def test_crossed_book_pass_empty_table() -> None:
    tbl = pa.table(
        {"bids_json": pa.array([], type=pa.string()), "asks_json": pa.array([], type=pa.string())}
    )
    result = CrossedBookExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# EmptyBookExpectation
# ---------------------------------------------------------------------------


def test_empty_book_pass_normal() -> None:
    tbl = _book_table()
    result = EmptyBookExpectation().validate(tbl)
    assert result.passed is True


def test_empty_book_fail_both_sides_empty() -> None:
    tbl = _book_table(bids=[[]], asks=[[]])
    result = EmptyBookExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["empty_book_rows"] == 1


def test_empty_book_pass_only_bids_empty() -> None:
    tbl = _book_table(bids=[[]], asks=[[{"price": "0.52", "size": "5"}]])
    result = EmptyBookExpectation().validate(tbl)
    assert result.passed is True  # only degraded if BOTH sides empty


# ---------------------------------------------------------------------------
# PriceLevelOrderExpectation
# ---------------------------------------------------------------------------


def test_price_level_order_pass_correct() -> None:
    tbl = _book_table(
        bids=[[{"price": "0.50", "size": "10"}, {"price": "0.45", "size": "5"}]],
        asks=[[{"price": "0.55", "size": "8"}, {"price": "0.60", "size": "4"}]],
    )
    result = PriceLevelOrderExpectation().validate(tbl)
    assert result.passed is True


def test_price_level_order_fail_bids_ascending() -> None:
    """Bids should be descending — ascending bids are a violation."""
    tbl = _book_table(
        bids=[[{"price": "0.45", "size": "5"}, {"price": "0.50", "size": "10"}]],  # ascending bids
        asks=[[{"price": "0.55", "size": "8"}]],
    )
    result = PriceLevelOrderExpectation().validate(tbl)
    assert result.passed is False


def test_price_level_order_fail_asks_descending() -> None:
    """Asks should be ascending — descending asks are a violation."""
    tbl = _book_table(
        bids=[[{"price": "0.50", "size": "5"}]],
        asks=[[{"price": "0.60", "size": "4"}, {"price": "0.55", "size": "8"}]],  # descending asks
    )
    result = PriceLevelOrderExpectation().validate(tbl)
    assert result.passed is False


def test_price_level_order_pass_single_level() -> None:
    tbl = _book_table(
        bids=[[{"price": "0.49", "size": "5"}]],
        asks=[[{"price": "0.51", "size": "5"}]],
    )
    result = PriceLevelOrderExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# BOOK_SUITE integration
# ---------------------------------------------------------------------------


def test_book_suite_passes_clean_data() -> None:
    tbl = _book_table()
    report = BOOK_SUITE.validate(tbl)
    assert report.passed is True
    assert report.suite_name == "silver_books"


def test_book_suite_fails_crossed_books() -> None:
    tbl = _book_table(
        bids=[[{"price": "0.60", "size": "10"}]],
        asks=[[{"price": "0.55", "size": "5"}]],
    )
    report = BOOK_SUITE.validate(tbl)
    assert report.passed is False
