"""Narrow DuckDB declarations used by the bounded research adapter."""

# standard library imports
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager

class DuckDBPyConnection(AbstractContextManager["DuckDBPyConnection"]):
    """Support the parameterized in-memory SQL surface consumed by research."""

    def __enter__(self) -> DuckDBPyConnection:
        """Return this connection for a context-managed query."""
        ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Close the context-managed connection."""
        ...

    def execute(self, query: str, parameters: Sequence[object] | None = ...) -> DuckDBPyConnection:
        """Execute one parameterized SQL statement.

        Args:
            query: Fixed SQL statement.
            parameters: Positional values bound to placeholders.

        Returns:
            This connection for fetching or chaining.
        """
        ...

    def executemany(self, query: str, parameters: Sequence[Sequence[object]]) -> DuckDBPyConnection:
        """Execute one fixed SQL statement for each parameter row.

        Args:
            query: Fixed insert statement.
            parameters: Ordered parameter rows.

        Returns:
            This connection for subsequent queries.
        """
        ...

    def fetchall(self) -> list[tuple[object, ...]]:
        """Return all rows from the preceding query.

        Returns:
            Tuples containing backend scalar values.
        """
        ...

def connect(
    database: str = ..., *, config: Mapping[str, object] | None = ...
) -> DuckDBPyConnection:
    """Open one bounded DuckDB connection.

    Args:
        database: Database name or path.
        config: Fixed backend configuration.

    Returns:
        A context-managed DuckDB connection.
    """
    ...
