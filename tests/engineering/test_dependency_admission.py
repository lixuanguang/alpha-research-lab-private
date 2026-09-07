"""Deterministic and adversarial dependency-admission tests for package B07."""

from __future__ import annotations

# standard library imports
import base64
import hashlib
import importlib.metadata
import io
import json
import os
import subprocess
import tomllib
from datetime import UTC, date, datetime
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import TypeGuard

# third party library imports
import pytest
from pydantic import BaseModel, TypeAdapter

# project library imports
from alpha_research_governance.dependency_admission import (
    DependencyAdmission,
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


def _model_payload(model: BaseModel) -> dict[str, object]:
    """Convert a Pydantic fixture record to a typed JSON-compatible mapping.

    Args:
        model: Validated record whose serialized fields are used by a policy fixture.

    Returns:
        A string-keyed mapping retaining the model's serialized values.
    """
    raw: object = model.model_dump(mode="json")
    return TypeAdapter(dict[str, object]).validate_python(raw)


def _json_mapping(value: bytes | str) -> dict[str, object]:
    """Parse one JSON object at a typed fixture boundary without unchecked containers.

    Args:
        value: UTF-8 JSON bytes or text containing an object.

    Returns:
        A string-keyed mapping preserving nested JSON values as objects.
    """
    raw: object = json.loads(value)
    return TypeAdapter(dict[str, object]).validate_python(raw)


def _is_string_mapping(value: object) -> TypeGuard[dict[str, object]]:
    """Identify a mutable JSON object without copying its nested container."""
    if not isinstance(value, dict):
        return False
    return all(isinstance(key, str) for key in value)


def _mapping(value: object) -> dict[str, object]:
    """Narrow one nested JSON or TOML object while preserving object identity."""
    if not _is_string_mapping(value):
        raise TypeError("expected a JSON object with string keys")
    return value


def _object_list(value: object) -> list[object]:
    """Narrow one nested JSON array while preserving its mutable list identity."""
    if not isinstance(value, list):
        raise TypeError("expected a JSON array")
    return value


def _toml_mapping(path: Path) -> dict[str, object]:
    """Parse a TOML fixture through an explicit object boundary."""
    raw: object = tomllib.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(dict[str, object]).validate_python(raw)


def _bundle_statement(bundle: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    """Decode one DSSE statement and return it with its mutable envelope mapping."""
    envelope = _mapping(bundle["dsseEnvelope"])
    payload = envelope["payload"]
    assert isinstance(payload, str)
    return _json_mapping(base64.b64decode(payload)), envelope


def _policy_fixture(tmp_path: Path) -> Path:
    """Copy the checked-in dependency policy to an isolated mutation fixture.

    Args:
        tmp_path: Existing directory in which to write or overwrite the policy copy.

    Returns:
        The temporary ``dependency-admission.toml`` path.

    Raises:
        OSError: The source policy cannot be read or the fixture cannot be written.
    """
    path = tmp_path / "dependency-admission.toml"
    path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _without_bootstrap(text: str) -> str:
    """Keep the prefix before the first bootstrap table and insert one empty profile array."""
    return "bootstrap_wheel_admissions = []\n" + text.split("[[bootstrap_wheel_admissions]]")[
        0
    ].replace("bootstrap_wheel_admissions = []\n", "")


def _copy_current_wheel_evidence(root: Path) -> None:
    """Materialize structural-test inputs; process doubles do not authenticate signatures.

    Args:
        root: Temporary repository root receiving copies of current bootstrap reports,
            trust roots and attestation bundles; parent directories are created as needed.

    Raises:
        OSError: A declared evidence file cannot be read or its fixture copy cannot be written.
    """
    data = _toml_mapping(POLICY_PATH)
    records = TypeAdapter(list[dict[str, object]]).validate_python(
        data.get("bootstrap_wheel_admissions", [])
    )
    for record in records:
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
        wheels = TypeAdapter(list[dict[str, object]]).validate_python(record["wheels"])
        reports.extend(wheel["bundle"] for wheel in wheels)
        for report in reports:
            report_mapping = _mapping(report)
            report_path = report_mapping["path"]
            assert isinstance(report_path, str)
            target = root / report_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPOSITORY_ROOT / report_path).read_bytes())


def _replace(path: Path, old: str, new: str) -> None:
    """Replace the first required policy fragment in place for a mutation test.

    Args:
        path: Temporary UTF-8 policy file to read and overwrite.
        old: Exact text required to be present before the mutation.
        new: Replacement text for the first occurrence only.

    Raises:
        AssertionError: The expected original fragment is absent.
        OSError: The fixture cannot be read or rewritten.
    """
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _clean_audit_report() -> dict[str, object]:
    """Build a synthetic report covering every admitted version with no vulnerabilities.

    Returns:
        A fresh dependency list in policy order and an empty fixes list; no scanner is run.

    Raises:
        DependencyAdmissionError: The checked-in admission policy cannot be loaded.
    """
    policy = load_policy(POLICY_PATH)
    return {
        "dependencies": [
            {"name": package.name, "version": package.version, "vulns": []}
            for package in policy.packages
        ],
        "fixes": [],
    }


def _write_json(tmp_path: Path, name: str, value: object) -> Path:
    """Write a JSON fixture with sorted object keys, overwriting an existing file.

    Args:
        tmp_path: Existing directory containing the fixture.
        name: Fixture filename beneath the temporary directory.
        value: JSON-serializable test payload.

    Returns:
        The path containing the UTF-8 JSON text.

    Raises:
        TypeError: The payload contains a value unsupported by the JSON encoder.
        OSError: The fixture cannot be written.
    """
    path = tmp_path / name
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


class TestDependencyPolicyAndPipAudit:
    """Exercise dependency policy, scanner coverage and vulnerability contracts."""

    @pytest.mark.skipif(
        RUNNING_UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks"
    )
    def test_dependency_admission_contract_is_partial_and_bounds_sbom_successor(self) -> None:
        """Validate current admissions, package counts, tool pins and open findings."""
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
            (
                "runtime_installation_allowed = false",
                "runtime_installation_allowed = true",
                "runtime",
            ),
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
    def test_policy_mutations_fail_closed(
        self, tmp_path: Path, old: str, new: str, message: str
    ) -> None:
        """Reject mutations to status, install/index rules, licenses, tools and lock pins."""
        path = _policy_fixture(tmp_path)
        _replace(path, old, new)

        with pytest.raises(DependencyAdmissionError, match=message):
            load_policy(path)

    def test_unknown_and_malformed_policy_fields_fail_closed(self, tmp_path: Path) -> None:
        """Translate unknown policy fields and malformed TOML into admission errors."""
        unknown = _policy_fixture(tmp_path)
        _replace(unknown, "[lock_digests]", "unknown = true\n\n[lock_digests]")
        with pytest.raises(DependencyAdmissionError, match="missing or unknown fields"):
            load_policy(unknown)

        malformed = tmp_path / "malformed.toml"
        malformed.write_text("schema_version = [\n", encoding="utf-8")
        with pytest.raises(DependencyAdmissionError, match="invalid TOML"):
            load_policy(malformed)

    def test_emergency_override_requires_specific_bounded_audited_record(
        self, tmp_path: Path
    ) -> None:
        """Accept an attributed override and reject vague identity or long expiry."""
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

    def test_complete_clean_pip_audit_report_passes(self, tmp_path: Path) -> None:
        """Accept a synthetic clean report that covers the complete admitted package graph."""
        report = _write_json(tmp_path, "audit.json", _clean_audit_report())
        assess_pip_audit_report(report, load_policy(POLICY_PATH))

    def test_live_audit_uses_the_complete_exact_lock_graph(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pass every admitted version to the scanner with strict, non-resolving audit options."""
        policy = load_policy(POLICY_PATH)

        def admitted_version(_name: str) -> str:
            """Return the pinned scanner version for the exact-audit invocation.

            Args:
                _name: Distribution name, intentionally ignored by this fixture.

            Returns:
                The admitted pip-audit version.
            """
            return "2.10.1"

        monkeypatch.setattr(importlib.metadata, "version", admitted_version)

        def run_audit(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Inspect requirements and write a clean report without running pip-audit.

            Args:
                command: Scanner argv identifying the requirements and report paths.
                **kwargs: Subprocess options; ``cwd`` must identify the fixture repository.

            Returns:
                A successful process result after writing the synthetic report.

            Raises:
                AssertionError: Command options, working directory or exact requirements drift.
                OSError: Requirements cannot be read or the report cannot be written.
            """
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

        monkeypatch.setattr(
            "alpha_research_governance.dependency_admission.subprocess.run", run_audit
        )
        run_pip_audit(REPOSITORY_ROOT, policy)

    @pytest.mark.parametrize(
        "mutation", ["missing", "wrong_version", "skip", "skip_unknown", "duplicate"]
    )
    def test_pip_audit_coverage_gaps_fail_closed(self, tmp_path: Path, mutation: str) -> None:
        """Reject omitted, misversioned, skipped or duplicated dependencies in scanner reports."""
        payload = _clean_audit_report()
        dependencies = TypeAdapter(list[dict[str, object]]).validate_python(payload["dependencies"])
        payload["dependencies"] = dependencies
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

    def test_vulnerability_requires_exact_owned_exploitability_decision(
        self, tmp_path: Path
    ) -> None:
        """Require an unexpired decision for the package/version and reject drift."""
        payload = _clean_audit_report()
        dependencies = TypeAdapter(list[dict[str, object]]).validate_python(payload["dependencies"])
        payload["dependencies"] = dependencies
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
    """Build a synthetic Scorecard report with fixed time, tool identity and required checks.

    Args:
        commit: Target repository revision placed in the report without validation.

    Returns:
        A fresh report dated 2026-09-03 UTC for the fixture repository and supplied commit.
    """
    checks: list[dict[str, object]] = [
        {"name": name, "score": 8, "reason": "synthetic deterministic signal"}
        for name in ("License", "Maintained", "Pinned-Dependencies", "Vulnerabilities")
    ]
    return {
        "date": "2026-09-03T00:00:00Z",
        "repo": {"name": "github.com/example/project", "commit": commit},
        "scorecard": {"version": "5.5.0", "commit": "b" * 40},
        "score": 7.5,
        "checks": checks,
    }


class TestScorecardAndLockAdmission:
    """Exercise Scorecard freshness, lock coverage and runtime-install controls."""

    def test_scorecard_signal_is_fresh_commit_bound_and_advisory(self, tmp_path: Path) -> None:
        """Accept a fresh synthetic Scorecard signal bound to the expected repository and commit."""
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
        self, tmp_path: Path, failure: str
    ) -> None:
        """Reject mismatched, stale, inconclusive or duplicated Scorecard signal identities."""
        payload = _scorecard_report()
        repository = "github.com/example/project"
        validation_time = datetime(2026, 9, 3, 12, tzinfo=UTC)
        if failure == "repository":
            repository = "github.com/other/project"
        elif failure == "stale":
            payload["date"] = "2026-08-01T00:00:00Z"
        elif failure == "inconclusive":
            checks = TypeAdapter(list[dict[str, object]]).validate_python(payload["checks"])
            payload["checks"] = checks
            checks[0]["score"] = -1
        elif failure == "version":
            scorecard = _mapping(payload["scorecard"])
            payload["scorecard"] = scorecard
            scorecard["version"] = "5.4.0"
        elif failure == "engine_commit":
            scorecard = _mapping(payload["scorecard"])
            payload["scorecard"] = scorecard
            scorecard["commit"] = "unknown"
        else:
            checks = TypeAdapter(list[dict[str, object]]).validate_python(payload["checks"])
            payload["checks"] = checks
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
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        wheel_cosign: None,
    ) -> None:
        """Check current lock coverage with copied evidence and a simulated signature verifier."""
        # Real authentication remains blocking in validate_repository above and the full lane.
        _copy_current_wheel_evidence(tmp_path)
        (tmp_path / "uv.lock").write_bytes((REPOSITORY_ROOT / "uv.lock").read_bytes())
        monkeypatch.setattr(subprocess, "run", _fake_cosign)
        assert _python_lock_findings(tmp_path, load_policy(POLICY_PATH)) == []

    @pytest.mark.skipif(
        RUNNING_UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks"
    )
    def test_repository_review_expiry_fails_closed(self) -> None:
        """Reject repository admission after the recorded policy review window expires."""
        with pytest.raises(DependencyAdmissionError, match="review is stale"):
            validate_repository(REPOSITORY_ROOT, validation_date=date(2026, 12, 4))

    def test_mutable_action_reference_and_runtime_install_are_rejected(
        self, tmp_path: Path
    ) -> None:
        """Detect mutable workflow actions and runtime package-install calls in fixtures."""
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
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Report unadmitted or missing audit tools and retain usage errors for unknown commands."""
        policy = load_policy(POLICY_PATH)

        def unadmitted_version(_name: str) -> str:
            """Return an intentionally unadmitted scanner version.

            Args:
                _name: Distribution name, intentionally ignored by this fixture.

            Returns:
                A version rejected by the admission policy.
            """
            return "0.0.0"

        monkeypatch.setattr(importlib.metadata, "version", unadmitted_version)
        with pytest.raises(DependencyAdmissionError, match="not admitted"):
            run_pip_audit(REPOSITORY_ROOT, policy)

        def missing_version(_name: str) -> str:
            """Simulate absent distribution metadata for the audit-tool lookup.

            Args:
                _name: Requested distribution name; ignored because every lookup fails.

            Returns:
                No version is returned; the annotation preserves the replaced lookup signature.

            Raises:
                PackageNotFoundError: Always, to exercise the missing-tool error translation.
            """
            raise PackageNotFoundError

        monkeypatch.setattr("importlib.metadata.version", missing_version)
        with pytest.raises(DependencyAdmissionError, match="not installed"):
            run_pip_audit(REPOSITORY_ROOT, policy)

        assert main(["unsupported"]) == 2
        assert "usage:" in capsys.readouterr().err


def _evidence_file(root: Path, filename: str, content: bytes) -> EvidenceFile:
    """Write fixture bytes and return their relative path and calculated SHA-256 identity.

    Args:
        root: Existing temporary evidence directory.
        filename: Relative fixture filename; parent directories must already exist.
        content: Exact bytes to write, replacing any existing file.

    Returns:
        Evidence identity describing the written bytes, without authenticating their claims.

    Raises:
        OSError: The fixture file cannot be written.
    """
    (root / filename).write_bytes(content)
    return EvidenceFile(path=filename, sha256=hashlib.sha256(content).hexdigest())


class DependencyAdmissionFixtureFactory:
    """Own deterministic filesystem fixtures for wheel-source admission contracts."""

    def __init__(self, root: Path) -> None:
        """Bind the factory to the temporary repository root it materializes.

        Args:
            root: Temporary repository root receiving generated evidence files.
        """
        self._root = root

    def wheel_source(self) -> tuple[WheelSourceAdmission, dict[str, object]]:
        """Make synthetic source claims; the fake runner does not authenticate these signatures.

        Returns:
            The NumPy 2.4.6 build-provenance admission and its matching lock fragment for
            macOS arm64 and Linux x86-64 wheels; no wheel or upstream archive is downloaded.

        Raises:
            OSError: A synthetic evidence file cannot be written.
        """
        sources = (
            SourceArchive(
                uri="https://example.invalid/source/archive/" + "a" * 40,
                revision="a" * 40,
                sha256="b" * 64,
                license_expression="BSD-3-Clause",
            ),
        )
        parameters: dict[str, object] = {
            "externalParameters": {"version": "2.4.6"},
            "internalParameters": {},
        }
        wheels: list[WheelProvenance] = []
        locked: list[dict[str, str]] = []
        for platform, digest in (
            ("macosx_11_0_arm64", "c" * 64),
            ("manylinux_2_28_x86_64", "d" * 64),
        ):
            filename = f"numpy-2.4.6-cp312-cp312-{platform}.whl"
            statement: dict[str, object] = {
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
            bundle_payload: dict[str, object] = {
                "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                "verificationMaterial": {},
                "dsseEnvelope": {
                    "payloadType": "application/vnd.in-toto+json",
                    "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
                    "signatures": [],
                },
            }
            bundle = json.dumps(bundle_payload).encode()
            wheels.append(
                WheelProvenance(
                    filename=filename,
                    sha256=digest,
                    bundle=_evidence_file(self._root, platform + ".json", bundle),
                )
            )
            locked.append(
                {"url": "https://files.pythonhosted.org/" + filename, "hash": "sha256:" + digest}
            )
        return WheelSourceAdmission(
            name="numpy",
            version="2.4.6",
            owner_role="platform",
            rationale=(
                "Synthetic native-wheel source evidence for deterministic validator tests only."
            ),
            sources=sources,
            wheels=tuple(wheels),
            builder_id="https://example.invalid/builder",
            build_type="https://example.invalid/native-wheel/v1",
            build_parameters_sha256=hashlib.sha256(
                json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            certificate_identity="https://example.invalid/workflow@refs/tags/v1",
            oidc_issuer="https://example.invalid/issuer",
            trusted_root=_evidence_file(self._root, "trust.json", b"{}"),
        ), {"version": "2.4.6", "source": {"registry": "https://pypi.org/simple"}, "wheels": locked}


def _parse_source_record(value: object) -> tuple[WheelSourceAdmission, ...]:
    """Validate fixture records against the exact native NumPy admission and BSD license.

    Args:
        value: Raw wheel-source record array, including intentionally invalid test payloads.

    Returns:
        Parsed source admissions without performing file or signature verification.

    Raises:
        DependencyAdmissionError: A record fails field, identity or admission-policy checks.
    """
    package = PythonPackageAdmission(
        name="numpy",
        version="2.4.6",
        native_artifacts=True,
        license_expression="BSD-3-Clause",
    )
    return parse_wheel_sources(value, (package,), {"BSD-3-Clause"})


def _fake_cosign(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Write canned version or verification text without authenticating any signature.

    Args:
        command: Simulated argv; an exact ``version`` suffix selects version output.
        **kwargs: Subprocess options containing the writable text stream ``stdout``.

    Returns:
        Status zero for the supplied command after writing to its output stream.
    """
    output = kwargs["stdout"]
    assert isinstance(output, io.TextIOBase)
    output.write("GitVersion:    v3.1.3\n" if command[1:] == ["version"] else "Verified OK\n")
    return subprocess.CompletedProcess(command, 0)


@pytest.fixture()
def wheel_cosign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve Cosign to a placeholder file while individual tests replace subprocess execution.

    Args:
        tmp_path: Directory receiving the placeholder ``cosign`` file.
        monkeypatch: Fixture redirecting executable discovery to that file for the test.

    Raises:
        OSError: The placeholder file cannot be written.
    """
    executable = tmp_path / "cosign"
    executable.write_text("synthetic path; subprocess execution is mocked")

    def find_cosign(_name: str) -> str:
        """Return the synthetic Cosign executable path for the fixture.

        Args:
            _name: Executable name, intentionally ignored by the fixture.

        Returns:
            The temporary executable path.
        """
        return str(executable)

    monkeypatch.setattr(
        "alpha_research_governance.dependency_admission.wheel_sources.shutil.which",
        find_cosign,
    )


class TestWheelSourceVerification:
    """Exercise source archive, wheel provenance and signature verification contracts."""

    def test_wheel_only_source_verification_pins_inputs_and_verifier_options(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        wheel_cosign: None,
    ) -> None:
        """Bind wheel digests to verifier claims, environment and staged inputs."""
        record, locked = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        assert _parse_source_record([_model_payload(record)]) == (record,)
        calls: list[list[str]] = []

        def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Record and check the source-verification invocation before simulating success.

            Args:
                command: Version or verification argv, retained in the call history.
                **kwargs: Subprocess options including timeout, sanitized environment and stdout.

            Returns:
                A canned successful Cosign result; no signature is authenticated.

            Raises:
                AssertionError: Verifier paths, options, identities or staging expectations drift.
                OSError: The staged trust-root fixture cannot be read.
            """
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
                    command[command.index("--certificate-identity") + 1]
                    == record.certificate_identity
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
        self,
        tmp_path: Path,
        field: str,
        value: object,
        message: str,
    ) -> None:
        """Reject malformed or unadmitted source-profile fields before evidence verification."""
        record, _ = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        data = _model_payload(record)
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
        self,
        tmp_path: Path,
        part: str,
        field: str,
        value: object,
        message: str,
    ) -> None:
        """Reject nested mutations that break revision, digest or license identity."""
        record, _ = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        data = _model_payload(record)
        nested = TypeAdapter(list[dict[str, object]]).validate_python(data[part])
        nested[0][field] = value
        data[part] = nested
        with pytest.raises(DependencyAdmissionError, match=message):
            _parse_source_record([data])

    @pytest.mark.parametrize("part", ["records", "sources", "wheels"])
    def test_duplicate_wheel_source_evidence_is_rejected(self, tmp_path: Path, part: str) -> None:
        """Reject repeated admission records, source archives and wheel-evidence identities."""
        record, _ = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        data = _model_payload(record)
        records = [data]
        if part == "records":
            records.append(data)
        else:
            nested = TypeAdapter(list[dict[str, object]]).validate_python(data[part])
            nested.append(dict(nested[0]))
            data[part] = nested
        with pytest.raises(DependencyAdmissionError, match="duplicate"):
            _parse_source_record(records)

    @pytest.mark.parametrize(
        "path", ["../escape.json", "/tmp/escape.json", "./trust.json", "a//b", "a/../b"]
    )
    def test_wheel_source_paths_cannot_escape(self, tmp_path: Path, path: str) -> None:
        """Require canonical relative evidence paths without absolute or traversal components."""
        record, _ = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        data = _model_payload(record)
        trusted_root = _mapping(data["trusted_root"])
        trusted_root["path"] = path
        data["trusted_root"] = trusted_root
        with pytest.raises(DependencyAdmissionError, match="canonical and relative"):
            _parse_source_record([data])

    @pytest.mark.parametrize(
        "case", ["missing", "tampered", "symlink", "directory_symlink", "oversized"]
    )
    def test_wheel_source_files_fail_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
        wheel_cosign: None,
    ) -> None:
        """Reject missing, altered, linked or oversized trust roots."""
        record, locked = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
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
            data = _model_payload(record)
            trusted_root = _mapping(data["trusted_root"])
            trusted_root["path"] = "link/trust.json"
            data["trusted_root"] = trusted_root
            record = _parse_source_record([data])[0]
        else:
            trust.write_bytes(b"x" * 5_000_001)
        monkeypatch.setattr(subprocess, "run", _fake_cosign)
        with pytest.raises(
            DependencyAdmissionError, match=r"missing|digest mismatch|symlinks|size bound"
        ):
            verify_wheel_sources(tmp_path, locked, record)

    @pytest.mark.parametrize("case", ["omitted", "added", "duplicate", "digest", "source", "sdist"])
    def test_wheel_provenance_must_cover_the_complete_lock(self, tmp_path: Path, case: str) -> None:
        """Reject wheel-set, registry drift and source alternatives with an sdist."""
        record, locked = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        wheels = TypeAdapter(list[dict[str, str]]).validate_python(locked["wheels"])
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
        locked["wheels"] = wheels
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
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
        wheel_cosign: None,
    ) -> None:
        """Reject mismatched build claims and malformed payloads before verification."""
        record, locked = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        path = tmp_path / record.wheels[0].bundle.path
        bundle = _json_mapping(path.read_bytes())
        statement, envelope = _bundle_statement(bundle)
        predicate = _mapping(statement["predicate"])
        statement["predicate"] = predicate
        if case == "publish_only":
            statement["predicateType"] = "https://docs.pypi.org/attestations/publish/v1"
        elif case == "subject":
            subject = _mapping(_object_list(statement["subject"])[0])
            digest = _mapping(subject["digest"])
            digest["sha256"] = "f" * 64
            subject["digest"] = digest
            subjects = _object_list(statement["subject"])
            subjects[0] = subject
            statement["subject"] = subjects
        elif case == "builder":
            run_details = _mapping(predicate["runDetails"])
            builder = _mapping(run_details["builder"])
            builder["id"] = "https://example.invalid/attacker"
            run_details["builder"] = builder
            predicate["runDetails"] = run_details
        elif case == "parameters":
            build_definition = _mapping(predicate["buildDefinition"])
            external_parameters = _mapping(build_definition["externalParameters"])
            external_parameters["version"] = "2.4.5"
            build_definition["externalParameters"] = external_parameters
            predicate["buildDefinition"] = build_definition
        elif case == "materials":
            build_definition = _mapping(predicate["buildDefinition"])
            build_definition["resolvedDependencies"] = []
            predicate["buildDefinition"] = build_definition
        elif case == "unknown":
            build_definition = _mapping(predicate["buildDefinition"])
            build_definition["ignored"] = True
            predicate["buildDefinition"] = build_definition
        payload = json.dumps(statement)
        if case == "duplicate_json":
            payload = payload.replace('"subject":', '"subject": [], "subject":')
        envelope["payload"] = (
            "%%%" if case == "encoding" else base64.b64encode(payload.encode()).decode()
        )
        bundle["dsseEnvelope"] = envelope
        evidence = _evidence_file(tmp_path, path.name, json.dumps(bundle).encode())
        data = _model_payload(record)
        wheels = TypeAdapter(list[dict[str, object]]).validate_python(data["wheels"])
        wheels[0]["bundle"] = _model_payload(evidence)
        data["wheels"] = wheels
        record = _parse_source_record([data])[0]
        monkeypatch.setattr(subprocess, "run", _fake_cosign)
        with pytest.raises(DependencyAdmissionError, match=r"mismatch|unsupported|JSON|encoding"):
            verify_wheel_sources(tmp_path, locked, record)

    @pytest.mark.parametrize("case", ["signature", "missing_tool", "timeout", "wrong_version"])
    def test_wheel_sources_require_successful_exact_verifier(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
        wheel_cosign: None,
    ) -> None:
        """Block source admission on signature failure, missing Cosign, timeout or version drift."""
        record, locked = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()

        def failing(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Simulate the selected Cosign failure while preserving normal version negotiation.

            Args:
                command: Version or verification argv whose result is controlled by ``case``.
                **kwargs: Subprocess options; stdout receives normal or deliberately wrong versions.

            Returns:
                Status zero for version output, or status one for a simulated signature failure.

            Raises:
                FileNotFoundError: The selected case simulates an unavailable executable.
                subprocess.TimeoutExpired: The selected case simulates a 60-second timeout.
            """
            if case == "missing_tool":
                raise FileNotFoundError("cosign")
            if case == "timeout":
                raise subprocess.TimeoutExpired(command, 60)
            if case == "wrong_version":
                output = kwargs["stdout"]
                assert isinstance(output, io.TextIOBase)
                output.write("GitVersion:    v3.1.30\n")
                return subprocess.CompletedProcess(command, 0)
            if command[1] == "version":
                return _fake_cosign(command, **kwargs)
            return subprocess.CompletedProcess(command, 1)

        monkeypatch.setattr(subprocess, "run", failing)
        with pytest.raises(DependencyAdmissionError, match="Cosign"):
            verify_wheel_sources(tmp_path, locked, record)


def _inline_toml(value: object) -> str:
    """Render fixture dictionaries, lists and JSON string/number/boolean scalars as inline TOML.

    Args:
        value: Fixture value restricted by callers to these TOML-compatible JSON shapes.

    Returns:
        Inline table, array or scalar text; this helper does not validate arbitrary TOML values.

    Raises:
        TypeError: A scalar or table key cannot be encoded by the JSON serializer.
    """
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{json.dumps(key)} = {_inline_toml(item)}" for key, item in value.items())
            + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_inline_toml(item) for item in value) + "]"
    return json.dumps(value)


class TestAlternativeAdmissionFlows:
    """Exercise legacy policy and exact lock-validator compatibility flows."""

    def test_alternative_flows_through_existing_policy_and_lock_validator(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        wheel_cosign: None,
    ) -> None:
        """Require explicit source admission and intact evidence through the policy/lock path."""
        record, replacement = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        _copy_current_wheel_evidence(tmp_path)
        policy_path = _policy_fixture(tmp_path)
        policy_path.write_text(
            "wheel_source_admissions = "
            + _inline_toml([_model_payload(record)])
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
                    + "\n".join(
                        f"{key} = {_inline_toml(value)}" for key, value in replacement.items()
                    )
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
        assert any(
            "digest mismatch" in finding for finding in _python_lock_findings(tmp_path, policy)
        )


class BootstrapWheelFixtureFactory:
    """Own deterministic publication fixtures for bootstrap-wheel contracts."""

    def __init__(self, root: Path) -> None:
        """Bind the factory to the temporary repository root it materializes.

        Args:
            root: Temporary repository root receiving generated publication evidence.
        """
        self._root = root

    def bootstrap(self) -> tuple[BootstrapWheelAdmission, dict[str, object]]:
        """Rewrite synthetic build evidence as publication-only claims with bounded review records.

        Returns:
            A bootstrap admission valid from 2026-09-04 through 2026-10-04 and its matching
            lock fragment. Claims remain unsigned and review text conveys no real approval.

        Raises:
            OSError: A fixture cannot be read or written.
            DependencyAdmissionError: The generated bootstrap record fails parser validation.
        """
        record, locked = DependencyAdmissionFixtureFactory(self._root).wheel_source()
        data = _model_payload(record)
        for excluded in ("builder_id", "build_type", "build_parameters_sha256"):
            data.pop(excluded, None)
        wheels = TypeAdapter(list[dict[str, object]]).validate_python(data["wheels"])
        for wheel in wheels:
            bundle_record = _mapping(wheel["bundle"])
            path_value = bundle_record["path"]
            assert isinstance(path_value, str)
            path = self._root / path_value
            bundle = _json_mapping(path.read_bytes())
            statement, envelope = _bundle_statement(bundle)
            statement["predicateType"] = "https://docs.pypi.org/attestations/publish/v1"
            statement["predicate"] = None
            envelope["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
            bundle["dsseEnvelope"] = envelope
            wheel["bundle"] = _model_payload(
                _evidence_file(self._root, path.name, json.dumps(bundle).encode())
            )
        data["wheels"] = wheels
        data.update(
            usage="isolated_development_and_ci",
            source_to_wheel_binding="unverified",
            finding_id="B07-DEP-001",
            reviewed_on="2026-09-04",
            expires_on="2026-10-04",
            residual_risk="The publisher's wheel may differ from the inspected upstream sources.",
            closure_condition=(
                "Supply signed source-to-wheel build evidence or remove the dependency."
            ),
        )
        for kind in (
            "source_review",
            "security_review",
            "native_inventory",
            "compatibility_report",
        ):
            data[kind] = _model_payload(
                _evidence_file(
                    self._root, kind + ".txt", b"Synthetic review evidence; no real approval.\n"
                )
            )
        return _parse_bootstrap_record([data])[0], locked


def _parse_bootstrap_record(value: object) -> tuple[BootstrapWheelAdmission, ...]:
    """Validate bootstrap records against fixed NumPy, license and policy-date fixtures.

    Args:
        value: Raw bootstrap record array, including deliberately malformed test payloads.

    Returns:
        Records admitted with assessment date 2026-09-03 and review deadline 2026-12-02;
        no evidence files or signatures are checked here.

    Raises:
        DependencyAdmissionError: Field, identity, ownership or date-window validation fails.
    """
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


class TestBootstrapWheelAdmission:
    """Exercise bootstrap publication evidence and release-boundary contracts."""

    @pytest.mark.parametrize("when", [date(2026, 9, 4), date(2026, 10, 4)])
    @pytest.mark.parametrize("empty_object", [False, True])
    def test_bootstrap_publication_verification_is_explicit_and_date_bounded(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        wheel_cosign: None,
        when: date,
        empty_object: bool,
    ) -> None:
        """Accept publication predicate forms at inclusive review boundaries."""
        record, locked = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        if empty_object:
            data = _model_payload(record)
            wheels = TypeAdapter(list[dict[str, object]]).validate_python(data["wheels"])
            for wheel in wheels:
                bundle_record = _mapping(wheel["bundle"])
                path_value = bundle_record["path"]
                assert isinstance(path_value, str)
                path = tmp_path / path_value
                bundle = _json_mapping(path.read_bytes())
                statement, envelope = _bundle_statement(bundle)
                statement["predicate"] = {}
                envelope["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
                bundle["dsseEnvelope"] = envelope
                wheel["bundle"] = _model_payload(
                    _evidence_file(tmp_path, path.name, json.dumps(bundle).encode())
                )
            data["wheels"] = wheels
            record = _parse_bootstrap_record([data])[0]
        calls: list[list[str]] = []

        def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Record publication-verifier claims and return simulated authentication success.

            Args:
                command: Version or publication-verification argv to retain and inspect.
                **kwargs: Subprocess options forwarded to the fake, including writable stdout.

            Returns:
                A canned successful Cosign result without authenticating the synthetic bundle.

            Raises:
                AssertionError: Predicate type, digest, signer, issuer or claim-check options drift.
            """
            calls.append(command)
            if command[1] != "version":
                assert (
                    command[command.index("--type") + 1]
                    == "https://docs.pypi.org/attestations/publish/v1"
                )
                assert "--check-claims=true" in command
                assert (
                    command[command.index("--certificate-identity") + 1]
                    == record.certificate_identity
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
        self,
        tmp_path: Path,
        field: str,
        value: object,
    ) -> None:
        """Reject bootstrap scope, identity, attribution and review-window mutations."""
        record, _ = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        data = _model_payload(record)
        data[field] = value
        with pytest.raises(DependencyAdmissionError):
            _parse_bootstrap_record([data])

    @pytest.mark.parametrize(
        "case", ["missing", "empty", "tampered", "symlink", "expired", "future"]
    )
    def test_bootstrap_review_failures_stop_before_verifier_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
    ) -> None:
        """Reject invalid review files or dates before any verifier subprocess can be invoked."""
        record, locked = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        path = tmp_path / record.security_review.path
        when = date(2026, 9, 4)
        if case == "missing":
            path.unlink()
        elif case == "empty":
            data = _model_payload(record)
            data["security_review"] = _model_payload(_evidence_file(tmp_path, path.name, b" \n"))
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
            """Fail the test if invalid review evidence reaches the verifier subprocess boundary.

            Args:
                *args: Positional subprocess inputs; ignored because every invocation is forbidden.
                **kwargs: Keyword subprocess options; ignored because every invocation is forbidden.

            Raises:
                pytest.fail.Exception: Always, identifying an unexpected verifier invocation.
            """
            pytest.fail("review failure must precede verifier execution")

        monkeypatch.setattr(subprocess, "run", unexpected)
        with pytest.raises(
            DependencyAdmissionError, match=r"missing|empty|digest|symlinks|expired"
        ):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=when)

    @pytest.mark.parametrize(
        "case", ["body", "type", "subject", "tampered", "signature", "sdist", "missing_wheel"]
    )
    def test_bootstrap_does_not_bypass_publication_signature_or_lock_checks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        wheel_cosign: None,
        case: str,
    ) -> None:
        """Keep publication claims, evidence integrity and complete-lock checks."""
        record, locked = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        path = tmp_path / record.wheels[0].bundle.path
        if case in {"body", "type", "subject"}:
            bundle = _json_mapping(path.read_bytes())
            statement, envelope = _bundle_statement(bundle)
            if case == "body":
                statement["predicate"] = {"verified": True}
            elif case == "type":
                statement["predicateType"] = "https://slsa.dev/provenance/v1"
            else:
                subject = _mapping(_object_list(statement["subject"])[0])
                digest = _mapping(subject["digest"])
                digest["sha256"] = "f" * 64
                subject["digest"] = digest
                subjects = _object_list(statement["subject"])
                subjects[0] = subject
                statement["subject"] = subjects
            envelope["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
            bundle["dsseEnvelope"] = envelope
            data = _model_payload(record)
            wheels = TypeAdapter(list[dict[str, object]]).validate_python(data["wheels"])
            wheels[0]["bundle"] = _model_payload(
                _evidence_file(tmp_path, path.name, json.dumps(bundle).encode())
            )
            data["wheels"] = wheels
            record = _parse_bootstrap_record([data])[0]
        elif case == "tampered":
            path.write_bytes(b"changed")
        elif case == "sdist":
            locked["sdist"] = {"hash": "malformed"}
        elif case == "missing_wheel":
            locked_wheels = _object_list(locked["wheels"])
            locked_wheels.pop()
            locked["wheels"] = locked_wheels

        def verify(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Return fake Cosign success except for the selected publication-signature failure.

            Args:
                command: Version or verification argv; version calls remain successful.
                **kwargs: Subprocess options forwarded to the fake when it writes normal output.

            Returns:
                Status one for the signature case's verification call, otherwise a canned success.
            """
            if case == "signature" and command[1] != "version":
                return subprocess.CompletedProcess(command, 1)
            return _fake_cosign(command, **kwargs)

        monkeypatch.setattr(subprocess, "run", verify)
        with pytest.raises(DependencyAdmissionError):
            verify_bootstrap_wheels(tmp_path, locked, record, validation_date=date(2026, 9, 4))

    def test_bootstrap_policy_lock_integration_and_removal_cannot_enable_release(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        wheel_cosign: None,
    ) -> None:
        """Enforce bootstrap expiry and block release both with and after deleting the exception."""
        record, locked = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        record_update: dict[str, object] = {"finding_id": "B07-DEP-002"}
        record = record.model_copy(update=record_update)
        policy_path = tmp_path / "docs/architecture/dependency-admission.toml"
        policy_path.parent.mkdir(parents=True)
        original = POLICY_PATH.read_text()
        _copy_current_wheel_evidence(tmp_path)
        policy_path.write_text(
            original
            + "\n[[bootstrap_wheel_admissions]]\n"
            + "\n".join(
                key + " = " + _inline_toml(value) for key, value in _model_payload(record).items()
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
        with pytest.raises(
            DependencyAdmissionError, match="lacks a digest-bound source distribution"
        ):
            require_release_admission(tmp_path)

    def test_bootstrap_and_build_profiles_cannot_overlap(self, tmp_path: Path) -> None:
        """Reject assigning both bootstrap and build-provenance profiles to one package."""
        bootstrap, _ = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        build, _ = DependencyAdmissionFixtureFactory(tmp_path).wheel_source()
        policy_path = _policy_fixture(tmp_path)
        policy_path.write_text(
            "wheel_source_admissions = "
            + _inline_toml([_model_payload(build)])
            + "\n"
            + _without_bootstrap(policy_path.read_text()).replace(
                "bootstrap_wheel_admissions = []",
                "bootstrap_wheel_admissions = " + _inline_toml([_model_payload(bootstrap)]),
            )
        )
        with pytest.raises(DependencyAdmissionError, match="both wheel admission profiles"):
            load_policy(policy_path)

    def test_bootstrap_report_paths_and_duplicate_records_are_rejected(
        self, tmp_path: Path
    ) -> None:
        """Reject repeated bootstrap records and review-report paths that escape the repository."""
        record, _ = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        data = _model_payload(record)
        with pytest.raises(DependencyAdmissionError, match="duplicate"):
            _parse_bootstrap_record([data, data])
        source_review = _mapping(data["source_review"])
        source_review["path"] = "../outside.txt"
        data["source_review"] = source_review
        with pytest.raises(DependencyAdmissionError, match="canonical and relative"):
            _parse_bootstrap_record([data])

    def test_cli_reports_bootstrap_limit_and_legacy_policy_remains_supported(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Load legacy profiles and disclose bootstrap scope and release denial."""
        record, _ = BootstrapWheelFixtureFactory(tmp_path).bootstrap()
        policy_path = _policy_fixture(tmp_path)
        legacy = _without_bootstrap(policy_path.read_text()).replace(
            "bootstrap_wheel_admissions = []\n", ""
        )
        policy_path.write_text(legacy)
        assert load_policy(policy_path).bootstrap_wheel_admissions == ()
        policy_path.write_text(
            "bootstrap_wheel_admissions = " + _inline_toml([_model_payload(record)]) + "\n" + legacy
        )
        policy = load_policy(policy_path)

        def current_policy(_root: Path) -> DependencyAdmission:
            """Return the synthetic policy through the CLI validation seam.

            Args:
                _root: Temporary repository root, intentionally ignored by the fake.

            Returns:
                The synthetic policy loaded for this test.
            """
            return policy

        monkeypatch.setattr(
            "alpha_research_governance.dependency_admission.validate_repository",
            current_policy,
        )
        assert main([]) == 0
        output = capsys.readouterr().out
        assert "BOOTSTRAP ONLY: numpy==2.4.6" in output
        assert "unverified; B07-DEP-001" in output
        assert "owner=platform; expires=2026-10-04; artifact release blocked" in output

    def test_release_admission_evaluates_the_current_graph_without_bootstrap_bypass(self) -> None:
        """Apply release admission to the current graph while bootstrap is used."""
        policy = load_policy(POLICY_PATH)
        if policy.bootstrap_wheel_admissions:
            with pytest.raises(DependencyAdmissionError, match="bootstrap-only"):
                require_release_admission(REPOSITORY_ROOT)
        else:
            require_release_admission(REPOSITORY_ROOT)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
