"""Load and enforce the language and static-quality standards contract."""

from __future__ import annotations

# standard library imports
import re
import tokenize
import tomllib
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import cast

# third party library imports
from pydantic import ValidationError

# project library imports
from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.engineering_standards.models import (
    EngineeringStandards,
    EngineeringStandardsError,
    LanguageStandard,
    ToolStandard,
)
from alpha_research_governance.engineering_standards.python_debt import PythonStandardsChecker
from alpha_research_governance.evidence import (
    EvidenceGovernanceError,
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
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
_ENGINEERING_STANDARDS_OPEN_FINDING_IDS = ("B04-F01", "B04-F02", "B04-F03")
_SOURCE_ROOTS = (
    "src/alpha_research",
    "tests",
    "tools/governance/src/alpha_research_governance",
    "tools/typing/stubs",
)
_TOOL_VERSIONS = {
    "bandit": "1.9.4",
    "coverage": "7.15.4",
    "hypothesis": "6.167.1",
    "mypy": "2.3.1",
    "pytest": "9.1.1",
    "pytest-cov": "7.1.0",
    "ruff": "0.16.5",
}
_TOOL_ROLES = {
    "bandit": ("security_static_analysis",),
    "coverage": ("coverage_baseline",),
    "hypothesis": ("property_testing", "state_machine_testing"),
    "mypy": ("strict_type_checking",),
    "pytest": ("test_execution", "warnings_as_errors"),
    "pytest-cov": ("coverage_baseline",),
    "ruff": ("formatting", "linting"),
}
_DIRECT_TOOL_REQUIREMENTS = (
    "bandit[toml]==1.9.4",
    "hypothesis==6.167.1",
    "mypy==2.3.1",
    "pytest==9.1.1",
    "pytest-cov==7.1.0",
    "ruff==0.16.5",
)
_LANGUAGE_IDS = ("python", "c_cpp", "rust")
_LANGUAGE_STANDARDS = {
    "python": (
        "admitted",
        "3.12.14",
        (".py", ".pyi"),
        "pytest warnings are errors; Ruff and strict mypy findings are blocking",
        (),
    ),
    "c_cpp": (
        "dormant",
        "not_admitted",
        (".c", ".cc", ".cpp", ".h", ".hpp"),
        "compiler warnings are errors for project code",
        ("address", "undefined_behavior", "thread_for_shared_memory"),
    ),
    "rust": (
        "dormant",
        "not_admitted",
        (".rs",),
        "clippy warnings are denied",
        ("miri_or_applicable_sanitizer_for_unsafe_or_low_level_code",),
    ),
}
_API_SURFACES = (
    (
        "alpha_research",
        "compatibility",
        "versioned migration, deprecation window, compatibility test, and rollback",
    ),
    (
        "alpha_research_governance",
        "repository_internal",
        "same-change consumer update plus retained rollback",
    ),
)
_FINDING_OWNERS = ("domain_architecture", "platform_ci", "security")
_NATIVE_EXTENSIONS = frozenset({".c", ".cc", ".cpp", ".h", ".hpp", ".rs"})
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SUPPRESSION = re.compile(
    r"#\s*(?:noqa(?::\s*[A-Z0-9, ]+)?|nosec(?:\s+[A-Z0-9, ]+)?|"
    r"type:\s*ignore(?:\[[^]]+\])?|pragma:\s*no cover|fmt:\s*(?:skip|off)|ruff:\s*noqa)\b"
)
_SUPPRESSION_METADATA = re.compile(
    r"\[owner=(?P<owner>[a-z][a-z0-9_]*); rationale=(?P<rationale>[^;\[\]]+); "
    r"expires=(?P<expires>\d{4}-\d{2}-\d{2})\]\s*$"
)
_ROOT_KEYS = {
    "accountable_owner_role",
    "api_surfaces",
    "applicable_gate_ids",
    "baselines",
    "findings",
    "generated_code",
    "languages",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "numerical",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "property_testing",
    "risk_class",
    "roadmap_package",
    "schema_version",
    "source_roots",
    "successor_package",
    "suppressions",
    "tools",
    "validation_workload_budget_ms",
    "validation_workload_iterations",
}
_LOCAL_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id="B04",
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
        PackageGateRequirement(gate_id=gate_id, status="passed") for gate_id in _APPLICABLE_GATES
    ),
    expected_package_status="partial",
    expected_finding_ids=_ENGINEERING_STANDARDS_OPEN_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=False,
)


def _table(value: object, *, context: str) -> dict[str, object]:
    """Require a parsed value to be a TOML table without deep validation.

    Args:
        value: Parsed TOML value expected to be a dictionary. The object is
            returned unchanged; keys and nested values are checked by callers.
        context: Policy location used in a validation finding.

    Returns:
        The same dictionary object, narrowed for field access.

    Raises:
        EngineeringStandardsError: If ``value`` is not a TOML table.
    """
    if not isinstance(value, dict):
        raise EngineeringStandardsError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _tables(value: object, *, context: str) -> list[dict[str, object]]:
    """Require an ordered list of parsed TOML tables.

    Args:
        value: Parsed TOML value expected to be a list containing only dictionaries.
            An empty list is accepted; nested fields are not inspected here.
        context: Policy location used in a validation finding.

    Returns:
        The same list object, narrowed for ordered field access.

    Raises:
        EngineeringStandardsError: If ``value`` is not a list of dictionaries.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise EngineeringStandardsError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Require an ordered list of unique, non-empty strings.

    Args:
        value: Parsed TOML value expected to be a list of strings. Whitespace-only
            strings are retained because this helper does not strip values.
        context: Policy location used in a validation finding.
        allow_empty: Whether an empty list is accepted; defaults to ``False``.

    Returns:
        A tuple containing the supplied strings in input order.

    Raises:
        EngineeringStandardsError: If the value is not a list of non-empty strings,
            is empty when ``allow_empty`` is false, or contains duplicates.
    """
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise EngineeringStandardsError([f"{context} must be an array of strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise EngineeringStandardsError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise EngineeringStandardsError([f"{context} must contain unique values"])
    return values


def _positive_integer(table: dict[str, object], key: str, *, context: str) -> int:
    """Require a table field to be an integer greater than or equal to one.

    Boolean values are rejected even though ``bool`` is an ``int`` subclass.

    Args:
        table: Parsed TOML table containing the field.
        key: Field name to retrieve.
        context: Policy location used in a validation finding.

    Returns:
        The positive integer value unchanged.

    Raises:
        EngineeringStandardsError: If the field is missing, non-integer, boolean,
            or less than one.
    """
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EngineeringStandardsError([f"{context}.{key} must be a positive integer"])
    return value


def _iso_date(value: object, *, context: str) -> date:
    """Parse one canonical ``YYYY-MM-DD`` string into a calendar date.

    This helper checks representation and calendar validity only. It does not
    compare the date with today or enforce a freshness or expiry window; callers
    supply those policy boundaries separately.

    Args:
        value: Parsed TOML value expected to be a canonical ISO date string.
        context: Policy location used in a validation finding.

    Returns:
        The parsed ``date`` value.

    Raises:
        EngineeringStandardsError: If ``value`` is not a string, is not a valid
            calendar date, or is not written in canonical ISO form. Invalid date
            errors from ``date.fromisoformat`` are translated and chained.
    """
    if not isinstance(value, str):
        raise EngineeringStandardsError([f"{context} must use YYYY-MM-DD"])
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise EngineeringStandardsError([f"{context} must use YYYY-MM-DD"]) from error
    if parsed.isoformat() != value:
        raise EngineeringStandardsError([f"{context} must use YYYY-MM-DD"])
    return parsed


def _parse_tools(value: object) -> tuple[ToolStandard, ...]:
    """Parse and enforce the exact ordered engineering-tool declarations.

    Each entry must be a TOML table with exactly ``roles``, ``tool_id`` and
    ``version`` keys. Roles are required to be non-empty and unique; the resulting
    records must then contain the seven configured tools, exact versions and role
    tuples, with tool IDs in sorted order. The helper validates this tools section
    only; root policy fields and lock/install bindings are checked by later callers.

    Args:
        value: Parsed ``tools`` array of TOML tables. An empty array is rejected by
            the exact tool-pin checks after shape parsing.

    Returns:
        Immutable tool records in the supplied sorted order.

    Raises:
        EngineeringStandardsError: If the value or entry shapes are invalid, a
            role list is empty or duplicated, or the exact tool/version/role/order
            contract drifts.
    """
    tools: list[ToolStandard] = []
    for index, entry in enumerate(_tables(value, context="tools"), 1):
        if set(entry) != {"roles", "tool_id", "version"}:
            raise EngineeringStandardsError([f"tools[{index}] has missing or unknown fields"])
        tool_id = entry.get("tool_id")
        version = entry.get("version")
        if not isinstance(tool_id, str) or not isinstance(version, str):
            raise EngineeringStandardsError([f"tools[{index}] identity must be strings"])
        tools.append(
            ToolStandard(
                tool_id=tool_id,
                version=version,
                roles=_strings(entry.get("roles"), context=f"tools[{index}].roles"),
            )
        )
    observed = {tool.tool_id: tool.version for tool in tools}
    observed_roles = {tool.tool_id: tool.roles for tool in tools}
    if (
        observed != _TOOL_VERSIONS
        or observed_roles != _TOOL_ROLES
        or len(tools) != len(observed)
        or tuple(observed) != tuple(sorted(_TOOL_VERSIONS))
    ):
        raise EngineeringStandardsError(
            ["tools must contain the exact sorted engineering-standard tool pins"]
        )
    return tuple(tools)


def _parse_languages(value: object) -> tuple[LanguageStandard, ...]:
    """Parse and enforce the exact admitted and dormant language declarations.

    Each entry must have exactly the six language fields ``admission_status``,
    ``language_id``, ``sanitizers``, ``source_extensions``, ``version`` and
    ``warnings_policy``. Scalar fields must be non-empty strings; source extensions
    must be a non-empty unique list, while sanitizers may be empty. The resulting
    records must use the configured ``python``, ``c_cpp``, ``rust`` order and exact
    policy tuples. Root policy and source-tree behavior are validated elsewhere.

    Args:
        value: Parsed ``languages`` array of TOML tables. An empty array is rejected
            by the required language ordering and exact-policy checks.

    Returns:
        Immutable language records in policy order.

    Raises:
        EngineeringStandardsError: If the value or entry fields are malformed, a
            required string/list is invalid, or language identity/order/policy
            values drift.
    """
    languages: list[LanguageStandard] = []
    required = {
        "admission_status",
        "language_id",
        "sanitizers",
        "source_extensions",
        "version",
        "warnings_policy",
    }
    for index, entry in enumerate(_tables(value, context="languages"), 1):
        if set(entry) != required:
            raise EngineeringStandardsError([f"languages[{index}] has missing or unknown fields"])
        language_id = entry.get("language_id")
        status = entry.get("admission_status")
        version = entry.get("version")
        warnings_policy = entry.get("warnings_policy")
        if not all(
            isinstance(item, str) and item
            for item in (language_id, status, version, warnings_policy)
        ):
            raise EngineeringStandardsError([f"languages[{index}] scalar fields must be strings"])
        languages.append(
            LanguageStandard(
                language_id=cast(str, language_id),
                admission_status=cast(str, status),
                version=cast(str, version),
                source_extensions=_strings(
                    entry.get("source_extensions"), context=f"languages[{index}].source_extensions"
                ),
                warnings_policy=cast(str, warnings_policy),
                sanitizers=_strings(
                    entry.get("sanitizers"),
                    context=f"languages[{index}].sanitizers",
                    allow_empty=True,
                ),
            )
        )
    if tuple(language.language_id for language in languages) != _LANGUAGE_IDS:
        raise EngineeringStandardsError(["languages must be ordered as python, c_cpp, rust"])
    observed_standards = {
        language.language_id: (
            language.admission_status,
            language.version,
            language.source_extensions,
            language.warnings_policy,
            language.sanitizers,
        )
        for language in languages
    }
    if observed_standards != _LANGUAGE_STANDARDS:
        raise EngineeringStandardsError(["language admission and quality policies drifted"])
    return tuple(languages)


def load_standards(path: Path) -> EngineeringStandards:
    """Load the engineering policy and reject missing, unknown, or weakened controls."""
    try:
        document = _table(tomllib.loads(path.read_text(encoding="utf-8")), context=str(path))
    except tomllib.TOMLDecodeError as error:
        raise EngineeringStandardsError([f"{path}: invalid TOML: {error}"]) from error
    if set(document) != _ROOT_KEYS:
        raise EngineeringStandardsError([f"{path}: has missing or unknown fields"])
    expected_scalars: dict[str, object] = {
        "accountable_owner_role": "platform",
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "risk_class": "R2",
        "roadmap_package": "B04",
        "schema_version": 1,
        "successor_package": "B05",
    }
    for key, expected in expected_scalars.items():
        if document.get(key) != expected:
            raise EngineeringStandardsError([f"{path}: {key} must be {expected!r}"])
    if (
        document.get("validation_workload_iterations") != 10_000
        or document.get("validation_workload_budget_ms") != 1_000
    ):
        raise EngineeringStandardsError(
            ["engineering-standards validation workload budget drifted"]
        )
    if (
        _strings(document.get("applicable_gate_ids"), context="applicable_gate_ids")
        != _APPLICABLE_GATES
    ):
        raise EngineeringStandardsError(
            ["engineering standards must retain the exact R2 applicable gates"]
        )
    if _strings(document.get("source_roots"), context="source_roots") != _SOURCE_ROOTS:
        raise EngineeringStandardsError(["source_roots must cover the exact current source areas"])
    evidence_sha = document.get("local_evidence_commit_sha")
    if not isinstance(evidence_sha, str) or _COMMIT_SHA.fullmatch(evidence_sha) is None:
        raise EngineeringStandardsError(["local_evidence_commit_sha must be a full lowercase SHA"])
    open_finding_ids = _strings(document.get("open_finding_ids"), context="open_finding_ids")
    findings = _tables(document.get("findings"), context="findings")
    if (
        open_finding_ids != _ENGINEERING_STANDARDS_OPEN_FINDING_IDS
        or tuple(item.get("finding_id") for item in findings)
        != _ENGINEERING_STANDARDS_OPEN_FINDING_IDS
    ):
        raise EngineeringStandardsError(
            ["partial engineering-standards status requires the exact open findings"]
        )
    for index, finding in enumerate(findings, 1):
        if set(finding) != {
            "closure_condition",
            "finding_id",
            "owner_role",
            "unavailable_evidence",
        }:
            raise EngineeringStandardsError([f"findings[{index}] has missing or unknown fields"])
        if not all(isinstance(value, str) and value for value in finding.values()):
            raise EngineeringStandardsError([f"findings[{index}] fields must be populated strings"])
    if tuple(item.get("owner_role") for item in findings) != _FINDING_OWNERS:
        raise EngineeringStandardsError(["engineering-standards finding ownership drifted"])

    suppressions = _table(document.get("suppressions"), context="suppressions")
    if set(suppressions) != {
        "maximum_lifetime_days",
        "minimum_rationale_characters",
        "required_metadata_order",
    } or _strings(
        suppressions.get("required_metadata_order"), context="suppressions.required_metadata_order"
    ) != ("owner", "rationale", "expires"):
        raise EngineeringStandardsError(["suppression metadata contract drifted"])
    maximum_lifetime = _positive_integer(
        suppressions, "maximum_lifetime_days", context="suppressions"
    )
    minimum_rationale = _positive_integer(
        suppressions, "minimum_rationale_characters", context="suppressions"
    )
    if maximum_lifetime != 180 or minimum_rationale != 12:
        raise EngineeringStandardsError(["suppression lifetime or rationale minimum was weakened"])

    generated = _table(document.get("generated_code"), context="generated_code")
    if (
        set(generated)
        != {
            "banner_prefix",
            "manual_edits_allowed",
            "required_metadata",
            "source_roots",
        }
        or generated.get("manual_edits_allowed") is not False
    ):
        raise EngineeringStandardsError(["generated-code separation contract drifted"])
    generated_roots = _strings(
        generated.get("source_roots"), context="generated_code.source_roots", allow_empty=True
    )
    if generated_roots:
        raise EngineeringStandardsError(
            ["no generated source root is admitted by the engineering standards"]
        )
    if generated.get("banner_prefix") != "@generated" or _strings(
        generated.get("required_metadata"), context="generated_code.required_metadata"
    ) != ("generator", "generator_version", "input_sha256"):
        raise EngineeringStandardsError(["generated-code provenance metadata drifted"])

    numerical = _table(document.get("numerical"), context="numerical")
    if numerical != {
        "exact_arithmetic_types": ["integer", "decimal"],
        "fast_math_requires_separate_review": True,
        "floating_comparison_requires": [
            "absolute_tolerance",
            "relative_tolerance",
            "scale_rationale",
        ],
        "global_epsilon_allowed": False,
        "non_finite_default": "reject",
    }:
        raise EngineeringStandardsError(["numerical tolerance or non-finite policy was weakened"])

    property_testing = _table(document.get("property_testing"), context="property_testing")
    expected_property_testing = {
        "database": "none",
        "derandomize": True,
        "maximum_examples": 50,
        "state_machine_required_for_stateful_contracts": True,
        "tool": "hypothesis",
        "version": "6.167.1",
    }
    if property_testing != expected_property_testing:
        raise EngineeringStandardsError(["property/state-machine test policy drifted"])

    baselines = _table(document.get("baselines"), context="baselines")
    if set(baselines) != {
        "coverage_branch_measurement",
        "coverage_scope",
        "coverage_statement_percent",
        "measurement_date",
        "mutation_cases",
        "mutation_cases_rejected",
    }:
        raise EngineeringStandardsError(["baseline fields drifted"])
    mutation_cases = _positive_integer(baselines, "mutation_cases", context="baselines")
    mutation_rejected = _positive_integer(baselines, "mutation_cases_rejected", context="baselines")
    if mutation_cases != 12 or mutation_rejected != mutation_cases:
        raise EngineeringStandardsError(["all twelve representative mutations must be rejected"])
    coverage_percent = _positive_integer(
        baselines, "coverage_statement_percent", context="baselines"
    )
    if coverage_percent != 81 or baselines.get("coverage_branch_measurement") is not True:
        raise EngineeringStandardsError(
            ["coverage baseline must retain the measured 81% branch run"]
        )
    if _strings(baselines.get("coverage_scope"), context="baselines.coverage_scope") != (
        "alpha_research",
        "alpha_research_governance",
    ):
        raise EngineeringStandardsError(["coverage baseline scope drifted"])

    api_surfaces = _tables(document.get("api_surfaces"), context="api_surfaces")
    observed_api_surfaces = tuple(
        (item.get("surface"), item.get("stability"), item.get("breaking_change_policy"))
        for item in api_surfaces
    )
    if observed_api_surfaces != _API_SURFACES or any(
        set(item) != {"breaking_change_policy", "stability", "surface"} for item in api_surfaces
    ):
        raise EngineeringStandardsError(["API stability surfaces or policies drifted"])

    tools = _parse_tools(document.get("tools"))
    languages = _parse_languages(document.get("languages"))
    try:
        return EngineeringStandards(
            package_status=cast(str, document["package_status"]),
            successor_package=cast(str, document["successor_package"]),
            validation_workload_iterations=_positive_integer(
                document, "validation_workload_iterations", context=str(path)
            ),
            validation_workload_budget_ms=_positive_integer(
                document, "validation_workload_budget_ms", context=str(path)
            ),
            applicable_gate_ids=_APPLICABLE_GATES,
            source_roots=_SOURCE_ROOTS,
            suppression_maximum_lifetime_days=maximum_lifetime,
            suppression_minimum_rationale_characters=minimum_rationale,
            generated_source_roots=generated_roots,
            hypothesis_version=cast(str, property_testing["version"]),
            hypothesis_maximum_examples=cast(int, property_testing["maximum_examples"]),
            coverage_statement_percent=coverage_percent,
            mutation_cases=mutation_cases,
            mutation_cases_rejected=mutation_rejected,
            measurement_date=_iso_date(
                baselines.get("measurement_date"), context="measurement_date"
            ),
            tools=tools,
            languages=languages,
            local_evidence_manifest_path=cast(str, document["local_evidence_manifest_path"]),
            local_evidence_commit_sha=evidence_sha,
            open_finding_ids=open_finding_ids,
        )
    except ValidationError as error:
        raise EngineeringStandardsError([f"{path}: model validation failed"]) from error


def validate_suppression_line(
    line: str,
    *,
    owner_roles: frozenset[str],
    validation_date: date,
    maximum_lifetime_days: int,
    minimum_rationale_characters: int,
) -> tuple[str, ...]:
    """Validate selected metadata on one recognized source-suppression line.

    The function searches raw line text with regular expressions; it does not
    tokenize or parse the source language. Lines without a supported suppression
    marker short-circuit to an empty result, even if they contain metadata-like
    text. A line with a recognized marker must contain trailing owner/rationale/expiry
    metadata with the exact required shape; missing metadata returns one finding.
    When metadata is present, owner membership and stripped rationale length are
    checked, then the caller-supplied expiry window is evaluated. Both boundaries
    are inclusive: expiry on ``validation_date`` and on
    ``validation_date + maximum_lifetime_days`` is accepted. The function does not
    select today's date or mutate the line.

    Args:
        line: Source line to inspect for a supported suppression marker and trailing
            metadata.
        owner_roles: Governed owner-role names accepted for the suppression.
        validation_date: Caller-supplied date from which expiry is measured.
        maximum_lifetime_days: Inclusive maximum number of days after validation.
        minimum_rationale_characters: Minimum length after trimming rationale edges.

    Returns:
        An ordered tuple of findings for owner, rationale, and expiry violations;
        an empty tuple means this line has no detected suppression finding.

    Raises:
        EngineeringStandardsError: If a recognized line has metadata with an
            invalid calendar date. The date parsing failure is translated by
            ``_iso_date`` and raises before any accumulated owner or rationale
            findings are returned; other findings are returned rather than raised.
    """
    if _SUPPRESSION.search(line) is None:
        return ()
    metadata = _SUPPRESSION_METADATA.search(line)
    if metadata is None:
        return ("suppression requires [owner=...; rationale=...; expires=YYYY-MM-DD]",)
    findings: list[str] = []
    owner = metadata.group("owner")
    if owner not in owner_roles:
        findings.append(f"suppression owner {owner!r} is not a governed role")
    rationale = metadata.group("rationale").strip()
    if len(rationale) < minimum_rationale_characters:
        findings.append("suppression rationale is too short")
    expiry = _iso_date(metadata.group("expires"), context="suppression expiry")
    if expiry < validation_date:
        findings.append("suppression is expired")
    if expiry > validation_date + timedelta(days=maximum_lifetime_days):
        findings.append("suppression exceeds the maximum lifetime")
    return tuple(findings)


def _owner_roles(path: Path) -> frozenset[str]:
    """Collect role names referenced by domain ownership declarations.

    For each parsed domain, each of ``accountable_role``,
    ``required_review_roles``, ``independent_review_roles`` and ``escalation_roles``
    accepts either a string or a list. This projection collects strings, including
    empty strings, from either form and ignores non-string values; unrelated fields
    and ownership records are ignored. Role names are deduplicated by the returned
    set. It does not validate the complete ownership schema or role naming policy.

    Args:
        path: UTF-8 TOML ownership file containing a ``domains`` array.

    Returns:
        A frozen set of collected role names.

    Raises:
        EngineeringStandardsError: If the root value or ``domains`` value is not
            a TOML table/list of tables.
        OSError: If the ownership file cannot be opened or read.
        UnicodeDecodeError: If the ownership file is not valid UTF-8.
        tomllib.TOMLDecodeError: If the ownership file is malformed TOML.
    """
    document = _table(tomllib.loads(path.read_text(encoding="utf-8")), context=str(path))
    roles: set[str] = set()
    for domain in _tables(document.get("domains"), context="domains"):
        for key in (
            "accountable_role",
            "required_review_roles",
            "independent_review_roles",
            "escalation_roles",
        ):
            value = domain.get(key)
            if isinstance(value, str):
                roles.add(value)
            elif isinstance(value, list):
                roles.update(item for item in value if isinstance(item, str))
    return frozenset(roles)


def _locked_packages(path: Path) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    """Project usable sdist lock records into a package lookup mapping.

    Each dictionary package table contributes only when its name and version are
    strings, ``sdist`` is a table with a string ``hash``, and ``dependencies`` is
    a list. An absent ``dependencies`` field defaults to an empty list. The
    projection includes dependency-table ``name`` strings in lock order, preserving
    duplicate names; dictionary tables with unusable consumed fields and malformed
    dependency items are skipped. A non-dictionary member of the package array is
    rejected by ``_tables`` before projection. If package names repeat, the later
    usable entry overwrites the earlier value while the dictionary's original
    insertion position is retained. This helper does not validate digest format,
    package uniqueness, or wheel data.

    Args:
        path: UTF-8 TOML lockfile containing a ``package`` array.

    Returns:
        Mapping from package name to ``(version, sdist_hash, dependency_names)``.

    Raises:
        EngineeringStandardsError: If the root value or ``package`` value is not
            a TOML table/list of tables.
        OSError: If the lockfile cannot be opened or read.
        UnicodeDecodeError: If the lockfile is not valid UTF-8.
        tomllib.TOMLDecodeError: If the lockfile is malformed TOML.
    """
    document = _table(tomllib.loads(path.read_text(encoding="utf-8")), context=str(path))
    result: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    for package in _tables(document.get("package"), context="package"):
        name = package.get("name")
        version = package.get("version")
        sdist = package.get("sdist")
        dependencies = package.get("dependencies", [])
        if (
            isinstance(name, str)
            and isinstance(version, str)
            and isinstance(sdist, dict)
            and isinstance(dependencies, list)
        ):
            digest = sdist.get("hash")
            dependency_names = tuple(
                item["name"]
                for item in dependencies
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            )
            if isinstance(digest, str):
                result[name] = (version, digest, dependency_names)
    return result


def _validate_dependency_record(
    repository_root: Path, locked: dict[str, tuple[str, str, tuple[str, ...]]]
) -> list[str]:
    path = repository_root / "docs/architecture/engineering-tool-dependencies.toml"
    document = _table(tomllib.loads(path.read_text(encoding="utf-8")), context=str(path))
    findings: list[str] = []
    if set(document) != {
        "accountable_owner_role",
        "admission_owner_package",
        "as_of_date",
        "dependencies",
        "operating_track",
        "package_status",
        "roadmap_package",
        "runtime_installation_allowed",
        "schema_version",
    }:
        return ["engineering-tool dependency record has missing or unknown fields"]
    expected = {
        "accountable_owner_role": "platform",
        "admission_owner_package": "B07",
        "operating_track": "solo_bootstrap",
        "package_status": "partial",
        "roadmap_package": "B04",
        "runtime_installation_allowed": False,
        "schema_version": 1,
    }
    for key, value in expected.items():
        if document.get(key) != value:
            findings.append(f"dependency record {key} must be {value!r}")
    if document.get("as_of_date") != "2026-09-02":
        findings.append("dependency record as_of_date must be '2026-09-02'")
    dependencies = _tables(document.get("dependencies"), context="dependencies")
    if len(dependencies) != 1:
        return [
            *findings,
            "engineering-tool dependency record must contain exactly Hypothesis",
        ]
    dependency = dependencies[0]
    required_fields = {
        "dependency_id",
        "license",
        "maintenance_review",
        "name",
        "purpose",
        "rollback",
        "source_digest",
        "source_url",
        "supported_platforms",
        "transitive_native_dependencies",
        "version",
        "vulnerability_review",
    }
    if set(dependency) != required_fields:
        return [*findings, "Hypothesis dependency record fields drifted"]
    hypothesis = locked.get("hypothesis")
    if hypothesis != ("6.167.1", dependency.get("source_digest"), ("sortedcontainers",)):
        findings.append("Hypothesis version, digest, or transitive lock binding drifted")
    if (
        dependency.get("dependency_id") != "b04.hypothesis"
        or dependency.get("name") != "Hypothesis"
        or dependency.get("version") != "6.167.1"
        or dependency.get("license") != "MPL-2.0"
        or dependency.get("source_url") != "https://pypi.org/project/hypothesis/6.167.1/"
    ):
        findings.append("Hypothesis dependency identity, version, source, or license drifted")
    if dependency.get("supported_platforms") != ["darwin_arm64", "linux_x86_64"]:
        findings.append("Hypothesis supported platforms drifted")
    if (
        dependency.get("transitive_native_dependencies")
        != [
            "hypothesis==6.167.1 platform wheels contain upstream native extension artifacts",
            "sortedcontainers==2.4.0 (pure Python)",
        ]
        or locked.get("sortedcontainers", (None,))[0] != "2.4.0"
    ):
        findings.append("Hypothesis transitive dependency record drifted")
    for key in ("maintenance_review", "purpose", "rollback", "source_url", "vulnerability_review"):
        if not isinstance(dependency.get(key), str) or not dependency[key]:
            findings.append(f"Hypothesis {key} must be populated")
    return findings


def source_tree_findings(
    repository_root: Path,
    standards: EngineeringStandards,
    *,
    owner_roles: frozenset[str],
    validation_date: date,
) -> tuple[str, ...]:
    """Return deterministic source findings for suppressions and dormant languages."""
    findings: list[str] = []
    for source_root in standards.source_roots:
        root = repository_root / source_root
        if not root.is_dir():
            findings.append(f"missing standards source root: {source_root}")
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix in _NATIVE_EXTENSIONS:
                findings.append(
                    "dormant native language source is not admitted: "
                    f"{path.relative_to(repository_root)}"
                )
            if path.suffix not in {".py", ".pyi"}:
                continue
            text = path.read_text(encoding="utf-8")
            try:
                comments = tuple(
                    token
                    for token in tokenize.generate_tokens(StringIO(text).readline)
                    if token.type == tokenize.COMMENT
                )
            except (IndentationError, tokenize.TokenError) as error:
                findings.append(
                    f"{path.relative_to(repository_root)}: cannot tokenize Python source: "
                    f"{error.args[0]}"
                )
                continue
            if any("@generated" in token.string and token.start[0] <= 5 for token in comments):
                findings.append(
                    "generated source is outside an admitted generated root: "
                    f"{path.relative_to(repository_root)}"
                )
            for comment in comments:
                for issue in validate_suppression_line(
                    comment.string,
                    owner_roles=owner_roles,
                    validation_date=validation_date,
                    maximum_lifetime_days=standards.suppression_maximum_lifetime_days,
                    minimum_rationale_characters=standards.suppression_minimum_rationale_characters,
                ):
                    findings.append(
                        f"{path.relative_to(repository_root)}:{comment.start[0]}: {issue}"
                    )
    return tuple(findings)


def validate_repository(
    repository_root: Path, *, validation_date: date | None = None
) -> EngineeringStandards:
    """Validate the engineering policy, tools, source tree, dependency, and evidence."""
    root = repository_root.resolve()
    standards = load_standards(root / "docs/architecture/engineering-standards.toml")
    today = date.today() if validation_date is None else validation_date
    findings: list[str] = []
    locked = _locked_packages(root / "uv.lock")
    for tool in standards.tools:
        locked_tool = locked.get(tool.tool_id)
        if locked_tool is None or locked_tool[0] != tool.version:
            findings.append(f"tool {tool.tool_id!r} is not locked at {tool.version}")
    pyproject = _table(
        tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")),
        context="pyproject.toml",
    )
    tool_configuration = _table(pyproject.get("tool"), context="pyproject.toml.tool")
    mypy_configuration = _table(tool_configuration.get("mypy"), context="pyproject.toml.tool.mypy")
    if mypy_configuration.get("strict") is not True:
        findings.append("Python migration must retain strict mypy checking")
    for flag in ("disallow_any_explicit", "disallow_any_unimported"):
        if mypy_configuration.get(flag) is not True:
            findings.append(f"Python boundary typing must retain {flag}")
    if mypy_configuration.get("plugins") != ["pydantic.mypy"]:
        findings.append("Python boundary typing requires the pinned Pydantic mypy plugin")
    plugin_configuration = _table(
        tool_configuration.get("pydantic-mypy"), context="pyproject.toml.tool.pydantic-mypy"
    )
    for flag in ("init_typed", "init_forbid_extra", "warn_required_dynamic_aliases"):
        if plugin_configuration.get(flag) is not True:
            findings.append(f"Pydantic typing must retain {flag}")
    expected_typing_scopes: list[dict[str, object]] = [
        {
            "module": ["alpha_research.*", "alpha_research_governance.*"],
            "disallow_any_decorated": True,
        },
        {
            "module": [
                "alpha_research.financial_units.conventions",
                "alpha_research_governance._models",
                "alpha_research_governance.change_risk.models",
                "alpha_research_governance.ci_policy.policy",
                "alpha_research_governance.engineering_standards.python_typing",
                "alpha_research_governance.operating_model",
                "test_python_typing",
            ],
            "disallow_any_expr": True,
        },
    ]
    if mypy_configuration.get("overrides") != expected_typing_scopes:
        findings.append("Python boundary typing enforcement scopes drifted")
    if mypy_configuration.get("mypy_path") != ["src", "tools/governance/src", "tools/typing/stubs"]:
        findings.append("Python boundary typing must resolve owned native stubs")
    ruff_configuration = _table(tool_configuration.get("ruff"), context="pyproject.toml.tool.ruff")
    ruff_lint = _table(ruff_configuration.get("lint"), context="pyproject.toml.tool.ruff.lint")
    if "I" not in _strings(ruff_lint.get("select"), context="Ruff selected rules"):
        findings.append("Python migration must retain Ruff import sorting")
    pytest_config = _table(tool_configuration.get("pytest"), context="pyproject.toml.tool.pytest")
    pytest_options = _table(
        pytest_config.get("ini_options"), context="pyproject.toml.tool.pytest.ini_options"
    )
    if pytest_options.get("filterwarnings") != ["error"]:
        findings.append("pytest warnings must fail as errors")
    dependency_groups = _table(
        pyproject.get("dependency-groups"), context="pyproject.toml.dependency-groups"
    )
    development_requirements = _strings(
        dependency_groups.get("dev"), context="pyproject.toml.dependency-groups.dev"
    )
    for requirement in _DIRECT_TOOL_REQUIREMENTS:
        if requirement not in development_requirements:
            findings.append(f"development requirements are missing exact tool pin {requirement}")
    requirements = (root / "requirements.bazel.txt").read_text(encoding="utf-8").splitlines()
    for requirement in ("hypothesis==6.167.1", "sortedcontainers==2.4.0"):
        if requirement not in requirements:
            findings.append(f"Bazel requirements are missing {requirement}")
    if (root / ".python-version").read_text(encoding="utf-8").strip() != "3.12.14":
        findings.append("Python language baseline must remain 3.12.14")

    owner_roles = _owner_roles(root / "docs/governance/domain-ownership.toml")
    findings.extend(
        PythonStandardsChecker(
            source_roots=standards.source_roots,
            owner_roles=owner_roles,
            validation_date=today,
        ).findings(root)
    )
    findings.extend(
        source_tree_findings(
            root,
            standards,
            owner_roles=owner_roles,
            validation_date=today,
        )
    )
    findings.extend(_validate_dependency_record(root, locked))
    try:
        manifest = validate_manifest(
            root / standards.local_evidence_manifest_path,
            expected_commit_sha=standards.local_evidence_commit_sha,
            change_policy=load_change_risk_policy(root / "docs/governance/change-risk-policy.toml"),
        )
        validate_package_evidence(manifest, _LOCAL_EVIDENCE_PROFILE)
    except (EvidenceGovernanceError, OSError, ValueError) as error:
        findings.append(f"engineering-standards evidence bundle: {error}")
    if findings:
        raise EngineeringStandardsError(findings)
    return standards
