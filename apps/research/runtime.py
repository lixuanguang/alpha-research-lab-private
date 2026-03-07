"""Research runtime scaffolding for stage-aligned run manifests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod


@dataclass(slots=True, frozen=True)
class ResearchStageOutcome:
    run_id: str
    run_type: run_context_mod.RunType
    status: str
    config_hash: str
    manifest_path: Path | None = None


def run_stage(
    *,
    run_type: run_context_mod.RunType,
    payload: dict[str, Any],
    storage_root: Path,
    execute: bool,
    parent_run_id: str | None = None,
) -> ResearchStageOutcome:
    run_context = run_context_mod.make_run_context(
        run_type,
        config_payload=payload,
    )
    completed_context = run_context
    manifest_path: Path | None = None
    status = "planned"
    if execute:
        completed_context = run_context_mod.close_run_context(run_context)
        manifest_mod.persist_run_record(
            storage_root=storage_root,
            run_context=completed_context,
            config_payload=payload,
            artifacts={},
            parent_run_id=parent_run_id,
        )
        manifest_path = artifact_paths.run_manifest_path(
            storage_root,
            completed_context.run_id,
        )
        status = "materialized"
    return ResearchStageOutcome(
        run_id=completed_context.run_id,
        run_type=completed_context.run_type,
        status=status,
        config_hash=completed_context.config_hash,
        manifest_path=manifest_path,
    )


__all__ = ["ResearchStageOutcome", "run_stage"]
