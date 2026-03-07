"""DuckDB query helper over Parquet-backed storage datasets."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pyarrow as pa

import alpha_core.storage._duckdb_validation as duckdb_validation
import alpha_core.storage.conventions as storage_conventions

_SUPPORTED_EVENT_DATASETS: dict[str, str] = {
    "trade": storage_conventions.TRADE_DATASET_NAME,
    "trades": storage_conventions.TRADE_DATASET_NAME,
    "book": storage_conventions.BOOK_DATASET_NAME,
    "books": storage_conventions.BOOK_DATASET_NAME,
    "ohlcv": storage_conventions.OHLCV_DATASET_NAME,
    "book_delta": storage_conventions.BOOK_DELTA_DATASET_NAME,
    "book_deltas": storage_conventions.BOOK_DELTA_DATASET_NAME,
}
_SCHEMA_BY_DATASET: dict[str, pa.Schema] = {
    storage_conventions.TRADE_DATASET_NAME: storage_conventions.TRADE_PARQUET_SCHEMA,
    storage_conventions.BOOK_DATASET_NAME: storage_conventions.BOOK_PARQUET_SCHEMA,
    storage_conventions.OHLCV_DATASET_NAME: storage_conventions.OHLCV_PARQUET_SCHEMA,
    storage_conventions.BOOK_DELTA_DATASET_NAME: storage_conventions.BOOK_DELTA_PARQUET_SCHEMA,
}

try:
    duckdb_module: Any | None = importlib.import_module("duckdb")
except ModuleNotFoundError:
    duckdb_module = None


class DuckDBAnalytics:
    """DuckDB wrapper for ad-hoc queries over silver-tier Parquet data."""

    def __init__(self, storage_root: Path) -> None:
        if duckdb_module is None:
            raise ModuleNotFoundError(
                "duckdb is required for DuckDBAnalytics. "
                "Install project dependencies with `.[dev]`."
            )
        self._storage_root = storage_root
        self._con: Any = duckdb_module.connect()
        self._registered_views: set[str] = set()

    def query(self, sql: str, parameters: tuple[object, ...] | None = None) -> pa.Table:
        """Execute a single read-only SQL statement and return an Arrow table."""
        statement = sql.strip()
        if not statement:
            raise ValueError("SQL query must be non-empty")
        if ";" in statement.rstrip(";"):
            raise ValueError("Only a single SQL statement is allowed")
        normalized_statement = duckdb_validation.strip_comments(statement)
        if not duckdb_validation.is_read_only_statement(normalized_statement):
            raise ValueError("Only read-only queries are allowed (`SELECT`, `WITH`, `EXPLAIN`).")
        duckdb_validation.raise_if_forbidden_sql(normalized_statement)
        duckdb_validation.validate_allowed_query_sources(
            normalized_statement,
            self._registered_views,
        )

        if parameters is None:
            return self._con.execute(statement).fetch_arrow_table()
        return self._con.execute(statement, parameters).fetch_arrow_table()

    def register_silver(self, event_type: str) -> None:
        """Register a silver dataset as a DuckDB view."""
        normalized = event_type.strip().lower()
        if normalized not in _SUPPORTED_EVENT_DATASETS:
            raise ValueError(f"Unsupported event_type for silver registration: {event_type}")

        dataset_name = _SUPPORTED_EVENT_DATASETS[normalized]
        view_name = f"silver_{dataset_name}"

        dataset_root = storage_conventions.dataset_root(
            self._storage_root,
            storage_conventions.StorageTier.SILVER,
            dataset_name,
        )
        parquet_glob = dataset_root / "**" / "*.parquet"

        if not dataset_root.exists() or not any(dataset_root.rglob("*.parquet")):
            self._register_empty_view(view_name, dataset_name)
            return

        self._con.from_parquet(
            str(parquet_glob),
            hive_partitioning=True,
            union_by_name=True,
        ).create_view(view_name)
        self._registered_views.add(view_name.lower())

    def _register_empty_view(self, view_name: str, dataset_name: str) -> None:
        schema = _SCHEMA_BY_DATASET[dataset_name]
        projection = ", ".join(
            f"NULL::{duckdb_validation.arrow_type_to_duckdb_type(field.type)} "
            f"AS {duckdb_validation.quote_identifier(field.name)}"
            for field in schema
        )
        self._con.execute(
            f"CREATE OR REPLACE VIEW {duckdb_validation.quote_identifier(view_name)} AS "
            f"SELECT {projection} WHERE FALSE"
        )
        self._registered_views.add(view_name.lower())


__all__ = ["DuckDBAnalytics"]
