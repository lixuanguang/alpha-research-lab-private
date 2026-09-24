"""Retain fresh complete vulnerability evidence from the admitted scanner before signing."""

from __future__ import annotations

# standard library imports
import importlib.metadata
import subprocess  # nosec B404  # [owner=platform; rationale=admitted vulnerability scanner invocation; expires=2027-03-01]
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# project library imports
from alpha_research_governance.dependency_admission import assess_pip_audit_report
from alpha_research_governance.dependency_admission.models import DependencyAdmission


class ReleaseAudit:
    """Run the exact admitted scanner against every package in the full root policy."""

    @staticmethod
    def run(policy: DependencyAdmission, output: Path) -> bytes:
        """Create fresh audit JSON at an absent path, preserving failures for diagnosis.

        The full unfiltered graph is supplied as exact name/version requirements.
        Existing reports cannot be passed off as a fresh scan or overwritten.
        """
        if output.exists() or output.is_symlink():
            raise ValueError("audit output already exists; use a new attempt path")
        if importlib.metadata.version("pip-audit") != "2.10.1":
            raise ValueError("release audit requires admitted pip-audit 2.10.1")
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="ar-release-audit-") as temporary:
            root = Path(temporary)
            requirements = root / "requirements.txt"
            requirements.write_text(
                "\n".join(f"{item.name}=={item.version}" for item in policy.packages) + "\n",
                encoding="utf-8",
            )
            arguments = [
                sys.executable,
                "-I",
                "-m",
                "pip_audit",
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
                str(output),
            ]
            try:
                result = subprocess.run(  # nosec B603  # [owner=platform; rationale=fixed admitted scanner argv and explicit evidence output; expires=2027-03-01]
                    arguments,
                    cwd=root,
                    check=False,
                    capture_output=True,
                    timeout=180,
                    env={"PATH": "/usr/bin:/bin", "HOME": str(root), "LC_ALL": "C"},
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError("release vulnerability audit timed out") from error
            output.with_suffix(".scanner.log").write_bytes(result.stdout + result.stderr)
            if result.returncode != 0 or not output.is_file():
                raise ValueError("release vulnerability audit failed; see retained scanner log")
            assess_pip_audit_report(output, policy)
            return output.read_bytes()
