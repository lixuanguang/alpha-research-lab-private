"""Integration test: build-features CLI command end-to-end.

Verifies that the ``build-features`` command:
- Emits a planned outcome (plan-only mode, no filesystem writes).
- Computes features, persists artifacts, and exits zero (execute mode).
- Outputs machine-readable JSON when ``--format json`` is requested.
- Fails fast when dataset artifacts are missing (non-zero exit).
- Handles an empty trades table (zero-row output without error).
- Run manifest carries ``feature_set_version`` in its artifacts map.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import apps.research.main as research_main
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from click.testing import CliRunner

import alpha_core.instruments.master as master_mod
import alpha_core.instruments.models as instrument_models
import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.session as session_mod

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_DATASET_ID = "deadbeef01234567"  # 16-char fake dataset hash

_TRADES_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string()),
        pa.field("instrument_id", pa.string()),
        pa.field("venue_id", pa.string()),
        pa.field("event_type", pa.string()),
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("ts_record", pa.timestamp("us", tz="UTC")),
        pa.field("price", pa.float64()),
        pa.field("size", pa.float64()),
    ]
)

_BOOKS_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string()),
        pa.field("instrument_id", pa.string()),
        pa.field("venue_id", pa.string()),
        pa.field("event_type", pa.string()),
        pa.field("ts_event", pa.timestamp("us", tz="UTC")),
        pa.field("ts_record", pa.timestamp("us", tz="UTC")),
        pa.field("bids_json", pa.string()),
        pa.field("asks_json", pa.string()),
    ]
)


def _write_gold_trades(dataset_dir: Path, n: int = 20) -> None:
    """Write a synthetic gold ``trades.parquet`` into *dataset_dir*."""
    dataset_dir.mkdir(parents=True, exist_ok=True)
    step = timedelta(minutes=30)
    ts_events = [_BASE + step * i for i in range(n)]
    instruments = [f"p:m1:{'yes' if i % 2 == 0 else 'no'}" for i in range(n)]
    table = pa.table(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "instrument_id": instruments,
            "venue_id": ["p"] * n,
            "event_type": ["trade"] * n,
            "ts_event": ts_events,
            "ts_record": ts_events,
            "price": [0.48 + 0.01 * (i % 5) for i in range(n)],
            "size": [100.0 + i for i in range(n)],
        },
        schema=_TRADES_SCHEMA,
    )
    pq.write_table(table, dataset_dir / "trades.parquet", compression="zstd")


def _write_pm_gold_trades(dataset_dir: Path, n_timestamps: int = 25) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    ts_events = [_BASE + timedelta(minutes=15 * i) for i in range(n_timestamps)]
    rows: list[dict[str, object]] = []
    venues = ("kalshi", "polymarket")
    for idx, ts_event in enumerate(ts_events):
        base_price = 0.40 + 0.01 * (idx % 10)
        for venue_idx, venue in enumerate(venues):
            rows.append(
                {
                    "event_id": f"{venue}-e{idx}",
                    "instrument_id": f"{venue}:m1:yes",
                    "venue_id": venue,
                    "event_type": "trade",
                    "ts_event": ts_event,
                    "ts_record": ts_event,
                    "price": base_price + 0.02 * venue_idx,
                    "size": 100.0 + idx + 10.0 * venue_idx,
                }
            )
    table = pa.Table.from_pylist(rows, schema=_TRADES_SCHEMA)
    pq.write_table(table, dataset_dir / "trades.parquet", compression="zstd")


def _write_pm_gold_books(dataset_dir: Path, n_timestamps: int = 25) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    ts_events = [_BASE + timedelta(minutes=15 * i) for i in range(n_timestamps)]
    rows: list[dict[str, object]] = []
    venues = ("kalshi", "polymarket")
    for idx, ts_event in enumerate(ts_events):
        for venue_idx, venue in enumerate(venues):
            rows.append(
                {
                    "event_id": f"{venue}-b{idx}",
                    "instrument_id": f"{venue}:m1:yes",
                    "venue_id": venue,
                    "event_type": "book_snapshot",
                    "ts_event": ts_event,
                    "ts_record": ts_event,
                    "bids_json": json.dumps(
                        [
                            {"price": "0.49", "size": str(140 + idx + venue_idx)},
                            {"price": "0.48", "size": str(50 + venue_idx)},
                            {"price": "0.47", "size": str(25 + venue_idx)},
                        ]
                    ),
                    "asks_json": json.dumps(
                        [
                            {"price": "0.51", "size": str(90 + idx - venue_idx)},
                            {"price": "0.52", "size": str(40 + venue_idx)},
                            {"price": "0.53", "size": str(20 + venue_idx)},
                        ]
                    ),
                }
            )
    table = pa.Table.from_pylist(rows, schema=_BOOKS_SCHEMA)
    pq.write_table(table, dataset_dir / "books.parquet", compression="zstd")


def _write_instrument_master(storage_root: Path) -> None:
    master = master_mod.MarketMaster()
    first_seen = _BASE - timedelta(days=1)
    resolution_date = _BASE + timedelta(days=7)
    for venue in ("kalshi", "polymarket"):
        master.register_market(
            instrument_models.MarketSpec(
                market_id="m1",
                venue=venue,
                title=f"{venue} market",
                category="macro",
                outcomes=[
                    instrument_models.OutcomeSpec(
                        outcome_id="yes",
                        label="YES",
                        canonical_id=f"{venue}:m1:yes",
                    )
                ],
                resolution_date=resolution_date,
                first_seen=first_seen,
                last_updated=first_seen,
            )
        )
    master.persist(storage_root / "instruments.parquet")


def _write_dataset_meta(dataset_dir: Path, dataset_id: str, dataset_name: str) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": "dataset_run_123",
        "dataset_id": dataset_id,
        "config": {
            "name": dataset_name,
            "start": _BASE.isoformat(),
            "end": (_BASE + timedelta(days=1)).isoformat(),
            "venues": None,
            "event_types": ["trades"],
            "universe_filters": {},
            "require_quality_pass": False,
            "require_gap_free": False,
            "max_gap_hours": 24.0,
        },
        "built_at": _BASE.isoformat(),
        "row_counts": {"trades": 20},
        "instrument_count": 2,
        "date_range": [_BASE.isoformat(), (_BASE + timedelta(days=1)).isoformat()],
        "quality_summary": {"checked": False},
        "schema_version": 1,
    }
    (dataset_dir / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _write_empty_gold_trades(dataset_dir: Path) -> None:
    """Write an empty-row gold ``trades.parquet`` into *dataset_dir*."""
    dataset_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({name: [] for name in _TRADES_SCHEMA.names}, schema=_TRADES_SCHEMA),
        dataset_dir / "trades.parquet",
        compression="zstd",
    )


@pytest.fixture()
def storage_root_with_dataset(tmp_path: Path) -> Path:
    """Storage root with a fully populated gold dataset directory."""
    dataset_dir = tmp_path / "gold" / "datasets" / _DATASET_ID
    _write_gold_trades(dataset_dir, n=20)
    return tmp_path


@pytest.fixture()
def storage_root_with_empty_dataset(tmp_path: Path) -> Path:
    """Storage root with a gold dataset containing zero trades rows."""
    dataset_dir = tmp_path / "gold" / "datasets" / _DATASET_ID
    _write_empty_gold_trades(dataset_dir)
    return tmp_path


@pytest.fixture()
def storage_root_with_named_dataset(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "gold" / "datasets" / _DATASET_ID
    _write_gold_trades(dataset_dir, n=20)
    _write_dataset_meta(dataset_dir, _DATASET_ID, "named_dataset")
    return tmp_path


@pytest.fixture()
def storage_root_with_pm_dataset(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "gold" / "datasets" / _DATASET_ID
    _write_pm_gold_trades(dataset_dir)
    _write_pm_gold_books(dataset_dir)
    _write_instrument_master(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests — plan-only mode (no FeatureRunner required)
# ---------------------------------------------------------------------------


def test_plan_only_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        ["build-features", "--dataset-id", _DATASET_ID, "--feature-set-version", "v1"],
    )
    assert result.exit_code == 0, result.output
    assert "planned" in result.output


def test_plan_only_json_output() -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "planned"
    assert data["run_type"] == "feature_build"
    assert "run_id" in data
    assert "config_hash" in data


def test_plan_only_does_not_write_files(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "runs").exists(), "Plan-only must not create run directories."


# ---------------------------------------------------------------------------
# Tests — execute mode (normal case)
# ---------------------------------------------------------------------------


def test_execute_exits_zero(storage_root_with_dataset: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "materialized" in result.output


def test_execute_writes_features_parquet(storage_root_with_dataset: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    run_dirs = list((storage_root_with_dataset / "runs").iterdir())
    assert len(run_dirs) == 1
    features_path = run_dirs[0] / "stage_outputs" / "features.parquet"
    assert features_path.exists(), "features.parquet must be written to stage_outputs/"


def test_execute_features_parquet_has_rows(storage_root_with_dataset: Path) -> None:
    runner = CliRunner()
    runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--lookback-bars",
            "5",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    features_path = (
        next((storage_root_with_dataset / "runs").iterdir()) / "stage_outputs" / "features.parquet"
    )
    table = pq.read_table(features_path)
    assert table.num_rows == 20  # One feature row per trade row.
    assert "instrument_id" in table.schema.names
    assert "price_mean_5" in table.schema.names
    assert "price_zscore_5" in table.schema.names


def test_execute_writes_config_snapshot(storage_root_with_dataset: Path) -> None:
    runner = CliRunner()
    runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    run_id = next((storage_root_with_dataset / "runs").iterdir()).name
    config_path = artifact_paths.run_config_path(storage_root_with_dataset, run_id)
    assert config_path.exists()


def test_feature_warmup_rows_remain_null(storage_root_with_dataset: Path) -> None:
    runner = CliRunner()
    runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--lookback-bars",
            "5",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    features_path = (
        next((storage_root_with_dataset / "runs").iterdir()) / "stage_outputs" / "features.parquet"
    )
    table = pq.read_table(features_path)
    assert table.column("price_mean_5")[0].as_py() is None


def test_execute_json_output_schema(storage_root_with_dataset: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["run_type"] == "feature_build"
    assert data["status"] == "materialized"
    assert data["dataset_id"] == _DATASET_ID
    assert data["feature_set_version"] == "v1"
    assert isinstance(data["row_count"], int)
    assert isinstance(data["feature_count"], int)
    assert isinstance(data["feature_names"], list)


def test_run_manifest_links_feature_artifacts(storage_root_with_dataset: Path) -> None:
    """Run manifest must include feature_set_version and features artifact path."""
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v2",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    run_dirs = list((storage_root_with_dataset / "runs").iterdir())
    manifest = manifest_mod.read_run_manifest(run_dirs[0] / "manifest.json")
    assert manifest.run.run_type == "feature_build"
    assert "feature_set_version" in manifest.artifacts
    assert manifest.artifacts["feature_set_version"] == "v2"
    assert "features" in manifest.artifacts
    assert Path(manifest.artifacts["features"]).exists()


def test_run_manifest_parent_run_id_is_set(storage_root_with_dataset: Path) -> None:
    """parent_run_id in the manifest must reflect --parent-run-id flag."""
    parent_id = "parentabc123"
    runner = CliRunner()
    runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--parent-run-id",
            parent_id,
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    run_dirs = list((storage_root_with_dataset / "runs").iterdir())
    manifest = manifest_mod.read_run_manifest(run_dirs[0] / "manifest.json")
    assert manifest.parent_run_id == parent_id


# ---------------------------------------------------------------------------
# Tests — execute mode (empty dataset case)
# ---------------------------------------------------------------------------


def test_execute_empty_dataset_exits_zero(storage_root_with_empty_dataset: Path) -> None:
    """Empty trades table must produce zero feature rows without error."""
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_empty_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "materialized" in result.output


def test_execute_empty_dataset_produces_empty_features_parquet(
    storage_root_with_empty_dataset: Path,
) -> None:
    runner = CliRunner()
    runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_empty_dataset),
            "--execute",
        ],
    )
    features_path = (
        next((storage_root_with_empty_dataset / "runs").iterdir())
        / "stage_outputs"
        / "features.parquet"
    )
    table = pq.read_table(features_path)
    assert table.num_rows == 0
    assert "instrument_id" in table.schema.names


def test_execute_empty_dataset_manifest_row_count_is_zero(
    storage_root_with_empty_dataset: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_empty_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["row_count"] == 0


# ---------------------------------------------------------------------------
# Tests — error / fast-fail paths
# ---------------------------------------------------------------------------


def test_missing_dataset_exits_nonzero(tmp_path: Path) -> None:
    """Command must fail fast when the dataset directory is absent."""
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            "nonexistentdataset",
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )
    assert result.exit_code != 0
    assert "nonexistentdataset" in result.output


def test_missing_trades_parquet_exits_nonzero(tmp_path: Path) -> None:
    """Command must fail fast when trades.parquet is absent inside the dataset."""
    dataset_dir = tmp_path / "gold" / "datasets" / _DATASET_ID
    dataset_dir.mkdir(parents=True, exist_ok=True)
    # Dataset dir exists but trades.parquet is absent.
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )
    assert result.exit_code != 0
    assert "trades.parquet" in result.output


def test_execute_resolves_dataset_by_name(storage_root_with_named_dataset: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-features",
            "--dataset-id",
            "named_dataset",
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_named_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["dataset_id"] == _DATASET_ID


def test_invalid_lookback_bars_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--lookback-bars",
            "0",
        ],
    )
    assert result.exit_code != 0


def test_feature_output_schema_is_deterministic(storage_root_with_dataset: Path) -> None:
    """Same config must produce identical feature column names across two runs."""
    common_args = [
        "build-features",
        "--dataset-id",
        _DATASET_ID,
        "--feature-set-version",
        "v1",
        "--lookback-bars",
        "10",
        "--storage-root",
        str(storage_root_with_dataset),
        "--execute",
    ]
    runner = CliRunner()
    runner.invoke(research_main.main, common_args)

    run_dirs = sorted((storage_root_with_dataset / "runs").iterdir())
    t1 = pq.read_table(run_dirs[0] / "stage_outputs" / "features.parquet")

    runner.invoke(research_main.main, common_args)
    run_dirs = sorted((storage_root_with_dataset / "runs").iterdir())
    t2 = pq.read_table(run_dirs[1] / "stage_outputs" / "features.parquet")

    assert t1.schema.names == t2.schema.names


def test_late_recorded_events_are_ordered_by_availability(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "gold" / "datasets" / _DATASET_ID
    dataset_dir.mkdir(parents=True, exist_ok=True)
    late_event = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    ontime_event = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    table = pa.table(
        {
            "event_id": ["late", "ontime"],
            "instrument_id": ["p:m1:yes", "p:m1:yes"],
            "venue_id": ["p", "p"],
            "event_type": ["trade", "trade"],
            "ts_event": [late_event, ontime_event],
            "ts_record": [datetime(2026, 1, 1, 2, 0, tzinfo=UTC), ontime_event],
            "price": [0.10, 0.55],
            "size": [10.0, 11.0],
        },
        schema=_TRADES_SCHEMA,
    )
    pq.write_table(table, dataset_dir / "trades.parquet", compression="zstd")

    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--lookback-bars",
            "1",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output

    run_dir = next((tmp_path / "runs").iterdir())
    features = pq.read_table(run_dir / "stage_outputs" / "features.parquet")
    ts_events = features.column("ts_event").to_pylist()
    ts_available = features.column("ts_available").to_pylist()
    price_mean = features.column("price_mean_1").to_pylist()

    assert ts_available == sorted(ts_available)
    assert ts_events[0] == ontime_event
    assert price_mean[0] is None
    assert price_mean[1] == pytest.approx(0.55)


def test_execute_with_factor_pack_materializes_manifest_driven_columns(
    storage_root_with_dataset: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--factor-pack",
            "momentum",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = json.loads(result.output)["run_id"]

    features = pq.read_table(
        artifact_paths.artifact_key_path(
            storage_root_with_dataset,
            run_id,
            "features.parquet",
        )
    )
    assert "price_zscore_20" in features.schema.names
    assert "price_zscore_50" in features.schema.names
    assert "rolling_return_10" in features.schema.names
    assert "rolling_return_20" in features.schema.names

    run_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_root_with_dataset, run_id)
    )
    assert run_manifest.artifacts["factor_pack_id"] == "momentum"
    assert run_manifest.artifacts["factor_pack_version"] == "1.0.0"


def test_execute_with_pm_factor_pack_materializes_pm_native_columns(
    storage_root_with_pm_dataset: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--factor-pack",
            "pm_core",
            "--storage-root",
            str(storage_root_with_pm_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = json.loads(result.output)["run_id"]

    features = pq.read_table(
        artifact_paths.artifact_key_path(
            storage_root_with_pm_dataset,
            run_id,
            "features.parquet",
        )
    ).to_pandas()
    expected_columns = {
        "implied_prob_momentum_20",
        "cross_venue_spread",
        "volume_weighted_prob_20",
        "time_to_resolution_decay",
        "category_momentum_10",
        "book_imbalance_3",
        "prob_acceleration_5_20",
    }
    assert expected_columns.issubset(features.columns)
    assert features["cross_venue_spread"].notna().any()
    assert features["time_to_resolution_decay"].notna().any()
    assert features["book_imbalance_3"].notna().any()
    assert features["prob_acceleration_5_20"].notna().any()


def test_missing_factor_pack_exits_nonzero(storage_root_with_dataset: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--factor-pack",
            "missing_pack",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    assert result.exit_code != 0
    assert "missing_pack" in result.output


def test_execute_records_session_id_in_manifest_and_session_file(
    storage_root_with_dataset: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--session-id",
            "session_123",
            "--format",
            "json",
            "build-features",
            "--dataset-id",
            _DATASET_ID,
            "--feature-set-version",
            "v1",
            "--storage-root",
            str(storage_root_with_dataset),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = json.loads(result.output)["run_id"]

    run_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_root_with_dataset, run_id)
    )
    assert run_manifest.run.session_id == "session_123"

    session = session_mod.load_session(storage_root_with_dataset, "session_123")
    assert session.run_ids == [run_id]
