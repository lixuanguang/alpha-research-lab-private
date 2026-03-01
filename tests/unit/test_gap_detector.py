"""Unit tests for GapDetector."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from alpha_core.quality.gap_detector import GapDetector
from alpha_core.storage.parquet_reader import ParquetEventReader

_START = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
_END = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _mock_reader(trades_table: pa.Table, ohlcv_table: pa.Table | None = None) -> ParquetEventReader:
    reader = MagicMock(spec=ParquetEventReader)
    reader.read_trades.return_value = trades_table
    reader.read_ohlcv.return_value = ohlcv_table or pa.table(
        {
            "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([], type=pa.string()),
            "resolution": pa.array([], type=pa.string()),
        }
    )
    return reader


def _ts_table(timestamps: list[datetime], outcome_id: str = "kalshi:m1:yes") -> pa.Table:
    return pa.table(
        {
            "ts_event": pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([outcome_id] * len(timestamps)),
        }
    )


def _empty_trades_tbl() -> pa.Table:
    return pa.table(
        {
            "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([], type=pa.string()),
        }
    )


def _detect_trades(
    detector: GapDetector,
    *,
    end: datetime = _END,
    max_gap_seconds: float = 3600.0,
) -> list[object]:
    return detector.detect_trade_gaps(
        "kalshi", "kalshi:m1:yes", start=_START, end=end, max_gap_seconds=max_gap_seconds
    )


def _detect_ohlcv(detector: GapDetector, *, resolution: str = "1h") -> list[object]:
    return detector.detect_ohlcv_gaps(
        "kalshi", "kalshi:m1:yes", resolution=resolution, start=_START, end=_END
    )


# ---------------------------------------------------------------------------
# detect_trade_gaps
# ---------------------------------------------------------------------------


def test_no_gaps_returns_empty() -> None:
    """Dense data with no gap exceeding threshold → no gaps detected."""
    # One event every 30 minutes across 12 hours
    ts = [_START + timedelta(minutes=30 * i) for i in range(25)]
    reader = _mock_reader(_ts_table(ts))
    detector = GapDetector(reader)
    gaps = _detect_trades(detector)
    assert gaps == []


def test_single_gap_detected() -> None:
    """Exactly one internal gap: events bookend the window within max_gap_seconds."""
    # ts[0] is 30min after start (no leading gap)
    # ts[1] is 30min before end (no trailing gap)
    # Only 1 internal gap: 11 hours
    ts = [_START + timedelta(minutes=30), _END - timedelta(minutes=30)]
    reader = _mock_reader(_ts_table(ts))
    detector = GapDetector(reader)
    gaps = _detect_trades(detector)
    assert len(gaps) == 1
    t0, t1 = _START + timedelta(minutes=30), _END - timedelta(minutes=30)
    expected_duration = (t1 - t0).total_seconds()
    assert gaps[0].duration_seconds == pytest.approx(expected_duration, abs=1)
    assert gaps[0].event_type == "trade"
    assert gaps[0].venue == "kalshi"


def test_multiple_gaps_detected() -> None:
    """Three events with two gaps."""
    ts = [_START + timedelta(hours=1), _START + timedelta(hours=5), _START + timedelta(hours=11)]
    reader = _mock_reader(_ts_table(ts))
    detector = GapDetector(reader)
    gaps = _detect_trades(detector)
    assert len(gaps) == 2


def test_entire_window_is_gap_when_no_data() -> None:
    """Empty table → whole window is a gap."""
    empty = pa.table(
        {
            "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array([], type=pa.string()),
        }
    )
    reader = _mock_reader(empty)
    detector = GapDetector(reader)
    gaps = _detect_trades(detector)
    assert len(gaps) == 1
    assert gaps[0].gap_start == _START
    assert gaps[0].gap_end == _END


def test_leading_gap_detected() -> None:
    """First event is many hours after window start."""
    ts = [_START + timedelta(hours=8)]
    reader = _mock_reader(_ts_table(ts))
    detector = GapDetector(reader)
    gaps = _detect_trades(detector)
    # Leading gap: 8h before first event
    leading = [g for g in gaps if g.gap_start == _START]
    assert len(leading) == 1
    assert leading[0].duration_seconds == pytest.approx(8 * 3600, abs=1)


def test_trailing_gap_detected() -> None:
    """Last event is long before window end."""
    ts = [_START + timedelta(minutes=5)]
    reader = _mock_reader(_ts_table(ts))
    detector = GapDetector(reader)
    gaps = _detect_trades(detector)
    trailing = [g for g in gaps if g.gap_end == _END]
    assert len(trailing) == 1


def test_gap_below_threshold_not_reported() -> None:
    """A gap smaller than max_gap_seconds should not be reported."""
    ts = [_START, _START + timedelta(minutes=30)]
    reader = _mock_reader(_ts_table(ts))
    detector = GapDetector(reader)
    gaps = detector.detect_trade_gaps(
        "kalshi", "kalshi:m1:yes", start=_START, end=_START + timedelta(hours=1),
        max_gap_seconds=7200.0,
    )
    assert gaps == []


def test_gap_filters_by_outcome_id() -> None:
    """Events from other instruments should not count."""
    ts = [_START + timedelta(hours=1), _START + timedelta(hours=2)]
    tbl = pa.table(
        {
            "ts_event": pa.array(ts, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(["kalshi:m1:no", "kalshi:m1:no"]),  # different outcome
        }
    )
    reader = _mock_reader(tbl)
    detector = GapDetector(reader)
    gaps = _detect_trades(detector)
    # All events belong to a different outcome_id → whole window is a gap
    assert len(gaps) == 1


# ---------------------------------------------------------------------------
# detect_ohlcv_gaps
# ---------------------------------------------------------------------------


def test_ohlcv_no_gaps() -> None:
    """One candle per hour across 12 hours → no gaps."""
    ts = [_START + timedelta(hours=i) for i in range(12)]
    tbl = pa.table(
        {
            "ts_event": pa.array(ts, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(["kalshi:m1:yes"] * 12),
            "resolution": pa.array(["1h"] * 12),
        }
    )
    reader = _mock_reader(_empty_trades_tbl(), ohlcv_table=tbl)
    detector = GapDetector(reader)
    gaps = _detect_ohlcv(detector)
    assert gaps == []


def test_ohlcv_missing_candle_detected() -> None:
    """Hour 3 is missing from the series."""
    ts = [_START + timedelta(hours=i) for i in range(12) if i != 3]
    tbl = pa.table(
        {
            "ts_event": pa.array(ts, type=pa.timestamp("us", tz="UTC")),
            "instrument_id": pa.array(["kalshi:m1:yes"] * len(ts)),
            "resolution": pa.array(["1h"] * len(ts)),
        }
    )
    reader = _mock_reader(_empty_trades_tbl(), ohlcv_table=tbl)
    detector = GapDetector(reader)
    gaps = _detect_ohlcv(detector)
    assert any(g.event_type == "ohlcv" for g in gaps)
    assert len(gaps) >= 1


def test_ohlcv_invalid_resolution_raises() -> None:
    reader = _mock_reader(_empty_trades_tbl())
    detector = GapDetector(reader)
    with pytest.raises(ValueError, match="Unknown resolution"):
        _detect_ohlcv(detector, resolution="99x")
