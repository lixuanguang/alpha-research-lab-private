"""Focused tests for frozen dependencies and the wheel-only development exception."""

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
    DependencyPolicy,
    DependencyRepository,
    PipAuditReport,
)
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
)
from alpha_research_governance.dependency_admission.source_archives import SourceArchiveVerifier

REPOSITORY_ROOT = Path(__file__).parents[2]

POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/dependency-admission.toml"

# No admitted package needs a wheel-only allowance, so these tests exercise the
# exception on a copy of the lock where one native package lost its sdist.
_WHEEL_ONLY = 'name = "msgspec"\nversion = "0.21.1"\n'
_ALLOWANCE = (
    "\n[[wheel_only_allowances]]\n"
    'name = "msgspec"\n'
    'version = "0.21.1"\n'
    'rationale = "Synthetic native package without a source distribution."\n'
    'usage = "isolated_development_and_ci"\n'
    'source_to_wheel_binding = "unverified"\n'
    'reviewed_on = "2026-10-01"\n'
    'expires_on = "2026-10-31"\n'
)


class AdmissionFixtures:
    """Build dependency-admission fixture repositories and pip-audit reports."""

    @staticmethod
    def wheel_only_repository(tmp_path: Path, *, allowance: str = _ALLOWANCE) -> Path:
        """Write a policy with one wheel-only allowance and a lock whose package has no sdist."""
        source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
        prefix, marker, tail = source.partition(_WHEEL_ONLY)
        assert marker
        package, separator, suffix = tail.partition("\n[[package]]")
        package = "\n".join(line for line in package.split("\n") if not line.startswith("sdist = "))
        (tmp_path / "uv.lock").write_text(prefix + marker + package + separator + suffix)
        policy = POLICY_PATH.read_text(encoding="utf-8").replace(
            "wheel_only_allowances = []\n", "", 1
        )
        (tmp_path / "policy.toml").write_text(policy.rstrip("\n") + "\n" + allowance)
        return tmp_path / "policy.toml"

    @staticmethod
    def write_audit_report(tmp_path: Path, report: object) -> Path:
        """Write one synthetic scanner result for a fail-closed boundary test."""
        path = tmp_path / "audit.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    @staticmethod
    def clean_audit_dependencies(policy: DependencyAdmission) -> list[dict[str, object]]:
        """Build exact dependency identities without coupling tests to model internals."""
        return [
            {"name": package.name, "version": package.version, "vulns": []}
            for package in policy.packages
        ]


class TestDependencyAdmission:
    """Validate the frozen dependency policy, lock graph and wheel-only exception."""

    def test_policy_translates_malformed_toml(self, tmp_path: Path) -> None:
        """Translate parser errors while preserving the original TOML exception cause."""
        path = tmp_path / "dependency-admission.toml"
        path.write_text("schema_version = [", encoding="utf-8")
        with pytest.raises(DependencyAdmissionError, match="invalid TOML") as raised:
            DependencyPolicy.load(path)
        assert type(raised.value.__cause__).__name__ == "TOMLDecodeError"

    def test_policy_preserves_unicode_read_errors(self, tmp_path: Path) -> None:
        """Keep invalid UTF-8 distinct from a syntactically invalid TOML document."""
        path = tmp_path / "dependency-admission.toml"
        path.write_bytes(b"\xff")
        with pytest.raises(UnicodeDecodeError):
            DependencyPolicy.load(path)

    def test_policy_contains_only_retained_dependency_facts(self) -> None:
        """Load the compact policy, which admits every package with its source."""
        policy = DependencyPolicy.load(POLICY_PATH)

        assert policy.schema_version == 5
        assert policy.wheel_only_allowances == ()

    def test_repository_validation_checks_lock_and_development_limits(self) -> None:
        """Accept the frozen bytes before the policy review date without archived reports."""
        with patch.object(SourceArchiveVerifier, "verify", return_value=283) as verify:
            policy = DependencyRepository.validate(
                REPOSITORY_ROOT, validation_date=date(2026, 10, 20)
            )
        verify.assert_called_once_with(policy.source_archives[0])
        assert len(policy.packages) == 188
        assert any(
            package.name == "websockets" and package.version == "16.0"
            for package in policy.packages
        )

    def test_release_admission_is_blocked_while_any_wheel_only_allowance_is_active(
        self,
        tmp_path: Path,
    ) -> None:
        """An unverified source-to-wheel binding blocks release before anything else runs."""
        docs = tmp_path / "repository/docs/architecture"
        docs.mkdir(parents=True)
        AdmissionFixtures.wheel_only_repository(tmp_path / "repository").rename(
            docs / "dependency-admission.toml"
        )
        with pytest.raises(DependencyAdmissionError, match="release blocked"):
            DependencyRepository.require_release(tmp_path / "repository")

    @pytest.mark.parametrize("validation_date", (date(2026, 9, 30), date(2026, 11, 1)))
    def test_wheel_only_allowance_rejects_dates_outside_its_window(
        self, tmp_path: Path, validation_date: date
    ) -> None:
        """Reject development and CI use outside the recorded allowance window."""
        policy = DependencyPolicy.load(AdmissionFixtures.wheel_only_repository(tmp_path))
        findings = DependencyRepository.lock_findings(
            tmp_path, policy, validation_date=validation_date
        )
        assert "msgspec: wheel-only allowance is expired or not yet effective" in findings

    def test_lock_source_url_is_checked_even_when_lock_digest_is_supplied(
        self, tmp_path: Path
    ) -> None:
        """Reject an alternate artifact origin independently of the lockfile digest."""
        lock_path = tmp_path / "uv.lock"
        source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
        lock_path.write_text(
            source.replace("https://files.pythonhosted.org", "https://evil.invalid", 1),
            encoding="utf-8",
        )
        findings = DependencyRepository.lock_findings(tmp_path, DependencyPolicy.load(POLICY_PATH))
        assert any("unapproved source" in finding for finding in findings)

    def test_lock_hash_is_checked_for_every_artifact(self, tmp_path: Path) -> None:
        """Reject an artifact record without a SHA-256 lock hash."""
        source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
        lock_path = tmp_path / "uv.lock"
        lock_path.write_text(
            source.replace('hash = "sha256:', 'hash = "sha256:not-a-digest', 1), encoding="utf-8"
        )
        findings = DependencyRepository.lock_findings(tmp_path, DependencyPolicy.load(POLICY_PATH))
        assert any("digest-bound source distribution" in finding for finding in findings)

    @pytest.mark.parametrize("python_boundary", ["==3.12.*", "==3.13.*", ">=3.14", "==3.15.*"])
    def test_lock_rejects_unsupported_python_boundary(
        self, tmp_path: Path, python_boundary: str
    ) -> None:
        """Reject a lock that permits an unsupported Python minor version."""
        source = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
        lock_path = tmp_path / "uv.lock"
        assert 'requires-python = "==3.14.*"' in source
        lock_path.write_text(
            source.replace(
                'requires-python = "==3.14.*"', f'requires-python = "{python_boundary}"'
            ),
            encoding="utf-8",
        )
        with pytest.raises(DependencyAdmissionError, match="Python boundary drifted"):
            DependencyRepository.locked_packages(lock_path)

    def test_lock_accepts_supported_python_boundary(self) -> None:
        """Load the supported lock with the pinned Python boundary."""
        packages = DependencyRepository.locked_packages(REPOSITORY_ROOT / "uv.lock")
        assert packages["alpha-research-lab"]["version"] == "0.1.0"

    def test_lock_schema_rejects_duplicate_package_names(self, tmp_path: Path) -> None:
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
            DependencyRepository.locked_packages(duplicate)

    def test_runtime_installation_scan_rejects_owned_source(self, tmp_path: Path) -> None:
        """Preserve the no-runtime-installation boundary for source roots."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src/runtime.py").write_text(
            "import subprocess\nsubprocess.run(['pip', 'install', 'x'])\n", encoding="utf-8"
        )
        findings = DependencyRepository.runtime_install_findings(tmp_path)
        assert findings == ["runtime package installation is prohibited: src/runtime.py"]

    @pytest.mark.parametrize(
        ("old", "new", "message"),
        [
            ('version = "0.21.1"', 'version = "0"', "exact native package"),
            ('name = "msgspec"', 'name = "unknown"', "exact native package"),
            ('usage = "isolated_development_and_ci"', 'usage = "release"', "allowance fields"),
            (
                'source_to_wheel_binding = "unverified"',
                'source_to_wheel_binding = "verified"',
                "allowance fields",
            ),
            ('reviewed_on = "2026-10-01"', 'reviewed_on = "2026-09-30"', "expire within 30 days"),
            ('expires_on = "2026-10-31"', 'expires_on = "2026-11-01"', "expire within 30 days"),
        ],
    )
    def test_wheel_only_allowance_preserves_identity_scope_and_window(
        self, tmp_path: Path, old: str, new: str, message: str
    ) -> None:
        """Reject mismatched identities, release use, verified claims and expanded dates."""
        assert old in _ALLOWANCE
        path = AdmissionFixtures.wheel_only_repository(
            tmp_path, allowance=_ALLOWANCE.replace(old, new, 1)
        )
        with pytest.raises(DependencyAdmissionError, match=message):
            DependencyPolicy.load(path)

    def test_duplicate_wheel_only_allowances_are_rejected(self, tmp_path: Path) -> None:
        """Reject conflicting grants for the same native dependency."""
        path = AdmissionFixtures.wheel_only_repository(tmp_path, allowance=_ALLOWANCE + _ALLOWANCE)
        with pytest.raises(DependencyAdmissionError, match="duplicate wheel-only allowance"):
            DependencyPolicy.load(path)

    def test_removing_allowance_does_not_admit_a_package_without_source(
        self, tmp_path: Path
    ) -> None:
        """Require a source distribution when the explicit wheel-only allowance is absent."""
        AdmissionFixtures.wheel_only_repository(tmp_path)
        findings = DependencyRepository.lock_findings(
            tmp_path, DependencyPolicy.load(POLICY_PATH), validation_date=date(2026, 10, 1)
        )
        assert "msgspec lacks a digest-bound source distribution" in findings

    @pytest.mark.parametrize(
        ("old", "new", "message"),
        [
            ("https://files.pythonhosted.org", "https://evil.invalid", "unapproved source"),
            ("sha256:", "sha256:invalid", "wheel without a SHA-256 digest"),
        ],
    )
    def test_wheel_only_allowance_keeps_artifact_source_and_hash_checks(
        self, tmp_path: Path, old: str, new: str, message: str
    ) -> None:
        """Reject a malformed wheel even while development use is allowed."""
        policy = DependencyPolicy.load(AdmissionFixtures.wheel_only_repository(tmp_path))
        source = (tmp_path / "uv.lock").read_text()
        prefix, marker, tail = source.partition(_WHEEL_ONLY)
        package, separator, suffix = tail.partition("\n[[package]]")
        assert old in package
        (tmp_path / "uv.lock").write_text(
            prefix + marker + package.replace(old, new, 1) + separator + suffix
        )
        findings = DependencyRepository.lock_findings(
            tmp_path, policy, validation_date=date(2026, 10, 1)
        )
        assert any("msgspec" in finding and message in finding for finding in findings)

    @pytest.mark.parametrize(
        ("replacement", "message"),
        [
            ("schema_version = 2", "schema_version must be 5"),
            ("vulnerability_decisions = []", "root has missing or unknown fields"),
        ],
    )
    def test_policy_rejects_unsupported_schema_and_unknown_keys(
        self, tmp_path: Path, replacement: str, message: str
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
            DependencyPolicy.load(path)


class TestPipAuditReport:
    """Require complete pip-audit coverage with no waiver path."""

    def test_clean_pip_audit_report_covers_the_admitted_graph(self, tmp_path: Path) -> None:
        """Accept a scanner report containing every exact admitted package."""
        policy = DependencyPolicy.load(POLICY_PATH)
        report = {
            "dependencies": [
                {"name": package.name, "version": package.version, "vulns": []}
                for package in policy.packages
            ],
            "fixes": [],
        }
        path = tmp_path / "audit.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        PipAuditReport.assess(path, policy)

    def test_pip_audit_skips_are_blocked(self, tmp_path: Path) -> None:
        """Keep scanner coverage fail-closed for skipped dependencies."""
        policy = DependencyPolicy.load(POLICY_PATH)
        report = {
            "dependencies": [{"name": policy.packages[0].name, "skip_reason": "offline"}],
            "fixes": [],
        }
        path = tmp_path / "audit.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        with pytest.raises(DependencyAdmissionError, match="skipped"):
            PipAuditReport.assess(path, policy)

    def test_pip_audit_findings_have_no_waiver_path(self, tmp_path: Path) -> None:
        """Block a vulnerability even when its record resembles an old waiver input."""
        policy = DependencyPolicy.load(POLICY_PATH)
        dependencies = AdmissionFixtures.clean_audit_dependencies(policy)
        dependencies[0]["vulns"] = [{"id": "CVE-2099-0001"}]
        with pytest.raises(DependencyAdmissionError, match="unresolved vulnerability"):
            PipAuditReport.assess(
                AdmissionFixtures.write_audit_report(
                    tmp_path, {"dependencies": dependencies, "fixes": []}
                ),
                policy,
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
        self, tmp_path: Path, mutation: str, message: str
    ) -> None:
        """Reject duplicate, wrong-version, and unexpected scanner identities."""
        policy = DependencyPolicy.load(POLICY_PATH)
        dependencies = AdmissionFixtures.clean_audit_dependencies(policy)
        if mutation == "duplicate":
            dependencies.append(dependencies[0].copy())
        elif mutation == "wrong-version":
            dependencies[0]["version"] = "0"
        else:
            dependencies[0] = {"name": "unexpected-package", "version": "1", "vulns": []}
        with pytest.raises(DependencyAdmissionError, match=message):
            PipAuditReport.assess(
                AdmissionFixtures.write_audit_report(
                    tmp_path, {"dependencies": dependencies, "fixes": []}
                ),
                policy,
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
    def test_pip_audit_malformed_or_unknown_shape_is_rejected(
        self, tmp_path: Path, report: object
    ) -> None:
        """Reject malformed reports and unrecognized top-level fields."""
        policy = DependencyPolicy.load(POLICY_PATH)
        with pytest.raises(
            DependencyAdmissionError,
            match=r"root fields|dependencies must be an array|coverage differs",
        ):
            PipAuditReport.assess(AdmissionFixtures.write_audit_report(tmp_path, report), policy)
