"""Unit tests for replay-package manifest schema, store, and cursor integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import alpha_core.storage.lineage as lineage
import alpha_core.storage.replay_package as rp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
_T1 = datetime(2024, 3, 2, 0, 0, 0, tzinfo=UTC)


def _simple_manifest(
    *,
    venue: str = "polymarket",
    source_run_ids: list[str] | None = None,
    partition_refs: list[rp.ReplayPartitionRef] | None = None,
    package_id: str | None = None,
) -> rp.ReplayPackageManifest:
    return rp.build_replay_package(
        venue=venue,
        source_run_ids=source_run_ids or ["run_abc"],
        window_start=_T0,
        window_end=_T1,
        event_types=["trades"],
        instrument_ids=["p:mkt1:yes"],
        partition_refs=partition_refs,
        cursor_watermark_utc=_T1,
        package_id=package_id,
    )


# ---------------------------------------------------------------------------
# ReplayOrderingPolicy
# ---------------------------------------------------------------------------


def test_ordering_policy_values() -> None:
    assert rp.ReplayOrderingPolicy.EVENT_TIME == "event_time"  # type: ignore[comparison-overlap]
    assert rp.ReplayOrderingPolicy.RECORD_TIME == "record_time"  # type: ignore[comparison-overlap]
    assert rp.ReplayOrderingPolicy.HYBRID == "hybrid"  # type: ignore[comparison-overlap]


# ---------------------------------------------------------------------------
# ReplayPartitionRef
# ---------------------------------------------------------------------------


def test_partition_ref_normalizes_venue_and_event_type() -> None:
    ref = rp.ReplayPartitionRef(
        venue="  Polymarket  ",
        event_type="  TRADES  ",
        date="2024-03-01",
        partition_path="silver/trades/venue=polymarket/date=2024-03-01",
    )
    assert ref.venue == "polymarket"
    assert ref.event_type == "trades"
    assert ref.row_count == -1  # default


def test_partition_ref_with_hour() -> None:
    ref = rp.ReplayPartitionRef(
        venue="kalshi",
        event_type="books",
        date="2024-03-01",
        hour="03",
        partition_path="silver/books/venue=kalshi/date=2024-03-01/hour=03",
        row_count=500,
    )
    assert ref.hour == "03"
    assert ref.row_count == 500


def test_partition_ref_rejects_invalid_date() -> None:
    with pytest.raises(Exception):
        rp.ReplayPartitionRef(
            venue="kalshi",
            event_type="trades",
            date="01-03-2024",  # wrong format
            partition_path="some/path",
        )


def test_partition_ref_forbids_extra_fields() -> None:
    with pytest.raises(Exception):
        rp.ReplayPartitionRef(  # type: ignore[call-arg]
            venue="kalshi",
            event_type="trades",
            date="2024-03-01",
            partition_path="some/path",
            unexpected_field="oops",
        )


# ---------------------------------------------------------------------------
# build_replay_package
# ---------------------------------------------------------------------------


def test_build_replay_package_basic_fields() -> None:
    manifest = _simple_manifest(venue="polymarket", source_run_ids=["run_1"])
    assert manifest.venue == "polymarket"
    assert manifest.source_run_ids == ["run_1"]
    assert manifest.window_start == _T0
    assert manifest.window_end == _T1
    assert manifest.event_types == ["trades"]
    assert manifest.instrument_ids == ["p:mkt1:yes"]
    assert manifest.cursor_watermark_utc == _T1
    assert manifest.schema_version == 1
    assert manifest.ordering_policy == rp.ReplayOrderingPolicy.EVENT_TIME


def test_build_replay_package_generates_package_id() -> None:
    m1 = _simple_manifest()
    m2 = _simple_manifest()
    assert m1.package_id != m2.package_id  # UUIDs differ
    assert len(m1.package_id) > 0


def test_build_replay_package_uses_explicit_package_id() -> None:
    manifest = _simple_manifest(package_id="fixed-id-123")
    assert manifest.package_id == "fixed-id-123"


def test_build_result_has_non_empty_integrity_hash() -> None:
    manifest = _simple_manifest()
    assert len(manifest.integrity_hash) == 64  # SHA-256 hex


def test_integrity_hash_is_stable_for_same_inputs() -> None:
    refs = [
        rp.ReplayPartitionRef(
            venue="polymarket",
            event_type="trades",
            date="2024-03-01",
            partition_path="silver/trades/venue=polymarket/date=2024-03-01",
        )
    ]
    m1 = _simple_manifest(source_run_ids=["run_abc"], partition_refs=refs, package_id="p1")
    m2 = _simple_manifest(source_run_ids=["run_abc"], partition_refs=refs, package_id="p1")
    assert m1.integrity_hash == m2.integrity_hash


def test_integrity_hash_changes_when_partition_paths_change() -> None:
    refs_a = [
        rp.ReplayPartitionRef(
            venue="polymarket",
            event_type="trades",
            date="2024-03-01",
            partition_path="silver/trades/venue=polymarket/date=2024-03-01",
        )
    ]
    refs_b = [
        rp.ReplayPartitionRef(
            venue="polymarket",
            event_type="trades",
            date="2024-03-02",
            partition_path="silver/trades/venue=polymarket/date=2024-03-02",
        )
    ]
    m1 = _simple_manifest(source_run_ids=["run_abc"], partition_refs=refs_a)
    m2 = _simple_manifest(source_run_ids=["run_abc"], partition_refs=refs_b)
    assert m1.integrity_hash != m2.integrity_hash


def test_integrity_hash_changes_when_source_run_ids_change() -> None:
    m1 = _simple_manifest(source_run_ids=["run_abc"])
    m2 = _simple_manifest(source_run_ids=["run_xyz"])
    assert m1.integrity_hash != m2.integrity_hash


def test_total_event_count_sums_known_row_counts() -> None:
    refs = [
        rp.ReplayPartitionRef(
            venue="polymarket",
            event_type="trades",
            date="2024-03-01",
            partition_path="silver/trades/venue=polymarket/date=2024-03-01",
            row_count=100,
        ),
        rp.ReplayPartitionRef(
            venue="polymarket",
            event_type="trades",
            date="2024-03-02",
            partition_path="silver/trades/venue=polymarket/date=2024-03-02",
            row_count=200,
        ),
    ]
    manifest = rp.build_replay_package(
        venue="polymarket",
        source_run_ids=["run_abc"],
        window_start=_T0,
        window_end=_T1,
        event_types=["trades"],
        partition_refs=refs,
    )
    assert manifest.total_event_count == 300


def test_total_event_count_is_minus_one_when_unknown() -> None:
    manifest = _simple_manifest()  # no partition_refs
    assert manifest.total_event_count == -1


def test_build_replay_package_normalizes_venue() -> None:
    manifest = rp.build_replay_package(
        venue="  POLYMARKET  ",
        source_run_ids=["run_abc"],
        window_start=_T0,
        window_end=_T1,
        event_types=["trades"],
    )
    assert manifest.venue == "polymarket"


def test_build_replay_package_normalizes_event_types() -> None:
    manifest = rp.build_replay_package(
        venue="polymarket",
        source_run_ids=["run_abc"],
        window_start=_T0,
        window_end=_T1,
        event_types=["  TRADES  ", "OHLCV"],
    )
    assert "trades" in manifest.event_types
    assert "ohlcv" in manifest.event_types


# ---------------------------------------------------------------------------
# ReplayPackageManifest round-trip
# ---------------------------------------------------------------------------


def test_manifest_round_trips_json() -> None:
    manifest = _simple_manifest()
    raw = manifest.model_dump_json(indent=2)
    restored = rp.ReplayPackageManifest.model_validate_json(raw)
    assert restored.package_id == manifest.package_id
    assert restored.integrity_hash == manifest.integrity_hash
    assert restored.cursor_watermark_utc == manifest.cursor_watermark_utc
    assert restored.schema_version == 1


def test_manifest_round_trips_with_partitions() -> None:
    refs = [
        rp.ReplayPartitionRef(
            venue="polymarket",
            event_type="trades",
            date="2024-03-01",
            partition_path="silver/trades/venue=polymarket/date=2024-03-01",
            row_count=77,
        ),
    ]
    manifest = _simple_manifest(partition_refs=refs)
    restored = rp.ReplayPackageManifest.model_validate_json(manifest.model_dump_json())
    assert len(restored.partitions) == 1
    assert restored.partitions[0].row_count == 77


def test_manifest_forbids_extra_fields() -> None:
    with pytest.raises(Exception):
        rp.ReplayPackageManifest(  # type: ignore[call-arg]
            package_id="x",
            created_at=_T0,
            venue="polymarket",
            source_run_ids=["run_abc"],
            window_start=_T0,
            window_end=_T1,
            event_types=["trades"],
            integrity_hash="a" * 64,
            undeclared_field="oops",
        )


# ---------------------------------------------------------------------------
# ReplayPackageStore
# ---------------------------------------------------------------------------


def test_store_save_and_get_round_trip(tmp_path: Path) -> None:
    store = rp.ReplayPackageStore(tmp_path)
    manifest = _simple_manifest(package_id="pkg-test-001")

    saved_path = store.save(manifest)
    assert saved_path.exists()

    loaded = store.get("pkg-test-001")
    assert loaded is not None
    assert loaded.package_id == "pkg-test-001"
    assert loaded.integrity_hash == manifest.integrity_hash


def test_store_get_returns_none_for_missing_id(tmp_path: Path) -> None:
    store = rp.ReplayPackageStore(tmp_path)
    assert store.get("nonexistent-id") is None


def test_store_save_write_once_by_default(tmp_path: Path) -> None:
    store = rp.ReplayPackageStore(tmp_path)
    manifest = _simple_manifest(package_id="pkg-dup-001")
    store.save(manifest)

    with pytest.raises(FileExistsError, match="pkg-dup-001"):
        store.save(manifest)


def test_store_save_overwrite_replaces_existing(tmp_path: Path) -> None:
    store = rp.ReplayPackageStore(tmp_path)
    m1 = _simple_manifest(source_run_ids=["run_001"], package_id="pkg-ow-001")
    store.save(m1)

    m2 = rp.build_replay_package(
        venue="polymarket",
        source_run_ids=["run_002"],  # changed
        window_start=_T0,
        window_end=_T1,
        event_types=["trades"],
        package_id="pkg-ow-001",
    )
    store.save(m2, overwrite=True)

    loaded = store.get("pkg-ow-001")
    assert loaded is not None
    assert loaded.source_run_ids == ["run_002"]


def test_store_list_packages_returns_all_sorted_by_window_end_desc(tmp_path: Path) -> None:
    store = rp.ReplayPackageStore(tmp_path)
    t_base = datetime(2024, 3, 1, tzinfo=UTC)

    for i in range(3):
        m = rp.build_replay_package(
            venue="polymarket",
            source_run_ids=[f"run_{i}"],
            window_start=t_base + timedelta(days=i),
            window_end=t_base + timedelta(days=i + 1),
            event_types=["trades"],
        )
        store.save(m)

    packages = store.list_packages()
    assert len(packages) == 3
    # Most recent window_end first
    assert packages[0].window_end > packages[1].window_end
    assert packages[1].window_end > packages[2].window_end


def test_store_list_packages_filters_by_venue(tmp_path: Path) -> None:
    store = rp.ReplayPackageStore(tmp_path)
    for venue in ("polymarket", "kalshi", "polymarket"):
        m = rp.build_replay_package(
            venue=venue,
            source_run_ids=["run_x"],
            window_start=_T0,
            window_end=_T1,
            event_types=["trades"],
        )
        store.save(m)

    poly = store.list_packages(venue="polymarket")
    assert all(p.venue == "polymarket" for p in poly)
    assert len(poly) == 2

    kalshi = store.list_packages(venue="kalshi")
    assert len(kalshi) == 1


def test_store_list_packages_filters_by_since(tmp_path: Path) -> None:
    store = rp.ReplayPackageStore(tmp_path)
    t_base = datetime(2024, 3, 1, tzinfo=UTC)

    for i in range(4):
        m = rp.build_replay_package(
            venue="polymarket",
            source_run_ids=[f"run_{i}"],
            window_start=t_base + timedelta(days=i),
            window_end=t_base + timedelta(days=i + 1),
            event_types=["trades"],
        )
        store.save(m)

    since = t_base + timedelta(days=2, hours=12)
    recent = store.list_packages(since=since)
    # Only packages with window_end >= since
    assert all(p.window_end >= since for p in recent)


def test_store_creates_package_directory_automatically(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested"  # does not exist yet
    store = rp.ReplayPackageStore(nested)
    m = _simple_manifest(package_id="pkg-auto-dir")
    store.save(m)
    assert (nested / "_replay_packages" / "pkg_pkg-auto-dir.json").exists()


# ---------------------------------------------------------------------------
# derive_partition_refs
# ---------------------------------------------------------------------------


def _make_hive_structure(base: Path, venue: str, event_type: str, dates: list[str]) -> None:
    """Build a minimal Hive directory tree without actual Parquet files."""
    dataset = event_type
    for date in dates:
        d = base / "silver" / dataset / f"venue={venue}" / f"date={date}"
        d.mkdir(parents=True, exist_ok=True)


def _make_hive_structure_with_hours(
    base: Path, venue: str, event_type: str, dates: list[str], hours: list[str]
) -> None:
    dataset = event_type
    for date in dates:
        for hour in hours:
            d = base / "silver" / dataset / f"venue={venue}" / f"date={date}" / f"hour={hour}"
            d.mkdir(parents=True, exist_ok=True)


def test_derive_partition_refs_scans_date_partitions(tmp_path: Path) -> None:
    _make_hive_structure(
        tmp_path, "polymarket", "trades", ["2024-03-01", "2024-03-02", "2024-03-03"]
    )

    refs = rp.derive_partition_refs(
        tmp_path,
        venue="polymarket",
        event_types=["trades"],
        window_start=datetime(2024, 3, 1, tzinfo=UTC),
        window_end=datetime(2024, 3, 2, tzinfo=UTC),
    )
    dates = {r.date for r in refs}
    assert "2024-03-01" in dates
    assert "2024-03-02" in dates
    # 2024-03-03 is outside the window
    assert "2024-03-03" not in dates


def test_derive_partition_refs_scans_hour_partitions(tmp_path: Path) -> None:
    _make_hive_structure_with_hours(
        tmp_path, "polymarket", "books", ["2024-03-01"], ["00", "01", "02"]
    )

    refs = rp.derive_partition_refs(
        tmp_path,
        venue="polymarket",
        event_types=["books"],
        window_start=datetime(2024, 3, 1, tzinfo=UTC),
        window_end=datetime(2024, 3, 2, tzinfo=UTC),
    )
    assert len(refs) == 3
    hours = {r.hour for r in refs}
    assert hours == {"00", "01", "02"}


def test_derive_partition_refs_returns_empty_for_missing_venue(tmp_path: Path) -> None:
    _make_hive_structure(tmp_path, "polymarket", "trades", ["2024-03-01"])

    refs = rp.derive_partition_refs(
        tmp_path,
        venue="kalshi",  # different venue
        event_types=["trades"],
        window_start=datetime(2024, 3, 1, tzinfo=UTC),
        window_end=datetime(2024, 3, 2, tzinfo=UTC),
    )
    assert refs == []


def test_derive_partition_refs_returns_empty_for_missing_event_type(tmp_path: Path) -> None:
    _make_hive_structure(tmp_path, "polymarket", "trades", ["2024-03-01"])

    refs = rp.derive_partition_refs(
        tmp_path,
        venue="polymarket",
        event_types=["ohlcv"],  # not present
        window_start=datetime(2024, 3, 1, tzinfo=UTC),
        window_end=datetime(2024, 3, 2, tzinfo=UTC),
    )
    assert refs == []


def test_derive_partition_refs_handles_nonexistent_storage_root(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    refs = rp.derive_partition_refs(
        missing,
        venue="polymarket",
        event_types=["trades"],
        window_start=_T0,
        window_end=_T1,
    )
    assert refs == []


def test_derive_partition_refs_partition_path_is_relative_to_storage_root(tmp_path: Path) -> None:
    _make_hive_structure(tmp_path, "polymarket", "trades", ["2024-03-01"])

    refs = rp.derive_partition_refs(
        tmp_path,
        venue="polymarket",
        event_types=["trades"],
        window_start=datetime(2024, 3, 1, tzinfo=UTC),
        window_end=datetime(2024, 3, 2, tzinfo=UTC),
    )
    assert len(refs) == 1
    # path is relative (no leading slash), does not include the storage root
    assert not refs[0].partition_path.startswith("/")
    assert "silver/trades" in refs[0].partition_path


def test_derive_partition_refs_covers_multiple_event_types(tmp_path: Path) -> None:
    _make_hive_structure(tmp_path, "polymarket", "trades", ["2024-03-01"])
    _make_hive_structure(tmp_path, "polymarket", "ohlcv", ["2024-03-01"])

    refs = rp.derive_partition_refs(
        tmp_path,
        venue="polymarket",
        event_types=["trades", "ohlcv"],
        window_start=datetime(2024, 3, 1, tzinfo=UTC),
        window_end=datetime(2024, 3, 2, tzinfo=UTC),
    )
    event_types_found = {r.event_type for r in refs}
    assert "trades" in event_types_found
    assert "ohlcv" in event_types_found


# ---------------------------------------------------------------------------
# LineageStore cursor integration
# ---------------------------------------------------------------------------


def test_complete_run_persists_cursor_fields(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("polymarket", "polling")
    watermark = datetime(2024, 3, 2, tzinfo=UTC)

    store.complete_run(
        run.run_id,
        counts={"trades": 100},
        cursor_type="ts_event",
        cursor_value=watermark.isoformat(),
        cursor_watermark_utc=watermark,
        resume_safe=True,
        replay_package_id="pkg-xyz",
    )

    completed = store.get_run(run.run_id)
    assert completed is not None
    assert completed.cursor_type == "ts_event"
    assert completed.cursor_value == watermark.isoformat()
    assert completed.cursor_watermark_utc == watermark
    assert completed.resume_safe is True
    assert completed.replay_package_id == "pkg-xyz"


def test_complete_run_without_cursor_leaves_cursor_fields_none(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")
    store.complete_run(run.run_id, counts={"trades": 10})

    completed = store.get_run(run.run_id)
    assert completed is not None
    assert completed.cursor_type is None
    assert completed.cursor_watermark_utc is None
    assert completed.resume_safe is None


def test_get_latest_cursor_returns_most_recent_completed_with_watermark(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    t_base = datetime(2024, 3, 1, tzinfo=UTC)
    for i in range(3):
        run = store.start_run("polymarket", "polling")
        store.complete_run(
            run.run_id,
            counts={"trades": 10 * (i + 1)},
            cursor_type="ts_event",
            cursor_value=(t_base + timedelta(days=i)).isoformat(),
            cursor_watermark_utc=t_base + timedelta(days=i),
            resume_safe=True,
        )

    latest = store.get_latest_cursor("polymarket")
    assert latest is not None
    # Should return the run with the highest cursor_watermark_utc
    assert latest.cursor_watermark_utc == t_base + timedelta(days=2)


def test_get_latest_cursor_ignores_failed_runs(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    # Complete one run with cursor
    run1 = store.start_run("polymarket", "polling")
    store.complete_run(
        run1.run_id,
        counts={"trades": 10},
        cursor_type="ts_event",
        cursor_value=_T0.isoformat(),
        cursor_watermark_utc=_T0,
        resume_safe=True,
    )
    # Start and fail a second run
    run2 = store.start_run("polymarket", "polling")
    store.fail_run(run2.run_id, "network error")

    latest = store.get_latest_cursor("polymarket")
    assert latest is not None
    assert latest.run_id == run1.run_id


def test_get_latest_cursor_returns_none_when_no_runs(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    assert store.get_latest_cursor("polymarket") is None


def test_get_latest_cursor_returns_none_when_no_cursor_watermark_set(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("polymarket", "polling")
    store.complete_run(run.run_id, counts={"trades": 10})  # no cursor fields

    assert store.get_latest_cursor("polymarket") is None


def test_get_latest_cursor_filters_by_event_type(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)

    # Run covering "trades"
    run_t = store.start_run(
        "polymarket",
        "polling",
        options=lineage.StartRunOptions(event_types=["trades"]),
    )
    store.complete_run(
        run_t.run_id,
        counts={"trades": 50},
        cursor_type="ts_event",
        cursor_value=_T0.isoformat(),
        cursor_watermark_utc=_T0,
        resume_safe=True,
    )

    # Run covering "ohlcv"
    run_o = store.start_run(
        "polymarket",
        "polling",
        options=lineage.StartRunOptions(event_types=["ohlcv"]),
    )
    store.complete_run(
        run_o.run_id,
        counts={"ohlcv": 10},
        cursor_type="ts_event",
        cursor_value=_T1.isoformat(),
        cursor_watermark_utc=_T1,
        resume_safe=True,
    )

    trades_cursor = store.get_latest_cursor("polymarket", event_type="trades")
    assert trades_cursor is not None
    assert trades_cursor.cursor_watermark_utc == _T0

    ohlcv_cursor = store.get_latest_cursor("polymarket", event_type="ohlcv")
    assert ohlcv_cursor is not None
    assert ohlcv_cursor.cursor_watermark_utc == _T1


def test_ingestion_run_cursor_fields_round_trip_json(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("polymarket", "polling")
    watermark = datetime(2024, 3, 15, 12, 0, 0, tzinfo=UTC)
    store.complete_run(
        run.run_id,
        counts={"trades": 999},
        cursor_type="ts_event",
        cursor_value=watermark.isoformat(),
        cursor_watermark_utc=watermark,
        resume_safe=True,
        replay_package_id="pkg-round-trip-001",
    )

    reloaded = store.get_run(run.run_id)
    assert reloaded is not None
    # JSON round-trip should preserve all cursor fields
    raw = reloaded.model_dump_json()
    restored = lineage.IngestionRun.model_validate_json(raw)
    assert restored.cursor_type == "ts_event"
    assert restored.cursor_watermark_utc == watermark
    assert restored.resume_safe is True
    assert restored.replay_package_id == "pkg-round-trip-001"


def test_ingestion_run_schema_version_defaults_to_2(tmp_path: Path) -> None:
    store = lineage.LineageStore(tmp_path)
    run = store.start_run("kalshi", "polling")
    assert run.schema_version == 2
