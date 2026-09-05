"""Canonical governed source-topology API and repository command."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.repository_topology.models import (
    RepositoryTopology,
    RepositoryTopologyError,
    SourceUnit,
)
from alpha_research_governance.repository_topology.registry import (
    load_topology,
    validate_repository,
)

__all__ = [
    "RepositoryTopology",
    "RepositoryTopologyError",
    "SourceUnit",
    "load_topology",
    "main",
    "validate_repository",
]


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate governed source topology from the command line.

    The repository root defaults to ``Path.cwd()``. Validation reads the topology
    register, ownership and source files needed by the loader, writes no files, and
    launches no subprocesses. ``OSError`` and ``RepositoryTopologyError`` raised during
    validation are caught and translated to status ``1``.

    Args:
        arguments: Optional command-line tokens. ``None`` consumes ``sys.argv[1:]``;
            otherwise provide at most one repository-root path.

    Returns:
        ``0`` after printing the count of owned targets and the B01 package status,
        ``1`` after printing a caught topology or filesystem failure to standard error,
        or ``2`` after printing usage for more than one argument.

    Raises:
        OSError: If resolving the default working directory or writing usage or success
            output fails outside the guarded validation block.
        UnicodeDecodeError: If a repository input read as UTF-8 has invalid encoding.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print(
            "usage: python -m alpha_research_governance.repository_topology [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        topology = validate_repository(repository_root)
    except (OSError, RepositoryTopologyError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"Repository topology passed for {len(topology.units)} owned targets; "
        f"B01 status is {topology.package_status}."
    )
    return 0
