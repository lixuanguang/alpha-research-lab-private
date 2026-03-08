"""Unit tests for alpha_core.evaluation.pm_metrics — PMMetrics."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from alpha_core.evaluation.pm_metrics import compute_pm_metrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _trades(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _basic_trades(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_event": _BASE + timedelta(hours=i),
                "instrument_id": f"mkt_{i}",
                "direction": "long",
                "price": 0.5,
                "size": 10,
                "realized_pnl": 0.0,
            }
            for i in range(n)
        ]
    )


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_empty_trades_returns_zero_metrics() -> None:
    m = compute_pm_metrics(pd.DataFrame())
    assert m.brier_score == 0.0
    assert m.log_loss == 0.0
    assert m.calibration_error == 0.0
    assert m.resolution_count == 0
    assert float(m.resolution_pnl) == 0.0


# ---------------------------------------------------------------------------
# Brier score via resolution_outcome column
# ---------------------------------------------------------------------------


def test_brier_score_perfect_forecaster_in_pm_metrics() -> None:
    df = _trades(
        [
            {
                "ts_event": _BASE,
                "instrument_id": "mkt_a",
                "direction": "long",
                "price": 1.0,
                "size": 10,
                "realized_pnl": 10.0,
                "resolution_outcome": 1.0,
            },
            {
                "ts_event": _BASE + timedelta(hours=1),
                "instrument_id": "mkt_b",
                "direction": "long",
                "price": 0.0,
                "size": 10,
                "realized_pnl": -10.0,
                "resolution_outcome": 0.0,
            },
        ]
    )
    m = compute_pm_metrics(df)
    assert m.brier_score == pytest.approx(0.0, abs=1e-6)


def test_brier_score_uniform_random_is_025() -> None:
    rng = np.random.default_rng(42)
    n = 5000
    rows = [
        {
            "ts_event": _BASE + timedelta(hours=i),
            "instrument_id": f"mkt_{i}",
            "direction": "long",
            "price": 0.5,
            "size": 1,
            "realized_pnl": rng.integers(0, 2) - 0.5,
            "resolution_outcome": float(rng.integers(0, 2)),
        }
        for i in range(n)
    ]
    df = _trades(rows)
    m = compute_pm_metrics(df)
    assert m.brier_score == pytest.approx(0.25, abs=0.01)


# ---------------------------------------------------------------------------
# Log-loss
# ---------------------------------------------------------------------------


def test_log_loss_uniform_random_is_ln2() -> None:
    n = 10_000
    rows = [
        {
            "ts_event": _BASE + timedelta(hours=i),
            "instrument_id": f"mkt_{i}",
            "direction": "long",
            "price": 0.5,
            "size": 1,
            "realized_pnl": 0.0,
            "resolution_outcome": float(i % 2),
        }
        for i in range(n)
    ]
    df = _trades(rows)
    m = compute_pm_metrics(df)
    assert m.log_loss == pytest.approx(math.log(2), abs=0.01)


# ---------------------------------------------------------------------------
# Calibration error
# ---------------------------------------------------------------------------


def test_calibration_error_zero_for_perfectly_calibrated() -> None:
    """All predictions exactly match empirical frequencies."""
    rng = np.random.default_rng(1)
    rows = []
    for centre in [0.1, 0.3, 0.5, 0.7, 0.9]:
        for _ in range(200):
            outcome = float(rng.binomial(1, centre))
            rows.append(
                {
                    "ts_event": _BASE,
                    "instrument_id": "m",
                    "direction": "long",
                    "price": centre,
                    "size": 1,
                    "realized_pnl": outcome - 0.5,
                    "resolution_outcome": outcome,
                }
            )
    df = _trades(rows)
    m = compute_pm_metrics(df)
    assert m.calibration_error < 0.05


# ---------------------------------------------------------------------------
# Resolution metrics
# ---------------------------------------------------------------------------


def test_resolution_pnl_and_count() -> None:
    df = _trades(
        [
            {
                "ts_event": _BASE,
                "instrument_id": "mkt_0",
                "direction": "long",
                "price": 0.7,
                "size": 10,
                "realized_pnl": 30.0,
                "resolution_outcome": 1.0,
            },
            {
                "ts_event": _BASE + timedelta(hours=1),
                "instrument_id": "mkt_1",
                "direction": "long",
                "price": 0.4,
                "size": 10,
                "realized_pnl": -40.0,
                "resolution_outcome": 0.0,
            },
        ]
    )
    m = compute_pm_metrics(df)
    assert m.resolution_count == 2
    assert float(m.resolution_pnl) == pytest.approx(-10.0, abs=1e-6)


def test_resolution_accuracy_all_correct() -> None:
    df = _trades(
        [
            {
                "ts_event": _BASE + timedelta(hours=i),
                "instrument_id": f"mkt_{i}",
                "direction": "long",
                "price": 0.8,
                "size": 1,
                "realized_pnl": 10.0,
                "resolution_outcome": 1.0,
            }
            for i in range(10)
        ]
    )
    m = compute_pm_metrics(df)
    assert m.resolution_accuracy == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Category breakdown
# ---------------------------------------------------------------------------


def test_category_breakdown_populated() -> None:
    df = _trades(
        [
            {
                "ts_event": _BASE + timedelta(hours=i),
                "instrument_id": f"m_{i}",
                "direction": "long",
                "price": 0.5,
                "size": 1,
                "realized_pnl": float(i % 3 - 1) * 10,
                "category": "politics" if i % 2 == 0 else "sports",
            }
            for i in range(20)
        ]
    )
    m = compute_pm_metrics(df)
    assert set(m.category_breakdown.keys()) == {"politics", "sports"}
    for cat_data in m.category_breakdown.values():
        assert "sharpe" in cat_data
        assert "brier" in cat_data
        assert "trade_count" in cat_data


def test_category_breakdown_empty_when_no_column() -> None:
    df = _basic_trades(5)
    m = compute_pm_metrics(df)
    assert m.category_breakdown == {}


# ---------------------------------------------------------------------------
# Avg entry/exit probability
# ---------------------------------------------------------------------------


def test_avg_prob_at_entry_correct() -> None:
    df = _trades(
        [
            {
                "ts_event": _BASE + timedelta(hours=i),
                "instrument_id": f"m_{i}",
                "direction": "long",
                "price": float(i + 1) / 10,
                "size": 1,
                "realized_pnl": 0.0,
            }
            for i in range(4)
        ]
    )
    m = compute_pm_metrics(df)
    expected = (0.1 + 0.2 + 0.3 + 0.4) / 4
    assert float(m.avg_prob_at_entry) == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# Type contracts
# ---------------------------------------------------------------------------


def test_pm_metrics_return_types() -> None:
    df = _basic_trades(3)
    m = compute_pm_metrics(df)
    assert isinstance(m.brier_score, float)
    assert isinstance(m.log_loss, float)
    assert isinstance(m.calibration_error, float)
    assert isinstance(m.resolution_pnl, Decimal)
    assert isinstance(m.avg_prob_at_entry, Decimal)
