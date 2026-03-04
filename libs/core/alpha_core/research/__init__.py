"""Research-plane components: run contracts, gold dataset assembly, point-in-time universe management."""

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.as_of as as_of
import alpha_core.research.dataset as dataset
import alpha_core.research.dataset_builder as dataset_builder
import alpha_core.research.manifest as manifest
import alpha_core.research.run_context as run_context
import alpha_core.research.universe as universe
from alpha_core.research.artifact_paths import (
    artifact_key_path,
    read_artifacts_index,
    run_artifacts_path,
    run_config_path,
    run_manifest_path,
    run_root,
    stage_outputs_path,
    write_artifacts_index,
)
from alpha_core.research.run_context import (
    RunContext,
    RunType,
    capture_git_commit,
    close_run_context,
    make_run_context,
)

__all__ = [
    # sub-modules (for `alpha_core.research.<module>.<symbol>` access)
    "artifact_paths",
    "as_of",
    "dataset",
    "dataset_builder",
    "manifest",
    "run_context",
    "universe",
    # convenience flat exports — run contracts
    "RunContext",
    "RunManifest",
    "RunType",
    "capture_git_commit",
    "close_run_context",
    "make_run_context",
    "read_run_manifest",
    "write_run_manifest",
    # convenience flat exports — artifact paths
    "artifact_key_path",
    "read_artifacts_index",
    "run_artifacts_path",
    "run_config_path",
    "run_manifest_path",
    "run_root",
    "stage_outputs_path",
    "write_artifacts_index",
]
