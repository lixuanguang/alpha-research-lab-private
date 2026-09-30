"""Publish durable directories and check durable SQLite layouts."""

from __future__ import annotations

# standard library imports
import errno
import os
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from pathlib import Path
from typing import cast


def sync_directory(path: Path) -> None:
    """Make a directory's entries durable on a local POSIX filesystem.

    Args:
        path: Directory whose created, renamed or removed names must survive a crash.
    """
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_directory(
    staging: Path, destination: Path, *, sync: Callable[[Path], None] = sync_directory
) -> bool:
    """Durably rename a completely written staging directory to its destination.

    The staging directory is synchronized, renamed into place, and the parent is
    synchronized, so a crash leaves either no destination or the whole one.

    Args:
        staging: Sibling directory holding every file, each already synchronized.
        destination: Absent path the staged directory becomes.
        sync: Directory synchronization; a caller may substitute its own.

    Returns:
        True once published. False when a publisher that went first already made
        a nonempty destination: the staging directory stays, and the caller
        verifies the existing destination instead.
    """
    sync(staging)
    try:
        os.rename(staging, destination)
    except OSError as error:
        if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
            raise
        return False
    sync(destination.parent)
    return True


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
