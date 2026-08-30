"""Strict parsing and cross-register validation for the A06 inventory."""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from alpha_research.change_risk import load_policy as load_change_risk_policy
from alpha_research.evidence import validate_manifest
from alpha_research.inventory.models import (
    InventoryGovernanceError,
    InventoryItem,
    KindPopulation,
    ResourceInventory,
)

RESOURCE_KINDS = (
    "dataset",
    "model",
    "strategy",
    "service",
    "limit",
    "venue",
    "release",
    "control",
)
RESOURCE_STATUSES = ("planned", "provisional", "validated", "deprecated", "retired")

_EXPECTED_FINDING_IDS = ("A06-F01", "A06-F02", "A06-F03")
_APPLICABLE_GATES = {
    "QG01",
    "QG02",
    "QG03",
    "QG04",
    "QG05",
    "QG06",
    "QG09",
    "QG10",
    "QG11",
    "QG12",
    "QG13",
    "QG14",
}
_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ROOT_KEYS = {
    "accountable_owner_role",
    "as_of_date",
    "catalog_version",
    "findings",
    "inventory_scope",
    "items",
    "kind_states",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "maximum_items",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "roadmap_package",
    "schema_version",
    "supported_kinds",
    "query_workload_budget_ms",
    "query_workload_iterations",
}
_ITEM_KEYS = {
    "criticality",
    "dependencies",
    "deployment_evidence",
    "deployment_status",
    "inventory_id",
    "kind",
    "lineage_refs",
    "name",
    "owner_role",
    "record_version",
    "retention_class",
    "review_due_on",
    "source_paths",
    "status",
    "status_evidence",
}
_INVENTORY_ID = re.compile(
    r"^inv\.(?P<kind>dataset|model|strategy|service|limit|venue|release|control)"
    r"\.[a-z0-9]+(?:[._-][a-z0-9]+)*$"
)
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")
_RETENTION = re.compile(r"^[a-z][a-z0-9_]*$")
_STATUSES = set(RESOURCE_STATUSES)
_DEPLOYMENT_STATUSES = {
    "activated",
    "deployed",
    "not_deployable",
    "not_deployed",
    "retired",
}
_POPULATION_STATUSES = {"empty", "populated"}


def _table(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InventoryGovernanceError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _table_list(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise InventoryGovernanceError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _string(table: dict[str, object], key: str, *, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InventoryGovernanceError([f"{context}.{key} must be a non-empty string"])
    return value


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise InventoryGovernanceError([f"{context} must be an array of non-empty strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise InventoryGovernanceError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise InventoryGovernanceError([f"{context} must contain unique values"])
    return values


def _positive_integer(table: dict[str, object], key: str, *, context: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise InventoryGovernanceError([f"{context}.{key} must be a positive integer"])
    return value


def _iso_date(value: str, *, context: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise InventoryGovernanceError([f"{context} must use YYYY-MM-DD"]) from error


def _load_toml(path: Path) -> dict[str, object]:
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise InventoryGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    return _table(parsed, context=str(path))


def _ownership_roles(path: Path) -> frozenset[str]:
    root = _load_toml(path)
    roles: set[str] = set()
    for index, domain in enumerate(_table_list(root.get("domains"), context="domains"), 1):
        context = f"domains[{index}]"
        roles.add(_string(domain, "accountable_role", context=context))
        for key in ("required_review_roles", "independent_review_roles", "escalation_roles"):
            roles.update(_strings(domain.get(key), context=f"{context}.{key}", allow_empty=True))
    if not roles:
        raise InventoryGovernanceError([f"{path}: ownership register contains no roles"])
    invalid_roles = sorted(role for role in roles if _ROLE.fullmatch(role) is None)
    if invalid_roles:
        raise InventoryGovernanceError(
            [f"{path}: ownership roles must be lower_snake_case: {invalid_roles!r}"]
        )
    return frozenset(roles)


def _validate_repository_path(
    value: str, *, repository_root: Path, context: str, findings: list[str]
) -> None:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        findings.append(f"{context}: repository path escapes the root: {value}")
        return
    candidate = repository_root / relative
    try:
        candidate.resolve(strict=True).relative_to(repository_root)
    except (FileNotFoundError, ValueError):
        findings.append(f"{context}: repository path is missing or outside the root: {value}")
        return
    if not candidate.is_file():
        findings.append(f"{context}: repository path must identify a file: {value}")


def _validate_reference(
    value: str,
    *,
    inventory_ids: frozenset[str],
    repository_root: Path,
    context: str,
    findings: list[str],
) -> None:
    if value.startswith("inv."):
        if value not in inventory_ids:
            findings.append(f"{context}: unresolved inventory reference {value!r}")
        return
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            findings.append(f"{context}: external evidence must use HTTPS without credentials")
        return
    _validate_repository_path(
        value, repository_root=repository_root, context=context, findings=findings
    )


def _parse_kind_states(
    value: object, *, ownership_roles: frozenset[str], findings: list[str]
) -> tuple[KindPopulation, ...]:
    states: list[KindPopulation] = []
    for index, entry in enumerate(_table_list(value, context="kind_states"), 1):
        context = f"kind_states[{index}]"
        if set(entry) != {"kind", "owner_role", "population_status", "rationale"}:
            raise InventoryGovernanceError([f"{context} has missing or unknown fields"])
        kind = _string(entry, "kind", context=context)
        population_status = _string(entry, "population_status", context=context)
        owner_role = _string(entry, "owner_role", context=context)
        rationale = _string(entry, "rationale", context=context)
        if population_status not in _POPULATION_STATUSES:
            findings.append(f"{context}.population_status is unsupported")
        if owner_role not in ownership_roles:
            findings.append(f"{context}: stale ownership role {owner_role!r}")
        states.append(KindPopulation(kind, population_status, owner_role, rationale))
    if tuple(state.kind for state in states) != RESOURCE_KINDS:
        findings.append(
            f"kind_states must declare each supported kind in order: {RESOURCE_KINDS!r}"
        )
    return tuple(states)


def _parse_item(entry: dict[str, object], *, index: int) -> InventoryItem:
    context = f"items[{index}]"
    if set(entry) != _ITEM_KEYS:
        raise InventoryGovernanceError([f"{context} has missing or unknown fields"])
    kind = _string(entry, "kind", context=context)
    inventory_id = _string(entry, "inventory_id", context=context)
    match = _INVENTORY_ID.fullmatch(inventory_id)
    if match is None or match.group("kind") != kind:
        raise InventoryGovernanceError(
            [f"{context}.inventory_id must be inv.<matching-kind>.<namespace>.<name>"]
        )
    return InventoryItem(
        inventory_id=inventory_id,
        kind=kind,
        record_version=_positive_integer(entry, "record_version", context=context),
        name=_string(entry, "name", context=context),
        owner_role=_string(entry, "owner_role", context=context),
        criticality=_string(entry, "criticality", context=context),
        status=_string(entry, "status", context=context),
        dependencies=_strings(
            entry.get("dependencies"), context=f"{context}.dependencies", allow_empty=True
        ),
        retention_class=_string(entry, "retention_class", context=context),
        source_paths=_strings(entry.get("source_paths"), context=f"{context}.source_paths"),
        lineage_refs=_strings(entry.get("lineage_refs"), context=f"{context}.lineage_refs"),
        deployment_status=_string(entry, "deployment_status", context=context),
        deployment_evidence=_strings(
            entry.get("deployment_evidence"),
            context=f"{context}.deployment_evidence",
            allow_empty=True,
        ),
        status_evidence=_strings(
            entry.get("status_evidence"), context=f"{context}.status_evidence"
        ),
        review_due_on=_iso_date(
            _string(entry, "review_due_on", context=context),
            context=f"{context}.review_due_on",
        ),
    )


def _find_dependency_cycles(items: tuple[InventoryItem, ...]) -> tuple[str, ...]:
    dependencies = {item.inventory_id: item.dependencies for item in items}
    states: dict[str, int] = {}
    cycles: list[str] = []

    def visit(inventory_id: str, trail: tuple[str, ...]) -> None:
        state = states.get(inventory_id, 0)
        if state == 1:
            start = trail.index(inventory_id)
            cycles.append(" -> ".join(trail[start:] + (inventory_id,)))
            return
        if state == 2:
            return
        states[inventory_id] = 1
        for dependency in dependencies[inventory_id]:
            if dependency in dependencies:
                visit(dependency, (*trail, inventory_id))
        states[inventory_id] = 2

    for inventory_id in dependencies:
        visit(inventory_id, ())
    return tuple(dict.fromkeys(cycles))


def load_inventory(
    path: Path, *, repository_root: Path, ownership_register_path: Path | None = None
) -> ResourceInventory:
    """Load and validate a complete A06 inventory against repository state."""
    resolved_root = repository_root.resolve()
    ownership_path = (
        resolved_root / "docs" / "governance" / "domain-ownership.toml"
        if ownership_register_path is None
        else ownership_register_path
    )
    ownership_roles = _ownership_roles(ownership_path)
    root = _load_toml(path)
    if set(root) != _ROOT_KEYS:
        raise InventoryGovernanceError([f"{path}: fields must be exactly {sorted(_ROOT_KEYS)!r}"])
    expected_scalars: dict[str, object] = {
        "schema_version": 1,
        "roadmap_package": "A06",
        "operating_track": "solo_bootstrap",
        "accountable_owner_role": "platform",
    }
    for key, expected in expected_scalars.items():
        if root.get(key) != expected:
            raise InventoryGovernanceError([f"{path}: {key} must be {expected!r}"])
    supported_kinds = _strings(root.get("supported_kinds"), context="supported_kinds")
    if supported_kinds != RESOURCE_KINDS:
        raise InventoryGovernanceError([f"{path}: supported_kinds must be {RESOURCE_KINDS!r}"])

    findings: list[str] = []
    as_of_date = _iso_date(_string(root, "as_of_date", context=str(path)), context="as_of_date")
    kinds = _parse_kind_states(
        root.get("kind_states"), ownership_roles=ownership_roles, findings=findings
    )
    item_values = _table_list(root.get("items"), context="items")
    items = tuple(_parse_item(entry, index=index) for index, entry in enumerate(item_values, 1))
    maximum_items = _positive_integer(root, "maximum_items", context=str(path))
    if len(items) > maximum_items:
        findings.append(f"catalog contains {len(items)} items; maximum_items is {maximum_items}")
    inventory_ids = tuple(item.inventory_id for item in items)
    if len(inventory_ids) != len(set(inventory_ids)):
        findings.append("inventory IDs must be unique")
    if inventory_ids != tuple(sorted(inventory_ids)):
        findings.append("inventory items must be ordered by stable inventory_id")
    inventory_id_set = frozenset(inventory_ids)

    for item in items:
        context = item.inventory_id
        if item.kind not in RESOURCE_KINDS:
            findings.append(f"{context}: unsupported kind {item.kind!r}")
        if item.owner_role not in ownership_roles:
            findings.append(f"{context}: stale ownership role {item.owner_role!r}")
        if item.criticality not in {"T0", "T1", "T2", "T3"}:
            findings.append(f"{context}: criticality must be T0-T3")
        if item.status not in _STATUSES:
            findings.append(f"{context}: unsupported status {item.status!r}")
        if item.status == "validated" and root.get("operating_track") == "solo_bootstrap":
            findings.append(f"{context}: solo_bootstrap resources cannot claim validated status")
        if _RETENTION.fullmatch(item.retention_class) is None:
            findings.append(f"{context}: retention_class must be lower_snake_case")
        if item.deployment_status not in _DEPLOYMENT_STATUSES:
            findings.append(f"{context}: unsupported deployment_status")
        if item.deployment_status in {"deployed", "activated"} and not item.deployment_evidence:
            findings.append(f"{context}: deployed resources require deployment evidence")
        if item.review_due_on < as_of_date:
            findings.append(f"{context}: ownership review is stale as of {as_of_date.isoformat()}")
        if item.inventory_id in item.dependencies:
            findings.append(f"{context}: a resource cannot depend on itself")
        for dependency in item.dependencies:
            if dependency not in inventory_id_set:
                findings.append(f"{context}: unresolved dependency {dependency!r}")
        missing_dependency_lineage = set(item.dependencies) - set(item.lineage_refs)
        if missing_dependency_lineage:
            findings.append(
                f"{context}: missing lineage for dependencies "
                f"{sorted(missing_dependency_lineage)!r}"
            )
        missing_source_lineage = set(item.source_paths) - set(item.lineage_refs)
        if missing_source_lineage:
            findings.append(
                f"{context}: missing lineage for source paths {sorted(missing_source_lineage)!r}"
            )
        for source_path in item.source_paths:
            _validate_repository_path(
                source_path,
                repository_root=resolved_root,
                context=f"{context}.source_paths",
                findings=findings,
            )
        for field_name, references in (
            ("lineage_refs", item.lineage_refs),
            ("deployment_evidence", item.deployment_evidence),
            ("status_evidence", item.status_evidence),
        ):
            for reference in references:
                _validate_reference(
                    reference,
                    inventory_ids=inventory_id_set,
                    repository_root=resolved_root,
                    context=f"{context}.{field_name}",
                    findings=findings,
                )

    counts = {kind: sum(item.kind == kind for item in items) for kind in RESOURCE_KINDS}
    for state in kinds:
        expected_population = "populated" if counts.get(state.kind, 0) else "empty"
        if state.population_status != expected_population:
            findings.append(
                f"kind {state.kind!r} must be {expected_population!r} for its item count"
            )
    for cycle in _find_dependency_cycles(items):
        findings.append(f"inventory dependency cycle: {cycle}")

    finding_values = _table_list(root.get("findings"), context="findings")
    finding_ids: list[str] = []
    expected_finding_keys = {
        "closure_condition",
        "finding_id",
        "owner_role",
        "unavailable_evidence",
    }
    for index, finding in enumerate(finding_values, 1):
        context = f"findings[{index}]"
        if set(finding) != expected_finding_keys:
            raise InventoryGovernanceError([f"{context} has missing or unknown fields"])
        for key in expected_finding_keys:
            _string(finding, key, context=context)
        owner_role = _string(finding, "owner_role", context=context)
        if owner_role not in ownership_roles:
            findings.append(f"{context}: stale ownership role {owner_role!r}")
        finding_ids.append(_string(finding, "finding_id", context=context))
    open_finding_ids = _strings(
        root.get("open_finding_ids"), context="open_finding_ids", allow_empty=True
    )
    if open_finding_ids != tuple(finding_ids):
        findings.append("open_finding_ids must exactly match findings")
    package_status = _string(root, "package_status", context=str(path))
    if package_status == "partial":
        if tuple(finding_ids) != _EXPECTED_FINDING_IDS:
            findings.append(f"partial status requires findings {list(_EXPECTED_FINDING_IDS)!r}")
    elif package_status == "validated":
        if root.get("operating_track") == "solo_bootstrap":
            findings.append("solo_bootstrap packages cannot claim validated status")
        if finding_ids:
            findings.append("validated status cannot retain open findings")
    else:
        findings.append("package_status must be partial or validated")

    if findings:
        raise InventoryGovernanceError(findings)
    local_evidence_manifest_path = _string(root, "local_evidence_manifest_path", context=str(path))
    evidence_path_findings: list[str] = []
    _validate_repository_path(
        local_evidence_manifest_path,
        repository_root=resolved_root,
        context="local_evidence_manifest_path",
        findings=evidence_path_findings,
    )
    if evidence_path_findings:
        raise InventoryGovernanceError(evidence_path_findings)
    local_evidence_commit_sha = _string(root, "local_evidence_commit_sha", context=str(path))
    if _COMMIT_SHA.fullmatch(local_evidence_commit_sha) is None:
        raise InventoryGovernanceError(
            [f"{path}: local_evidence_commit_sha must be a full lowercase SHA"]
        )
    return ResourceInventory(
        catalog_version=_positive_integer(root, "catalog_version", context=str(path)),
        as_of_date=as_of_date,
        inventory_scope=_string(root, "inventory_scope", context=str(path)),
        package_status=package_status,
        maximum_items=maximum_items,
        query_workload_iterations=_positive_integer(
            root, "query_workload_iterations", context=str(path)
        ),
        query_workload_budget_ms=_positive_integer(
            root, "query_workload_budget_ms", context=str(path)
        ),
        local_evidence_manifest_path=local_evidence_manifest_path,
        local_evidence_commit_sha=local_evidence_commit_sha,
        kinds=kinds,
        items=items,
        finding_ids=tuple(finding_ids),
    )


def _validate_local_evidence(repository_root: Path, inventory: ResourceInventory) -> None:
    """Validate the synthetic R2 bundle without treating it as forge acceptance."""
    try:
        change_policy = load_change_risk_policy(
            repository_root / "docs" / "governance" / "change-risk-policy.toml"
        )
        manifest = validate_manifest(
            repository_root / inventory.local_evidence_manifest_path,
            expected_commit_sha=inventory.local_evidence_commit_sha,
            change_policy=change_policy,
        )
    except (OSError, ValueError) as error:
        raise InventoryGovernanceError([f"A06 local evidence bundle: {error}"]) from error

    findings: list[str] = []
    if manifest.roadmap_id != "A06" or manifest.risk_class != "R2":
        findings.append("A06 local evidence bundle must be classified as roadmap A06 risk R2")
    if manifest.bundle_status != "partial":
        findings.append("A06 local evidence bundle must remain partial")
    if manifest.open_finding_ids != inventory.finding_ids:
        findings.append("A06 local evidence bundle must retain the catalog findings exactly")
    if {gate.gate_id for gate in manifest.gates} != _APPLICABLE_GATES:
        findings.append("A06 local evidence bundle must record every applicable gate exactly once")
    if any(gate.status != "passed" for gate in manifest.gates):
        findings.append("A06 local evidence bundle must pass each repository-local gate")
    if manifest.approvals:
        findings.append("A06 synthetic local evidence bundle cannot contain approvals")
    if findings:
        raise InventoryGovernanceError(findings)


def validate_repository(repository_root: Path) -> ResourceInventory:
    """Validate the authoritative inventory, A03 owners, and local R2 evidence."""
    root = repository_root.resolve()
    inventory = load_inventory(
        root / "docs" / "governance" / "resource-inventory.toml",
        repository_root=root,
    )
    _validate_local_evidence(root, inventory)
    return inventory
