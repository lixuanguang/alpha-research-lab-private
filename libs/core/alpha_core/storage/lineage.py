"""Lineage models and persistence for ingestion runs."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import alpha_core.utils.time as time_utils

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class IngestionRun(BaseModel):
    """Run-level ingestion metadata for audit and lineage."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    connector_type: Literal["polling", "streaming"]
    event_types: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
    status: Literal["running", "completed", "failed"] = "running"
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    schema_version: int = 1
    config_snapshot: dict[str, Any] = Field(default_factory=dict)

    @field_validator("venue")
    @classmethod
    def _normalize_venue(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("`venue` must be non-empty")
        return cleaned

    @field_validator("event_types")
    @classmethod
    def _normalize_event_types(cls, value: list[str]) -> list[str]:
        unique_event_types: list[str] = []
        seen: set[str] = set()
        for event_type in value:
            cleaned = event_type.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique_event_types.append(cleaned)
        return unique_event_types

    @field_validator("counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        normalized_counts: dict[str, int] = {}
        for key, count in value.items():
            cleaned_key = key.strip()
            if not cleaned_key:
                raise ValueError("`counts` keys must be non-empty")
            if count < 0:
                raise ValueError("`counts` values must be >= 0")
            normalized_counts[cleaned_key] = count
        return normalized_counts

    @field_validator("started_at", "completed_at")
    @classmethod
    def _normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return time_utils.ensure_utc(value)


class LineageStore:
    """Tracks ingestion runs for auditability."""

    def __init__(self, storage_root: Path) -> None:
        self._runs_root = storage_root / "_lineage" / "runs"
        self._runs_root.mkdir(parents=True, exist_ok=True)

    def start_run(
        self,
        venue: str,
        connector_type: Literal["polling", "streaming"],
        *,
        event_types: list[str] | None = None,
        schema_version: int = 1,
        config_snapshot: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> IngestionRun:
        effective_run_id = _normalize_run_id(run_id or uuid.uuid4().hex)
        run = IngestionRun(
            run_id=effective_run_id,
            venue=venue,
            connector_type=connector_type,
            event_types=list(event_types or []),
            started_at=datetime.now(tz=UTC),
            completed_at=None,
            status="running",
            counts={},
            errors=[],
            schema_version=schema_version,
            config_snapshot=dict(config_snapshot or {}),
        )
        self._persist_run(run)
        return run

    def complete_run(
        self,
        run_id: str,
        counts: dict[str, int],
        errors: list[str] | None = None,
    ) -> None:
        run = self._require_run(run_id)
        self._assert_running(run, transition="complete")
        completed = self._revalidated_run(
            run,
            completed_at=datetime.now(tz=UTC),
            status="completed",
            counts=dict(counts),
            errors=list(errors or []),
        )
        self._persist_run(completed)

    def fail_run(self, run_id: str, error: str) -> None:
        run = self._require_run(run_id)
        self._assert_running(run, transition="fail")
        existing_errors = list(run.errors)
        existing_errors.append(error)
        failed = self._revalidated_run(
            run,
            completed_at=datetime.now(tz=UTC),
            status="failed",
            errors=existing_errors,
        )
        self._persist_run(failed)

    def get_run(self, run_id: str) -> IngestionRun | None:
        run_path = self._run_path(run_id)
        if not run_path.exists():
            return None
        return IngestionRun.model_validate_json(run_path.read_text(encoding="utf-8"))

    def list_runs(
        self,
        venue: str | None = None,
        since: datetime | None = None,
    ) -> list[IngestionRun]:
        normalized_venue = venue.strip().lower() if venue is not None else None
        since_utc = time_utils.ensure_utc(since) if since is not None else None

        runs: list[IngestionRun] = []
        for run_path in sorted(self._runs_root.glob("run_*.json")):
            run = IngestionRun.model_validate_json(run_path.read_text(encoding="utf-8"))
            if normalized_venue is not None and run.venue != normalized_venue:
                continue
            if since_utc is not None and run.started_at < since_utc:
                continue
            runs.append(run)

        return sorted(runs, key=lambda run: run.started_at, reverse=True)

    def _require_run(self, run_id: str) -> IngestionRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return run

    def _persist_run(self, run: IngestionRun) -> None:
        destination = self._run_path(run.run_id)
        tmp_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        try:
            tmp_path.replace(destination)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _run_path(self, run_id: str) -> Path:
        safe_run_id = _normalize_run_id(run_id)
        return self._runs_root / f"run_{safe_run_id}.json"

    def _assert_running(self, run: IngestionRun, *, transition: str) -> None:
        if run.status == "running":
            return
        raise ValueError(
            f"Cannot {transition} run `{run.run_id}` with terminal status `{run.status}`"
        )

    def _revalidated_run(self, run: IngestionRun, **updates: object) -> IngestionRun:
        payload = run.model_dump(mode="python")
        payload.update(updates)
        return IngestionRun.model_validate(payload)


def _normalize_run_id(run_id: str) -> str:
    cleaned = run_id.strip()
    if not cleaned:
        raise ValueError("`run_id` must be non-empty")
    if _RUN_ID_RE.fullmatch(cleaned) is None:
        raise ValueError("`run_id` contains unsupported characters; use [A-Za-z0-9._-]")
    return cleaned


__all__ = ["IngestionRun", "LineageStore"]
