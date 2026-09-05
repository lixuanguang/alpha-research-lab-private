"""Compatibility facade for the canonical ownership-governance tool."""

# project library imports
from alpha_research_governance.ownership_governance import (
    OwnershipGovernanceError,
    main,
    validate_repository,
)

__all__ = ["OwnershipGovernanceError", "main", "validate_repository"]


if __name__ == "__main__":
    raise SystemExit(main())
