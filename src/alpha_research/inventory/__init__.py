"""Compatibility facade for the canonical A06 inventory-governance tool."""

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
