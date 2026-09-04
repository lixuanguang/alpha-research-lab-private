"""Deterministic and adversarial dependency-admission tests for package B07."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tomllib
from datetime import UTC, date, datetime
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import IO, cast

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
from alpha_research_governance.dependency_admission.models import (
    BootstrapWheelAdmission,
    EvidenceFile,
    PythonPackageAdmission,
    SourceArchive,
    WheelProvenance,
    WheelSourceAdmission,
)
from alpha_research_governance.dependency_admission.policy import (
    _lock_surface_findings,
    _python_lock_findings,
    _runtime_install_findings,
    require_release_admission,
)
from alpha_research_governance.dependency_admission.wheel_sources import (
    parse_bootstrap_wheels,
    parse_wheel_sources,
    verify_bootstrap_wheels,
    verify_wheel_sources,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "dependency-admission.toml"
RUNNING_UNDER_BAZEL = bool(os.environ.get("TEST_SRCDIR"))


def _policy_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "dependency-admission.toml"
    path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _without_bootstrap(text: str) -> str:
    """Isolate legacy and synthetic profile fixtures from current consumer records."""
    return "bootstrap_wheel_admissions = []\n" + text.split("[[bootstrap_wheel_admissions]]")[
        0
    ].replace("bootstrap_wheel_admissions = []\n", "")


def _copy_current_wheel_evidence(root: Path) -> None:
    """Materialize structural-test inputs; process doubles do not authenticate signatures."""
    data = tomllib.loads(POLICY_PATH.read_text())
    for record in data.get("bootstrap_wheel_admissions", []):
        reports = [
            record[key]
            for key in (
                "source_review",
                "security_review",
                "native_inventory",
                "compatibility_report",
                "trusted_root",
            )
        ]
        reports.extend(wheel["bundle"] for wheel in record["wheels"])
        for report in reports:
            target = root / report["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPOSITORY_ROOT / report["path"]).read_bytes())


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
    assert len(policy.packages) == 74
    assert len({package.name for package in policy.packages}) == 74
    assert len([package for package in policy.packages if package.native_artifacts]) == 14
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
            '"uv.lock" = "22f953c3cabb20af3d8203e188accb9a1011b4784b9674d77bc535930ffd31bd"',
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


def test_exact_lock_wheels_and_transitives_match_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wheel_cosign: None,
) -> None:
    # Real authentication remains blocking in validate_repository above and the full lane.
    _copy_current_wheel_evidence(tmp_path)
    (tmp_path / "uv.lock").write_bytes((REPOSITORY_ROOT / "uv.lock").read_bytes())
    monkeypatch.setattr(subprocess, "run", _fake_cosign)
    assert _python_lock_findings(tmp_path, load_policy(POLICY_PATH)) == []


@pytest.mark.skipif(
    RUNNING_UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks"
)
def test_repository_review_expiry_fails_closed() -> None:
    with pytest.raises(DependencyAdmissionError, match="review is stale"):
        validate_repository(REPOSITORY_ROOT, validation_date=date(2026, 12, 4))


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


def _evidence_file(root: Path, filename: str, content: bytes) -> EvidenceFile:
    (root / filename).write_bytes(content)
    return EvidenceFile(path=filename, sha256=hashlib.sha256(content).hexdigest())


def _wheel_source_fixture(root: Path) -> tuple[WheelSourceAdmission, dict[str, object]]:
    """Make synthetic source claims; the fake runner does not authenticate these signatures."""
    sources = (
        SourceArchive(
            uri="https://example.invalid/source/archive/" + "a" * 40,
            revision="a" * 40,
            sha256="b" * 64,
            license_expression="BSD-3-Clause",
        ),
    )
    parameters = {"externalParameters": {"version": "2.4.6"}, "internalParameters": {}}
    wheels = []
    locked = []
    for platform, digest in (("macosx_11_0_arm64", "c" * 64), ("manylinux_2_28_x86_64", "d" * 64)):
        filename = f"numpy-2.4.6-cp312-cp312-{platform}.whl"
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": filename, "digest": {"sha256": digest}}],
            "predicate": {
                "buildDefinition": {
                    "buildType": "https://example.invalid/native-wheel/v1",
                    **parameters,
                    "resolvedDependencies": [
                        {
                            "uri": source.uri,
                            "digest": {"sha256": source.sha256, "gitCommit": source.revision},
                        }
                        for source in sources
                    ],
                },
                "runDetails": {"builder": {"id": "https://example.invalid/builder"}},
            },
        }
        bundle = json.dumps(
            {
                "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                "verificationMaterial": {},
                "dsseEnvelope": {
                    "payloadType": "application/vnd.in-toto+json",
                    "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
                    "signatures": [],
                },
            }
        ).encode()
        wheels.append(
            WheelProvenance(
                filename=filename,
                sha256=digest,
                bundle=_evidence_file(root, platform + ".json", bundle),
            )
        )
        locked.append(
            {"url": "https://files.pythonhosted.org/" + filename, "hash": "sha256:" + digest}
        )
    return WheelSourceAdmission(
        name="numpy",
        version="2.4.6",
        owner_role="platform",
        rationale="Synthetic native-wheel source evidence for deterministic validator tests only.",
        sources=sources,
        wheels=tuple(wheels),
        builder_id="https://example.invalid/builder",
        build_type="https://example.invalid/native-wheel/v1",
        build_parameters_sha256=hashlib.sha256(
            json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        certificate_identity="https://example.invalid/workflow@refs/tags/v1",
        oidc_issuer="https://example.invalid/issuer",
        trusted_root=_evidence_file(root, "trust.json", b"{}"),
    ), {"version": "2.4.6", "source": {"registry": "https://pypi.org/simple"}, "wheels": locked}


def _parse_source_record(value: object) -> tuple[WheelSourceAdmission, ...]:
    package = PythonPackageAdmission(
        name="numpy",
        version="2.4.6",
        native_artifacts=True,
        license_expression="BSD-3-Clause",
    )
    return parse_wheel_sources(value, (package,), {"BSD-3-Clause"})


def _fake_cosign(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    output = cast(IO[str], kwargs["stdout"])
    output.write("GitVersion:    v3.1.3\n" if command[1:] == ["version"] else "Verified OK\n")
    return subprocess.CompletedProcess(command, 0)


@pytest.fixture
def wheel_cosign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "cosign"
    executable.write_text("synthetic path; subprocess execution is mocked")
    monkeypatch.setattr(
        "alpha_research_governance.dependency_admission.wheel_sources.shutil.which",
        lambda _: str(executable),
    )


def test_wheel_only_source_verification_pins_inputs_and_verifier_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wheel_cosign: None,
) -> None:
    record, locked = _wheel_source_fixture(tmp_path)
    assert _parse_source_record([record.model_dump(mode="json")]) == (record,)
    calls: list[list[str]] = []

    def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert command[0] == str(tmp_path / "cosign")
        assert kwargs["timeout"] == 60
        assert kwargs["env"] == {"PATH": os.environ.get("PATH", "")}
        if command[1] != "version":
            bundle = Path(command[command.index("--bundle") + 1])
            trust = Path(command[command.index("--trusted-root") + 1])
            assert bundle.parent != tmp_path and trust.read_bytes() == b"{}"
            assert bundle.is_file()
            assert "--check-claims=true" in command
            assert (
                command[command.index("--certificate-identity") + 1] == record.certificate_identity
            )
            assert command[command.index("--certificate-oidc-issuer") + 1] == record.oidc_issuer
            assert command[command.index("--type") + 1] == "https://slsa.dev/provenance/v1"
            assert not any("ignore" in arg or "regexp" in arg for arg in command)
        return _fake_cosign(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", inspect)
    verify_wheel_sources(tmp_path, locked, record)
    assert len(calls) == 3
    assert {call[call.index("--digest") + 1] for call in calls[1:]} == {"c" * 64, "d" * 64}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "unregistered", "exact native"),
        ("version", "2.4.5", "exact native"),
        ("owner_role", "unknown", "Platform"),
        ("rationale", "", "fields"),
        ("sources", [], "counts"),
        ("wheels", [], "counts"),
        ("builder_id", "http://example.invalid", "HTTPS"),
        ("oidc_issuer", "https://user:password@example.invalid", "HTTPS"),
        ("certificate_identity", "https://example.invalid?secret=bad", "HTTPS"),
        ("build_parameters_sha256", "mutable", "fields"),
        ("unknown", True, "fields"),
    ],
)
def test_wheel_source_policy_rejects_invalid_records(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    record, _ = _wheel_source_fixture(tmp_path)
    data = record.model_dump(mode="json")
    data[field] = value
    with pytest.raises(DependencyAdmissionError, match=message):
        _parse_source_record([data])


@pytest.mark.parametrize(
    ("part", "field", "value", "message"),
    [
        ("sources", "uri", "https://example.invalid/main", "immutable revision"),
        ("sources", "sha256", "", "fields"),
        ("sources", "license_expression", "unreviewed", "license"),
        ("wheels", "filename", "other-2.4.6-cp312-cp312-linux.whl", "filename"),
        ("wheels", "sha256", True, "fields"),
    ],
)
def test_nested_wheel_source_identity_is_strict(
    tmp_path: Path,
    part: str,
    field: str,
    value: object,
    message: str,
) -> None:
    record, _ = _wheel_source_fixture(tmp_path)
    data = record.model_dump(mode="json")
    data[part][0][field] = value
    with pytest.raises(DependencyAdmissionError, match=message):
        _parse_source_record([data])


@pytest.mark.parametrize("part", ["records", "sources", "wheels"])
def test_duplicate_wheel_source_evidence_is_rejected(tmp_path: Path, part: str) -> None:
    record, _ = _wheel_source_fixture(tmp_path)
    data = record.model_dump(mode="json")
    records = [data]
    if part == "records":
        records.append(data)
    else:
        data[part].append(data[part][0])
    with pytest.raises(DependencyAdmissionError, match="duplicate"):
        _parse_source_record(records)


@pytest.mark.parametrize(
    "path", ["../escape.json", "/tmp/escape.json", "./trust.json", "a//b", "a/../b"]
)
def test_wheel_source_paths_cannot_escape(tmp_path: Path, path: str) -> None:
    record, _ = _wheel_source_fixture(tmp_path)
    data = record.model_dump(mode="json")
    data["trusted_root"]["path"] = path
    with pytest.raises(DependencyAdmissionError, match="canonical and relative"):
        _parse_source_record([data])


@pytest.mark.parametrize(
    "case", ["missing", "tampered", "symlink", "directory_symlink", "oversized"]
)
def test_wheel_source_files_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    wheel_cosign: None,
) -> None:
    record, locked = _wheel_source_fixture(tmp_path)
    trust = tmp_path / record.trusted_root.path
    if case == "missing":
        trust.unlink()
    elif case == "tampered":
        trust.write_bytes(b"changed")
    elif case == "symlink":
        trust.unlink()
        trust.symlink_to(tmp_path / record.wheels[0].bundle.path)
    elif case == "directory_symlink":
        (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
        data = record.model_dump(mode="json")
        data["trusted_root"]["path"] = "link/trust.json"
        record = _parse_source_record([data])[0]
    else:
        trust.write_bytes(b"x" * 5_000_001)
    monkeypatch.setattr(subprocess, "run", _fake_cosign)
    with pytest.raises(
        DependencyAdmissionError, match=r"missing|digest mismatch|symlinks|size bound"
    ):
        verify_wheel_sources(tmp_path, locked, record)


@pytest.mark.parametrize("case", ["omitted", "added", "duplicate", "digest", "source", "sdist"])
def test_wheel_provenance_must_cover_the_complete_lock(tmp_path: Path, case: str) -> None:
    record, locked = _wheel_source_fixture(tmp_path)
    wheels = cast(list[dict[str, str]], locked["wheels"])
    if case == "omitted":
        wheels.pop()
    elif case == "added":
        wheels.append(
            {"url": "https://files.pythonhosted.org/new.whl", "hash": "sha256:" + "e" * 64}
        )
    elif case == "duplicate":
        wheels.append(wheels[0])
    elif case == "digest":
        wheels[0]["hash"] = "sha256:" + "e" * 64
    elif case == "source":
        wheels[0]["url"] = wheels[0]["url"].replace("files.pythonhosted.org", "example.invalid")
    else:
        locked["sdist"] = {"hash": "malformed"}
    with pytest.raises(
        DependencyAdmissionError, match=r"wheel set|duplicate|unapproved|existing sdist"
    ):
        verify_wheel_sources(tmp_path, locked, record)


@pytest.mark.parametrize(
    "case",
    [
        "publish_only",
        "subject",
        "builder",
        "parameters",
        "materials",
        "unknown",
        "duplicate_json",
        "encoding",
    ],
)
def test_provenance_claims_are_checked_before_signature_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    wheel_cosign: None,
) -> None:
    record, locked = _wheel_source_fixture(tmp_path)
    path = tmp_path / record.wheels[0].bundle.path
    bundle = json.loads(path.read_bytes())
    statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
    predicate = statement["predicate"]
    if case == "publish_only":
        statement["predicateType"] = "https://docs.pypi.org/attestations/publish/v1"
    elif case == "subject":
        statement["subject"][0]["digest"]["sha256"] = "f" * 64
    elif case == "builder":
        predicate["runDetails"]["builder"]["id"] = "https://example.invalid/attacker"
    elif case == "parameters":
        predicate["buildDefinition"]["externalParameters"]["version"] = "2.4.5"
    elif case == "materials":
        predicate["buildDefinition"]["resolvedDependencies"] = []
    elif case == "unknown":
        predicate["buildDefinition"]["ignored"] = True
    payload = json.dumps(statement)
    if case == "duplicate_json":
        payload = payload.replace('"subject":', '"subject": [], "subject":')
    bundle["dsseEnvelope"]["payload"] = (
        "%%%" if case == "encoding" else base64.b64encode(payload.encode()).decode()
    )
    evidence = _evidence_file(tmp_path, path.name, json.dumps(bundle).encode())
    data = record.model_dump(mode="json")
    data["wheels"][0]["bundle"] = evidence.model_dump()
    record = _parse_source_record([data])[0]
    monkeypatch.setattr(subprocess, "run", _fake_cosign)
    with pytest.raises(DependencyAdmissionError, match=r"mismatch|unsupported|JSON|encoding"):
        verify_wheel_sources(tmp_path, locked, record)


@pytest.mark.parametrize("case", ["signature", "missing_tool", "timeout", "wrong_version"])
def test_wheel_sources_require_successful_exact_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    wheel_cosign: None,
) -> None:
    record, locked = _wheel_source_fixture(tmp_path)

    def failing(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if case == "missing_tool":
            raise FileNotFoundError("cosign")
        if case == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        if case == "wrong_version":
            cast(IO[str], kwargs["stdout"]).write("GitVersion:    v3.1.30\n")
            return subprocess.CompletedProcess(command, 0)
        if command[1] == "version":
            return _fake_cosign(command, **kwargs)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(DependencyAdmissionError, match="Cosign"):
        verify_wheel_sources(tmp_path, locked, record)


def _inline_toml(value: object) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{json.dumps(key)} = {_inline_toml(item)}" for key, item in value.items())
            + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_inline_toml(item) for item in value) + "]"
    return json.dumps(value)


def test_alternative_flows_through_existing_policy_and_lock_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wheel_cosign: None,
) -> None:
    record, replacement = _wheel_source_fixture(tmp_path)
    _copy_current_wheel_evidence(tmp_path)
    policy_path = _policy_fixture(tmp_path)
    policy_path.write_text(
        "wheel_source_admissions = "
        + _inline_toml([record.model_dump(mode="json")])
        + "\n"
        + policy_path.read_text(),
    )
    policy = load_policy(policy_path)
    assert policy.wheel_source_admissions == (record,)
    parts = (REPOSITORY_ROOT / "uv.lock").read_text().split("[[package]]")
    for index, part in enumerate(parts):
        if '\nname = "numpy"\n' in part:
            parts[index] = (
                '\nname = "numpy"\n'
                + "\n".join(f"{key} = {_inline_toml(value)}" for key, value in replacement.items())
                + "\n\n"
            )
            break
    else:
        pytest.fail("numpy fixture missing")
    (tmp_path / "uv.lock").write_text("[[package]]".join(parts))
    monkeypatch.setattr(subprocess, "run", _fake_cosign)
    assert _python_lock_findings(tmp_path, policy) == []
    original = load_policy(POLICY_PATH)
    assert original.wheel_source_admissions == ()
    assert _python_lock_findings(tmp_path, original) == [
        "numpy lacks a digest-bound source distribution"
    ]
    (tmp_path / record.wheels[0].bundle.path).write_bytes(b"tampered")
    assert any("digest mismatch" in finding for finding in _python_lock_findings(tmp_path, policy))


def _bootstrap_fixture(root: Path) -> tuple[BootstrapWheelAdmission, dict[str, object]]:
    record, locked = _wheel_source_fixture(root)
    data = record.model_dump(
        mode="json", exclude={"builder_id", "build_type", "build_parameters_sha256"}
    )
    for wheel in data["wheels"]:
        path = root / wheel["bundle"]["path"]
        bundle = json.loads(path.read_bytes())
        statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
        statement["predicateType"] = "https://docs.pypi.org/attestations/publish/v1"
        statement["predicate"] = None
        bundle["dsseEnvelope"]["payload"] = base64.b64encode(
            json.dumps(statement).encode()
        ).decode()
        wheel["bundle"] = _evidence_file(root, path.name, json.dumps(bundle).encode()).model_dump()
    data.update(
        usage="isolated_development_and_ci",
        source_to_wheel_binding="unverified",
        finding_id="B07-DEP-001",
        reviewed_on="2026-09-04",
        expires_on="2026-10-04",
        residual_risk="The publisher's wheel may differ from the inspected upstream sources.",
        closure_condition="Supply signed source-to-wheel build evidence or remove the dependency.",
    )
    for kind in ("source_review", "security_review", "native_inventory", "compatibility_report"):
        data[kind] = _evidence_file(
            root, kind + ".txt", b"Synthetic review evidence; no real approval.\n"
        ).model_dump()
    return _parse_bootstrap_record([data])[0], locked


def _parse_bootstrap_record(value: object) -> tuple[BootstrapWheelAdmission, ...]:
    return parse_bootstrap_wheels(
        value,
        (
            PythonPackageAdmission(
                name="numpy",
                version="2.4.6",
                native_artifacts=True,
                license_expression="BSD-3-Clause",
            ),
        ),
        {"BSD-3-Clause"},
        as_of_date=date(2026, 9, 3),
        review_due_on=date(2026, 12, 2),
    )


@pytest.mark.parametrize("when", [date(2026, 9, 4), date(2026, 10, 4)])
@pytest.mark.parametrize("empty_object", [False, True])
def test_bootstrap_publication_verification_is_explicit_and_date_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wheel_cosign: None,
    when: date,
    empty_object: bool,
) -> None:
    record, locked = _bootstrap_fixture(tmp_path)
    if empty_object:
        data = record.model_dump(mode="json")
        for wheel in data["wheels"]:
            path = tmp_path / wheel["bundle"]["path"]
            bundle = json.loads(path.read_bytes())
            statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
            statement["predicate"] = {}
            bundle["dsseEnvelope"]["payload"] = base64.b64encode(
                json.dumps(statement).encode()
            ).decode()
            wheel["bundle"] = _evidence_file(
                tmp_path, path.name, json.dumps(bundle).encode()
            ).model_dump()
        record = _parse_bootstrap_record([data])[0]
    calls: list[list[str]] = []

    def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] != "version":
            assert (
                command[command.index("--type") + 1]
                == "https://docs.pypi.org/attestations/publish/v1"
            )
            assert "--check-claims=true" in command
            assert (
                command[command.index("--certificate-identity") + 1] == record.certificate_identity
            )
            assert command[command.index("--certificate-oidc-issuer") + 1] == record.oidc_issuer
            assert command[command.index("--digest") + 1] in {"c" * 64, "d" * 64}
            assert not any("ignore" in arg or "regexp" in arg for arg in command)
        return _fake_cosign(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", inspect)
    verify_bootstrap_wheels(tmp_path, locked, record, validation_date=when)
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("usage", "production"),
        ("source_to_wheel_binding", "verified"),
        ("owner_role", "unknown"),
        ("finding_id", ""),
        ("residual_risk", ""),
        ("closure_condition", ""),
        ("source_review", {}),
        ("unknown", True),
        ("reviewed_on", "2026-09-02"),
        ("expires_on", "2026-09-04"),
        ("expires_on", "2026-10-05"),
        ("expires_on", "2026-12-03"),
        ("name", "unadmitted"),
        ("version", "0.0.0"),
    ],
)
def test_bootstrap_policy_rejects_missing_unsafe_or_unbounded_decisions(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    record, _ = _bootstrap_fixture(tmp_path)
    data = record.model_dump(mode="json")
    data[field] = value
    with pytest.raises(DependencyAdmissionError):
        _parse_bootstrap_record([data])


@pytest.mark.parametrize("case", ["missing", "empty", "tampered", "symlink", "expired", "future"])
def test_bootstrap_review_failures_stop_before_verifier_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    record, locked = _bootstrap_fixture(tmp_path)
    path = tmp_path / record.security_review.path
    when = date(2026, 9, 4)
    if case == "missing":
        path.unlink()
    elif case == "empty":
        data = record.model_dump(mode="json")
        data["security_review"] = _evidence_file(tmp_path, path.name, b" \n").model_dump()
        record = _parse_bootstrap_record([data])[0]
    elif case == "tampered":
        path.write_bytes(b"changed")
    elif case == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / record.source_review.path)
    elif case == "expired":
        when = date(2026, 10, 5)
    else:
        when = date(2026, 9, 3)

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("review failure must precede verifier execution")

    monkeypatch.setattr(subprocess, "run", unexpected)
    with pytest.raises(DependencyAdmissionError, match=r"missing|empty|digest|symlinks|expired"):
        verify_bootstrap_wheels(tmp_path, locked, record, validation_date=when)


@pytest.mark.parametrize(
    "case", ["body", "type", "subject", "tampered", "signature", "sdist", "missing_wheel"]
)
def test_bootstrap_does_not_bypass_publication_signature_or_lock_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wheel_cosign: None,
    case: str,
) -> None:
    record, locked = _bootstrap_fixture(tmp_path)
    path = tmp_path / record.wheels[0].bundle.path
    if case in {"body", "type", "subject"}:
        bundle = json.loads(path.read_bytes())
        statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
        if case == "body":
            statement["predicate"] = {"verified": True}
        elif case == "type":
            statement["predicateType"] = "https://slsa.dev/provenance/v1"
        else:
            statement["subject"][0]["digest"]["sha256"] = "f" * 64
        bundle["dsseEnvelope"]["payload"] = base64.b64encode(
            json.dumps(statement).encode()
        ).decode()
        data = record.model_dump(mode="json")
        data["wheels"][0]["bundle"] = _evidence_file(
            tmp_path, path.name, json.dumps(bundle).encode()
        ).model_dump()
        record = _parse_bootstrap_record([data])[0]
    elif case == "tampered":
        path.write_bytes(b"changed")
    elif case == "sdist":
        locked["sdist"] = {"hash": "malformed"}
    elif case == "missing_wheel":
        cast(list[object], locked["wheels"]).pop()

    def verify(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if case == "signature" and command[1] != "version":
            return subprocess.CompletedProcess(command, 1)
        return _fake_cosign(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", verify)
    with pytest.raises(DependencyAdmissionError):
        verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 4))


def test_bootstrap_policy_lock_integration_and_removal_cannot_enable_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wheel_cosign: None,
) -> None:
    record, locked = _bootstrap_fixture(tmp_path)
    record = record.model_copy(update={"finding_id": "B07-DEP-002"})
    policy_path = tmp_path / "docs/architecture/dependency-admission.toml"
    policy_path.parent.mkdir(parents=True)
    original = POLICY_PATH.read_text()
    _copy_current_wheel_evidence(tmp_path)
    policy_path.write_text(
        original
        + "\n[[bootstrap_wheel_admissions]]\n"
        + "\n".join(
            key + " = " + _inline_toml(value)
            for key, value in record.model_dump(mode="json").items()
        )
    )
    policy = load_policy(policy_path)
    parts = (REPOSITORY_ROOT / "uv.lock").read_text().split("[[package]]")
    for index, part in enumerate(parts):
        if '\nname = "numpy"\n' in part:
            parts[index] = (
                '\nname = "numpy"\n'
                + "\n".join(f"{key} = {_inline_toml(value)}" for key, value in locked.items())
                + "\n"
            )
            break
    (tmp_path / "uv.lock").write_text("[[package]]".join(parts))
    monkeypatch.setattr(subprocess, "run", _fake_cosign)
    assert _python_lock_findings(tmp_path, policy, validation_date=date(2026, 9, 4)) == []
    assert any(
        "expired" in f
        for f in _python_lock_findings(tmp_path, policy, validation_date=date(2026, 10, 5))
    )
    with pytest.raises(DependencyAdmissionError, match="bootstrap-only"):
        require_release_admission(tmp_path)
    policy_path.write_text(_without_bootstrap(original))
    for relative in policy.lock_paths:
        if relative != "uv.lock":
            destination = tmp_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((REPOSITORY_ROOT / relative).read_bytes())
    with pytest.raises(DependencyAdmissionError, match="lacks a digest-bound source distribution"):
        require_release_admission(tmp_path)


def test_bootstrap_and_build_profiles_cannot_overlap(tmp_path: Path) -> None:
    bootstrap, _ = _bootstrap_fixture(tmp_path)
    build, _ = _wheel_source_fixture(tmp_path)
    policy_path = _policy_fixture(tmp_path)
    policy_path.write_text(
        "wheel_source_admissions = "
        + _inline_toml([build.model_dump(mode="json")])
        + "\n"
        + _without_bootstrap(policy_path.read_text()).replace(
            "bootstrap_wheel_admissions = []",
            "bootstrap_wheel_admissions = " + _inline_toml([bootstrap.model_dump(mode="json")]),
        )
    )
    with pytest.raises(DependencyAdmissionError, match="both wheel admission profiles"):
        load_policy(policy_path)


def test_bootstrap_report_paths_and_duplicate_records_are_rejected(tmp_path: Path) -> None:
    record, _ = _bootstrap_fixture(tmp_path)
    data = record.model_dump(mode="json")
    with pytest.raises(DependencyAdmissionError, match="duplicate"):
        _parse_bootstrap_record([data, data])
    data["source_review"]["path"] = "../outside.txt"
    with pytest.raises(DependencyAdmissionError, match="canonical and relative"):
        _parse_bootstrap_record([data])


def test_cli_reports_bootstrap_limit_and_legacy_policy_remains_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record, _ = _bootstrap_fixture(tmp_path)
    policy_path = _policy_fixture(tmp_path)
    legacy = _without_bootstrap(policy_path.read_text()).replace(
        "bootstrap_wheel_admissions = []\n", ""
    )
    policy_path.write_text(legacy)
    assert load_policy(policy_path).bootstrap_wheel_admissions == ()
    policy_path.write_text(
        "bootstrap_wheel_admissions = "
        + _inline_toml([record.model_dump(mode="json")])
        + "\n"
        + legacy
    )
    policy = load_policy(policy_path)
    monkeypatch.setattr(
        "alpha_research_governance.dependency_admission.validate_repository", lambda _root: policy
    )
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "BOOTSTRAP ONLY: numpy==2.4.6" in output
    assert "unverified; B07-DEP-001" in output
    assert "owner=platform; expires=2026-10-04; artifact release blocked" in output


def test_release_admission_evaluates_the_current_graph_without_bootstrap_bypass() -> None:
    policy = load_policy(POLICY_PATH)
    if policy.bootstrap_wheel_admissions:
        with pytest.raises(DependencyAdmissionError, match="bootstrap-only"):
            require_release_admission(REPOSITORY_ROOT)
    else:
        require_release_admission(REPOSITORY_ROOT)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
