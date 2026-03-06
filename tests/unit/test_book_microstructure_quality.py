"""Unit tests for microstructure book quality expectations (D5 extension 11.2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest

import alpha_core.quality.suites.book_microstructure_quality as quality_book

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _ts(offset_seconds: float = 0.0) -> datetime:
    return _BASE_TS + timedelta(seconds=offset_seconds)


def _book_snapshot_table(
    *,
    instrument_ids: list[str] | None = None,
    ts_events: list[datetime] | None = None,
    bids_list: list[list[dict]] | None = None,
    asks_list: list[list[dict]] | None = None,
    sequence_ids: list[str | None] | None = None,
) -> pa.Table:
    """Build a minimal snapshot table for microstructure expectation tests."""
    n = len(ts_events) if ts_events is not None else 1
    if instrument_ids is None:
        instrument_ids = ["outcome-1"] * n
    if ts_events is None:
        ts_events = [_ts(i * 10) for i in range(n)]
    if bids_list is None:
        bids_list = [[{"price": "0.48", "size": "10"}]] * n
    if asks_list is None:
        asks_list = [[{"price": "0.52", "size": "10"}]] * n
    if sequence_ids is None:
        sequence_ids = [None] * n

    return pa.table(
        {
            "instrument_id": pa.array(instrument_ids, type=pa.string()),
            "ts_event": pa.array(ts_events, type=pa.timestamp("us", tz="UTC")),
            "bids_json": pa.array([json.dumps(b) for b in bids_list], type=pa.string()),
            "asks_json": pa.array([json.dumps(a) for a in asks_list], type=pa.string()),
            "sequence_id": pa.array(sequence_ids, type=pa.string()),
        }
    )


def _delta_table(
    *,
    instrument_ids: list[str],
    prices: list[str],
    sides: list[str],
    delta_sizes: list[str],
    is_reconstructed: list[bool],
    ts_events: list[datetime] | None = None,
) -> pa.Table:
    """Build a minimal book_deltas table for DeltaConservationExpectation tests."""
    n = len(instrument_ids)
    if ts_events is None:
        ts_events = [_ts(i) for i in range(n)]
    return pa.table(
        {
            "instrument_id": pa.array(instrument_ids, type=pa.string()),
            "price": pa.array(prices, type=pa.string()),
            "side": pa.array(sides, type=pa.string()),
            "delta_size": pa.array(delta_sizes, type=pa.string()),
            "is_reconstructed": pa.array(is_reconstructed, type=pa.bool_()),
            "ts_event": pa.array(ts_events, type=pa.timestamp("us", tz="UTC")),
        }
    )


# ---------------------------------------------------------------------------
# SequenceContinuityExpectation
# ---------------------------------------------------------------------------


def test_sequence_continuity_pass_all_null() -> None:
    """Entirely-null sequence_id means venue doesn't expose sequences → pass."""
    tbl = _book_snapshot_table(
        ts_events=[_ts(0), _ts(10)],
        sequence_ids=[None, None],
    )
    result = quality_book.SequenceContinuityExpectation().validate(tbl)
    assert result.passed is True


def test_sequence_continuity_pass_consecutive() -> None:
    tbl = _book_snapshot_table(
        ts_events=[_ts(0), _ts(10), _ts(20)],
        sequence_ids=["1", "2", "3"],
    )
    result = quality_book.SequenceContinuityExpectation().validate(tbl)
    assert result.passed is True
    assert result.details["sequence_gaps"] == 0


def test_sequence_continuity_fail_gap() -> None:
    """Sequence jump of > 1 within an instrument signals dropped messages."""
    tbl = _book_snapshot_table(
        ts_events=[_ts(0), _ts(10), _ts(20)],
        sequence_ids=["1", "2", "5"],  # gap: 2 → 5
    )
    result = quality_book.SequenceContinuityExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["sequence_gaps"] >= 1


def test_sequence_continuity_pass_gap_different_instruments() -> None:
    """Sequence gaps on separate instruments should not cross-contaminate."""
    tbl = _book_snapshot_table(
        instrument_ids=["A", "A", "B", "B"],
        ts_events=[_ts(0), _ts(10), _ts(0), _ts(10)],
        sequence_ids=["1", "2", "10", "11"],  # B has non-contiguous but independent
    )
    result = quality_book.SequenceContinuityExpectation().validate(tbl)
    # No gap within A (1→2), no gap within B (10→11 is +1 so fine)
    assert result.passed is True


def test_sequence_continuity_pass_empty_table() -> None:
    tbl = pa.table(
        {
            "instrument_id": pa.array([], type=pa.string()),
            "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            "bids_json": pa.array([], type=pa.string()),
            "asks_json": pa.array([], type=pa.string()),
            "sequence_id": pa.array([], type=pa.string()),
        }
    )
    result = quality_book.SequenceContinuityExpectation().validate(tbl)
    assert result.passed is True


def test_sequence_continuity_pass_missing_column() -> None:
    """Table without sequence_id column should pass gracefully."""
    tbl = pa.table({"instrument_id": pa.array(["A"]), "ts_event": pa.array([_ts(0)])})
    result = quality_book.SequenceContinuityExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# SnapshotCadenceExpectation
# ---------------------------------------------------------------------------


def test_snapshot_cadence_pass_regular() -> None:
    tbl = _book_snapshot_table(ts_events=[_ts(0), _ts(10), _ts(20), _ts(30)])
    result = quality_book.SnapshotCadenceExpectation(max_gap_seconds=60.0).validate(tbl)
    assert result.passed is True
    assert result.details["cadence_violations"] == 0


def test_snapshot_cadence_fail_large_gap() -> None:
    tbl = _book_snapshot_table(ts_events=[_ts(0), _ts(10), _ts(200)])  # 190s gap
    result = quality_book.SnapshotCadenceExpectation(max_gap_seconds=60.0).validate(tbl)
    assert result.passed is False
    assert result.details["cadence_violations"] >= 1
    assert result.details["max_gap_seconds_observed"] > 60.0


def test_snapshot_cadence_pass_single_row() -> None:
    """Single row per instrument — no pairs to compare, always passes."""
    tbl = _book_snapshot_table(ts_events=[_ts(0)])
    result = quality_book.SnapshotCadenceExpectation(max_gap_seconds=5.0).validate(tbl)
    assert result.passed is True


def test_snapshot_cadence_different_instruments_checked_separately() -> None:
    """Gap between instruments in different groups should not trigger violations."""
    tbl = _book_snapshot_table(
        instrument_ids=["A", "B"],
        ts_events=[_ts(0), _ts(300)],  # 300s apart but different instruments
    )
    result = quality_book.SnapshotCadenceExpectation(max_gap_seconds=60.0).validate(tbl)
    assert result.passed is True


def test_snapshot_cadence_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="max_gap_seconds"):
        quality_book.SnapshotCadenceExpectation(max_gap_seconds=0.0)


# ---------------------------------------------------------------------------
# TopOfBookStabilityExpectation
# ---------------------------------------------------------------------------


def test_top_of_book_stability_pass_small_move() -> None:
    tbl = _book_snapshot_table(
        ts_events=[_ts(0), _ts(10)],
        bids_list=[[{"price": "0.48", "size": "10"}], [{"price": "0.49", "size": "10"}]],
        asks_list=[[{"price": "0.52", "size": "10"}], [{"price": "0.53", "size": "10"}]],
    )
    result = quality_book.TopOfBookStabilityExpectation(max_move_frac=0.20).validate(tbl)
    assert result.passed is True


def test_top_of_book_stability_fail_large_move() -> None:
    """Best bid jumping from 0.50 to 0.10 is a >20% move."""
    tbl = _book_snapshot_table(
        ts_events=[_ts(0), _ts(10)],
        bids_list=[
            [{"price": "0.50", "size": "10"}],
            [{"price": "0.10", "size": "10"}],  # 80% drop
        ],
        asks_list=[
            [{"price": "0.55", "size": "10"}],
            [{"price": "0.55", "size": "10"}],
        ],
    )
    result = quality_book.TopOfBookStabilityExpectation(max_move_frac=0.20).validate(tbl)
    assert result.passed is False
    assert result.details["stability_violations"] >= 1


def test_top_of_book_stability_pass_single_row() -> None:
    tbl = _book_snapshot_table(ts_events=[_ts(0)])
    result = quality_book.TopOfBookStabilityExpectation().validate(tbl)
    assert result.passed is True


def test_top_of_book_stability_pass_empty_table() -> None:
    result = quality_book.TopOfBookStabilityExpectation().validate(pa.table({}))
    assert result.passed is True


def test_top_of_book_stability_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="max_move_frac"):
        quality_book.TopOfBookStabilityExpectation(max_move_frac=1.5)


# ---------------------------------------------------------------------------
# DeltaConservationExpectation
# ---------------------------------------------------------------------------


def test_delta_conservation_pass_balanced() -> None:
    """One add + one cancel at the same price/side — net zero is fine."""
    tbl = _delta_table(
        instrument_ids=["A", "A"],
        prices=["0.48", "0.48"],
        sides=["bid", "bid"],
        delta_sizes=["10", "-10"],
        is_reconstructed=[True, True],
    )
    result = quality_book.DeltaConservationExpectation().validate(tbl)
    assert result.passed is True


def test_delta_conservation_fail_overcancellation() -> None:
    """Cancel more than was added → negative depth."""
    tbl = _delta_table(
        instrument_ids=["A", "A"],
        prices=["0.48", "0.48"],
        sides=["bid", "bid"],
        delta_sizes=["5", "-10"],  # running sum: 5 → -5 (violation)
        is_reconstructed=[True, True],
    )
    result = quality_book.DeltaConservationExpectation().validate(tbl)
    assert result.passed is False
    assert result.details["conservation_violations"] >= 1


def test_delta_conservation_pass_native_deltas_excluded() -> None:
    """is_reconstructed=False rows are excluded from the check."""
    tbl = _delta_table(
        instrument_ids=["A", "A"],
        prices=["0.48", "0.48"],
        sides=["bid", "bid"],
        delta_sizes=["5", "-10"],
        is_reconstructed=[False, False],  # native feed — not checked
    )
    result = quality_book.DeltaConservationExpectation().validate(tbl)
    assert result.passed is True


def test_delta_conservation_pass_no_reconstructed_rows() -> None:
    """Empty reconstructed subset → pass with note."""
    tbl = _delta_table(
        instrument_ids=["A"],
        prices=["0.50"],
        sides=["ask"],
        delta_sizes=["5"],
        is_reconstructed=[False],
    )
    result = quality_book.DeltaConservationExpectation().validate(tbl)
    assert result.passed is True


def test_delta_conservation_pass_missing_columns() -> None:
    tbl = pa.table({"event_id": pa.array(["x"])})
    result = quality_book.DeltaConservationExpectation().validate(tbl)
    assert result.passed is True


# ---------------------------------------------------------------------------
# StaleBookAgeExpectation
# ---------------------------------------------------------------------------


def test_stale_book_age_pass_recent() -> None:
    """Snapshot from a few seconds ago should pass."""
    now = datetime.now(UTC)
    tbl = _book_snapshot_table(ts_events=[now - timedelta(seconds=5)])
    result = quality_book.StaleBookAgeExpectation(max_age_seconds=30.0).validate(tbl)
    assert result.passed is True


def test_stale_book_age_fail_old_snapshot() -> None:
    """Snapshot older than threshold should fail."""
    old_ts = datetime.now(UTC) - timedelta(seconds=120)
    tbl = _book_snapshot_table(ts_events=[old_ts])
    result = quality_book.StaleBookAgeExpectation(max_age_seconds=30.0).validate(tbl)
    assert result.passed is False
    assert result.details["age_seconds"] > 30.0


def test_stale_book_age_pass_empty_table() -> None:
    tbl = pa.table({"event_id": pa.array([], type=pa.string())})
    result = quality_book.StaleBookAgeExpectation(max_age_seconds=30.0).validate(tbl)
    assert result.passed is True


def test_stale_book_age_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="max_age_seconds"):
        quality_book.StaleBookAgeExpectation(max_age_seconds=0.0)


# ---------------------------------------------------------------------------
# BOOK_MICROSTRUCTURE_SUITE
# ---------------------------------------------------------------------------


def test_microstructure_suite_all_pass_on_clean_data() -> None:
    """Clean snapshot data with no violations should produce passed=True."""
    now = datetime.now(UTC)
    tbl = _book_snapshot_table(
        instrument_ids=["outcome-1", "outcome-1", "outcome-1"],
        ts_events=[now - timedelta(seconds=20), now - timedelta(seconds=10), now],
        bids_list=[
            [{"price": "0.48", "size": "10"}],
            [{"price": "0.48", "size": "10"}],
            [{"price": "0.49", "size": "10"}],
        ],
        asks_list=[
            [{"price": "0.52", "size": "10"}],
            [{"price": "0.52", "size": "10"}],
            [{"price": "0.51", "size": "10"}],
        ],
        sequence_ids=["1", "2", "3"],
    )
    report = quality_book.BOOK_MICROSTRUCTURE_SUITE.validate(tbl)
    assert report.passed is True
    assert report.degraded is False


def test_microstructure_suite_has_correct_name() -> None:
    assert quality_book.BOOK_MICROSTRUCTURE_SUITE.name == "silver_books_microstructure"


def test_microstructure_suite_detects_sequence_gap() -> None:
    now = datetime.now(UTC)
    tbl = _book_snapshot_table(
        ts_events=[now - timedelta(seconds=20), now - timedelta(seconds=10), now],
        sequence_ids=["1", "2", "10"],  # gap at the end
    )
    report = quality_book.BOOK_MICROSTRUCTURE_SUITE.validate(tbl)
    assert report.degraded is True  # sequence_continuity is "warn"
    seq_result = next(r for r in report.results if r.expectation_name == "sequence_continuity")
    assert seq_result.passed is False
