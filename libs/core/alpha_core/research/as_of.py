"""As-of join helpers for point-in-time look-ahead bias protection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

import alpha_core.utils.time as time_utils


@dataclass(slots=True, frozen=True)
class GridAlignmentSpec:
    frequency: str
    start: datetime
    end: datetime
    as_of_column: str = "ts_record"
    ts_column: str = "ts_event"


def as_of_filter(
    table: pa.Table,
    *,
    as_of_column: str = "ts_record",
    cutoff: datetime,
) -> pa.Table:
    """Filter *table* to rows where *as_of_column* <= *cutoff*.

    Uses the record timestamp (``ts_record``), not the event timestamp
    (``ts_event``), so only information that was physically available at
    *cutoff* is retained — eliminating look-ahead bias from late-arriving data.

    Args:
        table:         PyArrow table with a timestamp column.
        as_of_column:  Column name to filter on.  Defaults to ``"ts_record"``.
        cutoff:        Inclusive upper bound.  Timezone-naive values are assumed UTC.

    Returns:
        Filtered table (may be empty).

    Raises:
        KeyError:  When *as_of_column* is not present in *table*.
    """
    if as_of_column not in table.schema.names:
        raise KeyError(f"Column '{as_of_column}' not found in table schema.")

    cutoff_utc = time_utils.ensure_utc(cutoff)
    cutoff_scalar = pa.scalar(cutoff_utc, type=pa.timestamp("us", tz="UTC"))
    mask = pc.less_equal(table.column(as_of_column), cutoff_scalar)
    return table.filter(mask)


def align_to_grid(
    tables: dict[str, pa.Table],
    *,
    spec: GridAlignmentSpec,
) -> dict[str, pa.Table]:
    """Align multiple tables to a uniform time grid via an as-of join.

    For each grid timestamp *t*, each table is filtered to events where
    ``ts_event <= t`` **and** ``ts_record <= t`` (no look-ahead on either
    dimension), retaining only the latest row per instrument per grid point.

    The result contains one entry per grid timestamp with all rows whose
    most-recent event falls within that bucket.

    Args:
        tables:       Mapping of label → PyArrow Table.  Each table must have
                      *as_of_column* and *ts_column* timestamp columns.
        frequency:    Pandas-compatible offset alias: ``"1h"``, ``"1d"``, etc.
        start:        Grid start (inclusive).
        end:          Grid end (inclusive).
        as_of_column: Column used for look-ahead protection (default ``ts_record``).
        ts_column:    Event-time column used for grid alignment (default ``ts_event``).

    Returns:
        Dict with the same keys, each value being the as-of-aligned table
        containing a ``grid_ts`` column (UTC timestamp) added to identify the
        grid point each row was assigned to.
    """
    import pandas as pd  # type: ignore[import-untyped]  # lazy import — pandas not always needed

    start_utc = time_utils.ensure_utc(spec.start)
    end_utc = time_utils.ensure_utc(spec.end)
    grid = pd.date_range(start=start_utc, end=end_utc, freq=spec.frequency, tz="UTC")

    result: dict[str, pa.Table] = {}
    for label, table in tables.items():
        if table.num_rows == 0:
            result[label] = table
            continue

        aligned_chunks: list[pa.Table] = []
        for grid_ts in grid:
            grid_dt: datetime = grid_ts.to_pydatetime()
            # Apply both as-of dimensions
            snapshot = as_of_filter(table, as_of_column=spec.as_of_column, cutoff=grid_dt)
            if spec.as_of_column != spec.ts_column and spec.ts_column in table.schema.names:
                snapshot = as_of_filter(snapshot, as_of_column=spec.ts_column, cutoff=grid_dt)
            if snapshot.num_rows > 0:
                grid_col = pa.array(
                    [grid_dt] * snapshot.num_rows,
                    type=pa.timestamp("us", tz="UTC"),
                )
                snapshot = snapshot.append_column(
                    pa.field("grid_ts", pa.timestamp("us", tz="UTC")), grid_col
                )
                aligned_chunks.append(snapshot)

        if aligned_chunks:
            result[label] = pa.concat_tables(aligned_chunks)
        else:
            # Return empty table with grid_ts column added
            extended_schema = table.schema.append(
                pa.field("grid_ts", pa.timestamp("us", tz="UTC"))
            )
            result[label] = pa.Table.from_pylist([], schema=extended_schema)

    return result


__all__ = ["GridAlignmentSpec", "align_to_grid", "as_of_filter"]
