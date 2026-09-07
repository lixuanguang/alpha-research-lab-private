"""Parse and cross-validate the resource inventory strictly."""

from __future__ import annotations

# standard library imports
import re
import tomllib
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

# third party library imports
from pydantic import ValidationError

# project library imports
from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.evidence import (
    EvidenceGovernanceError,
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)
from alpha_research_governance.inventory.models import (
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

_RESOURCE_INVENTORY_OPEN_FINDING_IDS = ("A06-F01", "A06-F02", "A06-F03")
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
_LOCAL_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id="A06",
    accountable_owner_role="platform",
    risk_class=RiskClass.R2,
    classification_facts=ChangeRiskInput(
        capital_at_risk=False,
        blast_radius="shared_domain",
        data_model_materiality="shared_or_candidate",
        security_privilege="none",
        reversibility="compatibility_window",
        computationally_material=True,
        economically_or_risk_relevant=False,
        model_or_trading_relevant=False,
        declared_class=RiskClass.R2,
    ),
    gate_requirements=tuple(
        PackageGateRequirement(gate_id=gate_id, status="passed")
        for gate_id in sorted(_APPLICABLE_GATES)
    ),
    expected_package_status="partial",
    expected_finding_ids=_RESOURCE_INVENTORY_OPEN_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=False,
)
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


def _require_table(value: object, *, context: str) -> dict[str, object]:
    """Require a parsed value to be a TOML table.

    Args:
        value: Parsed TOML value to inspect.
        context: Location label to include in a validation error.

    Returns:
        The original mapping, cast for TOML-parser input as having string keys and object values;
        only its dictionary shape is checked, and it is not copied.

    Raises:
        InventoryGovernanceError: If ``value`` is not a dictionary.
    """
    if not isinstance(value, dict):
        raise InventoryGovernanceError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _require_table_list(value: object, *, context: str) -> list[dict[str, object]]:
    """Require a parsed value to be an array of TOML tables.

    Args:
        value: Parsed TOML value to inspect; an empty list is accepted.
        context: Location label to include in a validation error.

    Returns:
        The original list with each element cast for TOML-parser input as a mapping; only the
        list and element dictionary shapes are checked, and no list or element mappings are
        copied.

    Raises:
        InventoryGovernanceError: If ``value`` is not a list or any element is not a dictionary.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise InventoryGovernanceError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _require_string(table: dict[str, object], key: str, *, context: str) -> str:
    """Require a non-blank string field.

    Args:
        table: Mapping containing the field to inspect.
        key: Field name to retrieve with ``dict.get``.
        context: Location label to include in a validation error.

    Returns:
        The original string, preserving any surrounding whitespace.

    Raises:
        InventoryGovernanceError: If the field is missing, is not a string, or contains only
            whitespace.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InventoryGovernanceError([f"{context}.{key} must be a non-empty string"])
    return value


def _require_strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Require an ordered sequence of unique non-empty strings.

    Args:
        value: Parsed value expected to be a list of strings.
        context: Location label to include in a validation error.
        allow_empty: Permit an empty list when ``True``; default to rejecting it.

    String values are not stripped; whitespace-only strings are accepted, while an exact empty
    string is rejected.

    Returns:
        A new tuple containing the input strings in their original order and text.

    Raises:
        InventoryGovernanceError: If the value is not a list of strings, contains an empty string,
            is empty when ``allow_empty`` is false, or contains duplicate values.
    """
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise InventoryGovernanceError([f"{context} must be an array of non-empty strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise InventoryGovernanceError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise InventoryGovernanceError([f"{context} must contain unique values"])
    return values


def _require_positive_integer(table: dict[str, object], key: str, *, context: str) -> int:
    """Require a positive integer field.

    Args:
        table: Mapping containing the field to inspect.
        key: Field name to retrieve with ``dict.get``.
        context: Location label to include in a validation error.

    Returns:
        The integer value stored in ``table``.

    Raises:
        InventoryGovernanceError: If the field is missing, is not an integer, is a boolean, or is
            less than one.
    """
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise InventoryGovernanceError([f"{context}.{key} must be a positive integer"])
    return value


def _parse_iso_date(value: str, *, context: str) -> date:
    """Parse a date in the canonical ISO extended calendar form.

    Args:
        value: Date text that must round-trip as ``YYYY-MM-DD``.
        context: Location label to include in a validation error.

    Returns:
        The parsed ``date`` value.

    Raises:
        InventoryGovernanceError: If parsing fails or the parsed date's ISO text does not exactly
            match ``value``; parsing ``ValueError`` instances are preserved as causes.
    """
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError as error:
        raise InventoryGovernanceError([f"{context} must use YYYY-MM-DD"]) from error
    if parsed_date.isoformat() != value:
        raise InventoryGovernanceError([f"{context} must use YYYY-MM-DD"])
    return parsed_date


def _load_toml(path: Path) -> dict[str, object]:
    """Load a UTF-8 TOML file and require a table at its root.

    Args:
        path: TOML file to read.

    Returns:
        The parser's top-level mapping, without copying it or normalizing its values.

    Raises:
        InventoryGovernanceError: If TOML decoding fails or the parsed root is not a dictionary;
            decoding errors are preserved as causes.
        OSError: If the file cannot be read.
        UnicodeDecodeError: If the file is not valid UTF-8.
    """
    try:
        parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise InventoryGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    return _require_table(parsed_document, context=str(path))


def _ownership_roles(path: Path) -> frozenset[str]:
    """Collect and validate roles declared by the ownership register's domains.

    Args:
        path: Ownership-register TOML file to read.

    Returns:
        A frozenset containing each domain's accountable, required-review, independent-review,
        and escalation roles; repeated roles across fields or domains are collapsed.

    Raises:
        InventoryGovernanceError: If the TOML or domain fields have the wrong shape, a role list
            contains duplicate text, no role is declared, or a role is outside the lowercase
            identifier pattern.
        OSError: If the ownership register cannot be read.
        UnicodeDecodeError: If the ownership register is not valid UTF-8.
    """
    ownership_document = _load_toml(path)
    roles: set[str] = set()
    for index, domain in enumerate(
        _require_table_list(ownership_document.get("domains"), context="domains"), 1
    ):
        context = f"domains[{index}]"
        roles.add(_require_string(domain, "accountable_role", context=context))
        for key in ("required_review_roles", "independent_review_roles", "escalation_roles"):
            roles.update(
                _require_strings(domain.get(key), context=f"{context}.{key}", allow_empty=True)
            )
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
    """Record a finding when a repository path escapes, is missing, or is not a file.

    Reject absolute paths and paths containing a ``..`` component lexically, then resolve the
    candidate strictly against the caller-resolved absolute ``repository_root``. Append one
    finding for each handled failure and leave valid paths unchanged. Symlinks resolving to
    in-root files are permitted, and resolution and file checks are not atomic.

    Args:
        value: Path text interpreted with the platform's ``Path`` rules.
        repository_root: Caller-resolved absolute root against which the candidate is joined and
            its resolved path is compared.
        context: Location label to prefix any appended finding.
        findings: Mutable finding list to extend for a handled path failure.

    Raises:
        OSError: If an underlying path operation raises an uncaught filesystem error.
        RuntimeError: If strict resolution encounters a symlink loop on Python 3.12.
    """
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
    """Record a finding for an unresolved or invalid inventory reference.

    Treat values beginning with ``inv.`` as exact inventory-ID lookups, values with a URL scheme
    as external references, and values without a scheme as repository paths. A ``urlsplit``
    ``ValueError`` appends a malformed-URL finding. A parsed external reference is accepted only
    when its scheme is ``https``, its hostname is nonempty, and its username and password are
    absent. These checks do not make network or existence requests and do not validate ports.
    Delegate handled path failures to ``_validate_repository_path``.

    Args:
        value: Reference text; values beginning with ``inv.`` are treated as inventory IDs.
        inventory_ids: Known inventory IDs used to resolve ``inv.`` references exactly.
        repository_root: Caller-resolved absolute root used when a reference is treated as a
            repository path.
        context: Location label to prefix any appended finding.
        findings: Mutable finding list to extend for a handled reference failure.

    Raises:
        OSError: If delegated repository-path validation encounters an uncaught filesystem error.
        RuntimeError: If delegated strict path resolution encounters a symlink loop on Python
            3.12.
    """
    if value.startswith("inv."):
        if value not in inventory_ids:
            findings.append(f"{context}: unresolved inventory reference {value!r}")
        return
    try:
        parsed_reference = urlsplit(value)
    except ValueError:
        findings.append(f"{context}: external evidence URL is malformed")
        return
    if parsed_reference.scheme:
        has_credentials = (
            parsed_reference.username is not None or parsed_reference.password is not None
        )
        if parsed_reference.scheme != "https" or not parsed_reference.hostname or has_credentials:
            findings.append(f"{context}: external evidence must use HTTPS without credentials")
        return
    _validate_repository_path(
        value, repository_root=repository_root, context=context, findings=findings
    )


def _parse_kind_states(
    value: object, *, ownership_roles: frozenset[str], findings: list[str]
) -> tuple[KindPopulation, ...]:
    """Parse kind-population tables and append local consistency findings.

    Args:
        value: Parsed TOML value expected to be an array of tables with exactly ``kind``,
            ``owner_role``, ``population_status``, and ``rationale`` fields.
        ownership_roles: Roles declared by the ownership register; this set is read only.
        findings: Mutable diagnostics list to which unsupported population statuses, stale owner
            roles, and a kind sequence differing from ``RESOURCE_KINDS`` are appended in
            traversal order. Existing entries are preserved.

    Returns:
        A tuple of ``KindPopulation`` records in input order. Text is not normalized or sorted;
        an empty input produces an empty tuple and one kind-sequence finding.

    Raises:
        InventoryGovernanceError: If the value is not a table list, an entry does not have exactly
            the four required fields, or a required field is missing/blank. Unsupported statuses,
            stale owners, duplicate kinds, and wrong ordering are recorded in ``findings`` rather
            than raised; a later structural error can therefore leave earlier findings appended.
            Population versus actual item counts is checked by the inventory loader.
    """
    states: list[KindPopulation] = []
    for index, entry in enumerate(_require_table_list(value, context="kind_states"), 1):
        context = f"kind_states[{index}]"
        if set(entry) != {"kind", "owner_role", "population_status", "rationale"}:
            raise InventoryGovernanceError([f"{context} has missing or unknown fields"])
        kind = _require_string(entry, "kind", context=context)
        population_status = _require_string(entry, "population_status", context=context)
        owner_role = _require_string(entry, "owner_role", context=context)
        rationale = _require_string(entry, "rationale", context=context)
        if population_status not in _POPULATION_STATUSES:
            findings.append(f"{context}.population_status is unsupported")
        if owner_role not in ownership_roles:
            findings.append(f"{context}: stale ownership role {owner_role!r}")
        states.append(
            KindPopulation(
                kind=kind,
                population_status=population_status,
                owner_role=owner_role,
                rationale=rationale,
            )
        )
    if tuple(state.kind for state in states) != RESOURCE_KINDS:
        findings.append(
            f"kind_states must declare each supported kind in order: {RESOURCE_KINDS!r}"
        )
    return tuple(states)


def _parse_inventory_item(entry: dict[str, object], *, index: int) -> InventoryItem:
    """Parse one inventory table into an immutable resource record.

    Args:
        entry: Parsed inventory table whose keys must be exactly ``_ITEM_KEYS``.
        index: One-based source position used in validation diagnostics.

    Returns:
        A newly constructed ``InventoryItem``. Scalar text retains its supplied spelling; list
        fields become ordered tuples of unique, non-empty strings. Dependencies and deployment
        evidence may be empty lists, while source paths, lineage references, and status evidence
        must contain at least one item. The review date is parsed from canonical ``YYYY-MM-DD``
        text. The inventory ID must match the exact ``inv.<kind>.<suffix>`` expression accepted by
        ``_INVENTORY_ID``; its final suffix may be one token or multiple lowercase tokens joined
        by ``.``, ``_``, or ``-``.

    Raises:
        InventoryGovernanceError: If keys, field types, positive record version, inventory-ID
            pattern/kind match, list contents, or date spelling are invalid. Repository path and
            external-reference safety, ownership/status vocabularies, deployment evidence rules,
            review age, dependency resolution/cycles, and lineage completeness are checked by the
            complete inventory loader. The input mapping is not modified.
    """
    context = f"items[{index}]"
    if set(entry) != _ITEM_KEYS:
        raise InventoryGovernanceError([f"{context} has missing or unknown fields"])
    kind = _require_string(entry, "kind", context=context)
    inventory_id = _require_string(entry, "inventory_id", context=context)
    match = _INVENTORY_ID.fullmatch(inventory_id)
    if match is None or match.group("kind") != kind:
        raise InventoryGovernanceError(
            [f"{context}.inventory_id must be inv.<matching-kind>.<namespace>.<name>"]
        )
    return InventoryItem(
        inventory_id=inventory_id,
        kind=kind,
        record_version=_require_positive_integer(entry, "record_version", context=context),
        name=_require_string(entry, "name", context=context),
        owner_role=_require_string(entry, "owner_role", context=context),
        criticality=_require_string(entry, "criticality", context=context),
        status=_require_string(entry, "status", context=context),
        dependencies=_require_strings(
            entry.get("dependencies"), context=f"{context}.dependencies", allow_empty=True
        ),
        retention_class=_require_string(entry, "retention_class", context=context),
        source_paths=_require_strings(entry.get("source_paths"), context=f"{context}.source_paths"),
        lineage_refs=_require_strings(entry.get("lineage_refs"), context=f"{context}.lineage_refs"),
        deployment_status=_require_string(entry, "deployment_status", context=context),
        deployment_evidence=_require_strings(
            entry.get("deployment_evidence"),
            context=f"{context}.deployment_evidence",
            allow_empty=True,
        ),
        status_evidence=_require_strings(
            entry.get("status_evidence"), context=f"{context}.status_evidence"
        ),
        review_due_on=_parse_iso_date(
            _require_string(entry, "review_due_on", context=context),
            context=f"{context}.review_due_on",
        ),
    )


def _find_dependency_cycles(items: tuple[InventoryItem, ...]) -> tuple[str, ...]:
    """Find directed dependency back edges in an inventory graph.

    Args:
        items: Inventory records whose ``inventory_id`` values are graph nodes and whose
            ``dependencies`` tuples are directed outgoing edges. The records and dependency
            tuples are not modified.

    Returns:
        A tuple of rendered cycles in depth-first discovery order. Each back edge to an active
        node is rendered from that node's first active occurrence through the repeated node, such
        as ``A -> B -> A``. Unknown dependency IDs are ignored as leaf edges. Exact duplicate
        renderings are removed while retaining their first occurrence. The temporary graph uses
        the last record's dependency tuple for duplicate inventory IDs, and traversal follows
        input/dependency order. The traversal is iterative and does not consume Python call
        stack frames. Lifecycle/deployment states and external/path references do not participate
        in this graph; unresolved dependency IDs are merely ignored by this cycle-only helper and
        are reported separately by the complete loader. With no back edges, the result is the
        empty tuple. No sorting or domain-error translation is performed by this helper.
    """
    dependencies = {item.inventory_id: item.dependencies for item in items}
    states: dict[str, int] = {}
    cycles: list[str] = []

    for inventory_id in dependencies:
        if states.get(inventory_id) == 2:
            continue
        states[inventory_id] = 1
        active_path = [inventory_id]
        active_positions = {inventory_id: 0}
        stack = [(inventory_id, 0)]
        while stack:
            current, dependency_index = stack[-1]
            current_dependencies = dependencies[current]
            if dependency_index == len(current_dependencies):
                stack.pop()
                active_positions.pop(current)
                active_path.pop()
                states[current] = 2
                continue
            dependency = current_dependencies[dependency_index]
            stack[-1] = (current, dependency_index + 1)
            if dependency not in dependencies:
                continue
            state = states.get(dependency, 0)
            if state == 1:
                start = active_positions[dependency]
                cycles.append(" -> ".join((*active_path[start:], dependency)))
            elif state == 0:
                states[dependency] = 1
                active_positions[dependency] = len(active_path)
                active_path.append(dependency)
                stack.append((dependency, 0))
    return tuple(dict.fromkeys(cycles))


class InventoryLoader:
    """Load and validate inventory records for one repository context.

    The constructor stores path context only. Each operation builds fresh parsed
    records and findings, so repeated calls on one loader cannot inherit state
    from a previous invocation.
    """

    def __init__(
        self,
        repository_root: Path,
        *,
        ownership_register_path: Path | None = None,
    ) -> None:
        """Bind repository and optional ownership-register paths without I/O.

        Args:
            repository_root: Repository root for repository-relative checks.
            ownership_register_path: Optional ownership-register override; when
                omitted, the default register below the resolved root is used.
        """
        self._repository_root = repository_root
        self._ownership_register_path = ownership_register_path

    def load(self, path: Path) -> ResourceInventory:
        """Load one inventory document with model-error translation.

        Args:
            path: UTF-8 inventory TOML file to parse.

        Returns:
            The validated immutable inventory record.

        Raises:
            InventoryGovernanceError: If parsing, validation, or model construction fails.
            OSError: If the inventory or ownership register cannot be read.
            UnicodeDecodeError: If an input file is not valid UTF-8.
        """
        return self._load_with_context(path, self._repository_root.resolve())

    def _load_with_context(self, path: Path, resolved_repository_root: Path) -> ResourceInventory:
        """Load one inventory while preserving the public model-error boundary.

        Args:
            path: UTF-8 inventory TOML file to parse.
            resolved_repository_root: Root snapshot for this load operation.

        Returns:
            The validated immutable inventory record.

        Raises:
            InventoryGovernanceError: If parsing or model construction fails.
            OSError: If the inventory or ownership register cannot be read.
            UnicodeDecodeError: If an input file is not valid UTF-8.
        """
        try:
            return self._load(path, resolved_repository_root=resolved_repository_root)
        except ValidationError as error:
            raise InventoryGovernanceError(
                [f"{path}: inventory model validation failed"]
            ) from error

    def _load(
        self, path: Path, *, resolved_repository_root: Path | None = None
    ) -> ResourceInventory:
        """Load and validate one complete resource inventory against repository state.

        Args:
            path: UTF-8 inventory TOML file to parse.
            resolved_repository_root: Optional root snapshot captured by the caller; when omitted,
                this method resolves the loader's bound root for direct internal use.

        Returns:
            A validated immutable inventory record.

        Raises:
            InventoryGovernanceError: If schema, ownership, reference, lifecycle,
                dependency, or evidence-path checks fail.
            OSError: If repository or input files cannot be read.
        """
        repository_root = self._repository_root
        ownership_register_path = self._ownership_register_path
        resolved_repository_root = (
            repository_root.resolve()
            if resolved_repository_root is None
            else resolved_repository_root
        )
        ownership_path = (
            resolved_repository_root / "docs" / "governance" / "domain-ownership.toml"
            if ownership_register_path is None
            else ownership_register_path
        )
        ownership_roles = _ownership_roles(ownership_path)
        inventory_document = _load_toml(path)
        if set(inventory_document) != _ROOT_KEYS:
            raise InventoryGovernanceError(
                [f"{path}: fields must be exactly {sorted(_ROOT_KEYS)!r}"]
            )
        expected_scalars: dict[str, object] = {
            "schema_version": 1,
            "roadmap_package": "A06",
            "operating_track": "solo_bootstrap",
            "accountable_owner_role": "platform",
        }
        for key, expected in expected_scalars.items():
            if inventory_document.get(key) != expected:
                raise InventoryGovernanceError([f"{path}: {key} must be {expected!r}"])
        supported_kinds = _require_strings(
            inventory_document.get("supported_kinds"), context="supported_kinds"
        )
        if supported_kinds != RESOURCE_KINDS:
            raise InventoryGovernanceError([f"{path}: supported_kinds must be {RESOURCE_KINDS!r}"])

        findings: list[str] = []
        as_of_date = _parse_iso_date(
            _require_string(inventory_document, "as_of_date", context=str(path)),
            context="as_of_date",
        )
        kinds = _parse_kind_states(
            inventory_document.get("kind_states"),
            ownership_roles=ownership_roles,
            findings=findings,
        )
        item_values = _require_table_list(inventory_document.get("items"), context="items")
        items = tuple(
            _parse_inventory_item(entry, index=index) for index, entry in enumerate(item_values, 1)
        )
        maximum_items = _require_positive_integer(
            inventory_document, "maximum_items", context=str(path)
        )
        if len(items) > maximum_items:
            findings.append(
                f"catalog contains {len(items)} items; maximum_items is {maximum_items}"
            )
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
            if (
                item.status == "validated"
                and inventory_document.get("operating_track") == "solo_bootstrap"
            ):
                findings.append(
                    f"{context}: solo_bootstrap resources cannot claim validated status"
                )
            if _RETENTION.fullmatch(item.retention_class) is None:
                findings.append(f"{context}: retention_class must be lower_snake_case")
            if item.deployment_status not in _DEPLOYMENT_STATUSES:
                findings.append(f"{context}: unsupported deployment_status")
            if item.deployment_status in {"deployed", "activated"} and not item.deployment_evidence:
                findings.append(f"{context}: deployed resources require deployment evidence")
            if item.review_due_on < as_of_date:
                findings.append(
                    f"{context}: ownership review is stale as of {as_of_date.isoformat()}"
                )
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
                    f"{context}: missing lineage for source paths "
                    f"{sorted(missing_source_lineage)!r}"
                )
            for source_path in item.source_paths:
                _validate_repository_path(
                    source_path,
                    repository_root=resolved_repository_root,
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
                        repository_root=resolved_repository_root,
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

        finding_values = _require_table_list(inventory_document.get("findings"), context="findings")
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
                _require_string(finding, key, context=context)
            owner_role = _require_string(finding, "owner_role", context=context)
            if owner_role not in ownership_roles:
                findings.append(f"{context}: stale ownership role {owner_role!r}")
            finding_ids.append(_require_string(finding, "finding_id", context=context))
        open_finding_ids = _require_strings(
            inventory_document.get("open_finding_ids"), context="open_finding_ids", allow_empty=True
        )
        if open_finding_ids != tuple(finding_ids):
            findings.append("open_finding_ids must exactly match findings")
        package_status = _require_string(inventory_document, "package_status", context=str(path))
        if package_status == "partial":
            if tuple(finding_ids) != _RESOURCE_INVENTORY_OPEN_FINDING_IDS:
                findings.append(
                    "partial status requires findings "
                    f"{list(_RESOURCE_INVENTORY_OPEN_FINDING_IDS)!r}"
                )
        elif package_status == "validated":
            if inventory_document.get("operating_track") == "solo_bootstrap":
                findings.append("solo_bootstrap packages cannot claim validated status")
            if finding_ids:
                findings.append("validated status cannot retain open findings")
        else:
            findings.append("package_status must be partial or validated")

        if findings:
            raise InventoryGovernanceError(findings)
        local_evidence_manifest_path = _require_string(
            inventory_document, "local_evidence_manifest_path", context=str(path)
        )
        evidence_path_findings: list[str] = []
        _validate_repository_path(
            local_evidence_manifest_path,
            repository_root=resolved_repository_root,
            context="local_evidence_manifest_path",
            findings=evidence_path_findings,
        )
        if evidence_path_findings:
            raise InventoryGovernanceError(evidence_path_findings)
        local_evidence_commit_sha = _require_string(
            inventory_document, "local_evidence_commit_sha", context=str(path)
        )
        if _COMMIT_SHA.fullmatch(local_evidence_commit_sha) is None:
            raise InventoryGovernanceError(
                [f"{path}: local_evidence_commit_sha must be a full lowercase SHA"]
            )
        return ResourceInventory(
            catalog_version=_require_positive_integer(
                inventory_document, "catalog_version", context=str(path)
            ),
            as_of_date=as_of_date,
            inventory_scope=_require_string(
                inventory_document, "inventory_scope", context=str(path)
            ),
            package_status=package_status,
            maximum_items=maximum_items,
            query_workload_iterations=_require_positive_integer(
                inventory_document, "query_workload_iterations", context=str(path)
            ),
            query_workload_budget_ms=_require_positive_integer(
                inventory_document, "query_workload_budget_ms", context=str(path)
            ),
            local_evidence_manifest_path=local_evidence_manifest_path,
            local_evidence_commit_sha=local_evidence_commit_sha,
            kinds=kinds,
            items=items,
            finding_ids=tuple(finding_ids),
        )

    def _validate_local_evidence(self, repository_root: Path, inventory: ResourceInventory) -> None:
        """Validate the synthetic R2 bundle without treating it as forge acceptance.

        Args:
            repository_root: Resolved repository root containing policy and evidence files.
            inventory: Validated inventory whose manifest path and commit are checked.

        Raises:
            InventoryGovernanceError: If policy, manifest, or package evidence fails.
        """
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
        try:
            validate_package_evidence(manifest, _LOCAL_EVIDENCE_PROFILE)
        except EvidenceGovernanceError as error:
            raise InventoryGovernanceError(error.findings) from error

    def validate_repository(self) -> ResourceInventory:
        """Validate the authoritative inventory and its local evidence bundle.

        Returns:
            The validated immutable inventory record.

        Raises:
            InventoryGovernanceError: If inventory or local evidence validation fails.
            OSError: If repository files cannot be read.
        """
        resolved_repository_root = self._repository_root.resolve()
        inventory = self._load_with_context(
            resolved_repository_root / "docs" / "governance" / "resource-inventory.toml",
            resolved_repository_root,
        )
        self._validate_local_evidence(resolved_repository_root, inventory)
        return inventory


def load_inventory(
    path: Path, *, repository_root: Path, ownership_register_path: Path | None = None
) -> ResourceInventory:
    """Load and validate a resource inventory TOML document.

    The loader resolves ``repository_root`` before checking repository-relative
    source paths and references. It reads and validates the ownership register
    first, using ``docs/governance/domain-ownership.toml`` below the resolved
    root when ``ownership_register_path`` is omitted. It then loads the
    inventory, checks its exact schema and scalar values, parses kind and item
    records, evaluates each ``review_due_on`` against the catalog's
    ``as_of_date`` rather than today's date, and accumulates catalog-wide
    ownership, lifecycle, lineage, dependency, population and package findings
    in validation order. When no earlier findings remain, it checks the
    recorded local evidence manifest path and commit SHA before constructing
    the immutable result. It does not read or validate manifest contents;
    ``validate_repository`` performs that separate evidence check.

    Args:
        path: UTF-8 TOML inventory file; a relative path follows normal
            process working-directory semantics.
        repository_root: Repository root used for ownership and reference
            checks; relative paths are resolved from the process directory.
        ownership_register_path: Optional ownership-register TOML file. ``None``
            uses the default register below the resolved root; a supplied
            relative path remains process-relative.

    Returns:
        The validated immutable ``ResourceInventory``.

    Raises:
        InventoryGovernanceError: If TOML, schema, ownership, references,
            lifecycle, dependency, lineage, population, package, evidence-path,
            commit-SHA, or model validation fails.
        OSError: If input or ownership files cannot be read, or an uncaught
            filesystem error occurs during path checks.
        UnicodeDecodeError: If inventory or ownership TOML is not valid UTF-8.
        RuntimeError: If path resolution encounters a symlink loop.
    """
    return InventoryLoader(repository_root, ownership_register_path=ownership_register_path).load(
        path
    )


def validate_repository(repository_root: Path) -> ResourceInventory:
    """Validate the authoritative inventory and its synthetic local R2 evidence.

    The function resolves ``repository_root``, loads the authoritative
    inventory with its default ownership register, then validates the recorded
    local evidence manifest against its commit SHA and the fixed A06 R2 package
    profile. All operations are read-only.

    Args:
        repository_root: Repository root containing the governance TOML files
            and recorded local evidence bundle.

    Returns:
        The immutable ``ResourceInventory`` loaded from the authoritative
        catalog.

    Raises:
        InventoryGovernanceError: If inventory, change-risk policy, manifest,
            or package-profile validation fails; translated causes are chained.
        OSError: If root or authoritative files cannot be read. Evidence-stage
            filesystem failures are translated to the domain error.
        UnicodeDecodeError: If authoritative input is not valid UTF-8.
        RuntimeError: If path resolution encounters a symlink loop.
    """
    return InventoryLoader(repository_root).validate_repository()
