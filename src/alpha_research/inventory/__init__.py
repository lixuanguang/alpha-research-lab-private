"""Compatibility facade for the canonical inventory-governance tool."""

# project library imports
from alpha_research_governance.inventory import (
    RESOURCE_KINDS,
    RESOURCE_STATUSES,
    InventoryGovernanceError,
    InventoryItem,
    KindPopulation,
    ResourceInventory,
    load_inventory,
    main,
    validate_repository,
)

__all__ = [
    "RESOURCE_KINDS",
    "RESOURCE_STATUSES",
    "InventoryGovernanceError",
    "InventoryItem",
    "KindPopulation",
    "ResourceInventory",
    "load_inventory",
    "main",
    "validate_repository",
]
