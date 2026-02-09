"""
lab.core.paths
~~~~~~~~~~~~~~
Canonical path resolution for the project.

**Environment-variable overrides** (set these to redirect output):

- ``LAB_DATA_ROOT``  — default ``<lab_root>/data`` (gitignored)
- ``LAB_RUNS_ROOT``  — default ``<lab_root>/runs`` (gitignored)

If the env-vars are set, output is written there; otherwise the defaults
(relative to the repo root containing ``pyproject.toml``) are used.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Locate lab root (directory containing pyproject.toml) ────────────────────
_THIS_FILE = Path(__file__).resolve()
_LAB_ROOT: Path | None = None

for _parent in _THIS_FILE.parents:
    if (_parent / "pyproject.toml").exists():
        _LAB_ROOT = _parent
        break

if _LAB_ROOT is None:
    raise RuntimeError("Could not locate lab root (no pyproject.toml found in parents).")


def lab_root() -> Path:
    """Return the absolute path to the lab repository root."""
    assert _LAB_ROOT is not None
    return _LAB_ROOT


# ── Data directory ────────────────────────────────────────────────────────────


def data_dir() -> Path:
    """Return the data directory.

    Resolved from ``LAB_DATA_ROOT`` env-var if set, otherwise ``<lab_root>/data``.
    Creates the directory if it doesn't exist.
    """
    env = os.environ.get("LAB_DATA_ROOT")
    p = Path(env).resolve() if env else lab_root() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Runs directory ────────────────────────────────────────────────────────────


def runs_root() -> Path:
    """Return the top-level runs directory.

    Resolved from ``LAB_RUNS_ROOT`` env-var if set, otherwise ``<lab_root>/runs``.
    Creates the directory if it doesn't exist.
    """
    env = os.environ.get("LAB_RUNS_ROOT")
    p = Path(env).resolve() if env else lab_root() / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_dir(run_id: str) -> Path:
    """Return ``runs/<run_id>/`` (created if missing)."""
    p = runs_root() / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def latest_run_dir() -> Path | None:
    """Return the most recent run directory, or *None* if no runs exist."""
    rd = runs_root()
    if not rd.exists():
        return None
    dirs = sorted([c for c in rd.iterdir() if c.is_dir()])
    return dirs[-1] if dirs else None


# ── Experiments directory (configs live here, not run outputs) ────────────────


def experiments_dir() -> Path:
    """Return the experiments config directory (``<root>/experiments/``)."""
    return lab_root() / "experiments"
