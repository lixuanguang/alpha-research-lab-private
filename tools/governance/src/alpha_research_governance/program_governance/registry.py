"""Validate the program roadmap, KPIs, and observations strictly."""

from __future__ import annotations

import json
import re
import tomllib
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

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
from alpha_research_governance.program_governance.models import (
    MetricDefinition,
    MetricObservation,
    PackageNode,
    PackageState,
    ProgramGovernance,
    ProgramGovernanceError,
)

PACKAGE_IDS = tuple(f"{wave}{number:02d}" for wave in "ABCDEFGHIJKL" for number in range(1, 9))
METRIC_IDS = (
    "kpi.build_duration_seconds",
    "kpi.test_duration_seconds",
    "kpi.deployment_lead_time_seconds",
    "kpi.incident_rate_per_1000_runtime_hours",
    "kpi.data_quality_defects_per_million_records",
    "kpi.research_reproducibility_percent",
    "kpi.rollback_recovery_seconds",
)
APPLICABLE_GATE_IDS = (
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

_EXPECTED_FINDING_IDS = ("A08-F01", "A08-F02", "A08-F03")
_LOCAL_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id="A08",
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
        PackageGateRequirement(gate_id=gate_id, status="passed") for gate_id in APPLICABLE_GATE_IDS
    ),
    expected_package_status="partial",
    expected_finding_ids=_EXPECTED_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=False,
)
_PACKAGE_ID = re.compile(r"^[A-L](?:0[1-8])$")
_METRIC_ID = re.compile(r"^kpi\.[a-z][a-z0-9_]*$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_]*$")
_EVENT_ID = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_WINDOW = re.compile(r"^P[1-9][0-9]*D$")
_DIMENSION_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_MAX_OBSERVATION_FILE_BYTES = 10_000_000
_ALLOWED_DEFERRED_CLASSES = {
    "external_control_plane",
    "independent_review",
    "organization",
    "qualified_review",
    "target_environment",
}
_ROOT_KEYS = {
    "accountable_owner_role",
    "aggregation_workload_budget_ms",
    "applicable_gate_ids",
    "as_of_date",
    "findings",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "maximum_observations",
    "metrics",
    "observation_schema_version",
    "open_finding_ids",
    "operating_track",
    "package_states",
    "package_status",
    "risk_class",
    "roadmap_package",
    "roadmap_path",
    "schema_version",
}
_STATE_KEYS = {
    "deferred_evidence_classes",
    "evidence_paths",
    "open_finding_ids",
    "owner_role",
    "package_id",
    "repository_local_status",
    "status",
}
_METRIC_REQUIRED_KEYS = {
    "aggregation",
    "baseline_status",
    "bounded_ratio",
    "collection_mode",
    "denominator_unit",
    "direction",
    "hard_gate_substitute",
    "manual_entry_allowed",
    "metric_id",
    "minimum_observations",
    "name",
    "numerator_unit",
    "output_unit",
    "owner_role",
    "producer_packages",
    "required_dimensions",
    "scale",
    "source_event_type",
    "target_status",
    "value_kind",
    "window",
}
_METRIC_OPTIONAL_KEYS = {
    "baseline_value",
    "target_approval_evidence",
    "target_value",
}
_OBSERVATION_COMMON_KEYS = {
    "dimensions",
    "event_id",
    "evidence_url",
    "metric_id",
    "schema_version",
    "source_event_type",
    "source_revision",
    "source_run_id",
    "window_end",
    "window_start",
}


def _require_table(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProgramGovernanceError([f"{context} must be a table or object"])
    return cast(dict[str, object], value)


def _require_table_list(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProgramGovernanceError([f"{context} must be an array of tables"])
    return cast(list[dict[str, object]], value)


def _require_string(table: dict[str, object], key: str, *, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProgramGovernanceError([f"{context}.{key} must be a non-empty string"])
    return value


def _require_strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProgramGovernanceError([f"{context} must be an array of non-empty strings"])
    string_values = tuple(cast(list[str], value))
    if not allow_empty and not string_values:
        raise ProgramGovernanceError([f"{context} must not be empty"])
    if len(string_values) != len(set(string_values)):
        raise ProgramGovernanceError([f"{context} must contain unique values"])
    return string_values


def _require_positive_integer(table: dict[str, object], key: str, *, context: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProgramGovernanceError([f"{context}.{key} must be a positive integer"])
    return value


def _require_number(table: dict[str, object], key: str, *, context: str) -> float:
    value = table.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ProgramGovernanceError([f"{context}.{key} must be a finite number"])
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise ProgramGovernanceError([f"{context}.{key} must be a finite number"])
    return numeric_value


def _parse_optional_number(table: dict[str, object], key: str, *, context: str) -> float | None:
    return None if key not in table else _require_number(table, key, context=context)


def _parse_iso_date(value: str, *, context: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ProgramGovernanceError([f"{context} must use YYYY-MM-DD"]) from error


def _parse_utc_datetime(value: str, *, context: str) -> datetime:
    if not value.endswith("Z"):
        raise ProgramGovernanceError([f"{context} must be an ISO-8601 UTC timestamp ending Z"])
    try:
        parsed_datetime = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ProgramGovernanceError([f"{context} must be an ISO-8601 UTC timestamp"]) from error
    if parsed_datetime.tzinfo != UTC:
        raise ProgramGovernanceError([f"{context} must be UTC"])
    return parsed_datetime


def _load_toml(path: Path) -> dict[str, object]:
    try:
        parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ProgramGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    return _require_table(parsed_document, context=str(path))


def _load_json_line(line: str, *, context: str) -> dict[str, object]:
    def build_json_object_rejecting_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        json_object: dict[str, object] = {}
        for key, value in pairs:
            if key in json_object:
                raise ProgramGovernanceError([f"{context}: duplicate JSON field {key!r}"])
            json_object[key] = value
        return json_object

    try:
        parsed_document: object = json.loads(
            line,
            object_pairs_hook=build_json_object_rejecting_duplicate_keys,
        )
    except json.JSONDecodeError as error:
        raise ProgramGovernanceError([f"{context}: invalid JSON: {error}"]) from error
    return _require_table(parsed_document, context=context)


def _ownership_roles(path: Path) -> frozenset[str]:
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
    return frozenset(roles)


def _require_repository_file(value: str, *, repository_root: Path, context: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProgramGovernanceError([f"{context}: repository path escapes the root: {value}"])
    candidate = repository_root / relative
    try:
        candidate.resolve(strict=True).relative_to(repository_root)
    except (FileNotFoundError, ValueError) as error:
        raise ProgramGovernanceError(
            [f"{context}: repository path is missing or outside the root: {value}"]
        ) from error
    if not candidate.is_file():
        raise ProgramGovernanceError([f"{context}: repository path must identify a file"])
    return candidate


def _require_https_url(value: str, *, context: str) -> str:
    try:
        parsed_url = urlsplit(value)
    except ValueError as error:
        raise ProgramGovernanceError([f"{context} must use a valid HTTPS URL"]) from error
    has_credentials = parsed_url.username is not None or parsed_url.password is not None
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or has_credentials
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ProgramGovernanceError([f"{context} must use HTTPS without credentials"])
    return value


def _expand_range(token: str) -> tuple[str, ...]:
    if _PACKAGE_ID.fullmatch(token):
        return (token,)
    parts = token.split("-")
    if len(parts) != 2 or any(_PACKAGE_ID.fullmatch(part) is None for part in parts):
        raise ProgramGovernanceError([f"unsupported roadmap dependency token {token!r}"])
    start, end = parts
    start_wave = ord(start[0])
    end_wave = ord(end[0])
    start_number = int(start[1:])
    end_number = int(end[1:])
    if start_wave > end_wave:
        raise ProgramGovernanceError([f"roadmap dependency range is reversed: {token}"])
    if start_wave == end_wave:
        if start_number > end_number:
            raise ProgramGovernanceError([f"roadmap dependency range is reversed: {token}"])
        return tuple(f"{start[0]}{number:02d}" for number in range(start_number, end_number + 1))
    if start_number != 1 or end_number != 8:
        raise ProgramGovernanceError(
            [f"cross-wave dependency ranges must span complete waves: {token}"]
        )
    return tuple(
        f"{chr(wave)}{number:02d}"
        for wave in range(start_wave, end_wave + 1)
        for number in range(1, 9)
    )


def _parse_dependency_list(expression: str) -> tuple[str, ...]:
    values: list[str] = []
    if expression == "-":
        return ()
    for token in (item.strip() for item in expression.split(",")):
        if not token:
            raise ProgramGovernanceError(["roadmap dependency expression contains an empty token"])
        values.extend(_expand_range(token))
    if len(values) != len(set(values)):
        raise ProgramGovernanceError(
            [f"roadmap dependency expression repeats a package: {expression}"]
        )
    return tuple(values)


def _parse_dependency_expression(
    expression: str,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    parts = expression.split(";")
    if len(parts) > 2:
        raise ProgramGovernanceError([f"roadmap dependency expression is malformed: {expression}"])
    dependencies = _parse_dependency_list(parts[0].strip())
    groups: tuple[tuple[str, ...], ...] = ()
    if len(parts) == 2:
        conditional = parts[1].strip()
        prefix = "any of "
        if not conditional.startswith(prefix):
            raise ProgramGovernanceError([f"unsupported conditional dependency: {conditional}"])
        group = _parse_dependency_list(conditional.removeprefix(prefix))
        if len(group) < 2:
            raise ProgramGovernanceError(
                ["any-of dependency group must contain at least two packages"]
            )
        groups = (group,)
    return dependencies, groups


def _load_roadmap(path: Path) -> tuple[PackageNode, ...]:
    """Parse the 96-package roadmap tables into an exact DAG."""
    lines = path.read_text(encoding="utf-8").splitlines()
    current_wave: str | None = None
    packages: list[PackageNode] = []
    for line in lines:
        wave_match = re.fullmatch(r"## Wave ([A-L]) - .+", line)
        if wave_match is not None:
            current_wave = wave_match.group(1)
            continue
        if re.match(r"\| [A-L]0[1-8] \|", line) is None:
            continue
        row_match = re.fullmatch(
            r"\| ([A-L]0[1-8]) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|",
            line,
        )
        if row_match is None:
            raise ProgramGovernanceError(
                [
                    "roadmap package rows must declare objective, library/tool, "
                    "incorporation boundary, and dependencies"
                ]
            )
        package_id, objective, library, boundary, expression = (
            value.strip() for value in row_match.groups()
        )
        if not library or not boundary:
            raise ProgramGovernanceError(
                [f"{package_id}: library/tool and incorporation boundary cannot be empty"]
            )
        if current_wave != package_id[0]:
            raise ProgramGovernanceError(
                [f"{package_id}: roadmap row is outside its Wave {package_id[0]} section"]
            )
        dependencies, groups = _parse_dependency_expression(expression)
        packages.append(
            PackageNode(
                package_id=package_id,
                wave=package_id[0],
                objective=objective,
                dependencies=dependencies,
                any_of_dependency_groups=groups,
            )
        )
    if tuple(package.package_id for package in packages) != PACKAGE_IDS:
        raise ProgramGovernanceError(
            ["roadmap must declare A01-L08 exactly once in dependency order"]
        )
    package_ids = frozenset(PACKAGE_IDS)
    findings: list[str] = []
    for package in packages:
        referenced = package.dependencies + tuple(
            item for group in package.any_of_dependency_groups for item in group
        )
        unknown = sorted(set(referenced) - package_ids)
        if unknown:
            findings.append(f"{package.package_id}: unknown dependencies {unknown!r}")
        if package.package_id in referenced:
            findings.append(f"{package.package_id}: package cannot depend on itself")
    findings.extend(_find_dependency_cycles(tuple(packages)))
    if findings:
        raise ProgramGovernanceError(findings)
    return tuple(packages)


def load_roadmap(path: Path) -> tuple[PackageNode, ...]:
    """Load the roadmap while preserving its public domain-error contract."""
    try:
        return _load_roadmap(path)
    except ValidationError as error:
        raise ProgramGovernanceError([f"{path}: roadmap model validation failed"]) from error


def _find_dependency_cycles(packages: tuple[PackageNode, ...]) -> tuple[str, ...]:
    graph = {
        package.package_id: package.dependencies
        + tuple(item for group in package.any_of_dependency_groups for item in group)
        for package in packages
    }
    states: dict[str, int] = {}
    cycles: list[str] = []

    def visit_dependency(package_id: str, trail: tuple[str, ...]) -> None:
        state = states.get(package_id, 0)
        if state == 1:
            start = trail.index(package_id)
            cycles.append(" -> ".join((*trail[start:], package_id)))
            return
        if state == 2:
            return
        states[package_id] = 1
        for dependency in graph[package_id]:
            visit_dependency(dependency, (*trail, package_id))
        states[package_id] = 2

    for package_id in graph:
        visit_dependency(package_id, ())
    return tuple(f"roadmap dependency cycle: {cycle}" for cycle in dict.fromkeys(cycles))


def _parse_package_states(
    value: object,
    *,
    repository_root: Path,
    ownership_roles: frozenset[str],
) -> tuple[PackageState, ...]:
    states: list[PackageState] = []
    for index, entry in enumerate(_require_table_list(value, context="package_states"), 1):
        context = f"package_states[{index}]"
        if set(entry) != _STATE_KEYS:
            raise ProgramGovernanceError([f"{context} has missing or unknown fields"])
        package_id = _require_string(entry, "package_id", context=context)
        status = _require_string(entry, "status", context=context)
        owner_role = _require_string(entry, "owner_role", context=context)
        repository_local_status = _require_string(entry, "repository_local_status", context=context)
        deferred_classes = _require_strings(
            entry.get("deferred_evidence_classes"),
            context=f"{context}.deferred_evidence_classes",
            allow_empty=True,
        )
        evidence_paths = _require_strings(
            entry.get("evidence_paths"), context=f"{context}.evidence_paths"
        )
        finding_ids = _require_strings(
            entry.get("open_finding_ids"), context=f"{context}.open_finding_ids"
        )
        if package_id not in PACKAGE_IDS:
            raise ProgramGovernanceError([f"{context}.package_id is unsupported"])
        if status != "partial":
            raise ProgramGovernanceError(
                [f"{context}: solo-bootstrap implemented packages must remain partial"]
            )
        if repository_local_status != "passed":
            raise ProgramGovernanceError(
                [f"{context}: implemented dependencies require passing repository-local evidence"]
            )
        if owner_role not in ownership_roles:
            raise ProgramGovernanceError([f"{context}: stale owner role {owner_role!r}"])
        invalid_classes = sorted(set(deferred_classes) - _ALLOWED_DEFERRED_CLASSES)
        if invalid_classes or not deferred_classes:
            raise ProgramGovernanceError(
                [f"{context}: deferred evidence classes must be recognized and non-empty"]
            )
        if any(not finding.startswith(f"{package_id}-F") for finding in finding_ids):
            raise ProgramGovernanceError([f"{context}: finding IDs must belong to {package_id}"])
        evidence_text = "\n".join(
            _require_repository_file(
                path, repository_root=repository_root, context=context
            ).read_text(encoding="utf-8")
            for path in evidence_paths
        )
        missing_findings = [finding for finding in finding_ids if finding not in evidence_text]
        if missing_findings:
            raise ProgramGovernanceError(
                [f"{context}: evidence paths do not retain findings {missing_findings!r}"]
            )
        states.append(
            PackageState(
                package_id=package_id,
                status=status,
                owner_role=owner_role,
                repository_local_status=repository_local_status,
                deferred_evidence_classes=deferred_classes,
                evidence_paths=evidence_paths,
                open_finding_ids=finding_ids,
            )
        )
    state_ids = tuple(state.package_id for state in states)
    if state_ids != PACKAGE_IDS[: len(state_ids)] or "A08" not in state_ids:
        raise ProgramGovernanceError(
            ["package_states must be a contiguous implemented prefix including A01-A08"]
        )
    return tuple(states)


def _parse_metric(
    entry: dict[str, object],
    *,
    index: int,
    ownership_roles: frozenset[str],
) -> MetricDefinition:
    context = f"metrics[{index}]"
    keys = set(entry)
    if (
        not _METRIC_REQUIRED_KEYS <= keys
        or not keys <= _METRIC_REQUIRED_KEYS | _METRIC_OPTIONAL_KEYS
    ):
        raise ProgramGovernanceError([f"{context} has missing or unknown fields"])
    metric_id = _require_string(entry, "metric_id", context=context)
    owner_role = _require_string(entry, "owner_role", context=context)
    value_kind = _require_string(entry, "value_kind", context=context)
    aggregation = _require_string(entry, "aggregation", context=context)
    output_unit = _require_string(entry, "output_unit", context=context)
    direction = _require_string(entry, "direction", context=context)
    numerator_unit = _require_string(entry, "numerator_unit", context=context)
    denominator_unit = _require_string(entry, "denominator_unit", context=context)
    source_event_type = _require_string(entry, "source_event_type", context=context)
    producer_packages = _require_strings(
        entry.get("producer_packages"), context=f"{context}.producer_packages"
    )
    dimensions = _require_strings(
        entry.get("required_dimensions"), context=f"{context}.required_dimensions"
    )
    collection_mode = _require_string(entry, "collection_mode", context=context)
    baseline_status = _require_string(entry, "baseline_status", context=context)
    target_status = _require_string(entry, "target_status", context=context)
    scale = _require_number(entry, "scale", context=context)
    baseline_value = _parse_optional_number(entry, "baseline_value", context=context)
    target_value = _parse_optional_number(entry, "target_value", context=context)
    target_evidence = (
        None
        if "target_approval_evidence" not in entry
        else _require_https_url(
            _require_string(entry, "target_approval_evidence", context=context),
            context=f"{context}.target_approval_evidence",
        )
    )
    bounded_ratio = entry.get("bounded_ratio")
    manual_entry_allowed = entry.get("manual_entry_allowed")
    hard_gate_substitute = entry.get("hard_gate_substitute")
    if _METRIC_ID.fullmatch(metric_id) is None:
        raise ProgramGovernanceError([f"{context}.metric_id is malformed"])
    if owner_role not in ownership_roles:
        raise ProgramGovernanceError([f"{context}: stale owner role {owner_role!r}"])
    if value_kind not in {"duration", "ratio"}:
        raise ProgramGovernanceError([f"{context}.value_kind is unsupported"])
    if value_kind == "duration" and aggregation not in {"p50", "p90", "p95", "p99"}:
        raise ProgramGovernanceError([f"{context}: duration metric requires a percentile"])
    if value_kind == "ratio" and aggregation != "ratio":
        raise ProgramGovernanceError([f"{context}: ratio metric requires ratio aggregation"])
    if direction not in {"lower_is_better", "higher_is_better"}:
        raise ProgramGovernanceError([f"{context}.direction is unsupported"])
    if any(
        _TOKEN.fullmatch(unit) is None for unit in (output_unit, numerator_unit, denominator_unit)
    ):
        raise ProgramGovernanceError([f"{context}: metric units must use lower_snake_case"])
    if scale <= 0:
        raise ProgramGovernanceError([f"{context}.scale must be positive"])
    if any(package not in PACKAGE_IDS for package in producer_packages):
        raise ProgramGovernanceError([f"{context}: producer package is unsupported"])
    if any(_TOKEN.fullmatch(dimension) is None for dimension in dimensions):
        raise ProgramGovernanceError([f"{context}: dimensions must use lower_snake_case"])
    if _TOKEN.fullmatch(source_event_type) is None:
        raise ProgramGovernanceError([f"{context}.source_event_type must use lower_snake_case"])
    if collection_mode != "automatic_event" or manual_entry_allowed is not False:
        raise ProgramGovernanceError([f"{context}: manual KPI entry is prohibited"])
    if hard_gate_substitute is not False:
        raise ProgramGovernanceError([f"{context}: a KPI cannot substitute for a hard gate"])
    if not isinstance(bounded_ratio, bool):
        raise ProgramGovernanceError([f"{context}.bounded_ratio must be a Boolean"])
    for field_name, numeric_value in (
        ("baseline_value", baseline_value),
        ("target_value", target_value),
    ):
        if numeric_value is not None and numeric_value < 0:
            raise ProgramGovernanceError([f"{context}.{field_name} must be non-negative"])
        if bounded_ratio and numeric_value is not None and numeric_value > scale:
            raise ProgramGovernanceError(
                [f"{context}.{field_name} cannot exceed the bounded ratio scale"]
            )
    if baseline_status not in {"awaiting_target_observations", "available"}:
        raise ProgramGovernanceError([f"{context}.baseline_status is unsupported"])
    if (baseline_status == "available") != (baseline_value is not None):
        raise ProgramGovernanceError([f"{context}: baseline status and value disagree"])
    if target_status not in {"pending_owner_approval", "approved"}:
        raise ProgramGovernanceError([f"{context}.target_status is unsupported"])
    if target_status == "approved" and (target_value is None or target_evidence is None):
        raise ProgramGovernanceError([f"{context}: approved target requires value and evidence"])
    if target_status != "approved" and (target_value is not None or target_evidence is not None):
        raise ProgramGovernanceError([f"{context}: pending target cannot claim value or approval"])
    window = _require_string(entry, "window", context=context)
    if _WINDOW.fullmatch(window) is None:
        raise ProgramGovernanceError([f"{context}.window must be a positive whole-day period"])
    return MetricDefinition(
        metric_id=metric_id,
        name=_require_string(entry, "name", context=context),
        owner_role=owner_role,
        value_kind=value_kind,
        aggregation=aggregation,
        output_unit=output_unit,
        direction=direction,
        scale=scale,
        numerator_unit=numerator_unit,
        denominator_unit=denominator_unit,
        bounded_ratio=bounded_ratio,
        minimum_observations=_require_positive_integer(
            entry, "minimum_observations", context=context
        ),
        window=window,
        source_event_type=source_event_type,
        producer_packages=producer_packages,
        required_dimensions=dimensions,
        collection_mode=collection_mode,
        manual_entry_allowed=manual_entry_allowed,
        baseline_status=baseline_status,
        baseline_value=baseline_value,
        target_status=target_status,
        target_value=target_value,
        target_approval_evidence=target_evidence,
        hard_gate_substitute=hard_gate_substitute,
    )


def _parse_findings(value: object) -> tuple[str, ...]:
    identifiers: list[str] = []
    for index, entry in enumerate(_require_table_list(value, context="findings"), 1):
        context = f"findings[{index}]"
        if set(entry) != {
            "closure_condition",
            "finding_id",
            "owner_role",
            "unavailable_evidence",
        }:
            raise ProgramGovernanceError([f"{context} has missing or unknown fields"])
        identifiers.append(_require_string(entry, "finding_id", context=context))
        for key in ("closure_condition", "owner_role", "unavailable_evidence"):
            _require_string(entry, key, context=context)
    return tuple(identifiers)


def _load_program(
    path: Path,
    *,
    repository_root: Path,
    ownership_register_path: Path | None = None,
) -> ProgramGovernance:
    """Load program governance and validate its roadmap, owners, and evidence paths."""
    resolved_repository_root = repository_root.resolve()
    program_document = _load_toml(path)
    if set(program_document) != _ROOT_KEYS:
        raise ProgramGovernanceError([f"{path}: fields must be exactly {sorted(_ROOT_KEYS)!r}"])
    expected_scalars: dict[str, object] = {
        "schema_version": 1,
        "roadmap_package": "A08",
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "accountable_owner_role": "platform",
        "risk_class": "R2",
        "observation_schema_version": 1,
    }
    for key, expected in expected_scalars.items():
        if program_document.get(key) != expected:
            raise ProgramGovernanceError([f"{path}: {key} must be {expected!r}"])
    gate_ids = _require_strings(
        program_document.get("applicable_gate_ids"), context="applicable_gate_ids"
    )
    if gate_ids != APPLICABLE_GATE_IDS:
        raise ProgramGovernanceError([f"{path}: applicable gates must be {APPLICABLE_GATE_IDS!r}"])
    roadmap_path = _require_string(program_document, "roadmap_path", context=str(path))
    roadmap_file = _require_repository_file(
        roadmap_path,
        repository_root=resolved_repository_root,
        context="roadmap_path",
    )
    packages = load_roadmap(roadmap_file)
    ownership_path = (
        resolved_repository_root / "docs" / "governance" / "domain-ownership.toml"
        if ownership_register_path is None
        else ownership_register_path
    )
    ownership_roles = _ownership_roles(ownership_path)
    package_states = _parse_package_states(
        program_document.get("package_states"),
        repository_root=resolved_repository_root,
        ownership_roles=ownership_roles,
    )
    metrics = tuple(
        _parse_metric(entry, index=index, ownership_roles=ownership_roles)
        for index, entry in enumerate(
            _require_table_list(program_document.get("metrics"), context="metrics"), 1
        )
    )
    if tuple(metric.metric_id for metric in metrics) != METRIC_IDS:
        raise ProgramGovernanceError(["metrics must declare the seven blueprint KPIs in order"])
    if len({metric.source_event_type for metric in metrics}) != len(metrics):
        raise ProgramGovernanceError(["each KPI must use a distinct source event type"])
    finding_ids = _parse_findings(program_document.get("findings"))
    declared_findings = _require_strings(
        program_document.get("open_finding_ids"), context="open_finding_ids"
    )
    if finding_ids != _EXPECTED_FINDING_IDS or declared_findings != finding_ids:
        raise ProgramGovernanceError(["A08 partial status requires the exact open findings"])
    local_evidence_manifest_path = _require_string(
        program_document, "local_evidence_manifest_path", context=str(path)
    )
    _require_repository_file(
        local_evidence_manifest_path,
        repository_root=resolved_repository_root,
        context="local_evidence_manifest_path",
    )
    local_evidence_commit_sha = _require_string(
        program_document, "local_evidence_commit_sha", context=str(path)
    )
    if _REVISION.fullmatch(local_evidence_commit_sha) is None:
        raise ProgramGovernanceError(["local_evidence_commit_sha must be a full digest"])
    return ProgramGovernance(
        schema_version=cast(int, program_document["schema_version"]),
        roadmap_package=cast(str, program_document["roadmap_package"]),
        operating_track=cast(str, program_document["operating_track"]),
        package_status=cast(str, program_document["package_status"]),
        accountable_owner_role=cast(str, program_document["accountable_owner_role"]),
        risk_class=cast(str, program_document["risk_class"]),
        applicable_gate_ids=gate_ids,
        as_of_date=_parse_iso_date(
            _require_string(program_document, "as_of_date", context=str(path)),
            context="as_of_date",
        ),
        roadmap_path=roadmap_path,
        observation_schema_version=cast(int, program_document["observation_schema_version"]),
        maximum_observations=_require_positive_integer(
            program_document, "maximum_observations", context=str(path)
        ),
        aggregation_workload_budget_ms=_require_positive_integer(
            program_document, "aggregation_workload_budget_ms", context=str(path)
        ),
        local_evidence_manifest_path=local_evidence_manifest_path,
        local_evidence_commit_sha=local_evidence_commit_sha,
        packages=packages,
        package_states=package_states,
        metrics=metrics,
        finding_ids=finding_ids,
    )


def load_program(
    path: Path,
    *,
    repository_root: Path,
    ownership_register_path: Path | None = None,
) -> ProgramGovernance:
    """Load program governance while preserving its public domain-error contract."""
    try:
        return _load_program(
            path,
            repository_root=repository_root,
            ownership_register_path=ownership_register_path,
        )
    except ValidationError as error:
        raise ProgramGovernanceError([f"{path}: program model validation failed"]) from error


def _load_observations(path: Path, *, program: ProgramGovernance) -> tuple[MetricObservation, ...]:
    """Load strict JSONL events and deduplicate identical retries by event ID."""
    if path.stat().st_size > _MAX_OBSERVATION_FILE_BYTES:
        raise ProgramGovernanceError(["observation input exceeds the governed byte limit"])
    metrics_by_id = {metric.metric_id: metric for metric in program.metrics}
    event_documents_by_id: dict[str, dict[str, object]] = {}
    observations: list[MetricObservation] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        context = f"{path}:{line_number}"
        event_document = _load_json_line(line, context=context)
        metric_id = _require_string(event_document, "metric_id", context=context)
        if metric_id not in metrics_by_id:
            raise ProgramGovernanceError([f"{context}: unsupported metric {metric_id!r}"])
        metric = metrics_by_id[metric_id]
        expected_keys = set(_OBSERVATION_COMMON_KEYS)
        if metric.value_kind == "ratio":
            expected_keys.update({"denominator", "denominator_unit", "numerator", "numerator_unit"})
        if set(event_document) != expected_keys:
            raise ProgramGovernanceError([f"{context}: observation has missing or unknown fields"])
        if event_document.get("schema_version") != program.observation_schema_version:
            raise ProgramGovernanceError([f"{context}: unsupported observation schema version"])
        event_id = _require_string(event_document, "event_id", context=context)
        if _EVENT_ID.fullmatch(event_id) is None:
            raise ProgramGovernanceError([f"{context}.event_id is malformed"])
        previous_event_document = event_documents_by_id.get(event_id)
        if previous_event_document is not None:
            if previous_event_document != event_document:
                raise ProgramGovernanceError([f"{context}: conflicting duplicate event {event_id}"])
            continue
        event_documents_by_id[event_id] = event_document
        source_event_type = _require_string(event_document, "source_event_type", context=context)
        if source_event_type != metric.source_event_type:
            raise ProgramGovernanceError([f"{context}: source event type does not match KPI"])
        source_revision = _require_string(event_document, "source_revision", context=context)
        if _REVISION.fullmatch(source_revision) is None:
            raise ProgramGovernanceError([f"{context}.source_revision must be a full digest"])
        window_start = _parse_utc_datetime(
            _require_string(event_document, "window_start", context=context),
            context=f"{context}.window_start",
        )
        window_end = _parse_utc_datetime(
            _require_string(event_document, "window_end", context=context),
            context=f"{context}.window_end",
        )
        if window_end <= window_start:
            raise ProgramGovernanceError([f"{context}: observation window must be positive"])
        if metric.value_kind == "ratio" and window_end - window_start > timedelta(
            days=int(metric.window[1:-1])
        ):
            raise ProgramGovernanceError(
                [f"{context}: ratio observation exceeds its governed reporting window"]
            )
        dimensions_table = _require_table(
            event_document.get("dimensions"), context=f"{context}.dimensions"
        )
        if set(dimensions_table) != set(metric.required_dimensions):
            raise ProgramGovernanceError([f"{context}: dimensions do not match KPI contract"])
        if not all(
            isinstance(value, str) and _DIMENSION_VALUE.fullmatch(value) is not None
            for value in dimensions_table.values()
        ):
            raise ProgramGovernanceError(
                [f"{context}: dimension values must use the bounded safe representation"]
            )
        numerator: float | None = None
        denominator: float | None = None
        if metric.value_kind == "ratio":
            numerator = _require_number(event_document, "numerator", context=context)
            denominator = _require_number(event_document, "denominator", context=context)
            if numerator < 0 or denominator <= 0:
                raise ProgramGovernanceError(
                    [f"{context}: ratio numerator must be non-negative and denominator positive"]
                )
            if metric.bounded_ratio and numerator > denominator:
                raise ProgramGovernanceError([f"{context}: bounded numerator exceeds denominator"])
            if (
                _require_string(event_document, "numerator_unit", context=context)
                != metric.numerator_unit
            ):
                raise ProgramGovernanceError([f"{context}: numerator unit does not match KPI"])
            if (
                _require_string(event_document, "denominator_unit", context=context)
                != metric.denominator_unit
            ):
                raise ProgramGovernanceError([f"{context}: denominator unit does not match KPI"])
        source_run_id = _require_string(event_document, "source_run_id", context=context)
        if _EVENT_ID.fullmatch(source_run_id) is None:
            raise ProgramGovernanceError([f"{context}.source_run_id is malformed"])
        observations.append(
            MetricObservation(
                event_id=event_id,
                metric_id=metric_id,
                source_event_type=source_event_type,
                source_run_id=source_run_id,
                source_revision=source_revision,
                evidence_url=_require_https_url(
                    _require_string(event_document, "evidence_url", context=context),
                    context=f"{context}.evidence_url",
                ),
                window_start=window_start,
                window_end=window_end,
                dimensions=tuple(sorted(cast(dict[str, str], dimensions_table).items())),
                numerator=numerator,
                denominator=denominator,
            )
        )
        if len(observations) > program.maximum_observations:
            raise ProgramGovernanceError(["observation input exceeds the governed maximum"])
    previous_end: dict[tuple[str, tuple[tuple[str, str], ...]], datetime] = {}
    for observation in sorted(
        observations,
        key=lambda item: (item.metric_id, item.dimensions, item.window_start, item.event_id),
    ):
        metric = metrics_by_id[observation.metric_id]
        if metric.value_kind != "ratio":
            continue
        observation_key = (observation.metric_id, observation.dimensions)
        previous_window_end = previous_end.get(observation_key)
        if previous_window_end is not None and observation.window_start < previous_window_end:
            raise ProgramGovernanceError(
                [f"{path}: overlapping ratio observations would double count evidence"]
            )
        previous_end[observation_key] = observation.window_end
    return tuple(observations)


def load_observations(path: Path, *, program: ProgramGovernance) -> tuple[MetricObservation, ...]:
    """Load KPI events while preserving their public domain-error contract."""
    try:
        return _load_observations(path, program=program)
    except ValidationError as error:
        raise ProgramGovernanceError([f"{path}: observation model validation failed"]) from error


def _validate_local_evidence(repository_root: Path, program: ProgramGovernance) -> None:
    if _REVISION.fullmatch(program.local_evidence_commit_sha) is None:
        raise ProgramGovernanceError(["A08 local evidence commit SHA must be full length"])
    try:
        change_policy = load_change_risk_policy(
            repository_root / "docs" / "governance" / "change-risk-policy.toml"
        )
        manifest = validate_manifest(
            repository_root / program.local_evidence_manifest_path,
            expected_commit_sha=program.local_evidence_commit_sha,
            change_policy=change_policy,
        )
    except (OSError, ValueError) as error:
        raise ProgramGovernanceError([f"A08 local evidence bundle: {error}"]) from error
    try:
        validate_package_evidence(manifest, _LOCAL_EVIDENCE_PROFILE)
    except EvidenceGovernanceError as error:
        raise ProgramGovernanceError(error.findings) from error


def validate_repository(repository_root: Path) -> ProgramGovernance:
    """Validate the authoritative program contract, graph, and synthetic evidence."""
    resolved_repository_root = repository_root.resolve()
    program = load_program(
        resolved_repository_root / "docs" / "governance" / "program-governance.toml",
        repository_root=resolved_repository_root,
    )
    _validate_local_evidence(resolved_repository_root, program)
    return program
