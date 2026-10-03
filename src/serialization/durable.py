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


class DurableDirectory:
    """Make directory entries and published directories survive a crash on local POSIX."""

    @staticmethod
    def sync(path: Path) -> None:
        """Make a directory's entries durable on a local POSIX filesystem.

        Args:
            path: Directory whose created, renamed or removed names must survive a crash.
        """
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def publish(
        cls,
        staging: Path,
        destination: Path,
        *,
        sync: Callable[[Path], None] | None = None,
    ) -> bool:
        """Durably rename a completely written staging directory to its destination.

        The staging directory is synchronized, renamed into place, and the parent is
        synchronized, so a crash leaves either no destination or the whole one.

        Args:
            staging: Sibling directory holding every file, each already synchronized.
            destination: Absent path the staged directory becomes.
            sync: Directory synchronization; defaults to :meth:`sync`, and a caller
                may substitute its own.

        Returns:
            True once published. False when a publisher that went first already made
            a nonempty destination: the staging directory stays, and the caller
            verifies the existing destination instead.
        """
        synchronize = cls.sync if sync is None else sync
        synchronize(staging)
        try:
            os.rename(staging, destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
            return False
        synchronize(destination.parent)
        return True


class SqliteLayout:
    """Refuse SQLite databases whose schema differs from the current layout."""

    @classmethod
    def require(
        cls, connection: sqlite3.Connection, statements: Iterable[str], message: str
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
            if cls._schema(connection) != cls._schema(expected):
                raise ValueError(message)

    @staticmethod
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
