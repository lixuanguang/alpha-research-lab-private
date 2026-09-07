"""Retain the runtime secret-scan compatibility boundary during CI cleanup."""

# project library imports
from alpha_research_governance.ci_policy import (
    CIPolicyError,
    main,
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
