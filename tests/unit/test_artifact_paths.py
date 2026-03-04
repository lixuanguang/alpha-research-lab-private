"""Unit tests for canonical run-artifact path helpers (LA-003 / 12.2)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import alpha_core.research.artifact_paths as ap
import alpha_core.storage.lineage as lineage_mod

RUN_ID = "abc123def456"


# ---------------------------------------------------------------------------
# Fixed-file path helpers — purity and layout
# ---------------------------------------------------------------------------


class TestFixedPaths:
    def test_run_root_layout(self, tmp_path: Path) -> None:
        root = ap.run_root(tmp_path, RUN_ID)
        assert root == tmp_path / "runs" / RUN_ID

    def test_manifest_path(self, tmp_path: Path) -> None:
        assert ap.run_manifest_path(tmp_path, RUN_ID) == (
            tmp_path / "runs" / RUN_ID / "manifest.json"
        )

    def test_config_path(self, tmp_path: Path) -> None:
        assert ap.run_config_path(tmp_path, RUN_ID) == tmp_path / "runs" / RUN_ID / "config.json"

    def test_artifacts_path(self, tmp_path: Path) -> None:
        assert ap.run_artifacts_path(tmp_path, RUN_ID) == (
            tmp_path / "runs" / RUN_ID / "artifacts.json"
        )

    def test_stage_outputs_path(self, tmp_path: Path) -> None:
        assert ap.stage_outputs_path(tmp_path, RUN_ID) == (
            tmp_path / "runs" / RUN_ID / "stage_outputs"
        )

    @pytest.mark.parametrize(
        "fn",
        [
            ap.run_manifest_path,
            ap.run_config_path,
            ap.run_artifacts_path,
            ap.stage_outputs_path,
        ],
    )
    def test_all_helpers_are_deterministic(
        self,
        tmp_path: Path,
        fn: Callable[[Path, str], Path],
    ) -> None:
        """Same inputs always produce the same path — no randomness."""
        assert fn(tmp_path, RUN_ID) == fn(tmp_path, RUN_ID)

    def test_different_run_ids_produce_different_roots(self, tmp_path: Path) -> None:
        assert ap.run_root(tmp_path, "run_a") != ap.run_root(tmp_path, "run_b")


# ---------------------------------------------------------------------------
# artifact_key_path — determinism and validation
# ---------------------------------------------------------------------------


class TestArtifactKeyPath:
    def test_simple_key(self, tmp_path: Path) -> None:
        path = ap.artifact_key_path(tmp_path, RUN_ID, "output.parquet")
        assert path == tmp_path / "runs" / RUN_ID / "stage_outputs" / "output.parquet"

    def test_subdir_key(self, tmp_path: Path) -> None:
        path = ap.artifact_key_path(tmp_path, RUN_ID, "features/v2/out.parquet")
        assert path == (
            tmp_path / "runs" / RUN_ID / "stage_outputs" / "features" / "v2" / "out.parquet"
        )

    def test_deterministic_for_same_inputs(self, tmp_path: Path) -> None:
        p1 = ap.artifact_key_path(tmp_path, RUN_ID, "metrics.json")
        p2 = ap.artifact_key_path(tmp_path, RUN_ID, "metrics.json")
        assert p1 == p2

    def test_different_keys_produce_different_paths(self, tmp_path: Path) -> None:
        assert ap.artifact_key_path(tmp_path, RUN_ID, "a.parquet") != ap.artifact_key_path(
            tmp_path, RUN_ID, "b.parquet"
        )

    def test_empty_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            ap.artifact_key_path(tmp_path, RUN_ID, "")

    def test_absolute_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="relative"):
            ap.artifact_key_path(tmp_path, RUN_ID, "/etc/passwd")

    def test_traversal_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="'\\.\\.'"):
            ap.artifact_key_path(tmp_path, RUN_ID, "../../secrets")

    def test_traversal_in_subpath_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="'\\.\\.'"):
            ap.artifact_key_path(tmp_path, RUN_ID, "features/../../../secrets")


# ---------------------------------------------------------------------------
# write_artifacts_index / read_artifacts_index
# ---------------------------------------------------------------------------


class TestArtifactsIndex:
    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        artifacts = {
            "dataset_meta": "/data/gold/datasets/ds/_meta.json",
            "universe": "/data/gold/datasets/ds/universe.parquet",
        }
        ap.write_artifacts_index(tmp_path, RUN_ID, artifacts)
        loaded = ap.read_artifacts_index(tmp_path, RUN_ID)
        assert loaded == artifacts

    def test_read_missing_returns_empty_dict(self, tmp_path: Path) -> None:
        result = ap.read_artifacts_index(tmp_path, "nonexistent_run")
        assert result == {}

    def test_write_creates_parent_directories(self, tmp_path: Path) -> None:
        nested_root = tmp_path / "deep" / "nested"
        ap.write_artifacts_index(nested_root, RUN_ID, {"k": "v"})
        assert ap.run_artifacts_path(nested_root, RUN_ID).exists()

    def test_write_is_atomic_on_overwrite(self, tmp_path: Path) -> None:
        ap.write_artifacts_index(tmp_path, RUN_ID, {"k": "v1"})
        ap.write_artifacts_index(tmp_path, RUN_ID, {"k": "v2"})
        assert ap.read_artifacts_index(tmp_path, RUN_ID) == {"k": "v2"}

    def test_keys_are_sorted_in_written_json(self, tmp_path: Path) -> None:
        ap.write_artifacts_index(tmp_path, RUN_ID, {"z": "last", "a": "first"})
        raw = ap.run_artifacts_path(tmp_path, RUN_ID).read_text(encoding="utf-8")
        keys = list(json.loads(raw).keys())
        assert keys == sorted(keys)

    def test_empty_artifacts_roundtrip(self, tmp_path: Path) -> None:
        ap.write_artifacts_index(tmp_path, RUN_ID, {})
        assert ap.read_artifacts_index(tmp_path, RUN_ID) == {}


# ---------------------------------------------------------------------------
# Lineage bridge — downstream_run_ids + link_downstream_run
# ---------------------------------------------------------------------------


class TestLineageBridge:
    def test_ingestion_run_has_empty_downstream_run_ids_by_default(self, tmp_path: Path) -> None:
        store = lineage_mod.LineageStore(tmp_path)
        run = store.start_run("kalshi", "polling")
        assert run.downstream_run_ids == []

    def test_link_downstream_run_registers_entry(self, tmp_path: Path) -> None:
        store = lineage_mod.LineageStore(tmp_path)
        ingestion = store.start_run("kalshi", "polling")
        store.link_downstream_run(ingestion.run_id, "research_run_abc")

        updated = store.get_run(ingestion.run_id)
        assert updated is not None
        assert "research_run_abc" in updated.downstream_run_ids

    def test_link_downstream_run_is_idempotent(self, tmp_path: Path) -> None:
        store = lineage_mod.LineageStore(tmp_path)
        ingestion = store.start_run("kalshi", "polling")
        store.link_downstream_run(ingestion.run_id, "ds_run_1")
        store.link_downstream_run(ingestion.run_id, "ds_run_1")  # duplicate call

        updated = store.get_run(ingestion.run_id)
        assert updated is not None
        assert updated.downstream_run_ids.count("ds_run_1") == 1

    def test_link_downstream_run_accumulates_multiple_ids(self, tmp_path: Path) -> None:
        store = lineage_mod.LineageStore(tmp_path)
        ingestion = store.start_run("polymarket", "streaming")
        store.link_downstream_run(ingestion.run_id, "ds_run_1")
        store.link_downstream_run(ingestion.run_id, "feature_run_2")

        updated = store.get_run(ingestion.run_id)
        assert updated is not None
        assert set(updated.downstream_run_ids) == {"ds_run_1", "feature_run_2"}

    def test_link_unknown_ingestion_run_raises_key_error(self, tmp_path: Path) -> None:
        store = lineage_mod.LineageStore(tmp_path)
        with pytest.raises(KeyError, match="nonexistent"):
            store.link_downstream_run("nonexistent", "some_research_run")

    def test_backward_compat_old_json_without_downstream_field(self, tmp_path: Path) -> None:
        """IngestionRun JSON without downstream_run_ids must load cleanly."""
        store = lineage_mod.LineageStore(tmp_path)
        run = store.start_run("kalshi", "polling")

        # Simulate an old JSON file that predates the downstream_run_ids field
        run_path = tmp_path / "_lineage" / "runs" / f"run_{run.run_id}.json"
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        del payload["downstream_run_ids"]
        run_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        loaded = store.get_run(run.run_id)
        assert loaded is not None
        assert loaded.downstream_run_ids == []
