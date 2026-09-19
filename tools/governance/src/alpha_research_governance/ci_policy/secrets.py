"""Detect high-confidence repository secrets."""

from __future__ import annotations

# standard library imports
import re
import subprocess  # nosec B404  # [owner=platform; rationale=external scanner argv boundary; expires=2027-03-01]
from pathlib import Path, PurePosixPath


class CIPolicyError(ValueError):
    """Report fail-closed CI preflight findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Join ordered diagnostics without retaining secret contents.

        Args:
            findings: Path or pattern diagnostics without secret contents.
        """
        super().__init__("\n".join(findings))


_SECRET_PATTERNS = {
    "assigned_credential": re.compile(
        rb"(?i)(?P<key_quote>['\"]?)"
        rb"(?:api[_-]?key|client[_-]?secret|password|private[_-]?key|token)"
        rb"(?P=key_quote)[ \t]*[:=][ \t]*['\"]?[A-Za-z0-9+/_.=-]{20,}['\"]?"
    ),
    "aws_access_key": re.compile(rb"(?:A3T[A-Z0-9]|AKIA|ASIA)[A-Z0-9]{16}"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,255}"),
    "private_key": re.compile(
        rb"-----BEGIN (?:DSA |EC |OPENSSH |PGP |RSA )?PRIVATE KEY(?: BLOCK)?-----"
    ),
    "slack_token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "stripe_live_key": re.compile(rb"sk_live_[A-Za-z0-9]{20,}"),
}

_MAXIMUM_FILE_BYTES = 1_000_000
_EXTERNAL_SCANNER = "detect-private-key"


def scan_secret_bytes(payload: bytes) -> tuple[str, ...]:
    """Scan bytes without returning matching secret material.

    Args:
        payload: Byte content to inspect for known secret patterns.

    Returns:
        Matching pattern identifiers in lexical order, without secret contents.
    """
    return tuple(
        pattern_id
        for pattern_id, pattern in sorted(_SECRET_PATTERNS.items())
        if pattern.search(payload) is not None
    )


def _normalize_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Return distinct canonical repository-relative POSIX paths in lexical order.

    Reject empty, absolute, non-canonical, traversal, and NUL-containing paths
    with ``CIPolicyError`` before filesystem access.
    """
    normalized: set[str] = set()
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        if (
            not raw_path
            or path.is_absolute()
            or path.as_posix() != raw_path
            or ".." in path.parts
            or "\0" in raw_path
        ):
            raise CIPolicyError([f"secret scan path is not repository-relative: {raw_path}"])
        normalized.add(raw_path)
    return tuple(sorted(normalized))


def scan_repository_paths(
    repository_root: Path,
    paths: tuple[str, ...],
    *,
    maximum_file_bytes: int = _MAXIMUM_FILE_BYTES,
) -> None:
    """Validate bounded local files, then run both retained scanners.

    Missing tracked files are skipped as deletions. Unsafe or oversized inputs fail before the
    external scanner, and findings exclude secret material.

    Args:
        repository_root: Existing repository directory bounding the scan.
        paths: Repository-relative paths selected by Git or a caller.
        maximum_file_bytes: Inclusive positive per-file scan limit.

    Raises:
        CIPolicyError: Paths, sizes, secret patterns or the external scanner fail.
        OSError: File metadata or content cannot be read.
        ValueError: The byte limit is not positive.
    """
    if maximum_file_bytes <= 0:
        raise ValueError("maximum_file_bytes must be positive")
    paths = _normalize_paths(paths)
    root = repository_root.resolve(strict=True)
    findings: list[str] = []
    for relative_path in paths:
        path = root / relative_path
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError:
            findings.append(f"secret scan path escapes repository root: {relative_path}")
            continue
        if path.is_symlink():
            findings.append(f"secret scan rejects non-regular path: {relative_path}")
            continue
        if not path.exists():
            continue
        if not path.is_file():
            findings.append(f"secret scan rejects non-regular path: {relative_path}")
            continue
        size = path.stat().st_size
        if size > maximum_file_bytes:
            findings.append(f"secret scan file exceeds {maximum_file_bytes} bytes: {relative_path}")
            continue
        matches = scan_secret_bytes(path.read_bytes())
        if matches:
            findings.append(f"secret pattern {','.join(matches)} detected in {relative_path}")
    if findings:
        raise CIPolicyError(findings)
    existing = tuple(path for path in paths if (root / path).is_file())
    run_external_secret_scanner(root, existing)


def run_external_secret_scanner(repository_root: Path, paths: tuple[str, ...]) -> None:
    """Run the pinned private-key scanner.

    Args:
        repository_root: Scanner working directory.
        paths: Canonical files passed to ``detect-private-key``.

    Raises:
        CIPolicyError: The scanner cannot start or exits with a nonzero status.
    """
    if not paths:
        return
    try:
        completed = subprocess.run(  # nosec B603  # [owner=platform; rationale=constant executable with validated paths; expires=2027-03-01]
            [_EXTERNAL_SCANNER, "--", *paths],
            cwd=repository_root,
            check=False,
        )
    except OSError as error:
        raise CIPolicyError([f"private-key scanner could not start: {error}"]) from error
    if completed.returncode:
        raise CIPolicyError([f"private-key scanner failed with exit {completed.returncode}"])
