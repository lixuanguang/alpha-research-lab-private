"""Focused tests for frozen dependencies and the retained QuantLib exception."""

from __future__ import annotations

# standard library imports
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

# third party library imports
import pytest

# project library imports
from alpha_research_governance.dependency_admission import (
    assess_pip_audit_report,
    load_policy,
    require_release_admission,
    validate_repository,
)
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
)
from alpha_research_governance.dependency_admission.policy import (
    _locked_python_packages,
    _python_lock_findings,
    _runtime_install_findings,
)
from alpha_research_governance.dependency_admission.source_archives import SourceArchiveVerifier

REPOSITORY_ROOT = Path(__file__).parents[2]

POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/dependency-admission.toml"


def test_policy_translates_malformed_toml(tmp_path: Path) -> None:
    """Translate parser errors while preserving the original TOML exception cause."""
    path = tmp_path / "dependency-admission.toml"
    path.write_text("schema_version = [", encoding="utf-8")
    with pytest.raises(DependencyAdmissionError, match="invalid TOML") as raised:
        load_policy(path)
    assert type(raised.value.__cause__).__name__ == "TOMLDecodeError"


def test_policy_preserves_unicode_read_errors(tmp_path: Path) -> None:
    """Keep invalid UTF-8 distinct from a syntactically invalid TOML document."""
    path = tmp_path / "dependency-admission.toml"
    path.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        load_policy(path)


def test_policy_contains_only_retained_dependency_facts() -> None:
    """Load the compact policy and retain the unresolved native exception."""
    policy = load_policy(POLICY_PATH)

    assert policy.schema_version == 5
    assert policy.wheel_only_allowances[0].name == "quantlib"
    assert policy.wheel_only_allowances[0].version == "1.43"
    assert policy.wheel_only_allowances[0].source_to_wheel_binding == "unverified"
    assert policy.wheel_only_allowances[0].expires_on == date(2026, 10, 4)


def test_repository_validation_checks_lock_and_development_limits() -> None:
    """Accept frozen bytes during the allowance window without archived reports."""
    with patch.object(SourceArchiveVerifier, "verify", return_value=283) as verify:
        policy = validate_repository(REPOSITORY_ROOT, validation_date=date(2026, 9, 20))
    verify.assert_called_once_with(policy.source_archives[0])
    assert len(policy.packages) == 131
    assert any(
        package.name == "websockets" and package.version == "16.0" for package in policy.packages
    )


def test_release_admission_remains_blocked_by_unverified_quantlib() -> None:
    """Keep the unresolved source-to-wheel binding release blocking."""
    with pytest.raises(DependencyAdmissionError, match="release blocked"):
        require_release_admission(REPOSITORY_ROOT)


@pytest.mark.parametrize("validation_date", (date(2026, 9, 3), date(2026, 10, 5)))
def test_wheel_only_allowance_rejects_dates_outside_its_window(validation_date: date) -> None:
    """Reject development and CI use outside the recorded allowance window."""
    with pytest.raises(DependencyAdmissionError, match="expired or not yet effective"):
        validate_repository(REPOSITORY_ROOT, validation_date=validation_date)


def test_lock_source_url_is_checked_even_when_lock_digest_is_supplied(tmp_path: Path) -> None:
    """Reject an alternate artifact origin independently of the lockfile digest."""
    lock_path = tmp_path / "uv.lock"
    source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_path.write_text(
        source.replace("https://files.pythonhosted.org", "https://evil.invalid", 1),
        encoding="utf-8",
    )
    findings = _python_lock_findings(tmp_path, load_policy(POLICY_PATH))
    assert any("unapproved source" in finding for finding in findings)


def test_lock_hash_is_checked_for_every_artifact(tmp_path: Path) -> None:
    """Reject an artifact record without a SHA-256 lock hash."""
    source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        source.replace('hash = "sha256:', 'hash = "sha256:not-a-digest', 1), encoding="utf-8"
    )
    findings = _python_lock_findings(tmp_path, load_policy(POLICY_PATH))
    assert any("digest-bound source distribution" in finding for finding in findings)


@pytest.mark.parametrize("python_boundary", ["==3.12.*", "==3.13.*", ">=3.14", "==3.15.*"])
def test_lock_rejects_unsupported_python_boundary(tmp_path: Path, python_boundary: str) -> None:
    """Reject a lock that permits an unsupported Python minor version."""
    source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_path = tmp_path / "uv.lock"
    assert 'requires-python = "==3.14.*"' in source
    lock_path.write_text(
        source.replace('requires-python = "==3.14.*"', f'requires-python = "{python_boundary}"'),
        encoding="utf-8",
    )
    with pytest.raises(DependencyAdmissionError, match="Python boundary drifted"):
        _locked_python_packages(lock_path)


def test_lock_accepts_supported_python_boundary() -> None:
    """Load the supported lock with the pinned Python boundary."""
    packages = _locked_python_packages(REPOSITORY_ROOT / "uv.lock")
    assert packages["alpha-research-lab"]["version"] == "0.1.0"


def test_lock_schema_rejects_duplicate_package_names(tmp_path: Path) -> None:
    """Reject malformed lock identity before package checks proceed."""
    source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    duplicate = tmp_path / "uv.lock"
    duplicate.write_text(
        source
        + (
            '\n[[package]]\nname = "pydantic"\nversion = "0"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
        ),
        encoding="utf-8",
    )
    with pytest.raises(DependencyAdmissionError, match="duplicate package"):
        _locked_python_packages(duplicate)


def test_runtime_installation_scan_rejects_owned_source(tmp_path: Path) -> None:
    """Preserve the no-runtime-installation boundary for source roots."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src/runtime.py").write_text(
        "import subprocess\nsubprocess.run(['pip', 'install', 'x'])\n", encoding="utf-8"
    )
    findings = _runtime_install_findings(tmp_path)
    assert findings == ["runtime package installation is prohibited: src/runtime.py"]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('version = "1.43"', 'version = "0"', "exact native package"),
        ('name = "quantlib"', 'name = "unknown"', "exact native package"),
        ('usage = "isolated_development_and_ci"', 'usage = "release"', "allowance fields"),
        (
            'source_to_wheel_binding = "unverified"',
            'source_to_wheel_binding = "verified"',
            "allowance fields",
        ),
        ('reviewed_on = "2026-09-04"', 'reviewed_on = "2026-09-03"', "expire within 30 days"),
        ('expires_on = "2026-10-04"', 'expires_on = "2026-10-05"', "expire within 30 days"),
    ],
)
def test_wheel_only_allowance_preserves_identity_scope_and_window(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    """Reject mismatched identities, release use, verified claims and expanded dates."""
    prefix, allowance = POLICY_PATH.read_text().split("[[wheel_only_allowances]]", 1)
    assert old in allowance
    path = tmp_path / "policy.toml"
    path.write_text(prefix + "[[wheel_only_allowances]]" + allowance.replace(old, new, 1))
    with pytest.raises(DependencyAdmissionError, match=message):
        load_policy(path)


def test_duplicate_wheel_only_allowances_are_rejected(tmp_path: Path) -> None:
    """Reject conflicting grants for the same native dependency."""
    source = POLICY_PATH.read_text()
    allowance = source.split("[[wheel_only_allowances]]", 1)[1]
    path = tmp_path / "policy.toml"
    path.write_text(source + "\n[[wheel_only_allowances]]" + allowance)
    with pytest.raises(DependencyAdmissionError, match="duplicate wheel-only allowance"):
        load_policy(path)


def test_removing_allowance_does_not_admit_a_package_without_source(tmp_path: Path) -> None:
    """Require a source distribution when the explicit wheel-only allowance is absent."""
    source = POLICY_PATH.read_text().split("[[wheel_only_allowances]]", 1)[0]
    path = tmp_path / "policy.toml"
    path.write_text("wheel_only_allowances = []\n" + source)
    findings = _python_lock_findings(
        REPOSITORY_ROOT, load_policy(path), validation_date=date(2026, 9, 13)
    )
    assert "quantlib lacks a digest-bound source distribution" in findings


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("https://files.pythonhosted.org", "https://evil.invalid", "unapproved source"),
        ("sha256:", "sha256:invalid", "wheel without a SHA-256 digest"),
    ],
)
def test_wheel_only_allowance_keeps_artifact_source_and_hash_checks(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    """Reject a malformed QuantLib wheel even while development use is allowed."""
    source = (REPOSITORY_ROOT / "uv.lock").read_text()
    prefix, marker, tail = source.partition('name = "quantlib"\n')
    assert marker
    package, separator, suffix = tail.partition("\n[[package]]")
    assert old in package
    (tmp_path / "uv.lock").write_text(
        prefix + marker + package.replace(old, new, 1) + separator + suffix
    )
    findings = _python_lock_findings(
        tmp_path, load_policy(POLICY_PATH), validation_date=date(2026, 9, 13)
    )
    assert any("quantlib" in finding and message in finding for finding in findings)


def test_clean_pip_audit_report_covers_the_admitted_graph(tmp_path: Path) -> None:
    """Accept a scanner report containing every exact admitted package."""
    policy = load_policy(POLICY_PATH)
    report = {
        "dependencies": [
            {"name": package.name, "version": package.version, "vulns": []}
            for package in policy.packages
        ],
        "fixes": [],
    }
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assess_pip_audit_report(path, policy)


def test_pip_audit_skips_are_blocked(tmp_path: Path) -> None:
    """Keep scanner coverage fail-closed for skipped dependencies."""
    policy = load_policy(POLICY_PATH)
    report = {
        "dependencies": [{"name": policy.packages[0].name, "skip_reason": "offline"}],
        "fixes": [],
    }
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(DependencyAdmissionError, match="skipped"):
        assess_pip_audit_report(path, policy)


def _write_audit_report(tmp_path: Path, report: object) -> Path:
    """Write one synthetic scanner result for a fail-closed boundary test."""
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _clean_audit_dependencies(policy: DependencyAdmission) -> list[dict[str, object]]:
    """Build exact dependency identities without coupling tests to model internals."""
    return [
        {"name": package.name, "version": package.version, "vulns": []}
        for package in policy.packages
    ]


def test_pip_audit_findings_have_no_waiver_path(tmp_path: Path) -> None:
    """Block a vulnerability even when its record resembles an old waiver input."""
    policy = load_policy(POLICY_PATH)
    dependencies = _clean_audit_dependencies(policy)
    dependencies[0]["vulns"] = [{"id": "CVE-2099-0001"}]
    with pytest.raises(DependencyAdmissionError, match="unresolved vulnerability"):
        assess_pip_audit_report(
            _write_audit_report(tmp_path, {"dependencies": dependencies, "fixes": []}), policy
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate", "duplicate dependency"),
        ("wrong-version", "coverage differs"),
        ("missing-unexpected", "coverage differs"),
    ],
)
def test_pip_audit_identity_and_coverage_are_exact(
    tmp_path: Path, mutation: str, message: str
) -> None:
    """Reject duplicate, wrong-version, and unexpected scanner identities."""
    policy = load_policy(POLICY_PATH)
    dependencies = _clean_audit_dependencies(policy)
    if mutation == "duplicate":
        dependencies.append(dependencies[0].copy())
    elif mutation == "wrong-version":
        dependencies[0]["version"] = "0"
    else:
        dependencies[0] = {"name": "unexpected-package", "version": "1", "vulns": []}
    with pytest.raises(DependencyAdmissionError, match=message):
        assess_pip_audit_report(
            _write_audit_report(tmp_path, {"dependencies": dependencies, "fixes": []}), policy
        )


@pytest.mark.parametrize(
    "report",
    [
        [],
        {"dependencies": [], "fixes": []},
        {"dependencies": {}, "fixes": []},
        {"dependencies": [], "fixes": {}, "unexpected": []},
    ],
)
def test_pip_audit_malformed_or_unknown_shape_is_rejected(tmp_path: Path, report: object) -> None:
    """Reject malformed reports and unrecognized top-level fields."""
    policy = load_policy(POLICY_PATH)
    with pytest.raises(
        DependencyAdmissionError,
        match=r"root fields|dependencies must be an array|coverage differs",
    ):
        assess_pip_audit_report(_write_audit_report(tmp_path, report), policy)


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("schema_version = 2", "schema_version must be 5"),
        ("vulnerability_decisions = []", "root has missing or unknown fields"),
    ],
)
def test_policy_rejects_unsupported_schema_and_unknown_keys(
    tmp_path: Path, replacement: str, message: str
) -> None:
    """Keep schema 5 explicit and reject unknown policy keys."""
    source = POLICY_PATH.read_text(encoding="utf-8")
    if replacement.startswith("schema"):
        source = source.replace("schema_version = 5", replacement, 1)
    else:
        source = source.replace("schema_version = 5", f"schema_version = 5\n{replacement}", 1)
    path = tmp_path / "dependency-admission.toml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(DependencyAdmissionError, match=message):
        load_policy(path)
