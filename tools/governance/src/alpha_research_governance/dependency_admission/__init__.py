"""Command and public functions for the frozen dependency boundary."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.dependency_admission.models import DependencyAdmissionError
from alpha_research_governance.dependency_admission.policy import (
    DependencyPolicy,
    DependencyRepository,
    PipAuditReport,
)

__all__ = [
    "DependencyAdmissionError",
    "DependencyPolicy",
    "DependencyRepository",
    "PipAuditReport",
    "main",
]


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
            policy = DependencyRepository.validate(root)
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
            PipAuditReport.run(root, DependencyRepository.validate(root))
            print("pip-audit found no unresolved vulnerabilities or coverage gaps.")
            return 0
    except (DependencyAdmissionError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print("usage: alpha-governance-dependencies [audit]", file=sys.stderr)
    return 2
