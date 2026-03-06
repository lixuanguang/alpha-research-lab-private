"""DuckDB SQL validation helpers."""

from __future__ import annotations

import re

import pyarrow as pa  # type: ignore[import-untyped]

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
_CTE_NAME_RE = re.compile(
    rf"\b(?:with|,)\s*({_IDENTIFIER_COMPONENT_RE})\s+as\s*\(",
    re.IGNORECASE,
)
_INLINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_QUOTE_STRING_RE = re.compile(r"'(?:''|[^'])*'")


def quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def is_read_only_statement(statement: str) -> bool:
    lowered = statement.lstrip().lower()
    return any(lowered.startswith(prefix) for prefix in _READ_ONLY_PREFIXES)


def strip_comments(statement: str) -> str:
    output: list[str] = []
    index = 0
    in_single_quote = False
    in_double_quote = False

    while index < len(statement):
        char = statement[index]
        next_char = statement[index + 1] if index + 1 < len(statement) else ""

        if in_single_quote:
            output.append(char)
            if char == "'" and next_char == "'":
                output.append(next_char)
                index += 2
                continue
            if char == "'":
                in_single_quote = False
            index += 1
            continue

        if in_double_quote:
            output.append(char)
            if char == '"' and next_char == '"':
                output.append(next_char)
                index += 2
                continue
            if char == '"':
                in_double_quote = False
            index += 1
            continue

        if char == "'":
            in_single_quote = True
            output.append(char)
            index += 1
            continue

        if char == '"':
            in_double_quote = True
            output.append(char)
            index += 1
            continue

        if char == "-" and next_char == "-":
            _append_comment_gap(output)
            index = _skip_line_comment(statement, index + 2)
            continue

        if char == "/" and next_char == "*":
            _append_comment_gap(output)
            index = _skip_block_comment(statement, index + 2)
            continue

        output.append(char)
        index += 1

    return "".join(output)


def raise_if_forbidden_sql(statement: str) -> None:
    scrubbed = _SINGLE_QUOTE_STRING_RE.sub("''", statement)
    lowered = scrubbed.lower()
    for keyword in _FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise ValueError(f"Disallowed SQL keyword in read-only query: {keyword}")


def validate_allowed_query_sources(statement: str, registered_views: set[str]) -> None:
    normalized_statement = strip_comments(statement)
    scrubbed_statement = _SINGLE_QUOTE_STRING_RE.sub("''", normalized_statement)
    relations, table_functions = _extract_relation_references(scrubbed_statement)
    if table_functions:
        names = ", ".join(sorted(table_functions))
        raise ValueError(f"Table functions are not allowed in queries: {names}")

    cte_names = _extract_cte_names(scrubbed_statement)
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


def arrow_type_to_duckdb_type(arrow_type: pa.DataType) -> str:
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


def last_identifier_component(relation: str) -> str:
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


def _extract_cte_names(statement: str) -> set[str]:
    return {_normalize_relation_name(match.group(1)) for match in _CTE_NAME_RE.finditer(statement)}


def _extract_relation_references(statement: str) -> tuple[set[str], set[str]]:
    relations: set[str] = set()
    table_functions: set[str] = set()

    for keyword, index in _scan_top_level_keywords(statement, ("from", "join")):
        if keyword == "from":
            _consume_sources_after_from(
                statement,
                index + len("from"),
                relations=relations,
                table_functions=table_functions,
            )
            continue
        relation_name, is_table_function, _ = _consume_relation_source(
            statement,
            index + len("join"),
        )
        _record_relation_reference(
            relation_name,
            is_table_function,
            relations=relations,
            table_functions=table_functions,
        )

    nested_relations, nested_table_functions = _extract_nested_query_references(statement)
    relations.update(nested_relations)
    table_functions.update(nested_table_functions)
    return relations, table_functions


def _extract_nested_query_references(statement: str) -> tuple[set[str], set[str]]:
    relations: set[str] = set()
    table_functions: set[str] = set()
    index = 0
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

        if char != "(":
            index += 1
            continue

        end_index = _skip_parenthesized_block(statement, index)
        inner_statement = statement[index + 1 : end_index - 1].strip()
        if inner_statement and is_read_only_statement(inner_statement):
            nested_relations, nested_table_functions = _extract_relation_references(
                inner_statement
            )
            relations.update(nested_relations)
            table_functions.update(nested_table_functions)
        index = end_index

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
            for keyword in keywords:
                if not _matches_keyword_at(statement, index, keyword):
                    continue
                matches.append((keyword, index))
                index += len(keyword)
                break
            else:
                index += 1
                continue
            continue

        index += 1
    return matches


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
            return ".".join(components), dot_index
        next_start = _skip_whitespace(statement, dot_index + 1)
        next_component, next_index = _consume_identifier_component(statement, next_start)
        if next_component is None:
            return ".".join(components), dot_index
        components.append(next_component)
        index = next_index


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


def _append_comment_gap(output: list[str]) -> None:
    if output and not output[-1].isspace():
        output.append(" ")


def _skip_line_comment(statement: str, start_index: int) -> int:
    index = start_index
    while index < len(statement) and statement[index] != "\n":
        index += 1
    return index


def _skip_block_comment(statement: str, start_index: int) -> int:
    index = start_index
    while index + 1 < len(statement):
        if statement[index] == "*" and statement[index + 1] == "/":
            return index + 2
        index += 1
    return len(statement)


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
    return not (end < len(statement) and (statement[end].isalnum() or statement[end] == "_"))


def _normalize_relation_name(relation: str) -> str:
    return _unquote_identifier(last_identifier_component(relation)).lower()


def _unquote_identifier(identifier: str) -> str:
    stripped = identifier.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        return stripped[1:-1].replace('""', '"')
    return stripped


__all__ = [
    "arrow_type_to_duckdb_type",
    "is_read_only_statement",
    "last_identifier_component",
    "quote_identifier",
    "raise_if_forbidden_sql",
    "strip_comments",
    "validate_allowed_query_sources",
]
