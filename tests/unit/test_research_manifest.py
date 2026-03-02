"""Unit tests for research run-context and run-manifest contracts."""

from __future__ import annotations

from pathlib import Path

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod


def test_make_run_context_is_hash_stable() -> None:
    payload = {"name": "dataset_a", "start": "2024-01-01", "end": "2024-01-31"}
    left = run_context_mod.make_run_context("dataset_build", config_payload=payload)
    right = run_context_mod.make_run_context("dataset_build", config_payload=payload)

    assert left.config_hash == right.config_hash
    assert left.run_type == "dataset_build"


def test_run_manifest_roundtrip(tmp_path: Path) -> None:
    run = run_context_mod.make_run_context(
        "dataset_build",
        config_payload={"name": "dataset_roundtrip"},
    )
    completed = run_context_mod.close_run_context(run)

    manifest = manifest_mod.RunManifest(
        run=completed,
        dataset_id="abc123",
        artifacts={"dataset_meta": "data/gold/datasets/x/_meta.json"},
        parent_run_id=None,
    )

    path = artifact_paths.run_manifest_path(tmp_path, completed.run_id)
    manifest_mod.write_run_manifest(path, manifest)

    loaded = manifest_mod.read_run_manifest(path)
    assert loaded.dataset_id == "abc123"
    assert loaded.run.run_id == completed.run_id
    assert "dataset_meta" in loaded.artifacts
