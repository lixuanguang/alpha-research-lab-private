"""Canonical resource-inventory API and repository check command."""

from __future__ import annotations

# standard library imports
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.inventory.models import (
    InventoryGovernanceError,
    InventoryItem,
    KindPopulation,
    ResourceInventory,
)
from alpha_research_governance.inventory.registry import (
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
    "usage: python -m alpha_research_governance.inventory [repository-root] [--json] "
    "[--kind KIND] [--status STATUS] [--owner-role ROLE]"
)


def _parse_arguments(arguments: Sequence[str]) -> tuple[Path, bool, dict[str, str]]:
    """Parse inventory CLI tokens and derive the requested output mode.

    Args:
        arguments: Ordered command-line tokens containing at most one repository root,
            the ``--json`` flag, and at most one occurrence of each supported filter.

    Returns:
        A tuple containing the selected repository root (defaulting to the current
        working directory), whether JSON output is required, and the supplied exact
        ``--kind``, ``--status`` and ``--owner-role`` filter values for ``main`` to
        validate or apply.

    Raises:
        InventoryGovernanceError: If an option is duplicated or unknown, a value is
            missing, or more than one positional repository root is supplied. Filter
            values are retained for ``main`` to validate or apply.
    """
    repository_root: Path | None = None
    should_emit_json = False
    filters: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--json":
            if should_emit_json:
                raise InventoryGovernanceError([_USAGE])
            should_emit_json = True
            index += 1
            continue
        if argument in {"--kind", "--owner-role", "--status"}:
            if argument in filters or index + 1 >= len(arguments):
                raise InventoryGovernanceError([_USAGE])
            filters[argument] = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--") or repository_root is not None:
            raise InventoryGovernanceError([_USAGE])
        repository_root = Path(argument)
        index += 1
    return (
        Path.cwd() if repository_root is None else repository_root,
        should_emit_json or bool(filters),
        filters,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate resource governance or emit a deterministic filtered inventory.

    The repository root defaults to ``Path.cwd()``. The command reads the authoritative
    inventory, ownership register and local evidence; it writes no files and launches no
    subprocesses. With no ``--json`` flag and no filter it prints a human summary. The
    explicit flag or any filter selects JSON output; filters use exact case-sensitive
    matching. ``--kind`` and ``--status`` are checked against their exported registries;
    ``--owner-role`` is applied as an exact string without separate role validation.
    The payload includes selected items, kind states, finding IDs and recorded query
    limits. Parser errors are caught as status ``2``; expected ``InventoryGovernanceError``
    and ``OSError`` failures during validation are caught as status ``1``.

    Args:
        arguments: Optional command-line tokens. ``None`` consumes ``sys.argv[1:]``;
            otherwise provide an optional repository root, ``--json``, and at most one
            occurrence of each ``--kind KIND``, ``--status STATUS`` and
            ``--owner-role ROLE`` filter.

    Returns:
        ``0`` after printing the human validation summary or compact, sorted JSON;
        ``1`` after printing an unsupported filter, governance failure or filesystem
        failure to standard error; or ``2`` after printing the exact usage for malformed
        argument syntax.

    Raises:
        OSError: If resolving the default working directory or writing output fails
            outside the guarded parsing and validation blocks.
        UnicodeDecodeError: If a repository input read as UTF-8 has invalid encoding.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        repository_root, should_emit_json, filters = _parse_arguments(cli_arguments)
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
        selected_inventory_items = inventory.query(
            kind=kind,
            status=status,
            owner_role=filters.get("--owner-role"),
        )
    except (InventoryGovernanceError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    if should_emit_json:
        inventory_payload = {
            "as_of_date": inventory.as_of_date.isoformat(),
            "catalog_version": inventory.catalog_version,
            "count": len(selected_inventory_items),
            "inventory_scope": inventory.inventory_scope,
            "items": [item.as_json() for item in selected_inventory_items],
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
        print(json.dumps(inventory_payload, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"Inventory governance passed for {len(inventory.items)} resources across "
            f"{len(inventory.kinds)} kinds; package status is {inventory.package_status}."
        )
    return 0
