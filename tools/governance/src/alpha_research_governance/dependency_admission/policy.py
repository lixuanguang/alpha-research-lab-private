"""Load and enforce the dependency-admission contract for roadmap package B07."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from pydantic import ValidationError

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
_PREDECESSOR_DEPENDENCY_PACKAGE_IDS = ("B02", "B03", "B04", "B05", "B06")
_EXPECTED_LOCK_PATHS = (
    "uv.lock",
    "requirements.bazel.txt",
    "MODULE.bazel.lock",
    "flake.lock",
    ".github/workflows/ci.yml",
)
_EXPECTED_MIGRATED_PATHS = (
    "docs/architecture/build-tool-dependencies.toml",
    "environments/dev/toolchain.toml",
    "docs/architecture/engineering-tool-dependencies.toml",
    "docs/architecture/ci-tool-dependencies.toml",
    "docs/architecture/remote-execution.toml",
)
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
    "migrated_records",
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
    "bazel-contrib/setup-bazel": "c5acdfb288317d0b5c0bbd7a396a3dc868bb0f86",
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
    if not isinstance(value, dict):
        raise DependencyAdmissionError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _tables(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of TOML tables"])
    return cast(list[dict[str, object]], value)


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of strings"])
    values = tuple(cast(list[str], value))
    if not allow_empty and not values:
        raise DependencyAdmissionError([f"{context} must not be empty"])
    if len(values) != len(set(values)):
        raise DependencyAdmissionError([f"{context} must contain unique values"])
    return values


def _iso_date(value: object, *, context: str) -> date:
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


def load_policy(path: Path) -> DependencyAdmission:
    """Load the dependency policy and reject missing, unknown, or weakened controls."""
    try:
        document = _table(tomllib.loads(path.read_text(encoding="utf-8")), context=str(path))
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
        raise DependencyAdmissionError(["review_due_on must be within 90 days after as_of_date"])
    maximum_signal_age_days = document.get("maximum_signal_age_days")
    maximum_override_days = document.get("emergency_override_maximum_days")
    patch_cadence_days = document.get("patch_cadence_days")
    if maximum_signal_age_days != 7 or maximum_override_days != 30 or patch_cadence_days != 30:
        raise DependencyAdmissionError(["signal, override, and patch/EOL review bounds drifted"])
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
    indexes = _strings(document.get("approved_python_indexes"), context="approved_python_indexes")
    if indexes != ("https://pypi.org/simple",):
        raise DependencyAdmissionError(["only the reviewed PyPI simple index is approved"])
    lock_paths = _strings(document.get("lock_paths"), context="lock_paths")
    if lock_paths != _EXPECTED_LOCK_PATHS:
        raise DependencyAdmissionError(["lock_paths must cover the exact current lock surfaces"])
    lock_digests = _table(document.get("lock_digests"), context="lock_digests")
    if set(lock_digests) != set(lock_paths) or any(
        not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for digest in lock_digests.values()
    ):
        raise DependencyAdmissionError(["lock_digests must bind every lock surface by SHA-256"])
    runtime_scan_roots = _strings(document.get("runtime_scan_roots"), context="runtime_scan_roots")
    if runtime_scan_roots != ("src", "tools"):
        raise DependencyAdmissionError(["runtime install scanning must cover src and tools"])

    migrated = _tables(document.get("migrated_records"), context="migrated_records")
    if (
        tuple(item.get("roadmap_package") for item in migrated)
        != _PREDECESSOR_DEPENDENCY_PACKAGE_IDS
        or tuple(item.get("path") for item in migrated) != _EXPECTED_MIGRATED_PATHS
        or any(set(item) != {"path", "roadmap_package"} for item in migrated)
    ):
        raise DependencyAdmissionError(
            ["B02-B06 migrated dependency records are incomplete or reordered"]
        )

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
            _parse_package(item, license_expression=license_expression, native_names=native_names)
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
        raise DependencyAdmissionError(["pip-audit must remain an exact, blocking signal boundary"])
    scorecard = _table(document.get("scorecard"), context="scorecard")
    if scorecard != {
        "required_checks": ["License", "Maintained", "Pinned-Dependencies", "Vulnerabilities"],
        "signal_role": "advisory_input_not_admission_authority",
        "version": "5.5.0",
    }:
        raise DependencyAdmissionError(["OpenSSF Scorecard signal contract drifted"])

    evidence_sha = document.get("local_evidence_commit_sha")
    if not isinstance(evidence_sha, str) or _COMMIT.fullmatch(evidence_sha) is None:
        raise DependencyAdmissionError(["local_evidence_commit_sha must be a full lowercase SHA"])
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
            migrated_record_paths=_EXPECTED_MIGRATED_PATHS,
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


def _locked_python_packages(path: Path) -> dict[str, dict[str, object]]:
    document = _table(tomllib.loads(path.read_text(encoding="utf-8")), context=str(path))
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


def _python_lock_findings(
    root: Path, policy: DependencyAdmission, *, validation_date: date | None = None
) -> list[str]:
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
            findings.append(f"{package.name} is not locked at admitted version {package.version}")
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
                    validation_date=date.today() if validation_date is None else validation_date,
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


def require_release_admission(repository_root: Path) -> None:
    """Reject bootstrap-only dependencies at artifact creation, signing and consumption."""
    root = repository_root.resolve(strict=True)
    policy = load_policy(root / "docs/architecture/dependency-admission.toml")
    if policy.bootstrap_wheel_admissions:
        names = ", ".join(record.name for record in policy.bootstrap_wheel_admissions)
        raise DependencyAdmissionError(
            [f"bootstrap-only dependencies block artifact release: {names}"]
        )
    # Removing a bootstrap record must not turn its unprovenanced locked wheel into a release.
    findings = _python_lock_findings(root, policy)
    if policy.review_due_on < date.today():
        findings.append("dependency admission review is stale")
    for relative, expected_digest in policy.lock_digests:
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected_digest:
            findings.append(f"{relative} differs from its admitted SHA-256 digest")
    if findings:
        raise DependencyAdmissionError(findings)


def _migrated_record_findings(root: Path, policy: DependencyAdmission) -> list[str]:
    findings: list[str] = []
    for expected_package, relative in zip(
        _PREDECESSOR_DEPENDENCY_PACKAGE_IDS,
        policy.migrated_record_paths,
        strict=True,
    ):
        document = _table(
            tomllib.loads((root / relative).read_text(encoding="utf-8")), context=relative
        )
        if document.get("roadmap_package") != expected_package:
            findings.append(f"{relative} is not the {expected_package} migration source")
        if expected_package != "B06":
            if document.get("admission_owner_package") != "B07":
                findings.append(f"{relative} does not retain B07 admission ownership")
            if document.get("runtime_installation_allowed") is not False:
                findings.append(f"{relative} permits runtime dependency installation")
        for collection in ("dependencies", "tools"):
            for item in _tables(document.get(collection, []), context=f"{relative}.{collection}"):
                required = (
                    "license",
                    "maintenance_review",
                    "purpose",
                    "rollback",
                    "source_digest",
                    "source_url",
                    "version",
                    "vulnerability_review",
                )
                if any(not isinstance(item.get(key), str) or not item.get(key) for key in required):
                    findings.append(f"{relative} has an incomplete migrated {collection} record")
                    continue
                source_url = cast(str, item["source_url"])
                source_digest = cast(str, item["source_digest"])
                try:
                    _https_url(source_url, context=f"{relative}.{collection}.source_url")
                except DependencyAdmissionError:
                    findings.append(f"{relative} has an unapproved migrated source URL")
                if re.search(r"(?:[0-9a-f]{64}|[0-9a-f]{40})", source_digest) is None:
                    findings.append(f"{relative} has no immutable migrated source digest")
                platform_key = (
                    "supported_systems" if collection == "tools" else "supported_platforms"
                )
                if not isinstance(item.get(platform_key), list) or not item.get(platform_key):
                    findings.append(f"{relative} has no migrated platform declaration")
                if not isinstance(item.get("transitive_native_dependencies"), list):
                    findings.append(f"{relative} has no migrated transitive/native declaration")
    return findings


def _lock_surface_findings(root: Path) -> list[str]:
    findings: list[str] = []
    module_lock = json.loads((root / "MODULE.bazel.lock").read_text(encoding="utf-8"))
    hashes = module_lock.get("registryFileHashes")
    if (
        not isinstance(hashes, dict)
        or not hashes
        or any(
            not isinstance(url, str)
            or not url.startswith("https://bcr.bazel.build/")
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for url, digest in hashes.items()
        )
    ):
        findings.append("MODULE.bazel.lock contains an unapproved or unhashed registry input")
    flake_lock = json.loads((root / "flake.lock").read_text(encoding="utf-8"))
    nodes = flake_lock.get("nodes")
    if not isinstance(nodes, dict):
        findings.append("flake.lock nodes are malformed")
    else:
        for name, node in nodes.items():
            if name == "root":
                continue
            locked = node.get("locked") if isinstance(node, dict) else None
            if (
                not isinstance(locked, dict)
                or not isinstance(locked.get("narHash"), str)
                or not isinstance(locked.get("rev"), str)
            ):
                findings.append(f"flake.lock node {name!r} lacks immutable revision and NAR hash")
    requirements = (root / "requirements.bazel.txt").read_text(encoding="utf-8").splitlines()
    requirement_names = {
        line.partition("==")[0]
        for line in requirements
        if line and not line.startswith("#") and "==" in line
    }
    uv_names = set(_locked_python_packages(root / "uv.lock"))
    if not requirement_names or not requirement_names <= uv_names:
        findings.append("requirements.bazel.txt is not an exact uv.lock subset")
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    observed_actions: dict[str, set[str]] = {}
    for action, revision in _WORKFLOW_USE.findall(workflow):
        observed_actions.setdefault(action, set()).add(revision)
        if _COMMIT.fullmatch(revision) is None:
            findings.append(f"GitHub Action {action} uses mutable reference {revision!r}")
    if observed_actions != {action: {revision} for action, revision in _ACTION_PINS.items()}:
        findings.append("GitHub Action set or immutable commit admission drifted")
    return findings


def _runtime_install_findings(root: Path, policy: DependencyAdmission) -> list[str]:
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


def _load_json_signal(report_path: Path, *, signal: str) -> object:
    try:
        if report_path.stat().st_size > _MAX_SIGNAL_BYTES:
            raise DependencyAdmissionError([f"{signal} report exceeds the size limit"])
        return json.loads(report_path.read_text(encoding="utf-8"))
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
    """Require complete exact-lock coverage and owned disposition of every finding."""
    report = _load_json_signal(report_path, signal="pip-audit")
    if not isinstance(report, dict) or set(report) != {"dependencies", "fixes"}:
        raise DependencyAdmissionError(["pip-audit report has missing or unknown root fields"])
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not isinstance(report.get("fixes"), list):
        raise DependencyAdmissionError(["pip-audit dependencies must be an array"])
    if len(dependencies) > _MAX_PIP_AUDIT_DEPENDENCIES:
        raise DependencyAdmissionError(["pip-audit dependency count exceeds the limit"])
    expected = {package.name: package.version for package in policy.packages}
    observed: dict[str, str] = {}
    findings: list[str] = []
    decisions = {decision.vulnerability_id: decision for decision in policy.vulnerability_decisions}
    today = date.today() if validation_date is None else validation_date
    for index, item in enumerate(dependencies, 1):
        if not isinstance(item, dict):
            findings.append(f"pip-audit dependency {index} is malformed")
            continue
        name = item.get("name")
        if not isinstance(name, str):
            findings.append(f"pip-audit dependency {index} has no name")
            continue
        if "skip_reason" in item:
            findings.append(f"pip-audit skipped dependency {name}")
            continue
        version = item.get("version")
        vulnerabilities = item.get("vulns")
        if not isinstance(version, str) or not isinstance(vulnerabilities, list):
            findings.append(f"pip-audit dependency {name} is incomplete")
            continue
        if name in observed:
            findings.append(f"pip-audit reported duplicate dependency {name}")
            continue
        observed[name] = version
        for vulnerability in vulnerabilities:
            vulnerability_id = vulnerability.get("id") if isinstance(vulnerability, dict) else None
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
    report_path: Path,
    *,
    expected_repository: str,
    expected_commit: str,
    policy: DependencyAdmission,
    validation_time: datetime | None = None,
) -> None:
    """Validate a fresh commit-bound Scorecard signal without treating it as admission."""
    report = _load_json_signal(report_path, signal="Scorecard")
    if not isinstance(report, dict):
        raise DependencyAdmissionError(["Scorecard report must be a JSON object"])
    repository = report.get("repo")
    scorecard = report.get("scorecard")
    checks = report.get("checks")
    if (
        not isinstance(repository, dict)
        or not isinstance(scorecard, dict)
        or not isinstance(checks, list)
    ):
        raise DependencyAdmissionError(["Scorecard report is missing repo, scorecard, or checks"])
    if len(checks) > _MAX_SCORECARD_CHECKS:
        raise DependencyAdmissionError(["Scorecard check count exceeds the limit"])
    if repository.get("name") != expected_repository or repository.get("commit") != expected_commit:
        raise DependencyAdmissionError(
            ["Scorecard report is not bound to the expected repository commit"]
        )
    if _COMMIT.fullmatch(expected_commit) is None:
        raise DependencyAdmissionError(["expected Scorecard commit must be a full lowercase SHA"])
    if scorecard.get("version") != policy.scorecard_version:
        raise DependencyAdmissionError(["Scorecard signal uses an unadmitted tool version"])
    scorecard_commit = scorecard.get("commit")
    if not isinstance(scorecard_commit, str) or _COMMIT.fullmatch(scorecard_commit) is None:
        raise DependencyAdmissionError(["Scorecard signal has no immutable engine commit"])
    raw_date = report.get("date")
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
        if (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("score"), int)
        ):
            name = cast(str, item["name"])
            if name in observed:
                raise DependencyAdmissionError([f"Scorecard check {name!r} is duplicated"])
            observed[name] = cast(int, item["score"])
    required = {"License", "Maintained", "Pinned-Dependencies", "Vulnerabilities"}
    if set(observed) & required != required or any(observed[name] < 0 for name in required):
        raise DependencyAdmissionError(["Scorecard required checks are missing or inconclusive"])


def validate_repository(
    repository_root: Path, *, validation_date: date | None = None
) -> DependencyAdmission:
    """Validate policy, locks, migrations, integrations, evidence, and safe source behavior."""
    root = repository_root.resolve(strict=True)
    policy = load_policy(root / "docs/architecture/dependency-admission.toml")
    today = date.today() if validation_date is None else validation_date
    findings = (
        _python_lock_findings(root, policy, validation_date=today)
        + _migrated_record_findings(root, policy)
        + _lock_surface_findings(root)
        + _runtime_install_findings(root, policy)
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
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject.get("dependency-groups", {}).get("dev", [])
    if "pip-audit==2.10.1" not in dev:
        findings.append("pyproject.toml is missing exact pip-audit 2.10.1 admission")
    integrations = {
        "Makefile": (
            "dependency-admission-check:",
            "dependency-audit:",
            "alpha-governance-dependencies",
        ),
        ".pre-commit-config.yaml": ("id: dependency-admission", "alpha-governance-dependencies"),
        ".github/workflows/ci.yml": ("make dependency-audit",),
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
