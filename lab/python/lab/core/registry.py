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
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
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


def compute_results_hash(
    metrics: Mapping[str, float],
    *,
    config_hash: str,
    toy_seed: int,
    data_snapshot_id: str | None = None,
    artifact_hashes: Mapping[str, str] | None = None,
) -> str:
    """SHA-256 hash binding metrics to config identity and toy seed.

    The payload is canonicalised with sorted keys so identical inputs always
    produce identical hashes.
    """
    rounded = {k: round(float(v), 6) for k, v in metrics.items()}
    payload = {
        "metrics": rounded,
        "config_hash": config_hash,
        "toy_seed": int(toy_seed),
        "data_snapshot_id": str(data_snapshot_id) if data_snapshot_id is not None else None,
        "artifact_hashes": dict(sorted((artifact_hashes or {}).items())),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_update_str(h: Any, text: str) -> None:
    b = text.encode("utf-8")
    h.update(len(b).to_bytes(8, "little", signed=False))
    h.update(b)


def _canonical_datetime_index(idx: pd.DatetimeIndex) -> np.ndarray:
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return np.asarray(idx.asi8, dtype="<i8")


def _hash_index(index: pd.Index) -> str:
    h = hashlib.sha256()
    _hash_update_str(h, type(index).__name__)
    if isinstance(index, pd.DatetimeIndex):
        arr = _canonical_datetime_index(index)
        h.update(arr.tobytes(order="C"))
    else:
        for item in index.tolist():
            _hash_update_str(h, str(item))
    return h.hexdigest()


def compute_stable_series_hash(series: pd.Series) -> str:
    """Deterministic SHA-256 hash for a numeric series across environments."""
    s = series.copy()
    s.index = pd.Index(s.index)
    s = s.sort_index()

    values = s.to_numpy(dtype=np.float64, copy=True)
    if not np.isfinite(values).all():
        raise ValueError("compute_stable_series_hash requires finite values.")
    values = np.ascontiguousarray(values.astype("<f8", copy=False))

    h = hashlib.sha256()
    _hash_update_str(h, "series")
    _hash_update_str(h, str(s.name) if s.name is not None else "")
    _hash_update_str(h, _hash_index(s.index))
    _hash_update_str(h, str(values.shape))
    h.update(values.tobytes(order="C"))
    return h.hexdigest()


def compute_stable_frame_hash(frame: pd.DataFrame) -> str:
    """Deterministic SHA-256 hash for a numeric DataFrame across environments."""
    df = frame.copy()
    df = df.sort_index().sort_index(axis=1)
    df.index = pd.Index(df.index)
    df.columns = pd.Index(df.columns)

    values = df.to_numpy(dtype=np.float64, copy=True)
    if not np.isfinite(values).all():
        raise ValueError("compute_stable_frame_hash requires finite values.")
    values = np.ascontiguousarray(values.astype("<f8", copy=False))

    h = hashlib.sha256()
    _hash_update_str(h, "frame")
    _hash_update_str(h, _hash_index(df.index))
    _hash_update_str(h, _hash_index(df.columns))
    _hash_update_str(h, str(values.shape))
    h.update(values.tobytes(order="C"))
    return h.hexdigest()


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
    base_rid = generate_run_id(config_hash)
    rid = base_rid
    suffix = 0

    while True:
        rdir = run_dir(rid)
        # Avoid accidental overwrite when multiple runs share the same
        # second-level timestamp and config hash prefix.
        if not any(rdir.iterdir()):
            break
        suffix += 1
        rid = f"{base_rid}_{suffix:02d}"

    meta: dict[str, Any] = {
        "run_id": rid,
        "start_time": datetime.now(UTC).isoformat(),
        "exp_name": exp_name,
        "config_path": str(Path(config_path).resolve()),
        "config_hash": config_hash,
        "data_snapshot_id": None,
        "git_commit": get_git_commit(),
        "python_version": sys.version,
        "platform": platform.platform(),
    }

    meta_path = rdir / "meta.json"
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)

    return rid, rdir


def update_run_meta(
    rdir: Path,
    **fields: Any,
) -> dict[str, Any]:
    """Merge fields into run ``meta.json`` and return updated metadata."""
    meta_path = Path(rdir) / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        with open(meta_path) as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            meta = loaded
    for key, value in fields.items():
        meta[str(key)] = value
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)
    return meta
