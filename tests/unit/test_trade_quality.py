"""Unit tests for silver trade quality expectations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa

import alpha_core.quality.suites.trade_quality as quality_trade

_NOW = datetime.now(UTC)
_RECENT = _NOW - timedelta(minutes=10)
_STALE = _NOW - timedelta(hours=2)


def _ts(dt: datetime) -> pa.Array:
    return pa.array([dt], type=pa.timestamp("us", tz="UTC"))


def _trade_table(
    *,
    n: int = 3,
    price: float = 0.5,
    trade_ids: list[str] | None = None,
    ts_event: list[datetime] | None = None,
    ts_record: list[datetime] | None = None,
    nullify: str | None = None,
) -> pa.Table:
    """Build a minimal trade-like PyArrow table."""
    if trade_ids is None:
        trade_ids = [f"t-{i}" for i in range(n)]
    if ts_event is None:
        ts_event = [_RECENT + timedelta(seconds=i) for i in range(n)]
    if ts_record is None:
        ts_record = [t + timedelta(seconds=1) for t in ts_event]

    tbl = pa.table(
        {
            "event_id": pa.array([f"e-{i}" for i in range(n)]),
            "instrument_id": pa.array(["kalshi:m1:yes"] * n),
            "price": pa.array([price] * n, type=pa.float64()),
            "size": pa.array([1.0] * n, type=pa.float64()),
            "trade_id": pa.array(trade_ids),
            "ts_event": pa.array(ts_event, type=pa.timestamp("us", tz="UTC")),
            "ts_record": pa.array(ts_record, type=pa.timestamp("us", tz="UTC")),
        }
    )
    if nullify:
        null_col = pa.array([None] * n, type=tbl.schema.field(nullify).type)
        tbl = tbl.set_column(tbl.schema.get_field_index(nullify), nullify, null_col)
    return tbl


# ---------------------------------------------------------------------------
# NullRateExpectation
# ---------------------------------------------------------------------------


def test_null_rate_pass_no_nulls() -> None:
    tbl = _trade_table()
    result = quality_trade.NullRateExpectation(
        columns=["event_id", "price"],
        threshold=0.0,
    ).validate(tbl)
    assert result.passed is True


def test_null_rate_fail_when_column_all_null() -> None:
    tbl = _trade_table(nullify="price")
    result = quality_trade.NullRateExpectation(columns=["price"], threshold=0.0).validate(tbl)
    assert result.passed is False
    assert result.details["violations"]["price"] == 1.0


def test_null_rate_pass_empty_table() -> None:
    tbl = pa.table({"price": pa.array([], type=pa.float64())})
    result = quality_trade.NullRateExpectation(columns=["price"], threshold=0.0).validate(tbl)
    assert result.passed is True


def test_null_rate_fail_missing_column() -> None:
    tbl = pa.table({"other": pa.array([1])})
    result = quality_trade.NullRateExpectation(
        columns=["price"],
        threshold=0.0,
        severity="fail",
    ).validate(tbl)
    assert result.passed is False


# ---------------------------------------------------------------------------
# PriceBoundsExpectation
# ---------------------------------------------------------------------------


def test_price_bounds_pass_valid() -> None:
    tbl = _trade_table(price=0.5)
    result = quality_trade.PriceBoundsExpectation().validate(tbl)
    assert result.passed is True


def test_price_bounds_fail_above_one() -> None:
    tbl = pa.table({"price": pa.array([1.5], type=pa.float64())})
    result = quality_trade.PriceBoundsExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["out_of_bounds_count"] == 1


def test_price_bounds_fail_below_zero() -> None:
    tbl = pa.table({"price": pa.array([-0.1], type=pa.float64())})
    result = quality_trade.PriceBoundsExpectation().validate(tbl)
    assert result.passed is False


def test_price_bounds_pass_boundary_values() -> None:
    tbl = pa.table({"price": pa.array([0.0, 1.0], type=pa.float64())})
    result = quality_trade.PriceBoundsExpectation().validate(tbl)
    assert result.passed is True


def test_price_bounds_pass_empty_table() -> None:
    tbl = pa.table({"price": pa.array([], type=pa.float64())})
    result = quality_trade.PriceBoundsExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# MonotonicTimestampExpectation
# ---------------------------------------------------------------------------


def test_monotonic_ts_pass_ascending() -> None:
    tbl = _trade_table(n=3)
    result = quality_trade.MonotonicTimestampExpectation().validate(tbl)
    assert result.passed is True


def test_monotonic_ts_fail_regression() -> None:
    ts = [_RECENT, _RECENT + timedelta(seconds=5), _RECENT + timedelta(seconds=2)]
    tbl = _trade_table(n=3, ts_event=ts, ts_record=[t + timedelta(seconds=1) for t in ts])
    result = quality_trade.MonotonicTimestampExpectation().validate(tbl)
    assert result.passed is False


def test_monotonic_ts_pass_single_row() -> None:
    tbl = _trade_table(n=1)
    result = quality_trade.MonotonicTimestampExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# DuplicateTradeIdExpectation
# ---------------------------------------------------------------------------


def test_duplicate_trade_id_pass_unique() -> None:
    tbl = _trade_table(trade_ids=["t1", "t2", "t3"])
    result = quality_trade.DuplicateTradeIdExpectation().validate(tbl)
    assert result.passed is True


def test_duplicate_trade_id_fail_duplicate() -> None:
    tbl = _trade_table(n=3, trade_ids=["t1", "t1", "t2"])
    result = quality_trade.DuplicateTradeIdExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["duplicate_count"] == 1


def test_duplicate_trade_id_pass_empty_table() -> None:
    tbl = pa.table({"trade_id": pa.array([], type=pa.string())})
    result = quality_trade.DuplicateTradeIdExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# StaleDataExpectation
# ---------------------------------------------------------------------------


def test_stale_data_pass_recent() -> None:
    ts = [_NOW - timedelta(minutes=5)]
    tbl = _trade_table(n=1, ts_event=ts, ts_record=[t + timedelta(seconds=1) for t in ts])
    result = quality_trade.StaleDataExpectation(max_age_hours=1.0).validate(tbl)
    assert result.passed is True


def test_stale_data_fail_old_ts() -> None:
    ts = [_NOW - timedelta(hours=3)]
    tbl = _trade_table(n=1, ts_event=ts, ts_record=[t + timedelta(seconds=1) for t in ts])
    result = quality_trade.StaleDataExpectation(max_age_hours=1.0).validate(tbl)
    assert result.passed is False


def test_stale_data_pass_empty_table() -> None:
    tbl = pa.table({"ts_event": pa.array([], type=pa.timestamp("us", tz="UTC"))})
    result = quality_trade.StaleDataExpectation(max_age_hours=1.0).validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# BitemporalOrderExpectation
# ---------------------------------------------------------------------------


def test_bitemporal_order_pass() -> None:
    tbl = _trade_table()
    result = quality_trade.BitemporalOrderExpectation().validate(tbl)
    assert result.passed is True


def test_bitemporal_order_fail_when_event_after_record() -> None:
    ts_event = [_NOW]
    ts_record = [_NOW - timedelta(seconds=10)]  # event > record
    tbl = _trade_table(n=1, ts_event=ts_event, ts_record=ts_record)
    result = quality_trade.BitemporalOrderExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["violation_count"] == 1


def test_bitemporal_order_pass_empty_table() -> None:
    tbl = pa.table(
        {
            "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            "ts_record": pa.array([], type=pa.timestamp("us", tz="UTC")),
        }
    )
    result = quality_trade.BitemporalOrderExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# TRADE_SUITE integration
# ---------------------------------------------------------------------------


def test_trade_suite_passes_clean_data() -> None:
    tbl = _trade_table(n=5)
    report = quality_trade.TRADE_SUITE.validate(tbl)
    assert report.passed is True
    assert report.suite_name == "silver_trades"


def test_trade_suite_fails_duplicate_trade_ids() -> None:
    tbl = _trade_table(n=3, trade_ids=["dup", "dup", "dup"])
    report = quality_trade.TRADE_SUITE.validate(tbl)
    assert report.passed is False
