"""Validate the frozen dependency graph and retained QuantLib exception.

This module owns policy parsing and repository checks in one shallow path. It
binds lock bytes, exact package/license/source/hash/platform/edge facts, complete
pip-audit coverage, runtime-install restrictions, workflow pins, and the
publication verifier. Scorecard and emergency-override contracts were retired
with their unused consumers.
"""

from __future__ import annotations

# standard library imports
import hashlib
import json
import re
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

# project library imports
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
    PythonPackageAdmission,
)
from alpha_research_governance.dependency_admission.wheel_sources import (
    parse_bootstrap_wheels,
    verify_bootstrap_wheels,
)

_ROOT_KEYS = {
    "as_of_date",
    "bootstrap_wheel_admissions",
    "lock_digests",
    "native_python_packages",
    "pip_audit",
    "review_due_on",
    "schema_version",
    "license_groups",
}
_EXPECTED_LOCK_PATHS = ("uv.lock",)
_RUNTIME_SCAN_ROOTS = ("src", "tools")
_EXPECTED_LOCAL_PACKAGES = {"alpha-research-governance", "alpha-research-lab"}
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PACKAGE_NAME = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
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


def _table(value: object, *, context: str) -> dict[str, object]:
    """Narrow a decoded TOML table while requiring string keys."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DependencyAdmissionError([f"{context} must be a TOML table"])
    return cast(dict[str, object], value)


def _tables(value: object, *, context: str) -> list[dict[str, object]]:
    """Narrow an ordered TOML array of tables."""
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of TOML tables"])
    return [cast(dict[str, object], item) for item in value]


def _strings(value: object, *, context: str, allow_empty: bool = False) -> tuple[str, ...]:
    """Require an ordered tuple of distinct, non-empty strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DependencyAdmissionError([f"{context} must be an array of strings"])
    result = tuple(cast(list[str], value))
    if not result and not allow_empty:
        raise DependencyAdmissionError([f"{context} must not be empty"])
    if len(result) != len(set(result)):
        raise DependencyAdmissionError([f"{context} must contain unique values"])
    return result


def _iso_date(value: object, *, context: str) -> date:
    """Parse one canonical ``YYYY-MM-DD`` policy date."""
    if not isinstance(value, str):
        raise DependencyAdmissionError([f"{context} must use YYYY-MM-DD"])
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DependencyAdmissionError([f"{context} must use YYYY-MM-DD"]) from error
    if parsed.isoformat() != value:
        raise DependencyAdmissionError([f"{context} must use YYYY-MM-DD"])
    return parsed


def load_policy(path: Path) -> DependencyAdmission:
    """Load and validate the machine-readable dependency admission policy.

    Args:
        path: TOML policy path.

    Returns:
        Immutable policy facts used by repository and release checks.

    Raises:
        DependencyAdmissionError: If schema, package, date, license, scanner,
            vulnerability, lock, or native evidence declarations are invalid.
        OSError: If the policy cannot be read.
        UnicodeDecodeError: If the policy is not UTF-8.
    """
    content = path.read_text(encoding="utf-8")
    try:
        raw_document: object = tomllib.loads(content)
    # TOMLDecodeError is a ValueError; its legacy constructor is dynamically typed in 3.14.
    except ValueError as error:
        raise DependencyAdmissionError([f"{path}: invalid TOML: {error}"]) from error
    document = _table(raw_document, context=str(path))
    if set(document) != _ROOT_KEYS:
        raise DependencyAdmissionError([f"{path}: root has missing or unknown fields"])
    if document.get("schema_version") != 3:
        raise DependencyAdmissionError(["dependency policy schema_version must be 3"])
    as_of_date = _iso_date(document.get("as_of_date"), context="as_of_date")
    review_due_on = _iso_date(document.get("review_due_on"), context="review_due_on")
    if review_due_on <= as_of_date or review_due_on > as_of_date + timedelta(days=90):
        raise DependencyAdmissionError(["review_due_on must be within 90 days after as_of_date"])
    lock_digests = _table(document.get("lock_digests"), context="lock_digests")
    if set(lock_digests) != set(_EXPECTED_LOCK_PATHS) or any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in lock_digests.values()
    ):
        raise DependencyAdmissionError(["lock_digests must bind every lock by SHA-256"])
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
        for item in entries:
            name, separator, version = item.partition("==")
            if separator != "==" or not version or _PACKAGE_NAME.fullmatch(name) is None:
                raise DependencyAdmissionError([f"invalid exact Python package identity: {item!r}"])
            packages.append(
                PythonPackageAdmission(
                    name=name,
                    version=version,
                    license_expression=license_expression,
                    native_artifacts=name in native_names,
                )
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
    bootstrap = parse_bootstrap_wheels(
        document.get("bootstrap_wheel_admissions"),
        tuple(packages),
        _APPROVED_LICENSES,
        as_of_date=as_of_date,
        review_due_on=review_due_on,
    )
    return DependencyAdmission(
        schema_version=3,
        as_of_date=as_of_date,
        review_due_on=review_due_on,
        lock_digests=tuple((name, cast(str, lock_digests[name])) for name in _EXPECTED_LOCK_PATHS),
        packages=tuple(packages),
        bootstrap_wheel_admissions=bootstrap,
    )


def assess_pip_audit_report(report_path: Path, policy: DependencyAdmission) -> None:
    """Require pip-audit coverage and no unresolved vulnerability for every package.

    Args:
        report_path: JSON report produced by the exact admitted pip-audit version.
        policy: Loaded dependency admission policy.

    Raises:
        DependencyAdmissionError: If the report is malformed, incomplete, skipped,
            duplicated, skipped, incomplete, or vulnerable dependencies.
    """
    try:
        if report_path.stat().st_size > _MAX_SIGNAL_BYTES:
            raise DependencyAdmissionError(["pip-audit report exceeds the size limit"])
        report: object = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DependencyAdmissionError([f"invalid pip-audit JSON: {error}"]) from error
    except UnicodeDecodeError as error:
        raise DependencyAdmissionError(["invalid pip-audit text encoding"]) from error
    if not isinstance(report, dict):
        raise DependencyAdmissionError(["pip-audit report has missing or unknown root fields"])
    report_object = cast(dict[str, object], report)
    if set(report_object) != {"dependencies", "fixes"}:
        raise DependencyAdmissionError(["pip-audit report has missing or unknown root fields"])
    dependencies, fixes = report_object.get("dependencies"), report_object.get("fixes")
    if not isinstance(dependencies, list) or not isinstance(fixes, list):
        raise DependencyAdmissionError(["pip-audit dependencies must be an array"])
    if len(dependencies) > _MAX_PIP_AUDIT_DEPENDENCIES:
        raise DependencyAdmissionError(["pip-audit dependency count exceeds the limit"])
    expected = {item.name: item.version for item in policy.packages}
    observed: dict[str, str] = {}
    findings: list[str] = []
    for index, item in enumerate(cast(list[object], dependencies), 1):
        if not isinstance(item, dict):
            findings.append(f"pip-audit dependency {index} is malformed")
            continue
        name, version, vulnerabilities = item.get("name"), item.get("version"), item.get("vulns")
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
            findings.append(f"{name}=={version} has unresolved vulnerability {vulnerability_id!r}")
    if observed != expected:
        findings.append(
            "pip-audit coverage differs from the admitted lock: "
            f"missing={sorted(set(expected) - set(observed))}, "
            f"unexpected={sorted(set(observed) - set(expected))}"
        )
    if findings:
        raise DependencyAdmissionError(findings)


def _locked_python_packages(path: Path) -> dict[str, dict[str, object]]:
    """Load unique package tables from a schema-pinned uv lock."""
    raw_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    document = _table(raw_document, context=str(path))
    if (
        document.get("version") != 1
        or document.get("revision") != 3
        or document.get("requires-python") != "==3.14.*"
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
    """Require native platform or pure-Python wheel coverage."""
    wheels = locked.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return [f"{package.name} has no locked wheel artifacts"]
    urls = [
        cast(str, item["url"])
        for item in wheels
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]
    if package.native_artifacts:
        if not any("macosx" in url and ("arm64" in url or "universal2" in url) for url in urls):
            return [f"{package.name} lacks a Darwin arm64 native wheel"]
        if not any(("manylinux" in url or "musllinux" in url) and "x86_64" in url for url in urls):
            return [f"{package.name} lacks a Linux x86_64 native wheel"]
    elif not any(url.endswith(("-none-any.whl", "-any.whl")) for url in urls):
        return [f"{package.name} lacks a platform-independent wheel"]
    return []


def _artifact_source_findings(
    package: PythonPackageAdmission, locked: dict[str, object]
) -> list[str]:
    """Reject malformed or mutable package artifact URLs."""
    artifacts: list[tuple[str, object]] = []
    if "sdist" in locked:
        artifacts.append(("sdist", locked["sdist"]))
    wheels = locked.get("wheels")
    if isinstance(wheels, list):
        artifacts.extend(("wheel", wheel) for wheel in wheels)
    findings: list[str] = []
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


def _python_lock_findings(
    root: Path, policy: DependencyAdmission, *, validation_date: date | None = None
) -> list[str]:
    """Check lock identity, origin, hashes, wheels, graph edges, and native evidence."""
    locked = _locked_python_packages(root / "uv.lock")
    admitted = {item.name for item in policy.packages}
    external = {
        name
        for name, item in locked.items()
        if item.get("source") == {"registry": "https://pypi.org/simple"}
    }
    findings: list[str] = []
    unexpected = {
        name
        for name, item in locked.items()
        if name not in admitted
        and not (
            name in _EXPECTED_LOCAL_PACKAGES
            and isinstance(item.get("source"), dict)
            and len(cast(dict[str, object], item["source"])) == 1
            and set(cast(dict[str, object], item["source"])) <= {"directory", "editable"}
        )
    }
    if unexpected:
        findings.append(f"uv.lock contains unadmitted external packages: {sorted(unexpected)}")
    if external != admitted:
        findings.append(
            "uv.lock external packages and admissions differ: "
            f"missing={sorted(external - admitted)}, stale={sorted(admitted - external)}"
        )
    bootstrap = {item.name: item for item in policy.bootstrap_wheel_admissions}
    observed_date = date.today() if validation_date is None else validation_date
    for package in policy.packages:
        item = locked.get(package.name)
        if item is None or item.get("version") != package.version:
            findings.append(f"{package.name} is not locked at admitted version {package.version}")
            continue
        if item.get("source") != {"registry": "https://pypi.org/simple"}:
            findings.append(f"{package.name} uses an unapproved package source")
        findings.extend(_artifact_source_findings(package, item))
        if package.name in bootstrap:
            try:
                verify_bootstrap_wheels(
                    root, item, bootstrap[package.name], validation_date=observed_date
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


def _lock_surface_findings(root: Path) -> list[str]:
    """Require the exact immutable GitHub Action revisions used by CI."""
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    observed: dict[str, set[str]] = {}
    findings: list[str] = []
    for action, revision in cast(list[tuple[str, str]], _WORKFLOW_USE.findall(workflow)):
        observed.setdefault(action, set()).add(revision)
        if _COMMIT.fullmatch(revision) is None:
            findings.append(f"GitHub Action {action} uses mutable reference {revision!r}")
    if observed != {action: {revision} for action, revision in _ACTION_PINS.items()}:
        findings.append("GitHub Action set or immutable commit admission drifted")
    return findings


def _runtime_install_findings(root: Path) -> list[str]:
    """Reject runtime package-install commands under the source roots."""
    findings: list[str] = []
    for relative_root in _RUNTIME_SCAN_ROOTS:
        scan_root = root / relative_root
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
                    f"{path.relative_to(root).as_posix()}"
                )
    return findings


def validate_repository(
    repository_root: Path, *, validation_date: date | None = None
) -> DependencyAdmission:
    """Validate the admitted policy, lock graph, CI pins, source roots, and evidence.

    Args:
        repository_root: Repository whose dependency boundary is checked.
        validation_date: Date used for review and bootstrap expiry checks.

    Returns:
        The validated immutable dependency policy.

    Raises:
        DependencyAdmissionError: If any retained lock, source, hash, graph, scan,
            evidence, or expiry check fails.
        OSError: If required repository files cannot be read.
    """
    root = repository_root.resolve(strict=True)
    policy = load_policy(root / "docs/architecture/dependency-admission.toml")
    today = date.today() if validation_date is None else validation_date
    findings = _python_lock_findings(root, policy, validation_date=today)
    findings += _lock_surface_findings(root)
    findings += _runtime_install_findings(root)
    if policy.review_due_on < today:
        findings.append("dependency admission review is stale")
    for relative, expected in policy.lock_digests:
        observed = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if observed != expected:
            findings.append(f"{relative} differs from its admitted SHA-256 digest")
    if findings:
        raise DependencyAdmissionError(findings)
    return policy


def require_release_admission(repository_root: Path) -> None:
    """Reject artifact release while QuantLib source-to-wheel binding is unverified.

    Args:
        repository_root: Repository whose policy and lock are checked.

    Raises:
        DependencyAdmissionError: If bootstrap evidence remains active or validation fails.
    """
    root = repository_root.resolve(strict=True)
    policy = load_policy(root / "docs/architecture/dependency-admission.toml")
    if policy.bootstrap_wheel_admissions:
        details = ", ".join(
            f"{item.name}=={item.version} ({item.finding_id}, expires {item.expires_on})"
            for item in policy.bootstrap_wheel_admissions
        )
        raise DependencyAdmissionError(
            [f"artifact release blocked by unresolved native dependency admission: {details}"]
        )
    validate_repository(root)
