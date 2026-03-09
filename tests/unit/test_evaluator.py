"""Unit tests for alpha_core.evaluation.evaluator — BacktestEvaluator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from alpha_core.evaluation.evaluator import (
    EVALUATION_REPORT_SCHEMA_VERSION,
    BacktestEvaluator,
    EvaluationReport,
)
from alpha_core.evaluation.financial import FinancialMetrics
from alpha_core.evaluation.pm_metrics import PMMetrics

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trades(n: int = 10, pnl: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_event": _BASE + timedelta(hours=i),
                "instrument_id": f"mkt_{i}",
                "direction": "long",
                "price": 0.6,
                "size": 1,
                "realized_pnl": pnl if i % 2 == 0 else -pnl / 2,
            }
            for i in range(n)
        ]
    )


def _make_equity(start: float = 1000.0, end: float = 1100.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_event": _BASE, "equity": start},
            {"ts_event": _BASE + timedelta(days=1), "equity": end},
        ]
    )


def _make_report(
    backtest_id: str = "test_run_1",
    strategy_name: str = "test_strategy",
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
# EvaluationReport model
# ---------------------------------------------------------------------------


def test_evaluate_produces_all_required_fields() -> None:
    report = _make_report()
    assert report.backtest_id == "test_run_1"
    assert report.strategy_name == "test_strategy"
    assert isinstance(report.financial, FinancialMetrics)
    assert isinstance(report.pm_specific, PMMetrics)
    assert isinstance(report.equity_curve_summary, dict)
    assert isinstance(report.monthly_returns, list)
    assert isinstance(report.equity_curve, list)
    assert isinstance(report.best_trades, list)
    assert isinstance(report.worst_trades, list)


def test_evaluate_schema_version_is_pinned() -> None:
    report = _make_report()
    assert report.schema_version == EVALUATION_REPORT_SCHEMA_VERSION


def test_evaluate_evaluated_at_is_recent_utc() -> None:
    report = _make_report()
    now = datetime.now(tz=UTC)
    delta = abs((now - report.evaluated_at).total_seconds())
    assert delta < 10.0


def test_lineage_fields_are_passed_through() -> None:
    evaluator = BacktestEvaluator()
    report = evaluator.evaluate(
        backtest_id="bt1",
        strategy_name="strat",
        trades_df=_make_trades(),
        equity_df=_make_equity(),
        starting_cash=1000.0,
        parent_run_id="parent_123",
        dataset_run_id="ds_456",
        feature_run_id="feat_789",
    )
    assert report.parent_run_id == "parent_123"
    assert report.dataset_run_id == "ds_456"
    assert report.feature_run_id == "feat_789"


# ---------------------------------------------------------------------------
# equity_curve_summary
# ---------------------------------------------------------------------------


def test_equity_curve_summary_has_expected_keys() -> None:
    report = _make_report()
    summary = report.equity_curve_summary
    assert "start_equity" in summary
    assert "end_equity" in summary
    assert "peak_equity" in summary
    assert "trough_equity" in summary


def test_equity_curve_summary_values_are_reasonable() -> None:
    report = _make_report(strategy_name="s")
    s = report.equity_curve_summary
    assert s["end_equity"] >= s["trough_equity"]
    assert s["peak_equity"] >= s["end_equity"]


# ---------------------------------------------------------------------------
# best / worst trades
# ---------------------------------------------------------------------------


def test_best_and_worst_trades_at_most_5() -> None:
    report = _make_report()
    assert len(report.best_trades) <= 5
    assert len(report.worst_trades) <= 5


def test_best_trades_have_higher_pnl_than_worst() -> None:
    report = _make_report()
    if report.best_trades and report.worst_trades:
        best_pnl = report.best_trades[0]["realized_pnl"]
        worst_pnl = report.worst_trades[0]["realized_pnl"]
        assert best_pnl >= worst_pnl


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def test_compare_returns_dataframe_with_correct_shape() -> None:
    evaluator = BacktestEvaluator()
    r1 = _make_report("bt1", "strat_A")
    r2 = _make_report("bt2", "strat_B")
    df = evaluator.compare([r1, r2])
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "backtest_id" in df.columns
    assert "sharpe_ratio" in df.columns
    assert "brier_score" in df.columns


def test_compare_empty_list_returns_empty_df() -> None:
    evaluator = BacktestEvaluator()
    df = evaluator.compare([])
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


def test_compare_single_report() -> None:
    evaluator = BacktestEvaluator()
    r = _make_report("bt1", "strat_A")
    df = evaluator.compare([r])
    assert len(df) == 1


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def test_evaluation_report_json_round_trip() -> None:
    report = _make_report()
    json_str = report.model_dump_json()
    loaded = EvaluationReport.model_validate_json(json_str)
    assert loaded.backtest_id == report.backtest_id
    assert loaded.financial.sharpe_ratio == report.financial.sharpe_ratio
    assert loaded.pm_specific.brier_score == report.pm_specific.brier_score
    assert (
        loaded.model_dump(mode="json")["equity_curve"]
        == report.model_dump(mode="json")["equity_curve"]
    )
