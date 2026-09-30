"""Check durable SQLite layouts against the statements that create them."""

from __future__ import annotations

# standard library imports
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from typing import cast


def require_sqlite_layout(
    connection: sqlite3.Connection, statements: Iterable[str], message: str
) -> None:
    """Refuse a database whose schema is not exactly the one ``statements`` create.

    Every table, index and trigger is compared by type, name, owning table and
    SQL text, so a layout that keeps the same names with other columns,
    constraints or trigger bodies is refused. The expected schema is built by
    running the statements in an empty in-memory database.

    Args:
        connection: Open connection to the database to check.
        statements: The ``CREATE`` statements that produce the current layout.
        message: Error text naming the unsupported schema.

    Raises:
        ValueError: The schema differs from the current layout.
    """
    with closing(sqlite3.connect(":memory:")) as expected:
        for statement in statements:
            expected.execute(statement)
        if _schema(connection) != _schema(expected):
            raise ValueError(message)


def _schema(connection: sqlite3.Connection) -> list[tuple[object, ...]]:
    """Read every schema object other than SQLite's own, in a stable order."""
    return sorted(
        cast(
            list[tuple[object, ...]],
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
            ).fetchall(),
        ),
        key=repr,
    )
