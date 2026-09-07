"""Focused tests for frozen dependencies and the retained QuantLib exception."""

from __future__ import annotations

# standard library imports
import json
import shutil
import tomllib
from datetime import date
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from alpha_research_governance.dependency_admission import (
    assess_pip_audit_report,
    load_policy,
    require_release_admission,
    validate_repository,
)
from alpha_research_governance.dependency_admission.models import DependencyAdmissionError
from alpha_research_governance.dependency_admission.policy import (
    DependencyRepositoryInspector,
    _locked_python_packages,
)
from alpha_research_governance.dependency_admission.wheel_sources import parse_bootstrap_wheels

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/dependency-admission.toml"


def test_policy_contains_only_retained_dependency_facts() -> None:
    """Load the compact policy and retain the unresolved native exception."""
    policy = load_policy(POLICY_PATH)

    assert policy.schema_version == 2
    assert policy.lock_paths == ("uv.lock",)
    assert policy.bootstrap_wheel_admissions[0].name == "quantlib"
    assert policy.bootstrap_wheel_admissions[0].finding_id == "quantlib-wheel-binding"
    assert policy.bootstrap_wheel_admissions[0].source_to_wheel_binding == "unverified"
    assert policy.bootstrap_wheel_admissions[0].expires_on == date(2026, 10, 4)


def test_repository_validation_checks_lock_and_native_evidence() -> None:
    """Accept current frozen bytes while the bootstrap review window is open."""
    if shutil.which("cosign") is None:
        pytest.skip("focused native verification binary is unavailable")
    policy = validate_repository(REPOSITORY_ROOT, validation_date=date(2026, 9, 7))
    assert len(policy.packages) == 71


def test_release_admission_remains_blocked_by_unverified_quantlib() -> None:
    """Keep the unresolved source-to-wheel binding release blocking."""
    with pytest.raises(DependencyAdmissionError, match="release blocked"):
        require_release_admission(REPOSITORY_ROOT)


def test_bootstrap_admission_expires_after_bounded_review() -> None:
    """Reject development and CI use after the recorded exception deadline."""
    with pytest.raises(DependencyAdmissionError, match="expired or not yet effective"):
        validate_repository(REPOSITORY_ROOT, validation_date=date(2026, 10, 5))


def test_lock_source_url_is_checked_even_when_lock_digest_is_supplied(tmp_path: Path) -> None:
    """Reject an alternate artifact origin independently of the lockfile digest."""
    lock_path = tmp_path / "uv.lock"
    source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_path.write_text(
        source.replace("https://files.pythonhosted.org", "https://evil.invalid", 1),
        encoding="utf-8",
    )
    findings = DependencyRepositoryInspector(
        tmp_path, load_policy(POLICY_PATH)
    )._python_lock_findings()
    assert any("unapproved source" in finding for finding in findings)


def test_lock_hash_is_checked_for_every_artifact(tmp_path: Path) -> None:
    """Reject an artifact record without a SHA-256 lock hash."""
    source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        source.replace('hash = "sha256:', 'hash = "sha256:not-a-digest', 1), encoding="utf-8"
    )
    findings = DependencyRepositoryInspector(
        tmp_path, load_policy(POLICY_PATH)
    )._python_lock_findings()
    assert any("digest-bound source distribution" in finding for finding in findings)


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
    policy = load_policy(POLICY_PATH)
    findings = DependencyRepositoryInspector(tmp_path, policy)._runtime_install_findings()
    assert findings == ["runtime package installation is prohibited: src/runtime.py"]


def test_bootstrap_evidence_path_is_canonical() -> None:
    """Reject path traversal in the retained native evidence record."""
    raw_document: object = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw_document, dict)
    raw_policy = cast(dict[str, object], raw_document)
    raw_records = raw_policy.get("bootstrap_wheel_admissions")
    assert isinstance(raw_records, list) and raw_records
    raw_record_object = raw_records[0]
    assert isinstance(raw_record_object, dict)
    raw_record = dict(cast(dict[str, object], raw_record_object))
    raw_record["trusted_root"] = {"path": "../outside.json", "sha256": "0" * 64}
    policy = load_policy(POLICY_PATH)
    with pytest.raises(DependencyAdmissionError, match="canonical"):
        parse_bootstrap_wheels(
            [raw_record],
            policy.packages,
            {package.license_expression for package in policy.packages},
            as_of_date=policy.as_of_date,
            review_due_on=policy.review_due_on,
        )


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
