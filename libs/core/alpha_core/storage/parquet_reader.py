"""Parquet readers with partition-aware filtering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.dataset as ds  # type: ignore[import-untyped]

import alpha_core.storage.conventions as storage_conventions
import alpha_core.utils.time as time_utils


class ParquetEventReader:
    """Read canonical events from partitioned Parquet datasets."""

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root

    def read_trades(
        self,
        venue: str | None,
        start: datetime | None,
        end: datetime | None,
    ) -> pa.Table:
        """Read canonical trades with partition-prunable filters."""
        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            storage_conventions.StorageTier.SILVER,
            storage_conventions.TRADE_DATASET_NAME,
        )

        if not dataset_root.exists():
            return pa.Table.from_pylist([], schema=storage_conventions.TRADE_PARQUET_SCHEMA)

        dataset = ds.dataset(str(dataset_root), format="parquet", partitioning="hive")
        filter_expr = _build_trade_filter(venue=venue, start=start, end=end)
        table = dataset.to_table(filter=filter_expr)

        if table.num_rows == 0:
            return pa.Table.from_pylist([], schema=storage_conventions.TRADE_PARQUET_SCHEMA)

        selected = table.select(storage_conventions.TRADE_PARQUET_SCHEMA.names)
        return selected.cast(storage_conventions.TRADE_PARQUET_SCHEMA, safe=False)


def _build_trade_filter(
    venue: str | None,
    start: datetime | None,
    end: datetime | None,
) -> ds.Expression | None:
    expressions: list[ds.Expression] = []

    if venue is not None:
        expressions.append(ds.field("venue") == venue.strip().lower())

    if start is not None:
        start_utc = time_utils.ensure_utc(start)
        expressions.append(ds.field("ts_event") >= pa.scalar(start_utc))
        expressions.append(ds.field("date") >= start_utc.date().isoformat())

    if end is not None:
        end_utc = time_utils.ensure_utc(end)
        expressions.append(ds.field("ts_event") <= pa.scalar(end_utc))
        expressions.append(ds.field("date") <= end_utc.date().isoformat())

    if not expressions:
        return None

    combined = expressions[0]
    for expression in expressions[1:]:
        combined = combined & expression
    return combined


__all__ = ["ParquetEventReader"]
