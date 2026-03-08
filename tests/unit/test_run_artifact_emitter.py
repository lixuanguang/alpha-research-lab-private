"""Unit tests for §12.3 — Run Artifact Compatibility with Research CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.storage.lineage as lineage
import alpha_core.storage.run_artifact_emitter as emitter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _complete_run(
    store: lineage.LineageStore,
    *,
    run_id: str = "test-run-001",
    venue: str = "kalshi",
    event_types: list[str] | None = None,
    config_snapshot: dict[str, object] | None = None,
    parent_run_id: str | None = None,
) -> lineage.IngestionRun:
    """Start + immediately complete a run and return the completed IngestionRun."""
    opts = lineage.StartRunOptions(
        run_id=run_id,
        event_types=event_types or ["trades"],
        config_snapshot=config_snapshot or {"venue": venue, "mode": "poll"},
        parent_run_id=parent_run_id,
    )
    run = store.start_run(venue, "polling", options=opts)
    store.complete_run(
        run.run_id,
        counts={"trades": 100},
        errors=[],
    )
    completed = store.get_run(run.run_id)
    assert completed is not None
    return completed


# ---------------------------------------------------------------------------
# emit_ingestion_run_artifacts — file creation
# ---------------------------------------------------------------------------


def test_emitter_creates_manifest_json(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-emit-001")

    result = emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    assert result.manifest_path.exists()
    assert result.manifest_path == tmp_path / "runs" / run.run_id / "manifest.json"


def test_emitter_creates_config_json(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-emit-002", config_snapshot={"mode": "poll", "v": 1})

    result = emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    assert result.config_path.exists()
    payload = json.loads(result.config_path.read_text())
    assert payload["mode"] == "poll"
    assert payload["v"] == 1


def test_emitter_creates_artifacts_json(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-emit-003")

    result = emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    assert result.artifacts_path.exists()


# ---------------------------------------------------------------------------
# Manifest content
# ---------------------------------------------------------------------------


def test_manifest_run_type_is_ingestion(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-type-001")

    emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.run.run_type == "ingestion"


def test_manifest_run_id_matches_ingestion_run(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-id-match-001")

    emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.run.run_id == run.run_id


def test_manifest_has_lineage_artifact(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-lineage-art-001")

    emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert "lineage" in manifest.artifacts
    # The lineage file exists at the standard path
    assert Path(manifest.artifacts["lineage"]).exists()


def test_manifest_has_config_artifact(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-config-art-001")

    emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert "config" in manifest.artifacts
    assert Path(manifest.artifacts["config"]).exists()


def test_manifest_parent_run_id_propagates(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    parent = _complete_run(store, run_id="parent-run-001")
    child = _complete_run(store, run_id="child-run-001", parent_run_id=parent.run_id)

    emitter.emit_ingestion_run_artifacts(ingestion_run=child, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, child.run_id)
    )
    assert manifest.parent_run_id == parent.run_id


def test_manifest_parent_run_id_is_none_when_unset(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="no-parent-001")

    emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.parent_run_id is None


def test_manifest_schema_version_is_current(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="schema-ver-001")

    emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.schema_version == manifest_mod.RUN_MANIFEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Partition refs
# ---------------------------------------------------------------------------


def test_partition_refs_appear_in_manifest(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-partref-001", event_types=["trades"])
    refs = {"silver_trades": "silver/trades/venue=kalshi/date=2026-03-01"}

    emitter.emit_ingestion_run_artifacts(
        ingestion_run=run, storage_root=tmp_path, partition_refs=refs
    )

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.artifacts["silver_trades"] == "silver/trades/venue=kalshi/date=2026-03-01"


def test_multiple_partition_refs(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-multiref-001", event_types=["trades", "ohlcv"])
    refs = {
        "silver_trades": "silver/trades/venue=kalshi/date=2026-03-01",
        "silver_ohlcv": "silver/ohlcv/venue=kalshi/resolution=1h/date=2026-03-01",
    }

    result = emitter.emit_ingestion_run_artifacts(
        ingestion_run=run, storage_root=tmp_path, partition_refs=refs
    )

    assert "silver_trades" in result.artifact_keys
    assert "silver_ohlcv" in result.artifact_keys

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.artifacts["silver_trades"] == refs["silver_trades"]
    assert manifest.artifacts["silver_ohlcv"] == refs["silver_ohlcv"]


def test_no_partition_refs_is_fine(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-noref-001")

    result = emitter.emit_ingestion_run_artifacts(
        ingestion_run=run, storage_root=tmp_path, partition_refs=None
    )

    assert "lineage" in result.artifact_keys
    assert "config" in result.artifact_keys


# ---------------------------------------------------------------------------
# Handoff manifest artifact
# ---------------------------------------------------------------------------


def test_handoff_manifest_artifact_included_when_set(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-hm-001")
    # Simulate mark_dataset_ready setting the path
    fake_hm_path = str(tmp_path / "_lineage" / "handoffs" / "hm-001.json")
    store.mark_dataset_ready(run.run_id, handoff_manifest_path=fake_hm_path)
    updated = store.get_run(run.run_id)
    assert updated is not None

    emitter.emit_ingestion_run_artifacts(ingestion_run=updated, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.artifacts["handoff_manifest"] == fake_hm_path


def test_no_handoff_manifest_key_when_not_set(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-nohm-001")

    emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert "handoff_manifest" not in manifest.artifacts


# ---------------------------------------------------------------------------
# Extra artifacts
# ---------------------------------------------------------------------------


def test_extra_artifacts_appear_in_index(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-extra-001")
    extras = {"replay_package": "/data/_lineage/replay/pkg-abc.json"}

    result = emitter.emit_ingestion_run_artifacts(
        ingestion_run=run, storage_root=tmp_path, extra_artifacts=extras
    )

    assert "replay_package" in result.artifact_keys

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.artifacts["replay_package"] == "/data/_lineage/replay/pkg-abc.json"


def test_extra_artifacts_override_partition_refs_on_key_collision(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-override-001")
    refs = {"silver_trades": "silver/trades/venue=kalshi/date=2026-03-01"}
    extras = {"silver_trades": "silver/trades/venue=kalshi/date=2026-03-02"}

    emitter.emit_ingestion_run_artifacts(
        ingestion_run=run,
        storage_root=tmp_path,
        partition_refs=refs,
        extra_artifacts=extras,
    )

    manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, run.run_id)
    )
    assert manifest.artifacts["silver_trades"] == "silver/trades/venue=kalshi/date=2026-03-02"


# ---------------------------------------------------------------------------
# Guard: non-completed runs are rejected
# ---------------------------------------------------------------------------


def test_raises_for_running_run(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    opts = lineage.StartRunOptions(run_id="run-still-running", event_types=["trades"])
    run = store.start_run("kalshi", "polling", options=opts)

    with pytest.raises(ValueError, match="must be completed"):
        emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)


def test_raises_for_failed_run(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    opts = lineage.StartRunOptions(run_id="run-failed-001", event_types=["trades"])
    run = store.start_run("kalshi", "polling", options=opts)
    store.fail_run(run.run_id, "connector error")
    failed = store.get_run(run.run_id)
    assert failed is not None

    with pytest.raises(ValueError, match="must be completed"):
        emitter.emit_ingestion_run_artifacts(ingestion_run=failed, storage_root=tmp_path)


# ---------------------------------------------------------------------------
# IngestionArtifactEmission fields
# ---------------------------------------------------------------------------


def test_emission_run_id_matches(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-emission-001")

    result = emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    assert result.run_id == run.run_id


def test_emission_artifact_keys_always_includes_config_and_lineage(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-keys-001")

    result = emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    assert "config" in result.artifact_keys
    assert "lineage" in result.artifact_keys


# ---------------------------------------------------------------------------
# Idempotency — re-emit produces same manifest
# ---------------------------------------------------------------------------


def test_re_emit_is_idempotent(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-idem-001")

    result1 = emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)
    result2 = emitter.emit_ingestion_run_artifacts(ingestion_run=run, storage_root=tmp_path)

    m1 = manifest_mod.read_run_manifest(result1.manifest_path)
    m2 = manifest_mod.read_run_manifest(result2.manifest_path)
    assert m1.run.run_id == m2.run.run_id
    assert m1.run.config_hash == m2.run.config_hash
    assert m1.artifacts == m2.artifacts


# ---------------------------------------------------------------------------
# Research CLI readability — artifacts.json round-trip
# ---------------------------------------------------------------------------


def test_artifacts_json_is_readable_by_read_artifacts_index(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = _complete_run(store, run_id="run-artidx-001")
    refs = {"silver_trades": "silver/trades/venue=kalshi/date=2026-03-01"}

    emitter.emit_ingestion_run_artifacts(
        ingestion_run=run, storage_root=tmp_path, partition_refs=refs
    )

    index = artifact_paths.read_artifacts_index(tmp_path, run.run_id)
    assert "config" in index
    assert "lineage" in index
    assert "silver_trades" in index
    assert index["silver_trades"] == "silver/trades/venue=kalshi/date=2026-03-01"


# ---------------------------------------------------------------------------
# Full end-to-end integration
# ---------------------------------------------------------------------------


def test_full_ingestion_to_research_cli_flow(tmp_path: Path) -> None:
    """Simulate complete flow: ingest → quality gate → handoff → emit artifacts."""
    store = lineage.LineageStore(tmp_path)

    # 1. Run ingestion
    run = _complete_run(
        store,
        run_id="e2e-ingest-001",
        venue="polymarket",
        event_types=["trades"],
        config_snapshot={"venue": "polymarket", "mode": "poll", "batch_size": 500},
    )

    # 2. Mark dataset ready (simulating §12.2 handoff)
    fake_hm = str(tmp_path / "_lineage" / "handoffs" / "hm-e2e.json")
    store.mark_dataset_ready(run.run_id, handoff_manifest_path=fake_hm)
    ready_run = store.get_run(run.run_id)
    assert ready_run is not None
    assert ready_run.dataset_ready is True

    # 3. Emit Research-CLI-compatible artifacts
    result = emitter.emit_ingestion_run_artifacts(
        ingestion_run=ready_run,
        storage_root=tmp_path,
        partition_refs={"silver_trades": "silver/trades/venue=polymarket/date=2026-03-01"},
        extra_artifacts={"replay_package": "/data/_lineage/replay/replay-e2e.json"},
    )

    # 4. Research CLI can read the manifest
    manifest = manifest_mod.read_run_manifest(result.manifest_path)
    assert manifest.run.run_id == "e2e-ingest-001"
    assert manifest.run.run_type == "ingestion"
    assert manifest.artifacts["handoff_manifest"] == fake_hm
    assert manifest.artifacts["silver_trades"] == "silver/trades/venue=polymarket/date=2026-03-01"
    assert manifest.artifacts["replay_package"] == "/data/_lineage/replay/replay-e2e.json"
    assert manifest.parent_run_id is None

    # 5. artifacts.json is also readable
    index = artifact_paths.read_artifacts_index(tmp_path, run.run_id)
    assert set(index.keys()) >= {"config", "lineage", "handoff_manifest", "silver_trades"}
