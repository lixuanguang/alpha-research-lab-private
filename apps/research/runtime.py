"""Research runtime scaffolding for stage-aligned run manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod


@dataclass(slots=True, frozen=True)
class ResearchStageRequest:
    run_type: run_context_mod.RunType
    payload: dict[str, Any]
    storage_root: Path
    execute: bool
    parent_run_id: str | None = None


@dataclass(slots=True, frozen=True)
class ResearchStageOutcome:
    run_id: str
    run_type: run_context_mod.RunType
    status: str
    config_hash: str
    manifest_path: Path | None = None


def run_stage(request: ResearchStageRequest) -> ResearchStageOutcome:
    run_context = run_context_mod.make_run_context(
        request.run_type,
        config_payload=request.payload,
    )
    if not request.execute:
        return ResearchStageOutcome(
            run_id=run_context.run_id,
            run_type=run_context.run_type,
            status="planned",
            config_hash=run_context.config_hash,
            manifest_path=None,
        )

    completed_context = run_context_mod.close_run_context(run_context)
    run_root = artifact_paths.run_root(request.storage_root, completed_context.run_id)
    run_root.mkdir(parents=True, exist_ok=True)

    config_path = artifact_paths.run_config_path(request.storage_root, completed_context.run_id)
    config_path.write_text(
        json.dumps(request.payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    artifacts = {"config": str(config_path)}
    artifact_paths.write_artifacts_index(request.storage_root, completed_context.run_id, artifacts)

    manifest = manifest_mod.RunManifest(
        run=completed_context,
        artifacts=artifacts,
        parent_run_id=request.parent_run_id,
    )
    manifest_path = artifact_paths.run_manifest_path(request.storage_root, completed_context.run_id)
    manifest_mod.write_run_manifest(manifest_path, manifest)
    return ResearchStageOutcome(
        run_id=completed_context.run_id,
        run_type=completed_context.run_type,
        status="materialized",
        config_hash=completed_context.config_hash,
        manifest_path=manifest_path,
    )


__all__ = ["ResearchStageOutcome", "ResearchStageRequest", "run_stage"]
