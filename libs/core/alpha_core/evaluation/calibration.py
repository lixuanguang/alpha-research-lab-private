"""Calibration curve and Expected Calibration Error (ECE) for PM evaluation.

These are pure-NumPy functions — no external dependencies beyond numpy.

Calibration
-----------
In prediction markets, *calibration* measures whether a strategy's entry
probability (the implied probability at which it trades) matches empirical
resolution outcomes.

A perfectly calibrated system with 60 % entry probability wins exactly 60 %
of the time across a large sample.  :func:`expected_calibration_error` returns
0.0 for perfect calibration and up to 1.0 for maximally miscalibrated models.

Usage::

    preds = np.array([0.2, 0.5, 0.8, 0.9])
    outcomes = np.array([0.0, 1.0, 1.0, 0.0])
    bins = calibration_curve(preds, outcomes)
    ece = expected_calibration_error(preds, outcomes)
"""

from __future__ import annotations

import numpy as np


def calibration_curve(
    predictions: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> list[dict]:
    """Bin predictions into equal-width buckets and compute avg predicted vs actual.

    Parameters
    ----------
    predictions:
        Predicted probabilities in ``[0, 1]``.
    outcomes:
        Binary outcomes (0 or 1).
    n_bins:
        Number of equal-width probability bins.

    Returns
    -------
    list[dict]
        One dict per non-empty bin::

            {
                "bin_start": float,
                "bin_end": float,
                "avg_predicted": float,
                "avg_actual": float,
                "count": int,
            }
    """
    predictions = np.asarray(predictions, dtype=float).ravel()
    outcomes = np.asarray(outcomes, dtype=float).ravel()
    if len(predictions) == 0:
        return []

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    results: list[dict] = []
    for i in range(n_bins):
        low, high = float(bins[i]), float(bins[i + 1])
        # Include upper edge in last bin
        if i < n_bins - 1:
            mask = (predictions >= low) & (predictions < high)
        else:
            mask = (predictions >= low) & (predictions <= high)
        count = int(mask.sum())
        if count == 0:
            continue
        results.append(
            {
                "bin_start": round(low, 4),
                "bin_end": round(high, 4),
                "avg_predicted": round(float(predictions[mask].mean()), 6),
                "avg_actual": round(float(outcomes[mask].mean()), 6),
                "count": count,
            }
        )
    return results


def expected_calibration_error(
    predictions: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute Expected Calibration Error (ECE).

    ECE = sum over bins of (bin_weight * |avg_predicted - avg_actual|)

    A perfectly calibrated forecaster has ECE = 0.0.

    Parameters
    ----------
    predictions:
        Predicted probabilities in ``[0, 1]``.
    outcomes:
        Binary outcomes (0 or 1).
    n_bins:
        Number of equal-width probability bins.

    Returns
    -------
    float
        ECE in ``[0, 1]``.
    """
    predictions = np.asarray(predictions, dtype=float).ravel()
    outcomes = np.asarray(outcomes, dtype=float).ravel()
    n = len(predictions)
    if n == 0:
        return 0.0

    bins_data = calibration_curve(predictions, outcomes, n_bins=n_bins)
    ece = 0.0
    for b in bins_data:
        weight = b["count"] / n
        ece += weight * abs(b["avg_predicted"] - b["avg_actual"])
    return round(ece, 6)


def brier_score(predictions: np.ndarray, outcomes: np.ndarray) -> float:
    """Mean squared error between predictions and binary outcomes.

    Ranges from 0 (perfect) to 1 (worst).  A naïve forecaster predicting 0.5
    always scores 0.25.

    Parameters
    ----------
    predictions:
        Predicted probabilities in ``[0, 1]``.
    outcomes:
        Binary outcomes (0 or 1).
    """
    predictions = np.asarray(predictions, dtype=float).ravel()
    outcomes = np.asarray(outcomes, dtype=float).ravel()
    if len(predictions) == 0:
        return 0.0
    return float(np.mean((predictions - outcomes) ** 2))


def log_loss_score(
    predictions: np.ndarray,
    outcomes: np.ndarray,
    eps: float = 1e-15,
) -> float:
    """Binary cross-entropy / log-loss.

    Ranges from 0 (perfect) to ∞.  A naïve forecaster predicting 0.5 always
    scores ``ln(2) ≈ 0.693``.

    Parameters
    ----------
    predictions:
        Predicted probabilities clipped to ``[eps, 1 - eps]``.
    outcomes:
        Binary outcomes (0 or 1).
    eps:
        Clipping bound to avoid ``log(0)``.
    """
    predictions = np.asarray(predictions, dtype=float).ravel()
    outcomes = np.asarray(outcomes, dtype=float).ravel()
    if len(predictions) == 0:
        return 0.0
    p = np.clip(predictions, eps, 1.0 - eps)
    loss = -(outcomes * np.log(p) + (1.0 - outcomes) * np.log(1.0 - p))
    return float(np.mean(loss))


__all__ = [
    "brier_score",
    "calibration_curve",
    "expected_calibration_error",
    "log_loss_score",
]
