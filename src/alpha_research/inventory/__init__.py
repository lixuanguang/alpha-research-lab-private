"""Public A06 resource-inventory API and repository check command."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from alpha_research.inventory.models import (
    InventoryGovernanceError,
    InventoryItem,
    KindPopulation,
    ResourceInventory,
)
from alpha_research.inventory.registry import (
    RESOURCE_KINDS,
    RESOURCE_STATUSES,
    load_inventory,
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

_USAGE = (
    "usage: python -m alpha_research.inventory [repository-root] [--json] "
    "[--kind KIND] [--status STATUS] [--owner-role ROLE]"
)


def _parse_arguments(arguments: Sequence[str]) -> tuple[Path, bool, dict[str, str]]:
    root: Path | None = None
    emit_json = False
    filters: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--json":
            if emit_json:
                raise InventoryGovernanceError([_USAGE])
            emit_json = True
            index += 1
            continue
        if argument in {"--kind", "--owner-role", "--status"}:
            if argument in filters or index + 1 >= len(arguments):
                raise InventoryGovernanceError([_USAGE])
            filters[argument] = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--") or root is not None:
            raise InventoryGovernanceError([_USAGE])
        root = Path(argument)
        index += 1
    return (Path.cwd() if root is None else root), emit_json or bool(filters), filters


def main(arguments: Sequence[str] | None = None) -> int:
    """Run A06 validation or emit a deterministic filtered JSON inventory."""
    provided = list(sys.argv[1:] if arguments is None else arguments)
    try:
        repository_root, emit_json, filters = _parse_arguments(provided)
    except InventoryGovernanceError as error:
        print(error, file=sys.stderr)
        return 2
    try:
        inventory = validate_repository(repository_root)
        kind = filters.get("--kind")
        if kind is not None and kind not in RESOURCE_KINDS:
            raise InventoryGovernanceError([f"unsupported inventory kind {kind!r}"])
        status = filters.get("--status")
        if status is not None and status not in RESOURCE_STATUSES:
            raise InventoryGovernanceError([f"unsupported inventory status {status!r}"])
        selected = inventory.query(
            kind=kind,
            status=status,
            owner_role=filters.get("--owner-role"),
        )
    except (InventoryGovernanceError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    if emit_json:
        result = {
            "as_of_date": inventory.as_of_date.isoformat(),
            "catalog_version": inventory.catalog_version,
            "count": len(selected),
            "inventory_scope": inventory.inventory_scope,
            "items": [item.as_json() for item in selected],
            "kind_states": [
                state.as_json() for state in inventory.kinds if kind is None or state.kind == kind
            ],
            "open_finding_ids": list(inventory.finding_ids),
            "package_status": inventory.package_status,
            "query_limits": {
                "maximum_items": inventory.maximum_items,
                "workload_budget_ms": inventory.query_workload_budget_ms,
                "workload_iterations": inventory.query_workload_iterations,
            },
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"Inventory governance passed for {len(inventory.items)} resources across "
            f"{len(inventory.kinds)} kinds; package status is {inventory.package_status}."
        )
    return 0
