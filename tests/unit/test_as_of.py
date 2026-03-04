"""Unit tests for as_of join helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest

import alpha_core.research.as_of as as_of_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_table(ts_records: list[datetime], ts_events: list[datetime] | None = None) -> pa.Table:
    """Build a minimal table with ts_record (and optionally ts_event)."""
    schema_fields = [pa.field("ts_record", pa.timestamp("us", tz="UTC"), nullable=False)]
    data: dict[str, list[object]] = {"ts_record": ts_records}

    if ts_events is not None:
        schema_fields.append(pa.field("ts_event", pa.timestamp("us", tz="UTC"), nullable=False))
        data["ts_event"] = ts_events

    schema = pa.schema(schema_fields)
    return pa.table(data, schema=schema)


_T0 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
_T1 = _T0 + timedelta(hours=1)
_T2 = _T0 + timedelta(hours=2)
_T3 = _T0 + timedelta(hours=3)
_T4 = _T0 + timedelta(hours=4)


# ---------------------------------------------------------------------------
# as_of_filter
# ---------------------------------------------------------------------------

class TestAsOfFilter:
    def test_removes_future_records(self) -> None:
        table = _make_table([_T1, _T2, _T3, _T4])
        result = as_of_mod.as_of_filter(table, cutoff=_T2)
        ts = result.column("ts_record").to_pylist()
        assert all(t <= _T2 for t in ts), f"Future leak: {ts}"
        assert len(ts) == 2  # T1 and T2

    def test_inclusive_cutoff(self) -> None:
        table = _make_table([_T1, _T2])
        result = as_of_mod.as_of_filter(table, cutoff=_T2)
        assert result.num_rows == 2

    def test_empty_input_returns_empty(self) -> None:
        empty = pa.table({"ts_record": pa.array([], type=pa.timestamp("us", tz="UTC"))})
        result = as_of_mod.as_of_filter(empty, cutoff=_T3)
        assert result.num_rows == 0

    def test_all_future_returns_empty(self) -> None:
        table = _make_table([_T3, _T4])
        result = as_of_mod.as_of_filter(table, cutoff=_T1)
        assert result.num_rows == 0

    def test_all_past_retained(self) -> None:
        table = _make_table([_T1, _T2])
        result = as_of_mod.as_of_filter(table, cutoff=_T4)
        assert result.num_rows == 2

    def test_custom_column_name(self) -> None:
        schema = pa.schema([pa.field("ts_event", pa.timestamp("us", tz="UTC"))])
        table = pa.table({"ts_event": [_T1, _T3]}, schema=schema)
        result = as_of_mod.as_of_filter(table, as_of_column="ts_event", cutoff=_T2)
        assert result.num_rows == 1

    def test_missing_column_raises_key_error(self) -> None:
        table = pa.table({"price": [1, 2, 3]})
        with pytest.raises(KeyError, match="ts_record"):
            as_of_mod.as_of_filter(table, cutoff=_T2)

    def test_timezone_naive_cutoff_treated_as_utc(self) -> None:
        naive_cutoff = datetime(2024, 1, 1, 2, 0, 0)  # no tzinfo
        table = _make_table([_T1, _T2, _T3])
        result = as_of_mod.as_of_filter(table, cutoff=naive_cutoff)
        assert result.num_rows == 2  # T1 and T2


# ---------------------------------------------------------------------------
# align_to_grid
# ---------------------------------------------------------------------------

class TestAlignToGrid:
    def _trade_table(self, records: list[tuple[datetime, datetime, str]]) -> pa.Table:
        """Build a small table with ts_record, ts_event, instrument_id."""
        ts_records, ts_events, ids = zip(*records, strict=True)
        return pa.table(
            {
                "ts_record": list(ts_records),
                "ts_event": list(ts_events),
                "instrument_id": list(ids),
            },
            schema=pa.schema(
                [
                    pa.field("ts_record", pa.timestamp("us", tz="UTC")),
                    pa.field("ts_event", pa.timestamp("us", tz="UTC")),
                    pa.field("instrument_id", pa.string()),
                ]
            ),
        )

    def test_grid_timestamps_added(self) -> None:
        table = self._trade_table(
            [(_T1, _T1, "abc"), (_T2, _T2, "abc")]
        )
        result = as_of_mod.align_to_grid(
            {"trades": table},
            spec=as_of_mod.GridAlignmentSpec(
                frequency="1h",
                start=_T1,
                end=_T3,
            ),
        )
        assert "grid_ts" in result["trades"].schema.names

    def test_no_future_leak_on_grid_boundary(self) -> None:
        # Row recorded at T3 should not appear on the T2 grid slice
        table = self._trade_table(
            [(_T1, _T1, "x"), (_T3, _T3, "x")]
        )
        result = as_of_mod.align_to_grid(
            {"trades": table},
            spec=as_of_mod.GridAlignmentSpec(
                frequency="1h",
                start=_T1,
                end=_T2,
            ),
        )
        # Rows with ts_record == T3 must not appear in aligned output (cutoff=T2)
        ts_records = result["trades"].column("ts_record").to_pylist()
        assert all(t <= _T2 for t in ts_records), f"Look-ahead leaked: {ts_records}"

    def test_empty_table_passthrough(self) -> None:
        empty = pa.table(
            {
                "ts_record": pa.array([], type=pa.timestamp("us", tz="UTC")),
                "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            }
        )
        result = as_of_mod.align_to_grid(
            {"trades": empty},
            spec=as_of_mod.GridAlignmentSpec(
                frequency="1h",
                start=_T1,
                end=_T2,
            ),
        )
        assert result["trades"].num_rows == 0

    def test_multiple_tables_aligned(self) -> None:
        trade_table = self._trade_table([(_T1, _T1, "a")])
        ohlcv_table = self._trade_table([(_T2, _T2, "b")])
        result = as_of_mod.align_to_grid(
            {"trades": trade_table, "ohlcv": ohlcv_table},
            spec=as_of_mod.GridAlignmentSpec(
                frequency="1h",
                start=_T1,
                end=_T3,
            ),
        )
        assert set(result.keys()) == {"trades", "ohlcv"}
        assert "grid_ts" in result["trades"].schema.names
        assert "grid_ts" in result["ohlcv"].schema.names
