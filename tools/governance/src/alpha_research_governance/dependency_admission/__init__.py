"""Canonical dependency-admission API and command for roadmap package B07."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess  # nosec B404  # [owner=platform; rationale=exact pip-audit argv execution; expires=2027-03-01]
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
    EmergencyOverride,
    PythonPackageAdmission,
    VulnerabilityDecision,
)
from alpha_research_governance.dependency_admission.policy import (
    assess_pip_audit_report,
    assess_scorecard_report,
    load_policy,
    validate_repository,
)

__all__ = [
    "DependencyAdmission",
    "DependencyAdmissionError",
    "EmergencyOverride",
    "PythonPackageAdmission",
    "VulnerabilityDecision",
    "assess_pip_audit_report",
    "assess_scorecard_report",
    "load_policy",
    "main",
    "run_pip_audit",
    "validate_repository",
]


def run_pip_audit(repository_root: Path, policy: DependencyAdmission) -> None:
    """Run the exact admitted scanner and apply repository-owned disposition policy."""
    try:
        observed_version = importlib.metadata.version("pip-audit")
    except importlib.metadata.PackageNotFoundError as error:
        raise DependencyAdmissionError(["admitted pip-audit is not installed"]) from error
    if observed_version != policy.pip_audit_version:
        raise DependencyAdmissionError(
            [
                f"pip-audit version {observed_version!r} is not admitted; "
                f"expected {policy.pip_audit_version}"
            ]
        )
    with tempfile.TemporaryDirectory(prefix="dependency-admission-pip-audit-") as temporary:
        temporary_root = Path(temporary)
        report_path = temporary_root / "report.json"
        requirements_path = temporary_root / "requirements.txt"
        requirements_path.write_text(
            "\n".join(f"{package.name}=={package.version}" for package in policy.packages) + "\n",
            encoding="utf-8",
        )
        command = [
            "pip-audit",
            "--requirement",
            str(requirements_path),
            "--no-deps",
            "--disable-pip",
            "--strict",
            "--vulnerability-service",
            policy.vulnerability_service,
            "--timeout",
            "15",
            "--format",
            "json",
            "--progress-spinner",
            "off",
            "--desc",
            "off",
            "--aliases",
            "on",
            "--output",
            str(report_path),
        ]
        try:
            completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=constant scanner argv and temp output; expires=2027-03-01]
                command,
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            raise DependencyAdmissionError([f"pip-audit could not start: {error}"]) from error
        if not report_path.is_file():
            detail = (completed.stdout + completed.stderr).strip()
            raise DependencyAdmissionError([f"pip-audit produced no JSON report: {detail}"])
        try:
            assess_pip_audit_report(report_path, policy)
        except DependencyAdmissionError as error:
            detail = (completed.stdout + completed.stderr).strip()
            suffix = f"\nscanner output: {detail}" if detail else ""
            raise DependencyAdmissionError([f"{error}{suffix}"]) from error
        if completed.returncode not in {0, 1}:
            detail = (completed.stdout + completed.stderr).strip()
            raise DependencyAdmissionError(
                [f"pip-audit failed with exit {completed.returncode}: {detail}"]
            )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run offline admission validation, live audit, or signal assessment."""
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    repository_root = Path.cwd()
    try:
        if not cli_arguments:
            policy = validate_repository(repository_root)
            print(
                f"Dependency admission passed for {len(policy.packages)} locked Python packages; "
                f"package status is {policy.package_status}."
            )
            for record in policy.bootstrap_wheel_admissions:
                print(
                    f"BOOTSTRAP ONLY: {record.name}=={record.version}; "
                    f"source-to-wheel binding unverified; {record.finding_id}; "
                    f"owner={record.owner_role}; expires={record.expires_on}; "
                    "artifact release blocked."
                )
            return 0
        command = cli_arguments.pop(0)
        if command == "audit" and not cli_arguments:
            policy = validate_repository(repository_root)
            run_pip_audit(repository_root, policy)
            print("pip-audit found no unresolved vulnerabilities or coverage gaps.")
            return 0
        if command == "audit-report" and len(cli_arguments) == 1:
            policy = validate_repository(repository_root)
            assess_pip_audit_report(Path(cli_arguments[0]), policy)
            print("pip-audit report passed dependency admission.")
            return 0
        if command == "scorecard-report" and len(cli_arguments) == 3:
            policy = validate_repository(repository_root)
            assess_scorecard_report(
                Path(cli_arguments[0]),
                expected_repository=cli_arguments[1],
                expected_commit=cli_arguments[2],
                policy=policy,
            )
            print(json.dumps({"signal": "accepted", "authority": "advisory_only"}, sort_keys=True))
            return 0
    except (DependencyAdmissionError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        "usage: alpha-governance-dependencies "
        "[audit | audit-report REPORT | scorecard-report REPORT REPOSITORY COMMIT]",
        file=sys.stderr,
    )
    return 2
