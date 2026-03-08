"""Unit tests for §12.2 — Dataset-Ready Handoff Contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import alpha_core.storage.handoff_manifest as handoff
import alpha_core.storage.lineage as lineage

_TS = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
_TS_END = _TS + timedelta(days=1)


# ---------------------------------------------------------------------------
# Lightweight stubs for duck-typed gating inputs
# ---------------------------------------------------------------------------


@dataclass
class _StubRun:
    run_id: str
    status: str
    cursor_watermark_utc: datetime | None = None


@dataclass
class _StubSuiteReport:
    suite_name: str  # e.g. "silver_trades"
    passed: bool


@dataclass
class _StubGap:
    duration_seconds: float


# ---------------------------------------------------------------------------
# QualityStatus / GapStatus / WatermarkInfo
# ---------------------------------------------------------------------------


def test_quality_status_defaults() -> None:
    qs = handoff.QualityStatus(passed=True)
    assert qs.passed is True
    assert qs.failed_suites == []


def test_gap_status_gap_free() -> None:
    gs = handoff.GapStatus(gap_free=True, max_gap_hours=0.0)
    assert gs.gap_free is True
    assert gs.max_gap_hours == 0.0


def test_watermark_info_normalizes_utc() -> None:
    naive = datetime(2026, 3, 1, 12, 0, 0)
    wm = handoff.WatermarkInfo(max_ts_event=naive)
    assert wm.max_ts_event is not None
    assert wm.max_ts_event.tzinfo is not None


# ---------------------------------------------------------------------------
# DatasetHandoffManifest
# ---------------------------------------------------------------------------


def _make_manifest(**overrides: object) -> handoff.DatasetHandoffManifest:
    kwargs: dict[str, object] = dict(
        handoff_id="test-handoff-001",
        source_run_ids=["run-1"],
        venue="kalshi",
        window_start_utc=_TS,
        window_end_utc=_TS_END,
        event_types=["trades", "ohlcv"],
        quality_status=handoff.QualityStatus(passed=True),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
        watermarks=handoff.WatermarkInfo(),
    )
    kwargs.update(overrides)
    return handoff.DatasetHandoffManifest.model_validate(kwargs)


def test_manifest_normalizes_venue() -> None:
    m = _make_manifest(venue="  Kalshi ")
    assert m.venue == "kalshi"


def test_manifest_normalizes_event_types() -> None:
    m = _make_manifest(event_types=["  Trades ", "OHLCV"])
    assert m.event_types == ["trades", "ohlcv"]


def test_manifest_is_dataset_ready_true() -> None:
    m = _make_manifest(
        quality_status=handoff.QualityStatus(passed=True),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
    )
    assert m.is_dataset_ready() is True


def test_manifest_is_dataset_ready_false_quality() -> None:
    m = _make_manifest(
        quality_status=handoff.QualityStatus(passed=False, failed_suites=["silver_trades"]),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
    )
    assert m.is_dataset_ready() is False


def test_manifest_is_dataset_ready_false_gap() -> None:
    m = _make_manifest(
        quality_status=handoff.QualityStatus(passed=True),
        gap_status=handoff.GapStatus(gap_free=False, max_gap_hours=2.5),
    )
    assert m.is_dataset_ready() is False


def test_manifest_schema_version_is_one() -> None:
    m = _make_manifest()
    assert m.schema_version == 1


def test_manifest_json_roundtrip() -> None:
    m = _make_manifest(partition_refs=["silver/trades/venue=kalshi/date=2026-03-01"])
    recovered = handoff.DatasetHandoffManifest.model_validate_json(m.model_dump_json())
    assert recovered.handoff_id == m.handoff_id
    assert recovered.partition_refs == m.partition_refs


# ---------------------------------------------------------------------------
# check_gating_rules
# ---------------------------------------------------------------------------


def test_gating_all_gates_pass() -> None:
    run = _StubRun(run_id="r1", status="completed", cursor_watermark_utc=_TS_END)
    report = _StubSuiteReport(suite_name="silver_trades", passed=True)

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[report],
        gaps=[],
        required_event_types=["trades"],
    )

    assert result.passed is True
    assert result.gate_errors == []
    assert result.quality_status.passed is True
    assert result.gap_status.gap_free is True
    assert result.gap_status.max_gap_hours == 0.0


def test_gating_fails_when_run_not_completed() -> None:
    run = _StubRun(run_id="r1", status="running")
    report = _StubSuiteReport(suite_name="silver_trades", passed=True)

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[report],
        gaps=[],
        required_event_types=["trades"],
    )

    assert result.passed is False
    assert any("r1" in e for e in result.gate_errors)


def test_gating_fails_when_run_failed() -> None:
    run = _StubRun(run_id="r2", status="failed")

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[],
        gaps=[],
        required_event_types=[],
    )

    assert result.passed is False
    assert any("failed" in e for e in result.gate_errors)


def test_gating_fails_when_quality_suite_did_not_pass() -> None:
    run = _StubRun(run_id="r1", status="completed")
    report = _StubSuiteReport(suite_name="silver_trades", passed=False)

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[report],
        gaps=[],
        required_event_types=["trades"],
    )

    assert result.passed is False
    assert result.quality_status.passed is False
    assert "silver_trades" in result.quality_status.failed_suites


def test_gating_fails_when_required_event_type_has_no_report() -> None:
    run = _StubRun(run_id="r1", status="completed")
    report = _StubSuiteReport(suite_name="silver_trades", passed=True)

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[report],
        gaps=[],
        required_event_types=["trades", "ohlcv"],  # ohlcv has no report
    )

    assert result.passed is False
    assert any("ohlcv" in e for e in result.gate_errors)


def test_gating_fails_when_gaps_detected_and_not_allowed() -> None:
    run = _StubRun(run_id="r1", status="completed")
    gap = _StubGap(duration_seconds=7200.0)

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[],
        gaps=[gap],
        required_event_types=[],
        allow_gaps=False,
    )

    assert result.passed is False
    assert result.gap_status.gap_free is False
    assert result.gap_status.max_gap_hours == pytest.approx(2.0)


def test_gating_passes_when_gaps_allowed() -> None:
    run = _StubRun(run_id="r1", status="completed")
    gap = _StubGap(duration_seconds=3600.0)

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[],
        gaps=[gap],
        required_event_types=[],
        allow_gaps=True,
    )

    assert result.passed is True
    assert result.gap_status.gap_free is False
    assert result.gap_status.max_gap_hours == pytest.approx(1.0)


def test_gating_watermark_from_cursor() -> None:
    wm = _TS + timedelta(hours=12)
    run = _StubRun(run_id="r1", status="completed", cursor_watermark_utc=wm)

    result = handoff.check_gating_rules(
        runs=[run],
        suite_reports=[],
        gaps=[],
        required_event_types=[],
    )

    assert result.watermarks.max_ts_event == wm


def test_gating_watermark_max_across_multiple_runs() -> None:
    early = _StubRun(run_id="r1", status="completed", cursor_watermark_utc=_TS)
    late = _StubRun(run_id="r2", status="completed", cursor_watermark_utc=_TS_END)

    result = handoff.check_gating_rules(
        runs=[early, late],
        suite_reports=[],
        gaps=[],
        required_event_types=[],
    )

    assert result.watermarks.max_ts_event == _TS_END


def test_gating_empty_inputs_pass_with_no_requirements() -> None:
    result = handoff.check_gating_rules(
        runs=[_StubRun(run_id="r1", status="completed")],
        suite_reports=[],
        gaps=[],
        required_event_types=[],
    )
    assert result.passed is True


# ---------------------------------------------------------------------------
# build_handoff_manifest
# ---------------------------------------------------------------------------


def test_build_handoff_manifest_auto_generates_id() -> None:
    qs = handoff.QualityStatus(passed=True)
    gs = handoff.GapStatus(gap_free=True, max_gap_hours=0.0)
    wm = handoff.WatermarkInfo()

    manifest = handoff.build_handoff_manifest(
        venue="polymarket",
        source_run_ids=["run-abc"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=qs,
        gap_status=gs,
        watermarks=wm,
    )

    assert manifest.handoff_id.startswith("20260301T120000Z_polymarket_trades_")
    assert manifest.venue == "polymarket"
    assert manifest.source_run_ids == ["run-abc"]


def test_build_handoff_manifest_respects_explicit_id() -> None:
    qs = handoff.QualityStatus(passed=True)
    gs = handoff.GapStatus(gap_free=True, max_gap_hours=0.0)
    wm = handoff.WatermarkInfo()

    manifest = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=["run-1"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["ohlcv"],
        quality_status=qs,
        gap_status=gs,
        watermarks=wm,
        handoff_id="custom-id-123",
    )

    assert manifest.handoff_id == "custom-id-123"


def test_build_handoff_manifest_includes_partition_refs() -> None:
    qs = handoff.QualityStatus(passed=True)
    gs = handoff.GapStatus(gap_free=True, max_gap_hours=0.0)
    wm = handoff.WatermarkInfo()
    refs = ["silver/trades/venue=kalshi/date=2026-03-01"]

    manifest = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=["run-1"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=qs,
        gap_status=gs,
        watermarks=wm,
        partition_refs=refs,
    )

    assert manifest.partition_refs == refs


# ---------------------------------------------------------------------------
# HandoffManifestStore
# ---------------------------------------------------------------------------


def _saved_manifest(store: handoff.HandoffManifestStore) -> handoff.DatasetHandoffManifest:
    m = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=["run-1"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=handoff.QualityStatus(passed=True),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
        watermarks=handoff.WatermarkInfo(),
        handoff_id="store-test-001",
    )
    store.save(m)
    return m


def test_store_save_creates_json_file(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    m = _saved_manifest(store)
    assert (tmp_path / "_lineage" / "handoffs" / "store-test-001.json").exists()
    assert m.handoff_id == "store-test-001"


def test_store_load_returns_manifest(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    _saved_manifest(store)
    loaded = store.load("store-test-001")
    assert loaded is not None
    assert loaded.handoff_id == "store-test-001"


def test_store_load_returns_none_for_unknown(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    assert store.load("does-not-exist") is None


def test_store_list_manifests_returns_all(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    for i in range(3):
        m = handoff.build_handoff_manifest(
            venue="kalshi",
            source_run_ids=[f"run-{i}"],
            window_start=_TS + timedelta(days=i),
            window_end=_TS + timedelta(days=i + 1),
            event_types=["trades"],
            quality_status=handoff.QualityStatus(passed=True),
            gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
            watermarks=handoff.WatermarkInfo(),
            handoff_id=f"list-test-{i:03d}",
        )
        store.save(m)

    manifests = store.list_manifests()
    assert len(manifests) == 3


def test_store_list_manifests_filters_by_venue(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    for venue in ("kalshi", "polymarket", "kalshi"):
        m = handoff.build_handoff_manifest(
            venue=venue,
            source_run_ids=["run-x"],
            window_start=_TS,
            window_end=_TS_END,
            event_types=["trades"],
            quality_status=handoff.QualityStatus(passed=True),
            gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
            watermarks=handoff.WatermarkInfo(),
        )
        store.save(m)

    kalshi_manifests = store.list_manifests(venue="kalshi")
    assert len(kalshi_manifests) == 2
    assert all(m.venue == "kalshi" for m in kalshi_manifests)


def test_store_list_manifests_dataset_ready_only(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    ready = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=["r1"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=handoff.QualityStatus(passed=True),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
        watermarks=handoff.WatermarkInfo(),
        handoff_id="ready-001",
    )
    not_ready = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=["r2"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=handoff.QualityStatus(passed=False, failed_suites=["silver_trades"]),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
        watermarks=handoff.WatermarkInfo(),
        handoff_id="not-ready-001",
    )
    store.save(ready)
    store.save(not_ready)

    results = store.list_manifests(dataset_ready_only=True)
    assert len(results) == 1
    assert results[0].handoff_id == "ready-001"


def test_store_save_is_atomic_overwrite(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    m1 = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=["r1"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=handoff.QualityStatus(passed=False),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
        watermarks=handoff.WatermarkInfo(),
        handoff_id="overwrite-001",
    )
    m2 = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=["r1"],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=handoff.QualityStatus(passed=True),
        gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
        watermarks=handoff.WatermarkInfo(),
        handoff_id="overwrite-001",
    )
    store.save(m1)
    store.save(m2)

    loaded = store.load("overwrite-001")
    assert loaded is not None
    assert loaded.quality_status.passed is True


def test_store_lists_newest_window_first(tmp_path: Path) -> None:
    store = handoff.HandoffManifestStore(tmp_path)
    dates = [_TS + timedelta(days=i) for i in range(3)]
    for i, ts in enumerate(dates):
        m = handoff.build_handoff_manifest(
            venue="kalshi",
            source_run_ids=["r"],
            window_start=ts,
            window_end=ts + timedelta(hours=1),
            event_types=["trades"],
            quality_status=handoff.QualityStatus(passed=True),
            gap_status=handoff.GapStatus(gap_free=True, max_gap_hours=0.0),
            watermarks=handoff.WatermarkInfo(),
            handoff_id=f"sort-{i:03d}",
        )
        store.save(m)

    manifests = store.list_manifests()
    assert manifests[0].window_start_utc > manifests[-1].window_start_utc


# ---------------------------------------------------------------------------
# Integration: gating → build → save → lineage link
# ---------------------------------------------------------------------------


def test_full_handoff_flow(tmp_path: Path) -> None:
    """End-to-end: gating check → build manifest → save → link to lineage run."""
    lin_store = lineage.LineageStore(tmp_path)
    man_store = handoff.HandoffManifestStore(tmp_path)

    run = lin_store.start_run(
        "kalshi",
        "polling",
        options=lineage.StartRunOptions(run_id="e2e-run-1", event_types=["trades"]),
    )
    lin_store.complete_run(
        run.run_id,
        counts={"trades": 500},
        errors=[],
        cursor_watermark_utc=_TS_END,
        resume_safe=True,
    )

    # Gating
    completed_run = lin_store.get_run(run.run_id)
    assert completed_run is not None
    reports = [_StubSuiteReport(suite_name="silver_trades", passed=True)]
    result = handoff.check_gating_rules(
        runs=[completed_run],
        suite_reports=reports,
        gaps=[],
        required_event_types=["trades"],
    )
    assert result.passed is True

    # Build and save manifest
    manifest = handoff.build_handoff_manifest(
        venue="kalshi",
        source_run_ids=[run.run_id],
        window_start=_TS,
        window_end=_TS_END,
        event_types=["trades"],
        quality_status=result.quality_status,
        gap_status=result.gap_status,
        watermarks=result.watermarks,
        partition_refs=["silver/trades/venue=kalshi/date=2026-03-01"],
    )
    saved_path = man_store.save(manifest)

    # Link to lineage
    lin_store.mark_dataset_ready(run.run_id, handoff_manifest_path=str(saved_path))

    # Verify lineage record is updated
    persisted = lin_store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.dataset_ready is True
    assert persisted.handoff_manifest_path == str(saved_path)

    # Verify manifest is loadable
    loaded = man_store.load(manifest.handoff_id)
    assert loaded is not None
    assert loaded.is_dataset_ready() is True
    assert loaded.partition_refs == ["silver/trades/venue=kalshi/date=2026-03-01"]
