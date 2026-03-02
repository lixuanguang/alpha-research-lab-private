"""Path helpers for research run artifacts."""

from __future__ import annotations

from pathlib import Path


def run_root(storage_root: Path, run_id: str) -> Path:
    """Canonical run root: ``{storage_root}/runs/{run_id}``."""
    return storage_root / "runs" / run_id


def run_manifest_path(storage_root: Path, run_id: str) -> Path:
    """Path to run manifest JSON."""
    return run_root(storage_root, run_id) / "manifest.json"


def run_config_path(storage_root: Path, run_id: str) -> Path:
    """Path to frozen run config JSON."""
    return run_root(storage_root, run_id) / "config.json"


def run_artifacts_path(storage_root: Path, run_id: str) -> Path:
    """Path to logical artifact mapping JSON."""
    return run_root(storage_root, run_id) / "artifacts.json"


__all__ = ["run_artifacts_path", "run_config_path", "run_manifest_path", "run_root"]
