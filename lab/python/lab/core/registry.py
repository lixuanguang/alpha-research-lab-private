"""
lab.core.registry
~~~~~~~~~~~~~~~~~
Run identity, directory creation, and ``meta.json`` writer.

Every experiment run gets:

- A unique **run_id** = ``YYYYMMDD_HHMMSS_<config_hash[:6]>``
- A directory under ``runs/<run_id>/``
- A ``meta.json`` capturing full provenance (config hash, git commit, etc.)
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from lab.core.paths import run_dir

# ── Config hashing ────────────────────────────────────────────────────────────


def _normalize(obj: Any) -> Any:
    """Recursively sort dict keys for deterministic serialization."""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def compute_config_hash(raw_config: dict[str, Any]) -> str:
    """SHA-256 hash of the normalized (sorted-key) YAML representation.

    Parameters
    ----------
    raw_config : dict
        The raw parsed YAML config.

    Returns
    -------
    str
        Hex-encoded SHA-256 digest (64 chars).
    """
    normalized = _normalize(raw_config)
    canonical = yaml.dump(normalized, default_flow_style=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Run-ID generation ────────────────────────────────────────────────────────


def generate_run_id(config_hash: str) -> str:
    """Generate ``run_id = <UTC timestamp>_<short config hash>``.

    Format: ``YYYYMMDD_HHMMSS_<first 6 hex chars of config hash>``

    Human-readable, sortable, and uniquely tied to a specific config snapshot.
    """
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    short_hash = config_hash[:6]
    return f"{ts}_{short_hash}"


# ── Git commit ────────────────────────────────────────────────────────────────


def get_git_commit() -> str | None:
    """Return the current ``git HEAD`` commit hash, or *None* if unavailable.

    Works even when called from a sub-directory of the repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ── Run creation ──────────────────────────────────────────────────────────────


def create_run(
    exp_name: str,
    config_path: str | Path,
    raw_config: dict[str, Any],
) -> tuple[str, Path]:
    """Create a new run directory and write ``meta.json``.

    Parameters
    ----------
    exp_name : str
        Experiment name (e.g. ``"macro_regimes"``).
    config_path : str | Path
        Path to the YAML config file.
    raw_config : dict[str, Any]
        Raw parsed config dict (used for hashing).

    Returns
    -------
    tuple[str, Path]
        ``(run_id, run_directory_path)``
    """
    config_hash = compute_config_hash(raw_config)
    rid = generate_run_id(config_hash)
    rdir = run_dir(rid)

    meta: dict[str, Any] = {
        "run_id": rid,
        "start_time": datetime.now(UTC).isoformat(),
        "exp_name": exp_name,
        "config_path": str(Path(config_path).resolve()),
        "config_hash": config_hash,
        "git_commit": get_git_commit(),
        "python_version": sys.version,
        "platform": platform.platform(),
    }

    meta_path = rdir / "meta.json"
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)

    return rid, rdir
