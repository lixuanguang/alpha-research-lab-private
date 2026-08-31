"""Compatibility facade for A06 inventory-registry operations."""

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
