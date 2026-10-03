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

__all__ = ["EngineeringStandards", "EngineeringStandardsError", "main"]


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the compact Python clarity checker from the command line.

    Args:
        arguments: Optional command-line arguments. Omit this value to consume
            ``sys.argv[1:]``; provide at most one repository-root argument.

    Returns:
        ``0`` after printing the validation summary to stdout, ``1`` after printing a
        handled standards, filesystem, or value failure to stderr, or ``2`` after printing
        usage for too many arguments.

    Raises:
        OSError: If resolving the default working directory or writing output fails
            outside the standards-validation handler.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print(
            "usage: alpha-governance-engineering-standards [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        EngineeringStandards.validate_repository(repository_root)
    except (EngineeringStandardsError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print("Python clarity standards passed for src, tests, governance, native stubs and examples")
    return 0
