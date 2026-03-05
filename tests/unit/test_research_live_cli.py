"""CLI scaffolding tests for research and live entrypoints."""

from __future__ import annotations

from pathlib import Path

import apps.live_system.main as live_main
import apps.research.main as research_main
import click.testing


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


def test_research_optimize_execute_writes_manifest(tmp_path: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "optimize",
            "--dataset-id",
            "dataset_a",
            "--feature-set",
            "feature_set_a",
            "--strategy-id",
            "strategy_a",
            "--storage-root",
            str(tmp_path),
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "run_type=optimize" in result.output
    assert "status=materialized" in result.output
    manifest_line = next(
        line for line in result.output.splitlines() if line.startswith("manifest=")
    )
    manifest_path = Path(manifest_line.split("=", maxsplit=1)[1].strip())
    assert manifest_path.exists()


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
    assert "orders=6" in result.output


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
    assert "orders=2" in status_result.output
