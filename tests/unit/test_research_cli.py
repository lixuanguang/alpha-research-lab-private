"""Unit tests for the research CLI — help, arg validation, output format.

Focuses on R6 contract coverage:
- All stage commands surface a --help with no errors.
- Required flags fail fast with exit code 2.
- ``--format json`` propagates to subcommands.
- plan-only mode exits 0 and emits a parseable run summary.
"""

from __future__ import annotations

from pathlib import Path

import apps.research.main as research_main
from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# --help smoke tests
# ---------------------------------------------------------------------------


def test_root_help_lists_all_stage_commands() -> None:
    result = _runner().invoke(research_main.main, ["--help"])
    assert result.exit_code == 0, result.output
    for cmd in ("build-dataset", "build-features", "backtest", "evaluate", "report", "optimize"):
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
    import json

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
