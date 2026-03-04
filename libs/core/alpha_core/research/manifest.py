"""Cross-stage run manifest contracts for artifact lineage."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

import alpha_core.research.run_context as run_context_mod


class RunManifest(BaseModel):
    """Persistent run manifest linking a RunContext to its stage outputs.

    Stage-specific metadata (dataset IDs, feature set versions, etc.) should be
    stored as entries in *artifacts* rather than as top-level fields so that this
    contract stays stable across all pipeline stages.
    """

    model_config = ConfigDict(extra="forbid")

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


__all__ = ["RunManifest", "read_run_manifest", "write_run_manifest"]
