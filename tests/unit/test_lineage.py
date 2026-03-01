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
        event_types=["trades", "ohlcv"],
        config_snapshot={"mode": "poll"},
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
    old_run = store.start_run("kalshi", "polling", run_id="old-run")
    store.start_run("polymarket", "polling", run_id="pm-run")

    old_loaded = store.get_run(old_run.run_id)
    assert old_loaded is not None
    old_loaded = old_loaded.model_copy(
        update={"started_at": datetime.now(tz=UTC) - timedelta(days=10)}
    )
    (tmp_path / "_lineage" / "runs" / f"run_{old_loaded.run_id}.json").write_text(
        old_loaded.model_dump_json(indent=2),
        encoding="utf-8",
    )

    recent = store.start_run("kalshi", "polling", run_id="recent-run")

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

    completed = store.start_run("kalshi", "polling", run_id="completed")
    store.complete_run(completed.run_id, counts={"trades_raw": 1}, errors=[])
    with pytest.raises(ValueError, match="terminal status"):
        store.fail_run(completed.run_id, "late error")

    failed = store.start_run("kalshi", "polling", run_id="failed")
    store.fail_run(failed.run_id, "first error")
    with pytest.raises(ValueError, match="terminal status"):
        store.complete_run(failed.run_id, counts={"trades_raw": 2}, errors=[])


def test_lineage_store_rejects_invalid_run_id_tokens(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    with pytest.raises(ValueError, match="unsupported characters"):
        store.start_run("kalshi", "polling", run_id="../escape")

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
        event_types=event_types,
        config_snapshot=config_snapshot,
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
            event_types=["trades"],
            run_id=f"perf-{index}",
        )
        store.complete_run(run.run_id, counts={"trades_raw": 1}, errors=[])
    runs = store.list_runs()
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(runs) == 100
    assert elapsed_ms < 100
