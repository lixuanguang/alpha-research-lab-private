"""Run the retained CI secret-scan preflight."""

from __future__ import annotations

# standard library imports
import subprocess  # nosec B404  # [owner=platform; rationale=Git path listing boundary; expires=2027-03-01]
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.ci_policy.secrets import (
    CIPolicyError,
    scan_repository_paths,
)


def _git_tracked_paths(repository_root: Path) -> tuple[str, ...]:
    """Read NUL-delimited tracked paths; the CLI owns process/error translation."""
    completed = subprocess.run(  # nosec B603, B607  # [owner=platform; rationale=constant Git argv; expires=2027-03-01]
        ["git", "ls-files", "-z"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return tuple(item for item in completed.stdout.decode("utf-8").split("\0") if item)


def _parse_arguments(arguments: Sequence[str]) -> tuple[bool, tuple[str, ...]]:
    """Parse CLI tokens into mutually exclusive all-files or explicit-path modes.

    Return ``(scan_all, paths)``. Raise ``CIPolicyError`` for unsupported commands
    or options, an empty scope, or a mixture of all-files and explicit paths.
    """
    if not arguments or arguments[0] != "scan-secrets":
        raise CIPolicyError(["CI command accepts only scan-secrets"])

    scan_all = False
    paths: list[str] = []
    for argument in arguments[1:]:
        if argument == "--all":
            scan_all = True
        elif argument == "--":
            continue
        elif argument.startswith("-"):
            raise CIPolicyError([f"unknown scan-secrets option: {argument}"])
        else:
            paths.append(argument)
    if scan_all == bool(paths):
        raise CIPolicyError(["scan-secrets accepts --all or one or more paths"])
    return scan_all, tuple(paths)


def main(arguments: Sequence[str] | None = None) -> int:
    """Scan tracked or explicitly supplied files for secrets.

    ``--all`` obtains every Git-tracked path. Both modes run local patterns and the external
    ``detect-private-key`` executable; failures return a nonzero status and never print matches.

    Args:
        arguments: CLI tokens, or ``None`` to consume ``sys.argv[1:]``.

    Returns:
        ``0`` after both scanners pass, or ``1`` after a handled preflight failure.
    """
    cli_arguments = tuple(sys.argv[1:] if arguments is None else arguments)
    try:
        scan_all, paths = _parse_arguments(cli_arguments)
        repository_root = Path.cwd().resolve(strict=True)
        selected_paths = _git_tracked_paths(repository_root) if scan_all else paths
        scan_repository_paths(repository_root, selected_paths)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
        print(f"CI secret scan failed: {error}", file=sys.stderr)
        return 1
    print(f"CI secret scan passed for {len(selected_paths)} governed paths.")
    return 0
