"""Keep release readiness fail-closed until a trusted artifact consumer exists."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.dependency_admission import require_release_admission


def main(arguments: Sequence[str] | None = None) -> int:
    """Check dependency release admission before rejecting the absent consumer.

    The former development-policy and artifact lifecycle commands are retired.
    Dependency admission alone cannot enable releases or create artifacts.

    Args:
        arguments: ``release-check``, or ``None`` to consume ``sys.argv[1:]``.

    Returns:
        ``1`` for the dependency or no-consumer release restriction, or ``2`` for
        unsupported arguments, including the former no-argument development check.
    """
    if list(sys.argv[1:] if arguments is None else arguments) != ["release-check"]:
        print("usage: alpha-governance-artifacts release-check", file=sys.stderr)
        return 2
    try:
        require_release_admission(Path.cwd())
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
    else:
        print("artifact release blocked: no trusted release consumer exists", file=sys.stderr)
    return 1
