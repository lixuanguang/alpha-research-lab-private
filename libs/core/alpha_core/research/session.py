"""ResearchSession contracts and filesystem persistence.

A :class:`ResearchSession` groups one or more pipeline runs under a shared
session identifier so researchers can track which dataset builds, feature
builds, backtests, and evaluations belong to the same experiment iteration.

Storage layout::

    {storage_root}/sessions/{session_id}.json

Each file is a single JSON object representing one session.  Files are written
atomically via a ``*.tmp`` rename so partial writes are not visible.

Typical usage::

    import alpha_core.research.session as session_mod

    sess = session_mod.create_session(storage_root, strategy_id="zscore_v1")
    session_mod.add_run(storage_root, sess.session_id, run_id=feature_run_id)
    sessions = session_mod.list_sessions(storage_root)
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Storage path helpers
# ---------------------------------------------------------------------------

_SESSIONS_DIR = "sessions"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _sessions_dir(storage_root: Path) -> Path:
    return storage_root / _SESSIONS_DIR


def _session_path(storage_root: Path, session_id: str) -> Path:
    safe_session_id = _normalize_session_id(session_id)
    return _sessions_dir(storage_root) / f"{safe_session_id}.json"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class ResearchSession(BaseModel):
    """Session-level grouping of related pipeline runs.

    Fields
    ------
    session_id
        Unique hex UUID identifying this session.
    run_ids
        Ordered list of run IDs attached to this session (newest last).
    dataset_id
        Optional reference to the primary gold-dataset artifact used.
    feature_set_version
        Optional version tag of the feature set used in this session.
    strategy_id
        Optional strategy identifier that anchors the session.
    notes
        Free-text researcher notes.
    created_at_utc
        Session creation timestamp.
    updated_at_utc
        Timestamp of the last mutation (add_run, update_notes …).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    run_ids: list[str] = Field(default_factory=list)
    dataset_id: str | None = None
    feature_set_version: str | None = None
    strategy_id: str | None = None
    notes: str | None = None
    created_at_utc: datetime
    updated_at_utc: datetime

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        return _normalize_session_id(value)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def create_session(
    storage_root: Path,
    *,
    dataset_id: str | None = None,
    feature_set_version: str | None = None,
    strategy_id: str | None = None,
    notes: str | None = None,
    session_id: str | None = None,
) -> ResearchSession:
    """Create and persist a new :class:`ResearchSession`.

    Returns the newly created session.
    """
    now = datetime.now(tz=UTC)
    session = ResearchSession(
        session_id=session_id or uuid.uuid4().hex,
        dataset_id=dataset_id,
        feature_set_version=feature_set_version,
        strategy_id=strategy_id,
        notes=notes,
        created_at_utc=now,
        updated_at_utc=now,
    )
    _write(storage_root, session)
    return session


def load_session(storage_root: Path, session_id: str) -> ResearchSession:
    """Load a session by *session_id*.  Raises :exc:`KeyError` if not found."""
    path = _session_path(storage_root, session_id)
    if not path.exists():
        raise KeyError(f"Session not found: {session_id!r}")
    return ResearchSession.model_validate_json(path.read_text(encoding="utf-8"))


def ensure_session(storage_root: Path, session_id: str) -> ResearchSession:
    """Return an existing session or create an empty one with *session_id*."""
    try:
        return load_session(storage_root, session_id)
    except KeyError:
        return create_session(storage_root, session_id=session_id)


def add_run(storage_root: Path, session_id: str, *, run_id: str) -> ResearchSession:
    """Append *run_id* to the session's run list and persist.

    Idempotent: adding an already-present *run_id* is a no-op.
    """
    session = load_session(storage_root, session_id)
    if run_id not in session.run_ids:
        payload = session.model_dump(mode="python")
        payload["run_ids"] = [*session.run_ids, run_id]
        payload["updated_at_utc"] = datetime.now(tz=UTC)
        session = ResearchSession.model_validate(payload)
        _write(storage_root, session)
    return session


def update_notes(storage_root: Path, session_id: str, *, notes: str) -> ResearchSession:
    """Replace the free-text notes on a session and persist."""
    session = load_session(storage_root, session_id)
    payload = session.model_dump(mode="python")
    payload["notes"] = notes
    payload["updated_at_utc"] = datetime.now(tz=UTC)
    updated = ResearchSession.model_validate(payload)
    _write(storage_root, updated)
    return updated


def list_sessions(storage_root: Path) -> list[ResearchSession]:
    """Return all persisted sessions sorted by *created_at_utc* ascending."""
    d = _sessions_dir(storage_root)
    if not d.exists():
        return []
    sessions = [
        ResearchSession.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(d.glob("*.json"))
    ]
    return sorted(sessions, key=lambda s: s.created_at_utc)


def find_sessions_by_run(storage_root: Path, run_id: str) -> list[ResearchSession]:
    """Return all sessions that contain *run_id*."""
    return [s for s in list_sessions(storage_root) if run_id in s.run_ids]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write(storage_root: Path, session: ResearchSession) -> None:
    """Atomically persist *session* to its canonical path."""
    path = _session_path(storage_root, session.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(_to_serialisable(session), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def _to_serialisable(session: ResearchSession) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(session.model_dump_json()))


def _normalize_session_id(session_id: str) -> str:
    cleaned = session_id.strip()
    if not cleaned:
        raise ValueError("`session_id` must be non-empty")
    if _SESSION_ID_RE.fullmatch(cleaned) is None:
        raise ValueError("`session_id` contains unsupported characters; use [A-Za-z0-9._-]")
    return cleaned
