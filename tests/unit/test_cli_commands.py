"""Unit tests for D6 CLI commands: backfill and detect-gaps."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import apps.data_collector.backfill as collector_backfill
import apps.data_collector.cli_support as collector_cli_support
import apps.data_collector.main as data_collector_main
import apps.research.main as research_main
import click.testing
import pyarrow as pa
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli_repo(tmp_path: Path) -> Path:
    """Minimal repo with config that includes a polymarket venue."""
    config_root = tmp_path / "config"
    (config_root / "environments").mkdir(parents=True)
    (config_root / "venues").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "alpha-research-lab"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (config_root / "default.yaml").write_text(
        "\n".join(
            [
                "project_name: alpha-research-lab",
                "log_level: INFO",
                "storage:",
                f"  base_path: {tmp_path / 'data'}",
                "venues:",
                "  - name: polymarket",
                "    exchange_class: Polymarket",
                "    enabled: true",
                "    rate_limit_rpm: 60",
            ]
        ),
        encoding="utf-8",
    )
    (config_root / "user_settings.yaml").write_text(
        "venue_enabled:\n  polymarket: true\n",
        encoding="utf-8",
    )
    return tmp_path


def _env(repo: Path) -> dict[str, str]:
    return {"ALPHA_RESEARCH_ROOT": str(repo)}


# ---------------------------------------------------------------------------
# --help tests
# ---------------------------------------------------------------------------


def test_backfill_help_exits_zero() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(data_collector_main.main, ["backfill", "--help"])
    assert result.exit_code == 0
    assert "--venue" in result.output
    assert "--outcomes" in result.output
    assert "--event-type" in result.output


def test_detect_gaps_help_exits_zero() -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(data_collector_main.main, ["detect-gaps", "--help"])
    assert result.exit_code == 0
    assert "--venue" in result.output
    assert "--start" in result.output
    assert "--end" in result.output


# ---------------------------------------------------------------------------
# backfill command
# ---------------------------------------------------------------------------


def test_backfill_rejects_invalid_start_datetime(cli_repo: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        data_collector_main.main,
        [
            "backfill",
            "--venue",
            "polymarket",
            "--outcomes",
            "polymarket:x:yes",
            "--start",
            "not-a-date",
            "--end",
            "2026-03-01T12:00:00Z",
        ],
        env=_env(cli_repo),
    )
    assert result.exit_code != 0


def test_backfill_rejects_unknown_venue(cli_repo: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        data_collector_main.main,
        [
            "backfill",
            "--venue",
            "unknown-venue",
            "--outcomes",
            "unknown:x:yes",
            "--start",
            "2026-03-01T10:00:00Z",
            "--end",
            "2026-03-01T12:00:00Z",
        ],
        env=_env(cli_repo),
    )
    assert result.exit_code != 0
    assert "unknown-venue" in result.output


def test_backfill_trades_succeeds_with_mocked_manager(
    cli_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = click.testing.CliRunner()

    dummy_result = collector_backfill.BackfillResult(
        venue="polymarket",
        event_type="trades",
        outcome_ids=["polymarket:market-a:yes"],
        window_start=datetime(2026, 3, 1, 10, tzinfo=UTC),
        window_end=datetime(2026, 3, 1, 12, tzinfo=UTC),
        events_fetched=100,
        events_stored=98,
        events_rejected=2,
        duration_seconds=0.5,
        run_id="run-test-123",
    )

    async def _fake_backfill(
        *_args: object, **_kwargs: object
    ) -> collector_backfill.BackfillResult:
        return dummy_result

    monkeypatch.setattr(
        "apps.data_collector.cli_support.collector_backfill.BackfillManager.backfill_trades",
        _fake_backfill,
    )

    # Provide a minimal adapter stand-in that satisfies venue_name()
    class _FakeAdapter:
        def venue_name(self) -> str:
            return "polymarket"

    monkeypatch.setattr(
        "apps.data_collector.cli_support.adapters_pmxt.PmxtAdapter",
        lambda *_a, **_kw: _FakeAdapter(),
    )

    result = runner.invoke(
        data_collector_main.main,
        [
            "backfill",
            "--venue",
            "polymarket",
            "--outcomes",
            "polymarket:market-a:yes",
            "--start",
            "2026-03-01T10:00:00Z",
            "--end",
            "2026-03-01T12:00:00Z",
        ],
        env=_env(cli_repo),
    )
    assert result.exit_code == 0, result.output
    assert "fetched=100" in result.output
    assert "stored=98" in result.output


def test_backfill_ohlcv_event_type_reaches_correct_method(
    cli_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = click.testing.CliRunner()
    called_with: list[str] = []

    dummy_result = collector_backfill.BackfillResult(
        venue="polymarket",
        event_type="ohlcv",
        outcome_ids=["polymarket:market-a:yes"],
        window_start=datetime(2026, 3, 1, 10, tzinfo=UTC),
        window_end=datetime(2026, 3, 1, 12, tzinfo=UTC),
        events_fetched=2,
        events_stored=2,
        events_rejected=0,
        duration_seconds=0.1,
        run_id="run-ohlcv-456",
    )

    async def _fake_backfill_ohlcv(*_a: object, **_kw: object) -> collector_backfill.BackfillResult:
        called_with.append("ohlcv")
        return dummy_result

    monkeypatch.setattr(
        "apps.data_collector.cli_support.collector_backfill.BackfillManager.backfill_ohlcv",
        _fake_backfill_ohlcv,
    )

    class _FakeAdapter:
        def venue_name(self) -> str:
            return "polymarket"

    monkeypatch.setattr(
        "apps.data_collector.cli_support.adapters_pmxt.PmxtAdapter",
        lambda *_a, **_kw: _FakeAdapter(),
    )

    result = runner.invoke(
        data_collector_main.main,
        [
            "backfill",
            "--venue",
            "polymarket",
            "--outcomes",
            "polymarket:market-a:yes",
            "--start",
            "2026-03-01T10:00:00Z",
            "--end",
            "2026-03-01T12:00:00Z",
            "--event-type",
            "ohlcv",
        ],
        env=_env(cli_repo),
    )
    assert result.exit_code == 0, result.output
    assert called_with == ["ohlcv"]


# ---------------------------------------------------------------------------
# detect-gaps command
# ---------------------------------------------------------------------------


def test_detect_gaps_rejects_invalid_datetime(cli_repo: Path) -> None:
    runner = click.testing.CliRunner()
    result = runner.invoke(
        data_collector_main.main,
        [
            "detect-gaps",
            "--venue",
            "polymarket",
            "--start",
            "bad-date",
            "--end",
            "2026-03-01T12:00:00Z",
        ],
        env=_env(cli_repo),
    )
    assert result.exit_code != 0


def test_detect_gaps_reports_no_data_found(cli_repo: Path) -> None:
    """When silver data is empty, detect-gaps reports no data found."""
    runner = click.testing.CliRunner()
    result = runner.invoke(
        data_collector_main.main,
        [
            "detect-gaps",
            "--venue",
            "polymarket",
            "--start",
            "2026-03-01T00:00:00Z",
            "--end",
            "2026-03-01T12:00:00Z",
        ],
        env=_env(cli_repo),
    )
    # No silver data → "No data found"
    assert result.exit_code == 0
    assert "No data found" in result.output


def test_detect_gaps_with_explicit_outcomes_and_no_gaps(
    cli_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = click.testing.CliRunner()

    monkeypatch.setattr(
        "apps.data_collector.cli_support.gap_detector_mod.GapDetector.detect_trade_gaps",
        lambda *_a, **_kw: [],
    )

    result = runner.invoke(
        data_collector_main.main,
        [
            "detect-gaps",
            "--venue",
            "polymarket",
            "--outcomes",
            "polymarket:market-a:yes",
            "--start",
            "2026-03-01T00:00:00Z",
            "--end",
            "2026-03-01T12:00:00Z",
        ],
        env=_env(cli_repo),
    )
    assert result.exit_code == 0
    assert "No gaps detected" in result.output


def test_detect_gaps_ohlcv_scans_ohlcv_instrument_ids(
    cli_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = click.testing.CliRunner()

    monkeypatch.setattr(
        "apps.data_collector.cli_support.parquet_reader_mod.ParquetEventReader.read_trades",
        lambda *_a, **_kw: pa.table(
            {
                "instrument_id": pa.array([], type=pa.string()),
                "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
            }
        ),
    )
    monkeypatch.setattr(
        "apps.data_collector.cli_support.parquet_reader_mod.ParquetEventReader.read_ohlcv",
        lambda *_a, **_kw: pa.table(
            {
                "instrument_id": pa.array(["polymarket:market-a:yes"]),
                "ts_event": pa.array([datetime(2026, 3, 1, 0, tzinfo=UTC)]),
                "resolution": pa.array(["1h"]),
            }
        ),
    )
    monkeypatch.setattr(
        "apps.data_collector.cli_support.gap_detector_mod.GapDetector.detect_ohlcv_gaps",
        lambda *_a, **_kw: [],
    )

    result = runner.invoke(
        data_collector_main.main,
        [
            "detect-gaps",
            "--venue",
            "polymarket",
            "--event-type",
            "ohlcv",
            "--start",
            "2026-03-01T00:00:00Z",
            "--end",
            "2026-03-01T12:00:00Z",
            "--resolution",
            "1h",
        ],
        env=_env(cli_repo),
    )
    assert result.exit_code == 0
    assert "No gaps detected" in result.output


def test_scan_instrument_ids_ignores_null_and_blank_values() -> None:
    class _ReaderStub:
        def read_trades(self, **_kwargs: object) -> pa.Table:
            return pa.table(
                {
                    "instrument_id": pa.array(
                        [None, "", "  ", "polymarket:market-a:yes", "polymarket:market-a:yes"]
                    ),
                    "ts_event": pa.array(
                        [
                            datetime(2026, 3, 1, 0, tzinfo=UTC),
                            datetime(2026, 3, 1, 0, tzinfo=UTC),
                            datetime(2026, 3, 1, 0, tzinfo=UTC),
                            datetime(2026, 3, 1, 1, tzinfo=UTC),
                            datetime(2026, 3, 1, 2, tzinfo=UTC),
                        ]
                    ),
                }
            )

        def read_ohlcv(self, **_kwargs: object) -> pa.Table:
            return pa.table(
                {
                    "instrument_id": pa.array([], type=pa.string()),
                    "ts_event": pa.array([], type=pa.timestamp("us", tz="UTC")),
                }
            )

    outcome_ids = collector_cli_support.scan_instrument_ids(
        _ReaderStub(),
        scope=collector_cli_support.GapScanScope(
            venue="polymarket",
            event_type="trades",
            start_dt=datetime(2026, 3, 1, 0, tzinfo=UTC),
            end_dt=datetime(2026, 3, 1, 12, tzinfo=UTC),
        ),
    )

    assert outcome_ids == ["polymarket:market-a:yes"]


# ---------------------------------------------------------------------------
# Research CLI smoke tests (LA-004)
# ---------------------------------------------------------------------------


_research_runner = click.testing.CliRunner()

_BUILD_DATASET_PLAN_ARGS = [
    "build-dataset",
    "--name",
    "smoke-ds",
    "--start",
    "2024-01-01T00:00:00",
    "--end",
    "2024-02-01T00:00:00",
    "--venue",
    "polymarket",
    "--event-type",
    "trades",
    "--plan-only",
]


def test_research_help_exits_zero() -> None:
    result = _research_runner.invoke(research_main.main, ["--help"])
    assert result.exit_code == 0
    assert "scaffolding" in result.output.lower()


def test_research_build_dataset_help_exits_zero() -> None:
    result = _research_runner.invoke(research_main.main, ["build-dataset", "--help"])
    assert result.exit_code == 0
    assert "dataset" in result.output.lower()


def test_research_invalid_config_path_exits_nonzero(tmp_path: Path) -> None:
    missing = str(tmp_path / "no-such-config.yaml")
    result = _research_runner.invoke(
        research_main.main,
        ["--config", missing, "build-dataset", "--help"],
    )
    assert result.exit_code != 0


def test_research_invalid_format_choice_exits_nonzero() -> None:
    result = _research_runner.invoke(
        research_main.main,
        ["--format", "csv", "build-dataset", "--help"],
    )
    assert result.exit_code != 0


def test_research_text_output_contains_key_value_pairs(tmp_path: Path) -> None:
    result = _research_runner.invoke(
        research_main.main,
        [*_BUILD_DATASET_PLAN_ARGS, "--storage-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "run_id=" in result.output
    assert "status=" in result.output


def test_research_json_output_is_valid_json(tmp_path: Path) -> None:
    result = _research_runner.invoke(
        research_main.main,
        ["--format", "json", *_BUILD_DATASET_PLAN_ARGS, "--storage-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "run_id" in payload
    assert "status" in payload
    assert "run_type" in payload
    assert "config_hash" in payload


def test_research_json_output_run_type_matches_command(tmp_path: Path) -> None:
    result = _research_runner.invoke(
        research_main.main,
        ["--format", "json", *_BUILD_DATASET_PLAN_ARGS, "--storage-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_type"] == "dataset_build"


def test_research_output_dir_overrides_storage_root(tmp_path: Path) -> None:
    output_root = tmp_path / "global-root"
    command_root = tmp_path / "command-root"
    result = _research_runner.invoke(
        research_main.main,
        [
            "--output-dir",
            str(output_root),
            "build-dataset",
            "--name",
            "scaffold-ds",
            "--start",
            "2024-01-01T00:00:00",
            "--end",
            "2024-02-01T00:00:00",
            "--storage-root",
            str(command_root),
            "--execute",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (output_root / "runs").exists()
    assert not (command_root / "runs").exists()


def test_research_invalid_yaml_config_exits_nonzero(tmp_path: Path) -> None:
    invalid_config = tmp_path / "broken.yaml"
    invalid_config.write_text("venues: [", encoding="utf-8")
    result = _research_runner.invoke(
        research_main.main,
        [
            "--config",
            str(invalid_config),
            "build-dataset",
            "--name",
            "broken-config",
            "--start",
            "2024-01-01T00:00:00",
            "--end",
            "2024-02-01T00:00:00",
            "--plan-only",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid research config override" in result.output


def test_research_config_override_changes_config_hash(tmp_path: Path) -> None:
    config_a = tmp_path / "config_a.yaml"
    config_b = tmp_path / "config_b.yaml"
    config_a.write_text("research:\n  mode: a\n", encoding="utf-8")
    config_b.write_text("research:\n  mode: b\n", encoding="utf-8")

    result_a = _research_runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "--config",
            str(config_a),
            "build-dataset",
            "--name",
            "cfg-a",
            "--start",
            "2024-01-01T00:00:00",
            "--end",
            "2024-02-01T00:00:00",
            "--plan-only",
        ],
    )
    result_b = _research_runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "--config",
            str(config_b),
            "build-dataset",
            "--name",
            "cfg-a",
            "--start",
            "2024-01-01T00:00:00",
            "--end",
            "2024-02-01T00:00:00",
            "--plan-only",
        ],
    )

    assert result_a.exit_code == 0, result_a.output
    assert result_b.exit_code == 0, result_b.output
    payload_a = json.loads(result_a.output)
    payload_b = json.loads(result_b.output)
    assert payload_a["config_hash"] != payload_b["config_hash"]


def test_research_report_json_output_run_type_matches_command(tmp_path: Path) -> None:
    result = _research_runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "report",
            "--evaluation-run-id",
            "eval-run-001",
            "--storage-root",
            str(tmp_path),
            "--plan-only",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_type"] == "report"
