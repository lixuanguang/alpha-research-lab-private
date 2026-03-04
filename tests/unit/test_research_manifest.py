"""Unit tests for cross-stage run-context and run-manifest contracts (LA-002)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
from alpha_core.research.run_context import RunType


# ---------------------------------------------------------------------------
# RunType coverage
# ---------------------------------------------------------------------------

ALL_RUN_TYPES: list[RunType] = [
    "ingestion",
    "dataset_build",
    "feature_build",
    "backtest",
    "evaluate",
    "optimize",
    "live",
]


@pytest.mark.parametrize("run_type", ALL_RUN_TYPES)
def test_make_run_context_all_types(run_type: RunType) -> None:
    """Every valid run_type produces a consistent, hash-stable RunContext."""
    payload = {"stage": run_type, "version": "1"}
    ctx_a = run_context_mod.make_run_context(run_type, config_payload=payload)
    ctx_b = run_context_mod.make_run_context(run_type, config_payload=payload)

    assert ctx_a.run_type == run_type
    assert ctx_a.config_hash == ctx_b.config_hash  # deterministic hash
    assert ctx_a.run_id != ctx_b.run_id             # unique IDs per call
    assert ctx_a.completed_at_utc is None           # open on creation


def test_make_run_context_config_hash_stability() -> None:
    """Same payload always produces the same config hash."""
    payload = {"name": "dataset_a", "start": "2024-01-01", "end": "2024-01-31"}
    left = run_context_mod.make_run_context("dataset_build", config_payload=payload)
    right = run_context_mod.make_run_context("dataset_build", config_payload=payload)
    assert left.config_hash == right.config_hash


def test_close_run_context_sets_completed_at() -> None:
    ctx = run_context_mod.make_run_context("backtest", config_payload={"v": 1})
    completed = run_context_mod.close_run_context(ctx)
    assert completed.completed_at_utc is not None
    assert completed.run_id == ctx.run_id
    assert completed.run_type == ctx.run_type


# ---------------------------------------------------------------------------
# capture_git_commit
# ---------------------------------------------------------------------------

def test_capture_git_commit_returns_string_or_none() -> None:
    """Result is either a non-empty string or None — never raises."""
    result = run_context_mod.capture_git_commit()
    assert result is None or (isinstance(result, str) and len(result) > 0)


def test_capture_git_commit_graceful_on_failure() -> None:
    """Returns None when git is unavailable rather than propagating the error."""
    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        result = run_context_mod.capture_git_commit()
    assert result is None


def test_make_run_context_auto_captures_git_commit() -> None:
    """make_run_context populates git_commit automatically when not supplied."""
    with patch("alpha_core.research.run_context.capture_git_commit", return_value="abc1234"):
        ctx = run_context_mod.make_run_context("live", config_payload={})
    assert ctx.git_commit == "abc1234"


def test_make_run_context_explicit_git_commit_not_overridden() -> None:
    """An explicitly passed git_commit is used as-is without calling capture."""
    with patch("alpha_core.research.run_context.capture_git_commit") as mock_capture:
        ctx = run_context_mod.make_run_context(
            "optimize", config_payload={}, git_commit="deadbeef"
        )
    mock_capture.assert_not_called()
    assert ctx.git_commit == "deadbeef"


# ---------------------------------------------------------------------------
# RunManifest — spec-minimal contract
# ---------------------------------------------------------------------------

def test_run_manifest_roundtrip(tmp_path: Path) -> None:
    """RunManifest write → read round-trip preserves all fields exactly."""
    run = run_context_mod.make_run_context(
        "dataset_build",
        config_payload={"name": "dataset_roundtrip"},
    )
    completed = run_context_mod.close_run_context(run)

    manifest = manifest_mod.RunManifest(
        run=completed,
        artifacts={"dataset_meta": "data/gold/datasets/x/_meta.json"},
        parent_run_id=None,
    )

    path = artifact_paths.run_manifest_path(tmp_path, completed.run_id)
    manifest_mod.write_run_manifest(path, manifest)

    loaded = manifest_mod.read_run_manifest(path)
    assert loaded.run.run_id == completed.run_id
    assert loaded.run.run_type == "dataset_build"
    assert "dataset_meta" in loaded.artifacts
    assert loaded.parent_run_id is None


def test_run_manifest_with_parent_run_id(tmp_path: Path) -> None:
    """parent_run_id links downstream manifests to their upstream run."""
    parent = run_context_mod.make_run_context("ingestion", config_payload={"v": 1})
    child = run_context_mod.make_run_context("dataset_build", config_payload={"v": 2})
    completed_child = run_context_mod.close_run_context(child)

    manifest = manifest_mod.RunManifest(
        run=completed_child,
        artifacts={"output": "data/gold/runs/x/out.parquet"},
        parent_run_id=parent.run_id,
    )
    path = artifact_paths.run_manifest_path(tmp_path, completed_child.run_id)
    manifest_mod.write_run_manifest(path, manifest)

    loaded = manifest_mod.read_run_manifest(path)
    assert loaded.parent_run_id == parent.run_id


def test_run_manifest_rejects_unknown_fields() -> None:
    """extra='forbid' ensures forward-compat — unknown keys raise ValidationError."""
    from pydantic import ValidationError

    run = run_context_mod.make_run_context("backtest", config_payload={})
    completed = run_context_mod.close_run_context(run)

    with pytest.raises(ValidationError):
        manifest_mod.RunManifest(
            run=completed,
            artifacts={},
            parent_run_id=None,
            unknown_field="oops",  # type: ignore[call-arg]
        )


@pytest.mark.parametrize("run_type", ALL_RUN_TYPES)
def test_run_manifest_accepts_all_run_types(run_type: RunType, tmp_path: Path) -> None:
    """RunManifest is valid for every pipeline stage run_type."""
    ctx = run_context_mod.make_run_context(run_type, config_payload={"stage": run_type})
    completed = run_context_mod.close_run_context(ctx)
    manifest = manifest_mod.RunManifest(run=completed, artifacts={})
    path = artifact_paths.run_manifest_path(tmp_path, completed.run_id)
    manifest_mod.write_run_manifest(path, manifest)
    loaded = manifest_mod.read_run_manifest(path)
    assert loaded.run.run_type == run_type
