"""§12.3 — Run Artifact Compatibility with Research CLI.

Given a completed :class:`~alpha_core.storage.lineage.IngestionRun`, emit the
standard Research-CLI artifact tree so that downstream research commands can
discover and consume ingestion outputs without custom path logic.

Output layout
-------------

.. code-block:: text

    {storage_root}/runs/{run_id}/
        manifest.json       # RunManifest (RunContext + artifact index + parent_run_id)
        config.json         # frozen config snapshot from IngestionRun
        artifacts.json      # logical key → absolute path index

Standard artifact keys
----------------------

``"config"``
    Frozen config snapshot JSON (auto-written by :func:`persist_run_record`).
``"lineage"``
    Path to the ``_lineage/runs/run_{run_id}.json`` file maintained by
    :class:`~alpha_core.storage.lineage.LineageStore`.
``"handoff_manifest"``
    Path to the dataset-ready handoff manifest JSON when
    ``ingestion_run.handoff_manifest_path`` is set.
``"silver_{event_type}"``
    Per-event-type partition reference(s) supplied via *partition_refs*.
Any additional keys supplied via *extra_artifacts*.

Usage
-----

.. code-block:: python

    from pathlib import Path
    from alpha_core.storage.run_artifact_emitter import emit_ingestion_run_artifacts

    result = emit_ingestion_run_artifacts(
        ingestion_run=completed_run,
        storage_root=Path("data"),
        partition_refs={
            "silver_trades": "silver/trades/venue=kalshi/date=2026-03-01",
        },
    )
    print(result.manifest_path)  # data/runs/{run_id}/manifest.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.storage.lineage as lineage_mod
import alpha_core.utils.time as time_utils

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class IngestionArtifactEmission(BaseModel):
    """Paths and artifact keys written by :func:`emit_ingestion_run_artifacts`."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    """Run identifier — same as ``ingestion_run.run_id``."""
    manifest_path: Path
    """`manifest.json` path inside ``{storage_root}/runs/{run_id}/``."""
    config_path: Path
    """`config.json` path (frozen ingestion config snapshot)."""
    artifacts_path: Path
    """`artifacts.json` path (logical key → absolute path index)."""
    artifact_keys: list[str]
    """All logical artifact keys written (including ``"config"``)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_ingestion_run_artifacts(
    *,
    ingestion_run: lineage_mod.IngestionRun,
    storage_root: Path,
    partition_refs: dict[str, str] | None = None,
    extra_artifacts: dict[str, str] | None = None,
) -> IngestionArtifactEmission:
    """Emit Research-CLI-compatible run artifacts for a completed ingestion run.

    The emitter writes three standard files under
    ``{storage_root}/runs/{run_id}/``:

    * ``manifest.json`` — :class:`~alpha_core.research.manifest.RunManifest`
      with ``run_type="ingestion"`` and links to all artifacts.
    * ``config.json`` — frozen ``config_snapshot`` from the ingestion run.
    * ``artifacts.json`` — logical key → absolute path index.

    This makes the ingestion run discoverable by every Research CLI command
    that reads ``{storage_root}/runs/{run_id}/manifest.json``.

    Args:
        ingestion_run: A **completed** :class:`~alpha_core.storage.lineage.IngestionRun`
            (``status="completed"``).  Raises :exc:`ValueError` for non-completed runs.
        storage_root: Root directory for Research-plane run artifacts.  Typically
            ``Path("data")`` (same root used by the Research CLI).
        partition_refs: Mapping of logical artifact key → partition path (relative
            to the storage root, or absolute).  Keys should follow the
            ``silver_{event_type}`` convention — for example
            ``{"silver_trades": "silver/trades/venue=kalshi/date=2026-03-01"}``.
            Pass ``None`` when no partition refs are available at emit time.
        extra_artifacts: Any additional logical key → path entries to include in
            the artifact index.  These are merged after ``partition_refs``.

    Returns:
        :class:`IngestionArtifactEmission` with the paths of all written files.

    Raises:
        ValueError: If ``ingestion_run.status`` is not ``"completed"``.
    """
    if ingestion_run.status != "completed":
        raise ValueError(
            f"Cannot emit run artifacts for run `{ingestion_run.run_id}` "
            f"with status `{ingestion_run.status}`; run must be completed first."
        )

    run_ctx = _build_run_context(ingestion_run)
    artifacts = _build_artifacts(ingestion_run, storage_root, partition_refs, extra_artifacts)

    manifest_mod.persist_run_record(
        storage_root=storage_root,
        run_context=run_ctx,
        config_payload=ingestion_run.config_snapshot,
        artifacts=artifacts,
        parent_run_id=ingestion_run.parent_run_id,
    )

    run_id = ingestion_run.run_id
    # persist_run_record always prepends "config" to the artifacts dict
    all_keys = ["config", *artifacts.keys()]

    return IngestionArtifactEmission(
        run_id=run_id,
        manifest_path=artifact_paths.run_manifest_path(storage_root, run_id),
        config_path=artifact_paths.run_config_path(storage_root, run_id),
        artifacts_path=artifact_paths.run_artifacts_path(storage_root, run_id),
        artifact_keys=all_keys,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_run_context(ingestion_run: lineage_mod.IngestionRun) -> run_context_mod.RunContext:
    """Construct a :class:`RunContext` from an :class:`IngestionRun`."""
    config_hash = _hash_config(ingestion_run.config_snapshot)
    started = time_utils.ensure_utc(ingestion_run.started_at)
    completed = (
        time_utils.ensure_utc(ingestion_run.completed_at)
        if ingestion_run.completed_at is not None
        else None
    )
    return run_context_mod.RunContext(
        run_id=ingestion_run.run_id,
        run_type="ingestion",
        config_hash=config_hash,
        session_id=None,
        git_commit=run_context_mod.capture_git_commit(),
        started_at_utc=started,
        completed_at_utc=completed,
    )


def _build_artifacts(
    ingestion_run: lineage_mod.IngestionRun,
    storage_root: Path,
    partition_refs: dict[str, str] | None,
    extra_artifacts: dict[str, str] | None,
) -> dict[str, str]:
    """Build the logical artifact key → path dict (excluding ``"config"``).

    The ``"config"`` key is injected automatically by
    :func:`~alpha_core.research.manifest.persist_run_record`, so callers must
    not include it here.

    Key precedence (later entries win on key collision):

    1. ``"lineage"`` — path to the lineage JSON file.
    2. ``"handoff_manifest"`` — when ``ingestion_run.handoff_manifest_path`` is set.
    3. Each key from *partition_refs* (``silver_{event_type}`` convention).
    4. Each key from *extra_artifacts*.
    """
    artifacts: dict[str, str] = {}

    # Always include the lineage record
    lineage_path = _lineage_run_path(storage_root, ingestion_run.run_id)
    artifacts["lineage"] = str(lineage_path)

    # Handoff manifest (optional)
    if ingestion_run.handoff_manifest_path is not None:
        artifacts["handoff_manifest"] = ingestion_run.handoff_manifest_path

    # Silver partition refs (optional)
    if partition_refs:
        for key, ref in partition_refs.items():
            artifacts[key] = ref

    # Caller-supplied extras (optional, overrides above on collision)
    if extra_artifacts:
        for key, path in extra_artifacts.items():
            artifacts[key] = path

    return artifacts


def _lineage_run_path(storage_root: Path, run_id: str) -> Path:
    """Return the path where :class:`~alpha_core.storage.lineage.LineageStore` persists *run_id*."""
    # Mirror LineageStore._run_path: {storage_root}/_lineage/runs/run_{run_id}.json
    return storage_root / "_lineage" / "runs" / f"run_{run_id}.json"


def _hash_config(config_snapshot: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 config hash from a config snapshot dict."""
    serial = json.dumps(config_snapshot, sort_keys=True, default=str)
    return hashlib.sha256(serial.encode()).hexdigest()


__all__ = [
    "IngestionArtifactEmission",
    "emit_ingestion_run_artifacts",
]
