"""Run-context models for research-plane reproducibility."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

import alpha_core.utils.time as time_utils


class RunContext(BaseModel):
    """Run-level context for research workflows."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_type: Literal["dataset_build"]
    config_hash: str
    git_commit: str | None = None
    started_at_utc: datetime
    completed_at_utc: datetime | None = None


def make_run_context(
    run_type: Literal["dataset_build"],
    *,
    config_payload: dict[str, Any],
    git_commit: str | None = None,
) -> RunContext:
    """Create a normalized run context from a config payload."""
    config_hash = _hash_payload(config_payload)
    return RunContext(
        run_id=uuid.uuid4().hex,
        run_type=run_type,
        config_hash=config_hash,
        git_commit=git_commit,
        started_at_utc=datetime.now(tz=UTC),
        completed_at_utc=None,
    )


def close_run_context(run: RunContext) -> RunContext:
    """Return a completed copy of *run* with UTC completion timestamp."""
    payload = run.model_dump(mode="python")
    payload["started_at_utc"] = time_utils.ensure_utc(run.started_at_utc)
    payload["completed_at_utc"] = datetime.now(tz=UTC)
    return RunContext.model_validate(payload)


def _hash_payload(payload: dict[str, Any]) -> str:
    serial = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serial.encode()).hexdigest()


__all__ = ["RunContext", "close_run_context", "make_run_context"]
