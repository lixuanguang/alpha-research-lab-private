"""Integration tests: backtest → evaluate → report command chain.

Verifies that each command:
- Emits a planned outcome in plan-only mode (no writes).
- Materializes the correct artifacts in execute mode.
- Produces machine-readable JSON output.
- Fails fast with non-zero exit when required upstream artifacts are missing.

The command chain tested end-to-end:
    build-features → backtest → evaluate → report
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import apps.research.main as research_main
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from click.testing import CliRunner

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.manifest as manifest_mod

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_N_ROWS = 30


def _write_feature_manifest(
    storage_root: Path,
    run_id: str,
    *,
    feature_names: list[str],
    row_count: int,
    factor_pack_id: str | None = None,
    factor_pack_version: str | None = None,
) -> None:
    manifest_path = artifact_paths.artifact_key_path(storage_root, run_id, "feature_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": run_id,
                "dataset_id": "deadbeef01234567",
                "feature_set_version": "v1",
                "built_at": _BASE.isoformat(),
                "lookback_bars": 200,
                "row_count": row_count,
                "feature_count": len(feature_names),
                "feature_names": feature_names,
                "artifacts": {
                    "features": str(
                        artifact_paths.artifact_key_path(
                            storage_root,
                            run_id,
                            "features.parquet",
                        )
                    )
                },
                "parent_run_id": None,
                "factor_pack_id": factor_pack_id,
                "factor_pack_version": factor_pack_version,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_features_parquet(storage_root: Path, run_id: str, n: int = _N_ROWS) -> Path:
    """Write a synthetic features.parquet into a fake run's stage_outputs dir."""
    path = artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    step = timedelta(minutes=30)
    ts_events = [_BASE + step * i for i in range(n)]
    instruments = [f"p:m1:{'yes' if i % 2 == 0 else 'no'}" for i in range(n)]
    # Vary zscore to produce both long/short signals (threshold ±1.5).
    zscores = [2.0 if i % 5 == 0 else (-2.0 if i % 7 == 0 else 0.0) for i in range(n)]
    prices = [0.48 + 0.01 * (i % 5) for i in range(n)]
    df_data = {
        "instrument_id": instruments,
        "ts_event": ts_events,
        "price_mean_200": prices,
        "price_std_200": [0.05] * n,
        "price_zscore_200": zscores,
        "volume_mean_200": [100.0 + i for i in range(n)],
    }
    schema = pa.schema(
        [
            pa.field("instrument_id", pa.string()),
            pa.field("ts_event", pa.timestamp("us", tz="UTC")),
            pa.field("price_mean_200", pa.float64()),
            pa.field("price_std_200", pa.float64()),
            pa.field("price_zscore_200", pa.float64()),
            pa.field("volume_mean_200", pa.float64()),
        ]
    )
    table = pa.Table.from_pandas(pd.DataFrame(df_data), schema=schema, preserve_index=False)
    pq.write_table(table, path, compression="zstd")
    _write_feature_manifest(
        storage_root,
        run_id,
        feature_names=[
            "price_mean_200",
            "price_std_200",
            "price_zscore_200",
            "volume_mean_200",
        ],
        row_count=n,
    )
    return path


def _write_recipe_features_parquet(storage_root: Path, run_id: str, n: int = _N_ROWS) -> Path:
    path = artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    step = timedelta(hours=1)
    ts_events = [_BASE + step * i for i in range(n)]
    zscores = [2.0 if i % 2 == 0 else -2.0 for i in range(n)]
    prices = [0.48 + 0.01 * (i % 5) for i in range(n)]
    table = pa.Table.from_pandas(
        pd.DataFrame(
            {
                "instrument_id": ["p:m1:yes"] * n,
                "ts_event": ts_events,
                "price": prices,
                "price_zscore_20": zscores,
                "price_zscore_50": zscores,
                "rolling_return_10": [0.01] * n,
                "rolling_return_20": [0.02] * n,
            }
        ),
        preserve_index=False,
    )
    pq.write_table(table, path, compression="zstd")
    _write_feature_manifest(
        storage_root,
        run_id,
        feature_names=[
            "price_zscore_20",
            "price_zscore_50",
            "rolling_return_10",
            "rolling_return_20",
        ],
        row_count=n,
        factor_pack_id="momentum",
        factor_pack_version="1.0.0",
    )
    return path


def _write_empty_features_parquet(storage_root: Path, run_id: str) -> Path:
    """Write an empty features.parquet."""
    path = artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            pa.field("instrument_id", pa.string()),
            pa.field("ts_event", pa.timestamp("us", tz="UTC")),
            pa.field("price_mean_200", pa.float64()),
            pa.field("price_std_200", pa.float64()),
            pa.field("price_zscore_200", pa.float64()),
            pa.field("volume_mean_200", pa.float64()),
        ]
    )
    pq.write_table(
        pa.table({name: [] for name in schema.names}, schema=schema),
        path,
        compression="zstd",
    )
    return path


_FEATURE_RUN_ID = "featurerun0000001"
_BT_STRATEGY = "zscore_v1"


@pytest.fixture()
def storage_with_features(tmp_path: Path) -> Path:
    _write_features_parquet(tmp_path, _FEATURE_RUN_ID)
    return tmp_path


@pytest.fixture()
def storage_with_empty_features(tmp_path: Path) -> Path:
    _write_empty_features_parquet(tmp_path, _FEATURE_RUN_ID)
    return tmp_path


@pytest.fixture()
def storage_with_recipe_features(tmp_path: Path) -> Path:
    _write_recipe_features_parquet(tmp_path, _FEATURE_RUN_ID)
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers: run command chain and collect run_ids
# ---------------------------------------------------------------------------


def _run_backtest(storage_root: Path, parent_run_id: str = _FEATURE_RUN_ID) -> str:
    """Execute backtest and return its run_id."""
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "backtest",
            "--dataset-id",
            "deadbeef01234567",
            "--feature-set-version",
            "v1",
            "--strategy-id",
            _BT_STRATEGY,
            "--parent-run-id",
            parent_run_id,
            "--storage-root",
            str(storage_root),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["run_id"]


def _first_feature_timestamp(storage_root: Path, run_id: str) -> datetime:
    table = pq.read_table(
        artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
    )
    return table.column("ts_event")[0].as_py()


def _run_evaluate(storage_root: Path, backtest_run_id: str) -> str:
    """Execute evaluate and return its run_id."""
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "evaluate",
            "--backtest-run-id",
            backtest_run_id,
            "--storage-root",
            str(storage_root),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["run_id"]


def _run_report(storage_root: Path, evaluate_run_id: str) -> str:
    """Execute report and return its run_id."""
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "report",
            "--evaluation-run-id",
            evaluate_run_id,
            "--storage-root",
            str(storage_root),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["run_id"]


# ===========================================================================
# BACKTEST tests
# ===========================================================================


class TestBacktest:
    def test_plan_only_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "planned" in result.output

    def test_plan_only_json(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "planned"
        assert data["run_type"] == "backtest"

    def test_plan_only_no_files(self, tmp_path: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert not (tmp_path / "runs").exists()

    def test_execute_exits_zero(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "materialized" in result.output

    def test_execute_writes_trades_and_equity(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        trades_path = artifact_paths.artifact_key_path(
            storage_with_features, bt_run_id, "trades.parquet"
        )
        equity_path = artifact_paths.artifact_key_path(
            storage_with_features, bt_run_id, "equity.parquet"
        )
        assert trades_path.exists(), "trades.parquet must be written"
        assert equity_path.exists(), "equity.parquet must be written"

    def test_execute_json_output_has_required_keys(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["run_type"] == "backtest"
        assert data["status"] == "materialized"
        assert "run_id" in data
        assert "trade_count" in data
        assert "final_equity" in data
        assert "total_return" in data

    def test_run_manifest_links_artifacts(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        mpath = artifact_paths.run_manifest_path(storage_with_features, bt_run_id)
        manifest = manifest_mod.read_run_manifest(mpath)
        assert manifest.run.run_type == "backtest"
        assert "config" in manifest.artifacts
        assert "trades" in manifest.artifacts
        assert "equity" in manifest.artifacts
        assert Path(manifest.artifacts["config"]).exists()
        assert Path(manifest.artifacts["trades"]).exists()
        assert Path(manifest.artifacts["equity"]).exists()
        assert manifest.parent_run_id == _FEATURE_RUN_ID

    def test_first_fill_is_delayed_until_next_observation(
        self,
        storage_with_features: Path,
    ) -> None:
        first_feature_ts = _first_feature_timestamp(storage_with_features, _FEATURE_RUN_ID)
        bt_run_id = _run_backtest(storage_with_features)
        trades_table = pq.read_table(
            artifact_paths.artifact_key_path(storage_with_features, bt_run_id, "trades.parquet")
        )
        if trades_table.num_rows == 0:
            pytest.fail("Expected at least one simulated trade for delayed-fill assertion")
        first_trade_ts = trades_table.column("ts_event")[0].as_py()
        assert first_trade_ts > first_feature_ts

    def test_vectorized_engine_executes_successfully(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--engine",
                "vectorized",
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["engine"] == "vectorized"

    def test_empty_features_exits_zero(self, storage_with_empty_features: Path) -> None:
        """Empty feature input must not crash — produces zero trades."""
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_empty_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["trade_count"] == 0

    def test_missing_parent_run_id_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code != 0

    def test_missing_features_artifact_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--parent-run-id",
                "nonexistentrun123",
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code != 0
        assert "nonexistentrun123" in result.output

    def test_invalid_starting_cash_exits_nonzero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "abc",
                "--strategy-id",
                _BT_STRATEGY,
                "--starting-cash",
                "0",
            ],
        )
        assert result.exit_code != 0

    def test_strategy_recipe_applies_manifest_parameters_and_costs(
        self,
        storage_with_recipe_features: Path,
    ) -> None:
        runner = CliRunner()
        plain_result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "backtest",
                "--dataset-id",
                "deadbeef01234567",
                "--feature-set-version",
                "v1",
                "--strategy-id",
                "zscore_momentum_v1",
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_recipe_features),
                "--execute",
            ],
        )
        assert plain_result.exit_code == 0, plain_result.output
        plain_run_id = json.loads(plain_result.output)["run_id"]

        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "backtest",
                "--dataset-id",
                "deadbeef01234567",
                "--feature-set-version",
                "v1",
                "--strategy-id",
                "zscore_momentum_v1",
                "--strategy-recipe",
                "zscore_momentum",
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_recipe_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        recipe_run_id = json.loads(result.output)["run_id"]

        plain_trades = pq.read_table(
            artifact_paths.artifact_key_path(
                storage_with_recipe_features,
                plain_run_id,
                "trades.parquet",
            )
        )
        recipe_trades = pq.read_table(
            artifact_paths.artifact_key_path(
                storage_with_recipe_features,
                recipe_run_id,
                "trades.parquet",
            )
        )
        assert plain_trades.num_rows > 0
        assert recipe_trades.num_rows > 0
        assert recipe_trades.column("size")[0].as_py() > plain_trades.column("size")[0].as_py()
        assert recipe_trades.column("price")[0].as_py() != plain_trades.column("price")[0].as_py()

        run_manifest = manifest_mod.read_run_manifest(
            artifact_paths.run_manifest_path(storage_with_recipe_features, recipe_run_id)
        )
        assert run_manifest.artifacts["strategy_recipe_id"] == "zscore_momentum"
        assert run_manifest.artifacts["strategy_recipe_version"] == "1.0.0"

    def test_missing_strategy_recipe_exits_nonzero(
        self,
        storage_with_recipe_features: Path,
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "deadbeef01234567",
                "--feature-set-version",
                "v1",
                "--strategy-id",
                _BT_STRATEGY,
                "--strategy-recipe",
                "missing_recipe",
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_recipe_features),
                "--execute",
            ],
        )
        assert result.exit_code != 0
        assert "missing_recipe" in result.output

    def test_strategy_recipe_rejects_generic_feature_artifacts(
        self,
        storage_with_features: Path,
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "backtest",
                "--dataset-id",
                "deadbeef01234567",
                "--feature-set-version",
                "v1",
                "--strategy-id",
                "zscore_momentum_v1",
                "--strategy-recipe",
                "zscore_momentum",
                "--parent-run-id",
                _FEATURE_RUN_ID,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code != 0
        assert "factor_pack_id" in result.output


# ===========================================================================
# EVALUATE tests
# ===========================================================================


class TestEvaluate:
    def test_plan_only_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(research_main.main, ["evaluate", "--backtest-run-id", "fakeid"])
        assert result.exit_code == 0, result.output
        assert "planned" in result.output

    def test_plan_only_json(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main, ["--format", "json", "evaluate", "--backtest-run-id", "fakeid"]
        )
        data = json.loads(result.output)
        assert data["status"] == "planned"
        assert data["run_type"] == "evaluate"

    def test_execute_exits_zero(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "evaluate",
                "--backtest-run-id",
                bt_run_id,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "materialized" in result.output

    def test_execute_writes_metrics_artifacts(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
        metrics_json = artifact_paths.artifact_key_path(
            storage_with_features, ev_run_id, "metrics.json"
        )
        metrics_pq = artifact_paths.artifact_key_path(
            storage_with_features, ev_run_id, "metrics.parquet"
        )
        assert metrics_json.exists(), "metrics.json must be written"
        assert metrics_pq.exists(), "metrics.parquet must be written"

    def test_execute_json_output_has_metrics(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "evaluate",
                "--backtest-run-id",
                bt_run_id,
                "--metrics-profile",
                "pm_core",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["run_type"] == "evaluate"
        assert data["status"] == "materialized"
        assert "metrics" in data
        metrics = data["metrics"]
        for key in ("total_return", "trade_count", "sharpe_ratio", "max_drawdown", "win_rate"):
            assert key in metrics, f"Expected metric '{key}' in pm_core output"

    def test_minimal_profile_subset(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "evaluate",
                "--backtest-run-id",
                bt_run_id,
                "--metrics-profile",
                "minimal",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        data = json.loads(result.output)
        assert "total_return" in data["metrics"]
        assert "trade_count" in data["metrics"]
        # Minimal profile must NOT include sharpe_ratio.
        assert "sharpe_ratio" not in data["metrics"]

    def test_run_manifest_links_to_backtest(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
        mpath = artifact_paths.run_manifest_path(storage_with_features, ev_run_id)
        manifest = manifest_mod.read_run_manifest(mpath)
        assert manifest.run.run_type == "evaluate"
        assert "config" in manifest.artifacts
        assert "metrics_json" in manifest.artifacts
        assert Path(manifest.artifacts["config"]).exists()
        assert manifest.parent_run_id == bt_run_id

    def test_missing_backtest_artifacts_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "evaluate",
                "--backtest-run-id",
                "nonexistentbt123",
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code != 0
        assert "nonexistentbt123" in result.output

    def test_empty_backtest_produces_zero_metrics(self, storage_with_empty_features: Path) -> None:
        """Empty backtest (zero trades) must still produce valid metrics."""
        bt_run_id = _run_backtest(storage_with_empty_features)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "evaluate",
                "--backtest-run-id",
                bt_run_id,
                "--storage-root",
                str(storage_with_empty_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["metrics"]["trade_count"] == 0.0


# ===========================================================================
# REPORT tests
# ===========================================================================


class TestReport:
    def test_plan_only_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(research_main.main, ["report", "--evaluation-run-id", "fakeid"])
        assert result.exit_code == 0, result.output
        assert "planned" in result.output

    def test_plan_only_json(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main, ["--format", "json", "report", "--evaluation-run-id", "fakeid"]
        )
        data = json.loads(result.output)
        assert data["status"] == "planned"
        assert data["run_type"] == "report"

    def test_execute_exits_zero(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "report",
                "--evaluation-run-id",
                ev_run_id,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "materialized" in result.output

    def test_execute_writes_report_file(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
        rpt_run_id = _run_report(storage_with_features, ev_run_id)
        report_path = artifact_paths.artifact_key_path(
            storage_with_features, rpt_run_id, "report.json"
        )
        assert report_path.exists(), "report.json must be written"

    def test_execute_json_output_has_summary(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "report",
                "--evaluation-run-id",
                ev_run_id,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["run_type"] == "report"
        assert data["status"] == "materialized"
        assert "summary" in data
        assert "evaluation_run_id" in data

    def test_report_file_is_deterministic(self, storage_with_features: Path) -> None:
        """Same evaluation_run_id must produce identical report payloads."""
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)

        runner = CliRunner()
        r1 = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "report",
                "--evaluation-run-id",
                ev_run_id,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        r2 = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "report",
                "--evaluation-run-id",
                ev_run_id,
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        d1 = json.loads(r1.output)
        d2 = json.loads(r2.output)
        # Summary values must be identical across two invocations.
        assert d1["summary"] == d2["summary"]

    def test_markdown_report_is_written(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "report",
                "--evaluation-run-id",
                ev_run_id,
                "--report-format",
                "markdown",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        # Find the report.md artifact.
        run_dirs = sorted((storage_with_features / "runs").iterdir())
        report_files = [
            f for d in run_dirs for f in (d / "stage_outputs").glob("report.md") if f.exists()
        ]
        assert report_files, "report.md must be written for markdown format"
        content = report_files[-1].read_text(encoding="utf-8")
        assert "# Research Report" in content

    def test_report_run_manifest_links_evaluate(self, storage_with_features: Path) -> None:
        bt_run_id = _run_backtest(storage_with_features)
        ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
        rpt_run_id = _run_report(storage_with_features, ev_run_id)
        mpath = artifact_paths.run_manifest_path(storage_with_features, rpt_run_id)
        manifest = manifest_mod.read_run_manifest(mpath)
        assert manifest.run.run_type == "report"
        assert "config" in manifest.artifacts
        assert manifest.parent_run_id == ev_run_id
        assert Path(manifest.artifacts["config"]).exists()
        assert "report" in manifest.artifacts

    def test_missing_evaluate_run_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "report",
                "--evaluation-run-id",
                "nonexistentev123",
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code != 0


# ===========================================================================
# END-TO-END chain test
# ===========================================================================


def test_full_command_chain(storage_with_features: Path) -> None:
    """backtest → evaluate → report all succeed and link via parent_run_id."""
    bt_run_id = _run_backtest(storage_with_features)
    ev_run_id = _run_evaluate(storage_with_features, bt_run_id)
    rpt_run_id = _run_report(storage_with_features, ev_run_id)

    # Backtest manifest.
    bt_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_with_features, bt_run_id)
    )
    # Evaluate manifest.
    ev_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_with_features, ev_run_id)
    )
    # Report manifest.
    rpt_manifest = manifest_mod.read_run_manifest(
        artifact_paths.run_manifest_path(storage_with_features, rpt_run_id)
    )

    # Lineage chain.
    assert bt_manifest.parent_run_id == _FEATURE_RUN_ID
    assert ev_manifest.parent_run_id == bt_run_id
    assert rpt_manifest.parent_run_id == ev_run_id

    # All artifact files exist.
    for key in ("trades", "equity"):
        assert Path(bt_manifest.artifacts[key]).exists(), f"Backtest artifact '{key}' missing"
    assert Path(ev_manifest.artifacts["metrics_json"]).exists()
    assert Path(rpt_manifest.artifacts["report"]).exists()

    # Metrics payload is non-trivially populated.
    metrics_raw = json.loads(
        Path(ev_manifest.artifacts["metrics_json"]).read_text(encoding="utf-8")
    )
    assert "total_return" in metrics_raw["metrics"]
    assert "sharpe_ratio" in metrics_raw["metrics"]
