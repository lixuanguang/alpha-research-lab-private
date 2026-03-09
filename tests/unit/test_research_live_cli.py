"""CLI scaffolding tests for research and live entrypoints."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import apps.live_system.main as live_main
import apps.research.main as research_main
import click.testing

import alpha_core.evaluation.evaluator as evaluator_mod
import alpha_core.evaluation.financial as financial_mod
import alpha_core.evaluation.pm_metrics as pm_metrics_mod
import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.evaluate_runner as evaluate_runner_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.run_context as run_context_mod


def _write_evaluate_artifacts(storage_root: Path, run_id: str) -> None:
    report = evaluator_mod.EvaluationReport(
        backtest_id="bt_run_a",
        strategy_name="strategy_a",
        financial=financial_mod.FinancialMetrics(
            total_return=Decimal("0"),
            annualised_return=Decimal("0"),
            volatility=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            max_drawdown=Decimal("0"),
            max_drawdown_duration_days=0,
            total_trades=10,
            win_rate=0.5,
            profit_factor=Decimal("1"),
            avg_trade_pnl=Decimal("0"),
            avg_holding_period_hours=0.0,
        ),
        pm_specific=pm_metrics_mod.PMMetrics(
            brier_score=0.0,
            log_loss=0.0,
            calibration_error=0.0,
        ),
    )
    report_path = artifact_paths.artifact_key_path(storage_root, run_id, "report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    evaluate_manifest = evaluate_runner_mod.EvaluateManifest(
        run_id=run_id,
        backtest_run_id="bt_run_a",
        metrics_profile="pm_core",
        built_at=report.evaluated_at,
        metrics={"total_return": 0.05, "trade_count": 10.0},
        artifacts={},
        parent_run_id="bt_run_a",
    )
    artifact_paths.artifact_key_path(storage_root, run_id, "evaluate_manifest.json").write_text(
        evaluate_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )


def test_research_cli_help_lists_stage_commands() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(research_main.main, ["--help"])

    assert result.exit_code == 0
    assert "build-dataset" in result.output
    assert "build-features" in result.output
    assert "backtest" in result.output
    assert "evaluate" in result.output
    assert "report" in result.output
    assert "optimize" in result.output
    assert "list-datasets" in result.output
    assert "list-features" in result.output
    assert "list-backtests" in result.output


def test_research_build_dataset_plan_only_emits_run_summary(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-dataset",
            "--name",
            "r1_scaffold",
            "--start",
            "2026-03-01T00:00:00Z",
            "--end",
            "2026-03-02T00:00:00Z",
            "--storage-root",
            str(tmp_path),
            "--plan-only",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "run_type=dataset_build" in result.output
    assert "status=planned" in result.output


def test_research_optimize_execute_with_missing_feature_run_fails(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "optimize",
            "--dataset-id",
            "dataset_a",
            "--feature-set-version",
            "v1",
            "--strategy-id",
            "strategy_a",
            "--feature-run-id",
            "nonexistent_feature_run",
            "--threshold",
            "1.5",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )

    assert result.exit_code != 0
    assert "Feature artifact not found" in result.output


def test_research_report_execute_writes_report_manifest(tmp_path: Path) -> None:
    eval_run_id = "eval_run_a"
    _write_evaluate_artifacts(tmp_path, eval_run_id)

    runner = click.testing.CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "report",
            "--evaluation-run-id",
            eval_run_id,
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "run_type=report" in result.output
    # Extract run_id from text output: "run_type=report  status=materialized  run_id=<id>  ..."
    run_id_token = next(t for t in result.output.split() if t.startswith("run_id="))
    run_id = run_id_token.split("=", maxsplit=1)[1]
    manifest_path = artifact_paths.run_manifest_path(tmp_path, run_id)
    manifest = manifest_mod.read_run_manifest(manifest_path)
    assert manifest.run.run_type == "report"
    assert manifest.parent_run_id == eval_run_id


def test_research_report_rejects_metrics_path_outside_run_root(tmp_path: Path) -> None:
    eval_run_context = run_context_mod.close_run_context(
        run_context_mod.make_run_context("evaluate", config_payload={"kind": "unit_test"})
    )
    eval_run_id = eval_run_context.run_id
    rogue_manifest_path = tmp_path / "rogue_evaluate_manifest.json"
    rogue_manifest_path.write_text(
        evaluate_runner_mod.EvaluateManifest(
            run_id=eval_run_id,
            backtest_run_id="bt_run_a",
            metrics_profile="pm_core",
            built_at=eval_run_context.started_at_utc,
            metrics={"total_return": 0.05, "trade_count": 10.0},
            artifacts={},
            parent_run_id="bt_run_a",
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    manifest_mod.write_run_manifest(
        artifact_paths.run_manifest_path(tmp_path, eval_run_id),
        manifest_mod.RunManifest(
            run=eval_run_context,
            artifacts={"evaluate_manifest": str(rogue_manifest_path)},
        ),
    )

    runner = click.testing.CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "report",
            "--evaluation-run-id",
            eval_run_id,
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )

    assert result.exit_code != 0
    assert "invalid" in result.output.lower()


def test_live_cli_help_lists_runtime_commands() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(live_main.main, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "status" in result.output


def test_live_run_plan_only_emits_summary(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        live_main.main,
        [
            "run",
            "--instrument",
            "polymarket:market-a:yes",
            "--instrument",
            "kalshi:market-b:no",
            "--cycles",
            "3",
            "--storage-root",
            str(tmp_path),
            "--plan-only",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "status=planned" in result.output
    assert "orders_emitted=6" in result.output


def test_live_run_execute_json_uses_persisted_artifact_keys(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        live_main.main,
        [
            "--format",
            "json",
            "run",
            "--instrument",
            "polymarket:market-a:yes",
            "--strategy-id",
            "zscore_v1",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_keys"] == ["config", "live_summary", "strategy_id"]
    assert "manifest" not in payload["artifact_keys"]
    assert payload["extra"]["strategy_id"] == "zscore_v1"


def test_live_status_reports_materialized_run(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    run_result = runner.invoke(
        live_main.main,
        [
            "run",
            "--instrument",
            "polymarket:market-a:yes",
            "--cycles",
            "2",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )
    assert run_result.exit_code == 0, run_result.output

    status_result = runner.invoke(
        live_main.main,
        ["status", "--storage-root", str(tmp_path), "--limit", "1"],
    )
    assert status_result.exit_code == 0, status_result.output
    assert "status=materialized" in status_result.output
    assert "cycles=2" in status_result.output
    assert "orders=2" in status_result.output


def test_live_status_ignores_summary_paths_outside_run_root(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    run_result = runner.invoke(
        live_main.main,
        [
            "run",
            "--instrument",
            "polymarket:market-a:yes",
            "--cycles",
            "2",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )
    assert run_result.exit_code == 0, run_result.output

    manifest_line = next(
        line for line in run_result.output.splitlines() if line.startswith("manifest=")
    )
    manifest_path = Path(manifest_line.split("=", maxsplit=1)[1].strip())
    manifest = manifest_mod.read_run_manifest(manifest_path)

    rogue_summary_path = tmp_path / "rogue_summary.json"
    rogue_summary_path.write_text(
        json.dumps({"cycles": 99, "orders_emitted": 99}, indent=2),
        encoding="utf-8",
    )
    manifest.artifacts["live_summary"] = str(rogue_summary_path)
    manifest_mod.write_run_manifest(manifest_path, manifest)

    status_result = runner.invoke(
        live_main.main,
        ["status", "--storage-root", str(tmp_path), "--limit", "1"],
    )
    assert status_result.exit_code == 0, status_result.output
    assert "cycles=0" in status_result.output
    assert "orders=0" in status_result.output


def test_live_status_tolerates_invalid_summary_json(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    run_result = runner.invoke(
        live_main.main,
        [
            "run",
            "--instrument",
            "polymarket:market-a:yes",
            "--cycles",
            "2",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )
    assert run_result.exit_code == 0, run_result.output

    manifest_line = next(
        line for line in run_result.output.splitlines() if line.startswith("manifest=")
    )
    manifest_path = Path(manifest_line.split("=", maxsplit=1)[1].strip())
    manifest = manifest_mod.read_run_manifest(manifest_path)
    summary_path = Path(manifest.artifacts["live_summary"])
    summary_path.write_text("{not valid json", encoding="utf-8")

    status_result = runner.invoke(
        live_main.main,
        ["status", "--storage-root", str(tmp_path), "--limit", "1"],
    )
    assert status_result.exit_code == 0, status_result.output
    assert "cycles=0" in status_result.output
    assert "orders=0" in status_result.output
