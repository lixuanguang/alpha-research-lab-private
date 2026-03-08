"""Parquet readers with partition-aware filtering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds

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

    def read_partition_refs(
        self,
        partition_refs: list[str],
        *,
        schema: pa.Schema,
    ) -> pa.Table:
        """Read an exact set of partition refs relative to the storage root.

        Raises ``FileNotFoundError`` when any referenced partition is missing so
        handoff/replay-style consumers fail fast on lineage drift.
        """
        if not partition_refs:
            return pa.Table.from_pylist([], schema=schema)

        dataset_names: set[str] = set()
        filter_expr: ds.Expression | None = None
        for partition_ref in partition_refs:
            resolved_path = self._resolve_partition_ref(partition_ref)
            if not resolved_path.exists():
                raise FileNotFoundError(
                    f"Referenced partition does not exist: {partition_ref}"
                )
            dataset_names.add(_dataset_name_from_partition_ref(partition_ref))
            if len(dataset_names) > 1:
                raise ValueError("All partition refs must belong to the same dataset.")
            partition_filter = _partition_filter_from_ref(partition_ref)
            filter_expr = (
                partition_filter if filter_expr is None else filter_expr | partition_filter
            )

        dataset_name = next(iter(dataset_names))
        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            storage_conventions.StorageTier.SILVER,
            dataset_name,
        )
        if not dataset_root.exists():
            raise FileNotFoundError(f"Referenced dataset does not exist: {dataset_root}")

        dataset = ds.dataset(str(dataset_root), format="parquet", partitioning="hive")
        table = dataset.to_table(filter=filter_expr)
        if table.num_rows == 0:
            return pa.Table.from_pylist([], schema=schema)
        return table.select(schema.names).cast(schema, safe=False)

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

    def _resolve_partition_ref(self, partition_ref: str) -> Path:
        path = Path(partition_ref)
        if path.is_absolute():
            return path
        return self._storage_root / path


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


def _dataset_name_from_partition_ref(partition_ref: str) -> str:
    segments = [segment for segment in partition_ref.replace("\\", "/").split("/") if segment]
    try:
        silver_index = segments.index("silver")
    except ValueError as exc:
        raise ValueError(f"Partition ref must include 'silver/': {partition_ref}") from exc
    if silver_index + 1 >= len(segments):
        raise ValueError(f"Partition ref is missing the dataset segment: {partition_ref}")
    return segments[silver_index + 1]


def _partition_filter_from_ref(partition_ref: str) -> ds.Expression:
    segments = [segment for segment in partition_ref.replace("\\", "/").split("/") if segment]
    try:
        silver_index = segments.index("silver")
    except ValueError as exc:
        raise ValueError(f"Partition ref must include 'silver/': {partition_ref}") from exc

    partition_segments = segments[silver_index + 2 :]
    filters: list[ds.Expression] = []
    for segment in partition_segments:
        key, separator, value = segment.partition("=")
        if not separator:
            continue
        filters.append(ds.field(key) == value)
    if not filters:
        raise ValueError(
            f"Partition ref does not contain partition key/value segments: {partition_ref}"
        )
    combined = filters[0]
    for filter_part in filters[1:]:
        combined = combined & filter_part
    return combined


__all__ = ["ParquetEventReader"]
