"""Compatibility facade for the canonical topology-governance tool."""

from alpha_research_governance.repository_topology import (
    RepositoryTopology,
    RepositoryTopologyError,
    SourceUnit,
    load_topology,
    main,
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
