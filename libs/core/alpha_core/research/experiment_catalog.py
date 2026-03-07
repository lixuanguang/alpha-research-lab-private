"""ExperimentCatalog contracts and JSONL persistence.

An :class:`ExperimentCatalog` is a queryable index of research runs annotated
with an explicit promotion status so experiments can be tracked from initial
candidate through to paper-trading approval or rejection.

Status lifecycle::

    candidate  →  needs_review  →  approved_for_paper
                                 ↘  rejected

Storage layout::

    {storage_root}/catalog/catalog.jsonl

Each line is one JSON-encoded :class:`CatalogEntry`.  New entries are appended;
status updates append a new entry with the same *entry_id* — the latest entry
per ``entry_id`` wins.  This makes the file an append-only audit log.

Typical usage::

    import alpha_core.research.experiment_catalog as catalog_mod

    entry = catalog_mod.add_entry(
        storage_root,
        session_id=sess.session_id,
        run_id=evaluate_run_id,
        strategy_id="zscore_v1",
    )
    catalog_mod.update_status(
        storage_root,
        entry.entry_id,
        status="needs_review",
    )
    catalog_mod.update_status(
        storage_root,
        entry.entry_id,
        status="approved_for_paper",
        reviewed_by="alice",
        reason="Sharpe > 1.5, drawdown < 10%",
    )
    approved = catalog_mod.list_by_status(storage_root, "approved_for_paper")
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ExperimentStatus = Literal["candidate", "needs_review", "approved_for_paper", "rejected"]

_ALL_STATUSES: tuple[ExperimentStatus, ...] = (
    "candidate",
    "needs_review",
    "approved_for_paper",
    "rejected",
)
_ALLOWED_STATUS_TRANSITIONS: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    "candidate": frozenset({"candidate", "needs_review"}),
    "needs_review": frozenset({"needs_review", "approved_for_paper", "rejected"}),
    "approved_for_paper": frozenset({"approved_for_paper"}),
    "rejected": frozenset({"rejected"}),
}

# ---------------------------------------------------------------------------
# Storage path helpers
# ---------------------------------------------------------------------------

_CATALOG_DIR = "catalog"
_CATALOG_FILE = "catalog.jsonl"


def _catalog_path(storage_root: Path) -> Path:
    return storage_root / _CATALOG_DIR / _CATALOG_FILE


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class CatalogEntry(BaseModel):
    """A single experiment record inside the catalog.

    Fields
    ------
    entry_id
        Stable unique identifier for this experiment record.  Multiple rows
        with the same *entry_id* in the JSONL file represent successive status
        updates; only the latest wins.
    session_id
        Optional reference to the :class:`~alpha_core.research.session.ResearchSession`
        that grouped the runs for this experiment.
    run_id
        The primary run ID being promoted (typically an ``evaluate`` run).
    status
        Current promotion status.
    strategy_id
        Strategy identifier, propagated from the run manifest when available.
    dataset_id
        Gold dataset identifier used for this experiment.
    feature_set_version
        Feature set version used for this experiment.
    notes
        Free-text researcher notes.
    reviewed_by
        Reviewer identifier set when status moves to ``approved_for_paper`` or
        ``rejected``.
    reviewed_at_utc
        Timestamp of the review action.
    reason
        Justification text for promote / reject decisions.
    created_at_utc
        Timestamp when this entry was first added to the catalog.
    updated_at_utc
        Timestamp of the last status change.
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    session_id: str | None = None
    run_id: str
    status: ExperimentStatus = "candidate"
    strategy_id: str | None = None
    dataset_id: str | None = None
    feature_set_version: str | None = None
    notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at_utc: datetime | None = None
    reason: str | None = None
    created_at_utc: datetime
    updated_at_utc: datetime


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def add_entry(
    storage_root: Path,
    *,
    run_id: str,
    session_id: str | None = None,
    strategy_id: str | None = None,
    dataset_id: str | None = None,
    feature_set_version: str | None = None,
    notes: str | None = None,
) -> CatalogEntry:
    """Append a new ``candidate`` entry to the catalog.

    Returns the created :class:`CatalogEntry`.
    """
    now = datetime.now(tz=UTC)
    entry = CatalogEntry(
        entry_id=uuid.uuid4().hex,
        session_id=session_id,
        run_id=run_id,
        status="candidate",
        strategy_id=strategy_id,
        dataset_id=dataset_id,
        feature_set_version=feature_set_version,
        notes=notes,
        created_at_utc=now,
        updated_at_utc=now,
    )
    _append(storage_root, entry)
    return entry


def update_status(
    storage_root: Path,
    entry_id: str,
    *,
    status: ExperimentStatus,
    reviewed_by: str | None = None,
    reason: str | None = None,
    notes: str | None = None,
) -> CatalogEntry:
    """Update the status of *entry_id* and append the revised record.

    Raises :exc:`KeyError` if *entry_id* does not exist in the catalog.
    Raises :exc:`ValueError` for invalid *status* values.
    """
    if status not in _ALL_STATUSES:
        raise ValueError(f"Invalid status {status!r}. Must be one of {_ALL_STATUSES}.")
    current = get_entry(storage_root, entry_id)
    _validate_transition(current.status, status)
    now = datetime.now(tz=UTC)
    payload = current.model_dump(mode="python")
    payload["status"] = status
    payload["updated_at_utc"] = now
    if reviewed_by is not None:
        payload["reviewed_by"] = reviewed_by
        payload["reviewed_at_utc"] = now
    if reason is not None:
        payload["reason"] = reason
    if notes is not None:
        payload["notes"] = notes
    updated = CatalogEntry.model_validate(payload)
    _append(storage_root, updated)
    return updated


def get_entry(storage_root: Path, entry_id: str) -> CatalogEntry:
    """Return the latest record for *entry_id*.

    Raises :exc:`KeyError` if not found.
    """
    entries = _latest_by_id(storage_root)
    if entry_id not in entries:
        raise KeyError(f"Catalog entry not found: {entry_id!r}")
    return entries[entry_id]


def list_all(storage_root: Path) -> list[CatalogEntry]:
    """Return all entries (latest record per entry_id), sorted by *created_at_utc*."""
    return sorted(
        _latest_by_id(storage_root).values(),
        key=lambda e: e.created_at_utc,
    )


def list_by_status(storage_root: Path, status: ExperimentStatus) -> list[CatalogEntry]:
    """Return entries matching *status*, sorted by *created_at_utc*."""
    return [e for e in list_all(storage_root) if e.status == status]


def list_by_session(storage_root: Path, session_id: str) -> list[CatalogEntry]:
    """Return entries belonging to *session_id*, sorted by *created_at_utc*."""
    return [e for e in list_all(storage_root) if e.session_id == session_id]


def list_by_run(storage_root: Path, run_id: str) -> list[CatalogEntry]:
    """Return all entries whose *run_id* matches, sorted by *created_at_utc*."""
    return [e for e in list_all(storage_root) if e.run_id == run_id]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _append(storage_root: Path, entry: CatalogEntry) -> None:
    """Append one JSON line to the catalog file (creates the file if absent)."""
    path = _catalog_path(storage_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(_to_serialisable(entry), sort_keys=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _latest_by_id(storage_root: Path) -> dict[str, CatalogEntry]:
    """Read all lines; keep only the last record per entry_id (audit-log semantics)."""
    path = _catalog_path(storage_root)
    if not path.exists():
        return {}
    latest: dict[str, CatalogEntry] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        entry = CatalogEntry.model_validate_json(raw)
        latest[entry.entry_id] = entry
    return latest


def _validate_transition(
    current_status: ExperimentStatus,
    target_status: ExperimentStatus,
) -> None:
    allowed_targets = _ALLOWED_STATUS_TRANSITIONS[current_status]
    if target_status in allowed_targets:
        return
    allowed_repr = ", ".join(sorted(allowed_targets))
    raise ValueError(
        "Invalid status transition "
        f"{current_status!r} -> {target_status!r}. "
        f"Allowed targets from {current_status!r}: {allowed_repr}."
    )


def _to_serialisable(entry: CatalogEntry) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(entry.model_dump_json()))
