"""High-confidence repository secret detection for CI preflight."""

from __future__ import annotations

import re
from pathlib import Path

from alpha_research_governance.ci_policy.models import CIPolicyError
from alpha_research_governance.ci_policy.selection import normalize_changed_paths

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


def secret_pattern_ids() -> tuple[str, ...]:
    """Return the closed high-confidence pattern set."""
    return tuple(sorted(_SECRET_PATTERNS))


def scan_secret_bytes(payload: bytes) -> tuple[str, ...]:
    """Return pattern identifiers found without disclosing matching material."""
    return tuple(
        pattern_id
        for pattern_id, pattern in sorted(_SECRET_PATTERNS.items())
        if pattern.search(payload) is not None
    )


def scan_secret_paths(
    repository_root: Path,
    paths: tuple[str, ...],
    *,
    maximum_file_bytes: int,
) -> None:
    """Fail closed on unsafe files or any high-confidence secret match."""
    findings: list[str] = []
    normalized = normalize_changed_paths(tuple(("M", path) for path in paths))
    repository_root = repository_root.resolve(strict=True)
    for relative_path in sorted({item.path for item in normalized}):
        path = repository_root / relative_path
        try:
            path.resolve(strict=False).relative_to(repository_root)
        except ValueError:
            findings.append(f"secret scan path escapes repository root: {relative_path}")
            continue
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
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
