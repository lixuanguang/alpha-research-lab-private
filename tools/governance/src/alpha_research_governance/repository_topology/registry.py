"""Validate the governed source registry and dependency graph strictly."""

from __future__ import annotations

import ast
import importlib.util
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import ValidationError

from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.evidence import (
    EvidenceGovernanceError,
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)
from alpha_research_governance.repository_topology.models import (
    RepositoryTopology,
    RepositoryTopologyError,
    SourceUnit,
)

_APPLICABLE_GATES = (
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
)
_REPOSITORY_TOPOLOGY_OPEN_FINDING_IDS = ("B01-F01", "B01-F02")
_EXPECTED_REMAINING_SLICES: tuple[str, ...] = ()
_EXPECTED_SOURCE_ROOTS = (
    "src/alpha_research",
    "tests/build",
    "tests/engineering",
    "tools/governance/src/alpha_research_governance",
)
_EXPECTED_LAYER_ORDER = (
    "foundation",
    "policy",
    "evidence",
    "catalog",
    "compatibility",
    "verification",
)
_LOCAL_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id="B01",
    accountable_owner_role="platform",
    risk_class=RiskClass.R2,
    classification_facts=ChangeRiskInput(
        capital_at_risk=False,
        blast_radius="shared_domain",
        data_model_materiality="shared_or_candidate",
        security_privilege="none",
        reversibility="compatibility_window",
        computationally_material=False,
        economically_or_risk_relevant=False,
        model_or_trading_relevant=False,
        declared_class=RiskClass.R2,
    ),
    gate_requirements=tuple(
        PackageGateRequirement(gate_id=gate_id, status="passed") for gate_id in _APPLICABLE_GATES
    ),
    expected_package_status="partial",
    expected_finding_ids=_REPOSITORY_TOPOLOGY_OPEN_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=False,
)
_ROOT_KEYS = {
    "accountable_owner_role",
    "applicable_gate_ids",
    "delivery_slice",
    "findings",
    "layer_order",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "maximum_source_files",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "remaining_slices",
    "risk_class",
    "roadmap_package",
    "schema_version",
    "slice_status",
    "source_roots",
    "units",
    "validation_workload_budget_ms",
}
_UNIT_KEYS = {
    "dependencies",
    "kind",
    "layer",
    "owner_role",
    "sources",
    "supported_platforms",
    "unit_id",
    "visibility",
}
_FINDING_KEYS = {"closure_condition", "finding_id", "owner_role", "unavailable_evidence"}
_TOKEN = re.compile(r"^[a-z][a-z0-9_]*$")
_UNIT_ID = re.compile(r"^[a-z][a-z0-9_.]*$")
_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SOURCE_NAMES = {"py.typed"}
_SOURCE_SUFFIXES = {".py", ".pyi"}


def _require_table(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RepositoryTopologyError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _require_table_list(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RepositoryTopologyError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _require_string(table: dict[str, object], key: str, *, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise RepositoryTopologyError([f"{context}.{key} must be a non-empty string"])
    return value


def _require_strings(
    value: object, *, context: str, allow_empty: bool = False, require_sorted: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RepositoryTopologyError([f"{context} must be an array of non-empty strings"])
    string_values = tuple(cast(list[str], value))
    if not allow_empty and not string_values:
        raise RepositoryTopologyError([f"{context} must not be empty"])
    if len(string_values) != len(set(string_values)):
        raise RepositoryTopologyError([f"{context} must contain unique values"])
    if require_sorted and string_values != tuple(sorted(string_values)):
        raise RepositoryTopologyError([f"{context} must be sorted"])
    return string_values


def _require_repository_path(value: str, *, repository_root: Path, context: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise RepositoryTopologyError([f"{context}: invalid repository path {value!r}"])
    candidate = repository_root.joinpath(*relative.parts)
    current = repository_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RepositoryTopologyError([f"{context}: symlinks are not permitted: {value}"])
    try:
        candidate.resolve(strict=True).relative_to(repository_root)
    except (FileNotFoundError, ValueError) as error:
        raise RepositoryTopologyError(
            [f"{context}: path is missing or outside the repository: {value}"]
        ) from error
    return candidate


def _ownership_roles(path: Path) -> frozenset[str]:
    try:
        ownership_document = _require_table(
            tomllib.loads(path.read_text(encoding="utf-8")), context=str(path)
        )
    except tomllib.TOMLDecodeError as error:
        raise RepositoryTopologyError([f"{path}: invalid TOML: {error}"]) from error
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
    for index, finding in enumerate(
        _require_table_list(ownership_document.get("findings"), context="findings"), 1
    ):
        roles.add(_require_string(finding, "owner_role", context=f"findings[{index}]"))
    return frozenset(roles)


def _source_files(
    repository_root: Path, source_roots: tuple[str, ...], maximum_source_files: int
) -> frozenset[str]:
    source_files: set[str] = set()
    for source_root in source_roots:
        directory = _require_repository_path(
            source_root, repository_root=repository_root, context="source_roots"
        )
        if not directory.is_dir():
            raise RepositoryTopologyError([f"source root must be a directory: {source_root}"])
        for path in directory.rglob("*"):
            if path.is_file() and (path.suffix in _SOURCE_SUFFIXES or path.name in _SOURCE_NAMES):
                if path.is_symlink():
                    raise RepositoryTopologyError([f"source file cannot be a symlink: {path}"])
                source_files.add(path.relative_to(repository_root).as_posix())
                if len(source_files) > maximum_source_files:
                    raise RepositoryTopologyError(
                        [f"current source exceeds the {maximum_source_files}-file workload limit"]
                    )
    return frozenset(source_files)


def _module_name(source: str) -> tuple[str, bool] | None:
    path = PurePosixPath(source)
    if path.suffix not in _SOURCE_SUFFIXES:
        return None
    parts = list(path.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    is_package = bool(parts and parts[-1] == "__init__")
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _internal_imports(
    path: Path, module_name: str, is_package: bool, known_modules: frozenset[str]
) -> frozenset[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        raise RepositoryTopologyError([f"{path}: cannot parse source: {error}"]) from error
    imports: set[str] = set()
    internal_roots = frozenset(module.partition(".")[0] for module in known_modules)

    def is_internal(name: str) -> bool:
        return name.partition(".")[0] in internal_roots

    package = module_name if is_package else module_name.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if is_internal(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                try:
                    base = importlib.util.resolve_name(
                        "." * node.level + (node.module or ""), package
                    )
                except (ImportError, ValueError) as error:
                    raise RepositoryTopologyError(
                        [f"{path}:{node.lineno}: invalid relative import"]
                    ) from error
            elif node.module:
                base = node.module
            else:
                continue
            if is_internal(base):
                for alias in node.names:
                    candidate = f"{base}.{alias.name}"
                    imports.add(candidate if candidate in known_modules else base)
    return frozenset(imports)


def _find_cycles(units: tuple[SourceUnit, ...]) -> tuple[str, ...]:
    graph = {unit.unit_id: unit.dependencies for unit in units}
    visited: set[str] = set()
    active: list[str] = []
    cycles: set[str] = set()

    def visit_dependency(unit_id: str) -> None:
        if unit_id in active:
            start = active.index(unit_id)
            cycles.add(" -> ".join((*active[start:], unit_id)))
            return
        if unit_id in visited:
            return
        active.append(unit_id)
        for dependency in graph.get(unit_id, ()):
            visit_dependency(dependency)
        active.pop()
        visited.add(unit_id)

    for unit_id in graph:
        visit_dependency(unit_id)
    return tuple(sorted(cycles))


def _validate_graph(topology: RepositoryTopology, repository_root: Path) -> None:
    findings: list[str] = []
    unit_by_id = {unit.unit_id: unit for unit in topology.units}
    if len(unit_by_id) != len(topology.units):
        findings.append("unit IDs must be unique")
    if tuple(unit_by_id) != tuple(sorted(unit_by_id)):
        findings.append("units must be sorted by unit_id")
    layer_index = {layer: index for index, layer in enumerate(topology.layer_order)}
    ownership_roles = _ownership_roles(
        repository_root / "docs" / "governance" / "domain-ownership.toml"
    )
    declared_sources: dict[str, str] = {}
    for unit in topology.units:
        if unit.kind not in {"compatibility", "test", "tool"}:
            findings.append(f"{unit.unit_id}: kind must be compatibility, test, or tool")
        if unit.layer not in layer_index:
            findings.append(f"{unit.unit_id}: unknown layer {unit.layer!r}")
        if unit.owner_role not in ownership_roles:
            findings.append(f"{unit.unit_id}: stale owner role {unit.owner_role!r}")
        if any(_TOKEN.fullmatch(platform) is None for platform in unit.supported_platforms):
            findings.append(f"{unit.unit_id}: supported platforms must be lower_snake_case")
        if "any" in unit.supported_platforms and unit.supported_platforms != ("any",):
            findings.append(f"{unit.unit_id}: platform 'any' cannot be combined")
        for source in unit.sources:
            if source in declared_sources:
                findings.append(
                    f"{source}: source is assigned to both {declared_sources[source]} "
                    f"and {unit.unit_id}"
                )
            declared_sources[source] = unit.unit_id
            try:
                candidate = _require_repository_path(
                    source, repository_root=repository_root, context=f"{unit.unit_id}.sources"
                )
            except RepositoryTopologyError as error:
                findings.extend(error.findings)
            else:
                if not candidate.is_file():
                    findings.append(f"{unit.unit_id}: source must be a file: {source}")
        for dependency in unit.dependencies:
            target = unit_by_id.get(dependency)
            if target is None:
                findings.append(f"{unit.unit_id}: unknown dependency {dependency!r}")
            elif dependency == unit.unit_id:
                findings.append(f"{unit.unit_id}: self-dependency is prohibited")
            elif unit.layer in layer_index and target.layer in layer_index:
                if layer_index[target.layer] > layer_index[unit.layer]:
                    findings.append(f"{unit.unit_id}: forbidden upward dependency on {dependency}")
        for consumer in unit.visibility:
            if consumer not in unit_by_id:
                findings.append(f"{unit.unit_id}: visibility names unknown unit {consumer!r}")

    actual_sources = _source_files(
        repository_root, topology.source_roots, topology.maximum_source_files
    )
    declared_source_set = frozenset(declared_sources)
    for source in sorted(actual_sources - declared_source_set):
        findings.append(f"{source}: current source is not registered")
    for source in sorted(declared_source_set - actual_sources):
        findings.append(f"{source}: registered path is outside the current source set")

    expected_consumers: dict[str, set[str]] = {unit_id: set() for unit_id in unit_by_id}
    for unit in topology.units:
        for dependency in unit.dependencies:
            if dependency in expected_consumers:
                expected_consumers[dependency].add(unit.unit_id)
    for unit in topology.units:
        if set(unit.visibility) != expected_consumers[unit.unit_id]:
            findings.append(f"{unit.unit_id}: visibility must exactly match direct consumers")

    for cycle in _find_cycles(topology.units):
        findings.append(f"source dependency cycle: {cycle}")

    module_units: dict[str, str] = {}
    source_modules: dict[str, tuple[str, bool]] = {}
    for source, unit_id in declared_sources.items():
        if source not in actual_sources:
            continue
        module = _module_name(source)
        if module is not None:
            module_name, _ = module
            if module_name in module_units and module_units[module_name] != unit_id:
                findings.append(f"{module_name}: module is assigned to multiple source units")
            module_units[module_name] = unit_id
            source_modules[source] = module
    actual_dependencies: dict[str, set[str]] = {unit_id: set() for unit_id in unit_by_id}
    known_modules = frozenset(module_units)
    for source, (module_name, is_package) in source_modules.items():
        unit_id = declared_sources[source]
        for imported_module in _internal_imports(
            repository_root / source, module_name, is_package, known_modules
        ):
            resolved_import = imported_module
            while resolved_import not in module_units and "." in resolved_import:
                resolved_import = resolved_import.rpartition(".")[0]
            imported_unit = module_units.get(resolved_import)
            if imported_unit is None:
                findings.append(f"{source}: internal import {imported_module!r} is not registered")
            elif imported_unit != unit_id:
                actual_dependencies[unit_id].add(imported_unit)
    for unit in topology.units:
        declared = set(unit.dependencies)
        actual = actual_dependencies[unit.unit_id]
        if declared != actual:
            findings.append(
                f"{unit.unit_id}: direct dependencies differ from imports; "
                f"missing={sorted(actual - declared)!r}, stale={sorted(declared - actual)!r}"
            )
    if findings:
        raise RepositoryTopologyError(findings)


def load_topology(path: Path, *, repository_root: Path) -> RepositoryTopology:
    """Load and validate the exact repository-topology registry contract."""
    try:
        topology_document = _require_table(
            tomllib.loads(path.read_text(encoding="utf-8")), context=str(path)
        )
    except tomllib.TOMLDecodeError as error:
        raise RepositoryTopologyError([f"{path}: invalid TOML: {error}"]) from error
    if set(topology_document) != _ROOT_KEYS:
        raise RepositoryTopologyError([f"{path}: registry has missing or unknown fields"])
    units: list[SourceUnit] = []
    for index, item in enumerate(
        _require_table_list(topology_document.get("units"), context="units"), 1
    ):
        context = f"units[{index}]"
        if set(item) != _UNIT_KEYS:
            raise RepositoryTopologyError([f"{context} has missing or unknown fields"])
        unit_id = _require_string(item, "unit_id", context=context)
        owner_role = _require_string(item, "owner_role", context=context)
        if _UNIT_ID.fullmatch(unit_id) is None or _TOKEN.fullmatch(owner_role) is None:
            raise RepositoryTopologyError([f"{context}: invalid unit_id or owner_role"])
        units.append(
            SourceUnit(
                unit_id=unit_id,
                kind=_require_string(item, "kind", context=context),
                layer=_require_string(item, "layer", context=context),
                owner_role=owner_role,
                supported_platforms=_require_strings(
                    item.get("supported_platforms"),
                    context=f"{context}.supported_platforms",
                    require_sorted=True,
                ),
                dependencies=_require_strings(
                    item.get("dependencies"),
                    context=f"{context}.dependencies",
                    allow_empty=True,
                    require_sorted=True,
                ),
                visibility=_require_strings(
                    item.get("visibility"),
                    context=f"{context}.visibility",
                    allow_empty=True,
                    require_sorted=True,
                ),
                sources=_require_strings(
                    item.get("sources"), context=f"{context}.sources", require_sorted=True
                ),
            )
        )
    finding_ids: list[str] = []
    ownership_roles = _ownership_roles(
        repository_root.resolve() / "docs" / "governance" / "domain-ownership.toml"
    )
    for index, item in enumerate(
        _require_table_list(topology_document.get("findings"), context="findings"), 1
    ):
        context = f"findings[{index}]"
        if set(item) != _FINDING_KEYS:
            raise RepositoryTopologyError([f"{context} has missing or unknown fields"])
        for key in _FINDING_KEYS:
            _require_string(item, key, context=context)
        if _require_string(item, "owner_role", context=context) not in ownership_roles:
            raise RepositoryTopologyError([f"{context}: stale finding owner role"])
        finding_ids.append(_require_string(item, "finding_id", context=context))
    open_finding_ids = _require_strings(
        topology_document.get("open_finding_ids"), context="open_finding_ids"
    )
    expected_scalars = {
        "accountable_owner_role": "platform",
        "delivery_slice": "B01c",
        "maximum_source_files": 1000,
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "risk_class": "R2",
        "roadmap_package": "B01",
        "schema_version": 1,
        "slice_status": "provisionally_implemented",
        "validation_workload_budget_ms": 1000,
    }
    findings: list[str] = []
    for key, expected in expected_scalars.items():
        if topology_document.get(key) != expected:
            findings.append(f"{path}: {key} must be {expected!r}")
    applicable_gates = _require_strings(
        topology_document.get("applicable_gate_ids"), context="applicable_gate_ids"
    )
    if applicable_gates != _APPLICABLE_GATES:
        findings.append(f"{path}: applicable_gate_ids must match the R2 policy")
    remaining_slices = _require_strings(
        topology_document.get("remaining_slices"), context="remaining_slices", allow_empty=True
    )
    if remaining_slices != _EXPECTED_REMAINING_SLICES:
        findings.append(f"{path}: remaining_slices must be empty after B01c")
    source_roots = _require_strings(topology_document.get("source_roots"), context="source_roots")
    if source_roots != _EXPECTED_SOURCE_ROOTS:
        findings.append(f"{path}: source_roots must identify the exact current source areas")
    layer_order = _require_strings(topology_document.get("layer_order"), context="layer_order")
    if layer_order != _EXPECTED_LAYER_ORDER:
        findings.append(f"{path}: layer_order must preserve the governed dependency direction")
    if tuple(finding_ids) != _REPOSITORY_TOPOLOGY_OPEN_FINDING_IDS or open_finding_ids != tuple(
        finding_ids
    ):
        findings.append(f"{path}: partial status requires the exact B01 findings")
    evidence_sha = _require_string(
        topology_document, "local_evidence_commit_sha", context=str(path)
    )
    if _COMMIT_SHA.fullmatch(evidence_sha) is None:
        findings.append(f"{path}: local_evidence_commit_sha must be a full lowercase SHA")
    evidence_path = _require_string(
        topology_document, "local_evidence_manifest_path", context=str(path)
    )
    if findings:
        raise RepositoryTopologyError(findings)
    try:
        topology = RepositoryTopology(
            schema_version=cast(int, topology_document["schema_version"]),
            roadmap_package=cast(str, topology_document["roadmap_package"]),
            delivery_slice=cast(str, topology_document["delivery_slice"]),
            operating_track=cast(str, topology_document["operating_track"]),
            package_status=cast(str, topology_document["package_status"]),
            slice_status=cast(str, topology_document["slice_status"]),
            accountable_owner_role=cast(str, topology_document["accountable_owner_role"]),
            risk_class=cast(str, topology_document["risk_class"]),
            applicable_gate_ids=applicable_gates,
            source_roots=source_roots,
            maximum_source_files=cast(int, topology_document["maximum_source_files"]),
            validation_workload_budget_ms=cast(
                int, topology_document["validation_workload_budget_ms"]
            ),
            layer_order=layer_order,
            remaining_slices=remaining_slices,
            local_evidence_manifest_path=evidence_path,
            local_evidence_commit_sha=evidence_sha,
            units=tuple(units),
            finding_ids=tuple(finding_ids),
        )
    except ValidationError as error:
        raise RepositoryTopologyError([f"{path}: topology model validation failed"]) from error
    _validate_graph(topology, repository_root.resolve())
    return topology


def validate_repository(repository_root: Path) -> RepositoryTopology:
    """Validate the enforced tooling graph and synthetic local evidence."""
    resolved_repository_root = repository_root.resolve()
    topology = load_topology(
        resolved_repository_root / "docs" / "architecture" / "repository-topology.toml",
        repository_root=resolved_repository_root,
    )
    try:
        manifest_path = _require_repository_path(
            topology.local_evidence_manifest_path,
            repository_root=resolved_repository_root,
            context="local_evidence_manifest_path",
        )
        manifest = validate_manifest(
            manifest_path,
            expected_commit_sha=topology.local_evidence_commit_sha,
            change_policy=load_change_risk_policy(
                resolved_repository_root / "docs" / "governance" / "change-risk-policy.toml"
            ),
        )
        validate_package_evidence(manifest, _LOCAL_EVIDENCE_PROFILE)
    except (EvidenceGovernanceError, OSError, ValueError) as error:
        raise RepositoryTopologyError([f"B01c local evidence bundle: {error}"]) from error
    return topology
