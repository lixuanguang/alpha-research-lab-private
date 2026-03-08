"""Unit tests for ingestion lineage persistence."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import alpha_core.storage.lineage as lineage


def test_start_run_persists_running_run(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    run = store.start_run(
        venue="Kalshi",
        connector_type="polling",
        options=lineage.StartRunOptions(
            event_types=["trades", "ohlcv"],
            config_snapshot={"mode": "poll"},
        ),
    )

    persisted = store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.status == "running"
    assert persisted.venue == "kalshi"
    assert persisted.event_types == ["trades", "ohlcv"]


def test_complete_run_sets_status_counts_and_completion_time(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")

    store.complete_run(run.run_id, counts={"trades_raw": 10, "rejected": 1}, errors=[])

    completed = store.get_run(run.run_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed_at is not None
    assert completed.counts["trades_raw"] == 10


def test_fail_run_appends_error_and_marks_failed(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("polymarket", "streaming")

    store.fail_run(run.run_id, "network timeout")

    failed = store.get_run(run.run_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.errors == ["network timeout"]
    assert failed.completed_at is not None


def test_list_runs_filters_by_venue_and_since(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    old_run = store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="old-run"),
    )
    store.start_run(
        "polymarket",
        "polling",
        options=lineage.StartRunOptions(run_id="pm-run"),
    )

    old_loaded = store.get_run(old_run.run_id)
    assert old_loaded is not None
    old_loaded = old_loaded.model_copy(
        update={"started_at": datetime.now(tz=UTC) - timedelta(days=10)}
    )
    (tmp_path / "_lineage" / "runs" / f"run_{old_loaded.run_id}.json").write_text(
        old_loaded.model_dump_json(indent=2),
        encoding="utf-8",
    )

    recent = store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="recent-run"),
    )

    filtered = store.list_runs(venue="kalshi", since=datetime.now(tz=UTC) - timedelta(days=1))

    assert [run.run_id for run in filtered] == [recent.run_id]


def test_unknown_run_transitions_raise_key_error(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    with pytest.raises(KeyError, match="Unknown run_id"):
        store.complete_run("missing", counts={}, errors=[])

    with pytest.raises(KeyError, match="Unknown run_id"):
        store.fail_run("missing", "error")


def test_terminal_runs_reject_additional_state_transitions(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    completed = store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="completed"),
    )
    store.complete_run(completed.run_id, counts={"trades_raw": 1}, errors=[])
    with pytest.raises(ValueError, match="terminal status"):
        store.fail_run(completed.run_id, "late error")

    failed = store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="failed"),
    )
    store.fail_run(failed.run_id, "first error")
    with pytest.raises(ValueError, match="terminal status"):
        store.complete_run(failed.run_id, counts={"trades_raw": 2}, errors=[])


def test_lineage_store_rejects_invalid_run_id_tokens(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    with pytest.raises(ValueError, match="unsupported characters"):
        store.start_run(
            "kalshi",
            "polling",
            options=lineage.StartRunOptions(run_id="../escape"),
        )

    with pytest.raises(ValueError, match="unsupported characters"):
        store.get_run("../escape")


def test_complete_run_rejects_negative_counts(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")

    with pytest.raises(ValueError, match="values must be >= 0"):
        store.complete_run(run.run_id, counts={"trades_raw": -1}, errors=[])


def test_start_run_copies_mutable_inputs(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    event_types = ["trades"]
    config_snapshot = {"poll_interval_seconds": 30}

    run = store.start_run(
        venue="kalshi",
        connector_type="polling",
        options=lineage.StartRunOptions(
            event_types=event_types,
            config_snapshot=config_snapshot,
        ),
    )

    event_types.append("ohlcv")
    config_snapshot["poll_interval_seconds"] = 60

    persisted = store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.event_types == ["trades"]
    assert persisted.config_snapshot == {"poll_interval_seconds": 30}


@pytest.mark.perf
def test_lineage_store_meets_d2_persist_and_query_target(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    start = time.perf_counter()
    for index in range(100):
        run = store.start_run(
            venue="kalshi",
            connector_type="polling",
            options=lineage.StartRunOptions(
                event_types=["trades"],
                run_id=f"perf-{index}",
            ),
        )
        store.complete_run(run.run_id, counts={"trades_raw": 1}, errors=[])
    runs = store.list_runs()
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(runs) == 100
    assert elapsed_ms < 100


# ---------------------------------------------------------------------------
# §12.1 — Ingestion Lineage → Research Run Bridge
# ---------------------------------------------------------------------------


def test_ingestion_run_parent_run_id_defaults_to_none(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")
    assert run.parent_run_id is None
    persisted = store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.parent_run_id is None


def test_start_run_propagates_parent_run_id(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    parent = store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="parent-1"),
    )
    store.complete_run(parent.run_id, counts={}, errors=[])

    child = store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="child-1", parent_run_id=parent.run_id),
    )

    assert child.parent_run_id == "parent-1"
    persisted = store.get_run(child.run_id)
    assert persisted is not None
    assert persisted.parent_run_id == "parent-1"


def test_ingestion_run_dataset_ready_defaults_to_false(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("polymarket", "polling")
    assert run.dataset_ready is False


def test_mark_dataset_ready_sets_flag(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")
    store.complete_run(run.run_id, counts={"trades": 10}, errors=[])

    store.mark_dataset_ready(run.run_id)

    persisted = store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.dataset_ready is True
    assert persisted.handoff_manifest_path is None


def test_mark_dataset_ready_stores_handoff_manifest_path(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")
    store.complete_run(run.run_id, counts={"trades": 50}, errors=[])
    manifest_path = str(tmp_path / "handoffs" / "20260308_kalshi.json")

    store.mark_dataset_ready(run.run_id, handoff_manifest_path=manifest_path)

    persisted = store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.dataset_ready is True
    assert persisted.handoff_manifest_path == manifest_path


def test_mark_dataset_ready_idempotent(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")
    store.complete_run(run.run_id, counts={}, errors=[])
    path_v1 = str(tmp_path / "v1.json")
    path_v2 = str(tmp_path / "v2.json")

    store.mark_dataset_ready(run.run_id, handoff_manifest_path=path_v1)
    store.mark_dataset_ready(run.run_id, handoff_manifest_path=path_v2)

    persisted = store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.dataset_ready is True
    # Second call overwrites the path — callers control this intentionally.
    assert persisted.handoff_manifest_path == path_v2


def test_mark_dataset_ready_rejects_running_run(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")

    with pytest.raises(ValueError, match="dataset-ready"):
        store.mark_dataset_ready(run.run_id)


def test_mark_dataset_ready_rejects_failed_run(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")
    store.fail_run(run.run_id, "connector error")

    with pytest.raises(ValueError, match="dataset-ready"):
        store.mark_dataset_ready(run.run_id)


def test_bidirectional_traceability_parent_and_downstream(tmp_path: Path) -> None:
    """Parent-child and downstream linkage interop."""
    store = lineage.LineageStore(tmp_path)

    # Upstream ingestion run
    ingestion = store.start_run(
        "kalshi", "polling", options=lineage.StartRunOptions(run_id="ingest-1")
    )
    store.complete_run(ingestion.run_id, counts={"trades": 100}, errors=[])

    # Downstream research run references the ingestion run as parent
    research = store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="research-1", parent_run_id="ingest-1"),
    )
    store.complete_run(research.run_id, counts={}, errors=[])

    # Register the linkage bidirectionally
    store.link_downstream_run("ingest-1", "research-1")

    ingestion_persisted = store.get_run("ingest-1")
    research_persisted = store.get_run("research-1")
    assert ingestion_persisted is not None
    assert research_persisted is not None
    assert "research-1" in ingestion_persisted.downstream_run_ids
    assert research_persisted.parent_run_id == "ingest-1"


def test_dataset_ready_and_handoff_path_survive_persistence_roundtrip(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("myriad", "streaming")
    store.complete_run(run.run_id, counts={"books": 200}, errors=[])
    handoff_path = "/data/handoffs/myriad_2026.json"

    store.mark_dataset_ready(run.run_id, handoff_manifest_path=handoff_path)

    # Re-instantiate the store to force a cold read from disk
    fresh_store = lineage.LineageStore(tmp_path)
    loaded = fresh_store.get_run(run.run_id)
    assert loaded is not None
    assert loaded.dataset_ready is True
    assert loaded.handoff_manifest_path == handoff_path
