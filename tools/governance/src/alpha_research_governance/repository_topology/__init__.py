"""Canonical B01 governed source-topology API and repository command."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

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
    """Run the B01 repository-topology checker from the command line."""
    provided = list(sys.argv[1:] if arguments is None else arguments)
    if len(provided) > 1:
        print(
            "usage: python -m alpha_research_governance.repository_topology [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(provided[0]) if provided else Path.cwd()
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
