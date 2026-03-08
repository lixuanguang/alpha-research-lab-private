"""Unit tests for apps.research.reporting.writer — ReportWriter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from apps.research.reporting.writer import ReportNotFoundError, ReportWriter

from alpha_core.evaluation.evaluator import BacktestEvaluator, EvaluationReport

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_equity() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_event": _BASE, "equity": 1000.0},
            {"ts_event": _BASE + timedelta(days=1), "equity": 1100.0},
        ]
    )


def _make_trades(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_event": _BASE + timedelta(hours=i),
                "instrument_id": f"mkt_{i}",
                "direction": "long",
                "price": 0.6,
                "size": 1,
                "realized_pnl": 10.0,
            }
            for i in range(n)
        ]
    )


def _make_report(
    backtest_id: str = "bt_abc",
    strategy_name: str = "test_strat",
) -> EvaluationReport:
    evaluator = BacktestEvaluator()
    return evaluator.evaluate(
        backtest_id=backtest_id,
        strategy_name=strategy_name,
        trades_df=_make_trades(),
        equity_df=_make_equity(),
        starting_cash=1000.0,
    )


# ---------------------------------------------------------------------------
# Write → load round-trip
# ---------------------------------------------------------------------------


def test_write_and_load_round_trip(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    report = _make_report()
    run_id = "run_test_001"

    path = writer.write(report, run_id)

    assert path.exists()
    assert path.name == "report.json"

    loaded = writer.load(run_id)
    assert loaded.backtest_id == report.backtest_id
    assert loaded.strategy_name == report.strategy_name
    assert loaded.schema_version == report.schema_version
    assert loaded.financial.sharpe_ratio == report.financial.sharpe_ratio
    assert loaded.pm_specific.brier_score == report.pm_specific.brier_score


def test_write_creates_metrics_json(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    report = _make_report()
    run_id = "run_metrics_check"
    writer.write(report, run_id)

    metrics_path = tmp_path / "runs" / run_id / "stage_outputs" / "metrics.json"
    assert metrics_path.exists()
    data = json.loads(metrics_path.read_text())
    assert "sharpe_ratio" in data
    assert "brier_score" in data
    assert "backtest_id" in data


# ---------------------------------------------------------------------------
# load — missing report
# ---------------------------------------------------------------------------


def test_load_missing_report_raises_not_found(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    with pytest.raises(ReportNotFoundError):
        writer.load("nonexistent_run_id")


# ---------------------------------------------------------------------------
# list_reports
# ---------------------------------------------------------------------------


def test_list_reports_empty_when_no_runs(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    assert writer.list_reports() == []


def test_list_reports_returns_written_run_ids(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    ids = ["run_zzz", "run_aaa", "run_mmm"]
    for rid in ids:
        writer.write(_make_report(backtest_id=rid), rid)

    listed = writer.list_reports()
    assert set(listed) == set(ids)


def test_list_reports_sorted(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    for rid in ["run_c", "run_a", "run_b"]:
        writer.write(_make_report(backtest_id=rid), rid)
    listed = writer.list_reports()
    assert listed == sorted(listed)


# ---------------------------------------------------------------------------
# Multiple writes to same run_id are idempotent
# ---------------------------------------------------------------------------


def test_overwrite_existing_report(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    run_id = "run_overwrite"
    r1 = _make_report(backtest_id="bt_v1", strategy_name="v1")
    r2 = _make_report(backtest_id="bt_v2", strategy_name="v2")
    writer.write(r1, run_id)
    writer.write(r2, run_id)

    loaded = writer.load(run_id)
    assert loaded.backtest_id == "bt_v2"


# ---------------------------------------------------------------------------
# storage_root with nested structure
# ---------------------------------------------------------------------------


def test_writer_creates_directories_automatically(tmp_path: Path) -> None:
    deep_root = tmp_path / "deep" / "nested" / "root"
    writer = ReportWriter(deep_root)
    writer.write(_make_report(), "run_deep")
    assert (deep_root / "runs" / "run_deep" / "stage_outputs" / "report.json").exists()
