"""Detect high-confidence repository secrets for local and hosted checks."""

from __future__ import annotations

# standard library imports
import re
import subprocess  # nosec B404  # [owner=platform; rationale=external scanner argv boundary; expires=2027-03-01]
from pathlib import Path, PurePosixPath


class CIPolicyError(ValueError):
    """Report one or more fail-closed CI preflight findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Capture ordered diagnostics without retaining secret contents.

        Args:
            findings: Diagnostic messages that identify paths or pattern names only.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


_SECRET_PATTERNS = {
    "assigned_credential": re.compile(
        rb"(?i)(?:api[_-]?key|client[_-]?secret|password|private[_-]?key|token)"
        rb"[ \t]*[:=][ \t]*['\"]?[A-Za-z0-9+/_.=-]{20,}['\"]?"
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


def secret_pattern_ids() -> tuple[str, ...]:
    """Return the configured high-confidence secret-pattern identifiers in order.

    Returns:
        Pattern identifiers sorted in deterministic lexical order.
    """
    return tuple(sorted(_SECRET_PATTERNS))


def scan_secret_bytes(payload: bytes) -> tuple[str, ...]:
    """Scan bytes without returning matching secret material.

    Args:
        payload: Byte content to inspect.

    Returns:
        Matching pattern identifiers in lexical order.
    """
    return tuple(
        pattern_id
        for pattern_id, pattern in sorted(_SECRET_PATTERNS.items())
        if pattern.search(payload) is not None
    )


def _normalize_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Validate and sort repository-relative path arguments.

    Args:
        paths: Candidate paths supplied by Git or pre-commit.

    Returns:
        Distinct canonical POSIX paths in lexical order.

    Raises:
        CIPolicyError: A path is empty, absolute, non-canonical, contains ``..`` or NUL.
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


def _scan_path_contents(
    repository_root: Path,
    paths: tuple[str, ...],
    *,
    maximum_file_bytes: int,
) -> tuple[str, ...]:
    """Inspect regular files after checking containment and size limits.

    Args:
        repository_root: Existing directory that bounds every path.
        paths: Canonical repository-relative paths to inspect.
        maximum_file_bytes: Inclusive per-file scan limit.

    Returns:
        Fail-closed diagnostics that contain no matching secret contents.

    Raises:
        OSError: A repository or file metadata/content operation fails.
    """
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
    return tuple(findings)


def scan_secret_paths(
    repository_root: Path,
    paths: tuple[str, ...],
    *,
    maximum_file_bytes: int = _MAXIMUM_FILE_BYTES,
) -> None:
    """Scan bounded files and fail closed on unsafe paths, content, or limits.

    Args:
        repository_root: Existing directory that bounds file access.
        paths: Repository-relative paths to inspect.
        maximum_file_bytes: Inclusive per-file byte limit.

    Raises:
        CIPolicyError: A path is unsafe, a file exceeds the limit, or a configured
            high-confidence pattern is detected.
        OSError: The repository or an inspected file cannot be resolved, inspected,
            or read.
        ValueError: ``maximum_file_bytes`` is not positive.
    """
    if maximum_file_bytes <= 0:
        raise ValueError("maximum_file_bytes must be positive")
    findings = _scan_path_contents(
        repository_root,
        _normalize_paths(paths),
        maximum_file_bytes=maximum_file_bytes,
    )
    if findings:
        raise CIPolicyError(findings)


def run_external_secret_scanner(repository_root: Path, paths: tuple[str, ...]) -> None:
    """Run the pinned pre-commit private-key scanner and propagate failures.

    Args:
        repository_root: Repository directory used as the scanner working directory.
        paths: Canonical repository-relative files passed to ``detect-private-key``.

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


def scan_repository_paths(
    repository_root: Path,
    paths: tuple[str, ...],
    *,
    maximum_file_bytes: int = _MAXIMUM_FILE_BYTES,
) -> None:
    """Run both repository-owned patterns and the external private-key scanner.

    Args:
        repository_root: Repository directory that bounds the scan.
        paths: Repository-relative files to inspect.
        maximum_file_bytes: Inclusive per-file limit for repository-owned checks.

    Raises:
        CIPolicyError: A local pattern, unsafe path, or external scanner fails.
        OSError: A local file operation fails.
    """
    normalized = _normalize_paths(paths)
    scan_secret_paths(
        repository_root,
        normalized,
        maximum_file_bytes=maximum_file_bytes,
    )
    existing = tuple(path for path in normalized if (repository_root / path).is_file())
    run_external_secret_scanner(repository_root, existing)
