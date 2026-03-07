"""Unit tests for cross-stage run-context and run-manifest contracts (LA-002)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod
import alpha_core.research.session as session_mod
import alpha_core.storage.lineage as lineage_mod

# ---------------------------------------------------------------------------
# RunType coverage
# ---------------------------------------------------------------------------

ALL_RUN_TYPES: list[run_context_mod.RunType] = [
    "ingestion",
    "dataset_build",
    "feature_build",
    "backtest",
    "evaluate",
    "report",
    "optimize",
    "live",
]


@pytest.mark.parametrize("run_type", ALL_RUN_TYPES)
def test_make_run_context_all_types(run_type: run_context_mod.RunType) -> None:
    """Every valid run_type produces a consistent, hash-stable RunContext."""
    payload = {"stage": run_type, "version": "1"}
    ctx_a = run_context_mod.make_run_context(run_type, config_payload=payload)
    ctx_b = run_context_mod.make_run_context(run_type, config_payload=payload)

    assert ctx_a.run_type == run_type
    assert ctx_a.config_hash == ctx_b.config_hash  # deterministic hash
    assert ctx_a.run_id != ctx_b.run_id  # unique IDs per call
    assert ctx_a.completed_at_utc is None  # open on creation


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


def test_make_run_context_records_session_id() -> None:
    ctx = run_context_mod.make_run_context(
        "backtest",
        config_payload={"v": 1},
        session_id=" session_001 ",
    )
    assert ctx.session_id == "session_001"


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
        ctx = run_context_mod.make_run_context("optimize", config_payload={}, git_commit="deadbeef")
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
def test_run_manifest_accepts_all_run_types(
    run_type: run_context_mod.RunType,
    tmp_path: Path,
) -> None:
    """RunManifest is valid for every pipeline stage run_type."""
    ctx = run_context_mod.make_run_context(run_type, config_payload={"stage": run_type})
    completed = run_context_mod.close_run_context(ctx)
    manifest = manifest_mod.RunManifest(run=completed, artifacts={})
    path = artifact_paths.run_manifest_path(tmp_path, completed.run_id)
    manifest_mod.write_run_manifest(path, manifest)
    loaded = manifest_mod.read_run_manifest(path)
    assert loaded.run.run_type == run_type


# ---------------------------------------------------------------------------
# Missing required fields — acceptance criterion: clear error messages
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    """Pydantic must reject manifests and contexts with missing required fields."""

    def test_run_context_missing_run_id_fails(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="run_id"):
            run_context_mod.RunContext(  # type: ignore[call-arg]
                run_type="backtest",
                config_hash="abc",
                started_at_utc="2024-01-01T00:00:00Z",
            )

    def test_run_context_missing_run_type_fails(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="run_type"):
            run_context_mod.RunContext(  # type: ignore[call-arg]
                run_id="abc123",
                config_hash="abc",
                started_at_utc="2024-01-01T00:00:00Z",
            )

    def test_run_context_missing_config_hash_fails(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="config_hash"):
            run_context_mod.RunContext(  # type: ignore[call-arg]
                run_id="abc123",
                run_type="backtest",
                started_at_utc="2024-01-01T00:00:00Z",
            )

    def test_run_manifest_missing_run_fails(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="run"):
            manifest_mod.RunManifest(artifacts={})  # type: ignore[call-arg]

    def test_run_manifest_missing_artifacts_fails(self) -> None:
        from pydantic import ValidationError

        ctx = run_context_mod.make_run_context("evaluate", config_payload={})
        completed = run_context_mod.close_run_context(ctx)
        with pytest.raises(ValidationError, match="artifacts"):
            manifest_mod.RunManifest(run=completed)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Config hash — key-ordering stability
# ---------------------------------------------------------------------------


def test_config_hash_stable_across_key_ordering() -> None:
    """config_hash is identical regardless of dict key insertion order."""
    payload_a = {"z": 1, "a": 2, "m": 3}
    payload_b = {"a": 2, "m": 3, "z": 1}
    ctx_a = run_context_mod.make_run_context("optimize", config_payload=payload_a)
    ctx_b = run_context_mod.make_run_context("optimize", config_payload=payload_b)
    assert ctx_a.config_hash == ctx_b.config_hash


def test_config_hash_differs_for_different_payloads() -> None:
    """Different payloads always produce different hashes."""
    ctx_a = run_context_mod.make_run_context("live", config_payload={"x": 1})
    ctx_b = run_context_mod.make_run_context("live", config_payload={"x": 2})
    assert ctx_a.config_hash != ctx_b.config_hash


# ---------------------------------------------------------------------------
# README.LEAN_ADOPTION required fields coverage
# ---------------------------------------------------------------------------


def test_manifest_exposes_all_lean_adoption_required_fields() -> None:
    """Every field listed in README.LEAN_ADOPTION §3.2 is reachable on the manifest."""
    ctx = run_context_mod.make_run_context(
        "backtest",
        config_payload={"strategy_version": "v1", "dataset_id": "ds_abc"},
    )
    completed = run_context_mod.close_run_context(ctx)
    m = manifest_mod.RunManifest(
        run=completed,
        artifacts={
            "dataset_id": "ds_abc",
            "feature_set_version": "fv1",
            "strategy_version": "v1",
        },
    )

    # Top-level RunContext fields
    assert m.run.run_id
    assert m.run.run_type == "backtest"
    assert m.run.config_hash
    assert m.run.started_at_utc is not None
    assert m.run.completed_at_utc is not None
    # Stage-specific fields surfaced via artifacts dict
    assert m.artifacts["dataset_id"] == "ds_abc"
    assert m.artifacts["feature_set_version"] == "fv1"
    assert m.artifacts["strategy_version"] == "v1"


def test_persist_run_record_links_parent_ingestion_run(tmp_path: Path) -> None:
    store = lineage_mod.LineageStore(tmp_path)
    ingestion = store.start_run("kalshi", "polling")
    run_context = run_context_mod.close_run_context(
        run_context_mod.make_run_context("dataset_build", config_payload={"name": "linked"})
    )

    manifest_mod.persist_run_record(
        storage_root=tmp_path,
        run_context=run_context,
        config_payload={"name": "linked"},
        artifacts={"dataset_id": "abc123"},
        parent_run_id=ingestion.run_id,
    )

    updated_ingestion = store.get_run(ingestion.run_id)
    assert updated_ingestion is not None
    assert run_context.run_id in updated_ingestion.downstream_run_ids


def test_persist_run_record_links_run_into_session(tmp_path: Path) -> None:
    run_context = run_context_mod.close_run_context(
        run_context_mod.make_run_context(
            "feature_build",
            config_payload={"dataset_id": "ds_001"},
            session_id="session_123",
        )
    )

    manifest_mod.persist_run_record(
        storage_root=tmp_path,
        run_context=run_context,
        config_payload={"dataset_id": "ds_001"},
        artifacts={"features": "data/runs/r1/stage_outputs/features.parquet"},
        parent_run_id=None,
    )

    stored_session = session_mod.load_session(tmp_path, "session_123")
    assert stored_session.run_ids == [run_context.run_id]


def test_run_manifest_roundtrip_preserves_session_id(tmp_path: Path) -> None:
    run = run_context_mod.make_run_context(
        "evaluate",
        config_payload={"metric": "sharpe_ratio"},
        session_id="session_abc",
    )
    completed = run_context_mod.close_run_context(run)
    manifest = manifest_mod.RunManifest(
        run=completed,
        artifacts={"metrics_json": "data/runs/r1/stage_outputs/metrics.json"},
    )

    path = artifact_paths.run_manifest_path(tmp_path, completed.run_id)
    manifest_mod.write_run_manifest(path, manifest)

    loaded = manifest_mod.read_run_manifest(path)
    assert loaded.run.session_id == "session_abc"
