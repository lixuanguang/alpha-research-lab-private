"""Path resolution helpers for config and secrets loading."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT_ENV_VAR = "ALPHA_RESEARCH_ROOT"


def _is_project_root(candidate: Path) -> bool:
    """Return True when *candidate* looks like the repository root."""
    return (candidate / "pyproject.toml").exists() and (
        candidate / "config" / "default.yaml"
    ).exists()


def _search_upwards(start: Path) -> Path | None:
    """Search *start* and its parents for a project root marker."""
    current = start.resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if _is_project_root(candidate):
            return candidate

    return None


def find_project_root(module_file: str) -> Path:
    """Resolve project root via env var, CWD ancestry, then module-file ancestry."""
    env_root = os.getenv(_ROOT_ENV_VAR)
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if not _is_project_root(candidate):
            raise FileNotFoundError(
                f"{_ROOT_ENV_VAR} must point to a directory containing "
                "`pyproject.toml` and `config/default.yaml`: "
                f"{candidate}"
            )
        return candidate

    cwd_root = _search_upwards(Path.cwd())
    if cwd_root is not None:
        return cwd_root

    module_root = _search_upwards(Path(module_file))
    if module_root is not None:
        return module_root

    raise FileNotFoundError(
        "Unable to locate project root. Set ALPHA_RESEARCH_ROOT, or pass explicit "
        "`config_dir` / `secrets_file` paths."
    )
