"""
tests.test_registry
~~~~~~~~~~~~~~~~~~~
Regression tests for run/config identity helpers in ``lab.core.registry``.
"""

from __future__ import annotations

from pathlib import Path

from lab.core import registry
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


def test_create_run_avoids_collision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LAB_RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(registry, "generate_run_id", lambda _config_hash: "20260210_000000_abc123")

    rid1, rdir1 = registry.create_run("exp", "cfg.yaml", {"exp": "x"})
    rid2, rdir2 = registry.create_run("exp", "cfg.yaml", {"exp": "x"})

    assert rid1 == "20260210_000000_abc123"
    assert rid2 == "20260210_000000_abc123_01"
    assert rdir1 != rdir2
    assert (rdir1 / "meta.json").exists()
    assert (rdir2 / "meta.json").exists()
