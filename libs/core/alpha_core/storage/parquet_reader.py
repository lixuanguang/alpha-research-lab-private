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
        venue: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pa.Table:
        """Read canonical trades with partition-prunable filters."""
        return self._read_dataset(
            dataset_name=storage_conventions.TRADE_DATASET_NAME,
            schema=storage_conventions.TRADE_PARQUET_SCHEMA,
            filter_expr=_build_time_filter(venue=venue, start=start, end=end),
        )

    def read_books(
        self,
        venue: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pa.Table:
        """Read canonical order book snapshots with partition-prunable filters."""
        return self._read_dataset(
            dataset_name=storage_conventions.BOOK_DATASET_NAME,
            schema=storage_conventions.BOOK_PARQUET_SCHEMA,
            filter_expr=_build_time_filter(venue=venue, start=start, end=end),
        )

    def read_ohlcv(
        self,
        venue: str | None = None,
        resolution: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pa.Table:
        """Read canonical OHLCV bars with partition-prunable filters."""
        return self._read_dataset(
            dataset_name=storage_conventions.OHLCV_DATASET_NAME,
            schema=storage_conventions.OHLCV_PARQUET_SCHEMA,
            filter_expr=_build_time_filter(
                venue=venue,
                start=start,
                end=end,
                resolution=resolution,
            ),
        )

    def read_book_deltas(
        self,
        venue: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pa.Table:
        """Read canonical book delta events with partition-prunable filters."""
        return self._read_dataset(
            dataset_name=storage_conventions.BOOK_DELTA_DATASET_NAME,
            schema=storage_conventions.BOOK_DELTA_PARQUET_SCHEMA,
            filter_expr=_build_time_filter(venue=venue, start=start, end=end),
        )

    def _read_dataset(
        self,
        *,
        dataset_name: str,
        schema: pa.Schema,
        filter_expr: ds.Expression | None,
    ) -> pa.Table:
        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            storage_conventions.StorageTier.SILVER,
            dataset_name,
        )
        if not dataset_root.exists():
            return pa.Table.from_pylist([], schema=schema)

        dataset = ds.dataset(str(dataset_root), format="parquet", partitioning="hive")
        table = dataset.to_table(filter=filter_expr)
        if table.num_rows == 0:
            return pa.Table.from_pylist([], schema=schema)

        selected = table.select(schema.names)
        return selected.cast(schema, safe=False)


def _build_time_filter(
    venue: str | None,
    start: datetime | None,
    end: datetime | None,
    resolution: str | None = None,
) -> ds.Expression | None:
    expressions: list[ds.Expression] = []

    if venue is not None:
        expressions.append(ds.field("venue") == venue.strip().lower())
    if resolution is not None:
        expressions.append(ds.field("resolution") == resolution.strip())

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
