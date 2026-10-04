"""Compact Python clarity checker and command."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.engineering_standards.checker import (
    EngineeringStandards,
    EngineeringStandardsError,
)
from alpha_research_governance.engineering_standards.import_audit import ImportAudit, ImportFinding

__all__ = [
    "EngineeringStandards",
    "EngineeringStandardsError",
    "ImportAudit",
    "ImportFinding",
    "main",
]


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the compact Python clarity checker, or the external import audit.

    Args:
        arguments: Optional command-line arguments. Omit this value to consume
            ``sys.argv[1:]``. Provide at most one repository-root argument, or
            ``import-audit PATH`` to audit an external source tree against the
            installed platform owners.

    Returns:
        ``0`` after printing the validation summary to stdout, ``1`` after printing a
        handled standards, filesystem, or value failure, or audit findings, to stderr,
        or ``2`` after printing usage for invalid arguments.

    Raises:
        OSError: If resolving the default working directory or writing output fails
            outside the standards-validation handler.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if cli_arguments[:1] == ["import-audit"]:
        if len(cli_arguments) != 2:
            print(
                "usage: alpha-governance-engineering-standards import-audit PATH", file=sys.stderr
            )
            return 2
        audit = ImportAudit()
        try:
            findings = audit.audit(Path(cli_arguments[1]))
        except (OSError, SyntaxError, UnicodeError) as error:
            print(f"import audit: {error}", file=sys.stderr)
            return 1
        for line in audit.report(findings):
            print(line, file=sys.stderr)
        if findings:
            return 1
        print(f"Import audit passed for {cli_arguments[1]}")
        return 0
    if len(cli_arguments) > 1:
        print(
            "usage: alpha-governance-engineering-standards [repository-root | import-audit PATH]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        EngineeringStandards.validate_repository(repository_root)
    except (EngineeringStandardsError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        "Python clarity standards passed for src, tests, governance, native stubs, "
        "examples and extensions"
    )
    return 0
