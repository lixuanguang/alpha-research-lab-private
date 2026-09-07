"""Run the small CI preflight retained during the cleanup migration."""

from __future__ import annotations

# standard library imports
import subprocess  # nosec B404  # [owner=platform; rationale=Git path listing boundary; expires=2027-03-01]
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.ci_policy.secrets import (
    CIPolicyError,
    run_external_secret_scanner,
    scan_repository_paths,
    scan_secret_bytes,
    scan_secret_paths,
    secret_pattern_ids,
)

__all__ = [
    "CIPolicyError",
    "main",
    "run_external_secret_scanner",
    "scan_repository_paths",
    "scan_secret_bytes",
    "scan_secret_paths",
    "secret_pattern_ids",
]


def _git_tracked_paths(repository_root: Path) -> tuple[str, ...]:
    """Return all tracked repository paths using a NUL-delimited Git query.

    Args:
        repository_root: Checkout whose index supplies the tracked paths.

    Returns:
        Canonical repository-relative paths in Git's index order.

    Raises:
        CIPolicyError: Git cannot start, exits unsuccessfully, or emits invalid UTF-8.
    """
    try:
        completed = subprocess.run(  # nosec B603, B607  # [owner=platform; rationale=constant Git argv; expires=2027-03-01]
            ["git", "ls-files", "-z"],
            cwd=repository_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise CIPolicyError([f"Git tracked-path query could not start: {error}"]) from error
    if completed.returncode:
        detail = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").strip()
        raise CIPolicyError([f"Git tracked-path query failed: {detail}"])
    try:
        paths = tuple(item for item in completed.stdout.decode("utf-8").split("\0") if item)
    except UnicodeDecodeError as error:
        raise CIPolicyError(["Git tracked-path query emitted invalid UTF-8"]) from error
    return paths


def _parse_arguments(arguments: Sequence[str]) -> tuple[bool, tuple[str, ...]]:
    """Parse the minimal secret-scan interface without accepting ambiguous modes.

    Args:
        arguments: Full CLI tokens excluding the executable name.

    Returns:
        ``(scan_all, paths)`` where exactly one mode is selected.

    Raises:
        CIPolicyError: The command name is unsupported, or both ``--all`` and paths,
            neither mode, or an unknown option is supplied.
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
    """Scan tracked or explicitly supplied files for repository secrets.

    The ``--all`` mode obtains every Git-tracked path. Both modes run the bounded
    repository-owned patterns and the external ``detect-private-key`` executable;
    an absent scanner, unsafe path, unreadable file, detected pattern, or nonzero
    scanner status returns a failure. Matching contents are never printed.

    Args:
        arguments: CLI tokens, or ``None`` to consume ``sys.argv[1:]``.

    Returns:
        Zero after both scanners pass, or one after a handled preflight failure.

    """
    cli_arguments = tuple(sys.argv[1:] if arguments is None else arguments)
    try:
        scan_all, paths = _parse_arguments(cli_arguments)
        repository_root = Path.cwd().resolve(strict=True)
        selected_paths = _git_tracked_paths(repository_root) if scan_all else paths
        scan_repository_paths(repository_root, selected_paths)
    except (CIPolicyError, OSError, UnicodeError, ValueError) as error:
        print(f"CI secret scan failed: {error}", file=sys.stderr)
        return 1
    print(f"CI secret scan passed for {len(selected_paths)} governed paths.")
    return 0
