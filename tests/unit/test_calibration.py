"""Unit tests for alpha_core.evaluation.calibration."""

from __future__ import annotations

import math

import numpy as np
import pytest

from alpha_core.evaluation.calibration import (
    brier_score,
    calibration_curve,
    expected_calibration_error,
    log_loss_score,
)

# ---------------------------------------------------------------------------
# brier_score
# ---------------------------------------------------------------------------


def test_brier_score_perfect_forecaster() -> None:
    preds = np.array([1.0, 0.0, 1.0, 0.0])
    outcomes = np.array([1.0, 0.0, 1.0, 0.0])
    assert brier_score(preds, outcomes) == pytest.approx(0.0, abs=1e-12)


def test_brier_score_uniform_random_binary() -> None:
    """Predict 0.5 always on binary outcomes → Brier = 0.25."""
    preds = np.full(1000, 0.5)
    outcomes = np.concatenate([np.ones(500), np.zeros(500)])
    assert brier_score(preds, outcomes) == pytest.approx(0.25, abs=1e-10)


def test_brier_score_worst_case() -> None:
    # Predict 1.0 when outcome is 0 → (1-0)² = 1.0
    preds = np.array([1.0, 1.0])
    outcomes = np.array([0.0, 0.0])
    assert brier_score(preds, outcomes) == pytest.approx(1.0, abs=1e-12)


def test_brier_score_empty_returns_zero() -> None:
    assert brier_score(np.array([]), np.array([])) == 0.0


# ---------------------------------------------------------------------------
# log_loss_score
# ---------------------------------------------------------------------------


def test_log_loss_perfect_forecaster() -> None:
    # Predicting with very high confidence and being correct → near 0
    preds = np.array([0.9999, 0.0001])
    outcomes = np.array([1.0, 0.0])
    assert log_loss_score(preds, outcomes) < 0.001


def test_log_loss_uniform_random_binary() -> None:
    """Predict 0.5 always → log-loss ≈ ln(2) ≈ 0.6931."""
    preds = np.full(10_000, 0.5)
    outcomes = np.concatenate([np.ones(5000), np.zeros(5000)])
    assert log_loss_score(preds, outcomes) == pytest.approx(math.log(2), abs=1e-4)


def test_log_loss_empty_returns_zero() -> None:
    assert log_loss_score(np.array([]), np.array([])) == 0.0


def test_log_loss_greater_than_zero_for_imperfect() -> None:
    preds = np.array([0.6, 0.4])
    outcomes = np.array([1.0, 1.0])
    assert log_loss_score(preds, outcomes) > 0.0


# ---------------------------------------------------------------------------
# calibration_curve
# ---------------------------------------------------------------------------


def test_calibration_curve_empty_predictions() -> None:
    result = calibration_curve(np.array([]), np.array([]))
    assert result == []


def test_calibration_curve_perfect_calibration() -> None:
    """Uniform predictions matched to proportional outcomes → avg_pred ≈ avg_actual."""
    rng = np.random.default_rng(42)
    n = 10_000
    preds = rng.uniform(0.0, 1.0, n)
    outcomes = (rng.uniform(0.0, 1.0, n) < preds).astype(float)
    bins = calibration_curve(preds, outcomes, n_bins=10)
    for b in bins:
        assert abs(b["avg_predicted"] - b["avg_actual"]) < 0.05


def test_calibration_curve_structure() -> None:
    preds = np.array([0.1, 0.4, 0.6, 0.9])
    outcomes = np.array([0.0, 1.0, 1.0, 1.0])
    bins = calibration_curve(preds, outcomes)
    for b in bins:
        assert "bin_start" in b
        assert "bin_end" in b
        assert "avg_predicted" in b
        assert "avg_actual" in b
        assert "count" in b
        assert b["count"] > 0
        assert 0.0 <= b["avg_predicted"] <= 1.0
        assert 0.0 <= b["avg_actual"] <= 1.0


def test_calibration_curve_boundary_inclusion() -> None:
    # value exactly at 1.0 should be included in last bin
    preds = np.array([1.0])
    outcomes = np.array([1.0])
    bins = calibration_curve(preds, outcomes)
    total = sum(b["count"] for b in bins)
    assert total == 1


# ---------------------------------------------------------------------------
# expected_calibration_error
# ---------------------------------------------------------------------------


def test_ece_perfect_calibration_is_zero() -> None:
    # Predicting exactly the empirical probability → ECE = 0
    # Use 10 bins with 0.05, 0.15, ..., 0.95 each with 1k samples
    preds: list[float] = []
    outcomes: list[float] = []
    rng = np.random.default_rng(0)
    for centre in np.linspace(0.05, 0.95, 10):
        n = 1000
        preds.extend([centre] * n)
        outcomes.extend(rng.binomial(1, centre, n).tolist())
    ece = expected_calibration_error(np.array(preds), np.array(outcomes))
    assert ece < 0.05  # should be very close to 0 for well-calibrated


def test_ece_empty_returns_zero() -> None:
    assert expected_calibration_error(np.array([]), np.array([])) == 0.0


def test_ece_maximally_miscalibrated() -> None:
    # Always predict 0.0 but outcomes are all 1.0 → ECE = 1.0 * |0 - 1| = 1.0
    preds = np.zeros(100)
    outcomes = np.ones(100)
    ece = expected_calibration_error(preds, outcomes, n_bins=10)
    assert ece == pytest.approx(1.0, abs=0.01)


def test_ece_in_unit_interval() -> None:
    rng = np.random.default_rng(7)
    preds = rng.uniform(0, 1, 500)
    outcomes = rng.binomial(1, 0.4, 500).astype(float)
    ece = expected_calibration_error(preds, outcomes)
    assert 0.0 <= ece <= 1.0
