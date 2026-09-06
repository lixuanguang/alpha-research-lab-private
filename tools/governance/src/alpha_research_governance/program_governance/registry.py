"""Validate the program roadmap, KPIs, and observations strictly."""

from __future__ import annotations

# standard library imports
import json
import re
import tomllib
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Literal, cast
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
from alpha_research_governance.operating_model import (
    GovernanceStatus,
    ImplementationStatus,
    OperatingModel,
    OperatingModelError,
    load_operating_model,
)
from alpha_research_governance.program_governance.models import (
    FindingDispositionGroup,
    MetricDefinition,
    MetricObservation,
    PackageNode,
    PackageState,
    ProgramGovernance,
    ProgramGovernanceError,
)

ROADMAP_PACKAGE_IDS = tuple(
    f"{wave}{number:02d}" for wave in "ABCDEFGHIJKL" for number in range(1, 9)
)
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

_PROGRAM_GOVERNANCE_OPEN_FINDING_IDS = ("A08-F01", "A08-F02", "A08-F03")
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
    expected_finding_ids=_PROGRAM_GOVERNANCE_OPEN_FINDING_IDS,
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
_ROOT_KEYS_V4 = _ROOT_KEYS | {"finding_dispositions", "generated_status_path"}
_STATE_KEYS = {
    "deferred_evidence_classes",
    "evidence_paths",
    "open_finding_ids",
    "owner_role",
    "package_id",
    "repository_local_status",
    "status",
}
_STATE_V2_KEYS = _STATE_KEYS | {"implementation_status", "domain_id", "technical_finding_ids"}
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
_FINDING_DISPOSITIONS = ("technical", "operation_prerequisite", "role_handover")
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
    """Require a parsed value to be a table or object.

    Check only the dictionary shape. The TOML or JSON parser supplies string-key typing;
    return the original mapping without copying it.

    Args:
        value: Parsed TOML or JSON value to inspect.
        context: Diagnostic location to include in a validation error.

    Returns:
        The original dictionary, cast to the parser-boundary mapping type.

    Raises:
        ProgramGovernanceError: If ``value`` is not a dictionary.
    """
    if not isinstance(value, dict):
        raise ProgramGovernanceError([f"{context} must be a table or object"])
    return cast(dict[str, object], value)


def _require_table_list(value: object, *, context: str) -> list[dict[str, object]]:
    """Require a parsed value to be a list of tables or objects.

    Check only the list and element dictionary shapes. The parser supplies string-key typing;
    preserve the original list and element mappings without copying them. Empty lists are
    accepted.

    Args:
        value: Parsed TOML or JSON value to inspect.
        context: Diagnostic location to include in a validation error.

    Returns:
        The original list, cast to the parser-boundary mapping type.

    Raises:
        ProgramGovernanceError: If ``value`` is not a list or any element is not a dictionary.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProgramGovernanceError([f"{context} must be an array of tables"])
    return cast(list[dict[str, object]], value)


def _require_string(table: dict[str, object], key: str, *, context: str) -> str:
    """Require a named table field to contain a non-blank string.

    Reject missing, non-string, and whitespace-only values. Preserve surrounding whitespace in
    an accepted value and do not normalize the table or field name.

    Args:
        table: Mapping containing the field to inspect.
        key: Field name to retrieve with ``dict.get``.
        context: Diagnostic location to include in a validation error.

    Returns:
        The original string value, including any surrounding whitespace.

    Raises:
        ProgramGovernanceError: If the field is missing, is not a string, or is blank.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProgramGovernanceError([f"{context}.{key} must be a non-empty string"])
    return value


def _require_strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Require an ordered list of unique non-empty strings.

    Preserve item text and order without stripping it. Reject exact empty strings while accepting
    whitespace-only strings. Control whether an empty list is valid with ``allow_empty``.

    Args:
        value: Parsed value expected to be a list of strings.
        context: Diagnostic location to include in a validation error.
        allow_empty: Permit an empty list when ``True``; reject it otherwise.

    Returns:
        A tuple containing the original strings in their original order.

    Raises:
        ProgramGovernanceError: If ``value`` is not a list of strings, contains an exact empty
            string, is empty when disallowed, or contains duplicate strings.
    """
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProgramGovernanceError([f"{context} must be an array of non-empty strings"])
    string_values = tuple(cast(list[str], value))
    if not allow_empty and not string_values:
        raise ProgramGovernanceError([f"{context} must not be empty"])
    if len(string_values) != len(set(string_values)):
        raise ProgramGovernanceError([f"{context} must contain unique values"])
    return string_values


def _require_positive_integer(table: dict[str, object], key: str, *, context: str) -> int:
    """Require a table field to contain a positive integer.

    Reject booleans even though Python treats them as integers.

    Args:
        table: Mapping containing the field to inspect.
        key: Field name to retrieve with ``dict.get``.
        context: Diagnostic location to include in a validation error.

    Returns:
        The stored integer value.

    Raises:
        ProgramGovernanceError: If the field is missing, is not an integer, is a boolean, or is
            less than one.
    """
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProgramGovernanceError([f"{context}.{key} must be a positive integer"])
    return value


def _require_number(table: dict[str, object], key: str, *, context: str) -> float:
    """Require a table field to contain a finite number.

    Accept integers and floats but reject booleans. Convert accepted values to ``float`` before
    checking finiteness; converting an integer too large for ``float`` can raise ``OverflowError``.

    Args:
        table: Mapping containing the field to inspect.
        key: Field name to retrieve with ``dict.get``.
        context: Diagnostic location to include in a validation error.

    Returns:
        The finite floating-point representation of the stored number.

    Raises:
        ProgramGovernanceError: If the field is missing, has another type, is a boolean, or is
            non-finite after conversion.
        OverflowError: If converting an excessively large integer to ``float`` overflows.
    """
    value = table.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ProgramGovernanceError([f"{context}.{key} must be a finite number"])
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise ProgramGovernanceError([f"{context}.{key} must be a finite number"])
    return numeric_value


def _parse_optional_number(table: dict[str, object], key: str, *, context: str) -> float | None:
    """Parse an optional finite numeric field.

    Treat an absent key as ``None``. Validate a present key through ``_require_number``, so an
    explicit ``None`` is invalid and large-integer conversion may propagate ``OverflowError``.

    Args:
        table: Mapping containing the optional field.
        key: Field name whose presence controls optionality.
        context: Diagnostic location to include in a validation error.

    Returns:
        ``None`` when ``key`` is absent; otherwise the validated finite float.

    Raises:
        ProgramGovernanceError: If a present field is not a finite number or is a boolean.
        OverflowError: If a present integer is too large to convert to ``float``.
    """
    return None if key not in table else _require_number(table, key, context=context)


def _parse_iso_date(value: str, *, context: str) -> date:
    """Parse a date that round-trips exactly as ``YYYY-MM-DD``.

    Require the extended calendar spelling after parsing, even when ``date.fromisoformat`` accepts
    another ISO spelling.

    Args:
        value: Date text to parse and compare with the parsed date's ISO text.
        context: Diagnostic location to include in a validation error.

    Returns:
        The parsed ``date`` value.

    Raises:
        ProgramGovernanceError: If parsing fails or the parsed date does not round-trip exactly as
            ``value``; parsing ``ValueError`` instances are preserved as causes.
    """
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError as error:
        raise ProgramGovernanceError([f"{context} must use YYYY-MM-DD"]) from error
    if parsed_date.isoformat() != value:
        raise ProgramGovernanceError([f"{context} must use YYYY-MM-DD"])
    return parsed_date


def _parse_utc_datetime(value: str, *, context: str) -> datetime:
    """Parse a UTC timestamp whose final character is ``Z``.

    Replace the required final ``Z`` with ``+00:00`` and accept spellings that
    ``datetime.fromisoformat`` parses with UTC timezone information. Do not require a canonical
    timestamp spelling.

    Args:
        value: ISO timestamp text ending in ``Z``.
        context: Diagnostic location to include in a validation error.

    Returns:
        The parsed timezone-aware ``datetime`` with the UTC timezone.

    Raises:
        ProgramGovernanceError: If ``value`` lacks the final ``Z``, cannot be parsed, or is not
            UTC; parsing ``ValueError`` instances are preserved as causes.
    """
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
    """Load a UTF-8 TOML file and require a table at its root.

    Preserve the parser's values without copying or normalizing them.

    Args:
        path: TOML file to read.

    Returns:
        The parser's top-level mapping.

    Raises:
        ProgramGovernanceError: If TOML decoding fails or the parsed root is not a dictionary;
            decoding errors are preserved as causes.
        OSError: If reading the file fails.
        UnicodeDecodeError: If the file is not valid UTF-8.
    """
    try:
        parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ProgramGovernanceError([f"{path}: invalid TOML: {error}"]) from error
    return _require_table(parsed_document, context=str(path))


def _load_json_line(line: str, *, context: str) -> dict[str, object]:
    """Parse JSON text and require an object at its root.

    Reject duplicate object keys at every nesting depth through the parser hook. Preserve the
    standard parser's handling of non-finite constants, and perform no I/O or physical line-count
    check on the supplied text.

    Args:
        line: JSON text supplied by the caller, normally one observation line.
        context: Diagnostic location to include in a validation error.

    Returns:
        The parser-built top-level object mapping.

    Raises:
        ProgramGovernanceError: If JSON syntax is invalid, any object has a duplicate key, or the
            parsed root is not a dictionary; syntax errors are preserved as causes.
        ValueError: If an integer token exceeds the interpreter's enabled conversion limit.
        RecursionError: If JSON nesting exceeds the decoder's recursion limit.
    """

    def build_json_object_rejecting_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        """Build one JSON object while rejecting duplicate keys.

        Apply this hook to every object produced by ``json.loads`` and preserve the decoder's
        key order in the new dictionary.

        Args:
            pairs: Object key-value pairs in decoder encounter order.

        Returns:
            A new dictionary containing the supplied pairs.

        Raises:
            ProgramGovernanceError: If ``pairs`` contains a repeated key.
        """
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
    """Collect roles from the ownership register's domain fields.

    Collect accountable, required-review, independent-review, and escalation roles. Allow an
    empty result when the domains list is empty, collapse repeats across fields and domains, and
    do not validate role-token format.

    Args:
        path: UTF-8 ownership-register TOML file to read.

    Returns:
        A frozenset of collected roles, with no role order retained.

    Raises:
        ProgramGovernanceError: If TOML or any domain field has the wrong shape, or an individual
            role list contains a non-string, exact empty, or duplicate item; malformed TOML is
            translated with its cause.
        OSError: If reading the ownership register fails.
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
    return frozenset(roles)


def _require_repository_file(value: str, *, repository_root: Path, context: str) -> Path:
    """Require a repository-relative path to resolve to an in-root file.

    Require the caller to supply a resolved absolute ``repository_root``. Reject absolute paths
    and lexical ``..`` components, then follow symlinks and perform separate, non-atomic existence
    and file-type checks. Return the joined candidate without resolving it.

    Args:
        value: Repository-relative path to validate.
        repository_root: Caller-resolved absolute repository root.
        context: Diagnostic location to include in a validation error.

    Returns:
        The unresolved candidate path after strict resolution confirms in-root existence and the
        candidate identifies a file.

    Raises:
        ProgramGovernanceError: If the path is absolute, contains ``..``, is missing, resolves
            outside the root, or does not identify a file; missing and containment failures chain
            ``FileNotFoundError`` or ``ValueError``.
        OSError: If an uncaught filesystem operation fails.
        RuntimeError: If strict resolution encounters a symlink loop.
    """
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
    """Require an HTTPS URL with a non-empty host and no credentials.

    Reject non-empty query and fragment components while allowing empty ``?`` and ``#``
    delimiters. Parse only; do not access or validate the port and do not perform network I/O.

    Args:
        value: URL text to parse and validate.
        context: Diagnostic location to include in a validation error.

    Returns:
        The original URL text, without normalization.

    Raises:
        ProgramGovernanceError: If the scheme is not ``https``, the host is empty, credentials
            are present, or the query or fragment is non-empty; ``urlsplit`` ``ValueError``
            instances are preserved as causes.
    """
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
    """Expand one roadmap package ID or an inclusive package range.

    Accept waves ``A`` through ``L`` and numbers ``01`` through ``08``. Expand same-wave ranges
    directly; cross-wave ranges must cover complete waves from ``01`` through ``08``. Do not
    validate package existence in another document.

    Args:
        token: Exact package ID or hyphenated package range to expand.

    Returns:
        Package IDs in inclusive roadmap order.

    Raises:
        ProgramGovernanceError: If the token is malformed, its range is reversed, or a cross-wave
            range does not span complete waves from ``01`` through ``08``.
    """
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
    """Parse comma-separated roadmap dependency IDs and ranges.

    Treat exactly ``"-"`` as the no-dependencies sentinel. Otherwise strip each comma-separated
    token before expansion, preserve expanded order, and reject duplicates after expansion.

    Args:
        expression: Dependency expression containing the exact sentinel or comma-separated
            package IDs and ranges.

    Returns:
        Expanded package IDs in expression order, or an empty tuple for the sentinel.

    Raises:
        ProgramGovernanceError: If a stripped token is empty, a token or range is unsupported, a
            range is reversed or incomplete, or expansion repeats a package ID.
    """
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
) -> tuple[
    tuple[str, ...],
    tuple[tuple[str, ...], ...],
    tuple[str, ...],
    tuple[tuple[str, ...], ...],
    tuple[str, ...],
    tuple[tuple[str, ...], ...],
]:
    """Parse legacy or purpose-specific roadmap dependency expressions.

    Dispatch to the purpose-specific grammar only when the expression starts with
    ``implementation``, ``operation/release`` or ``team handover``, optionally followed by
    `` any of`` and then the literal ``: ``; otherwise parse a comma-separated all-of list with
    one optional ``any of`` group. Purpose-specific clauses are semicolon-separated, with one
    all-of and one any-of clause permitted per purpose. Preserve dependency order, return six
    tuples in purpose order, and validate duplicates within each list and each purpose. IDs may
    recur across different purposes, while legacy all-of/any-of overlap is accepted.

    Args:
        expression: Roadmap table dependency text, including ``-`` for no dependencies.

    Returns:
        A tuple containing all-of IDs and any-of groups for implementation, operation/release,
        and team handover, in that order. Legacy expressions populate only implementation.

    Raises:
        ProgramGovernanceError: If the expression is malformed, contains unsupported dependency
            tokens, repeats a same-purpose clause kind or package within one list, overlaps
            same-purpose all-of and any-of IDs, or uses an invalid any-of group.
    """
    purpose_match = re.match(
        r"^(?:implementation|operation/release|team handover)(?: any of)?: ", expression
    )
    if purpose_match is not None:
        requirements: dict[str, tuple[str, ...]] = {}
        any_of_requirements: dict[str, tuple[tuple[str, ...], ...]] = {}
        for clause in expression.split(";"):
            clause_match = re.fullmatch(
                r"(implementation|operation/release|team handover)( any of)?: (.+)",
                clause.strip(),
            )
            if clause_match is None:
                raise ProgramGovernanceError(
                    [f"roadmap dependency purpose is malformed: {clause.strip()}"]
                )
            raw_purpose, raw_any_of, raw_dependencies = clause_match.groups()
            purpose = raw_purpose.replace("/", "_").replace(" ", "_")
            dependencies = _parse_dependency_list(raw_dependencies.strip())
            if raw_any_of is None:
                if purpose in requirements:
                    raise ProgramGovernanceError(
                        [f"roadmap repeats {raw_purpose} dependencies: {expression}"]
                    )
                requirements[purpose] = dependencies
                continue
            if purpose in any_of_requirements:
                raise ProgramGovernanceError(
                    [f"roadmap repeats {raw_purpose} any-of dependencies: {expression}"]
                )
            if len(dependencies) < 2:
                raise ProgramGovernanceError(
                    ["any-of dependency group must contain at least two packages"]
                )
            any_of_requirements[purpose] = (dependencies,)
        for purpose, dependencies in requirements.items():
            grouped = {item for group in any_of_requirements.get(purpose, ()) for item in group}
            if set(dependencies) & grouped:
                raise ProgramGovernanceError(
                    [f"roadmap repeats a dependency across all-of and any-of: {expression}"]
                )
        return (
            requirements.get("implementation", ()),
            any_of_requirements.get("implementation", ()),
            requirements.get("operation_release", ()),
            any_of_requirements.get("operation_release", ()),
            requirements.get("team_handover", ()),
            any_of_requirements.get("team_handover", ()),
        )

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
    return dependencies, groups, (), (), (), ()


class RoadmapParser:
    """Parse and validate the repository's ordered roadmap package graph.

    The parser has no repository state and performs no work during construction. Each
    ``parse`` call reads one Markdown roadmap and keeps all graph-validation findings in
    local variables, so a failed parse cannot affect a later call.
    """

    def parse(self, path: Path) -> tuple[PackageNode, ...]:
        """Read and validate one UTF-8 roadmap document.

        Args:
            path: Markdown roadmap file to read. Relative paths are interpreted from
                the process current working directory.

        Returns:
            The 96 immutable package nodes in roadmap order.

        Raises:
            ProgramGovernanceError: If the roadmap rows, dependency expressions, package
                coverage, dependency references, or dependency graph are invalid. Package
                model failures are translated with their causes chained.
            OSError: If the roadmap cannot be read.
            UnicodeDecodeError: If the roadmap is not valid UTF-8.
        """
        try:
            packages = self._parse_rows(path.read_text(encoding="utf-8").splitlines())
        except ValidationError as error:
            raise ProgramGovernanceError([f"{path}: roadmap model validation failed"]) from error
        self._validate_graph(tuple(packages))
        return tuple(packages)

    def _parse_rows(self, lines: list[str]) -> list[PackageNode]:
        """Parse roadmap rows while preserving source order and diagnostics.

        Args:
            lines: Markdown lines read by ``parse``.

        Returns:
            Package nodes in the order declared by the roadmap.

        Raises:
            ProgramGovernanceError: If a row is malformed, outside its wave, or
                the document does not contain every expected package exactly once.
            ValidationError: If a package model rejects parsed fields.
        """
        current_wave: str | None = None
        packages: list[PackageNode] = []
        for line in lines:
            wave_match = re.fullmatch(r"## Wave ([A-L]) - .+", line)
            if wave_match is not None:
                current_wave = wave_match.groups(default="")[0]
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
            package_id, objective, library, boundary, expression = row_match.groups(default="")
            package_id = package_id.strip()
            objective = objective.strip()
            library = library.strip()
            boundary = boundary.strip()
            expression = expression.strip()
            if not library or not boundary:
                raise ProgramGovernanceError(
                    [f"{package_id}: library/tool and incorporation boundary cannot be empty"]
                )
            if current_wave != package_id[0]:
                raise ProgramGovernanceError(
                    [f"{package_id}: roadmap row is outside its Wave {package_id[0]} section"]
                )
            (
                dependencies,
                groups,
                operation_release_dependencies,
                operation_release_groups,
                team_handover_dependencies,
                team_handover_groups,
            ) = _parse_dependency_expression(expression)
            packages.append(
                PackageNode(
                    package_id=package_id,
                    wave=package_id[0],
                    objective=objective,
                    dependencies=dependencies,
                    any_of_dependency_groups=groups,
                    operation_release_dependencies=operation_release_dependencies,
                    operation_release_any_of_dependency_groups=operation_release_groups,
                    team_handover_dependencies=team_handover_dependencies,
                    team_handover_any_of_dependency_groups=team_handover_groups,
                )
            )
        if tuple(package.package_id for package in packages) != ROADMAP_PACKAGE_IDS:
            raise ProgramGovernanceError(
                ["roadmap must declare A01-L08 exactly once in dependency order"]
            )
        return packages

    def _validate_graph(self, packages: tuple[PackageNode, ...]) -> None:
        """Validate roadmap dependency references and cycles.

        Args:
            packages: Parsed package nodes whose dependency IDs form the graph.

        Raises:
            ProgramGovernanceError: If a package references an unknown package,
                depends on itself, or participates in a dependency cycle.
        """
        package_ids = frozenset(ROADMAP_PACKAGE_IDS)
        findings: list[str] = []
        for package in packages:
            referenced = package.all_dependency_ids()
            unknown = sorted(set(referenced) - package_ids)
            if unknown:
                findings.append(f"{package.package_id}: unknown dependencies {unknown!r}")
            if package.package_id in referenced:
                findings.append(f"{package.package_id}: package cannot depend on itself")
        findings.extend(_find_dependency_cycles(packages))
        if findings:
            raise ProgramGovernanceError(findings)


def _load_roadmap(path: Path) -> tuple[PackageNode, ...]:
    """Delegate roadmap loading through the compatibility parser seam.

    Args:
        path: Markdown roadmap file to read.

    Returns:
        The validated package nodes in roadmap order.

    Raises:
        ProgramGovernanceError: If roadmap validation fails; package model failures
            retain their causes through ``RoadmapParser.parse``.
        OSError: If the file cannot be read.
        UnicodeDecodeError: If the file is not valid UTF-8.
    """
    return RoadmapParser().parse(path)


def load_roadmap(path: Path) -> tuple[PackageNode, ...]:
    """Load and validate the repository roadmap as an immutable package tuple.

    Read the UTF-8 Markdown file once, scan wave headings and package rows in
    source order, parse purpose-specific dependency expressions, require all 96
    package IDs exactly once in roadmap order, then reject unknown or self
    dependencies and graph cycles. The file and parsed input are not modified.

    Args:
        path: UTF-8 Markdown roadmap file; a relative path is interpreted from
            the process current working directory.

    Returns:
        A tuple of 96 immutable ``PackageNode`` records in roadmap order, with
        all-of and any-of dependencies retaining their parsed source order for
        each supported purpose.

    Raises:
        ProgramGovernanceError: If row shape, wave placement, dependency
            syntax, package coverage, references, or graph consistency is
            invalid. Pydantic model failures are translated with their causes
            chained.
        OSError: If the roadmap file cannot be read.
        UnicodeDecodeError: If the roadmap file is not valid UTF-8.
    """
    try:
        return _load_roadmap(path)
    except ValidationError as error:
        raise ProgramGovernanceError([f"{path}: roadmap model validation failed"]) from error


def _find_dependency_cycles(packages: tuple[PackageNode, ...]) -> tuple[str, ...]:
    """Find directed dependency cycles and render their roadmap diagnostics.

    Args:
        packages: Package nodes whose IDs form graph vertices and whose combined dependency IDs
            form directed edges. Duplicate IDs use the last node's edges in the temporary graph;
            the tuple and its nodes are not modified.

    Returns:
        Unique cycle messages in depth-first traversal order, with each message prefixed by
        ``roadmap dependency cycle:``. A cycle is rendered from its first active node through
        the repeated node. Traversal mutates only its local state and cycle accumulators.

    Raises:
        KeyError: If a dependency ID is absent from ``packages`` while traversing the graph.
    """
    graph = {package.package_id: package.all_dependency_ids() for package in packages}
    states: dict[str, int] = {}
    cycles: list[str] = []

    def visit_dependency(package_id: str, trail: tuple[str, ...]) -> None:
        """Visit one dependency and record a back edge to an active ancestor.

        Update the enclosing traversal state and cycle accumulator without mutating package
        nodes.

        Args:
            package_id: Current package ID to mark or inspect in the traversal state.
            trail: Active ancestor IDs preceding ``package_id``.

        Raises:
            KeyError: If an unvisited ID is absent from the dependency graph.
        """
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
    unique_cycles: list[str] = []
    seen_cycles: set[str] = set()
    for cycle in cycles:
        if cycle in seen_cycles:
            continue
        seen_cycles.add(cycle)
        unique_cycles.append(cycle)
    return tuple(f"roadmap dependency cycle: {cycle}" for cycle in unique_cycles)


class _PackageStateParser:
    """Parse package states with bound repository, ownership, and schema context.

    Construction stores validation context without reading files or resolving operating-model
    rules. Each ``parse`` call evaluates versioned states using a fresh current date and local
    state collection, so a failed parse cannot affect a later call on the same parser.
    """

    def __init__(
        self,
        *,
        repository_root: Path,
        ownership_roles: frozenset[str],
        schema_version: int,
        operating_model: OperatingModel | None,
    ) -> None:
        """Bind context used to validate package-state records.

        Args:
            repository_root: Resolved repository root used to validate and read evidence paths.
            ownership_roles: Role names permitted in package-state records.
            schema_version: Program schema version controlling accepted fields and legacy rules.
            operating_model: Operating model required for schema versions 2 through 4; ignored
                for schema version 1.
        """
        self._repository_root = repository_root
        self._ownership_roles = ownership_roles
        self._schema_version = schema_version
        self._operating_model = operating_model

    def parse(self, value: object) -> tuple[PackageState, ...]:
        """Parse and validate package-state records in source order.

        Read each referenced evidence file as UTF-8 for schemas before version 4; schema 4
        requires exactly one existing ``.md`` path but does not read it here. Resolve
        implementation governance on the current date for versioned states. Schemas below 3
        require a contiguous roadmap prefix including A08; schemas 3 and 4 require an ordered
        subset including A08.

        Args:
            value: Parsed ``package_states`` value expected to be a list of tables.

        Returns:
            Validated package states in source order, with versioned governance fields resolved.

        Raises:
            ProgramGovernanceError: If records, paths, findings, statuses, ordering, or required
                operating-model input violate the selected schema contract.
            OSError: If an uncaught evidence-file operation fails.
            UnicodeDecodeError: If a legacy evidence file is not valid UTF-8.
            OperatingModelError: If the operating model cannot resolve a versioned state.
            ValidationError: If constructing a package-state model rejects a parsed value.
        """
        evaluation_date = date.today()
        states = [
            self._parse_record(entry, index=index, evaluation_date=evaluation_date)
            for index, entry in enumerate(_require_table_list(value, context="package_states"), 1)
        ]
        self._validate_ordering(states)
        return tuple(states)

    def _parse_record(
        self,
        entry: dict[str, object],
        *,
        index: int,
        evaluation_date: date,
    ) -> PackageState:
        """Validate one package-state record and construct its immutable model.

        Args:
            entry: Parsed package-state table.
            index: One-based source position used in diagnostics.
            evaluation_date: Date used to resolve versioned operating rules.

        Returns:
            The validated package-state model for ``entry``.

        Raises:
            ProgramGovernanceError: If record fields, evidence, or versioned state rules fail.
            OSError: If an uncaught legacy evidence-file operation fails.
            UnicodeDecodeError: If a legacy evidence file is not valid UTF-8.
            OperatingModelError: If the operating model cannot resolve a versioned state.
            ValidationError: If constructing the package-state model rejects a parsed value.
        """
        context = f"package_states[{index}]"
        if set(entry) != (_STATE_KEYS if self._schema_version == 1 else _STATE_V2_KEYS):
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
        if self._schema_version >= 4 and (
            len(evidence_paths) != 1 or not evidence_paths[0].endswith(".md")
        ):
            raise ProgramGovernanceError(
                [f"{context}: current state must name exactly one Markdown capability contract"]
            )
        finding_ids = _require_strings(
            entry.get("open_finding_ids"),
            context=f"{context}.open_finding_ids",
            allow_empty=self._schema_version >= 2,
        )
        if package_id not in ROADMAP_PACKAGE_IDS:
            raise ProgramGovernanceError([f"{context}.package_id is unsupported"])
        if status != "partial":
            raise ProgramGovernanceError(
                [f"{context}: solo-bootstrap implemented packages must remain partial"]
            )
        if self._schema_version == 1 and repository_local_status != "passed":
            raise ProgramGovernanceError(
                [f"{context}: implemented dependencies require passing repository-local evidence"]
            )
        if owner_role not in self._ownership_roles:
            raise ProgramGovernanceError([f"{context}: stale owner role {owner_role!r}"])
        invalid_classes = sorted(set(deferred_classes) - _ALLOWED_DEFERRED_CLASSES)
        if invalid_classes or (self._schema_version == 1 and not deferred_classes):
            raise ProgramGovernanceError(
                [f"{context}: deferred evidence classes must be recognized and non-empty"]
            )
        if any(not finding.startswith(f"{package_id}-F") for finding in finding_ids):
            raise ProgramGovernanceError([f"{context}: finding IDs must belong to {package_id}"])
        self._validate_evidence(
            evidence_paths=evidence_paths,
            finding_ids=finding_ids,
            context=context,
        )
        implementation_status = "complete"
        domain_id: str | None = None
        technical_findings: tuple[str, ...] = ()
        governance_status: GovernanceStatus = "pending"
        assigned_reviewers: tuple[str, ...] = ()
        if self._schema_version >= 2:
            (
                implementation_status,
                domain_id,
                technical_findings,
                governance_status,
                assigned_reviewers,
            ) = self._parse_versioned_state(
                entry,
                context=context,
                repository_local_status=repository_local_status,
                evaluation_date=evaluation_date,
            )
        return PackageState(
            package_id=package_id,
            status=status,
            owner_role=owner_role,
            repository_local_status=repository_local_status,
            deferred_evidence_classes=deferred_classes,
            evidence_paths=evidence_paths,
            open_finding_ids=finding_ids,
            implementation_status=cast(ImplementationStatus, implementation_status),
            domain_id=domain_id,
            technical_finding_ids=technical_findings,
            governance_status=governance_status,
            assigned_reviewers=assigned_reviewers,
        )

    def _validate_evidence(
        self,
        *,
        evidence_paths: tuple[str, ...],
        finding_ids: tuple[str, ...],
        context: str,
    ) -> None:
        """Validate evidence paths and retain required findings for legacy schemas.

        Args:
            evidence_paths: Repository-relative evidence paths from one state.
            finding_ids: Open finding IDs that legacy evidence must contain.
            context: Record context used in path and finding diagnostics.

        Raises:
            ProgramGovernanceError: If an evidence path is unsafe, nonexistent, or not a file,
                or a legacy file omits a finding.
            OSError: If an uncaught evidence-file operation fails.
            UnicodeDecodeError: If a legacy evidence file is not valid UTF-8.
        """
        evidence_files = tuple(
            _require_repository_file(path, repository_root=self._repository_root, context=context)
            for path in evidence_paths
        )
        if self._schema_version < 4:
            evidence_text = "\n".join(
                evidence_file.read_text(encoding="utf-8") for evidence_file in evidence_files
            )
            missing_findings = [finding for finding in finding_ids if finding not in evidence_text]
            if missing_findings:
                raise ProgramGovernanceError(
                    [f"{context}: evidence paths do not retain findings {missing_findings!r}"]
                )

    def _parse_versioned_state(
        self,
        entry: dict[str, object],
        *,
        context: str,
        repository_local_status: str,
        evaluation_date: date,
    ) -> tuple[str, str, tuple[str, ...], GovernanceStatus, tuple[str, ...]]:
        """Resolve and validate schema-2-through-4 implementation governance fields.

        Args:
            entry: Parsed package-state table.
            context: Record context used in diagnostics.
            repository_local_status: Repository-local evidence status already parsed from the
                record.
            evaluation_date: Date used to resolve the effective operating rules.

        Returns:
            Parsed implementation status, domain ID, and technical finding IDs, followed by the
            governance status and assigned reviewers resolved by the operating model. The
            implementation-status membership is checked during ``PackageState`` construction.

        Raises:
            ProgramGovernanceError: If versioned fields or completion dependencies are invalid.
            OperatingModelError: If the operating model cannot resolve the domain and operation
                or the resolved rules reject local completion.
        """
        domain_id = _require_string(entry, "domain_id", context=context)
        implementation_status = _require_string(entry, "implementation_status", context=context)
        technical_findings = _require_strings(
            entry.get("technical_finding_ids"),
            context=f"{context}.technical_finding_ids",
            allow_empty=True,
        )
        if repository_local_status not in {"not_started", "passed", "failed"}:
            raise ProgramGovernanceError([f"{context}: invalid repository_local_status"])
        if self._operating_model is None:
            raise ProgramGovernanceError(["versioned states require the operating model"])
        rules = self._operating_model.resolve(
            domain_id=domain_id, operation="implementation", on_date=evaluation_date
        )
        if implementation_status == "complete":
            rules.require_local_completion(
                repository_local_status=repository_local_status,
                technical_finding_ids=technical_findings,
            )
        if repository_local_status == "failed" and implementation_status != "blocked":
            raise ProgramGovernanceError([f"{context}: failed local evidence requires blocked"])
        if technical_findings and implementation_status != "blocked":
            raise ProgramGovernanceError([f"{context}: technical findings require blocked"])
        return (
            implementation_status,
            domain_id,
            technical_findings,
            rules.governance_status,
            rules.assigned_reviewers,
        )

    def _validate_ordering(self, states: list[PackageState]) -> None:
        """Validate schema-specific package-state order and required A08 coverage.

        Args:
            states: Parsed package states in their source order.

        Raises:
            ProgramGovernanceError: If states are not the required contiguous prefix or ordered
                unique subset for the selected schema.
        """
        state_ids = tuple(state.package_id for state in states)
        if self._schema_version < 3 and (
            state_ids != ROADMAP_PACKAGE_IDS[: len(state_ids)] or "A08" not in state_ids
        ):
            raise ProgramGovernanceError(
                ["package_states must be a contiguous implemented prefix including A01-A08"]
            )
        expected_state_order = tuple(
            package_id for package_id in ROADMAP_PACKAGE_IDS if package_id in set(state_ids)
        )
        if self._schema_version >= 3 and (
            state_ids != expected_state_order
            or len(state_ids) != len(set(state_ids))
            or "A08" not in state_ids
        ):
            raise ProgramGovernanceError(
                ["package_states must be unique, in roadmap order, and include A08"]
            )


def _parse_metric(
    entry: dict[str, object],
    *,
    index: int,
    ownership_roles: frozenset[str],
) -> MetricDefinition:
    """Parse one KPI definition and enforce its measurement contract.

    Validate field names, ownership, value-kind and aggregation combinations, units, dimensions,
    automatic collection, positive scale and window, nonnegative baseline/target coupling, and
    bounded values. Validate approved-target evidence URL syntax without checking the approval.

    Args:
        entry: Parsed metric table to validate.
        index: One-based source index used in diagnostic context.
        ownership_roles: Role names permitted as metric owners.

    Returns:
        A validated ``MetricDefinition`` retaining the parsed values and optional target data.

    Raises:
        ProgramGovernanceError: If fields are missing or unknown, values violate the KPI
            contract, or an approved target lacks its value or HTTPS evidence. URL parser
            ``ValueError`` instances are translated to this error.
        OverflowError: If a numeric input is too large to convert to ``float``.
        ValidationError: If constructing a ``MetricDefinition`` rejects a parsed value.
    """
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
    if any(package not in ROADMAP_PACKAGE_IDS for package in producer_packages):
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
    """Parse finding records and return their identifiers in source order.

    Require each table to contain exactly the four finding fields and each field to be a
    non-blank string. Preserve duplicate identifiers because this parser does not deduplicate or
    cross-check them against package state.

    Args:
        value: Parsed ``findings`` value expected to be a list of tables.

    Returns:
        Finding IDs in input order, including any duplicates supplied by the input.

    Raises:
        ProgramGovernanceError: If the value is not a table list or a finding has missing,
            unknown, or blank fields.
    """
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


def _parse_finding_dispositions(
    value: object,
    *,
    package_states: tuple[PackageState, ...],
) -> tuple[FindingDispositionGroup, ...]:
    """Parse ordered finding-disposition groups and cover active historical findings.

    Require technical, operation-prerequisite, and role-handover groups in that exact order;
    permit an empty technical group, reject duplicate mappings, and require every active finding
    in ``package_states`` to appear in a group.

    Args:
        value: Parsed ``finding_dispositions`` value expected to be a list of tables.
        package_states: Package states whose active historical findings must be mapped.

    Returns:
        Disposition groups in their required source order, retaining each group's finding-ID
        order. Mapped IDs that are not currently active are retained.

    Raises:
        ProgramGovernanceError: If group fields, dispositions, required ordering, uniqueness, or
            active-finding coverage is invalid.
    """
    groups: list[FindingDispositionGroup] = []
    mapped_ids: list[str] = []
    for index, entry in enumerate(_require_table_list(value, context="finding_dispositions"), 1):
        context = f"finding_dispositions[{index}]"
        if set(entry) != {"disposition", "finding_ids"}:
            raise ProgramGovernanceError([f"{context} has missing or unknown fields"])
        disposition = _require_string(entry, "disposition", context=context)
        if disposition not in _FINDING_DISPOSITIONS:
            raise ProgramGovernanceError([f"{context}.disposition is unsupported"])
        finding_ids = _require_strings(
            entry.get("finding_ids"),
            context=f"{context}.finding_ids",
            allow_empty=disposition == "technical",
        )
        mapped_ids.extend(finding_ids)
        groups.append(
            FindingDispositionGroup(
                disposition=cast(
                    Literal["technical", "operation_prerequisite", "role_handover"],
                    disposition,
                ),
                finding_ids=finding_ids,
            )
        )
    if tuple(group.disposition for group in groups) != _FINDING_DISPOSITIONS:
        raise ProgramGovernanceError(
            ["finding dispositions must declare technical, operation, and role groups in order"]
        )
    if len(mapped_ids) != len(set(mapped_ids)):
        raise ProgramGovernanceError(["historical finding IDs must have one disposition"])
    active_ids = {finding_id for state in package_states for finding_id in state.open_finding_ids}
    missing_ids = sorted(active_ids - set(mapped_ids))
    if missing_ids:
        raise ProgramGovernanceError(
            [f"active historical findings lack a migration disposition: {missing_ids!r}"]
        )
    return tuple(groups)


class ProgramRepository:
    """Load program governance with an explicit repository and ownership context.

    Construction stores path context and creates no files, reads no policy, and performs no
    validation. Each operation allocates its own parsed documents, findings, and dependency
    state. A failed load or validation therefore cannot contaminate a later call on the same
    repository instance.
    """

    def __init__(
        self,
        repository_root: Path,
        ownership_register_path: Path | None = None,
    ) -> None:
        """Bind repository-relative and ownership-register path context.

        Args:
            repository_root: Repository root used for relative roadmap, evidence, and
                generated-status paths. It is resolved when an operation starts.
            ownership_register_path: Optional ownership TOML path. ``None`` selects
                ``docs/governance/domain-ownership.toml`` below the resolved root;
                a supplied relative path remains process-relative.
        """
        self._repository_root = repository_root
        self._ownership_register_path = ownership_register_path
        self._roadmap_parser = RoadmapParser()

    def load_program(self, path: Path) -> ProgramGovernance:
        """Load one validated program-governance TOML document.

        Resolve the bound repository root, validate fixed A08 scalars and the selected schema
        version, parse the ordered roadmap, load ownership roles and versioned operating rules,
        validate package states and schema-4 finding dispositions, then parse metrics and finding
        IDs in source order. Validate evidence paths, the full commit digest, and a schema-4
        generated-status parent before constructing the immutable model and checking complete
        implementation states against technical dependencies. Versioned package-state rules use
        ``date.today()``; the recorded ``as_of_date`` remains metadata. Schemas 1 through 3 read
        package-state evidence as UTF-8 and check finding IDs; schema 4 checks one existing
        Markdown path per state without reading it. Local evidence and generated-status contents
        are checked only by ``validate_repository``. All reads and path checks are read-only.

        Args:
            path: UTF-8 TOML program record. Relative paths are interpreted from the
                process current working directory.

        Returns:
            The immutable program record with schema-specific package states, metrics,
            findings, and dependency readiness validated.

        Raises:
            ProgramGovernanceError: If policy structure, schema 1-4 content, ownership,
                roadmap, evidence path, operating model, metrics, findings, or model
                validation fails. Model and operating-model failures are translated with
                their causes chained.
            OSError: If an uncaught input file operation fails.
            UnicodeDecodeError: If an uncaught UTF-8 read fails.
            RuntimeError: If strict path resolution encounters a symlink loop.
            OverflowError: If a metric integer is too large for ``float`` conversion.
        """
        try:
            return self._load_program(path)
        except OperatingModelError as error:
            raise ProgramGovernanceError([str(error)]) from error
        except ValidationError as error:
            raise ProgramGovernanceError([f"{path}: program model validation failed"]) from error

    def _load_program(self, path: Path) -> ProgramGovernance:
        """Run the ordered program-loading workflow for one TOML document.

        Args:
            path: Program-governance TOML path to parse.

        Returns:
            The assembled immutable program record after all schema and dependency checks.

        Raises:
            ProgramGovernanceError: If any owned policy, path, state, metric, finding, or
                dependency invariant fails.
            OSError: If an uncaught input file operation fails.
            UnicodeDecodeError: If an uncaught UTF-8 read fails.
            ValidationError: If the assembled Pydantic model rejects the record; the public
                method translates this error with the program path as context.
            OperatingModelError: If an operating rule cannot be resolved; the public method
                translates this error to a governance finding.
        """
        resolved_repository_root = self._repository_root.resolve()
        (
            program_document,
            schema_version,
            gate_ids,
            roadmap_path,
            packages,
        ) = self._read_program_header(path, resolved_repository_root)
        ownership_roles, package_states, finding_dispositions = self._load_states(
            program_document,
            resolved_repository_root=resolved_repository_root,
            schema_version=schema_version,
        )
        metrics, finding_ids = self._load_metrics_and_findings(
            program_document, ownership_roles=ownership_roles
        )
        (
            local_evidence_manifest_path,
            local_evidence_commit_sha,
            generated_status_path,
        ) = self._load_evidence_paths(
            program_document,
            path=path,
            repository_root=resolved_repository_root,
            schema_version=schema_version,
        )
        return self._build_program(
            program_document,
            path=path,
            schema_version=schema_version,
            gate_ids=gate_ids,
            roadmap_path=roadmap_path,
            packages=packages,
            package_states=package_states,
            metrics=metrics,
            finding_ids=finding_ids,
            finding_dispositions=finding_dispositions,
            local_evidence_manifest_path=local_evidence_manifest_path,
            local_evidence_commit_sha=local_evidence_commit_sha,
            generated_status_path=generated_status_path,
        )

    def _read_program_header(
        self,
        path: Path,
        repository_root: Path,
    ) -> tuple[
        dict[str, object],
        int,
        tuple[str, ...],
        str,
        tuple[PackageNode, ...],
    ]:
        """Read fixed program scalars and parse the repository roadmap.

        Args:
            path: Program-governance TOML path.
            repository_root: Resolved root used for the repository-relative roadmap path.

        Returns:
            Parsed document, schema version, gate IDs, roadmap path, and package nodes.

        Raises:
            ProgramGovernanceError: If fixed policy values or roadmap validation fails.
            OSError: If the program or roadmap cannot be read.
            UnicodeDecodeError: If an input is not valid UTF-8.
        """
        program_document = _load_toml(path)
        schema_version = program_document.get("schema_version")
        if type(schema_version) is not int or schema_version not in {1, 2, 3, 4}:
            raise ProgramGovernanceError([f"{path}: schema_version must be 1, 2, 3, or 4"])
        expected_root_keys = _ROOT_KEYS_V4 if schema_version >= 4 else _ROOT_KEYS
        if set(program_document) != expected_root_keys:
            raise ProgramGovernanceError(
                [f"{path}: fields must be exactly {sorted(expected_root_keys)!r}"]
            )
        expected_scalars: dict[str, object] = {
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
            raise ProgramGovernanceError(
                [f"{path}: applicable gates must be {APPLICABLE_GATE_IDS!r}"]
            )
        roadmap_path = _require_string(program_document, "roadmap_path", context=str(path))
        roadmap_file = _require_repository_file(
            roadmap_path,
            repository_root=repository_root,
            context="roadmap_path",
        )
        packages = self._roadmap_parser.parse(roadmap_file)
        return program_document, schema_version, gate_ids, roadmap_path, packages

    def _load_states(
        self,
        program_document: dict[str, object],
        *,
        resolved_repository_root: Path,
        schema_version: int,
    ) -> tuple[frozenset[str], tuple[PackageState, ...], tuple[FindingDispositionGroup, ...]]:
        """Load ownership roles, operating rules, package states, and finding mappings.

        Args:
            program_document: Parsed program-governance document.
            resolved_repository_root: Repository root for evidence paths and default ownership.
            schema_version: Schema version selecting legacy or versioned state rules.

        Returns:
            Ownership roles, validated package states, and schema-4 finding dispositions.

        Raises:
            ProgramGovernanceError: If ownership, state, or finding mapping rules fail.
            OperatingModelError: If loading or resolving operating rules fails; the calling
                ``load_program`` method translates the error with its cause chained.
            ValidationError: If a package-state or finding-disposition model rejects its input.
            OSError: If ownership or legacy evidence files cannot be read.
            UnicodeDecodeError: If a legacy evidence file is not UTF-8.
        """
        ownership_path = (
            resolved_repository_root / "docs" / "governance" / "domain-ownership.toml"
            if self._ownership_register_path is None
            else self._ownership_register_path
        )
        ownership_roles = _ownership_roles(ownership_path)
        operating_model = load_operating_model(ownership_path) if schema_version >= 2 else None
        package_states = _PackageStateParser(
            repository_root=resolved_repository_root,
            ownership_roles=ownership_roles,
            schema_version=schema_version,
            operating_model=operating_model,
        ).parse(program_document.get("package_states"))
        finding_dispositions = (
            ()
            if schema_version < 4
            else _parse_finding_dispositions(
                program_document.get("finding_dispositions"),
                package_states=package_states,
            )
        )
        return ownership_roles, package_states, finding_dispositions

    def _load_metrics_and_findings(
        self,
        program_document: dict[str, object],
        *,
        ownership_roles: frozenset[str],
    ) -> tuple[tuple[MetricDefinition, ...], tuple[str, ...]]:
        """Parse the ordered KPI definitions and fixed open finding identifiers.

        Args:
            program_document: Parsed program-governance document.
            ownership_roles: Roles accepted by metric definitions.

        Returns:
            Validated metric definitions and the declared finding IDs.

        Raises:
            ProgramGovernanceError: If metric ordering, source-event uniqueness, finding
                content, or declared-finding agreement fails.
            OverflowError: If a metric integer cannot be converted to ``float``.
            ValidationError: If a metric model rejects validated fields.
        """
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
        if finding_ids != _PROGRAM_GOVERNANCE_OPEN_FINDING_IDS or declared_findings != finding_ids:
            raise ProgramGovernanceError(["A08 partial status requires the exact open findings"])
        return metrics, finding_ids

    def _load_evidence_paths(
        self,
        program_document: dict[str, object],
        *,
        path: Path,
        repository_root: Path,
        schema_version: int,
    ) -> tuple[str, str, str | None]:
        """Validate recorded evidence and schema-4 generated-status paths.

        Args:
            program_document: Parsed program-governance document.
            path: Program path used for field diagnostics.
            repository_root: Resolved root for repository-relative files.
            schema_version: Schema version selecting the optional status path.

        Returns:
            Local evidence manifest path, full commit digest, and optional status path.

        Raises:
            ProgramGovernanceError: If evidence paths, digest, or generated-status parent
                safety checks fail; filesystem containment failures preserve their causes.
            OSError: If an uncaught path operation fails.
            RuntimeError: If strict path resolution encounters a symlink loop.
        """
        local_evidence_manifest_path = _require_string(
            program_document, "local_evidence_manifest_path", context=str(path)
        )
        _require_repository_file(
            local_evidence_manifest_path,
            repository_root=repository_root,
            context="local_evidence_manifest_path",
        )
        local_evidence_commit_sha = _require_string(
            program_document, "local_evidence_commit_sha", context=str(path)
        )
        if _REVISION.fullmatch(local_evidence_commit_sha) is None:
            raise ProgramGovernanceError(["local_evidence_commit_sha must be a full digest"])
        generated_status_path = (
            None
            if schema_version < 4
            else _require_string(program_document, "generated_status_path", context=str(path))
        )
        if generated_status_path is not None:
            relative_status_path = PurePosixPath(generated_status_path)
            if (
                relative_status_path.is_absolute()
                or ".." in relative_status_path.parts
                or relative_status_path.as_posix() != generated_status_path
                or relative_status_path.suffix != ".md"
            ):
                raise ProgramGovernanceError(["generated_status_path must be a safe Markdown path"])
            status_parent = repository_root.joinpath(*relative_status_path.parts).parent
            try:
                status_parent.resolve(strict=True).relative_to(repository_root)
            except (FileNotFoundError, ValueError) as error:
                raise ProgramGovernanceError(
                    ["generated_status_path parent must exist inside the repository"]
                ) from error
        return local_evidence_manifest_path, local_evidence_commit_sha, generated_status_path

    def _build_program(
        self,
        program_document: dict[str, object],
        *,
        path: Path,
        schema_version: int,
        gate_ids: tuple[str, ...],
        roadmap_path: str,
        packages: tuple[PackageNode, ...],
        package_states: tuple[PackageState, ...],
        metrics: tuple[MetricDefinition, ...],
        finding_ids: tuple[str, ...],
        finding_dispositions: tuple[FindingDispositionGroup, ...],
        local_evidence_manifest_path: str,
        local_evidence_commit_sha: str,
        generated_status_path: str | None,
    ) -> ProgramGovernance:
        """Construct the immutable program and enforce completion dependencies.

        Args:
            program_document: Parsed scalar fields from the TOML document.
            path: Program path used for date diagnostics.
            schema_version: Validated schema version.
            gate_ids: Validated ordered gate IDs.
            roadmap_path: Repository-relative roadmap path.
            packages: Validated roadmap package graph.
            package_states: Validated package states.
            metrics: Validated KPI definitions.
            finding_ids: Validated open finding IDs.
            finding_dispositions: Ordered schema-4 finding mappings.
            local_evidence_manifest_path: Validated manifest path.
            local_evidence_commit_sha: Validated evidence commit digest.
            generated_status_path: Optional validated schema-4 status path.

        Returns:
            An immutable ``ProgramGovernance`` record.

        Raises:
            ProgramGovernanceError: If model construction or technical dependency readiness
                fails. The caller translates Pydantic model failures with their cause chained.
            ValidationError: If the Pydantic boundary model rejects the assembled record.
        """
        program = ProgramGovernance(
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
            generated_status_path=generated_status_path,
            packages=packages,
            package_states=package_states,
            metrics=metrics,
            finding_ids=finding_ids,
            finding_dispositions=finding_dispositions,
        )
        if schema_version >= 2:
            for package in packages:
                state = program.state_for(package.package_id)
                if state is not None and state.implementation_status == "complete":
                    if not program._dependencies_ready(package, institutional=False):
                        raise ProgramGovernanceError(
                            [
                                f"{package.package_id}: completion requires "
                                "complete technical dependencies"
                            ]
                        )
        return program

    def load_observations(
        self,
        path: Path,
        *,
        program: ProgramGovernance,
    ) -> tuple[MetricObservation, ...]:
        """Read observations through a dedicated reader bound to the supplied program.

        Apply the retry, window, and first-seen ordering contracts of ``ObservationReader.read``.
        This operation uses the supplied program and file path; it does not resolve either
        against the repository context or reload the program policy.

        Args:
            path: UTF-8 JSONL observation file; relative paths are process-relative.
            program: Immutable program contract used for metric validation.

        Returns:
            Unique observations in first-seen order.

        Raises:
            ProgramGovernanceError: If the 10,000,000-byte limit, JSON structure, duplicate
                event identity, metric contract, provenance, UTC ``Z`` windows, dimensions,
                ratio bounds, evidence URL, unique-event limit, or overlap checks fail.
            OSError: If file inspection or reading fails.
            UnicodeDecodeError: If the JSONL file is not UTF-8.
            ValueError: If a JSON integer exceeds the interpreter's conversion limit.
            RecursionError: If JSON nesting exceeds the decoder's recursion limit.
            OverflowError: If a numeric observation is too large for ``float`` conversion.
            ValidationError: If a model rejects parsed input; the public wrapper translates
                this error with its cause chained.
        """
        return ObservationReader(program).read(path)

    def validate_repository(self) -> ProgramGovernance:
        """Validate the authoritative program, local evidence, and generated status.

        Resolve the bound root, load the authoritative program, validate its A08 local
        evidence bundle, and validate the configured generated status document when schema
        4 supplies one. Each invocation resolves and checks all state independently.

        Returns:
            The immutable program record after every repository check passes.

        Raises:
            ProgramGovernanceError: If program loading, local evidence, or generated-status
                validation fails. Local evidence and translated status I/O failures preserve
                their causes according to their existing boundary contracts.
            OSError: If root, program, roadmap, ownership, or legacy-evidence reads fail
                before an existing translation boundary.
            UnicodeDecodeError: If an authoritative or generated-status read is not UTF-8.
            RuntimeError: If strict path resolution encounters a symlink loop.
            OverflowError: If a metric integer is too large for ``float`` conversion.
        """
        resolved_repository_root = self._repository_root.resolve()
        program = self.load_program(
            resolved_repository_root / "docs" / "governance" / "program-governance.toml"
        )
        self._validate_local_evidence(resolved_repository_root, program)
        if program.generated_status_path is not None:
            # project library imports
            from alpha_research_governance.program_governance.status import (
                validate_status_document,
            )

            validate_status_document(
                resolved_repository_root / program.generated_status_path,
                program,
            )
        return program

    def _validate_local_evidence(
        self,
        repository_root: Path,
        program: ProgramGovernance,
    ) -> None:
        """Validate the A08 local evidence bundle against its policy and fixed profile.

        Read the repository change-risk policy, manifest, and manifest artifacts through the
        evidence validators; this method performs no writes and does not change ``program``.

        Args:
            repository_root: Operation-resolved repository root containing the change-risk
                policy and evidence manifest.
            program: Program record supplying the expected commit SHA and manifest path.

        Raises:
            ProgramGovernanceError: If the commit SHA is malformed, policy or manifest loading
                fails, or the manifest does not match the A08 local-evidence profile.
        """
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


def _load_program(
    path: Path,
    *,
    repository_root: Path,
    ownership_register_path: Path | None = None,
) -> ProgramGovernance:
    """Delegate program loading through the compatibility failure-injection seam.

    Args:
        path: UTF-8 program-governance TOML file.
        repository_root: Repository root for relative paths.
        ownership_register_path: Optional ownership-register override.

    Returns:
        The validated immutable program record.

    Raises:
        ProgramGovernanceError: If loading or validation fails.
    """
    return ProgramRepository(repository_root, ownership_register_path).load_program(path)


def load_program(
    path: Path,
    *,
    repository_root: Path,
    ownership_register_path: Path | None = None,
) -> ProgramGovernance:
    """Load and validate a program-governance TOML record.

    Resolve ``repository_root`` first, load the policy schema and fixed A08
    scalars, validate its roadmap path and package graph, then read the
    ownership register and (for schema versions 2 through 4) derive operating
    rules. Parse package states, then schema-4 finding dispositions, then
    metrics and finding IDs in source order; validate the recorded evidence
    path and commit digest; validate a schema-4 generated-status parent;
    construct the immutable program; and finally require complete
    implementation states to have ready technical dependencies. Versioned
    package-state rules use ``date.today()`` for their effective date; the
    policy's recorded ``as_of_date`` is retained as metadata and does not
    select those rules. Schemas 1 through 3 read package-state evidence files
    as UTF-8 and check their finding IDs; schema 4 checks one existing Markdown
    path per package state without reading it. The recorded local evidence manifest and
    generated-status contents are validated only by ``validate_repository``.
    All reads and path checks are read-only.

    Args:
        path: UTF-8 TOML program-governance file; a relative path is interpreted
            from the process current working directory.
        repository_root: Repository root used for repository-relative paths and
            the default ownership register; a relative path is resolved from
            the process current working directory.
        ownership_register_path: Optional ownership-register TOML file. ``None``
            uses ``docs/governance/domain-ownership.toml`` below the resolved
            root; a supplied relative path is interpreted from the process
            current working directory and is not rebased to the root.

    Returns:
        The immutable ``ProgramGovernance`` record with roadmap packages,
        ordered package states, KPI definitions, returned finding IDs and any schema-4
        finding dispositions.

    Raises:
        ProgramGovernanceError: If TOML syntax or policy structure, roadmap,
            ownership, package-state, operating-rule, metric, finding,
            evidence-path, digest, generated-status-path, dependency, or model
            validation fails. ``OperatingModelError`` and Pydantic
            ``ValidationError`` failures are translated with causes chained.
        OSError: If an uncaught repository, policy, roadmap, ownership or
            legacy-evidence file operation fails.
        UnicodeDecodeError: If an uncaught UTF-8 read fails.
        RuntimeError: If strict repository-path resolution encounters a symlink
            loop.
        OverflowError: If a metric integer is too large to convert to ``float``.
    """
    try:
        return _load_program(
            path,
            repository_root=repository_root,
            ownership_register_path=ownership_register_path,
        )
    except OperatingModelError as error:
        raise ProgramGovernanceError([str(error)]) from error
    except ValidationError as error:
        raise ProgramGovernanceError([f"{path}: program model validation failed"]) from error


class ObservationReader:
    """Read and validate bounded JSONL metric observations for one program contract.

    Construction performs no I/O and retains only the immutable program contract. Each
    ``read`` operation parses one file into local collections, deduplicates identical
    retries, and returns observations in first-seen order.
    """

    def __init__(self, program: ProgramGovernance) -> None:
        """Bind the immutable program contract used for observation validation.

        Args:
            program: Validated metric definitions, observation schema version, and
                maximum-observation limit.
        """
        self._program = program

    def read(self, path: Path) -> tuple[MetricObservation, ...]:
        """Read one bounded JSONL file using the bound immutable program contract.

        Check the file size before reading, ignore blank lines, reject duplicate JSON keys,
        validate metric-specific fields and UTC ``Z`` timestamps, require positive windows, and
        deduplicate retries only when their parsed event dictionaries are equal. Ratio windows
        may last at most the configured metric window; overlap checks apply only to the same
        metric and dimensions, and touching endpoints are allowed. The overlap check sorts a
        separate sequence, while the returned tuple preserves first-seen order of unique events.
        The file and bound program are never modified.

        Args:
            path: UTF-8 JSONL observation file. Its size is checked before reading.

        Returns:
            Unique observations in first-seen input order.

        Raises:
            ProgramGovernanceError: If JSON structure, metric fields, provenance,
                timestamps, dimensions, limits, overlap, or evidence rules fail.
            ValidationError: If an observation model rejects parsed values; the public
                ``load_observations`` wrapper translates this error.
            OSError: If the file cannot be inspected or read.
            UnicodeDecodeError: If the file is not valid UTF-8.
            ValueError: If JSON integer conversion exceeds the interpreter limit.
            RecursionError: If JSON nesting exceeds the decoder limit.
            OverflowError: If a numeric value cannot be converted to ``float``.
        """
        if path.stat().st_size > _MAX_OBSERVATION_FILE_BYTES:
            raise ProgramGovernanceError(["observation input exceeds the governed byte limit"])
        metrics_by_id = {metric.metric_id: metric for metric in self._program.metrics}
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
                expected_keys.update(
                    {"denominator", "denominator_unit", "numerator", "numerator_unit"}
                )
            if set(event_document) != expected_keys:
                raise ProgramGovernanceError(
                    [f"{context}: observation has missing or unknown fields"]
                )
            if event_document.get("schema_version") != self._program.observation_schema_version:
                raise ProgramGovernanceError([f"{context}: unsupported observation schema version"])
            event_id = _require_string(event_document, "event_id", context=context)
            if _EVENT_ID.fullmatch(event_id) is None:
                raise ProgramGovernanceError([f"{context}.event_id is malformed"])
            previous_event_document = event_documents_by_id.get(event_id)
            if previous_event_document is not None:
                if previous_event_document != event_document:
                    raise ProgramGovernanceError(
                        [f"{context}: conflicting duplicate event {event_id}"]
                    )
                continue
            event_documents_by_id[event_id] = event_document
            observations.append(self._parse_event(event_document, context=context, metric=metric))
            if len(observations) > self._program.maximum_observations:
                raise ProgramGovernanceError(["observation input exceeds the governed maximum"])
        self._validate_non_overlapping(path, observations, metrics_by_id)
        return tuple(observations)

    def _parse_event(
        self,
        event_document: dict[str, object],
        *,
        context: str,
        metric: MetricDefinition,
    ) -> MetricObservation:
        """Validate one event against its metric and build an immutable observation.

        Args:
            event_document: Parsed JSON object with duplicate keys already rejected.
            context: File and line location used in findings.
            metric: Metric definition selected by the event's metric ID.

        Returns:
            The validated immutable observation.

        Raises:
            ProgramGovernanceError: If provenance, timestamps, dimensions, units,
                ratio bounds, or evidence URL validation fails.
            ValidationError: If the observation model rejects the validated values.
            OverflowError: If a numeric value is too large to convert to ``float``.
        """
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
        event_id = _require_string(event_document, "event_id", context=context)
        return MetricObservation(
            event_id=event_id,
            metric_id=metric.metric_id,
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

    def _validate_non_overlapping(
        self,
        path: Path,
        observations: list[MetricObservation],
        metrics_by_id: dict[str, MetricDefinition],
    ) -> None:
        """Reject overlapping ratio windows while retaining input order.

        Args:
            path: Observation file used in the overlap finding.
            observations: Unique observations in first-seen order.
            metrics_by_id: Metric definitions keyed by metric ID.

        Raises:
            ProgramGovernanceError: If ratio observations with matching metric and
                dimensions overlap.
        """
        previous_end: dict[tuple[str, tuple[tuple[str, str], ...]], datetime] = {}
        for observation in sorted(observations, key=self._observation_sort_key):
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

    def _observation_sort_key(
        self,
        observation: MetricObservation,
    ) -> tuple[str, tuple[tuple[str, str], ...], datetime, str]:
        """Return the deterministic key used for overlap checks.

        Args:
            observation: Immutable observation whose metric, dimensions, window start,
                and event identity determine validation order.

        Returns:
            A stable ordering key that leaves the caller's observation sequence unchanged.
        """
        return (
            observation.metric_id,
            observation.dimensions,
            observation.window_start,
            observation.event_id,
        )


def _load_observations(path: Path, *, program: ProgramGovernance) -> tuple[MetricObservation, ...]:
    """Delegate observation loading through the compatibility reader seam.

    Args:
        path: UTF-8 JSONL observation file to read.
        program: Immutable program record supplying observation contracts.

    Returns:
        Unique observations in first-seen input order.

    Raises:
        ProgramGovernanceError: If observation validation fails.
        ValidationError: If an observation model rejects parsed input; the public
            wrapper translates this error.
        OSError: If the file cannot be inspected or read.
        UnicodeDecodeError: If the file is not valid UTF-8.
    """
    return ObservationReader(program).read(path)


def load_observations(path: Path, *, program: ProgramGovernance) -> tuple[MetricObservation, ...]:
    """Load, validate and deduplicate bounded JSONL KPI observations.

    Check the file size before reading, ignore blank lines, parse each JSON
    object with duplicate-key rejection, validate metric-specific fields and
    UTC ``Z`` timestamps, require positive windows, and deduplicate retries by
    parsed event-dictionary equality. Identical retries are retained once; a
    conflicting duplicate ID fails. Ratio windows may last at most the
    configured metric window, and overlap checks apply only to the same metric
    and dimensions; touching endpoints are allowed. The checks sort a
    separate sequence, while the returned tuple preserves first-seen order of
    unique input events. The file and ``program`` are not modified.

    Args:
        path: UTF-8 JSONL observation file; relative paths are interpreted from
            the process current working directory. Its size must not exceed the
            governed 10,000,000-byte limit before reading.
        program: Immutable, validated program record supplying metric contracts,
            observation schema version and maximum-observation limit. That limit
            counts unique parsed events after identical retries are discarded.

    Returns:
        A tuple of immutable ``MetricObservation`` records in first-seen input
        order, excluding blank lines and repeated identical event IDs.

    Raises:
        ProgramGovernanceError: If file size, JSON structure, duplicate IDs,
            metric identity, schema, provenance, timestamps, dimensions, units,
            ratio bounds, evidence URL, observation count, overlap, or model
            validation fails. Pydantic model failures are translated with their
            causes chained.
        OSError: If stat or UTF-8 file reading fails.
        UnicodeDecodeError: If the JSONL file is not valid UTF-8.
        ValueError: If a JSON integer exceeds the interpreter's conversion
            limit; ordinary JSON syntax errors are translated above.
        RecursionError: If JSON nesting exceeds the decoder's recursion limit.
        OverflowError: If a numeric observation value is too large to convert to
            ``float``.
    """
    try:
        return _load_observations(path, program=program)
    except ValidationError as error:
        raise ProgramGovernanceError([f"{path}: observation model validation failed"]) from error


def validate_repository(repository_root: Path) -> ProgramGovernance:
    """Validate the authoritative program record, local evidence and status file.

    Resolve ``repository_root``, load the authoritative
    ``docs/governance/program-governance.toml`` with its default ownership
    register, load the change-risk policy, then validate the recorded local
    evidence manifest and its artifacts against the commit SHA and A08
    package-evidence profile. Finally validate the configured generated status
    document when schema 4 supplies one. The checks run in that order, perform
    only reads and path inspection, and return the immutable program record
    after every check passes.

    Args:
        repository_root: Repository root containing the authoritative program,
            ownership, roadmap, evidence and generated-status files; a relative
            path is resolved from the process current working directory.

    Returns:
        The immutable ``ProgramGovernance`` record loaded from the authoritative
        policy and checked against local evidence and generated status.

    Raises:
        ProgramGovernanceError: If program loading, local evidence, package
            profile, generated-status content, or a translated filesystem
            failure occurs. Local evidence ``OSError``/``ValueError`` failures
            and generated-status ``OSError`` failures are translated with their
            causes chained.
        OSError: If root or authoritative program, roadmap, ownership or
            legacy-evidence operations fail before a translation boundary.
        UnicodeDecodeError: If an authoritative or generated-status UTF-8 read
            fails; local-evidence decoding failures are translated.
        RuntimeError: If root or strict repository/evidence path resolution
            encounters a symlink loop.
        OverflowError: If a metric integer is too large to convert to ``float``
            while loading the program.
    """
    return ProgramRepository(repository_root).validate_repository()
