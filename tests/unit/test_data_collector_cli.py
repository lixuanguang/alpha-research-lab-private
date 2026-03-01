"""Unit tests for data collector CLI wiring."""

from __future__ import annotations

from pathlib import Path

import apps.data_collector.main as data_collector_main
import click.testing as click_testing
import pytest


@pytest.fixture
def temp_cli_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    config_root = repo_root / "config"
    (config_root / "environments").mkdir(parents=True)
    (config_root / "venues").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "alpha-research-lab"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (config_root / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                "  base_path: data",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    enabled: true",
                "    rate_limit_rpm: 60",
                "  - name: kalshi",
                "    exchange_class: Kalshi",
                "    enabled: false",
                "    rate_limit_rpm: 60",
            ]
        ),
        encoding="utf-8",
    )
    (config_root / "user_settings.yaml").write_text(
        "\n".join(
            [
                "venue_enabled:",
                "  polymarket: true",
                "  kalshi: false",
            ]
        ),
        encoding="utf-8",
    )
    return repo_root


def _cli_env(repo_root: Path) -> dict[str, str]:
    return {"ALPHA_RESEARCH_ROOT": str(repo_root)}


def test_run_and_validate_commands_use_loaded_settings(temp_cli_repo: Path) -> None:
    runner = click_testing.CliRunner()

    run_result = runner.invoke(
        data_collector_main.main,
        ["run", "--ignore-user-settings"],
        env=_cli_env(temp_cli_repo),
    )
    validate_result = runner.invoke(
        data_collector_main.main,
        ["validate", "--ignore-user-settings"],
        env=_cli_env(temp_cli_repo),
    )

    assert run_result.exit_code == 0
    assert "Run configuration ready" in run_result.output
    assert "venues=polymarket" in run_result.output
    assert validate_result.exit_code == 0
    assert "Configuration valid" in validate_result.output
    assert "All required secrets resolved" in validate_result.output


def test_status_backfill_and_detect_gaps_commands_return_expected_output(
    temp_cli_repo: Path,
) -> None:
    runner = click_testing.CliRunner()
    env = _cli_env(temp_cli_repo)

    status_result = runner.invoke(data_collector_main.main, ["status"], env=env)
    backfill_result = runner.invoke(
        data_collector_main.main,
        [
            "backfill",
            "--venue",
            "polymarket",
            "--instrument-id",
            "polymarket:market-a:yes",
            "--start",
            "2026-02-28T00:00:00Z",
            "--end",
            "2026-02-28T01:00:00Z",
        ],
        env=env,
    )
    detect_gaps_result = runner.invoke(
        data_collector_main.main,
        ["detect-gaps", "--venue", "polymarket"],
        env=env,
    )

    assert status_result.exit_code == 0
    assert "Enabled venues (1): polymarket" in status_result.output
    assert "Disabled venues (1): kalshi" in status_result.output
    assert backfill_result.exit_code == 0
    assert "Backfill request captured" in backfill_result.output
    assert detect_gaps_result.exit_code == 0
    assert "Gap detection inputs accepted" in detect_gaps_result.output


def test_run_command_execute_path_reports_completion(
    temp_cli_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = click_testing.CliRunner()

    async def _fake_run_polling_pipelines(*_args: object, **_kwargs: object) -> int:
        return 7

    monkeypatch.setattr(
        data_collector_main.collector_runtime,
        "run_polling_pipelines",
        _fake_run_polling_pipelines,
    )

    result = runner.invoke(
        data_collector_main.main,
        ["run", "--ignore-user-settings", "--execute"],
        env=_cli_env(temp_cli_repo),
    )

    assert result.exit_code == 0
    assert "Execution complete (mode=once, successful_runs=7)" in result.output


def test_run_command_rejects_invalid_max_outcomes(temp_cli_repo: Path) -> None:
    runner = click_testing.CliRunner()
    result = runner.invoke(
        data_collector_main.main,
        ["run", "--max-outcomes-per-venue", "0"],
        env=_cli_env(temp_cli_repo),
    )

    assert result.exit_code != 0
    assert "--max-outcomes-per-venue" in result.output


def test_run_command_rejects_invalid_request_timeout(temp_cli_repo: Path) -> None:
    runner = click_testing.CliRunner()
    result = runner.invoke(
        data_collector_main.main,
        ["run", "--request-timeout-seconds", "0"],
        env=_cli_env(temp_cli_repo),
    )

    assert result.exit_code != 0
    assert "--request-timeout-seconds" in result.output
