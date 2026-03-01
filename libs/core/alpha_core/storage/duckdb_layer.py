"""DuckDB query helper over Parquet-backed storage datasets."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]

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
_READ_ONLY_PREFIXES = ("select", "with", "explain")
_FORBIDDEN_SQL_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "merge",
    "create",
    "drop",
    "alter",
    "truncate",
    "attach",
    "detach",
    "copy",
    "export",
    "import",
    "install",
    "load",
    "set",
    "reset",
    "pragma",
    "call",
)
_IDENTIFIER_COMPONENT_RE = r'(?:[a-zA-Z_][a-zA-Z0-9_]*|"(?:[^"]|"")+")'
_IDENTIFIER_PATH_RE = rf"{_IDENTIFIER_COMPONENT_RE}(?:\s*\.\s*{_IDENTIFIER_COMPONENT_RE})*"
_CTE_NAME_RE = re.compile(
    rf"\b(?:with|,)\s*({_IDENTIFIER_COMPONENT_RE})\s+as\s*\(",
    re.IGNORECASE,
)
_INLINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_QUOTE_STRING_RE = re.compile(r"'(?:''|[^'])*'")

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
        normalized_statement = _strip_comments(statement)
        if not _is_read_only_statement(normalized_statement):
            raise ValueError("Only read-only queries are allowed (`SELECT`, `WITH`, `EXPLAIN`).")
        _raise_if_forbidden_sql(normalized_statement)
        _validate_allowed_query_sources(normalized_statement, self._registered_views)

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

        escaped_glob = str(parquet_glob).replace("'", "''")
        self._con.execute(
            f"CREATE OR REPLACE VIEW {_quote_identifier(view_name)} AS "
            f"SELECT * FROM read_parquet('{escaped_glob}', hive_partitioning=1, union_by_name=1)"
        )
        self._registered_views.add(view_name.lower())

    def _register_empty_view(self, view_name: str, dataset_name: str) -> None:
        schema = _SCHEMA_BY_DATASET[dataset_name]
        projection = ", ".join(
            f"NULL::{_arrow_type_to_duckdb_type(field.type)} AS {_quote_identifier(field.name)}"
            for field in schema
        )
        self._con.execute(
            f"CREATE OR REPLACE VIEW {_quote_identifier(view_name)} AS "
            f"SELECT {projection} WHERE FALSE"
        )
        self._registered_views.add(view_name.lower())


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _is_read_only_statement(statement: str) -> bool:
    lowered = statement.lstrip().lower()
    return any(lowered.startswith(prefix) for prefix in _READ_ONLY_PREFIXES)


def _normalize_relation_name(relation: str) -> str:
    return _unquote_identifier(_last_identifier_component(relation)).lower()


def _strip_comments(statement: str) -> str:
    no_block_comments = _BLOCK_COMMENT_RE.sub(" ", statement)
    return _INLINE_COMMENT_RE.sub(" ", no_block_comments)


def _raise_if_forbidden_sql(statement: str) -> None:
    scrubbed = _SINGLE_QUOTE_STRING_RE.sub("''", statement)
    lowered = scrubbed.lower()
    for keyword in _FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise ValueError(f"Disallowed SQL keyword in read-only query: {keyword}")


def _extract_cte_names(statement: str) -> set[str]:
    return {_normalize_relation_name(match.group(1)) for match in _CTE_NAME_RE.finditer(statement)}


def _extract_relation_references(statement: str) -> tuple[set[str], set[str]]:
    scrubbed_statement = _SINGLE_QUOTE_STRING_RE.sub("''", statement)
    relations: set[str] = set()
    table_functions: set[str] = set()

    for keyword, index in _scan_top_level_keywords(scrubbed_statement, ("from", "join")):
        if keyword == "from":
            _consume_sources_after_from(
                scrubbed_statement,
                index + len("from"),
                relations=relations,
                table_functions=table_functions,
            )
            continue
        relation_name, is_table_function, _ = _consume_relation_source(
            scrubbed_statement,
            index + len("join"),
        )
        _record_relation_reference(
            relation_name,
            is_table_function,
            relations=relations,
            table_functions=table_functions,
        )

    return relations, table_functions


def _scan_top_level_keywords(statement: str, keywords: tuple[str, ...]) -> list[tuple[str, int]]:
    matches: list[tuple[str, int]] = []
    index = 0
    depth = 0
    in_quotes = False

    while index < len(statement):
        char = statement[index]
        if in_quotes:
            if char == '"':
                if index + 1 < len(statement) and statement[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = False
            index += 1
            continue

        if char == '"':
            in_quotes = True
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue

        if depth == 0:
            matched = False
            for keyword in keywords:
                if not _matches_keyword_at(statement, index, keyword):
                    continue
                matches.append((keyword, index))
                index += len(keyword)
                matched = True
                break
            if matched:
                continue

        index += 1
    return matches


def _validate_allowed_query_sources(statement: str, registered_views: set[str]) -> None:
    relations, table_functions = _extract_relation_references(statement)
    if table_functions:
        names = ", ".join(sorted(table_functions))
        raise ValueError(f"Table functions are not allowed in queries: {names}")

    cte_names = _extract_cte_names(statement)
    allowed_relations = set(registered_views)
    allowed_relations.update(cte_names)
    unknown_relations = sorted(
        relation for relation in relations if relation not in allowed_relations
    )
    if unknown_relations:
        names = ", ".join(unknown_relations)
        raise ValueError(
            "Queries may only reference registered silver views and CTEs. "
            f"Unknown relation(s): {names}"
        )


def _arrow_type_to_duckdb_type(arrow_type: pa.DataType) -> str:
    if pa.types.is_string(arrow_type):
        return "VARCHAR"
    if pa.types.is_int32(arrow_type):
        return "INTEGER"
    if pa.types.is_decimal(arrow_type):
        return f"DECIMAL({arrow_type.precision},{arrow_type.scale})"
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMPTZ"
    if pa.types.is_boolean(arrow_type):
        return "BOOLEAN"
    if pa.types.is_float32(arrow_type) or pa.types.is_float64(arrow_type):
        return "DOUBLE"

    raise TypeError(f"Unsupported Arrow type for DuckDB empty-view schema: {arrow_type}")


def _consume_sources_after_from(
    statement: str,
    start_index: int,
    *,
    relations: set[str],
    table_functions: set[str],
) -> int:
    relation_name, is_table_function, index = _consume_relation_source(statement, start_index)
    _record_relation_reference(
        relation_name,
        is_table_function,
        relations=relations,
        table_functions=table_functions,
    )

    while True:
        index = _skip_whitespace(statement, index)
        if index >= len(statement) or statement[index] != ",":
            return index
        relation_name, is_table_function, index = _consume_relation_source(statement, index + 1)
        _record_relation_reference(
            relation_name,
            is_table_function,
            relations=relations,
            table_functions=table_functions,
        )


def _record_relation_reference(
    relation_name: str | None,
    is_table_function: bool,
    *,
    relations: set[str],
    table_functions: set[str],
) -> None:
    if relation_name is None:
        return
    normalized = _normalize_relation_name(relation_name)
    if is_table_function:
        table_functions.add(normalized)
        return
    relations.add(normalized)


def _consume_relation_source(
    statement: str,
    start_index: int,
) -> tuple[str | None, bool, int]:
    index = _skip_whitespace(statement, start_index)
    if index >= len(statement):
        return None, False, index

    if statement[index] == "(":
        return None, False, _skip_parenthesized_block(statement, index)

    relation_name, index = _consume_identifier_path(statement, index)
    if relation_name is None:
        return None, False, index

    index = _skip_whitespace(statement, index)
    if index < len(statement) and statement[index] == "(":
        return relation_name, True, _skip_parenthesized_block(statement, index)
    return relation_name, False, index


def _consume_identifier_path(statement: str, start_index: int) -> tuple[str | None, int]:
    component, index = _consume_identifier_component(statement, start_index)
    if component is None:
        return None, start_index

    components = [component]
    while True:
        dot_index = _skip_whitespace(statement, index)
        if dot_index >= len(statement) or statement[dot_index] != ".":
            index = dot_index
            break
        next_start = _skip_whitespace(statement, dot_index + 1)
        next_component, next_index = _consume_identifier_component(statement, next_start)
        if next_component is None:
            index = dot_index
            break
        components.append(next_component)
        index = next_index

    return ".".join(components), index


def _consume_identifier_component(statement: str, start_index: int) -> tuple[str | None, int]:
    index = _skip_whitespace(statement, start_index)
    if index >= len(statement):
        return None, index

    if statement[index] == '"':
        end_index = index + 1
        while end_index < len(statement):
            if statement[end_index] == '"':
                if end_index + 1 < len(statement) and statement[end_index + 1] == '"':
                    end_index += 2
                    continue
                return statement[index : end_index + 1], end_index + 1
            end_index += 1
        return None, len(statement)

    if not (statement[index].isalpha() or statement[index] == "_"):
        return None, index
    end_index = index + 1
    while end_index < len(statement):
        char = statement[end_index]
        if char.isalnum() or char == "_":
            end_index += 1
            continue
        break
    return statement[index:end_index], end_index


def _skip_whitespace(statement: str, start_index: int) -> int:
    index = start_index
    while index < len(statement) and statement[index].isspace():
        index += 1
    return index


def _skip_parenthesized_block(statement: str, open_paren_index: int) -> int:
    index = open_paren_index
    depth = 0
    in_quotes = False
    while index < len(statement):
        char = statement[index]
        if in_quotes:
            if char == '"':
                if index + 1 < len(statement) and statement[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = False
            index += 1
            continue

        if char == '"':
            in_quotes = True
            index += 1
            continue

        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(statement)


def _matches_keyword_at(statement: str, index: int, keyword: str) -> bool:
    end = index + len(keyword)
    if end > len(statement):
        return False
    if statement[index:end].lower() != keyword:
        return False
    if index > 0 and (statement[index - 1].isalnum() or statement[index - 1] == "_"):
        return False
    if end < len(statement) and (statement[end].isalnum() or statement[end] == "_"):
        return False
    return True


def _last_identifier_component(relation: str) -> str:
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    index = 0

    while index < len(relation):
        char = relation[index]
        if char == '"':
            current.append(char)
            if in_quotes and index + 1 < len(relation) and relation[index + 1] == '"':
                current.append('"')
                index += 2
                continue
            in_quotes = not in_quotes
            index += 1
            continue

        if char == "." and not in_quotes:
            segment = "".join(current).strip()
            if segment:
                parts.append(segment)
            current.clear()
            index += 1
            continue

        current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    if not parts:
        return relation.strip()
    return parts[-1]


def _unquote_identifier(identifier: str) -> str:
    stripped = identifier.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        return stripped[1:-1].replace('""', '"')
    return stripped


__all__ = ["DuckDBAnalytics"]
