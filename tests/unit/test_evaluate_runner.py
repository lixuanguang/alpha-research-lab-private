"""Unit tests for alpha_core.research.evaluate_runner."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

import alpha_core.research.evaluate_runner as evaluate_runner_mod


def _equity_frame(points: list[tuple[datetime, float]]) -> pd.DataFrame:
    return pd.DataFrame(points, columns=["ts_event", "equity"])


def test_risk_metrics_are_invariant_to_duplicate_event_cadence() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    sparse = _equity_frame(
        [
            (base, 1000.0),
            (base + timedelta(hours=12), 1100.0),
            (base + timedelta(hours=24), 1210.0),
        ]
    )
    dense = _equity_frame(
        [
            (base, 1000.0),
            (base + timedelta(hours=3), 1000.0),
            (base + timedelta(hours=6), 1000.0),
            (base + timedelta(hours=9), 1000.0),
            (base + timedelta(hours=12), 1100.0),
            (base + timedelta(hours=15), 1100.0),
            (base + timedelta(hours=18), 1100.0),
            (base + timedelta(hours=21), 1100.0),
            (base + timedelta(hours=24), 1210.0),
        ]
    )

    sparse_metrics = evaluate_runner_mod._compute_metrics(
        trades_df=pd.DataFrame(columns=["realized_pnl"]),
        equity_df=sparse,
        profile="pm_core",
        starting_cash=1000.0,
    )
    dense_metrics = evaluate_runner_mod._compute_metrics(
        trades_df=pd.DataFrame(columns=["realized_pnl"]),
        equity_df=dense,
        profile="pm_core",
        starting_cash=1000.0,
    )

    assert dense_metrics["annualized_return"] == sparse_metrics["annualized_return"]
    assert dense_metrics["sharpe_ratio"] == sparse_metrics["sharpe_ratio"]


def test_annualized_return_is_finite_for_short_positive_runs() -> None:
    base = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    metrics = evaluate_runner_mod._compute_metrics(
        trades_df=pd.DataFrame(columns=["realized_pnl"]),
        equity_df=_equity_frame(
            [
                (base, 110.0),
                (base + timedelta(hours=1), 121.0),
            ]
        ),
        profile="pm_core",
        starting_cash=100.0,
    )

    assert math.isfinite(metrics["annualized_return"])
    assert metrics["annualized_return"] > 0.0


def test_resample_equity_includes_first_return_from_starting_cash() -> None:
    base = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    resampled = evaluate_runner_mod._resample_equity(
        equity_frame=_equity_frame(
            [
                (base, 110.0),
                (base + timedelta(hours=1), 121.0),
            ]
        ),
        starting_cash=100.0,
    )

    returns = resampled.pct_change().dropna()
    assert returns.iloc[0] == pytest.approx(0.10)
