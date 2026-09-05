"""Compatibility facade for inventory-registry operations."""

# project library imports
from alpha_research_governance.inventory.registry import (
    RESOURCE_KINDS,
    RESOURCE_STATUSES,
    load_inventory,
    validate_repository,
)

__all__ = [
    "RESOURCE_KINDS",
    "RESOURCE_STATUSES",
    "load_inventory",
    "validate_repository",
]
