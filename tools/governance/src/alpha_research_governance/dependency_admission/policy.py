"""Check the frozen Python dependency boundary and retained native exception.

The policy is deliberately a repository boundary: it binds ``uv.lock`` bytes,
package source and artifact hashes, license decisions, scanner output, and the
bounded QuantLib exception.  It does not load change, ownership, evidence, or
roadmap registries.
"""

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

# project library imports
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

_ROOT_KEYS = {
    "approved_python_indexes",
    "as_of_date",
    "bootstrap_wheel_admissions",
    "emergency_overrides",
    "lock_digests",
    "lock_paths",
    "maximum_signal_age_days",
    "native_python_packages",
    "pip_audit",
    "review_due_on",
    "runtime_scan_roots",
    "schema_version",
    "scorecard",
    "supported_platforms",
    "vulnerability_decisions",
    "wheel_source_admissions",
    "license_groups",
}
_EXPECTED_LOCK_PATHS = ("uv.lock",)
_EXPECTED_PLATFORMS = ("darwin_arm64", "linux_x86_64")
_EXPECTED_INDEXES = ("https://pypi.org/simple",)
_EXPECTED_LOCAL_PACKAGES = {"alpha-research-governance", "alpha-research-lab"}
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
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
_APPROVED_LICENSES = {
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


def _table(value: object, *, context: str) -> dict[str, object]:
    """Narrow a decoded TOML table without copying it.

    Args:
        value: Decoded TOML value expected to be a mapping.
        context: Field name used in the diagnostic.

    Returns:
        The original mapping narrowed to string keys and object values.

    Raises:
        DependencyAdmissionError: If ``value`` is not a mapping with string keys.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DependencyAdmissionError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _tables(value: object, *, context: str) -> list[dict[str, object]]:
    """Narrow an ordered array of TOML tables.

    Args:
        value: Decoded TOML value expected to contain dictionaries.
        context: Field name used in the diagnostic.

    Returns:
        The ordered dictionaries from ``value``.

    Raises:
        DependencyAdmissionError: If the value is not an array of tables.
    """
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of TOML tables"])
    return [cast(dict[str, object], item) for item in value]


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Validate an ordered tuple of distinct non-empty strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of strings"])
    result = tuple(cast(list[str], value))
    if not result and not allow_empty:
        raise DependencyAdmissionError([f"{context} must not be empty"])
    if len(result) != len(set(result)):
        raise DependencyAdmissionError([f"{context} must contain unique values"])
    return result


def _iso_date(value: object, *, context: str) -> date:
    """Parse a canonical TOML date string."""
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
    """Require a credential-free HTTPS URL without query or fragment."""
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
        or re.search(r"[\s\x00-\x1f]", value)
    ):
        raise DependencyAdmissionError([f"{context} must be a credential-free HTTPS URL"])
    return value


def _parse_package(
    value: str, *, license_expression: str, native_names: set[str]
) -> PythonPackageAdmission:
    """Parse an exact ``name==version`` declaration."""
    name, separator, version = value.partition("==")
    if separator != "==" or not version or _PACKAGE_NAME.fullmatch(name) is None:
        raise DependencyAdmissionError([f"invalid exact Python package identity: {value!r}"])
    return PythonPackageAdmission(
        name=name,
        version=version,
        license_expression=license_expression,
        native_artifacts=name in native_names,
    )


def _parse_decisions(value: object, *, as_of_date: date) -> tuple[VulnerabilityDecision, ...]:
    """Parse expiring vulnerability decisions without reviewer metadata."""
    decisions: list[VulnerabilityDecision] = []
    required = {
        "affected_version",
        "disposition",
        "evidence_url",
        "expires_on",
        "package_name",
        "rationale",
        "vulnerability_id",
    }
    for index, entry in enumerate(_tables(value, context="vulnerability_decisions"), 1):
        context = f"vulnerability_decisions[{index}]"
        if set(entry) != required:
            raise DependencyAdmissionError([f"{context} has missing or unknown fields"])
        if entry.get("disposition") not in {"not_exploitable", "temporary_exception"}:
            raise DependencyAdmissionError([f"{context}.disposition is not permitted"])
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or len(rationale.strip()) < 24:
            raise DependencyAdmissionError([f"{context}.rationale must be specific"])
        expires_on = _iso_date(entry.get("expires_on"), context=f"{context}.expires_on")
        if expires_on < as_of_date or expires_on > as_of_date + timedelta(days=90):
            raise DependencyAdmissionError([f"{context} expiry is outside the review window"])
        values = {
            key: entry.get(key) for key in ("affected_version", "package_name", "vulnerability_id")
        }
        if not all(isinstance(item, str) and item for item in values.values()):
            raise DependencyAdmissionError([f"{context} identity fields must be populated strings"])
        decisions.append(
            VulnerabilityDecision(
                vulnerability_id=cast(str, values["vulnerability_id"]),
                package_name=cast(str, values["package_name"]),
                affected_version=cast(str, values["affected_version"]),
                disposition=cast(str, entry["disposition"]),
                rationale=rationale.strip(),
                expires_on=expires_on,
                evidence_url=_https_url(
                    entry.get("evidence_url"), context=f"{context}.evidence_url"
                ),
            )
        )
    ids = tuple(item.vulnerability_id for item in decisions)
    if len(ids) != len(set(ids)):
        raise DependencyAdmissionError(["vulnerability decisions must have unique IDs"])
    return tuple(decisions)


def _parse_overrides(value: object, *, as_of_date: date) -> tuple[EmergencyOverride, ...]:
    """Parse expiring exceptions tied to concrete component identities."""
    overrides: list[EmergencyOverride] = []
    required = {"component_id", "evidence_url", "expires_on", "override_id", "rationale"}
    for index, entry in enumerate(_tables(value, context="emergency_overrides"), 1):
        context = f"emergency_overrides[{index}]"
        if set(entry) != required:
            raise DependencyAdmissionError([f"{context} has missing or unknown fields"])
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or len(rationale.strip()) < 24:
            raise DependencyAdmissionError([f"{context}.rationale must be specific"])
        expires_on = _iso_date(entry.get("expires_on"), context=f"{context}.expires_on")
        if expires_on < as_of_date or expires_on > as_of_date + timedelta(days=90):
            raise DependencyAdmissionError([f"{context} expiry is outside the review window"])
        values = {key: entry.get(key) for key in ("component_id", "override_id")}
        if not all(isinstance(item, str) and item for item in values.values()):
            raise DependencyAdmissionError([f"{context} identity fields must be populated strings"])
        component_id = cast(str, values["component_id"])
        if _COMPONENT_ID.fullmatch(component_id) is None:
            raise DependencyAdmissionError([f"{context}.component_id must be an exact identity"])
        overrides.append(
            EmergencyOverride(
                override_id=cast(str, values["override_id"]),
                component_id=component_id,
                rationale=rationale.strip(),
                expires_on=expires_on,
                evidence_url=_https_url(
                    entry.get("evidence_url"), context=f"{context}.evidence_url"
                ),
            )
        )
    ids = tuple(item.override_id for item in overrides)
    if len(ids) != len(set(ids)):
        raise DependencyAdmissionError(["emergency overrides must have unique IDs"])
    return tuple(overrides)


class DependencyPolicyLoader:
    """Load one compact dependency policy file."""

    def __init__(self, policy_path: Path) -> None:
        """Bind the path without reading it.

        Args:
            policy_path: TOML path read by :meth:`load`.
        """
        self.policy_path = policy_path

    def load(self) -> DependencyAdmission:
        """Parse and validate frozen dependency identities and native exceptions.

        Returns:
            The immutable admission record.

        Raises:
            DependencyAdmissionError: If the policy schema, package identity, digest,
                date, or native exception is invalid.
            OSError: If the policy cannot be read.
            UnicodeDecodeError: If the policy is not UTF-8.
        """
        path = self.policy_path
        try:
            raw_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
            document = _table(raw_document, context=str(path))
        except tomllib.TOMLDecodeError as error:
            raise DependencyAdmissionError([f"{path}: invalid TOML: {error}"]) from error
        if set(document) != _ROOT_KEYS:
            raise DependencyAdmissionError([f"{path}: root has missing or unknown fields"])
        if document.get("schema_version") != 2:
            raise DependencyAdmissionError(["dependency policy schema_version must be 2"])
        as_of_date = _iso_date(document.get("as_of_date"), context="as_of_date")
        review_due_on = _iso_date(document.get("review_due_on"), context="review_due_on")
        if review_due_on <= as_of_date or review_due_on > as_of_date + timedelta(days=90):
            raise DependencyAdmissionError(
                ["review_due_on must be within 90 days after as_of_date"]
            )
        platforms = _strings(document.get("supported_platforms"), context="supported_platforms")
        if platforms != _EXPECTED_PLATFORMS:
            raise DependencyAdmissionError(
                ["supported platforms must retain Darwin arm64 and Linux x86_64"]
            )
        indexes = _strings(
            document.get("approved_python_indexes"), context="approved_python_indexes"
        )
        if indexes != _EXPECTED_INDEXES:
            raise DependencyAdmissionError(["only the reviewed PyPI simple index is approved"])
        lock_paths = _strings(document.get("lock_paths"), context="lock_paths")
        if lock_paths != _EXPECTED_LOCK_PATHS:
            raise DependencyAdmissionError(["lock_paths must contain exactly uv.lock"])
        lock_digests = _table(document.get("lock_digests"), context="lock_digests")
        if set(lock_digests) != set(lock_paths) or any(
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in lock_digests.values()
        ):
            raise DependencyAdmissionError(["lock_digests must bind every lock by SHA-256"])
        runtime_roots = _strings(document.get("runtime_scan_roots"), context="runtime_scan_roots")
        native_names = set(
            _strings(
                document.get("native_python_packages"),
                context="native_python_packages",
                allow_empty=True,
            )
        )
        packages: list[PythonPackageAdmission] = []
        for index, group in enumerate(
            _tables(document.get("license_groups"), context="license_groups"), 1
        ):
            if set(group) != {"disposition", "license_expression", "packages"}:
                raise DependencyAdmissionError(
                    [f"license_groups[{index}] has missing or unknown fields"]
                )
            license_expression = group.get("license_expression")
            if group.get("disposition") != "approved" or not isinstance(license_expression, str):
                raise DependencyAdmissionError(
                    [f"license_groups[{index}] is not approved and identified"]
                )
            if license_expression not in _APPROVED_LICENSES:
                raise DependencyAdmissionError(
                    [f"license_groups[{index}] uses an unapproved license expression"]
                )
            entries = _strings(group.get("packages"), context=f"license_groups[{index}].packages")
            if entries != tuple(sorted(entries)):
                raise DependencyAdmissionError([f"license_groups[{index}].packages must be sorted"])
            packages.extend(
                _parse_package(
                    item, license_expression=license_expression, native_names=native_names
                )
                for item in entries
            )
        names = tuple(item.name for item in packages)
        if len(names) != len(set(names)):
            raise DependencyAdmissionError(["Python package admissions must be unique"])
        if native_names != {item.name for item in packages if item.native_artifacts}:
            raise DependencyAdmissionError(
                ["native package declarations must match package admissions"]
            )
        pip_audit = _table(document.get("pip_audit"), context="pip_audit")
        if pip_audit != {
            "command_mode": "exact_locked_graph",
            "failure_policy": "block_unresolved_findings_or_skips",
            "service": "pypi",
            "version": "2.10.1",
        }:
            raise DependencyAdmissionError(["pip-audit must remain an exact blocking signal"])
        scorecard = _table(document.get("scorecard"), context="scorecard")
        if scorecard != {
            "required_checks": ["License", "Maintained", "Pinned-Dependencies", "Vulnerabilities"],
            "signal_role": "advisory_input_not_admission_authority",
            "version": "5.5.0",
        }:
            raise DependencyAdmissionError(["Scorecard signal contract drifted"])
        decisions = _parse_decisions(document.get("vulnerability_decisions"), as_of_date=as_of_date)
        admitted_versions = {item.name: item.version for item in packages}
        if any(
            admitted_versions.get(item.package_name) != item.affected_version for item in decisions
        ):
            raise DependencyAdmissionError(
                ["vulnerability decisions must match an admitted package"]
            )
        overrides = _parse_overrides(document.get("emergency_overrides"), as_of_date=as_of_date)
        wheel_sources = parse_wheel_sources(
            document.get("wheel_source_admissions", []), tuple(packages), _APPROVED_LICENSES
        )
        bootstrap_wheels = parse_bootstrap_wheels(
            document.get("bootstrap_wheel_admissions", []),
            tuple(packages),
            _APPROVED_LICENSES,
            as_of_date=as_of_date,
            review_due_on=review_due_on,
        )
        if {item.name for item in wheel_sources} & {item.name for item in bootstrap_wheels}:
            raise DependencyAdmissionError(["a package cannot use both wheel admission profiles"])
        return DependencyAdmission(
            schema_version=2,
            as_of_date=as_of_date,
            review_due_on=review_due_on,
            pip_audit_version=cast(str, pip_audit["version"]),
            vulnerability_service=cast(str, pip_audit["service"]),
            scorecard_version=cast(str, scorecard["version"]),
            maximum_signal_age_days=7,
            supported_platforms=platforms,
            approved_python_indexes=indexes,
            lock_paths=lock_paths,
            lock_digests=tuple(
                (path_name, cast(str, lock_digests[path_name])) for path_name in lock_paths
            ),
            runtime_scan_roots=runtime_roots,
            packages=tuple(packages),
            vulnerability_decisions=decisions,
            emergency_overrides=overrides,
            wheel_source_admissions=wheel_sources,
            bootstrap_wheel_admissions=bootstrap_wheels,
        )


def load_policy(path: Path) -> DependencyAdmission:
    """Load a dependency admission policy from a TOML path.

    Args:
        path: TOML policy path.

    Returns:
        The parsed dependency admission policy.

    Raises:
        DependencyAdmissionError: If the policy schema or values are invalid.
    """
    return DependencyPolicyLoader(path).load()


def _load_json_signal(report_path: Path, *, signal: str) -> object:
    """Read a bounded UTF-8 JSON signal document."""
    try:
        if report_path.stat().st_size > _MAX_SIGNAL_BYTES:
            raise DependencyAdmissionError([f"{signal} report exceeds the size limit"])
        raw_report: object = json.loads(report_path.read_text(encoding="utf-8"))
        return raw_report
    except json.JSONDecodeError as error:
        raise DependencyAdmissionError([f"invalid {signal} JSON: {error}"]) from error
    except UnicodeDecodeError as error:
        raise DependencyAdmissionError([f"invalid {signal} text encoding"]) from error


def assess_pip_audit_report(
    report_path: Path, policy: DependencyAdmission, *, validation_date: date | None = None
) -> None:
    """Require pip-audit coverage for every exact admitted package version.

    Args:
        report_path: JSON report produced by pip-audit.
        policy: Loaded dependency admission policy.
        validation_date: Date used for expiring vulnerability decisions.

    Raises:
        DependencyAdmissionError: If the report is malformed, incomplete, skipped,
            or contains an unresolved vulnerability.
    """
    report = _load_json_signal(report_path, signal="pip-audit")
    if not isinstance(report, dict):
        raise DependencyAdmissionError(["pip-audit report has missing or unknown root fields"])
    report_object = cast(dict[str, object], report)
    if set(report_object) != {"dependencies", "fixes"}:
        raise DependencyAdmissionError(["pip-audit report has missing or unknown root fields"])
    dependencies = report_object.get("dependencies")
    if not isinstance(dependencies, list) or not isinstance(report_object.get("fixes"), list):
        raise DependencyAdmissionError(["pip-audit dependencies must be an array"])
    dependency_items = cast(list[object], dependencies)
    if len(dependencies) > _MAX_PIP_AUDIT_DEPENDENCIES:
        raise DependencyAdmissionError(["pip-audit dependency count exceeds the limit"])
    expected = {item.name: item.version for item in policy.packages}
    observed: dict[str, str] = {}
    decisions = {item.vulnerability_id: item for item in policy.vulnerability_decisions}
    today = date.today() if validation_date is None else validation_date
    findings: list[str] = []
    for index, item in enumerate(dependency_items, 1):
        if not isinstance(item, dict):
            findings.append(f"pip-audit dependency {index} is malformed")
            continue
        name = item.get("name")
        version = item.get("version")
        vulnerabilities = item.get("vulns")
        if not isinstance(name, str):
            findings.append(f"pip-audit dependency {index} has no name")
            continue
        if "skip_reason" in item:
            findings.append(f"pip-audit skipped dependency {name}")
            continue
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
        findings.append(
            "pip-audit coverage differs from the admitted lock: "
            f"missing={sorted(set(expected) - set(observed))}, "
            f"unexpected={sorted(set(observed) - set(expected))}"
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
    """Check advisory Scorecard identity, freshness, and required checks.

    Args:
        report_path: JSON report produced by Scorecard.
        expected_repository: Exact repository identity expected in the report.
        expected_commit: Exact lowercase Git commit expected in the report.
        policy: Loaded dependency admission policy.
        validation_time: Time used for the freshness check.

    Raises:
        DependencyAdmissionError: If identity, freshness, shape, or required checks fail.
    """
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
        raise DependencyAdmissionError(["Scorecard report has an invalid shape"])
    check_items = cast(list[object], checks)
    repository_object = cast(dict[str, object], repository)
    scorecard_object = cast(dict[str, object], scorecard)
    if len(check_items) > _MAX_SCORECARD_CHECKS:
        raise DependencyAdmissionError(["Scorecard check count exceeds the limit"])
    if (
        repository_object.get("name") != expected_repository
        or repository_object.get("commit") != expected_commit
        or _COMMIT.fullmatch(expected_commit) is None
    ):
        raise DependencyAdmissionError(["Scorecard repository identity does not match"])
    if (
        scorecard_object.get("version") != policy.scorecard_version
        or not isinstance(scorecard_object.get("commit"), str)
        or _COMMIT.fullmatch(cast(str, scorecard_object["commit"])) is None
    ):
        raise DependencyAdmissionError(["Scorecard identity is not admitted"])
    generated = scorecard_object.get("date")
    if not isinstance(generated, str):
        raise DependencyAdmissionError(["Scorecard report has no timestamp"])
    try:
        generated_at = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as error:
        raise DependencyAdmissionError(["Scorecard timestamp is invalid"]) from error
    now = datetime.now(UTC) if validation_time is None else validation_time
    if (
        generated_at.tzinfo is None
        or generated_at > now
        or now - generated_at > timedelta(days=policy.maximum_signal_age_days)
    ):
        raise DependencyAdmissionError(["Scorecard signal is future-dated or stale"])
    observed: dict[str, int] = {}
    for item in check_items:
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
    if required - set(observed) or any(observed[name] < 0 for name in required):
        raise DependencyAdmissionError(["Scorecard required checks are missing or inconclusive"])


def _locked_python_packages(path: Path) -> dict[str, dict[str, object]]:
    """Load unique package tables from a uv lock after checking its schema."""
    raw_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    document = _table(raw_document, context=str(path))
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
    """Require platform coverage for native and pure-Python package wheels."""
    wheels = locked.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return [f"{package.name} has no locked wheel artifacts"]
    urls = [
        item.get("url")
        for item in wheels
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]
    if package.native_artifacts:
        if not any(
            "macosx" in cast(str, url)
            and ("arm64" in cast(str, url) or "universal2" in cast(str, url))
            for url in urls
        ):
            return [f"{package.name} lacks a Darwin arm64 native wheel"]
        if not any(
            ("manylinux" in cast(str, url) or "musllinux" in cast(str, url))
            and "x86_64" in cast(str, url)
            for url in urls
        ):
            return [f"{package.name} lacks a Linux x86_64 native wheel"]
    elif not any(cast(str, url).endswith(("-none-any.whl", "-any.whl")) for url in urls):
        return [f"{package.name} lacks a platform-independent wheel"]
    return []


def _artifact_source_findings(
    package: PythonPackageAdmission, locked: dict[str, object]
) -> list[str]:
    """Reject package artifacts from mutable or unapproved URL origins.

    Args:
        package: Admitted package whose artifact records are checked.
        locked: Parsed uv-lock package table.

    Returns:
        Findings for malformed, credentialed, queried, or non-PyPI artifact URLs.
    """
    findings: list[str] = []
    artifacts: list[tuple[str, object]] = []
    if "sdist" in locked:
        artifacts.append(("sdist", locked["sdist"]))
    wheels = locked.get("wheels")
    if isinstance(wheels, list):
        artifacts.extend(("wheel", wheel) for wheel in wheels)
    for kind, value in artifacts:
        if not isinstance(value, dict) or not isinstance(value.get("url"), str):
            findings.append(f"{package.name} {kind} artifact is malformed")
            continue
        url = cast(str, value["url"])
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "files.pythonhosted.org"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or re.search(r"[\s\x00-\x1f]", url)
        ):
            findings.append(f"{package.name} {kind} artifact uses an unapproved source")
    return findings


def _is_local_lock_source(value: object) -> bool:
    """Identify editable or directory packages owned by this repository."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return False
    source = cast(dict[str, object], value)
    return len(source) == 1 and set(source) <= {"directory", "editable"}


def _read_record(root: Path, path: str, expected_digest: str) -> bytes:
    """Read one retained native evidence file after path and digest checks."""
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != path:
        raise DependencyAdmissionError([f"unsafe dependency evidence path: {path}"])
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise DependencyAdmissionError([f"missing dependency evidence file: {path}"])
    content = candidate.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise DependencyAdmissionError([f"dependency evidence digest mismatch: {path}"])
    return content


class DependencyRepositoryInspector:
    """Inspect the lock graph and source roots for dependency boundary violations."""

    def __init__(self, repository_root: Path, policy: DependencyAdmission | None = None) -> None:
        """Bind repository and optional already-loaded policy.

        Args:
            repository_root: Root whose lock and source files are inspected.
            policy: Loaded policy, or ``None`` to require one before inspection.
        """
        self.repository_root = repository_root
        self.policy = policy

    def _python_lock_findings(self, *, validation_date: date | None = None) -> list[str]:
        """Check package names, versions, source URLs, hashes, wheels, and edges."""
        if self.policy is None:
            raise ValueError("dependency repository inspector requires an admitted policy")
        locked = _locked_python_packages(self.repository_root / "uv.lock")
        policy = self.policy
        findings: list[str] = []
        external = {
            name
            for name, item in locked.items()
            if item.get("source") == {"registry": "https://pypi.org/simple"}
        }
        admitted = {item.name for item in policy.packages}
        unexpected = {
            name
            for name, item in locked.items()
            if name not in admitted
            and not (name in _EXPECTED_LOCAL_PACKAGES and _is_local_lock_source(item.get("source")))
        }
        if unexpected:
            findings.append(f"uv.lock contains unadmitted external packages: {sorted(unexpected)}")
        if external != admitted:
            findings.append(
                "uv.lock external packages and admissions differ: "
                f"missing={sorted(external - admitted)}, "
                f"stale={sorted(admitted - external)}"
            )
        source_records = {item.name: item for item in policy.wheel_source_admissions}
        bootstrap_records = {item.name: item for item in policy.bootstrap_wheel_admissions}
        observed_date = date.today() if validation_date is None else validation_date
        for package in policy.packages:
            item = locked.get(package.name)
            if item is None or item.get("version") != package.version:
                findings.append(
                    f"{package.name} is not locked at admitted version {package.version}"
                )
                continue
            if item.get("source") != {"registry": "https://pypi.org/simple"}:
                findings.append(f"{package.name} uses an unapproved package source")
            findings.extend(_artifact_source_findings(package, item))
            if package.name in source_records:
                try:
                    verify_wheel_sources(self.repository_root, item, source_records[package.name])
                except DependencyAdmissionError as error:
                    findings.extend(f"{package.name}: {finding}" for finding in error.findings)
            elif package.name in bootstrap_records:
                record = bootstrap_records[package.name]
                try:
                    verify_bootstrap_wheels(
                        self.repository_root,
                        item,
                        record,
                        validation_date=observed_date,
                    )
                except DependencyAdmissionError as error:
                    findings.extend(f"{package.name}: {finding}" for finding in error.findings)
            else:
                source = item.get("sdist")
                if (
                    not isinstance(source, dict)
                    or not isinstance(source.get("hash"), str)
                    or _HASH.fullmatch(cast(str, source["hash"])) is None
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
            elif any(
                not isinstance(edge, dict)
                or not isinstance(edge.get("name"), str)
                or edge.get("name") not in locked
                for edge in dependencies
            ):
                findings.append(f"{package.name} has an unresolved transitive dependency")
        return findings

    def _lock_surface_findings(self) -> list[str]:
        """Require pinned GitHub Action revisions when the workflow uses them."""
        workflow = (self.repository_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        observed: dict[str, set[str]] = {}
        findings: list[str] = []
        for action, revision in cast(list[tuple[str, str]], _WORKFLOW_USE.findall(workflow)):
            observed.setdefault(action, set()).add(revision)
            if _COMMIT.fullmatch(revision) is None:
                findings.append(f"GitHub Action {action} uses mutable reference {revision!r}")
        if observed != {action: {revision} for action, revision in _ACTION_PINS.items()}:
            findings.append("GitHub Action set or immutable commit admission drifted")
        return findings

    def _runtime_install_findings(self) -> list[str]:
        """Reject runtime package installation commands in configured source roots."""
        if self.policy is None:
            raise ValueError("dependency repository inspector requires an admitted policy")
        findings: list[str] = []
        for relative_root in self.policy.runtime_scan_roots:
            scan_root = self.repository_root / relative_root
            if not scan_root.exists():
                continue
            for path in sorted(scan_root.rglob("*")):
                if (
                    path.is_file()
                    and path.suffix in {".py", ".sh", ".bash", ".zsh"}
                    and _INSTALL_COMMAND.search(path.read_text(encoding="utf-8"))
                ):
                    findings.append(
                        "runtime package installation is prohibited: "
                        f"{path.relative_to(self.repository_root).as_posix()}"
                    )
        return findings


def _python_lock_findings(
    root: Path, policy: DependencyAdmission, *, validation_date: date | None = None
) -> list[str]:
    """Return lock-graph findings for callers that use the old helper name."""
    return DependencyRepositoryInspector(root, policy)._python_lock_findings(
        validation_date=validation_date
    )


def _lock_surface_findings(root: Path) -> list[str]:
    """Return workflow pin findings for callers that use the old helper name."""
    return DependencyRepositoryInspector(root)._lock_surface_findings()


def _runtime_install_findings(root: Path, policy: DependencyAdmission) -> list[str]:
    """Return runtime installation findings for callers that use the old helper name."""
    return DependencyRepositoryInspector(root, policy)._runtime_install_findings()


class DependencyRepositoryValidator:
    """Validate one repository and expose the release admission gate."""

    def __init__(self, repository_root: Path, policy: DependencyAdmission | None = None) -> None:
        """Bind repository and optional policy without I/O.

        Args:
            repository_root: Root whose dependency files are inspected.
            policy: Loaded policy, or ``None`` to load it at validation time.
        """
        self.repository_root = repository_root
        self.policy = policy

    def validate_repository(self, *, validation_date: date | None = None) -> DependencyAdmission:
        """Validate frozen dependency bytes, graph, source scans, and exception window.

        Args:
            validation_date: Date used for review and exception expiry checks.

        Returns:
            The validated dependency policy.

        Raises:
            DependencyAdmissionError: If any lock, source, hash, scan, or expiry check fails.
        """
        root = self.repository_root.resolve(strict=True)
        policy = self.policy or load_policy(root / "docs/architecture/dependency-admission.toml")
        today = date.today() if validation_date is None else validation_date
        inspector = DependencyRepositoryInspector(root, policy)
        findings = inspector._python_lock_findings(validation_date=today)
        findings += inspector._lock_surface_findings()
        findings += inspector._runtime_install_findings()
        if policy.review_due_on < today:
            findings.append("dependency admission review is stale")
        findings.extend(
            f"emergency override {item.override_id} is expired"
            for item in policy.emergency_overrides
            if item.expires_on < today
        )
        for relative, expected in policy.lock_digests:
            observed = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            if observed != expected:
                findings.append(f"{relative} differs from its admitted SHA-256 digest")
        if findings:
            raise DependencyAdmissionError(findings)
        return policy

    def require_release_admission(self) -> None:
        """Reject release use while any native source-to-wheel binding is unresolved.

        Raises:
            DependencyAdmissionError: If a native exception remains or validation fails.
        """
        root = self.repository_root.resolve(strict=True)
        policy = self.policy or load_policy(root / "docs/architecture/dependency-admission.toml")
        if policy.bootstrap_wheel_admissions:
            details = ", ".join(
                f"{item.name}=={item.version} ({item.finding_id}, expires {item.expires_on})"
                for item in policy.bootstrap_wheel_admissions
            )
            raise DependencyAdmissionError(
                [f"artifact release blocked by unresolved native dependency admission: {details}"]
            )
        self.validate_repository()


def require_release_admission(repository_root: Path) -> None:
    """Require release admission for a repository's dependency boundary.

    Args:
        repository_root: Repository whose dependency policy and lock are checked.

    Raises:
        DependencyAdmissionError: If release use is blocked or validation fails.
    """
    DependencyRepositoryValidator(repository_root).require_release_admission()


def validate_repository(
    repository_root: Path, *, validation_date: date | None = None
) -> DependencyAdmission:
    """Validate the repository dependency boundary and return its policy.

    Args:
        repository_root: Repository whose dependency boundary is checked.
        validation_date: Date used for review and exception expiry checks.

    Returns:
        The validated dependency policy.

    Raises:
        DependencyAdmissionError: If any retained dependency check fails.
    """
    return DependencyRepositoryValidator(repository_root).validate_repository(
        validation_date=validation_date
    )
