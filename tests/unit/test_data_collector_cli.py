"""Unit tests for data collector CLI wiring."""

from __future__ import annotations

from pathlib import Path

import apps.data_collector.main as data_collector_main
import click.testing as click_testing
import pytest

import alpha_core.storage.lineage as storage_lineage


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


def test_validate_command_accepts_data_quality_window_flags(temp_cli_repo: Path) -> None:
    runner = click_testing.CliRunner()
    result = runner.invoke(
        data_collector_main.main,
        [
            "validate",
            "--ignore-user-settings",
            "--venue",
            "polymarket",
            "--since",
            "2026-02-28T00:00:00Z",
        ],
        env=_cli_env(temp_cli_repo),
    )

    assert result.exit_code == 0
    assert "Configuration valid" in result.output
    assert "Data quality validation: no matching silver data" in result.output


def test_status_command_returns_expected_venue_summary(
    temp_cli_repo: Path,
) -> None:
    runner = click_testing.CliRunner()
    env = _cli_env(temp_cli_repo)

    status_result = runner.invoke(data_collector_main.main, ["status"], env=env)

    assert status_result.exit_code == 0
    assert "Enabled venues (1): polymarket" in status_result.output
    assert "Disabled venues (1): kalshi" in status_result.output
    assert "Runtime metrics (24h): no ingestion runs recorded." in status_result.output


def test_backfill_command_rejects_missing_outcomes(temp_cli_repo: Path) -> None:
    runner = click_testing.CliRunner()
    # --outcomes is now required; invoking without it must fail
    result = runner.invoke(
        data_collector_main.main,
        [
            "backfill",
            "--venue",
            "polymarket",
            "--start",
            "2026-02-28T00:00:00Z",
            "--end",
            "2026-02-28T01:00:00Z",
        ],
        env=_cli_env(temp_cli_repo),
    )
    assert result.exit_code != 0


def test_detect_gaps_command_rejects_missing_window(temp_cli_repo: Path) -> None:
    runner = click_testing.CliRunner()
    # --start and --end are now required
    result = runner.invoke(
        data_collector_main.main,
        ["detect-gaps", "--venue", "polymarket"],
        env=_cli_env(temp_cli_repo),
    )
    assert result.exit_code != 0


def test_status_command_reports_recent_runtime_metrics(temp_cli_repo: Path) -> None:
    lineage_store = storage_lineage.LineageStore(temp_cli_repo / "data")
    run = lineage_store.start_run(
        venue="polymarket",
        connector_type="polling",
        options=storage_lineage.StartRunOptions(event_types=["trades"]),
    )
    lineage_store.complete_run(
        run.run_id,
        counts={"events_raw": 12, "events_silver": 11, "rejected": 1},
        errors=[],
    )

    runner = click_testing.CliRunner()
    status_result = runner.invoke(
        data_collector_main.main,
        ["status"],
        env=_cli_env(temp_cli_repo),
    )

    assert status_result.exit_code == 0
    assert "Runtime metrics (24h): total_runs=1, completed=1, failed=0, running=0" in (
        status_result.output
    )
    assert "Recent run: venue=polymarket, status=completed" in status_result.output


def test_run_command_execute_path_reports_completion(
    temp_cli_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = click_testing.CliRunner()

    async def _fake_run_polling_pipelines(*_args: object, **_kwargs: object) -> int:
        return 7

    monkeypatch.setattr(
        "apps.data_collector.main.collector_runtime.run_polling_pipelines",
        _fake_run_polling_pipelines,
    )

    result = runner.invoke(
        data_collector_main.main,
        ["run", "--ignore-user-settings", "--execute"],
        env=_cli_env(temp_cli_repo),
    )

    assert result.exit_code == 0
    assert "Execution complete (collection_mode=poll, run_mode=once, successful_runs=7)" in (
        result.output
    )


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
