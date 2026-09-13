"""Command and public functions for the frozen dependency boundary."""

from __future__ import annotations

# standard library imports
import importlib.metadata
import subprocess  # nosec B404  # [owner=platform; rationale=exact pip-audit argv execution; expires=2027-03-01]
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.dependency_admission.models import (
    DependencyAdmission,
    DependencyAdmissionError,
)
from alpha_research_governance.dependency_admission.policy import (
    assess_pip_audit_report,
    load_policy,
    require_release_admission,
    validate_repository,
)

__all__ = [
    "DependencyAdmissionError",
    "assess_pip_audit_report",
    "load_policy",
    "main",
    "require_release_admission",
    "validate_repository",
]


def _run_pip_audit(repository_root: Path, policy: DependencyAdmission) -> None:
    """Run the pinned scanner and assess its complete temporary JSON report."""
    try:
        version = importlib.metadata.version("pip-audit")
    except importlib.metadata.PackageNotFoundError as error:
        raise DependencyAdmissionError(["admitted pip-audit is not installed"]) from error
    if version != "2.10.1":
        raise DependencyAdmissionError(
            [f"pip-audit version {version!r} is not admitted; expected 2.10.1"]
        )
    with tempfile.TemporaryDirectory(prefix="dependency-admission-pip-audit-") as temporary:
        directory = Path(temporary)
        report = directory / "report.json"
        requirements = directory / "requirements.txt"
        requirements.write_text(
            "\n".join(f"{item.name}=={item.version}" for item in policy.packages) + "\n",
            encoding="utf-8",
        )
        command = [
            "pip-audit",
            "--requirement",
            str(requirements),
            "--no-deps",
            "--disable-pip",
            "--strict",
            "--vulnerability-service",
            "pypi",
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
            str(report),
        ]
        try:
            completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=constant scanner argv and temp output; expires=2027-03-01]
                command, cwd=repository_root, check=False, capture_output=True, text=True
            )
        except OSError as error:
            raise DependencyAdmissionError([f"pip-audit could not start: {error}"]) from error
        if not report.is_file():
            detail = (completed.stdout + completed.stderr).strip()
            raise DependencyAdmissionError([f"pip-audit produced no JSON report: {detail}"])
        try:
            assess_pip_audit_report(report, policy)
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
    """Validate dependency admission or assess a complete pip-audit report.

    Args:
        arguments: Optional command-line tokens. Provide no command or ``audit``;
            ``None`` consumes ``sys.argv[1:]``.

    Returns:
        ``0`` after successful validation or report assessment, ``1`` after a
        caught admission/filesystem/value failure, or ``2`` for invalid usage.
    """
    tokens = list(sys.argv[1:] if arguments is None else arguments)
    root = Path.cwd()
    try:
        if not tokens:
            policy = validate_repository(root)
            print(f"Dependency admission passed for {len(policy.packages)} locked Python packages.")
            for record in policy.wheel_only_allowances:
                print(
                    f"DEVELOPMENT ONLY: {record.name}=={record.version}; source-to-wheel binding "
                    f"unverified; expires={record.expires_on}; "
                    f"usage={record.usage}; artifact release blocked."
                )
            return 0
        command = tokens[0]
        if command == "audit" and len(tokens) == 1:
            _run_pip_audit(root, validate_repository(root))
            print("pip-audit found no unresolved vulnerabilities or coverage gaps.")
            return 0
    except (DependencyAdmissionError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print("usage: alpha-governance-dependencies [audit]", file=sys.stderr)
    return 2
