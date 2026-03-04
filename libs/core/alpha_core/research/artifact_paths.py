"""Canonical run-artifact path helpers.

Every research-plane run (ingestion, dataset build, feature build, backtest,
evaluate, optimize, live) produces output under a single deterministic root::

    {storage_root}/runs/{run_id}/
        manifest.json       - RunManifest (run context + artifact index)
        config.json         - frozen run config snapshot
        artifacts.json      - logical artifact key -> absolute path index
        stage_outputs/      - default home for run-scoped output files

Rules
-----
- All helper functions are **pure** - no filesystem I/O.
- :func:`artifact_key_path` is the single source of truth for default per-key
  paths so callers never construct paths ad-hoc.
- Stage-specific outputs (datasets, features, backtests, reports) may live
  outside ``stage_outputs/`` but **must** be registered in ``artifacts.json``
  so the manifest can locate them.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Fixed-file path helpers
# ---------------------------------------------------------------------------


def run_root(storage_root: Path, run_id: str) -> Path:
    """Canonical run directory: ``{storage_root}/runs/{run_id}``."""
    return storage_root / "runs" / run_id


def run_manifest_path(storage_root: Path, run_id: str) -> Path:
    """Path to ``manifest.json`` inside the run directory."""
    return run_root(storage_root, run_id) / "manifest.json"


def run_config_path(storage_root: Path, run_id: str) -> Path:
    """Path to ``config.json`` (frozen config snapshot) inside the run directory."""
    return run_root(storage_root, run_id) / "config.json"


def run_artifacts_path(storage_root: Path, run_id: str) -> Path:
    """Path to ``artifacts.json`` (logical key -> absolute path index) inside the run directory."""
    return run_root(storage_root, run_id) / "artifacts.json"


def stage_outputs_path(storage_root: Path, run_id: str) -> Path:
    """Default root for run-scoped stage output files: ``{run_root}/stage_outputs/``."""
    return run_root(storage_root, run_id) / "stage_outputs"


# ---------------------------------------------------------------------------
# Deterministic per-artifact path
# ---------------------------------------------------------------------------


def artifact_key_path(storage_root: Path, run_id: str, artifact_key: str) -> Path:
    """Return the **deterministic** path for *artifact_key* under *stage_outputs/*.

    For identical ``(storage_root, run_id, artifact_key)`` inputs this function
    always returns the same :class:`~pathlib.Path` - no I/O is performed.

    *artifact_key* rules:

    - Must be non-empty.
    - May use ``/`` to create subdirectories under ``stage_outputs/``.
    - Must not be an absolute path or contain ``..`` traversal components.
    """
    _validate_artifact_key(artifact_key)
    return stage_outputs_path(storage_root, run_id) / artifact_key


def _validate_artifact_key(key: str) -> None:
    if not key:
        raise ValueError("artifact_key must be non-empty")
    if key.startswith("/"):
        raise ValueError("artifact_key must be a relative path, not absolute")
    if ".." in key.split("/"):
        raise ValueError("artifact_key must not contain '..' traversal components")


# ---------------------------------------------------------------------------
# Artifact index I/O  (artifacts.json)
# ---------------------------------------------------------------------------


def write_artifacts_index(
    storage_root: Path,
    run_id: str,
    artifacts: dict[str, str],
) -> None:
    """Atomically write the logical artifact key->path index to ``artifacts.json``.

    Creates the run directory if it does not already exist.
    """
    path = run_artifacts_path(storage_root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(artifacts, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def read_artifacts_index(storage_root: Path, run_id: str) -> dict[str, str]:
    """Read the artifact key->path index from ``artifacts.json``.

    Returns an empty ``dict`` when the file does not exist so callers can
    treat a missing index the same as an empty one.
    """
    path = run_artifacts_path(storage_root, run_id)
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


__all__ = [
    "artifact_key_path",
    "read_artifacts_index",
    "run_artifacts_path",
    "run_config_path",
    "run_manifest_path",
    "run_root",
    "stage_outputs_path",
    "write_artifacts_index",
]
