"""Deterministic and adversarial dependency-admission tests for package B07."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, date, datetime
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from alpha_research_governance.dependency_admission import (
    DependencyAdmissionError,
    assess_pip_audit_report,
    assess_scorecard_report,
    load_policy,
    main,
    run_pip_audit,
    validate_repository,
)
from alpha_research_governance.dependency_admission.policy import (
    _lock_surface_findings,
    _python_lock_findings,
    _runtime_install_findings,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "dependency-admission.toml"
RUNNING_UNDER_BAZEL = bool(os.environ.get("TEST_SRCDIR"))


def _policy_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "dependency-admission.toml"
    path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _clean_audit_report() -> dict[str, object]:
    policy = load_policy(POLICY_PATH)
    return {
        "dependencies": [
            {"name": package.name, "version": package.version, "vulns": []}
            for package in policy.packages
        ],
        "fixes": [],
    }


def _write_json(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


@pytest.mark.skipif(
    RUNNING_UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks"
)
def test_dependency_admission_contract_is_partial_and_bounds_sbom_successor() -> None:
    policy = validate_repository(REPOSITORY_ROOT)

    assert policy.package_status == "partial"
    assert policy.successor_package == "B08"
    assert policy.pip_audit_version == "2.10.1"
    assert policy.scorecard_version == "5.5.0"
    assert len(policy.packages) == 64
    assert len({package.name for package in policy.packages}) == 64
    assert len([package for package in policy.packages if package.native_artifacts]) == 11
    assert policy.vulnerability_decisions == ()
    assert policy.emergency_overrides == ()
    assert policy.open_finding_ids == ("B07-F01", "B07-F02", "B07-F03")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('package_status = "partial"', 'package_status = "validated"', "package_status"),
        ("runtime_installation_allowed = false", "runtime_installation_allowed = true", "runtime"),
        (
            'approved_python_indexes = ["https://pypi.org/simple"]',
            'approved_python_indexes = ["https://example.invalid/simple"]',
            "PyPI",
        ),
        ('disposition = "approved"', 'disposition = "ignored"', "approved"),
        ('version = "2.10.1"', 'version = "2.9.0"', "pip-audit"),
        (
            '"uv.lock" = "ba148d5f1ea020cceff9d6b78230b46fb2a044e2d276572288b4b94dac514896"',
            '"uv.lock" = "not-a-digest"',
            "lock_digests",
        ),
    ],
)
def test_policy_mutations_fail_closed(tmp_path: Path, old: str, new: str, message: str) -> None:
    path = _policy_fixture(tmp_path)
    _replace(path, old, new)

    with pytest.raises(DependencyAdmissionError, match=message):
        load_policy(path)


def test_unknown_and_malformed_policy_fields_fail_closed(tmp_path: Path) -> None:
    unknown = _policy_fixture(tmp_path)
    _replace(unknown, "[lock_digests]", "unknown = true\n\n[lock_digests]")
    with pytest.raises(DependencyAdmissionError, match="missing or unknown fields"):
        load_policy(unknown)

    malformed = tmp_path / "malformed.toml"
    malformed.write_text("schema_version = [\n", encoding="utf-8")
    with pytest.raises(DependencyAdmissionError, match="invalid TOML"):
        load_policy(malformed)


def test_emergency_override_requires_specific_bounded_audited_record(tmp_path: Path) -> None:
    path = _policy_fixture(tmp_path)
    _replace(
        path,
        "emergency_overrides = []",
        'emergency_overrides = [{ override_id = "B07-OVR-001", '
        'component_id = "python:urllib3==2.7.0", '
        'owner_role = "security", rationale = "Temporary containment while the fixed '
        'lock is tested and reviewed.", expires_on = "2026-09-30", '
        'evidence_url = "https://example.invalid/evidence/B07-OVR-001" }]',
    )
    assert load_policy(path).emergency_overrides[0].override_id == "B07-OVR-001"

    invalid_root = tmp_path / "invalid-identity"
    invalid_root.mkdir()
    invalid_identity = _policy_fixture(invalid_root)
    _replace(
        invalid_identity,
        "emergency_overrides = []",
        'emergency_overrides = [{ override_id = "B07-OVR-002", component_id = "urllib3", '
        'owner_role = "security", rationale = "Temporary containment while the fixed '
        'lock is tested and reviewed.", expires_on = "2026-09-30", '
        'evidence_url = "https://example.invalid/evidence/B07-OVR-002" }]',
    )
    with pytest.raises(DependencyAdmissionError, match="exact identity"):
        load_policy(invalid_identity)

    _replace(path, 'expires_on = "2026-09-30"', 'expires_on = "2027-09-30"')
    with pytest.raises(DependencyAdmissionError, match="expiry"):
        load_policy(path)


def test_complete_clean_pip_audit_report_passes(tmp_path: Path) -> None:
    report = _write_json(tmp_path, "audit.json", _clean_audit_report())
    assess_pip_audit_report(report, load_policy(POLICY_PATH))


def test_live_audit_uses_the_complete_exact_lock_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = load_policy(POLICY_PATH)
    monkeypatch.setattr("importlib.metadata.version", lambda _name: "2.10.1")

    def run_audit(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["cwd"] == REPOSITORY_ROOT
        assert "--local" not in command
        assert {"--no-deps", "--disable-pip", "--strict"} <= set(command)
        assert command[command.index("--vulnerability-service") + 1] == "pypi"
        requirements = Path(command[command.index("--requirement") + 1])
        assert requirements.read_text(encoding="utf-8").splitlines() == [
            f"{package.name}=={package.version}" for package in policy.packages
        ]
        report = Path(command[command.index("--output") + 1])
        report.write_text(json.dumps(_clean_audit_report()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("alpha_research_governance.dependency_admission.subprocess.run", run_audit)
    run_pip_audit(REPOSITORY_ROOT, policy)


@pytest.mark.parametrize(
    "mutation", ["missing", "wrong_version", "skip", "skip_unknown", "duplicate"]
)
def test_pip_audit_coverage_gaps_fail_closed(tmp_path: Path, mutation: str) -> None:
    payload = _clean_audit_report()
    dependencies = payload["dependencies"]
    assert isinstance(dependencies, list)
    if mutation == "missing":
        dependencies.pop()
    elif mutation == "wrong_version":
        dependencies[0]["version"] = "0"
    elif mutation == "skip":
        dependencies[0] = {"name": dependencies[0]["name"], "skip_reason": "network failure"}
    elif mutation == "skip_unknown":
        dependencies.append({"name": "unknown", "skip_reason": "unsupported"})
    else:
        dependencies.append(dict(dependencies[0]))
    report = _write_json(tmp_path, "audit.json", payload)

    with pytest.raises(DependencyAdmissionError, match=r"coverage|skipped|duplicate"):
        assess_pip_audit_report(report, load_policy(POLICY_PATH))


def test_vulnerability_requires_exact_owned_exploitability_decision(tmp_path: Path) -> None:
    payload = _clean_audit_report()
    dependencies = payload["dependencies"]
    assert isinstance(dependencies, list)
    dependencies[0]["vulns"] = [{"id": "PYSEC-SYNTHETIC-1", "fix_versions": ["99"]}]
    report = _write_json(tmp_path, "audit.json", payload)
    with pytest.raises(DependencyAdmissionError, match="unresolved vulnerability"):
        assess_pip_audit_report(report, load_policy(POLICY_PATH))

    policy_path = _policy_fixture(tmp_path)
    first_name = dependencies[0]["name"]
    first_version = dependencies[0]["version"]
    _replace(
        policy_path,
        "vulnerability_decisions = []",
        f'vulnerability_decisions = [{{ vulnerability_id = "PYSEC-SYNTHETIC-1", '
        f'package_name = "{first_name}", '
        f'affected_version = "{first_version}", disposition = "not_exploitable", '
        'owner_role = "security", rationale = "The vulnerable code path is absent from '
        'the admitted offline tool usage.", expires_on = "2026-09-30", '
        'evidence_url = "https://example.invalid/evidence/PYSEC-SYNTHETIC-1" }]',
    )
    assess_pip_audit_report(report, load_policy(policy_path))

    invalid_root = tmp_path / "invalid-decision"
    invalid_root.mkdir()
    invalid_policy = _policy_fixture(invalid_root)
    _replace(
        invalid_policy,
        "vulnerability_decisions = []",
        f'vulnerability_decisions = [{{ vulnerability_id = "PYSEC-SYNTHETIC-1", '
        'package_name = "not-admitted", '
        f'affected_version = "{first_version}", disposition = "not_exploitable", '
        'owner_role = "security", rationale = "The vulnerable code path is absent from '
        'the admitted offline tool usage.", expires_on = "2026-09-30", '
        'evidence_url = "https://example.invalid/evidence/PYSEC-SYNTHETIC-1" }]',
    )
    with pytest.raises(DependencyAdmissionError, match="exact admitted package"):
        load_policy(invalid_policy)

    with pytest.raises(DependencyAdmissionError, match="unresolved vulnerability"):
        assess_pip_audit_report(
            report,
            load_policy(policy_path),
            validation_date=date(2026, 10, 1),
        )


def _scorecard_report(*, commit: str = "a" * 40) -> dict[str, object]:
    return {
        "date": "2026-09-03T00:00:00Z",
        "repo": {"name": "github.com/example/project", "commit": commit},
        "scorecard": {"version": "5.5.0", "commit": "b" * 40},
        "score": 7.5,
        "checks": [
            {"name": name, "score": 8, "reason": "synthetic deterministic signal"}
            for name in ("License", "Maintained", "Pinned-Dependencies", "Vulnerabilities")
        ],
    }


def test_scorecard_signal_is_fresh_commit_bound_and_advisory(tmp_path: Path) -> None:
    report = _write_json(tmp_path, "scorecard.json", _scorecard_report())
    assess_scorecard_report(
        report,
        expected_repository="github.com/example/project",
        expected_commit="a" * 40,
        policy=load_policy(POLICY_PATH),
        validation_time=datetime(2026, 9, 3, 12, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "failure", ["repository", "stale", "inconclusive", "version", "engine_commit", "duplicate"]
)
def test_scorecard_invalid_or_inconclusive_signal_fails_closed(
    tmp_path: Path, failure: str
) -> None:
    payload = _scorecard_report()
    repository = "github.com/example/project"
    validation_time = datetime(2026, 9, 3, 12, tzinfo=UTC)
    if failure == "repository":
        repository = "github.com/other/project"
    elif failure == "stale":
        payload["date"] = "2026-08-01T00:00:00Z"
    elif failure == "inconclusive":
        checks = payload["checks"]
        assert isinstance(checks, list) and isinstance(checks[0], dict)
        checks[0]["score"] = -1
    elif failure == "version":
        scorecard = payload["scorecard"]
        assert isinstance(scorecard, dict)
        scorecard["version"] = "5.4.0"
    elif failure == "engine_commit":
        scorecard = payload["scorecard"]
        assert isinstance(scorecard, dict)
        scorecard["commit"] = "unknown"
    else:
        checks = payload["checks"]
        assert isinstance(checks, list) and isinstance(checks[0], dict)
        checks.append(dict(checks[0]))
    report = _write_json(tmp_path, "scorecard.json", payload)

    with pytest.raises(
        DependencyAdmissionError,
        match=r"commit|stale|inconclusive|version|immutable|duplicated",
    ):
        assess_scorecard_report(
            report,
            expected_repository=repository,
            expected_commit="a" * 40,
            policy=load_policy(POLICY_PATH),
            validation_time=validation_time,
        )


def test_exact_lock_wheels_and_transitives_match_registry() -> None:
    assert _python_lock_findings(REPOSITORY_ROOT, load_policy(POLICY_PATH)) == []


@pytest.mark.skipif(
    RUNNING_UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks"
)
def test_repository_review_expiry_fails_closed() -> None:
    with pytest.raises(DependencyAdmissionError, match="review is stale"):
        validate_repository(REPOSITORY_ROOT, validation_date=date(2026, 12, 2))


def test_mutable_action_reference_and_runtime_install_are_rejected(tmp_path: Path) -> None:
    for relative in ("MODULE.bazel.lock", "flake.lock", "requirements.bazel.txt", "uv.lock"):
        (tmp_path / relative).write_text(
            (REPOSITORY_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8"
        )
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml")
        .read_text(encoding="utf-8")
        .replace(
            "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5", "actions/checkout@v4"
        ),
        encoding="utf-8",
    )
    assert any("mutable reference" in finding for finding in _lock_surface_findings(tmp_path))

    source = tmp_path / "src" / "runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text('subprocess.run(["pip", "install", "unsafe"])\n', encoding="utf-8")
    (tmp_path / "tools").mkdir()
    assert _runtime_install_findings(tmp_path, load_policy(POLICY_PATH)) == [
        "runtime package installation is prohibited: src/runtime.py"
    ]


def test_live_audit_missing_tool_version_and_cli_usage_are_explicit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = load_policy(POLICY_PATH)
    monkeypatch.setattr("importlib.metadata.version", lambda _name: "0.0.0")
    with pytest.raises(DependencyAdmissionError, match="not admitted"):
        run_pip_audit(REPOSITORY_ROOT, policy)

    def missing_version(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("importlib.metadata.version", missing_version)
    with pytest.raises(DependencyAdmissionError, match="not installed"):
        run_pip_audit(REPOSITORY_ROOT, policy)

    assert main(["unsupported"]) == 2
    assert "usage:" in capsys.readouterr().err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
