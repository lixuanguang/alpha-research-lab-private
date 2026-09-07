"""Load and enforce the dependency-admission contract for roadmap package B07."""

from __future__ import annotations

# standard library imports
import hashlib
import json
import re
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

# third party library imports
from pydantic import ValidationError

# project library imports
from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
    EmergencyOverride,
    PythonPackageAdmission,
    VulnerabilityDecision,
)
from alpha_research_governance.dependency_admission.wheel_sources import (
    parse_bootstrap_wheels,
    parse_wheel_sources,
    verify_bootstrap_wheels,
    verify_wheel_sources,
)
from alpha_research_governance.evidence import (
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
_DEPENDENCY_ADMISSION_OPEN_FINDING_IDS = ("B07-F01", "B07-F02", "B07-F03")
_EXPECTED_LOCK_PATHS = ("uv.lock",)
_ROOT_KEYS = {
    "accountable_owner_role",
    "applicable_gate_ids",
    "approved_python_indexes",
    "as_of_date",
    "emergency_override_maximum_days",
    "emergency_overrides",
    "findings",
    "license_groups",
    "local_evidence_commit_sha",
    "local_evidence_manifest_path",
    "lock_paths",
    "lock_digests",
    "maximum_signal_age_days",
    "native_python_packages",
    "open_finding_ids",
    "operating_track",
    "package_status",
    "patch_cadence_days",
    "pip_audit",
    "review_due_on",
    "risk_class",
    "roadmap_package",
    "runtime_installation_allowed",
    "runtime_scan_roots",
    "schema_version",
    "scorecard",
    "successor_package",
    "supported_platforms",
    "vulnerability_decisions",
}
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_PACKAGE_NAME = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
_COMPONENT_ID = re.compile(r"^[a-z][a-z0-9_-]*:[^\s]+(?:==|@|#)[^\s]+$")
_INSTALL_COMMAND = re.compile(
    r"(?im)(?:^|[;&|]\s*|(?:subprocess\.(?:run|call|Popen)|os\.(?:system|popen))\([^\n]*)"
    r"(?:python[\s\"',]+-m[\s\"',]+pip[\s\"',]+install|"
    r"pip(?:3)?[\s\"',]+install|uv[\s\"',]+(?:pip[\s\"',]+install|add))\b"
)
_WORKFLOW_USE = re.compile(r"(?m)^\s*-?\s*uses:\s*([^\s@]+)@([^\s#]+)")
_ACTION_PINS = {
    "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",
    "astral-sh/setup-uv": "c771a70e6277c0a99b617c7a806ffedaca235ff9",
    "sigstore/cosign-installer": "6f9f17788090df1f26f669e9d70d6ae9567deba6",
}
_APPROVED_PYTHON_LICENSES = {
    "Apache-2.0",
    "Apache-2.0 OR BSD-2-Clause",
    "Apache-2.0 OR BSD-3-Clause",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
    "ISC",
    "MIT",
    "MPL-2.0",
    "PSF-2.0",
}
_MAX_SIGNAL_BYTES = 5_000_000
_MAX_PIP_AUDIT_DEPENDENCIES = 1_000
_MAX_SCORECARD_CHECKS = 100
_LOCAL_EVIDENCE_PROFILE = PackageEvidenceProfile(
    roadmap_package_id="B07",
    accountable_owner_role="platform",
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
        PackageGateRequirement(gate_id=gate_id, status="passed") for gate_id in _APPLICABLE_GATES
    ),
    expected_package_status="partial",
    expected_finding_ids=_DEPENDENCY_ADMISSION_OPEN_FINDING_IDS,
    approvals_permitted=False,
    waivers_permitted=False,
    additional_required_gates_permitted=False,
)


def _table(value: object, *, context: str) -> dict[str, object]:
    """Require a parsed value to be a TOML table without deep validation.

    Args:
        value: Parsed TOML value expected to be a dictionary; its keys and nested values are not
            inspected here.
        context: Policy location used in a validation finding.

    Returns:
        The same dictionary object, narrowed for subsequent field access without copying it.

    Raises:
        DependencyAdmissionError: If ``value`` is not a dictionary.
    """
    if not isinstance(value, dict):
        raise DependencyAdmissionError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _tables(value: object, *, context: str) -> list[dict[str, object]]:
    """Require an ordered list of parsed TOML tables.

    Args:
        value: Parsed TOML value expected to be a list containing only dictionaries; an empty
            list is accepted and nested fields are not inspected here.
        context: Policy location used in a validation finding.

    Returns:
        The same list object, narrowed for ordered field access without copying its dictionaries.

    Raises:
        DependencyAdmissionError: If ``value`` is not a list or any element is not a dictionary.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Require an ordered list of unique, non-empty strings.

    Args:
        value: Parsed value expected to be a list of strings; string text is retained without
            stripping, so whitespace-only values are accepted.
        context: Policy location used in a validation finding.
        allow_empty: Whether to accept an empty list; individual empty strings remain invalid.

    Returns:
        A new tuple containing the supplied strings in their original order and text.

    Raises:
        DependencyAdmissionError: If the value is not a list of strings, contains an empty
            string or duplicate, or is empty when ``allow_empty`` is false.
    """
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise DependencyAdmissionError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise DependencyAdmissionError([f"{context} must contain unique values"])
    return values


def _iso_date(value: object, *, context: str) -> date:
    """Parse a canonical ISO extended calendar date.

    Args:
        value: Parsed TOML value expected to be a string written exactly as ``YYYY-MM-DD``.
        context: Policy location used in a validation finding.

    Returns:
        The parsed ``date`` value.

    Raises:
        DependencyAdmissionError: If ``value`` is not a string, is not a valid calendar date,
            or is not written in canonical ISO form; parser ``ValueError`` instances are
            translated and chained.
    """
    if not isinstance(value, str):
        raise DependencyAdmissionError([f"{context} must use YYYY-MM-DD"])
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DependencyAdmissionError([f"{context} must use YYYY-MM-DD"]) from error
    if parsed.isoformat() != value:
        raise DependencyAdmissionError([f"{context} must use YYYY-MM-DD"])
    return parsed


def _https_url(value: object, *, context: str) -> str:
    """Require a credential-free HTTPS URL with a non-empty hostname.

    Args:
        value: Parsed value expected to be a non-empty URL string; query and fragment text must
            be absent, while empty query or fragment delimiters are accepted.
        context: Policy location used in a validation finding.

    Returns:
        The original URL string after syntactic checks; no network request is made and the port
        is not inspected.

    Raises:
        DependencyAdmissionError: If the value is not a non-empty credential-free HTTPS URL with
            a hostname, or has a non-empty query or fragment.
        ValueError: If ``urlsplit`` rejects the URL syntax; this parser error propagates.
    """
    if not isinstance(value, str) or not value:
        raise DependencyAdmissionError([f"{context} must be a populated HTTPS URL"])
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DependencyAdmissionError([f"{context} must be a credential-free HTTPS URL"])
    return value


def _parse_package(
    value: str, *, license_expression: str, native_names: set[str]
) -> PythonPackageAdmission:
    """Parse an exact package identity and attach its license and native-artifact facts.

    The parser checks package-name syntax and a non-empty version only; it does not normalize
    names or validate full PEP 440 version semantics.

    Args:
        value: Package identity split at its first ``==`` into a validated name and non-empty
            version; name and version text are otherwise preserved for model validation.
        license_expression: Reviewed license expression to store on the package record.
        native_names: Package names designated as having native artifacts.

    Returns:
        A validated package admission whose native flag is true when the parsed name is in
        ``native_names``.

    Raises:
        DependencyAdmissionError: If ``value`` lacks the first exact separator, has an empty
            version, or has a name outside the accepted package-name syntax.
        ValidationError: If ``PythonPackageAdmission`` rejects the constructed record.
    """
    name, separator, version = value.partition("==")
    if separator != "==" or not version or _PACKAGE_NAME.fullmatch(name) is None:
        raise DependencyAdmissionError([f"invalid exact Python package identity: {value!r}"])
    return PythonPackageAdmission(
        name=name,
        version=version,
        license_expression=license_expression,
        native_artifacts=name in native_names,
    )


def _parse_decisions(
    value: object, *, as_of_date: date, maximum_days: int
) -> tuple[VulnerabilityDecision, ...]:
    """Parse vulnerability decisions within the policy assessment window.

    Args:
        value: Parsed ``vulnerability_decisions`` value expected to be an ordered list of
            tables. Each table must contain exactly the required decision fields.
        as_of_date: Inclusive lower bound for every decision expiry date.
        maximum_days: Inclusive upper-bound window, in days, after ``as_of_date``.

    Returns:
        Frozen decision models in input order; rationale text is stripped before model
        construction, while non-empty identity strings retain their original text, including
        surrounding whitespace. The input tables are not mutated and no network request is made.

    Raises:
        DependencyAdmissionError: If the value is not a list of tables, a table has unknown or
            missing fields, a disposition is not ``not_exploitable`` or
            ``temporary_exception``, rationale has fewer than 24 characters after stripping,
            expiry is outside the inclusive window, an identity is not a non-empty string, the
            owner is not ``security``, an evidence URL fails the HTTPS check, or a vulnerability
            ID is duplicated across the input sequence. Evidence URL violations are reported by
            the URL helper.
        ValueError: If URL parsing rejects malformed evidence URL authority syntax.
    """
    decisions: list[VulnerabilityDecision] = []
    required = {
        "affected_version",
        "disposition",
        "evidence_url",
        "expires_on",
        "owner_role",
        "package_name",
        "rationale",
        "vulnerability_id",
    }
    for index, entry in enumerate(_tables(value, context="vulnerability_decisions"), 1):
        context = f"vulnerability_decisions[{index}]"
        if set(entry) != required:
            raise DependencyAdmissionError([f"{context} has missing or unknown fields"])
        disposition = entry.get("disposition")
        rationale = entry.get("rationale")
        if disposition not in {"not_exploitable", "temporary_exception"}:
            raise DependencyAdmissionError([f"{context}.disposition is not permitted"])
        if not isinstance(rationale, str) or len(rationale.strip()) < 24:
            raise DependencyAdmissionError([f"{context}.rationale must be specific"])
        expires_on = _iso_date(entry.get("expires_on"), context=f"{context}.expires_on")
        if expires_on < as_of_date or expires_on > as_of_date + timedelta(days=maximum_days):
            raise DependencyAdmissionError([f"{context} expiry is stale or exceeds the limit"])
        string_fields = {
            key: entry.get(key)
            for key in ("affected_version", "owner_role", "package_name", "vulnerability_id")
        }
        if not all(isinstance(item, str) and item for item in string_fields.values()):
            raise DependencyAdmissionError([f"{context} identity fields must be populated strings"])
        if string_fields["owner_role"] != "security":
            raise DependencyAdmissionError([f"{context}.owner_role must be security"])
        decisions.append(
            VulnerabilityDecision(
                vulnerability_id=cast(str, string_fields["vulnerability_id"]),
                package_name=cast(str, string_fields["package_name"]),
                affected_version=cast(str, string_fields["affected_version"]),
                disposition=disposition,
                owner_role=string_fields["owner_role"],
                rationale=rationale.strip(),
                expires_on=expires_on,
                evidence_url=_https_url(
                    entry.get("evidence_url"), context=f"{context}.evidence_url"
                ),
            )
        )
    identities = tuple(decision.vulnerability_id for decision in decisions)
    if len(identities) != len(set(identities)):
        raise DependencyAdmissionError(["vulnerability decisions must have unique IDs"])
    return tuple(decisions)


def _parse_overrides(
    value: object, *, as_of_date: date, maximum_days: int
) -> tuple[EmergencyOverride, ...]:
    """Parse emergency overrides within the policy assessment window.

    Args:
        value: Parsed ``emergency_overrides`` value expected to be an ordered list of tables.
            Each table must contain exactly the required override fields.
        as_of_date: Inclusive lower bound for every override expiry date.
        maximum_days: Inclusive upper-bound window, in days, after ``as_of_date``.

    Returns:
        Frozen override models in input order; rationale text is stripped before model
        construction, while non-empty identity strings retain their original text, including
        surrounding whitespace. The input tables are not mutated and no network request is made.

    Raises:
        DependencyAdmissionError: If the value is not a list of tables, a table has unknown or
            missing fields, rationale has fewer than 24 characters after stripping, expiry is
            outside the inclusive window, an identity is not a non-empty string, the owner is not
            ``platform`` or ``security``, a component ID fails the exact identity pattern, an
            evidence URL fails the HTTPS check, or an override ID is duplicated across the input
            sequence. Evidence URL violations are reported by the URL helper.
        ValueError: If URL parsing rejects malformed evidence URL authority syntax.
    """
    overrides: list[EmergencyOverride] = []
    required = {
        "component_id",
        "evidence_url",
        "expires_on",
        "override_id",
        "owner_role",
        "rationale",
    }
    for index, entry in enumerate(_tables(value, context="emergency_overrides"), 1):
        context = f"emergency_overrides[{index}]"
        if set(entry) != required:
            raise DependencyAdmissionError([f"{context} has missing or unknown fields"])
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or len(rationale.strip()) < 24:
            raise DependencyAdmissionError([f"{context}.rationale must be specific"])
        expires_on = _iso_date(entry.get("expires_on"), context=f"{context}.expires_on")
        if expires_on < as_of_date or expires_on > as_of_date + timedelta(days=maximum_days):
            raise DependencyAdmissionError([f"{context} expiry is stale or exceeds the limit"])
        values = {key: entry.get(key) for key in ("component_id", "override_id", "owner_role")}
        if not all(isinstance(item, str) and item for item in values.values()):
            raise DependencyAdmissionError([f"{context} identity fields must be populated strings"])
        if values["owner_role"] not in {"platform", "security"}:
            raise DependencyAdmissionError([f"{context}.owner_role must be platform or security"])
        component_id = cast(str, values["component_id"])
        if _COMPONENT_ID.fullmatch(component_id) is None:
            raise DependencyAdmissionError([f"{context}.component_id must be an exact identity"])
        overrides.append(
            EmergencyOverride(
                override_id=cast(str, values["override_id"]),
                component_id=component_id,
                owner_role=values["owner_role"],
                rationale=rationale.strip(),
                expires_on=expires_on,
                evidence_url=_https_url(
                    entry.get("evidence_url"), context=f"{context}.evidence_url"
                ),
            )
        )
    identities = tuple(item.override_id for item in overrides)
    if len(identities) != len(set(identities)):
        raise DependencyAdmissionError(["emergency overrides must have unique IDs"])
    return tuple(overrides)


class DependencyPolicyLoader:
    """Load the dependency policy at one explicit file boundary."""

    def __init__(self, policy_path: Path) -> None:
        """Bind DependencyPolicyLoader collaborators without filesystem or process I/O.

        Args:
            policy_path: Policy path read only when ``load`` is called.
        """
        self.policy_path = policy_path

    def load(self) -> DependencyAdmission:
        """Load and validate the B07 dependency-admission TOML policy.

        Read ``path`` as UTF-8 TOML and enforce the fixed B07 metadata, root and nested
        schemas, policy dates and bounds, quality gates, supported platforms and index,
        lock surfaces and digests, package/license/native
        admissions, scanner and Scorecard pins, findings, decisions, overrides, and
        optional wheel-admission profiles. The wheel parsers validate claims only: this
        function does not read referenced evidence, hash artifacts, inspect lock files,
        invoke a verifier, query installed packages, or access the network. Policy dates
        define the assessment windows; this loader does not compare review or expiry dates
        with today.

        Returns:
            An immutable ``DependencyAdmission`` populated from the validated policy,
            including its exact package, lock, decision, and wheel-admission records.

        Raises:
            DependencyAdmissionError: If the TOML structure or any fixed metadata,
                schema, identity, ordering, date, digest, package, decision, override,
                or wheel-admission rule fails. TOML syntax failures are translated and
                chained; wheel-parser failures are translated by their parsers, and final
                policy-model validation failures are translated by this loader.
            OSError: If the policy file cannot be opened or read.
            UnicodeDecodeError: If the policy file is not valid UTF-8.
            ValueError: If URL parsing rejects malformed URL authority syntax.
            pydantic.ValidationError: If a parsed package record is rejected while its
                ``PythonPackageAdmission`` is constructed; wheel-record and final-policy
                model failures are translated to ``DependencyAdmissionError``.
        """
        path = self.policy_path
        try:
            raw_document: dict[str, object] = tomllib.loads(path.read_text(encoding="utf-8"))
            document = _table(raw_document, context=str(path))
        except tomllib.TOMLDecodeError as error:
            raise DependencyAdmissionError([f"{path}: invalid TOML: {error}"]) from error
        if not _ROOT_KEYS <= set(document) or set(document) - _ROOT_KEYS - {
            "wheel_source_admissions",
            "bootstrap_wheel_admissions",
        }:
            raise DependencyAdmissionError([f"{path}: has missing or unknown fields"])
        expected = {
            "accountable_owner_role": "platform",
            "operating_track": "solo_bootstrap",
            "package_status": "partial",
            "risk_class": "R2",
            "roadmap_package": "B07",
            "runtime_installation_allowed": False,
            "schema_version": 1,
            "successor_package": "B08",
        }
        for key, value in expected.items():
            if document.get(key) != value:
                raise DependencyAdmissionError([f"{path}: {key} must be {value!r}"])
        as_of_date = _iso_date(document.get("as_of_date"), context="as_of_date")
        review_due_on = _iso_date(document.get("review_due_on"), context="review_due_on")
        if review_due_on <= as_of_date or review_due_on > as_of_date + timedelta(days=90):
            raise DependencyAdmissionError(
                ["review_due_on must be within 90 days after as_of_date"]
            )
        maximum_signal_age_days = document.get("maximum_signal_age_days")
        maximum_override_days = document.get("emergency_override_maximum_days")
        patch_cadence_days = document.get("patch_cadence_days")
        if maximum_signal_age_days != 7 or maximum_override_days != 30 or patch_cadence_days != 30:
            raise DependencyAdmissionError(
                ["signal, override, and patch/EOL review bounds drifted"]
            )
        if (
            _strings(document.get("applicable_gate_ids"), context="applicable_gate_ids")
            != _APPLICABLE_GATES
        ):
            raise DependencyAdmissionError(["dependency admission must retain the exact R2 gates"])
        supported_platforms = _strings(
            document.get("supported_platforms"), context="supported_platforms"
        )
        if supported_platforms != ("darwin_arm64", "linux_x86_64"):
            raise DependencyAdmissionError(
                ["supported platforms must retain Darwin arm64 and Linux x86_64"]
            )
        indexes = _strings(
            document.get("approved_python_indexes"), context="approved_python_indexes"
        )
        if indexes != ("https://pypi.org/simple",):
            raise DependencyAdmissionError(["only the reviewed PyPI simple index is approved"])
        lock_paths = _strings(document.get("lock_paths"), context="lock_paths")
        if lock_paths != _EXPECTED_LOCK_PATHS:
            raise DependencyAdmissionError(
                ["lock_paths must cover the exact current lock surfaces"]
            )
        lock_digests = _table(document.get("lock_digests"), context="lock_digests")
        if set(lock_digests) != set(lock_paths) or any(
            not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in lock_digests.values()
        ):
            raise DependencyAdmissionError(["lock_digests must bind every lock surface by SHA-256"])
        runtime_scan_roots = _strings(
            document.get("runtime_scan_roots"), context="runtime_scan_roots"
        )
        if runtime_scan_roots != ("src", "tools"):
            raise DependencyAdmissionError(["runtime install scanning must cover src and tools"])

        native_names = set(
            _strings(
                document.get("native_python_packages"),
                context="native_python_packages",
                allow_empty=True,
            )
        )
        license_groups = _tables(document.get("license_groups"), context="license_groups")
        packages: list[PythonPackageAdmission] = []
        for index, group in enumerate(license_groups, 1):
            if set(group) != {"disposition", "license_expression", "packages"}:
                raise DependencyAdmissionError(
                    [f"license_groups[{index}] has missing or unknown fields"]
                )
            license_expression = group.get("license_expression")
            if group.get("disposition") != "approved" or not isinstance(license_expression, str):
                raise DependencyAdmissionError(
                    [f"license_groups[{index}] is not approved and identified"]
                )
            if license_expression not in _APPROVED_PYTHON_LICENSES:
                raise DependencyAdmissionError(
                    [f"license_groups[{index}] uses an unapproved license expression"]
                )
            group_packages = _strings(
                group.get("packages"), context=f"license_groups[{index}].packages"
            )
            if group_packages != tuple(sorted(group_packages)):
                raise DependencyAdmissionError([f"license_groups[{index}].packages must be sorted"])
            packages.extend(
                _parse_package(
                    item, license_expression=license_expression, native_names=native_names
                )
                for item in group_packages
            )
        package_names = tuple(package.name for package in packages)
        if len(package_names) != len(set(package_names)):
            raise DependencyAdmissionError(["Python package admissions must be unique"])
        if native_names != {package.name for package in packages if package.native_artifacts}:
            raise DependencyAdmissionError(
                ["native Python package declarations must match admitted packages"]
            )
        if {package.license_expression for package in packages} != _APPROVED_PYTHON_LICENSES:
            raise DependencyAdmissionError(["Python license decision groups are incomplete"])

        pip_audit = _table(document.get("pip_audit"), context="pip_audit")
        if pip_audit != {
            "command_mode": "exact_locked_graph",
            "failure_policy": "block_unresolved_findings_or_skips",
            "service": "pypi",
            "version": "2.10.1",
        }:
            raise DependencyAdmissionError(
                ["pip-audit must remain an exact, blocking signal boundary"]
            )
        scorecard = _table(document.get("scorecard"), context="scorecard")
        if scorecard != {
            "required_checks": ["License", "Maintained", "Pinned-Dependencies", "Vulnerabilities"],
            "signal_role": "advisory_input_not_admission_authority",
            "version": "5.5.0",
        }:
            raise DependencyAdmissionError(["OpenSSF Scorecard signal contract drifted"])

        evidence_sha = document.get("local_evidence_commit_sha")
        if not isinstance(evidence_sha, str) or _COMMIT.fullmatch(evidence_sha) is None:
            raise DependencyAdmissionError(
                ["local_evidence_commit_sha must be a full lowercase SHA"]
            )
        finding_ids = _strings(document.get("open_finding_ids"), context="open_finding_ids")
        findings = _tables(document.get("findings"), context="findings")
        if (
            finding_ids != _DEPENDENCY_ADMISSION_OPEN_FINDING_IDS
            or tuple(item.get("finding_id") for item in findings) != finding_ids
        ):
            raise DependencyAdmissionError(["partial B07 status requires the exact open findings"])
        finding_fields = {"closure_condition", "finding_id", "owner_role", "unavailable_evidence"}
        if any(
            set(item) != finding_fields
            or not all(isinstance(field, str) and field for field in item.values())
            for item in findings
        ):
            raise DependencyAdmissionError(["B07 findings must use exact populated fields"])

        decisions = _parse_decisions(
            document.get("vulnerability_decisions"),
            as_of_date=as_of_date,
            maximum_days=maximum_override_days,
        )
        admitted_versions = {package.name: package.version for package in packages}
        if any(
            admitted_versions.get(decision.package_name) != decision.affected_version
            for decision in decisions
        ):
            raise DependencyAdmissionError(
                ["vulnerability decisions must match an exact admitted package version"]
            )
        overrides = _parse_overrides(
            document.get("emergency_overrides"),
            as_of_date=as_of_date,
            maximum_days=maximum_override_days,
        )

        wheel_sources = parse_wheel_sources(
            document.get("wheel_source_admissions", []), tuple(packages), _APPROVED_PYTHON_LICENSES
        )
        bootstrap_wheels = parse_bootstrap_wheels(
            document.get("bootstrap_wheel_admissions", []),
            tuple(packages),
            _APPROVED_PYTHON_LICENSES,
            as_of_date=as_of_date,
            review_due_on=review_due_on,
        )
        if {record.name for record in wheel_sources} & {record.name for record in bootstrap_wheels}:
            raise DependencyAdmissionError(["a package cannot use both wheel admission profiles"])

        try:
            return DependencyAdmission(
                package_status="partial",
                successor_package="B08",
                as_of_date=as_of_date,
                review_due_on=review_due_on,
                pip_audit_version="2.10.1",
                vulnerability_service="pypi",
                scorecard_version="5.5.0",
                maximum_signal_age_days=maximum_signal_age_days,
                emergency_override_maximum_days=maximum_override_days,
                supported_platforms=supported_platforms,
                approved_python_indexes=indexes,
                lock_paths=lock_paths,
                lock_digests=tuple((path, cast(str, lock_digests[path])) for path in lock_paths),
                runtime_scan_roots=runtime_scan_roots,
                packages=tuple(packages),
                vulnerability_decisions=decisions,
                emergency_overrides=overrides,
                applicable_gate_ids=_APPLICABLE_GATES,
                local_evidence_manifest_path=cast(str, document["local_evidence_manifest_path"]),
                local_evidence_commit_sha=evidence_sha,
                open_finding_ids=finding_ids,
                wheel_source_admissions=wheel_sources,
                bootstrap_wheel_admissions=bootstrap_wheels,
            )
        except ValidationError as error:
            raise DependencyAdmissionError([f"{path}: model validation failed"]) from error


class DependencyReportEvaluator:
    """Evaluate scanner reports against one admitted dependency policy."""

    def __init__(self, policy: DependencyAdmission) -> None:
        """Bind DependencyReportEvaluator collaborators without filesystem or process I/O.

        Args:
            policy: Already validated policy object owned by the service.
        """
        self.policy = policy

    def assess_pip_audit_report(
        self,
        report_path: Path,
        *,
        validation_date: date | None = None,
    ) -> None:
        """Assess a bounded pip-audit JSON report against the admitted lock and decisions.

        Consume the already-produced report through the shared JSON loader. Require the exact root
        fields and array types, then compare each usable dependency name and version
        with the policy's
        admitted package mapping. Resolve each vulnerability ID against the policy's owned decisions
        and require an exact package/version match with an expiry on or after the validation date.
        This function checks the decision fields it uses; it neither revalidates nor fetches a
        decision's evidence URL, and it does not establish vulnerability exploitability.
        It reads the report and policy without mutating either value and performs no
        scanner, network, or decision
        evidence I/O.

        Args:
            report_path: UTF-8 JSON report path. The loader checks the pre-read file size against
                5,000,000 bytes before reading it; the report must decode to an object whose exact
                root keys are ``dependencies`` and ``fixes``. Both values must be arrays, and the
                dependency array may contain at most 1,000 entries. A dependency counts toward
                coverage only when it is a mapping with a string ``name``, a string ``version``, and
                a list ``vulns``; a present ``skip_reason`` records a finding instead. Extra fields
                in dependency or vulnerability mappings are accepted, and the contents of ``fixes``
                are not inspected.
            validation_date: Date used for decision expiry checks; defaults to ``date.today()`` when
                omitted. A decision is current when ``expires_on`` equals this date or is later.

        Returns:
            ``None`` after every admitted package is covered exactly once and every reported
            vulnerability has a matching, current decision.

        Raises:
            DependencyAdmissionError: If the report exceeds the size limit, fails JSON or UTF-8
                loading, has the wrong root shape, has non-array ``dependencies`` or ``fixes``, or
                exceeds 1,000 dependencies. These envelope, shape, and size failures are raised
                immediately. For a structurally valid report, malformed, unnamed, skipped,
                incomplete, duplicate, or unresolved dependency entries become findings in traversal
                order; a missing, unexpected, or misversioned package adds the final coverage
                finding. Vulnerability findings are unresolved when their ID is absent,
                their decision
                does not match the exact package and version, or the decision has expired. If that
                finding list is non-empty after traversal, raise one ``DependencyAdmissionError``
                containing those findings.
            OSError: If report ``stat`` or read operations fail.
            ValueError: If the JSON decoder raises a non-syntax value error, such as an oversized
                integer, while loading the report.
            RecursionError: If JSON nesting exceeds the decoder's recursion limit.
        """
        policy = self.policy
        report = _load_json_signal(report_path, signal="pip-audit")
        if not isinstance(report, dict):
            raise DependencyAdmissionError(["pip-audit report has missing or unknown root fields"])
        report_object = cast(dict[str, object], report)
        if set(report_object) != {"dependencies", "fixes"}:
            raise DependencyAdmissionError(["pip-audit report has missing or unknown root fields"])
        raw_dependencies = report_object.get("dependencies")
        if not isinstance(raw_dependencies, list) or not isinstance(
            report_object.get("fixes"), list
        ):
            raise DependencyAdmissionError(["pip-audit dependencies must be an array"])
        dependencies = cast(list[object], raw_dependencies)
        if len(dependencies) > _MAX_PIP_AUDIT_DEPENDENCIES:
            raise DependencyAdmissionError(["pip-audit dependency count exceeds the limit"])
        expected = {package.name: package.version for package in policy.packages}
        observed: dict[str, str] = {}
        findings: list[str] = []
        decisions = {
            decision.vulnerability_id: decision for decision in policy.vulnerability_decisions
        }
        today = date.today() if validation_date is None else validation_date
        for index, item in enumerate(dependencies, 1):
            if not isinstance(item, dict):
                findings.append(f"pip-audit dependency {index} is malformed")
                continue
            dependency = cast(dict[str, object], item)
            name = dependency.get("name")
            if not isinstance(name, str):
                findings.append(f"pip-audit dependency {index} has no name")
                continue
            if "skip_reason" in dependency:
                findings.append(f"pip-audit skipped dependency {name}")
                continue
            version = dependency.get("version")
            raw_vulnerabilities = dependency.get("vulns")
            vulnerabilities = (
                cast(list[object], raw_vulnerabilities)
                if isinstance(raw_vulnerabilities, list)
                else None
            )
            if not isinstance(version, str) or not isinstance(vulnerabilities, list):
                findings.append(f"pip-audit dependency {name} is incomplete")
                continue
            if name in observed:
                findings.append(f"pip-audit reported duplicate dependency {name}")
                continue
            observed[name] = version
            for vulnerability in vulnerabilities:
                vulnerability_id = None
                if isinstance(vulnerability, dict):
                    vulnerability_object = cast(dict[str, object], vulnerability)
                    vulnerability_id = vulnerability_object.get("id")
                decision = (
                    decisions.get(vulnerability_id) if isinstance(vulnerability_id, str) else None
                )
                if (
                    decision is None
                    or decision.package_name != name
                    or decision.affected_version != version
                    or decision.expires_on < today
                ):
                    findings.append(
                        f"{name}=={version} has unresolved vulnerability {vulnerability_id!r}"
                    )
        if observed != expected:
            mismatches = sorted(
                name for name in set(expected) & set(observed) if expected[name] != observed[name]
            )
            findings.append(
                "pip-audit coverage differs from the admitted lock: "
                f"missing={sorted(set(expected) - set(observed))}, "
                f"unexpected={sorted(set(observed) - set(expected))}, "
                f"version_mismatches={mismatches}"
            )
        if findings:
            raise DependencyAdmissionError(findings)

    def assess_scorecard_report(
        self,
        report_path: Path,
        *,
        expected_repository: str,
        expected_commit: str,
        validation_time: datetime | None = None,
    ) -> None:
        """Assess a bounded Scorecard JSON report for identity, freshness, and required checks.

        Consume the already-produced report through the shared JSON loader and validate its
        repository binding, admitted tool version, timestamp, and required check records. Parse the
        report timestamp with ``datetime.fromisoformat`` after replacing every ``Z`` with
        ``+00:00``; this accepts a broader syntax than strict RFC 3339, but the resulting timestamp
        must be timezone-aware. Treat a passing result as an advisory signal: do not apply an
        aggregate score threshold, authenticate the repository or engine commit, or use
        the signal as dependency admission. Read the report and policy without mutating
        either value and perform no
        external network or evidence I/O.

        Args:
            report_path: UTF-8 JSON report path. The loader checks the pre-read file size against
                5,000,000 bytes before reading it. The decoded value must be an object containing
                mapping values for ``repo`` and ``scorecard`` and a list value for ``checks``; the
                check list may contain at most 100 entries. Extra report, repository, scorecard, and
                check fields are accepted.
            expected_repository: Repository name that must equal ``repo["name"]`` exactly. The value
                is not normalized or otherwise authenticated.
            expected_commit: Expected repository revision that must equal ``repo["commit"]`` exactly
                and must be a full lowercase 40-character hexadecimal SHA. The report's
                ``scorecard["commit"]`` is separately required to have that same shape, but is not
                compared with this revision or with a policy pin.
            validation_time: Time against which the report timestamp is checked; defaults to the
                current UTC time. Supply a timezone-aware ``datetime`` so aware report
                timestamps can
                be compared; a naive or otherwise incompatible value can cause ``TypeError``.

        Returns:
            ``None`` after the report is bound to the expected repository commit, uses the admitted
            Scorecard version, is neither future-dated nor older than the policy's inclusive age
            window, and contains all required conclusive checks.

        Raises:
            DependencyAdmissionError: If report loading fails, the decoded report is not an object,
                ``repo`` or ``scorecard`` is not a mapping, ``checks`` is not a list, or
                the list has
                more than 100 entries. The function then rejects a repository name or commit that
                does not exactly match the supplied values, an invalid expected commit, an
                unadmitted Scorecard version, an engine commit that is not lowercase 40-hex text, or
                a missing or unparsable timestamp. It also rejects a naive, future-dated, or stale
                timestamp; duplicate qualifying check names; and missing or negative
                required checks.
                A qualifying check is any mapping with a string ``name`` and an ``int`` ``score``;
                malformed entries without both fields are ignored. Unknown names still qualify and
                participate in duplicate-name rejection, while only ``License``, ``Maintained``,
                ``Pinned-Dependencies``, and ``Vulnerabilities`` are required to have nonnegative
                scores. ``bool`` scores satisfy the runtime ``int`` check, scores have no
                upper bound, and the report's aggregate score is unused. The function
                raises directly in validation
                order, rejecting duplicate names during traversal and missing or negative required
                checks afterward; it does not collect findings.
            OSError: If report ``stat`` or read operations fail.
            ValueError: If the JSON decoder raises a non-syntax value error while
                loading the report.
            RecursionError: If JSON nesting exceeds the decoder's recursion limit.
            TypeError: If ``validation_time`` is naive or otherwise incompatible with an aware
                report timestamp during freshness comparison.
        """
        policy = self.policy
        report = _load_json_signal(report_path, signal="Scorecard")
        if not isinstance(report, dict):
            raise DependencyAdmissionError(["Scorecard report must be a JSON object"])
        report_object = cast(dict[str, object], report)
        repository = report_object.get("repo")
        scorecard = report_object.get("scorecard")
        checks = report_object.get("checks")
        if (
            not isinstance(repository, dict)
            or not isinstance(scorecard, dict)
            or not isinstance(checks, list)
        ):
            raise DependencyAdmissionError(
                ["Scorecard report is missing repo, scorecard, or checks"]
            )
        repository = cast(dict[str, object], repository)
        scorecard = cast(dict[str, object], scorecard)
        checks = cast(list[object], checks)
        if len(checks) > _MAX_SCORECARD_CHECKS:
            raise DependencyAdmissionError(["Scorecard check count exceeds the limit"])
        repository_name = repository.get("name")
        repository_commit = repository.get("commit")
        if repository_name != expected_repository or repository_commit != expected_commit:
            raise DependencyAdmissionError(
                ["Scorecard report is not bound to the expected repository commit"]
            )
        if _COMMIT.fullmatch(expected_commit) is None:
            raise DependencyAdmissionError(
                ["expected Scorecard commit must be a full lowercase SHA"]
            )
        if scorecard.get("version") != policy.scorecard_version:
            raise DependencyAdmissionError(["Scorecard signal uses an unadmitted tool version"])
        scorecard_commit = scorecard.get("commit")
        if not isinstance(scorecard_commit, str) or _COMMIT.fullmatch(scorecard_commit) is None:
            raise DependencyAdmissionError(["Scorecard signal has no immutable engine commit"])
        raw_date = report_object.get("date")
        if not isinstance(raw_date, str):
            raise DependencyAdmissionError(["Scorecard report date is missing"])
        try:
            generated_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError as error:
            raise DependencyAdmissionError(["Scorecard report date is not RFC 3339"]) from error
        now = datetime.now(UTC) if validation_time is None else validation_time
        if (
            generated_at.tzinfo is None
            or generated_at > now
            or now - generated_at > timedelta(days=policy.maximum_signal_age_days)
        ):
            raise DependencyAdmissionError(["Scorecard signal is future-dated or stale"])
        observed: dict[str, int] = {}
        for item in checks:
            if not isinstance(item, dict):
                continue
            check = cast(dict[str, object], item)
            if isinstance(check.get("name"), str) and isinstance(check.get("score"), int):
                name = cast(str, check["name"])
                if name in observed:
                    raise DependencyAdmissionError([f"Scorecard check {name!r} is duplicated"])
                observed[name] = cast(int, check["score"])
        required = {"License", "Maintained", "Pinned-Dependencies", "Vulnerabilities"}
        if set(observed) & required != required or any(observed[name] < 0 for name in required):
            raise DependencyAdmissionError(
                ["Scorecard required checks are missing or inconclusive"]
            )


class DependencyRepositoryValidator:
    """Validate repository dependency surfaces and release admission."""

    def __init__(self, repository_root: Path, policy: DependencyAdmission | None = None) -> None:
        """Bind DependencyRepositoryValidator collaborators without filesystem or process I/O.

        Args:
            repository_root: Repository root used by later service operations.
            policy: Already validated policy object owned by the service.
        """
        self.repository_root = repository_root
        self.policy = policy

    def require_release_admission(self) -> None:
        """Require release admission for the repository's dependency lock boundary.

        Resolve ``repository_root`` strictly, load the dependency policy, and reject
        immediately when it contains any bootstrap-wheel admission. That short-circuit
        occurs before reading ``uv.lock``, checking the current date, or hashing the
        admitted lock surfaces. Otherwise, collect Python lock findings, append a
        stale-review finding when ``review_due_on`` is before ``date.today()``, then
        hash each policy-listed lock path in its admitted order and append digest
        mismatches before raising one combined error.

        The Python lock checks cover the admitted external package set, versions,
        registry source, supplied wheel and source digests, platform heuristics, and
        dependency edges. Delegated wheel verifiers compare the locked wheel set and
        supplied digests with retained local provenance and may authenticate claims
        with Cosign; they do not download or recompute wheel or source-archive bytes
        and do not repeat parser-level cross-record checks. Policy, lock, evidence,
        and digest operations read repository files without mutating them. A
        source-bound verifier may stage a temporary trust root and invoke a local
        Cosign subprocess with no shell, a ``PATH``-only environment, and no offline
        flag, so this function does not establish network-free execution. This gate
        is narrower than ``validate_repository``: it hashes every admitted lock path
        but does not run runtime-install scans or external audit signals.

        The repository root is bound by the service constructor.

        Raises:
            DependencyAdmissionError: If policy loading, bootstrap use, Python lock or
                provenance checks, review freshness, or an admitted lock digest fails.
            OSError: If strict root resolution or a policy, lock, evidence, digest, or
                temporary-verifier filesystem operation fails.
            RuntimeError: If strict root resolution encounters a symlink loop.
            UnicodeDecodeError: If a required text policy or lock file is not UTF-8.
            tomllib.TOMLDecodeError: If ``uv.lock`` is not valid TOML; policy TOML
                syntax errors are translated to ``DependencyAdmissionError``.
            ValueError: If URL parsing or another verifier operation raises an
                untranslated value error.
        """
        root = self.repository_root.resolve(strict=True)
        policy = (
            self.policy
            or DependencyPolicyLoader(root / "docs/architecture/dependency-admission.toml").load()
        )
        if policy.bootstrap_wheel_admissions:
            names = ", ".join(record.name for record in policy.bootstrap_wheel_admissions)
            raise DependencyAdmissionError(
                [f"bootstrap-only dependencies block artifact release: {names}"]
            )
        # Removing a bootstrap record must not turn its unprovenanced locked wheel into a release.
        findings = DependencyRepositoryInspector(root, policy)._python_lock_findings()
        if policy.review_due_on < date.today():
            findings.append("dependency admission review is stale")
        for relative, expected_digest in policy.lock_digests:
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected_digest:
                findings.append(f"{relative} differs from its admitted SHA-256 digest")
        if findings:
            raise DependencyAdmissionError(findings)

    def validate_repository(self, *, validation_date: date | None = None) -> DependencyAdmission:
        """Validate the B07 policy, repository dependency surfaces, and local evidence.

        Resolve ``repository_root`` strictly, load its policy, and use ``validation_date``
        or ``date.today()`` for bootstrap-wheel effectiveness, review freshness, and
        emergency-override expiry. A review deadline or override expiry equal to the
        chosen date remains valid because the checks flag only dates before it. Collect
        findings in order from the Python lock graph and configured ``src``/``tools``
        runtime-install scans. Then check policy-listed lock digests, the exact
        ``pip-audit==2.10.1`` development dependency, and required integration fragments.
        A non-empty finding list is raised together. When those checks pass, validate the
        repository change-risk policy, local evidence manifest and artifact digests, and
        the exact B07 package-evidence profile before returning the policy.

        The repository checks read files and do not mutate them. An optional wheel profile
        can cause retained evidence reads and a local Cosign subprocess through the lock
        helper; verifier domain failures become package-prefixed findings there, while
        unrelated I/O, decoding, parsing, URL, and temporary-resource failures propagate.
        This function does not run pip-audit or Scorecard, query installed package metadata,
        or install packages, and its Cosign path does not guarantee network-free execution.

        Args:
            validation_date: Date used for bootstrap validity, review freshness, and
                override expiry; defaults to ``date.today()`` when omitted.

        Returns:
            The validated immutable ``DependencyAdmission`` policy when repository checks
            report no findings and evidence validation succeeds.

        Raises:
            DependencyAdmissionError: If policy loading fails, repository checks produce
                findings, or policy-bound wheel and dependency-admission evidence fails.
                Findings from the repository scans and digest checks are aggregated; domain
                failures translated by wheel verifiers are included through that boundary.
            EvidenceGovernanceError: If the local evidence manifest, its artifact digests,
                or the B07 package-evidence profile fails after repository findings clear.
            ChangeRiskPolicyError: If the policy-bound change-risk policy cannot be loaded
                or validated.
            OSError: If strict root resolution or an uncaught repository, evidence,
                lock-digest, temporary-resource, or integration-file operation fails.
            RuntimeError: If repository or evidence-bundle path resolution encounters a
                symlink loop.
            UnicodeDecodeError: If an uncaught repository, policy, lock,
                integration, source, or evidence text file is not valid UTF-8.
            tomllib.TOMLDecodeError: If an uncaught repository TOML document, including
                a lock or ``pyproject.toml``, is malformed. Policy,
                change-risk, and evidence-manifest TOML syntax is translated by its
                respective loader.
            ValueError: If URL parsing or another helper operation raises an untranslated
                value error.
        """
        root = self.repository_root.resolve(strict=True)
        policy = (
            self.policy
            or DependencyPolicyLoader(root / "docs/architecture/dependency-admission.toml").load()
        )
        today = date.today() if validation_date is None else validation_date
        inspector = DependencyRepositoryInspector(root, policy)
        findings = (
            inspector._python_lock_findings(validation_date=today)
            + inspector._lock_surface_findings()
            + inspector._runtime_install_findings()
        )
        if policy.review_due_on < today:
            findings.append("dependency admission review is stale")
        for override in policy.emergency_overrides:
            if override.expires_on < today:
                findings.append(f"emergency override {override.override_id} is expired")
        for relative, expected_digest in policy.lock_digests:
            observed_digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            if observed_digest != expected_digest:
                findings.append(f"{relative} differs from its admitted SHA-256 digest")
        pyproject: dict[str, object] = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )
        groups = _table(pyproject.get("dependency-groups", {}), context="dependency-groups")
        dev = _strings(groups.get("dev", []), context="dependency-groups.dev", allow_empty=True)
        if "pip-audit==2.10.1" not in dev:
            findings.append("pyproject.toml is missing exact pip-audit 2.10.1 admission")
        integrations = {
            "Makefile": (
                "dependency-admission-check:",
                "dependency-audit:",
                "alpha-governance-dependencies",
            ),
            ".github/workflows/ci.yml": ("make source-check",),
            "tools/governance/pyproject.toml": ("alpha-governance-dependencies",),
        }
        for relative, fragments in integrations.items():
            text = (root / relative).read_text(encoding="utf-8")
            missing = [fragment for fragment in fragments if fragment not in text]
            if missing:
                findings.append(f"{relative} is missing dependency-admission interfaces: {missing}")
        if findings:
            raise DependencyAdmissionError(findings)
        manifest = validate_manifest(
            root / policy.local_evidence_manifest_path,
            expected_commit_sha=policy.local_evidence_commit_sha,
            change_policy=load_change_risk_policy(root / "docs/governance/change-risk-policy.toml"),
        )
        validate_package_evidence(manifest, _LOCAL_EVIDENCE_PROFILE)
        return policy


def load_policy(path: Path) -> DependencyAdmission:
    """Load and validate the B07 dependency-admission TOML policy.

    Read ``path`` as UTF-8 TOML and enforce the fixed B07 metadata, root and nested
    schemas, policy dates and bounds, quality gates, supported platforms and index,
    lock surfaces and digests, package/license/native
    admissions, scanner and Scorecard pins, findings, decisions, overrides, and
    optional wheel-admission profiles. The wheel parsers validate claims only: this
    function does not read referenced evidence, hash artifacts, inspect lock files,
    invoke a verifier, query installed packages, or access the network. Policy dates
    define the assessment windows; this loader does not compare review or expiry dates
    with today.

    Args:
        path: UTF-8 TOML policy file to read and validate. The file is not modified.

    Returns:
        An immutable ``DependencyAdmission`` populated from the validated policy,
        including its exact package, lock, decision, and wheel-admission records.

    Raises:
        DependencyAdmissionError: If the TOML structure or any fixed metadata,
            schema, identity, ordering, date, digest, package, decision, override,
            or wheel-admission rule fails. TOML syntax failures are translated and
            chained; wheel-parser failures are translated by their parsers, and final
            policy-model validation failures are translated by this loader.
        OSError: If the policy file cannot be opened or read.
        UnicodeDecodeError: If the policy file is not valid UTF-8.
        ValueError: If URL parsing rejects malformed URL authority syntax.
        pydantic.ValidationError: If a parsed package record is rejected while its
            ``PythonPackageAdmission`` is constructed; wheel-record and final-policy
            model failures are translated to ``DependencyAdmissionError``.
    """
    return DependencyPolicyLoader(path).load()


def _locked_python_packages(path: Path) -> dict[str, dict[str, object]]:
    """Load named package entries from a uv lock at the admitted schema boundary.

    The package list may be empty. Schema markers use ordinary equality, so their values are not
    independently type-checked.

    Args:
        path: UTF-8 ``uv.lock`` file to read and parse; its root must be a dictionary and its
            package collection must be a list of dictionaries.

    Returns:
        A new mapping from each string package name to its original parsed package dictionary;
        entries with non-string names are skipped, while an empty string name is retained.

    Raises:
        DependencyAdmissionError: If the root or package collection has the wrong shape, the
            schema markers (``version == 1``, ``revision == 3`` and
            ``requires-python == '==3.12.*'``) do not compare equal, or a usable name repeats.
        OSError: If reading the lock file fails.
        UnicodeDecodeError: If the lock file is not valid UTF-8.
        tomllib.TOMLDecodeError: If the lock file contains invalid TOML.
    """
    parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    document = _table(parsed_document, context=str(path))
    if (
        document.get("version") != 1
        or document.get("revision") != 3
        or document.get("requires-python") != "==3.12.*"
    ):
        raise DependencyAdmissionError(["uv.lock schema or Python boundary drifted"])
    packages: dict[str, dict[str, object]] = {}
    for item in _tables(document.get("package"), context="uv.lock.package"):
        name = item.get("name")
        if isinstance(name, str):
            if name in packages:
                raise DependencyAdmissionError([f"uv.lock contains duplicate package {name}"])
            packages[name] = item
    return packages


def _wheel_platform_findings(
    package: PythonPackageAdmission, locked: dict[str, object]
) -> list[str]:
    """Check locked wheel URLs for the required platform coverage heuristically.

    A missing, non-list, or empty ``wheels`` value yields the no-locked-artifacts finding. A
    non-empty list with no usable URL strings proceeds to the applicable coverage finding.

    Args:
        package: Admitted package whose native-artifact flag selects the coverage rule.
        locked: Parsed lock entry containing the candidate ``wheels`` value.

    Returns:
        An empty list when coverage is found, otherwise a list containing the first missing-wheel
        finding. Native checks first seek ``macosx`` with ``arm64`` or ``universal2``, then
        ``manylinux`` or ``musllinux`` with ``x86_64`` in URL text. Non-native checks require a
        ``-none-any.whl`` or ``-any.whl`` suffix. Malformed wheel items or URL fields are skipped;
        no wheel-tag parser, URL parser, or network request is used.
    """
    wheels = locked.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return [f"{package.name} has no locked wheel artifacts"]
    urls: list[str] = []
    for item in wheels:
        if isinstance(item, dict):
            url = item.get("url")
            if isinstance(url, str):
                urls.append(url)
    if package.native_artifacts:
        if not any("macosx" in url and ("arm64" in url or "universal2" in url) for url in urls):
            return [f"{package.name} lacks a Darwin arm64 native wheel"]
        if not any(("manylinux" in url or "musllinux" in url) and "x86_64" in url for url in urls):
            return [f"{package.name} lacks a Linux x86_64 native wheel"]
    elif not any(url.endswith("-none-any.whl") or url.endswith("-any.whl") for url in urls):
        return [f"{package.name} lacks a platform-independent wheel"]
    return []


class DependencyRepositoryInspector:
    """Own repository lock and installation-scan workflows."""

    def __init__(self, repository_root: Path, policy: DependencyAdmission | None = None) -> None:
        """Bind DependencyRepositoryInspector collaborators without filesystem or process I/O.

        Args:
            repository_root: Repository root used by later service operations.
            policy: Already validated policy object owned by the service.
        """
        self.repository_root = repository_root
        self.policy = policy

    def _python_lock_findings(self, *, validation_date: date | None = None) -> list[str]:
        """Collect findings for the admitted Python lock graph.

        Args:
            validation_date: Date passed to bootstrap-wheel verification; when omitted, the verifier
                uses the current date, while source-bound profiles do not use this argument.

        Returns:
            Findings in deterministic order: external-name mismatch first, then each admitted
            package
            in policy order, with version, source, evidence, digest, platform, and dependency-edge
            checks in their execution order. Wheel-verifier domain findings are returned with a
            package prefix. Source-bound or bootstrap profiles can read retained local evidence and,
            through their verifier, invoke the pinned local Cosign executable. The policy and lock
            inputs are not mutated.

        Raises:
            DependencyAdmissionError: If ``uv.lock`` has an invalid shape, schema, or duplicate
                usable package name. Domain failures from wheel verifiers are caught and converted
                into findings; their non-domain filesystem, parsing, or process errors propagate.
            OSError: If lock or wheel-evidence filesystem operations fail outside translated
                verifier boundaries.
            UnicodeDecodeError: If a read lock or evidence file is not valid UTF-8.
            tomllib.TOMLDecodeError: If ``uv.lock`` is not valid TOML.
            ValueError: If URL parsing or another verifier operation raises an untranslated value
                error.
        """
        root = self.repository_root
        policy = self.policy
        if policy is None:
            raise ValueError("dependency repository inspector requires an admitted policy")
        locked = _locked_python_packages(root / "uv.lock")
        findings: list[str] = []
        external_names = {
            name
            for name, item in locked.items()
            if item.get("source") in ({"registry": "https://pypi.org/simple"},)
        }
        admitted = {package.name for package in policy.packages}
        wheel_sources = {record.name: record for record in policy.wheel_source_admissions}
        bootstrap_wheels = {record.name: record for record in policy.bootstrap_wheel_admissions}
        if external_names != admitted:
            findings.append(
                "uv.lock external packages and dependency admissions differ: "
                f"missing={sorted(external_names - admitted)}, "
                f"stale={sorted(admitted - external_names)}"
            )
        for package in policy.packages:
            item = locked.get(package.name)
            if item is None or item.get("version") != package.version:
                findings.append(
                    f"{package.name} is not locked at admitted version {package.version}"
                )
                continue
            source = item.get("source")
            if source != {"registry": "https://pypi.org/simple"}:
                findings.append(f"{package.name} uses an unapproved package source")
            sdist = item.get("sdist")
            if package.name in wheel_sources:
                try:
                    verify_wheel_sources(root, item, wheel_sources[package.name])
                except DependencyAdmissionError as error:
                    findings.extend(f"{package.name}: {finding}" for finding in error.findings)
            elif package.name in bootstrap_wheels:
                try:
                    verify_bootstrap_wheels(
                        root,
                        item,
                        bootstrap_wheels[package.name],
                        validation_date=date.today()
                        if validation_date is None
                        else validation_date,
                    )
                except DependencyAdmissionError as error:
                    findings.extend(f"{package.name}: {finding}" for finding in error.findings)
            elif (
                not isinstance(sdist, dict)
                or not isinstance(sdist.get("hash"), str)
                or _HASH.fullmatch(cast(str, sdist["hash"])) is None
            ):
                findings.append(f"{package.name} lacks a digest-bound source distribution")
            wheels = item.get("wheels")
            if not isinstance(wheels, list) or any(
                not isinstance(wheel, dict)
                or not isinstance(wheel.get("hash"), str)
                or _HASH.fullmatch(cast(str, wheel["hash"])) is None
                for wheel in wheels
            ):
                findings.append(f"{package.name} has a wheel without a SHA-256 digest")
            findings.extend(_wheel_platform_findings(package, item))
            dependencies = item.get("dependencies", [])
            if not isinstance(dependencies, list):
                findings.append(f"{package.name} dependency edges are malformed")
                continue
            for dependency in dependencies:
                if not isinstance(dependency, dict) or dependency.get("name") not in locked:
                    findings.append(f"{package.name} has an unresolved transitive dependency")
        return findings

    def _lock_surface_findings(self) -> list[str]:
        """Validate immutable GitHub Action revisions used by the uv workflow.

        The Python dependency graph and its single ``uv.lock`` digest are checked by
        ``_python_lock_findings`` and the caller. This method only validates workflow action
        references, keeping CI provenance useful without making a second build system a policy
        prerequisite.

        Returns:
            Findings in workflow order for mutable or unexpected action revisions.

        Raises:
            OSError: If the workflow cannot be read.
            UnicodeDecodeError: If the workflow is not valid UTF-8.
        """
        root = self.repository_root
        findings: list[str] = []
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        observed_actions: dict[str, set[str]] = {}
        workflow_uses = cast(list[tuple[str, str]], _WORKFLOW_USE.findall(workflow))
        for action, revision in workflow_uses:
            observed_actions.setdefault(action, set()).add(revision)
            if _COMMIT.fullmatch(revision) is None:
                findings.append(f"GitHub Action {action} uses mutable reference {revision!r}")
        if observed_actions != {action: {revision} for action, revision in _ACTION_PINS.items()}:
            findings.append("GitHub Action set or immutable commit admission drifted")
        return findings

    def _runtime_install_findings(self) -> list[str]:
        """Scan configured source roots for textual runtime-install command matches.

        Search raw file text with the module's ``_INSTALL_COMMAND`` regular expression, so this
        helper reports only the command forms that pattern recognizes rather than every possible
        package installation.

        Returns:
            Findings for matching ``.py``, ``.sh``, ``.bash`` and ``.zsh`` files, ordered by scan
            root and lexical path. Missing roots can yield no findings; source text is matched
            directly, including comments and docstrings, without parsing or executing Python or
            shell code.

        Raises:
            OSError: If an uncaught filesystem traversal or source-read error occurs.
            UnicodeDecodeError: If a scanned source file is not valid UTF-8.
        """
        root = self.repository_root
        policy = self.policy
        if policy is None:
            raise ValueError("dependency repository inspector requires an admitted policy")
        findings: list[str] = []
        for relative_root in policy.runtime_scan_roots:
            scan_root = root / relative_root
            for path in sorted(scan_root.rglob("*")):
                if not path.is_file() or path.suffix not in {".py", ".sh", ".bash", ".zsh"}:
                    continue
                if _INSTALL_COMMAND.search(path.read_text(encoding="utf-8")):
                    findings.append(
                        "runtime package installation is prohibited: "
                        f"{path.relative_to(root).as_posix()}"
                    )
        return findings


def _python_lock_findings(
    root: Path, policy: DependencyAdmission, *, validation_date: date | None = None
) -> list[str]:
    """Compatibility facade delegating to ``DependencyRepositoryInspector``."""
    return DependencyRepositoryInspector(root, policy)._python_lock_findings(
        validation_date=validation_date
    )


def require_release_admission(repository_root: Path) -> None:
    """Require release admission for the repository's dependency lock boundary.

    Resolve ``repository_root`` strictly, load the dependency policy, and reject
    immediately when it contains any bootstrap-wheel admission. That short-circuit
    occurs before reading ``uv.lock``, checking the current date, or hashing the
    admitted lock surfaces. Otherwise, collect Python lock findings, append a
    stale-review finding when ``review_due_on`` is before ``date.today()``, then
    hash each policy-listed lock path in its admitted order and append digest
    mismatches before raising one combined error.

    The Python lock checks cover the admitted external package set, versions,
    registry source, supplied wheel and source digests, platform heuristics, and
    dependency edges. Delegated wheel verifiers compare the locked wheel set and
    supplied digests with retained local provenance and may authenticate claims
    with Cosign; they do not download or recompute wheel or source-archive bytes
    and do not repeat parser-level cross-record checks. Policy, lock, evidence,
    and digest operations read repository files without mutating them. A
    source-bound verifier may stage a temporary trust root and invoke a local
    Cosign subprocess with no shell, a ``PATH``-only environment, and no offline
    flag, so this function does not establish network-free execution. This gate
    is narrower than ``validate_repository``: it hashes every admitted lock path
    but does not inspect runtime-install scans or external audit signals.

    Args:
        repository_root: Existing repository directory whose policy, lock, evidence,
            and admitted lock surfaces are evaluated.

    Returns:
        ``None`` after release-admission checks pass.

    Raises:
        DependencyAdmissionError: If policy loading, bootstrap use, Python lock or
            provenance checks, review freshness, or an admitted lock digest fails.
        OSError: If strict root resolution or a policy, lock, evidence, digest, or
            temporary-verifier filesystem operation fails.
        RuntimeError: If strict root resolution encounters a symlink loop.
        UnicodeDecodeError: If a required text policy or lock file is not UTF-8.
        tomllib.TOMLDecodeError: If ``uv.lock`` is not valid TOML; policy TOML
            syntax errors are translated to ``DependencyAdmissionError``.
        ValueError: If URL parsing or another verifier operation raises an
            untranslated value error.
    """
    return DependencyRepositoryValidator(repository_root).require_release_admission()


def _lock_surface_findings(root: Path) -> list[str]:
    """Compatibility facade delegating to ``DependencyRepositoryInspector``."""
    return DependencyRepositoryInspector(root)._lock_surface_findings()


def _runtime_install_findings(root: Path, policy: DependencyAdmission) -> list[str]:
    """Compatibility facade delegating to ``DependencyRepositoryInspector``."""
    return DependencyRepositoryInspector(root, policy)._runtime_install_findings()


def _load_json_signal(report_path: Path, *, signal: str) -> object:
    """Load a JSON signal after checking its reported byte size.

    Check ``_MAX_SIGNAL_BYTES`` (5,000,000 bytes) from a pre-read ``stat`` result before reading
    the complete file. The check does not bound streaming, prevent a later file growth, or
    provide an atomic size guarantee.

    Args:
        report_path: UTF-8 JSON report path to inspect and read.
        signal: Signal label included in size and decoding diagnostics.

    Returns:
        The JSON decoder result without shape validation, duplicate-key rejection, or finite
        number enforcement; the default decoder therefore permits non-finite constants.

    Raises:
        DependencyAdmissionError: If the pre-read ``stat`` size exceeds ``_MAX_SIGNAL_BYTES``,
            or JSON syntax or UTF-8 decoding fails; translated errors retain their causes.
        OSError: Propagates from ``stat`` or the full text read.
        ValueError: Propagates from other decoder conversions such as an oversized integer.
        RecursionError: If JSON nesting exceeds the decoder's recursion limit.
    """
    try:
        if report_path.stat().st_size > _MAX_SIGNAL_BYTES:
            raise DependencyAdmissionError([f"{signal} report exceeds the size limit"])
        parsed_report: object = json.loads(report_path.read_text(encoding="utf-8"))
        return parsed_report
    except json.JSONDecodeError as error:
        raise DependencyAdmissionError([f"invalid {signal} JSON: {error}"]) from error
    except UnicodeDecodeError as error:
        raise DependencyAdmissionError([f"invalid {signal} text encoding"]) from error


def assess_pip_audit_report(
    report_path: Path,
    policy: DependencyAdmission,
    *,
    validation_date: date | None = None,
) -> None:
    """Assess a bounded pip-audit JSON report against the admitted lock and decisions.

    Consume the already-produced report through the shared JSON loader. Require the exact root
    fields and array types, then compare each usable dependency name and version with the policy's
    admitted package mapping. Resolve each vulnerability ID against the policy's owned decisions
    and require an exact package/version match with an expiry on or after the validation date.
    This function checks the decision fields it uses; it neither revalidates nor fetches a
    decision's evidence URL, and it does not establish vulnerability exploitability. It reads the
    report and policy without mutating either value and performs no scanner, network, or decision
    evidence I/O.

    Args:
        report_path: UTF-8 JSON report path. The loader checks the pre-read file size against
            5,000,000 bytes before reading it; the report must decode to an object whose exact
            root keys are ``dependencies`` and ``fixes``. Both values must be arrays, and the
            dependency array may contain at most 1,000 entries. A dependency counts toward
            coverage only when it is a mapping with a string ``name``, a string ``version``, and
            a list ``vulns``; a present ``skip_reason`` records a finding instead. Extra fields
            in dependency or vulnerability mappings are accepted, and the contents of ``fixes``
            are not inspected.
        policy: Validated admission policy supplying the exact package-name/version mapping and
            vulnerability decisions. Package names, versions, vulnerability IDs, decision package
            names, and decision affected versions are compared as their original strings without
            normalization. Decision disposition, owner, rationale, and evidence URL are not
            consulted by this function because the policy loader owns their validation.
        validation_date: Date used for decision expiry checks; defaults to ``date.today()`` when
            omitted. A decision is current when ``expires_on`` equals this date or is later.

    Returns:
        ``None`` after every admitted package is covered exactly once and every reported
        vulnerability has a matching, current decision.

    Raises:
        DependencyAdmissionError: If the report exceeds the size limit, fails JSON or UTF-8
            loading, has the wrong root shape, has non-array ``dependencies`` or ``fixes``, or
            exceeds 1,000 dependencies. These envelope, shape, and size failures are raised
            immediately. For a structurally valid report, malformed, unnamed, skipped,
            incomplete, duplicate, or unresolved dependency entries become findings in traversal
            order; a missing, unexpected, or misversioned package adds the final coverage
            finding. Vulnerability findings are unresolved when their ID is absent, their decision
            does not match the exact package and version, or the decision has expired. If that
            finding list is non-empty after traversal, raise one ``DependencyAdmissionError``
            containing those findings.
        OSError: If report ``stat`` or read operations fail.
        ValueError: If the JSON decoder raises a non-syntax value error, such as an oversized
            integer, while loading the report.
        RecursionError: If JSON nesting exceeds the decoder's recursion limit.
    """
    return DependencyReportEvaluator(policy).assess_pip_audit_report(
        report_path, validation_date=validation_date
    )


def assess_scorecard_report(
    report_path: Path,
    *,
    expected_repository: str,
    expected_commit: str,
    policy: DependencyAdmission,
    validation_time: datetime | None = None,
) -> None:
    """Assess a bounded Scorecard JSON report for identity, freshness, and required checks.

    Consume the already-produced report through the shared JSON loader and validate its
    repository binding, admitted tool version, timestamp, and required check records. Parse the
    report timestamp with ``datetime.fromisoformat`` after replacing every ``Z`` with
    ``+00:00``; this accepts a broader syntax than strict RFC 3339, but the resulting timestamp
    must be timezone-aware. Treat a passing result as an advisory signal: do not apply an
    aggregate score threshold, authenticate the repository or engine commit, or use the signal as
    dependency admission. Read the report and policy without mutating either value and perform no
    external network or evidence I/O.

    Args:
        report_path: UTF-8 JSON report path. The loader checks the pre-read file size against
            5,000,000 bytes before reading it. The decoded value must be an object containing
            mapping values for ``repo`` and ``scorecard`` and a list value for ``checks``; the
            check list may contain at most 100 entries. Extra report, repository, scorecard, and
            check fields are accepted.
        expected_repository: Repository name that must equal ``repo["name"]`` exactly. The value
            is not normalized or otherwise authenticated.
        expected_commit: Expected repository revision that must equal ``repo["commit"]`` exactly
            and must be a full lowercase 40-character hexadecimal SHA. The report's
            ``scorecard["commit"]`` is separately required to have that same shape, but is not
            compared with this revision or with a policy pin.
        policy: Validated admission policy supplying the exact Scorecard version and the maximum
            accepted signal age in days. Treat the policy as already validated; this function
            reads only those two fields and does not authenticate external evidence.
        validation_time: Time against which the report timestamp is checked; defaults to the
            current UTC time. Supply a timezone-aware ``datetime`` so aware report timestamps can
            be compared; a naive or otherwise incompatible value can cause ``TypeError``.

    Returns:
        ``None`` after the report is bound to the expected repository commit, uses the admitted
        Scorecard version, is neither future-dated nor older than the policy's inclusive age
        window, and contains all required conclusive checks.

    Raises:
        DependencyAdmissionError: If report loading fails, the decoded report is not an object,
            ``repo`` or ``scorecard`` is not a mapping, ``checks`` is not a list, or the list has
            more than 100 entries. The function then rejects a repository name or commit that
            does not exactly match the supplied values, an invalid expected commit, an
            unadmitted Scorecard version, an engine commit that is not lowercase 40-hex text, or
            a missing or unparsable timestamp. It also rejects a naive, future-dated, or stale
            timestamp; duplicate qualifying check names; and missing or negative required checks.
            A qualifying check is any mapping with a string ``name`` and an ``int`` ``score``;
            malformed entries without both fields are ignored. Unknown names still qualify and
            participate in duplicate-name rejection, while only ``License``, ``Maintained``,
            ``Pinned-Dependencies``, and ``Vulnerabilities`` are required to have nonnegative
            scores. ``bool`` scores satisfy the runtime ``int`` check, scores have no upper bound,
            and the report's aggregate score is unused. The function raises directly in validation
            order, rejecting duplicate names during traversal and missing or negative required
            checks afterward; it does not collect findings.
        OSError: If report ``stat`` or read operations fail.
        ValueError: If the JSON decoder raises a non-syntax value error while loading the report.
        RecursionError: If JSON nesting exceeds the decoder's recursion limit.
        TypeError: If ``validation_time`` is naive or otherwise incompatible with an aware
            report timestamp during freshness comparison.
    """
    return DependencyReportEvaluator(policy).assess_scorecard_report(
        report_path,
        expected_repository=expected_repository,
        expected_commit=expected_commit,
        validation_time=validation_time,
    )


def validate_repository(
    repository_root: Path, *, validation_date: date | None = None
) -> DependencyAdmission:
    """Validate the B07 policy, repository dependency surfaces, and local evidence.

    Resolve ``repository_root`` strictly, load its policy, and use ``validation_date``
    or ``date.today()`` for bootstrap-wheel effectiveness, review freshness, and
    emergency-override expiry. A review deadline or override expiry equal to the
    chosen date remains valid because the checks flag only dates before it. Collect
    findings in order from the Python lock graph and configured ``src``/``tools``
    runtime-install scans. Then check policy-listed lock digests, the exact
    ``pip-audit==2.10.1`` development dependency, and required integration fragments.
    A non-empty finding list is raised together. When those checks pass, validate the
    repository change-risk policy, local evidence manifest and artifact digests, and
    the exact B07 package-evidence profile before returning the policy.

    The repository checks read files and do not mutate them. An optional wheel profile
    can cause retained evidence reads and a local Cosign subprocess through the lock
    helper; verifier domain failures become package-prefixed findings there, while
    unrelated I/O, decoding, parsing, URL, and temporary-resource failures propagate.
    This function does not run pip-audit or Scorecard, query installed package metadata,
    or install packages, and its Cosign path does not guarantee network-free execution.

    Args:
        repository_root: Existing repository directory whose policy, lock, integrations,
            source roots, and local evidence are checked.
        validation_date: Date used for bootstrap validity, review freshness, and
            override expiry; defaults to ``date.today()`` when omitted.

    Returns:
        The validated immutable ``DependencyAdmission`` policy when repository checks
        report no findings and evidence validation succeeds.

    Raises:
        DependencyAdmissionError: If policy loading fails, repository checks produce
            findings, or policy-bound wheel and dependency-admission evidence fails.
            Findings from the repository scans and digest checks are aggregated; domain
            failures translated by wheel verifiers are included through that boundary.
        EvidenceGovernanceError: If the local evidence manifest, its artifact digests,
            or the B07 package-evidence profile fails after repository findings clear.
        ChangeRiskPolicyError: If the policy-bound change-risk policy cannot be loaded
            or validated.
        OSError: If strict root resolution or an uncaught repository, evidence,
            lock-digest, temporary-resource, or integration-file operation fails.
        RuntimeError: If repository or evidence-bundle path resolution encounters a
            symlink loop.
        UnicodeDecodeError: If an uncaught repository, policy, lock,
            integration, source, or evidence text file is not valid UTF-8.
        tomllib.TOMLDecodeError: If an uncaught repository TOML document, including
            a lock or ``pyproject.toml``, is malformed. Policy,
            change-risk, and evidence-manifest TOML syntax is translated by its
            respective loader.
        ValueError: If URL parsing or another helper operation raises an untranslated
            value error.
    """
    return DependencyRepositoryValidator(repository_root).validate_repository(
        validation_date=validation_date
    )
