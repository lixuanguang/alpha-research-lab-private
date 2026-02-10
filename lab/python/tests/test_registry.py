"""
tests.test_registry
~~~~~~~~~~~~~~~~~~~
Regression tests for run/config identity helpers in ``lab.core.registry``.
"""

from __future__ import annotations

from lab.core.registry import compute_results_hash


def test_results_hash_is_deterministic() -> None:
    metrics = {"sharpe": 1.23456789, "cagr": 0.123456789}
    h1 = compute_results_hash(metrics, config_hash="abc123", toy_seed=42)
    h2 = compute_results_hash({"cagr": 0.123456789, "sharpe": 1.23456789}, config_hash="abc123", toy_seed=42)
    assert h1 == h2


def test_results_hash_changes_when_seed_changes() -> None:
    metrics = {"sharpe": 1.2, "cagr": 0.1}
    h1 = compute_results_hash(metrics, config_hash="abc123", toy_seed=42)
    h2 = compute_results_hash(metrics, config_hash="abc123", toy_seed=7)
    assert h1 != h2


def test_results_hash_changes_when_config_changes() -> None:
    metrics = {"sharpe": 1.2, "cagr": 0.1}
    h1 = compute_results_hash(metrics, config_hash="abc123", toy_seed=42)
    h2 = compute_results_hash(metrics, config_hash="def456", toy_seed=42)
    assert h1 != h2
