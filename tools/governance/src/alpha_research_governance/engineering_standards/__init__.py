"""Canonical language and static-quality standards API and command."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.engineering_standards.models import (
    EngineeringStandards,
    EngineeringStandardsError,
    LanguageStandard,
    ToolStandard,
)
from alpha_research_governance.engineering_standards.policy import (
    load_standards,
    source_tree_findings,
    validate_repository,
    validate_suppression_line,
)

__all__ = [
    "EngineeringStandards",
    "EngineeringStandardsError",
    "LanguageStandard",
    "ToolStandard",
    "load_standards",
    "main",
    "source_tree_findings",
    "validate_repository",
    "validate_suppression_line",
]


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the engineering-standards checker from the command line."""
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print(
            "usage: python -m alpha_research_governance.engineering_standards [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
    try:
        standards = validate_repository(repository_root)
    except (EngineeringStandardsError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"Engineering standards passed for {len(standards.languages)} language policies and "
        f"{len(standards.tools)} exact tools; package status is {standards.package_status}."
    )
    return 0
