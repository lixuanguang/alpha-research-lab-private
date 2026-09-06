"""Parse and cross-validate the security control map strictly."""

from __future__ import annotations

# standard library imports
import re
import tomllib
from datetime import date, timedelta
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
from alpha_research_governance.security_controls.models import (
    AuthoritySource,
    EvidenceSource,
    JurisdictionProfile,
    ProtectedAsset,
    RegulatoryMapping,
    SecurityControl,
    SecurityControlError,
    SecurityControlMap,
    ThreatScenario,
    TrustBoundary,
)

THREAT_CATEGORIES = (
    "data_entitlement",
    "market_integrity",
    "model_risk",
    "operational_resilience",
    "privileged_access",
    "software_supply_chain",
)
JURISDICTION_IDS = ("GB", "GLOBAL", "SG", "US")
SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS = ("A02", "A06")
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

_SECURITY_CONTROL_OPEN_FINDING_IDS = ("A07-F01", "A07-F02", "A07-F03", "A07-F04")
_LOCAL_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id="A07",
    accountable_owner_role="security",
    risk_class=RiskClass.R2,
    classification_facts=ChangeRiskInput(
        capital_at_risk=False,
        blast_radius="shared_domain",
        data_model_materiality="shared_or_candidate",
        security_privilege="shared_sensitive",
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
    expected_finding_ids=_SECURITY_CONTROL_OPEN_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=False,
)
_TRUSTED_AUTHORITY_HOSTS = {
    "A07-SRC-GB-01": "handbook.fca.org.uk",
    "A07-SRC-GB-02": "www.fca.org.uk",
    "A07-SRC-GLOBAL-01": "csrc.nist.gov",
    "A07-SRC-SG-01": "sso.agc.gov.sg",
    "A07-SRC-US-01": "www.sec.gov",
    "A07-SRC-US-02": "www.federalreserve.gov",
}
_MAX_SOURCE_VERIFICATION_AGE = timedelta(days=31)
_MAX_LEGAL_REVIEW_HORIZON = timedelta(days=93)
_ROOT_KEYS = {
    "accountable_owner_role",
    "applicable_gate_ids",
    "as_of_date",
    "assets",
    "authority_sources",
    "boundaries",
    "controls",
    "dependency_package_ids",
    "evidence_sources",
    "findings",
    "jurisdiction_applicability_authority",
    "jurisdictions",
    "legal_advice",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "regulatory_mappings",
    "risk_class",
    "roadmap_package",
    "schema_version",
    "threats",
}
_ASSET_KEYS = {"asset_id", "name", "owner_role", "security_objectives"}
_BOUNDARY_KEYS = {
    "asset_ids",
    "boundary_id",
    "control_ids",
    "destination_zone",
    "name",
    "owner_role",
    "source_zone",
    "trust_change",
}
_THREAT_KEYS = {
    "abuse_case",
    "actor",
    "asset_ids",
    "boundary_ids",
    "category",
    "control_ids",
    "impact",
    "owner_role",
    "threat_id",
    "title",
}
_CONTROL_KEYS = {
    "control_functions",
    "control_id",
    "domain",
    "evidence_source_ids",
    "fail_safe_response",
    "implementation_packages",
    "implementation_status",
    "independent_review_roles",
    "objective",
    "owner_role",
    "test_procedure",
    "title",
}
_EVIDENCE_KEYS = {
    "closure_condition",
    "evidence_source_id",
    "location",
    "name",
    "owner_role",
    "required_packages",
    "source_type",
    "status",
}
_AUTHORITY_KEYS = {
    "authority",
    "citation",
    "jurisdiction_id",
    "last_verified_on",
    "source_class",
    "source_id",
    "title",
    "url",
}
_JURISDICTION_KEYS = {
    "applicability_status",
    "jurisdiction_id",
    "legal_owner_role",
    "name",
    "review_due_on",
    "scope",
    "source_ids",
}
_MAPPING_KEYS = {
    "applicability_rationale",
    "applicability_status",
    "control_ids",
    "evidence_source_ids",
    "jurisdiction_id",
    "mapping_id",
    "owner_role",
    "source_ids",
    "topic",
}
_ID_PATTERNS = {
    "asset": re.compile(r"^ASSET[0-9]{2}$"),
    "boundary": re.compile(r"^TB[0-9]{2}$"),
    "control": re.compile(r"^A07-C[0-9]{2}$"),
    "evidence": re.compile(r"^A07-EV[0-9]{2}$"),
    "mapping": re.compile(r"^A07-MAP-[A-Z]+-[0-9]{2}$"),
    "source": re.compile(r"^A07-SRC-[A-Z]+-[0-9]{2}$"),
    "threat": re.compile(r"^A07-T[0-9]{2}$"),
}
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")
_LOWER_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_PACKAGE_ID = re.compile(r"^[A-L]0[1-8]$")
_COMMIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _require_table(value: object, *, context: str) -> dict[str, object]:
    """Require a parsed value to be a TOML table.

    Args:
        value: Parsed TOML value to narrow to a dictionary.
        context: Path-like label used in the validation diagnostic.

    Returns:
        The original dictionary object, without copying or changing its contents. The runtime check
        only validates dictionary shape; the cast assumes TOML parser input with string keys.

    Raises:
        SecurityControlError: If ``value`` is not a dictionary.
    """
    if not isinstance(value, dict):
        raise SecurityControlError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _require_table_list(value: object, *, context: str) -> list[dict[str, object]]:
    """Require a value to be a list whose items are TOML tables.

    Args:
        value: Parsed TOML value expected to contain table entries.
        context: Path-like label used in the validation diagnostic.

    Returns:
        The original list and dictionary objects in order; an empty list is accepted. The runtime
        check only validates list/dictionary shape; the cast assumes TOML string-keyed input.

    Raises:
        SecurityControlError: If ``value`` is not a list of dictionaries.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SecurityControlError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _require_string(
    table: dict[str, object], key: str, *, context: str, allow_empty: bool = False
) -> str:
    """Require a table field to contain a string with the selected emptiness rule.

    Args:
        table: Table whose value is inspected without mutation.
        key: Field name to retrieve with ``table.get``.
        context: Path-like label used in the validation diagnostic.
        allow_empty: Whether an empty or whitespace-only string is accepted. Defaults to
            ``False``; otherwise only the string type is required.

    Returns:
        The original string, including any surrounding whitespace.

    Raises:
        SecurityControlError: If the field is missing, is not a string, or is blank when
            ``allow_empty`` is false.
    """
    value = table.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise SecurityControlError([f"{context}.{key} must be {qualifier}"])
    return value


def _require_integer(table: dict[str, object], key: str, *, context: str) -> int:
    """Require a table field to contain an integer other than a Boolean.

    Args:
        table: Table whose value is inspected without mutation.
        key: Field name to retrieve with ``table.get``.
        context: Path-like label used in the validation diagnostic.

    Returns:
        The integer value unchanged.

    Raises:
        SecurityControlError: If the field is missing, non-integer, or Boolean.
    """
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SecurityControlError([f"{context}.{key} must be an integer"])
    return value


def _require_strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Require a unique list of non-empty strings and preserve its order.

    Args:
        value: Parsed TOML value expected to be a list of string values.
        context: Path-like label used in the validation diagnostic.
        allow_empty: Whether an empty list is accepted. Defaults to ``False``; individual
            empty strings remain invalid when this is true.

    Returns:
        A new tuple preserves values and list order; whitespace-only items pass.

    Raises:
        SecurityControlError: If the value is not a string list, contains an empty string, is
            empty when disallowed, or contains duplicate values.
    """
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SecurityControlError([f"{context} must be an array of non-empty strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise SecurityControlError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise SecurityControlError([f"{context} must contain unique values"])
    return values


def _require_entries(value: object, *, context: str, keys: set[str]) -> list[dict[str, object]]:
    """Require table entries to expose exactly a specified set of fields.

    Args:
        value: Parsed TOML value expected to be an array of tables.
        context: Path-like label used in the validation diagnostic.
        keys: Exact field names required on every table entry.

    Returns:
        The list returned by ``_require_table_list``, preserving entry order and dictionary
        identity without validating or copying field values. An empty list is accepted.

    Raises:
        SecurityControlError: If the value is not a table list or fields differ from ``keys``.
    """
    entries = _require_table_list(value, context=context)
    for index, entry in enumerate(entries, 1):
        if set(entry) != keys:
            raise SecurityControlError([f"{context}[{index}] has missing or unknown fields"])
    return entries


def _parse_iso_date(value: str, *, context: str) -> date:
    """Parse a date string only when its spelling is exactly ``YYYY-MM-DD``.

    Args:
        value: Date text supplied to ``date.fromisoformat``.
        context: Path-like label used in the validation diagnostic.

    Returns:
        The parsed calendar date.

    Raises:
        SecurityControlError: If parsing raises ``ValueError`` or text is not canonical
            extended-format.
    """
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError as error:
        raise SecurityControlError([f"{context} must use YYYY-MM-DD"]) from error
    if parsed_date.isoformat() != value:
        raise SecurityControlError([f"{context} must use YYYY-MM-DD"])
    return parsed_date


def _load_toml(path: Path) -> dict[str, object]:
    """Read a UTF-8 TOML file and require a table at its top level.

    Args:
        path: File to read as UTF-8 text.

    Returns:
        The newly parsed top-level TOML dictionary, retaining the parser's values and order.

    Raises:
        SecurityControlError: If TOML decoding fails or the parsed value is not a table.
        OSError: If reading ``path`` fails.
        UnicodeDecodeError: If the file is not valid UTF-8.
    """
    try:
        parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise SecurityControlError([f"{path}: invalid TOML: {error}"]) from error
    return _require_table(parsed_document, context=str(path))


def _ownership_roles(path: Path) -> frozenset[str]:
    """Load accountable, review, and escalation roles from an ownership register.

    Args:
        path: Ownership-register TOML file to read.

    Returns:
        A frozenset of role strings from every domain, deduplicated across domains and role
        fields; source order is not retained. Empty ``domains`` yields an empty frozenset; roles use
        ``[a-z][a-z0-9_]*``.

    Raises:
        SecurityControlError: If the TOML, domain tables, role fields, role-list uniqueness, or
            ``[a-z][a-z0-9_]*`` role pattern is invalid.
        OSError: If reading ``path`` fails.
        UnicodeDecodeError: If the file is not valid UTF-8.
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
    if any(_ROLE.fullmatch(role) is None for role in roles):
        raise SecurityControlError([f"{path}: ownership roles must be lower_snake_case"])
    return frozenset(roles)


def _validate_repository_path(
    value: str, *, repository_root: Path, context: str, findings: list[str]
) -> None:
    """Append a finding when a repository-relative value is not an in-root file.

    Compare the strictly resolved candidate with the caller-resolved absolute repository root;
    allow symlinks resolving to in-root files. Resolution and ``is_file`` are separate, non-atomic
    filesystem checks. A successful check leaves ``findings`` unchanged; failures append one
    diagnostic and return.

    Args:
        value: Path text checked lexically for absoluteness and ``..`` components.
        repository_root: Caller-resolved absolute root against which the candidate is compared.
        context: Label identifying the path field in a finding.
        findings: Mutable diagnostic list to extend on the first failed check.

    Raises:
        OSError: If filesystem access fails, except for a missing candidate path handled as a
            finding.
        RuntimeError: If strict resolution encounters a symlink loop.
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


def _validate_id_order(values: tuple[str, ...], *, kind: str, findings: list[str]) -> None:
    """Append findings for duplicate, unsorted, or malformed identifiers.

    Check uniqueness, ordinary lexicographic tuple order, and the configured full-match pattern in
    order. Empty sequences produce no finding; input stays unchanged, and only diagnostics are
    sorted or collected.

    Args:
        values: Identifier sequence to inspect; it is neither changed nor normalized.
        kind: Identifier category whose regular expression is used.
        findings: Mutable diagnostic list receiving findings in uniqueness, order, and format
            check order.

    Raises:
        KeyError: If ``kind`` is not a configured identifier category.
    """
    if len(values) != len(set(values)):
        findings.append(f"{kind} IDs must be unique")
    if values != tuple(sorted(values)):
        findings.append(f"{kind} entries must be ordered by ID")
    pattern = _ID_PATTERNS[kind]
    invalid = sorted(value for value in values if pattern.fullmatch(value) is None)
    if invalid:
        findings.append(f"{kind} IDs have invalid format: {invalid!r}")


def _validate_references(
    values: tuple[str, ...], *, allowed: frozenset[str], context: str, findings: list[str]
) -> None:
    """Append one finding for references absent from an allowed identifier set.

    Deduplicate and sort unknown identifiers only for diagnostics. An empty tuple or duplicate
    known values produces no finding; input values and order remain unchanged.

    Args:
        values: References to compare without changing their order or contents.
        allowed: Identifiers that may be referenced.
        context: Label identifying the reference field in a finding.
        findings: Mutable diagnostic list to extend when unknown identifiers exist.
    """
    unknown = sorted(set(values) - allowed)
    if unknown:
        findings.append(f"{context}: unknown references {unknown!r}")


def _validate_authority_url(source: AuthoritySource, *, findings: list[str]) -> None:
    """Append findings for an authority URL's shape and trusted host.

    Require the ``urlsplit``-parsed scheme to be ``https`` and the hostname to be non-empty and
    trusted for the source identifier. Reject credentials and numeric explicit ports, but accept
    an empty suffix such as ``https://host:`` because ``parsed_url.port`` is ``None``. Perform no
    network I/O. A parsing ``ValueError`` adds a malformed-URL finding and stops this check.

    Args:
        source: Authority record whose URL and source identifier are checked.
        findings: Mutable diagnostic list receiving URL validation findings.
    """
    try:
        parsed_url = urlsplit(source.url)
        explicit_port = parsed_url.port
    except ValueError:
        findings.append(f"{source.source_id}: source URL is malformed")
        return
    has_credentials = parsed_url.username is not None or parsed_url.password is not None
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or has_credentials
        or explicit_port is not None
    ):
        findings.append(
            f"{source.source_id}: source URL must use HTTPS without credentials and "
            "without an explicit port"
        )
    expected_host = _TRUSTED_AUTHORITY_HOSTS.get(source.source_id)
    if expected_host is None or parsed_url.hostname != expected_host:
        findings.append(
            f"{source.source_id}: source URL host must match its trusted official publisher"
        )


def _parse_assets(value: object) -> tuple[ProtectedAsset, ...]:
    """Parse asset tables into immutable protected-asset records.

    Args:
        value: Parsed TOML value expected to be an array of asset tables. Each table must expose
            exactly the fields in ``_ASSET_KEYS``.

    Returns:
        A tuple of newly constructed records in input order. Required scalar strings retain their
        original text; ``security_objectives`` is a tuple of unique, non-empty strings in its
        declared order. List members reject exact empty strings but accept whitespace-only text.
        Empty entry arrays are accepted, and exact-key shape validation completes before record
        construction begins. The parsed value and its entry mappings are not modified.

    Raises:
        SecurityControlError: If the value is not an array of tables, an entry has missing or
            unknown fields, or a required field/list item is invalid or duplicated. Record IDs
            are not required to be unique, ordered, or pattern-matching here; those are checked
            by the complete map loader.
    """
    return tuple(
        ProtectedAsset(
            asset_id=_require_string(entry, "asset_id", context=f"assets[{index}]"),
            name=_require_string(entry, "name", context=f"assets[{index}]"),
            owner_role=_require_string(entry, "owner_role", context=f"assets[{index}]"),
            security_objectives=_require_strings(
                entry.get("security_objectives"),
                context=f"assets[{index}].security_objectives",
            ),
        )
        for index, entry in enumerate(
            _require_entries(value, context="assets", keys=_ASSET_KEYS), 1
        )
    )


def _parse_boundaries(value: object) -> tuple[TrustBoundary, ...]:
    """Parse trust-boundary tables into immutable boundary records.

    Args:
        value: Parsed TOML value expected to be an array of boundary tables. Each table must
            expose exactly the fields in ``_BOUNDARY_KEYS``.

    Returns:
        A tuple of records in input order. Scalar zone, name, trust-change, owner, and identifier
        text is retained; ``asset_ids`` and ``control_ids`` become ordered tuples of unique,
        non-empty strings (exact empty members are rejected, while whitespace-only members pass).
        An empty array of entries is accepted, and all entry keys are checked before construction.
        The parsed value and its entry mappings are not modified.

    Raises:
        SecurityControlError: If the array/table shape, exact fields, required strings, or
            reference lists are invalid. This parser does not require source and destination
            zones to differ, resolve referenced assets or controls, or validate boundary ID
            uniqueness/order; the complete map loader performs those checks.
    """
    return tuple(
        TrustBoundary(
            boundary_id=_require_string(entry, "boundary_id", context=f"boundaries[{index}]"),
            name=_require_string(entry, "name", context=f"boundaries[{index}]"),
            source_zone=_require_string(entry, "source_zone", context=f"boundaries[{index}]"),
            destination_zone=_require_string(
                entry, "destination_zone", context=f"boundaries[{index}]"
            ),
            asset_ids=_require_strings(
                entry.get("asset_ids"), context=f"boundaries[{index}].asset_ids"
            ),
            trust_change=_require_string(entry, "trust_change", context=f"boundaries[{index}]"),
            owner_role=_require_string(entry, "owner_role", context=f"boundaries[{index}]"),
            control_ids=_require_strings(
                entry.get("control_ids"), context=f"boundaries[{index}].control_ids"
            ),
        )
        for index, entry in enumerate(
            _require_entries(value, context="boundaries", keys=_BOUNDARY_KEYS), 1
        )
    )


def _parse_threats(value: object) -> tuple[ThreatScenario, ...]:
    """Parse threat tables into immutable threat-scenario records.

    Args:
        value: Parsed TOML value expected to be an array of threat tables. Each table must expose
            exactly the fields in ``_THREAT_KEYS``.

    Returns:
        A tuple of records in input order. Required text fields retain their supplied spelling;
        boundary, asset, and control references become ordered tuples of unique, non-empty
        strings (exact empty members are rejected, while whitespace-only members pass). An empty
        entry array is accepted, and exact-key validation completes before record construction.
        The parsed value and its entry mappings are not modified.

    Raises:
        SecurityControlError: If the array/table shape, exact fields, required strings, or any
            reference list is invalid. Threat category membership, ID format/order/uniqueness,
            and cross-record reference resolution are loader-wide checks and are not performed.
    """
    return tuple(
        ThreatScenario(
            threat_id=_require_string(entry, "threat_id", context=f"threats[{index}]"),
            title=_require_string(entry, "title", context=f"threats[{index}]"),
            category=_require_string(entry, "category", context=f"threats[{index}]"),
            actor=_require_string(entry, "actor", context=f"threats[{index}]"),
            abuse_case=_require_string(entry, "abuse_case", context=f"threats[{index}]"),
            impact=_require_string(entry, "impact", context=f"threats[{index}]"),
            boundary_ids=_require_strings(
                entry.get("boundary_ids"), context=f"threats[{index}].boundary_ids"
            ),
            asset_ids=_require_strings(
                entry.get("asset_ids"), context=f"threats[{index}].asset_ids"
            ),
            control_ids=_require_strings(
                entry.get("control_ids"), context=f"threats[{index}].control_ids"
            ),
            owner_role=_require_string(entry, "owner_role", context=f"threats[{index}]"),
        )
        for index, entry in enumerate(
            _require_entries(value, context="threats", keys=_THREAT_KEYS), 1
        )
    )


def _parse_controls(value: object) -> tuple[SecurityControl, ...]:
    """Parse control tables into immutable security-control records.

    Args:
        value: Parsed TOML value expected to be an array of control tables. Each table must expose
            exactly the fields in ``_CONTROL_KEYS``.

    Returns:
        A tuple of records in input order. Scalar text is retained, while each role, function,
        implementation-package, and evidence-source list becomes an ordered tuple of unique,
        non-empty strings (exact empty members are rejected, while whitespace-only members pass).
        An empty entry array is accepted, and exact-key validation completes before construction.
        The parsed value and its entry mappings are not modified.

    Raises:
        SecurityControlError: If the array/table shape, exact fields, required strings, or list
            contents are invalid or duplicated. Supported function/package tokens, implementation
            status, evidence references, and owner/reviewer relationships are validated only by
            the complete map loader.
    """
    return tuple(
        SecurityControl(
            control_id=_require_string(entry, "control_id", context=f"controls[{index}]"),
            title=_require_string(entry, "title", context=f"controls[{index}]"),
            domain=_require_string(entry, "domain", context=f"controls[{index}]"),
            owner_role=_require_string(entry, "owner_role", context=f"controls[{index}]"),
            independent_review_roles=_require_strings(
                entry.get("independent_review_roles"),
                context=f"controls[{index}].independent_review_roles",
            ),
            objective=_require_string(entry, "objective", context=f"controls[{index}]"),
            control_functions=_require_strings(
                entry.get("control_functions"),
                context=f"controls[{index}].control_functions",
            ),
            implementation_packages=_require_strings(
                entry.get("implementation_packages"),
                context=f"controls[{index}].implementation_packages",
            ),
            implementation_status=_require_string(
                entry, "implementation_status", context=f"controls[{index}]"
            ),
            test_procedure=_require_string(entry, "test_procedure", context=f"controls[{index}]"),
            fail_safe_response=_require_string(
                entry, "fail_safe_response", context=f"controls[{index}]"
            ),
            evidence_source_ids=_require_strings(
                entry.get("evidence_source_ids"),
                context=f"controls[{index}].evidence_source_ids",
            ),
        )
        for index, entry in enumerate(
            _require_entries(value, context="controls", keys=_CONTROL_KEYS), 1
        )
    )


def _parse_evidence_sources(value: object) -> tuple[EvidenceSource, ...]:
    """Parse evidence-source tables into immutable evidence records.

    Args:
        value: Parsed TOML value expected to be an array of evidence-source tables. Each table
            must expose exactly the fields in ``_EVIDENCE_KEYS``.

    Returns:
        A tuple of records in input order. Required text is retained; ``location`` and
        ``closure_condition`` may be empty strings, and ``required_packages`` may be empty, but
        any supplied package string must be non-empty and unique. No entry is synthesized for an
        empty input array. Entry keys are checked for the whole array before records are built.
        The parsed value and its entry mappings are not modified.

    Raises:
        SecurityControlError: If the array/table shape, exact fields, required strings, or
            package-list contents are invalid or duplicated. Status vocabulary, package ID
            format, location containment, and available/deferred field combinations are checked
            by the complete map loader.
    """
    return tuple(
        EvidenceSource(
            evidence_source_id=_require_string(
                entry, "evidence_source_id", context=f"evidence_sources[{index}]"
            ),
            name=_require_string(entry, "name", context=f"evidence_sources[{index}]"),
            source_type=_require_string(entry, "source_type", context=f"evidence_sources[{index}]"),
            status=_require_string(entry, "status", context=f"evidence_sources[{index}]"),
            owner_role=_require_string(entry, "owner_role", context=f"evidence_sources[{index}]"),
            location=_require_string(
                entry, "location", context=f"evidence_sources[{index}]", allow_empty=True
            ),
            required_packages=_require_strings(
                entry.get("required_packages"),
                context=f"evidence_sources[{index}].required_packages",
                allow_empty=True,
            ),
            closure_condition=_require_string(
                entry,
                "closure_condition",
                context=f"evidence_sources[{index}]",
                allow_empty=True,
            ),
        )
        for index, entry in enumerate(
            _require_entries(value, context="evidence_sources", keys=_EVIDENCE_KEYS), 1
        )
    )


def _parse_authority_sources(value: object) -> tuple[AuthoritySource, ...]:
    """Parse authority-source tables into immutable citation records.

    Args:
        value: Parsed TOML value expected to be an array of authority-source tables. Each table
            must expose exactly the fields in ``_AUTHORITY_KEYS``.

    Returns:
        A tuple of records in input order. Required text fields retain their supplied spelling;
        each ``last_verified_on`` value is converted from canonical ``YYYY-MM-DD`` text to a
        ``date``. An empty entry array is accepted, and exact-key validation completes before
        record construction. The parsed value and its entry mappings are not modified. URL text
        is only required to be a non-blank string here; no URL parsing or network access occurs.

    Raises:
        SecurityControlError: If the array/table shape, exact fields, required text, or canonical
            date spelling is invalid. URL syntax/trusted-host checks, source-class vocabulary,
            and verification age relative to the map snapshot are loader-wide checks.
    """
    return tuple(
        AuthoritySource(
            source_id=_require_string(entry, "source_id", context=f"authority_sources[{index}]"),
            jurisdiction_id=_require_string(
                entry, "jurisdiction_id", context=f"authority_sources[{index}]"
            ),
            authority=_require_string(entry, "authority", context=f"authority_sources[{index}]"),
            title=_require_string(entry, "title", context=f"authority_sources[{index}]"),
            citation=_require_string(entry, "citation", context=f"authority_sources[{index}]"),
            source_class=_require_string(
                entry, "source_class", context=f"authority_sources[{index}]"
            ),
            url=_require_string(entry, "url", context=f"authority_sources[{index}]"),
            last_verified_on=_parse_iso_date(
                _require_string(entry, "last_verified_on", context=f"authority_sources[{index}]"),
                context=f"authority_sources[{index}].last_verified_on",
            ),
        )
        for index, entry in enumerate(
            _require_entries(value, context="authority_sources", keys=_AUTHORITY_KEYS), 1
        )
    )


def _parse_jurisdictions(value: object) -> tuple[JurisdictionProfile, ...]:
    """Parse jurisdiction tables into immutable applicability profiles.

    Args:
        value: Parsed TOML value expected to be an array of jurisdiction tables. Each table must
            expose exactly the fields in ``_JURISDICTION_KEYS``.

    Returns:
        A tuple of profiles in input order. Required text is retained, ``source_ids`` becomes an
        ordered tuple of unique, non-empty strings, and ``review_due_on`` becomes a
        ``date`` parsed from canonical ``YYYY-MM-DD`` text. Exact empty list members are rejected
        while whitespace-only members pass; an empty entry array is accepted after key validation.
        The parsed value and its entry mappings are not modified; text is not normalized.

    Raises:
        SecurityControlError: If the array/table shape, exact fields, required strings, source
            list, or canonical date is invalid. Required jurisdiction order, applicability
            status, source resolution, and review horizon are checked by the complete loader.
    """
    return tuple(
        JurisdictionProfile(
            jurisdiction_id=_require_string(
                entry, "jurisdiction_id", context=f"jurisdictions[{index}]"
            ),
            name=_require_string(entry, "name", context=f"jurisdictions[{index}]"),
            scope=_require_string(entry, "scope", context=f"jurisdictions[{index}]"),
            applicability_status=_require_string(
                entry, "applicability_status", context=f"jurisdictions[{index}]"
            ),
            legal_owner_role=_require_string(
                entry, "legal_owner_role", context=f"jurisdictions[{index}]"
            ),
            source_ids=_require_strings(
                entry.get("source_ids"), context=f"jurisdictions[{index}].source_ids"
            ),
            review_due_on=_parse_iso_date(
                _require_string(entry, "review_due_on", context=f"jurisdictions[{index}]"),
                context=f"jurisdictions[{index}].review_due_on",
            ),
        )
        for index, entry in enumerate(
            _require_entries(value, context="jurisdictions", keys=_JURISDICTION_KEYS), 1
        )
    )


def _parse_regulatory_mappings(value: object) -> tuple[RegulatoryMapping, ...]:
    """Parse regulatory-mapping tables into immutable mapping records.

    Args:
        value: Parsed TOML value expected to be an array of mapping tables. Each table must
            expose exactly the fields in ``_MAPPING_KEYS``.

    Returns:
        A tuple of records in input order. Required text is retained; source, control, and
        evidence references become ordered tuples of unique, non-empty strings (exact empty
        members are rejected, while whitespace-only members pass). An empty entry array is
        accepted after exact-key validation for all entries. The parsed value and its entry
        mappings are not modified.

    Raises:
        SecurityControlError: If the array/table shape, exact fields, required strings, or any
            reference list is invalid or duplicated. Mapping ID format/order, jurisdiction and
            reference resolution, applicability ownership/status, and evidence requirements are
            enforced by the complete map loader.
    """
    return tuple(
        RegulatoryMapping(
            mapping_id=_require_string(
                entry, "mapping_id", context=f"regulatory_mappings[{index}]"
            ),
            jurisdiction_id=_require_string(
                entry, "jurisdiction_id", context=f"regulatory_mappings[{index}]"
            ),
            topic=_require_string(entry, "topic", context=f"regulatory_mappings[{index}]"),
            source_ids=_require_strings(
                entry.get("source_ids"), context=f"regulatory_mappings[{index}].source_ids"
            ),
            control_ids=_require_strings(
                entry.get("control_ids"), context=f"regulatory_mappings[{index}].control_ids"
            ),
            applicability_status=_require_string(
                entry, "applicability_status", context=f"regulatory_mappings[{index}]"
            ),
            applicability_rationale=_require_string(
                entry, "applicability_rationale", context=f"regulatory_mappings[{index}]"
            ),
            owner_role=_require_string(
                entry, "owner_role", context=f"regulatory_mappings[{index}]"
            ),
            evidence_source_ids=_require_strings(
                entry.get("evidence_source_ids"),
                context=f"regulatory_mappings[{index}].evidence_source_ids",
            ),
        )
        for index, entry in enumerate(
            _require_entries(value, context="regulatory_mappings", keys=_MAPPING_KEYS), 1
        )
    )


def _load_control_map(
    path: Path, *, repository_root: Path, ownership_register_path: Path | None = None
) -> SecurityControlMap:
    """Load and validate the complete threat and regulatory control map."""
    resolved_root = repository_root.resolve()
    ownership_path = ownership_register_path or (
        resolved_root / "docs" / "governance" / "domain-ownership.toml"
    )
    ownership_roles = _ownership_roles(ownership_path)
    control_map_document = _load_toml(path)
    if set(control_map_document) != _ROOT_KEYS:
        raise SecurityControlError([f"{path}: fields must be exactly {sorted(_ROOT_KEYS)!r}"])
    schema_version = _require_integer(control_map_document, "schema_version", context=str(path))
    if schema_version != 1:
        raise SecurityControlError([f"{path}: schema_version must be 1"])
    roadmap_package = _require_string(control_map_document, "roadmap_package", context=str(path))
    operating_track = _require_string(control_map_document, "operating_track", context=str(path))
    accountable_owner_role = _require_string(
        control_map_document, "accountable_owner_role", context=str(path)
    )
    risk_class = _require_string(control_map_document, "risk_class", context=str(path))
    expected_strings = {
        "accountable_owner_role": (accountable_owner_role, "security"),
        "jurisdiction_applicability_authority": (
            _require_string(
                control_map_document, "jurisdiction_applicability_authority", context=str(path)
            ),
            "qualified_legal_compliance",
        ),
        "operating_track": (operating_track, "solo_bootstrap"),
        "risk_class": (risk_class, "R2"),
        "roadmap_package": (roadmap_package, "A07"),
    }
    for key, (actual, expected) in expected_strings.items():
        if actual != expected:
            raise SecurityControlError([f"{path}: {key} must be {expected!r}"])
    if control_map_document.get("legal_advice") is not False:
        raise SecurityControlError([f"{path}: legal_advice must be False"])
    dependency_package_ids = _require_strings(
        control_map_document.get("dependency_package_ids"), context="dependency_package_ids"
    )
    if dependency_package_ids != SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS:
        raise SecurityControlError(
            [f"dependency_package_ids must be exactly {SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS!r}"]
        )
    applicable_gate_ids = _require_strings(
        control_map_document.get("applicable_gate_ids"), context="applicable_gate_ids"
    )
    if applicable_gate_ids != APPLICABLE_GATE_IDS:
        raise SecurityControlError([f"applicable_gate_ids must be exactly {APPLICABLE_GATE_IDS!r}"])

    assets = _parse_assets(control_map_document.get("assets"))
    boundaries = _parse_boundaries(control_map_document.get("boundaries"))
    threats = _parse_threats(control_map_document.get("threats"))
    controls = _parse_controls(control_map_document.get("controls"))
    evidence_sources = _parse_evidence_sources(control_map_document.get("evidence_sources"))
    authority_sources = _parse_authority_sources(control_map_document.get("authority_sources"))
    jurisdictions = _parse_jurisdictions(control_map_document.get("jurisdictions"))
    regulatory_mappings = _parse_regulatory_mappings(
        control_map_document.get("regulatory_mappings")
    )
    as_of_date = _parse_iso_date(
        _require_string(control_map_document, "as_of_date", context=str(path)),
        context=f"{path}.as_of_date",
    )
    findings: list[str] = []

    id_groups = (
        ("asset", tuple(item.asset_id for item in assets)),
        ("boundary", tuple(item.boundary_id for item in boundaries)),
        ("threat", tuple(item.threat_id for item in threats)),
        ("control", tuple(item.control_id for item in controls)),
        ("evidence", tuple(item.evidence_source_id for item in evidence_sources)),
        ("source", tuple(item.source_id for item in authority_sources)),
        ("mapping", tuple(item.mapping_id for item in regulatory_mappings)),
    )
    for kind, identifiers in id_groups:
        _validate_id_order(identifiers, kind=kind, findings=findings)
    jurisdiction_ids = tuple(item.jurisdiction_id for item in jurisdictions)
    if jurisdiction_ids != JURISDICTION_IDS:
        findings.append(f"jurisdictions must be ordered and exactly {JURISDICTION_IDS!r}")

    asset_ids = frozenset(item.asset_id for item in assets)
    boundary_ids = frozenset(item.boundary_id for item in boundaries)
    control_ids = frozenset(item.control_id for item in controls)
    evidence_ids = frozenset(item.evidence_source_id for item in evidence_sources)
    source_ids = frozenset(item.source_id for item in authority_sources)
    jurisdiction_id_set = frozenset(jurisdiction_ids)
    evidence_status_by_id = {item.evidence_source_id: item.status for item in evidence_sources}

    used_roles: set[str] = set()
    for asset in assets:
        used_roles.add(asset.owner_role)
    for boundary in boundaries:
        used_roles.add(boundary.owner_role)
        if boundary.source_zone == boundary.destination_zone:
            findings.append(f"{boundary.boundary_id}: trust boundary zones must differ")
        _validate_references(
            boundary.asset_ids,
            allowed=asset_ids,
            context=f"{boundary.boundary_id}.asset_ids",
            findings=findings,
        )
        _validate_references(
            boundary.control_ids,
            allowed=control_ids,
            context=f"{boundary.boundary_id}.control_ids",
            findings=findings,
        )
    categories = frozenset(threat.category for threat in threats)
    if categories != frozenset(THREAT_CATEGORIES):
        findings.append(f"threats must cover exactly the required categories {THREAT_CATEGORIES!r}")
    for threat in threats:
        used_roles.add(threat.owner_role)
        _validate_references(
            threat.boundary_ids,
            allowed=boundary_ids,
            context=f"{threat.threat_id}.boundary_ids",
            findings=findings,
        )
        _validate_references(
            threat.asset_ids,
            allowed=asset_ids,
            context=f"{threat.threat_id}.asset_ids",
            findings=findings,
        )
        _validate_references(
            threat.control_ids,
            allowed=control_ids,
            context=f"{threat.threat_id}.control_ids",
            findings=findings,
        )
    for control in controls:
        used_roles.add(control.owner_role)
        used_roles.update(control.independent_review_roles)
        if control.owner_role in control.independent_review_roles:
            findings.append(f"{control.control_id}: owner cannot independently review its control")
        if any(
            function not in {"detect", "prevent", "recover", "respond"}
            for function in control.control_functions
        ):
            findings.append(f"{control.control_id}: unsupported control function")
        if control.implementation_status not in {"planned", "repository_local"}:
            findings.append(f"{control.control_id}: unsupported implementation_status")
        if any(_PACKAGE_ID.fullmatch(item) is None for item in control.implementation_packages):
            findings.append(f"{control.control_id}: implementation_packages must use A01-L08")
        _validate_references(
            control.evidence_source_ids,
            allowed=evidence_ids,
            context=f"{control.control_id}.evidence_source_ids",
            findings=findings,
        )
        control_evidence_statuses = {
            evidence_status_by_id[evidence_id]
            for evidence_id in control.evidence_source_ids
            if evidence_id in evidence_status_by_id
        }
        if (
            control.implementation_status == "repository_local"
            and "available" not in control_evidence_statuses
        ):
            findings.append(
                f"{control.control_id}: repository_local status requires available evidence"
            )
        if (
            control.implementation_status == "planned"
            and "deferred" not in control_evidence_statuses
        ):
            findings.append(f"{control.control_id}: planned status requires deferred evidence")
    for evidence in evidence_sources:
        used_roles.add(evidence.owner_role)
        if _LOWER_NAME.fullmatch(evidence.source_type) is None:
            findings.append(f"{evidence.evidence_source_id}: source_type must be lower_snake_case")
        if any(_PACKAGE_ID.fullmatch(item) is None for item in evidence.required_packages):
            findings.append(f"{evidence.evidence_source_id}: required_packages must use A01-L08")
        if evidence.status == "available":
            if not evidence.location or evidence.closure_condition:
                findings.append(
                    f"{evidence.evidence_source_id}: available evidence needs location and "
                    "no closure condition"
                )
            elif evidence.required_packages:
                findings.append(
                    f"{evidence.evidence_source_id}: available evidence cannot require "
                    "future packages"
                )
            else:
                _validate_repository_path(
                    evidence.location,
                    repository_root=resolved_root,
                    context=evidence.evidence_source_id,
                    findings=findings,
                )
        elif evidence.status == "deferred":
            if (
                evidence.location
                or not evidence.closure_condition
                or not evidence.required_packages
            ):
                findings.append(
                    f"{evidence.evidence_source_id}: deferred evidence needs packages and "
                    "closure condition, not a location"
                )
        else:
            findings.append(f"{evidence.evidence_source_id}: status must be available or deferred")

    sources_by_jurisdiction: dict[str, set[str]] = {
        jurisdiction_id: set() for jurisdiction_id in jurisdiction_ids
    }
    for source in authority_sources:
        if source.jurisdiction_id not in jurisdiction_id_set:
            findings.append(f"{source.source_id}: unknown jurisdiction")
        else:
            sources_by_jurisdiction[source.jurisdiction_id].add(source.source_id)
        _validate_authority_url(source, findings=findings)
        if source.source_class not in {
            "binding_rule",
            "statute",
            "supervisory_guidance",
            "reference_framework",
        }:
            findings.append(f"{source.source_id}: unsupported source_class")
        if source.last_verified_on > as_of_date:
            findings.append(f"{source.source_id}: last_verified_on cannot be after as_of_date")
        elif as_of_date - source.last_verified_on > _MAX_SOURCE_VERIFICATION_AGE:
            findings.append(
                f"{source.source_id}: authority-source verification is older than 31 days"
            )
    status_by_jurisdiction: dict[str, str] = {}
    legal_owner_by_jurisdiction: dict[str, str] = {}
    for jurisdiction in jurisdictions:
        used_roles.add(jurisdiction.legal_owner_role)
        expected_status = (
            "reference_only"
            if jurisdiction.jurisdiction_id == "GLOBAL"
            else "requires_legal_review"
        )
        if jurisdiction.applicability_status != expected_status:
            findings.append(
                f"{jurisdiction.jurisdiction_id}: applicability_status must be {expected_status!r}"
            )
        if set(jurisdiction.source_ids) != sources_by_jurisdiction[jurisdiction.jurisdiction_id]:
            findings.append(
                f"{jurisdiction.jurisdiction_id}: source_ids must match its authority sources"
            )
        review_horizon = jurisdiction.review_due_on - as_of_date
        if review_horizon <= timedelta(0):
            findings.append(f"{jurisdiction.jurisdiction_id}: legal review is overdue")
        elif review_horizon > _MAX_LEGAL_REVIEW_HORIZON:
            findings.append(f"{jurisdiction.jurisdiction_id}: legal review horizon exceeds 93 days")
        status_by_jurisdiction[jurisdiction.jurisdiction_id] = jurisdiction.applicability_status
        legal_owner_by_jurisdiction[jurisdiction.jurisdiction_id] = jurisdiction.legal_owner_role
    mapped_source_ids: set[str] = set()
    mapped_control_ids: set[str] = set()
    for mapping in regulatory_mappings:
        used_roles.add(mapping.owner_role)
        if mapping.jurisdiction_id not in jurisdiction_id_set:
            findings.append(f"{mapping.mapping_id}: unknown jurisdiction")
            continue
        if mapping.applicability_status != status_by_jurisdiction[mapping.jurisdiction_id]:
            findings.append(f"{mapping.mapping_id}: applicability status differs from profile")
        if mapping.owner_role != legal_owner_by_jurisdiction[mapping.jurisdiction_id]:
            findings.append(f"{mapping.mapping_id}: owner must match the jurisdiction legal owner")
        allowed_sources = frozenset(sources_by_jurisdiction[mapping.jurisdiction_id])
        _validate_references(
            mapping.source_ids,
            allowed=allowed_sources,
            context=f"{mapping.mapping_id}.source_ids",
            findings=findings,
        )
        _validate_references(
            mapping.control_ids,
            allowed=control_ids,
            context=f"{mapping.mapping_id}.control_ids",
            findings=findings,
        )
        _validate_references(
            mapping.evidence_source_ids,
            allowed=evidence_ids,
            context=f"{mapping.mapping_id}.evidence_source_ids",
            findings=findings,
        )
        if (
            mapping.applicability_status == "requires_legal_review"
            and "A07-EV15" not in mapping.evidence_source_ids
        ):
            findings.append(
                f"{mapping.mapping_id}: legal-review mapping requires A07-EV15 evidence"
            )
        if (
            mapping.applicability_status == "reference_only"
            and "A07-EV15" in mapping.evidence_source_ids
        ):
            findings.append(
                f"{mapping.mapping_id}: reference-only mapping cannot claim legal-review evidence"
            )
        mapped_source_ids.update(mapping.source_ids)
        mapped_control_ids.update(mapping.control_ids)
    if mapped_source_ids != source_ids:
        findings.append("every authority source must appear in a regulatory mapping")
    referenced_control_ids = (
        mapped_control_ids
        | {control_id for boundary in boundaries for control_id in boundary.control_ids}
        | {control_id for threat in threats for control_id in threat.control_ids}
    )
    if referenced_control_ids != control_ids:
        findings.append("every control must mitigate a boundary, threat, or regulatory mapping")
    referenced_asset_ids = {
        asset_id for boundary in boundaries for asset_id in boundary.asset_ids
    } | {asset_id for threat in threats for asset_id in threat.asset_ids}
    if referenced_asset_ids != asset_ids:
        findings.append("every protected asset must appear in a boundary or threat")
    referenced_boundary_ids = {
        boundary_id for threat in threats for boundary_id in threat.boundary_ids
    }
    if referenced_boundary_ids != boundary_ids:
        findings.append("every trust boundary must appear in a threat scenario")
    referenced_evidence_ids = {
        evidence_id for control in controls for evidence_id in control.evidence_source_ids
    } | {
        evidence_id
        for mapping in regulatory_mappings
        for evidence_id in mapping.evidence_source_ids
    }
    if referenced_evidence_ids != evidence_ids:
        findings.append("every evidence source must support a control or regulatory mapping")

    finding_values = _require_entries(
        control_map_document.get("findings"),
        context="findings",
        keys={"closure_condition", "finding_id", "owner_role", "unavailable_evidence"},
    )
    finding_ids: list[str] = []
    for index, finding in enumerate(finding_values, 1):
        context = f"findings[{index}]"
        finding_ids.append(_require_string(finding, "finding_id", context=context))
        used_roles.add(_require_string(finding, "owner_role", context=context))
        _require_string(finding, "unavailable_evidence", context=context)
        _require_string(finding, "closure_condition", context=context)
    open_finding_ids = _require_strings(
        control_map_document.get("open_finding_ids"), context="open_finding_ids"
    )
    if open_finding_ids != tuple(finding_ids):
        findings.append("open_finding_ids must exactly match findings")
    package_status = _require_string(control_map_document, "package_status", context=str(path))
    if package_status != "partial" or tuple(finding_ids) != _SECURITY_CONTROL_OPEN_FINDING_IDS:
        findings.append(
            f"solo-bootstrap A07 must remain partial with {_SECURITY_CONTROL_OPEN_FINDING_IDS!r}"
        )
    stale_roles = sorted(used_roles - ownership_roles)
    if stale_roles:
        findings.append(f"control map contains stale ownership roles: {stale_roles!r}")
    if findings:
        raise SecurityControlError(findings)

    manifest_path = _require_string(
        control_map_document, "local_evidence_manifest_path", context=str(path)
    )
    path_findings: list[str] = []
    _validate_repository_path(
        manifest_path,
        repository_root=resolved_root,
        context="local_evidence_manifest_path",
        findings=path_findings,
    )
    if path_findings:
        raise SecurityControlError(path_findings)
    commit_sha = _require_string(
        control_map_document, "local_evidence_commit_sha", context=str(path)
    )
    if _COMMIT_SHA.fullmatch(commit_sha) is None:
        raise SecurityControlError(["local_evidence_commit_sha must be a full lowercase SHA"])
    return SecurityControlMap(
        schema_version=schema_version,
        roadmap_package=roadmap_package,
        operating_track=operating_track,
        accountable_owner_role=accountable_owner_role,
        risk_class=risk_class,
        dependency_package_ids=dependency_package_ids,
        applicable_gate_ids=applicable_gate_ids,
        as_of_date=as_of_date,
        package_status=package_status,
        local_evidence_manifest_path=manifest_path,
        local_evidence_commit_sha=commit_sha,
        assets=assets,
        boundaries=boundaries,
        threats=threats,
        controls=controls,
        evidence_sources=evidence_sources,
        authority_sources=authority_sources,
        jurisdictions=jurisdictions,
        regulatory_mappings=regulatory_mappings,
        finding_ids=tuple(finding_ids),
    )


def load_control_map(
    path: Path, *, repository_root: Path, ownership_register_path: Path | None = None
) -> SecurityControlMap:
    """Load and cross-validate a security control map from UTF-8 TOML.

    The ownership register is loaded first from ``ownership_register_path`` or
    from ``docs/governance/domain-ownership.toml`` below the resolved
    ``repository_root``. The map is then checked for its exact root schema and
    fixed package metadata, followed by record parsing, canonical dates, ordered
    and unique IDs, cross-record references, control/evidence relationships,
    authority URL and freshness rules, jurisdiction and regulatory mapping
    consistency, ownership roles, coverage, package findings, and local evidence
    metadata. Authority freshness and legal-review horizons use the map's
    recorded ``as_of_date``, not the wall-clock date. Available-evidence
    locations and the local evidence manifest are checked as repository-relative
    in-root files; their contents are not loaded here.

    The function reads the ownership register and map as UTF-8 and performs
    local filesystem checks for referenced paths. It does not write files,
    make network requests, or validate the local evidence manifest contents.
    TOML decoding and Pydantic model failures are translated to
    ``SecurityControlError`` with their causes preserved.

    Args:
        path: UTF-8 TOML security-control map to load. A relative path is
            interpreted from the current working directory and is not rebased to
            ``repository_root``.
        repository_root: Repository root used to resolve and bound repository-relative
            evidence and manifest paths. Relative and symlinked roots are resolved
            before validation.
        ownership_register_path: Optional ownership-register TOML path. If omitted,
            it defaults to ``docs/governance/domain-ownership.toml`` below the
            resolved repository root. A supplied path is used as given; if relative,
            it is interpreted from the current working directory and is not rebased
            to ``repository_root``.

    Returns:
        The validated immutable ``SecurityControlMap`` after all validation checks
        pass. Record collections retain their source order, and the map's recorded
        open finding IDs remain in ``finding_ids``.

    Raises:
        SecurityControlError: If the ownership register or map has invalid TOML,
            schema, values, references, ordering, ownership, evidence, authority,
            or package findings. TOML decoding and Pydantic validation failures are
            translated here, while domain findings retain their ordered messages.
        OSError: If root or input-file resolution or reading fails, or an uncaught
            filesystem failure occurs while inspecting referenced evidence or
            manifest paths. Missing or out-of-root referenced paths are reported
            as ``SecurityControlError`` findings instead.
        UnicodeDecodeError: If the ownership register or map is not valid UTF-8.
        RuntimeError: If path resolution encounters a symbolic-link loop.
    """
    try:
        return _load_control_map(
            path,
            repository_root=repository_root,
            ownership_register_path=ownership_register_path,
        )
    except ValidationError as error:
        raise SecurityControlError([f"{path}: control-map model validation failed"]) from error


def _validate_local_evidence(repository_root: Path, control_map: SecurityControlMap) -> None:
    """Validate the synthetic R2 evidence without treating it as acceptance."""
    try:
        change_policy = load_change_risk_policy(
            repository_root / "docs" / "governance" / "change-risk-policy.toml"
        )
        manifest = validate_manifest(
            repository_root / control_map.local_evidence_manifest_path,
            expected_commit_sha=control_map.local_evidence_commit_sha,
            change_policy=change_policy,
        )
    except (OSError, ValueError) as error:
        raise SecurityControlError([f"A07 local evidence bundle: {error}"]) from error
    try:
        validate_package_evidence(manifest, _LOCAL_EVIDENCE_PROFILE)
    except EvidenceGovernanceError as error:
        raise SecurityControlError(error.findings) from error


def validate_repository(repository_root: Path) -> SecurityControlMap:
    """Validate the repository security map and its bound local evidence.

    The function resolves ``repository_root`` first, validates the authoritative
    map at ``docs/governance/security-control-map.toml`` through
    :func:`load_control_map`, and then loads the change-risk policy at
    ``docs/governance/change-risk-policy.toml``. It validates the map's
    SHA-bound local evidence manifest and its declared artifacts, then compares
    the result with the fixed A07 R2 partial package-evidence profile. Authority
    freshness and legal-review horizons use the map's recorded ``as_of_date``,
    not the wall-clock date. All operations are read-only and use local files; no
    files are written and no network requests or subprocesses are made.

    Map parsing and cross-record validation complete before local evidence
    validation starts. Map findings from ``load_control_map`` propagate as-is.
    Failures from the final evidence block are translated to one
    ``SecurityControlError`` with the original cause, including change-risk,
    manifest, package-profile, filesystem, decoding, and value failures.

    Args:
        repository_root: Repository root containing the authoritative security
            map, ownership register, change-risk policy, local evidence manifest,
            and its artifacts. Relative and symlinked roots are resolved before
            fixed paths are formed.

    Returns:
        The validated immutable ``SecurityControlMap`` after map and local evidence
        checks pass. Its records retain map order, and recorded open finding IDs
        remain retained in ``finding_ids``.

    Raises:
        SecurityControlError: If map validation reports findings, or if change-risk
            policy, local manifest, artifact, or A07 package-profile validation
            fails. Final evidence-block failures are translated with their causes;
            map findings from ``load_control_map`` retain their original messages.
        OSError: If root, map, or ownership resolution or reading fails, or an
            uncaught filesystem failure occurs while inspecting referenced evidence
            or manifest paths before the final evidence block. Filesystem failures
            in that block are translated to ``SecurityControlError``.
        UnicodeDecodeError: If a map or ownership file read before the final
            evidence block is not valid UTF-8. Final evidence decoding failures are
            translated to ``SecurityControlError``.
        RuntimeError: If path resolution encounters a symbolic-link loop.
    """
    resolved_repository_root = repository_root.resolve()
    control_map = load_control_map(
        resolved_repository_root / "docs" / "governance" / "security-control-map.toml",
        repository_root=resolved_repository_root,
    )
    _validate_local_evidence(resolved_repository_root, control_map)
    return control_map
