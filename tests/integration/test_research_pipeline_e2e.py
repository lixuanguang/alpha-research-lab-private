"""End-to-end research pipeline integration test.

Covers the full research command chain on fixture data:

    build-features  →  backtest  →  evaluate

Artifact existence and schema assertions are made at each stage so a
regression in any intermediate step fails with a clear diagnostic.

Note: ``build-dataset`` materializes from live silver Parquet data and is
tested separately (``test_research_build_dataset.py``).  This test seeds the
gold dataset directory directly so the chain from ``build-features`` onward
runs against the real command implementations without external dependencies.
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

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_DATASET_ID = "e2edataset000001"  # stable fake dataset hash
_STRATEGY_ID = "zscore_momentum_v1"
_N_ROWS = 60  # enough rows for a meaningful lookback (default 200 bars still fine)

# Gold dataset path mirrors StorageTier.GOLD / "datasets" in storage_conventions.
_GOLD_SUBPATH = "gold/datasets"

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

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


def _write_gold_trades(storage_root: Path, dataset_id: str, n: int = _N_ROWS) -> Path:
    """Write a synthetic gold ``trades.parquet`` for *dataset_id*."""
    dataset_dir = storage_root / _GOLD_SUBPATH / dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=True)
    step = timedelta(minutes=30)
    ts_events = [_BASE + step * i for i in range(n)]
    instruments = [f"p:m1:{'yes' if i % 2 == 0 else 'no'}" for i in range(n)]
    trades_path = dataset_dir / "trades.parquet"
    pq.write_table(
        pa.table(
            {
                "event_id": [f"e{i:04d}" for i in range(n)],
                "instrument_id": instruments,
                "venue_id": ["p"] * n,
                "event_type": ["trade"] * n,
                "ts_event": ts_events,
                "ts_record": ts_events,
                "price": [0.48 + 0.01 * (i % 5) for i in range(n)],
                "size": [100.0 + i for i in range(n)],
            },
            schema=_TRADES_SCHEMA,
        ),
        trades_path,
        compression="zstd",
    )
    return trades_path


@pytest.fixture()
def storage_root(tmp_path: Path) -> Path:
    """tmp_path pre-seeded with a synthetic gold dataset."""
    _write_gold_trades(tmp_path, _DATASET_ID)
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers — run each command and return the emitted run_id
# ---------------------------------------------------------------------------


def _run_build_features(storage_root: Path, dataset_id: str) -> str:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "text",
            "build-features",
            "--dataset-id",
            dataset_id,
            "--storage-root",
            str(storage_root),
            "--execute",
        ],
    )
    assert result.exit_code == 0, f"build-features failed:\n{result.output}"
    run_id_token = next(t for t in result.output.split() if t.startswith("run_id="))
    return run_id_token.split("=", maxsplit=1)[1]


def _run_backtest(storage_root: Path, feature_run_id: str) -> str:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "text",
            "backtest",
            "--dataset-id",
            _DATASET_ID,
            "--strategy-id",
            _STRATEGY_ID,
            "--parent-run-id",
            feature_run_id,
            "--storage-root",
            str(storage_root),
            "--execute",
        ],
    )
    assert result.exit_code == 0, f"backtest failed:\n{result.output}"
    run_id_token = next(t for t in result.output.split() if t.startswith("run_id="))
    return run_id_token.split("=", maxsplit=1)[1]


def _run_evaluate(storage_root: Path, backtest_run_id: str) -> str:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "text",
            "evaluate",
            "--backtest-run-id",
            backtest_run_id,
            "--storage-root",
            str(storage_root),
            "--execute",
        ],
    )
    assert result.exit_code == 0, f"evaluate failed:\n{result.output}"
    run_id_token = next(t for t in result.output.split() if t.startswith("run_id="))
    return run_id_token.split("=", maxsplit=1)[1]


# ===========================================================================
# Tests
# ===========================================================================


class TestBuildFeaturesStage:
    """Validate the build-features stage of the pipeline."""

    def test_produces_features_parquet(self, storage_root: Path) -> None:
        run_id = _run_build_features(storage_root, _DATASET_ID)
        features_path = artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
        assert features_path.exists(), f"features.parquet missing at {features_path}"

    def test_features_parquet_has_required_columns(self, storage_root: Path) -> None:
        run_id = _run_build_features(storage_root, _DATASET_ID)
        features_path = artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
        table = pq.read_table(features_path)
        cols = set(table.schema.names)
        assert "instrument_id" in cols
        assert "ts_event" in cols
        # At least one rolling feature column should exist.
        assert any(c.startswith("price_zscore_") for c in cols), (
            f"No price_zscore_* column found. Columns: {sorted(cols)}"
        )

    def test_run_manifest_is_written(self, storage_root: Path) -> None:
        run_id = _run_build_features(storage_root, _DATASET_ID)
        manifest_path = artifact_paths.run_manifest_path(storage_root, run_id)
        assert manifest_path.exists()
        manifest = manifest_mod.read_run_manifest(manifest_path)
        assert manifest.run.run_type == "feature_build"
        assert "config" in manifest.artifacts
        assert "features" in manifest.artifacts

    def test_artifacts_index_is_written(self, storage_root: Path) -> None:
        run_id = _run_build_features(storage_root, _DATASET_ID)
        index = artifact_paths.read_artifacts_index(storage_root, run_id)
        assert "features" in index
        assert Path(index["features"]).exists()


class TestBacktestStage:
    """Validate the backtest stage, using build-features output as input."""

    @pytest.fixture()
    def feature_run_id(self, storage_root: Path) -> str:
        return _run_build_features(storage_root, _DATASET_ID)

    def test_produces_trades_parquet(self, storage_root: Path, feature_run_id: str) -> None:
        run_id = _run_backtest(storage_root, feature_run_id)
        trades_path = artifact_paths.artifact_key_path(storage_root, run_id, "trades.parquet")
        assert trades_path.exists()

    def test_produces_equity_parquet(self, storage_root: Path, feature_run_id: str) -> None:
        run_id = _run_backtest(storage_root, feature_run_id)
        equity_path = artifact_paths.artifact_key_path(storage_root, run_id, "equity.parquet")
        assert equity_path.exists()

    def test_trades_parquet_schema(self, storage_root: Path, feature_run_id: str) -> None:
        run_id = _run_backtest(storage_root, feature_run_id)
        trades_path = artifact_paths.artifact_key_path(storage_root, run_id, "trades.parquet")
        table = pq.read_table(trades_path)
        required = {"ts_event", "instrument_id", "direction", "size", "price"}
        assert required.issubset(set(table.schema.names)), (
            f"Missing columns: {required - set(table.schema.names)}"
        )

    def test_equity_parquet_schema(self, storage_root: Path, feature_run_id: str) -> None:
        run_id = _run_backtest(storage_root, feature_run_id)
        equity_path = artifact_paths.artifact_key_path(storage_root, run_id, "equity.parquet")
        table = pq.read_table(equity_path)
        required = {"ts_event", "equity", "cash"}
        assert required.issubset(set(table.schema.names)), (
            f"Missing columns: {required - set(table.schema.names)}"
        )

    def test_run_manifest_links_to_features(self, storage_root: Path, feature_run_id: str) -> None:
        run_id = _run_backtest(storage_root, feature_run_id)
        manifest_path = artifact_paths.run_manifest_path(storage_root, run_id)
        manifest = manifest_mod.read_run_manifest(manifest_path)
        assert manifest.run.run_type == "backtest"
        assert "config" in manifest.artifacts
        assert manifest.parent_run_id == feature_run_id

    def test_artifacts_index_has_trades_and_equity(
        self, storage_root: Path, feature_run_id: str
    ) -> None:
        run_id = _run_backtest(storage_root, feature_run_id)
        index = artifact_paths.read_artifacts_index(storage_root, run_id)
        assert "trades" in index
        assert "equity" in index
        assert Path(index["trades"]).exists()
        assert Path(index["equity"]).exists()


class TestEvaluateStage:
    """Validate the evaluate stage, using backtest output as input."""

    @pytest.fixture()
    def backtest_run_id(self, storage_root: Path) -> str:
        feature_run_id = _run_build_features(storage_root, _DATASET_ID)
        return _run_backtest(storage_root, feature_run_id)

    def test_produces_metrics_json(self, storage_root: Path, backtest_run_id: str) -> None:
        run_id = _run_evaluate(storage_root, backtest_run_id)
        metrics_path = artifact_paths.artifact_key_path(storage_root, run_id, "metrics.json")
        assert metrics_path.exists()

    def test_metrics_json_has_required_keys(self, storage_root: Path, backtest_run_id: str) -> None:
        run_id = _run_evaluate(storage_root, backtest_run_id)
        metrics_path = artifact_paths.artifact_key_path(storage_root, run_id, "metrics.json")
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics = data.get("metrics", {})
        required = {"total_return", "trade_count"}
        assert required.issubset(set(metrics.keys())), (
            f"Missing metric keys: {required - set(metrics.keys())}"
        )

    def test_metrics_json_pm_core_keys(self, storage_root: Path, backtest_run_id: str) -> None:
        run_id = _run_evaluate(storage_root, backtest_run_id)
        metrics_path = artifact_paths.artifact_key_path(storage_root, run_id, "metrics.json")
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        assert data.get("metrics_profile") == "pm_core"
        metrics = data.get("metrics", {})
        pm_core_keys = {"sharpe_ratio", "max_drawdown", "win_rate", "annualized_return"}
        assert pm_core_keys.issubset(set(metrics.keys())), (
            f"Missing pm_core keys: {pm_core_keys - set(metrics.keys())}"
        )

    def test_produces_metrics_parquet(self, storage_root: Path, backtest_run_id: str) -> None:
        run_id = _run_evaluate(storage_root, backtest_run_id)
        metrics_parquet_path = artifact_paths.artifact_key_path(
            storage_root, run_id, "metrics.parquet"
        )
        assert metrics_parquet_path.exists()

    def test_run_manifest_links_to_backtest(self, storage_root: Path, backtest_run_id: str) -> None:
        run_id = _run_evaluate(storage_root, backtest_run_id)
        manifest_path = artifact_paths.run_manifest_path(storage_root, run_id)
        manifest = manifest_mod.read_run_manifest(manifest_path)
        assert manifest.run.run_type == "evaluate"
        assert "config" in manifest.artifacts
        assert manifest.parent_run_id == backtest_run_id

    def test_artifacts_index_has_metrics(self, storage_root: Path, backtest_run_id: str) -> None:
        run_id = _run_evaluate(storage_root, backtest_run_id)
        index = artifact_paths.read_artifacts_index(storage_root, run_id)
        assert "metrics_json" in index
        assert Path(index["metrics_json"]).exists()


# ===========================================================================
# Full command chain — single test covering build-features → backtest → evaluate
# ===========================================================================


@pytest.mark.smoke
def test_full_research_command_chain(storage_root: Path) -> None:
    """Single test covering the complete implemented research command chain.

    build-features → backtest → evaluate

    Asserts:
    - All three stages exit zero.
    - Each stage's run manifest links to the previous stage's run_id.
    - Final evaluate artifacts contain the required metric keys.
    - All artifact files physically exist on disk.
    """
    # ---- Stage 1: build-features ----------------------------------------
    feature_run_id = _run_build_features(storage_root, _DATASET_ID)
    features_path = artifact_paths.artifact_key_path(
        storage_root, feature_run_id, "features.parquet"
    )
    assert features_path.exists(), "Stage 1: features.parquet absent"

    # ---- Stage 2: backtest -----------------------------------------------
    backtest_run_id = _run_backtest(storage_root, feature_run_id)
    trades_path = artifact_paths.artifact_key_path(storage_root, backtest_run_id, "trades.parquet")
    equity_path = artifact_paths.artifact_key_path(storage_root, backtest_run_id, "equity.parquet")
    assert trades_path.exists(), "Stage 2: trades.parquet absent"
    assert equity_path.exists(), "Stage 2: equity.parquet absent"

    bt_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_root, backtest_run_id)
    )
    assert bt_manifest.parent_run_id == feature_run_id, (
        "Stage 2 manifest.parent_run_id should point to the feature build run"
    )

    # ---- Stage 3: evaluate -----------------------------------------------
    evaluate_run_id = _run_evaluate(storage_root, backtest_run_id)
    metrics_path = artifact_paths.artifact_key_path(storage_root, evaluate_run_id, "metrics.json")
    assert metrics_path.exists(), "Stage 3: metrics.json absent"

    ev_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_root, evaluate_run_id)
    )
    assert ev_manifest.parent_run_id == backtest_run_id, (
        "Stage 3 manifest.parent_run_id should point to the backtest run"
    )

    # ---- Final artifact content assertions --------------------------------
    metrics_data = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics = metrics_data.get("metrics", {})

    required_keys = {"total_return", "trade_count", "sharpe_ratio", "max_drawdown", "win_rate"}
    missing = required_keys - set(metrics.keys())
    assert not missing, (
        f"metrics.json is missing required keys: {sorted(missing)}\n"
        f"Available: {sorted(metrics.keys())}"
    )

    # Sanity-check numeric types.
    assert isinstance(metrics["trade_count"], (int, float))
    assert isinstance(metrics["total_return"], float)


@pytest.mark.smoke
def test_lineage_chain_is_complete(storage_root: Path) -> None:
    """Assert that run_id lineage is traceable from evaluate back to build-features."""
    feature_run_id = _run_build_features(storage_root, _DATASET_ID)
    backtest_run_id = _run_backtest(storage_root, feature_run_id)
    evaluate_run_id = _run_evaluate(storage_root, backtest_run_id)

    # Walk the chain backward.
    ev_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_root, evaluate_run_id)
    )
    assert ev_manifest.parent_run_id is not None
    bt_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_root, ev_manifest.parent_run_id)
    )
    assert bt_manifest.parent_run_id is not None
    feat_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_root, bt_manifest.parent_run_id)
    )

    assert ev_manifest.parent_run_id == backtest_run_id
    assert bt_manifest.parent_run_id == feature_run_id
    assert feat_manifest.run.run_id == feature_run_id
    assert feat_manifest.run.run_type == "feature_build"
