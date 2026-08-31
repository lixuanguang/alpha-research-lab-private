"""Compatibility facade for the canonical architecture-governance tool."""

from alpha_research_governance.architecture_governance import (
    ArchitectureGovernanceError,
    main,
    validate_adr,
    validate_decision_directory,
    validate_local_links,
    validate_repository,
)

__all__ = [
    "ArchitectureGovernanceError",
    "main",
    "validate_adr",
    "validate_decision_directory",
    "validate_local_links",
    "validate_repository",
]


if __name__ == "__main__":
    raise SystemExit(main())
