"""Unit tests for the research CLI — help, arg validation, output format.

Focuses on R6 contract coverage:
- All stage commands surface a --help with no errors.
- Required flags fail fast with exit code 2.
- ``--format json`` propagates to subcommands.
- plan-only mode exits 0 and emits a parseable run summary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import apps.research.main as research_main
from click.testing import CliRunner

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.backtest_runner as backtest_runner_mod
import alpha_core.research.dataset as dataset_mod
import alpha_core.research.feature_runner as feature_runner_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod

_BASE = datetime(2026, 1, 1, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner() -> CliRunner:
    return CliRunner()


def _persist_dataset(storage_root: Path) -> None:
    dataset_dir = storage_root / "gold" / "datasets" / "ds_cli"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    manifest = dataset_mod.DatasetManifest(
        run_id="dataset_run_cli",
        dataset_id="ds_cli",
        config=dataset_mod.DatasetConfig(
            name="cli_dataset",
            start=_BASE,
            end=_BASE + timedelta(days=1),
        ),
        built_at=_BASE,
        row_counts={"trades": 10},
        instrument_count=3,
        date_range=(_BASE, _BASE + timedelta(days=1)),
        quality_summary={},
        schema_version=1,
    )
    (dataset_dir / "_meta.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def _persist_feature_run(storage_root: Path) -> None:
    run_id = "feature_run_cli"
    feature_manifest_path = artifact_paths.artifact_key_path(
        storage_root, run_id, "feature_manifest.json"
    )
    feature_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    feature_manifest = feature_runner_mod.FeatureManifest(
        run_id=run_id,
        dataset_id="ds_cli",
        feature_set_version="v1",
        built_at=_BASE,
        lookback_bars=20,
        row_count=100,
        feature_count=8,
        feature_names=["price_zscore_20"],
        artifacts={
            "features": str(
                artifact_paths.artifact_key_path(storage_root, run_id, "features.parquet")
            )
        },
        factor_pack_id="pm_core",
        factor_pack_version="1.0.0",
    )
    feature_manifest.artifacts["feature_manifest"] = str(feature_manifest_path)
    feature_manifest_path.write_text(feature_manifest.model_dump_json(indent=2), encoding="utf-8")
    manifest_mod.persist_run_record(
        storage_root=storage_root,
        run_context=run_context_mod.RunContext(
            run_id=run_id,
            run_type="feature_build",
            config_hash="cfg",
            git_commit="abc1234",
            started_at_utc=_BASE,
            completed_at_utc=_BASE,
        ),
        config_payload={"dataset_id": "ds_cli"},
        artifacts={
            "feature_manifest": str(feature_manifest_path),
            "dataset_id": "ds_cli",
            "feature_set_version": "v1",
        },
        parent_run_id="dataset_run_cli",
    )


def _persist_backtest_run(storage_root: Path) -> None:
    run_id = "backtest_run_cli"
    backtest_manifest_path = artifact_paths.artifact_key_path(
        storage_root, run_id, "backtest_manifest.json"
    )
    backtest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    backtest_manifest = backtest_runner_mod.BacktestManifest(
        run_id=run_id,
        dataset_id="ds_cli",
        feature_set_version="v1",
        strategy_id="zscore_v1",
        engine="event",
        starting_cash=1000.0,
        built_at=_BASE,
        trade_count=12,
        final_equity=1042.5,
        total_return=0.0425,
        artifacts={
            "trades": str(artifact_paths.artifact_key_path(storage_root, run_id, "trades.parquet"))
        },
        parent_run_id="feature_run_cli",
    )
    backtest_manifest.artifacts["backtest_manifest"] = str(backtest_manifest_path)
    backtest_manifest_path.write_text(backtest_manifest.model_dump_json(indent=2), encoding="utf-8")
    manifest_mod.persist_run_record(
        storage_root=storage_root,
        run_context=run_context_mod.RunContext(
            run_id=run_id,
            run_type="backtest",
            config_hash="cfg",
            git_commit="abc1234",
            started_at_utc=_BASE,
            completed_at_utc=_BASE,
        ),
        config_payload={"dataset_id": "ds_cli"},
        artifacts={
            "backtest_manifest": str(backtest_manifest_path),
            "dataset_id": "ds_cli",
            "feature_set_version": "v1",
            "strategy_id": "zscore_v1",
        },
        parent_run_id="feature_run_cli",
    )


# ---------------------------------------------------------------------------
# --help smoke tests
# ---------------------------------------------------------------------------


def test_root_help_lists_all_stage_commands() -> None:
    result = _runner().invoke(research_main.main, ["--help"])
    assert result.exit_code == 0, result.output
    for cmd in (
        "build-dataset",
        "build-features",
        "backtest",
        "evaluate",
        "report",
        "optimize",
        "list-datasets",
        "list-features",
        "list-backtests",
    ):
        assert cmd in result.output, f"Expected '{cmd}' in --help output"


def test_build_dataset_help() -> None:
    result = _runner().invoke(research_main.main, ["build-dataset", "--help"])
    assert result.exit_code == 0, result.output
    assert "--name" in result.output
    assert "--start" in result.output
    assert "--end" in result.output


def test_build_features_help() -> None:
    result = _runner().invoke(research_main.main, ["build-features", "--help"])
    assert result.exit_code == 0, result.output
    assert "--dataset-id" in result.output or "--dataset" in result.output


def test_backtest_help() -> None:
    result = _runner().invoke(research_main.main, ["backtest", "--help"])
    assert result.exit_code == 0, result.output
    assert "--strategy-id" in result.output or "--strategy" in result.output
    assert "--engine" in result.output


def test_evaluate_help() -> None:
    result = _runner().invoke(research_main.main, ["evaluate", "--help"])
    assert result.exit_code == 0, result.output


def test_report_help() -> None:
    result = _runner().invoke(research_main.main, ["report", "--help"])
    assert result.exit_code == 0, result.output


def test_optimize_help() -> None:
    result = _runner().invoke(research_main.main, ["optimize", "--help"])
    assert result.exit_code == 0, result.output
    assert "--objective" in result.output or "--primary-metric" in result.output
    assert "--max-trials" in result.output


def test_list_datasets_help() -> None:
    result = _runner().invoke(research_main.main, ["list-datasets", "--help"])
    assert result.exit_code == 0, result.output


def test_list_features_help() -> None:
    result = _runner().invoke(research_main.main, ["list-features", "--help"])
    assert result.exit_code == 0, result.output


def test_list_backtests_help() -> None:
    result = _runner().invoke(research_main.main, ["list-backtests", "--help"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Missing required args → exit code 2
# ---------------------------------------------------------------------------


def test_build_dataset_missing_name_fails() -> None:
    result = _runner().invoke(
        research_main.main,
        ["build-dataset", "--start", "2026-01-01T00:00:00", "--end", "2026-01-02T00:00:00"],
    )
    assert result.exit_code == 2, result.output


def test_backtest_missing_strategy_id_fails(tmp_path: Path) -> None:
    result = _runner().invoke(
        research_main.main,
        ["backtest", "--dataset-id", "ds001", "--storage-root", str(tmp_path)],
    )
    assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------
# JSON format propagation
# ---------------------------------------------------------------------------


def test_json_format_propagates_to_build_dataset(tmp_path: Path) -> None:
    """--format json on root group causes subcommand output to be valid JSON."""
    result = _runner().invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-dataset",
            "--name",
            "test_json",
            "--start",
            "2026-01-01T00:00:00Z",
            "--end",
            "2026-01-02T00:00:00Z",
            "--storage-root",
            str(tmp_path),
            "--plan-only",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "run_id" in payload or "status" in payload or "run_type" in payload


def test_list_datasets_json_output(tmp_path: Path) -> None:
    _persist_dataset(tmp_path)

    result = _runner().invoke(
        research_main.main,
        ["--format", "json", "list-datasets", "--storage-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["dataset_id"] == "ds_cli"
    assert payload[0]["name"] == "cli_dataset"


def test_list_features_json_output(tmp_path: Path) -> None:
    _persist_feature_run(tmp_path)

    result = _runner().invoke(
        research_main.main,
        ["--format", "json", "list-features", "--storage-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["run_id"] == "feature_run_cli"
    assert payload[0]["feature_count"] == 8


def test_list_backtests_json_output(tmp_path: Path) -> None:
    _persist_backtest_run(tmp_path)

    result = _runner().invoke(
        research_main.main,
        ["--format", "json", "list-backtests", "--storage-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["run_id"] == "backtest_run_cli"
    assert payload[0]["strategy_id"] == "zscore_v1"
