"""Cross-stage run-context models for research-to-production reproducibility."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

import alpha_core.utils.time as time_utils

# All supported run types across every pipeline stage.
RunType = Literal[
    "ingestion",
    "dataset_build",
    "feature_build",
    "backtest",
    "evaluate",
    "optimize",
    "live",
]


class RunContext(BaseModel):
    """Immutable run-level identity and timing metadata shared by all pipeline stages."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_type: RunType
    config_hash: str
    git_commit: str | None = None
    started_at_utc: datetime
    completed_at_utc: datetime | None = None


def make_run_context(
    run_type: RunType,
    *,
    config_payload: dict[str, Any],
    git_commit: str | None = None,
) -> RunContext:
    """Create a normalized run context from a config payload.

    If *git_commit* is ``None``, :func:`capture_git_commit` is called as a
    best-effort fallback so every run carries provenance when inside a Git repo.
    """
    if git_commit is None:
        git_commit = capture_git_commit()
    return RunContext(
        run_id=uuid.uuid4().hex,
        run_type=run_type,
        config_hash=_hash_payload(config_payload),
        git_commit=git_commit,
        started_at_utc=datetime.now(tz=UTC),
        completed_at_utc=None,
    )


def close_run_context(run: RunContext) -> RunContext:
    """Return a completed copy of *run* with a UTC completion timestamp."""
    payload = run.model_dump(mode="python")
    payload["started_at_utc"] = time_utils.ensure_utc(run.started_at_utc)
    payload["completed_at_utc"] = datetime.now(tz=UTC)
    return RunContext.model_validate(payload)


def capture_git_commit() -> str | None:
    """Return the current HEAD short-hash, or ``None`` when unavailable.

    Safe to call outside a Git repository or when the ``git`` binary is absent.
    """
    git_executable = shutil.which("git")
    if git_executable is None:
        return None
    try:
        result = subprocess.run(
            [git_executable, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _hash_payload(payload: dict[str, Any]) -> str:
    serial = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serial.encode()).hexdigest()


__all__ = [
    "RunContext",
    "RunType",
    "capture_git_commit",
    "close_run_context",
    "make_run_context",
]
