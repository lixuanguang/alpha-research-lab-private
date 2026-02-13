"""
tests.test_registry
~~~~~~~~~~~~~~~~~~~
Regression tests for run/config identity helpers in ``lab.core.registry``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lab.core import registry
from lab.core.registry import (
    compute_results_hash,
    compute_stable_frame_hash,
    compute_stable_series_hash,
)


def test_results_hash_is_deterministic() -> None:
    metrics = {"sharpe": 1.23456789, "cagr": 0.123456789}
    h1 = compute_results_hash(metrics, config_hash="abc123", toy_seed=42)
    h2 = compute_results_hash(
        {"cagr": 0.123456789, "sharpe": 1.23456789}, config_hash="abc123", toy_seed=42
    )
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


def test_results_hash_depends_on_artifact_hashes() -> None:
    metrics = {"sharpe": 1.2, "cagr": 0.1}
    h1 = compute_results_hash(
        metrics,
        config_hash="abc123",
        toy_seed=42,
        data_snapshot_id="snap_1",
        artifact_hashes={"returns": "aaa", "weights": "bbb"},
    )
    h2 = compute_results_hash(
        metrics,
        config_hash="abc123",
        toy_seed=42,
        data_snapshot_id="snap_1",
        artifact_hashes={"weights": "bbb", "returns": "aaa"},
    )
    h3 = compute_results_hash(
        metrics,
        config_hash="abc123",
        toy_seed=42,
        data_snapshot_id="snap_1",
        artifact_hashes={"returns": "aaa", "weights": "ccc"},
    )
    assert h1 == h2
    assert h1 != h3


def test_stable_series_hash_order_invariant() -> None:
    idx = pd.to_datetime(["2024-01-03", "2024-01-02", "2024-01-04"])
    s1 = pd.Series([1.0, 2.0, 3.0], index=idx, name="x")
    s2 = s1.sort_index()
    assert compute_stable_series_hash(s1) == compute_stable_series_hash(s2)


def test_stable_frame_hash_order_invariant() -> None:
    idx = pd.to_datetime(["2024-01-03", "2024-01-02"])
    df1 = pd.DataFrame({"B": [2.0, 3.0], "A": [1.0, 4.0]}, index=idx)
    df2 = df1.sort_index().reindex(columns=["A", "B"])
    assert compute_stable_frame_hash(df1) == compute_stable_frame_hash(df2)


def test_stable_hash_rejects_non_finite_values() -> None:
    bad_s = pd.Series([1.0, np.nan], index=pd.date_range("2024-01-01", periods=2))
    bad_df = pd.DataFrame({"A": [1.0, np.inf]}, index=pd.date_range("2024-01-01", periods=2))
    with pytest.raises(ValueError):
        compute_stable_series_hash(bad_s)
    with pytest.raises(ValueError):
        compute_stable_frame_hash(bad_df)


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

    meta = (rdir1 / "meta.json").read_text()
    assert '"data_snapshot_id": null' in meta
