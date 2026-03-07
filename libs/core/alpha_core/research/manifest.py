"""Cross-stage run manifest contracts for artifact lineage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.run_context as run_context_mod

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

#: Increment this constant whenever any field in :class:`RunManifest` changes
#: (add, remove, rename, or type-change).  The regression snapshot at
#: ``tests/data/fixtures/schema_snapshots/run_manifest_v{N}.json`` and the JSON
#: Schema at ``data/schemas/run_manifest_v{N}.json`` must be updated together
#: with every bump.
RUN_MANIFEST_SCHEMA_VERSION: int = 1


class RunManifest(BaseModel):
    """Persistent run manifest linking a RunContext to its stage outputs.

    Stage-specific metadata (dataset IDs, feature set versions, etc.) should be
    stored as entries in *artifacts* rather than as top-level fields so that this
    contract stays stable across all pipeline stages.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(
        default=RUN_MANIFEST_SCHEMA_VERSION,
        description="Manifest schema version.  Bump whenever the contract changes.",
    )
    run: run_context_mod.RunContext
    artifacts: dict[str, str]
    parent_run_id: str | None = None


def write_run_manifest(path: Path, manifest: RunManifest) -> None:
    """Atomically persist a run manifest JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    temp_path.replace(path)


def read_run_manifest(path: Path) -> RunManifest:
    """Load a run manifest from JSON."""
    return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))


def persist_run_record(
    *,
    storage_root: Path,
    run_context: run_context_mod.RunContext,
    config_payload: dict[str, Any],
    artifacts: dict[str, str],
    parent_run_id: str | None,
) -> None:
    """Persist the config snapshot, artifact index, and manifest for one run."""
    run_root = artifact_paths.run_root(storage_root, run_context.run_id)
    run_root.mkdir(parents=True, exist_ok=True)

    config_path = artifact_paths.run_config_path(storage_root, run_context.run_id)
    config_path.write_text(
        json.dumps(config_payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    persisted_artifacts = {"config": str(config_path), **artifacts}
    artifact_paths.write_artifacts_index(
        storage_root,
        run_context.run_id,
        persisted_artifacts,
    )
    write_run_manifest(
        artifact_paths.run_manifest_path(storage_root, run_context.run_id),
        RunManifest(
            run=run_context,
            artifacts=persisted_artifacts,
            parent_run_id=parent_run_id,
        ),
    )


__all__ = [
    "RUN_MANIFEST_SCHEMA_VERSION",
    "RunManifest",
    "persist_run_record",
    "read_run_manifest",
    "write_run_manifest",
]
