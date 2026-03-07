"""Gap detection — identify missing time windows in silver data partitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pyarrow.compute as pc
from pydantic import BaseModel, ConfigDict

import alpha_core.storage.parquet_reader as parquet_reader_mod

# Resolution → expected candle duration in seconds
_RESOLUTION_SECONDS: dict[str, float] = {
    "1m": 60.0,
    "5m": 300.0,
    "1h": 3600.0,
    "1d": 86400.0,
}


class TimeGap(BaseModel):
    """A detected gap in silver data for a specific venue and instrument."""

    model_config = ConfigDict(extra="forbid")

    venue: str
    outcome_id: str
    gap_start: datetime
    gap_end: datetime
    duration_seconds: float
    event_type: str


@dataclass(slots=True, frozen=True)
class _GapIdentity:
    venue: str
    outcome_id: str
    event_type: str


class GapDetector:
    """Identifies missing time windows in silver trade, book, and OHLCV data."""

    def __init__(self, reader: parquet_reader_mod.ParquetEventReader) -> None:
        self._reader = reader

    def detect_trade_gaps(
        self,
        venue: str,
        outcome_id: str,
        *,
        start: datetime,
        end: datetime,
        max_gap_seconds: float = 3600.0,
    ) -> list[TimeGap]:
        """Return windows where no trades exist for longer than max_gap_seconds."""
        _validate_window(start=start, end=end)
        if max_gap_seconds <= 0:
            raise ValueError("`max_gap_seconds` must be > 0")
        table = self._reader.read_trades(venue=venue, start=start, end=end)
        if "instrument_id" in table.schema.names:
            table = table.filter(pc.equal(table.column("instrument_id"), outcome_id))

        if table.num_rows == 0:
            # The entire window is a gap
            duration = (end - start).total_seconds()
            if duration > max_gap_seconds:
                return [
                    TimeGap(
                        venue=venue,
                        outcome_id=outcome_id,
                        gap_start=_ensure_utc(start),
                        gap_end=_ensure_utc(end),
                        duration_seconds=duration,
                        event_type="trade",
                    )
                ]
            return []

        ts_list: list[datetime] = sorted(
            _ensure_utc(ts) for ts in table.column("ts_event").to_pylist()
        )
        return _find_gaps(
            timestamps=ts_list,
            window_start=_ensure_utc(start),
            window_end=_ensure_utc(end),
            max_gap_seconds=max_gap_seconds,
            identity=_GapIdentity(
                venue=venue,
                outcome_id=outcome_id,
                event_type="trade",
            ),
        )

    def detect_book_gaps(
        self,
        venue: str,
        outcome_id: str,
        *,
        start: datetime,
        end: datetime,
        max_gap_seconds: float = 3600.0,
    ) -> list[TimeGap]:
        """Return windows where no book snapshots exist for longer than max_gap_seconds."""
        _validate_window(start=start, end=end)
        if max_gap_seconds <= 0:
            raise ValueError("`max_gap_seconds` must be > 0")
        table = self._reader.read_books(venue=venue, start=start, end=end)
        if "instrument_id" in table.schema.names:
            table = table.filter(pc.equal(table.column("instrument_id"), outcome_id))

        if table.num_rows == 0:
            duration = (end - start).total_seconds()
            if duration > max_gap_seconds:
                return [
                    TimeGap(
                        venue=venue,
                        outcome_id=outcome_id,
                        gap_start=_ensure_utc(start),
                        gap_end=_ensure_utc(end),
                        duration_seconds=duration,
                        event_type="book",
                    )
                ]
            return []

        ts_list: list[datetime] = sorted(
            _ensure_utc(ts) for ts in table.column("ts_event").to_pylist()
        )
        return _find_gaps(
            timestamps=ts_list,
            window_start=_ensure_utc(start),
            window_end=_ensure_utc(end),
            max_gap_seconds=max_gap_seconds,
            identity=_GapIdentity(
                venue=venue,
                outcome_id=outcome_id,
                event_type="book",
            ),
        )

    def detect_ohlcv_gaps(
        self,
        venue: str,
        outcome_id: str,
        *,
        resolution: str,
        start: datetime,
        end: datetime,
    ) -> list[TimeGap]:
        """Return missing candle periods based on the expected resolution cadence."""
        _validate_window(start=start, end=end)
        candle_seconds = _RESOLUTION_SECONDS.get(resolution)
        if candle_seconds is None:
            valid = list(_RESOLUTION_SECONDS)
            raise ValueError(f"Unknown resolution '{resolution}'. Expected one of {valid}")

        table = self._reader.read_ohlcv(venue=venue, resolution=resolution, start=start, end=end)
        if "instrument_id" in table.schema.names:
            table = table.filter(pc.equal(table.column("instrument_id"), outcome_id))

        present: set[datetime] = {
            _floor_to_resolution(_ensure_utc(ts), candle_seconds)
            for ts in table.column("ts_event").to_pylist()
        }

        gaps: list[TimeGap] = []
        cursor = _floor_to_resolution(_ensure_utc(start), candle_seconds)
        floor_end = _floor_to_resolution(_ensure_utc(end), candle_seconds)

        while cursor <= floor_end:
            if cursor not in present:
                gap_end = cursor + timedelta(seconds=candle_seconds)
                gaps.append(
                    TimeGap(
                        venue=venue,
                        outcome_id=outcome_id,
                        gap_start=cursor,
                        gap_end=gap_end,
                        duration_seconds=candle_seconds,
                        event_type="ohlcv",
                    )
                )
            cursor += timedelta(seconds=candle_seconds)
        return gaps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _validate_window(*, start: datetime, end: datetime) -> None:
    if _ensure_utc(end) <= _ensure_utc(start):
        raise ValueError("`end` must be later than `start`")


def _floor_to_resolution(dt: datetime, candle_seconds: float) -> datetime:
    """Truncate a datetime to the nearest candle boundary."""
    ts = dt.timestamp()
    floored = (ts // candle_seconds) * candle_seconds
    return datetime.fromtimestamp(floored, tz=UTC)


def _find_gaps(
    *,
    timestamps: list[datetime],
    window_start: datetime,
    window_end: datetime,
    max_gap_seconds: float,
    identity: _GapIdentity,
) -> list[TimeGap]:
    """Find spans > max_gap_seconds with no events, including leading/trailing gaps."""
    gaps: list[TimeGap] = []

    # Leading gap: before first event
    if (timestamps[0] - window_start).total_seconds() > max_gap_seconds:
        gaps.append(
            TimeGap(
                venue=identity.venue,
                outcome_id=identity.outcome_id,
                gap_start=window_start,
                gap_end=timestamps[0],
                duration_seconds=(timestamps[0] - window_start).total_seconds(),
                event_type=identity.event_type,
            )
        )

    # Internal gaps
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta > max_gap_seconds:
            gaps.append(
                TimeGap(
                    venue=identity.venue,
                    outcome_id=identity.outcome_id,
                    gap_start=timestamps[i - 1],
                    gap_end=timestamps[i],
                    duration_seconds=delta,
                    event_type=identity.event_type,
                )
            )

    # Trailing gap: after last event
    if (window_end - timestamps[-1]).total_seconds() > max_gap_seconds:
        gaps.append(
            TimeGap(
                venue=identity.venue,
                outcome_id=identity.outcome_id,
                gap_start=timestamps[-1],
                gap_end=window_end,
                duration_seconds=(window_end - timestamps[-1]).total_seconds(),
                event_type=identity.event_type,
            )
        )

    return gaps
