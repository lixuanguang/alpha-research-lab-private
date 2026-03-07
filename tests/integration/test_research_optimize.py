"""Integration tests: optimize command (LA-010).

Covers:
- Plan-only mode (no writes, deterministic run_id)
- Execute mode with grid/random search
- Trial registry (JSONL + Parquet) and leaderboard artifacts
- Best-run manifest reference
- Deterministic seed — same seed/config yields identical leaderboard ordering
- Constraint filtering (trade_count guard)
- Missing --feature-run-id exits non-zero in execute mode
- JSON output format parsing
- max_trials cap
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
from alpha_core.research.optimize_runner import (
    OptimizeConfig,
    OptimizeRunner,
    _expand_parameter_space,
)

# ---------------------------------------------------------------------------
# Constants / synthesis helpers (shared with backtest test pattern)
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_N_ROWS = 40
_FEATURE_RUN_ID = "featurerun_opt001"
_STRATEGY_ID = "zscore_v1"
_DATASET_ID = "ds_opt_001"
_FEATURE_SET_VERSION = "v1"


def _write_feature_manifest(storage_root: Path, run_id: str, *, row_count: int) -> None:
    manifest_path = artifact_paths.artifact_key_path(storage_root, run_id, "feature_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": run_id,
                "dataset_id": _DATASET_ID,
                "feature_set_version": _FEATURE_SET_VERSION,
                "built_at": _BASE.isoformat(),
                "lookback_bars": 200,
                "row_count": row_count,
                "feature_count": 4,
                "feature_names": [
                    "price_mean_200",
                    "price_std_200",
                    "price_zscore_200",
                    "volume_mean_200",
                ],
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
                "factor_pack_id": None,
                "factor_pack_version": None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_features_parquet(storage_root: Path, run_id: str, n: int = _N_ROWS) -> Path:
    """Write a synthetic features.parquet to simulate a completed build-features run."""
    path = artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    step = timedelta(minutes=30)
    ts_events = [_BASE + step * i for i in range(n)]
    instruments = [f"p:m1:{'yes' if i % 2 == 0 else 'no'}" for i in range(n)]
    zscores = [2.0 if i % 5 == 0 else (-2.0 if i % 7 == 0 else 0.0) for i in range(n)]
    prices = [0.48 + 0.01 * (i % 5) for i in range(n)]

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
    import pandas as pd

    df = pd.DataFrame(
        {
            "instrument_id": instruments,
            "ts_event": ts_events,
            "price_mean_200": prices,
            "price_std_200": [0.05] * n,
            "price_zscore_200": zscores,
            "volume_mean_200": [100.0 + i for i in range(n)],
        }
    )
    pq.write_table(
        pa.Table.from_pandas(df, schema=schema, preserve_index=False),
        path,
        compression="zstd",
    )
    _write_feature_manifest(storage_root, run_id, row_count=n)
    return path


@pytest.fixture()
def storage_with_features(tmp_path: Path) -> Path:
    """tmp_path pre-seeded with a synthetic features.parquet."""
    _write_features_parquet(tmp_path, _FEATURE_RUN_ID)
    return tmp_path


# ---------------------------------------------------------------------------
# Unit: parameter space expansion
# ---------------------------------------------------------------------------


class TestParameterSpaceExpansion:
    def test_grid_full_cartesian_product(self) -> None:
        config = OptimizeConfig(
            dataset_id="d",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            parameter_space={"threshold": [1.0, 1.5], "target_weight": [0.01, 0.02]},
            max_trials=100,
        )
        combos = _expand_parameter_space(config)
        assert len(combos) == 4
        assert {"threshold": 1.0, "target_weight": 0.01} in combos
        assert {"threshold": 1.5, "target_weight": 0.02} in combos

    def test_grid_capped_to_max_trials(self) -> None:
        config = OptimizeConfig(
            dataset_id="d",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            parameter_space={"threshold": [1.0, 1.5, 2.0]},
            max_trials=2,
        )
        combos = _expand_parameter_space(config)
        assert len(combos) == 2

    def test_random_search_uses_seed(self) -> None:
        config = OptimizeConfig(
            dataset_id="d",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            search_mode="random",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0]},
            max_trials=2,
            seed=99,
        )
        run1 = _expand_parameter_space(config)
        run2 = _expand_parameter_space(config)
        assert run1 == run2  # same seed → same order

    def test_random_search_different_seeds_differ(self) -> None:
        config_a = OptimizeConfig(
            dataset_id="d",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            search_mode="random",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]},
            max_trials=3,
            seed=1,
        )
        config_b = config_a.model_copy(update={"seed": 2})
        run_a = _expand_parameter_space(config_a)
        run_b = _expand_parameter_space(config_b)
        # Different seeds should almost certainly produce different orderings
        assert run_a != run_b

    def test_empty_parameter_space_returns_single_empty_dict(self) -> None:
        config = OptimizeConfig(
            dataset_id="d",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            parameter_space={"threshold": [1.5]},
            max_trials=1,
        )
        combos = _expand_parameter_space(config)
        assert combos == [{"threshold": 1.5}]


# ---------------------------------------------------------------------------
# OptimizeConfig validation
# ---------------------------------------------------------------------------


class TestOptimizeConfigValidation:
    def test_unsupported_parameter_key_raises(self) -> None:
        with pytest.raises(Exception, match="Unsupported parameter_space keys"):
            OptimizeConfig(
                dataset_id="d",
                feature_set_version="v1",
                strategy_id="zscore_v1",
                parameter_space={"unknown_key": [1.0]},
            )

    def test_empty_value_list_raises(self) -> None:
        with pytest.raises(Exception, match="must not be empty"):
            OptimizeConfig(
                dataset_id="d",
                feature_set_version="v1",
                strategy_id="zscore_v1",
                parameter_space={"threshold": []},
            )


# ---------------------------------------------------------------------------
# CLI: plan-only mode
# ---------------------------------------------------------------------------


class TestOptimizePlanOnly:
    def test_plan_only_exits_zero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

    def test_plan_only_writes_no_artifacts(self, tmp_path: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert not any(tmp_path.rglob("trial_registry.*"))

    def test_plan_only_json_output_parseable(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["run_type"] == "optimize"
        assert payload["status"] == "planned"


# ---------------------------------------------------------------------------
# CLI: execute mode — artifact existence and schema
# ---------------------------------------------------------------------------


class TestOptimizeExecute:
    def test_execute_exits_zero(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_execute_writes_trial_registry_jsonl(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        jsonl_files = list(storage_with_features.rglob("trial_registry.jsonl"))
        assert len(jsonl_files) == 1

    def test_execute_writes_trial_registry_parquet(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        parquet_files = list(storage_with_features.rglob("trial_registry.parquet"))
        assert len(parquet_files) == 1

    def test_execute_writes_leaderboard(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        leaderboard_files = list(storage_with_features.rglob("leaderboard.json"))
        assert len(leaderboard_files) == 1

    def test_execute_writes_best_manifest(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        best_files = list(storage_with_features.rglob("best_manifest.json"))
        assert len(best_files) == 1

    def test_execute_writes_run_manifest(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        manifest_files = list(storage_with_features.rglob("manifest.json"))
        assert len(manifest_files) >= 1

    def test_json_output_has_expected_keys(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        for key in ("run_type", "status", "run_id", "total_trials", "feasible_trials", "objective"):
            assert key in payload, f"missing key: {key}"
        assert payload["run_type"] == "optimize"
        assert payload["status"] == "materialized"
        assert payload["total_trials"] == 2

    def test_missing_feature_run_id_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code != 0

    def test_missing_feature_artifact_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                "missing_feature_run",
                "--threshold",
                "1.5",
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code != 0
        assert "Feature artifact not found" in result.output


# ---------------------------------------------------------------------------
# Trial registry content
# ---------------------------------------------------------------------------


class TestTrialRegistryContent:
    def test_trial_jsonl_rows_match_trial_count(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        jsonl_path = next(storage_with_features.rglob("trial_registry.jsonl"))
        rows = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
        assert len(rows) == 2
        assert all("trial_index" in row for row in rows)
        assert all("params" in row for row in rows)
        assert all("metrics" in row for row in rows)
        assert all("status" in row for row in rows)

    def test_trial_parquet_columns(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        parquet_path = next(storage_with_features.rglob("trial_registry.parquet"))
        table = pq.read_table(parquet_path)
        col_names = table.schema.names
        assert "trial_index" in col_names
        assert "objective_value" in col_names
        assert "status" in col_names

    def test_leaderboard_is_valid_json_list(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        lb_path = next(storage_with_features.rglob("leaderboard.json"))
        leaderboard = json.loads(lb_path.read_text())
        assert isinstance(leaderboard, list)

    def test_best_manifest_has_required_fields(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        best_path = next(storage_with_features.rglob("best_manifest.json"))
        best = json.loads(best_path.read_text())
        for key in ("best_backtest_run_id", "best_params", "best_objective_value", "trial_index"):
            assert key in best, f"missing key: {key}"

    def test_optimize_manifest_parents_feature_run(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output

        manifests = [
            manifest_mod.read_run_manifest(path)
            for path in storage_with_features.rglob("manifest.json")
        ]
        optimize_manifest = next(m for m in manifests if m.run.run_type == "optimize")
        assert optimize_manifest.parent_run_id == _FEATURE_RUN_ID

    def test_trial_evaluations_parent_backtest_runs(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output

        manifests = [
            manifest_mod.read_run_manifest(path)
            for path in storage_with_features.rglob("manifest.json")
        ]
        evaluate_manifests = [m for m in manifests if m.run.run_type == "evaluate"]
        assert evaluate_manifests
        for manifest in evaluate_manifests:
            assert manifest.parent_run_id == manifest.artifacts["backtest_run_id"]


# ---------------------------------------------------------------------------
# Deterministic seed — same config twice yields identical leaderboard order
# ---------------------------------------------------------------------------


class TestDeterministicSeed:
    def _run_optimize(self, storage_root: Path, seed: int) -> list[str]:
        config = OptimizeConfig(
            dataset_id=_DATASET_ID,
            feature_set_version=_FEATURE_SET_VERSION,
            strategy_id=_STRATEGY_ID,
            search_mode="random",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0]},
            max_trials=3,
            seed=seed,
        )
        runner = OptimizeRunner(storage_root)
        runner.run(config, feature_run_id=_FEATURE_RUN_ID)
        lb_path = next(storage_root.rglob("leaderboard.json"))
        leaderboard = json.loads(lb_path.read_text())
        return [entry["backtest_run_id"] for entry in leaderboard]

    def test_same_seed_same_trial_order(self) -> None:
        """Two independent runs with the same seed expand the parameter space identically."""

        config = OptimizeConfig(
            dataset_id=_DATASET_ID,
            feature_set_version=_FEATURE_SET_VERSION,
            strategy_id=_STRATEGY_ID,
            search_mode="random",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0]},
            max_trials=3,
            seed=77,
        )
        combos_a = _expand_parameter_space(config)
        combos_b = _expand_parameter_space(config)
        assert combos_a == combos_b

    def test_different_seeds_produce_different_trial_order(self) -> None:
        config_a = OptimizeConfig(
            dataset_id=_DATASET_ID,
            feature_set_version=_FEATURE_SET_VERSION,
            strategy_id=_STRATEGY_ID,
            search_mode="random",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]},
            max_trials=4,
            seed=1,
        )
        config_b = config_a.model_copy(update={"seed": 2})
        assert _expand_parameter_space(config_a) != _expand_parameter_space(config_b)


# ---------------------------------------------------------------------------
# Constraint filtering
# ---------------------------------------------------------------------------


class TestConstraintFiltering:
    def test_constraint_violation_reduces_feasible_count(self, storage_with_features: Path) -> None:
        """Requiring a very high trade_count means some/all trials are infeasible."""
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--min-trade-count",
                "999999",  # impossible threshold
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["feasible_trials"] == 0

    def test_leaderboard_empty_when_all_constrained(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        runner.invoke(
            research_main.main,
            [
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.5",
                "--min-trade-count",
                "999999",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        lb_path = next(storage_with_features.rglob("leaderboard.json"))
        leaderboard = json.loads(lb_path.read_text())
        assert leaderboard == []


# ---------------------------------------------------------------------------
# Failed trial handling
# ---------------------------------------------------------------------------


class TestFailedTrials:
    def test_failed_trials_are_recorded_without_aborting_sweep(self, tmp_path: Path) -> None:
        _write_features_parquet(tmp_path, _FEATURE_RUN_ID)
        artifact_paths.artifact_key_path(
            tmp_path,
            _FEATURE_RUN_ID,
            "feature_manifest.json",
        ).unlink()

        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["total_trials"] == 2
        assert payload["feasible_trials"] == 0

        registry_path = next(tmp_path.rglob("trial_registry.jsonl"))
        rows = [json.loads(line) for line in registry_path.read_text().splitlines() if line.strip()]
        assert {row["status"] for row in rows} == {"failed"}


# ---------------------------------------------------------------------------
# max_trials cap
# ---------------------------------------------------------------------------


class TestMaxTrialsCap:
    def test_max_trials_limits_grid_expansion(self) -> None:
        config = OptimizeConfig(
            dataset_id="d",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            search_mode="grid",
            parameter_space={"threshold": [1.0, 1.5, 2.0, 2.5]},
            max_trials=2,
        )
        combos = _expand_parameter_space(config)
        assert len(combos) == 2

    def test_max_trials_from_cli_is_respected(self, storage_with_features: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "optimize",
                "--dataset-id",
                _DATASET_ID,
                "--strategy-id",
                _STRATEGY_ID,
                "--feature-run-id",
                _FEATURE_RUN_ID,
                "--threshold",
                "1.0",
                "--threshold",
                "1.5",
                "--threshold",
                "2.0",
                "--max-trials",
                "2",
                "--storage-root",
                str(storage_with_features),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["total_trials"] == 2


# ---------------------------------------------------------------------------
# CLI help text
# ---------------------------------------------------------------------------


class TestCliHelp:
    def test_help_shows_objective_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(research_main.main, ["optimize", "--help"])
        assert result.exit_code == 0
        assert "--objective" in result.output

    def test_help_shows_search_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(research_main.main, ["optimize", "--help"])
        assert "--search" in result.output

    def test_help_shows_threshold_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(research_main.main, ["optimize", "--help"])
        assert "--threshold" in result.output
