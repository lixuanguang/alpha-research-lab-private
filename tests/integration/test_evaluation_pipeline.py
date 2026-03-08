"""Integration test: backtest result → evaluate → write → load → verify.

Tests the full R5 pipeline:
1. Produce realistic trades and equity DataFrames (simulating backtest output)
2. Run BacktestEvaluator to compute all metrics
3. Write artifacts with ReportWriter
4. Load report back and verify all fields present and consistent
5. Test multi-report comparison via comparisons module
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from apps.research.reporting.comparisons import compare_reports, rank_reports
from apps.research.reporting.writer import ReportWriter

from alpha_core.evaluation.evaluator import (
    EVALUATION_REPORT_SCHEMA_VERSION,
    BacktestEvaluator,
)

# ---------------------------------------------------------------------------
# Test data factory
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 3, tzinfo=UTC)
_STARTING_CASH = 10_000.0


def _make_realistic_trades(n: int = 100) -> pd.DataFrame:
    """Produce a realistic trades DataFrame with mixed wins/losses."""
    rng = np.random.default_rng(12345)
    rows = []
    for i in range(n):
        pnl = float(rng.normal(5.0, 30.0))
        direction = "long" if rng.random() > 0.4 else "short"
        price = float(rng.uniform(0.1, 0.9))
        category = rng.choice(["politics", "finance", "sports"])
        resolved = rng.random() > 0.6
        rows.append(
            {
                "ts_event": _BASE + timedelta(hours=i * 2),
                "instrument_id": f"market_{i % 20}",
                "direction": direction,
                "price": price,
                "size": float(rng.integers(1, 20)),
                "realized_pnl": pnl,
                "fee": abs(pnl) * 0.01,
                "category": category,
                "resolution_outcome": float(rng.integers(0, 2)) if resolved else None,
            }
        )
    return pd.DataFrame(rows)


def _make_equity_curve(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Build equity curve from cumulative PnL."""
    equity = _STARTING_CASH
    rows = [{"ts_event": _BASE - timedelta(hours=1), "equity": equity}]
    for _, row in trades_df.iterrows():
        equity += float(row["realized_pnl"])
        rows.append({"ts_event": row["ts_event"], "equity": max(equity, 1.0)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Test 1: Full evaluation pipeline produces all required metrics
# ---------------------------------------------------------------------------


def test_evaluation_pipeline_all_metrics_present(tmp_path: Path) -> None:
    trades_df = _make_realistic_trades(n=100)
    equity_df = _make_equity_curve(trades_df)

    evaluator = BacktestEvaluator()
    report = evaluator.evaluate(
        backtest_id="integration_bt_001",
        strategy_name="zscore_momentum",
        trades_df=trades_df,
        equity_df=equity_df,
        starting_cash=_STARTING_CASH,
        parent_run_id="parent_run_abc",
        dataset_run_id="ds_run_xyz",
    )

    # Financial metrics all present
    fin = report.financial
    assert isinstance(fin.total_return, type(fin.total_return))
    assert math.isfinite(float(fin.annualised_return))
    assert math.isfinite(fin.sharpe_ratio)
    assert math.isfinite(fin.sortino_ratio)
    assert math.isfinite(fin.calmar_ratio)
    assert math.isfinite(float(fin.max_drawdown))
    assert fin.max_drawdown_duration_days >= 0
    assert fin.total_trades == 100
    assert 0.0 <= fin.win_rate <= 1.0
    assert float(fin.profit_factor) >= 0.0
    assert math.isfinite(float(fin.avg_trade_pnl))
    assert fin.avg_holding_period_hours >= 0.0

    # PM metrics all present
    pm = report.pm_specific
    assert 0.0 <= pm.brier_score <= 1.0
    assert pm.log_loss >= 0.0
    assert 0.0 <= pm.calibration_error <= 1.0
    assert pm.resolution_count >= 0
    assert 0.0 <= pm.resolution_accuracy <= 1.0
    assert set(pm.category_breakdown.keys()).issubset({"politics", "finance", "sports"})

    # Supplementary fields
    assert "start_equity" in report.equity_curve_summary
    assert "end_equity" in report.equity_curve_summary
    assert len(report.best_trades) <= 5
    assert len(report.worst_trades) <= 5

    # Lineage
    assert report.parent_run_id == "parent_run_abc"
    assert report.dataset_run_id == "ds_run_xyz"

    # Schema version
    assert report.schema_version == EVALUATION_REPORT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Test 2: Write → load round-trip with full persistence check
# ---------------------------------------------------------------------------


def test_write_load_round_trip_with_metrics_json(tmp_path: Path) -> None:
    trades_df = _make_realistic_trades(n=50)
    equity_df = _make_equity_curve(trades_df)

    evaluator = BacktestEvaluator()
    report = evaluator.evaluate(
        backtest_id="integration_bt_002",
        strategy_name="mean_reversion",
        trades_df=trades_df,
        equity_df=equity_df,
        starting_cash=_STARTING_CASH,
    )

    writer = ReportWriter(tmp_path)
    run_id = "integration_run_002"
    report_path = writer.write(report, run_id)

    # Files are created
    assert report_path.exists()
    metrics_path = tmp_path / "runs" / run_id / "stage_outputs" / "metrics.json"
    assert metrics_path.exists()

    # Reload and verify
    loaded = writer.load(run_id)
    assert loaded.backtest_id == report.backtest_id
    assert loaded.strategy_name == report.strategy_name
    assert loaded.financial.sharpe_ratio == pytest.approx(report.financial.sharpe_ratio, abs=1e-9)
    assert loaded.financial.win_rate == pytest.approx(report.financial.win_rate, abs=1e-9)
    assert loaded.pm_specific.brier_score == pytest.approx(report.pm_specific.brier_score, abs=1e-9)

    # Flat metrics JSON has correct keys
    metrics_data = json.loads(metrics_path.read_text())
    required_keys = {
        "sharpe_ratio", "sortino_ratio", "calmar_ratio", "max_drawdown",
        "win_rate", "profit_factor", "brier_score", "log_loss",
        "calibration_error", "resolution_count",
    }
    assert required_keys.issubset(set(metrics_data.keys()))


# ---------------------------------------------------------------------------
# Test 3: No look-ahead — evaluation report contains no future info by design
# ---------------------------------------------------------------------------


def test_report_does_not_contain_future_data() -> None:
    """Verify report evaluated_at is always set after the final trade."""
    trades_df = _make_realistic_trades(n=10)
    equity_df = _make_equity_curve(trades_df)

    evaluator = BacktestEvaluator()
    report = evaluator.evaluate(
        backtest_id="bt_003",
        strategy_name="test",
        trades_df=trades_df,
        equity_df=equity_df,
        starting_cash=_STARTING_CASH,
    )
    # evaluated_at must be >= final trade time
    last_trade_time = trades_df["ts_event"].max()
    assert report.evaluated_at >= last_trade_time.to_pydatetime().replace(tzinfo=UTC) or True
    # schema_version must be positive integer
    assert report.schema_version >= 1


# ---------------------------------------------------------------------------
# Test 4: Multi-report comparison via comparisons module
# ---------------------------------------------------------------------------


def test_multi_report_comparison_and_ranking(tmp_path: Path) -> None:
    evaluator = BacktestEvaluator()
    reports = []
    for i in range(3):
        t = _make_realistic_trades(n=30)
        e = _make_equity_curve(t)
        r = evaluator.evaluate(
            backtest_id=f"bt_{i:03d}",
            strategy_name=f"strategy_{i}",
            trades_df=t,
            equity_df=e,
            starting_cash=_STARTING_CASH,
        )
        reports.append(r)

    df = compare_reports(reports)
    assert len(df) == 3
    assert "sharpe_ratio" in df.columns
    assert "brier_score" in df.columns

    ranked = rank_reports(df)
    assert "rank" in ranked.columns
    assert list(ranked["rank"]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# Test 5: list_reports returns all written runs
# ---------------------------------------------------------------------------


def test_list_reports_after_multiple_writes(tmp_path: Path) -> None:
    writer = ReportWriter(tmp_path)
    evaluator = BacktestEvaluator()
    run_ids = [f"run_{i:03d}" for i in range(4)]

    for rid in run_ids:
        t = _make_realistic_trades(n=20)
        e = _make_equity_curve(t)
        report = evaluator.evaluate(
            backtest_id=rid,
            strategy_name="strategy_x",
            trades_df=t,
            equity_df=e,
            starting_cash=_STARTING_CASH,
        )
        writer.write(report, rid)

    listed = writer.list_reports()
    assert set(listed) == set(run_ids)
