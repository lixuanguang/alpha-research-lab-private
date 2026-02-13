"""Integration checks for strict real-data run behavior."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_configs(root: Path) -> Path:
    universe = {
        "tickers": ["SPY", "TLT"],
        "ticker_meta": {
            "SPY": {"bucket": "equities", "cost_bps": 3, "per_asset_cap": 0.35, "adv_usd_mn": 1000},
            "TLT": {"bucket": "rates", "cost_bps": 2, "per_asset_cap": 0.35, "adv_usd_mn": 900},
        },
        "constraints": {
            "gross_cap": 1.5,
            "net_target": 0.0,
            "net_band": 0.20,
            "bucket_gross_caps": {"equities": 1.0, "rates": 1.0},
        },
    }
    universe_path = root / "universe.yaml"
    universe_path.write_text(yaml.safe_dump(universe))

    cfg = {
        "exp": "macro_allocator_ls",
        "strategy": "macro.allocator_ls",
        "universe_config": str(universe_path),
        "dates": {"start": "2023-01-02", "end": "2023-08-31"},
        "rebalance": {"frequency": "W-FRI"},
        "signal": {"name": "ts_trend", "method": "ma_cross", "fast": 5, "slow": 20, "lookback_days": 40},
        "regime": {"enabled": True, "lag_days": 5, "lookback_days": 21},
        "macro": {"series_ids": ["UNRATE", "CPIAUCSL", "INDPRO", "DFF"], "lag_days": 5, "ffill_limit": 22},
        "feature_store": {"enabled": True},
        "risk": {"vol_target_annual": 0.10, "vol_lookback_days": 21},
        "costs": {"use_meta_costs": True, "stress_multipliers": [1, 2]},
        "evaluation": {"folds": {"train_days": 60, "test_days": 20, "step_days": 20, "embargo_days": 2}},
    }
    cfg_path = root / "macro_cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    return cfg_path


def _write_data_artifacts(data_root: Path) -> None:
    prices_dir = data_root / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    idx = pd.bdate_range("2023-01-02", "2023-08-31")
    close = pd.DataFrame(
        {
            "SPY": 100.0 * np.exp(np.cumsum(np.full(len(idx), 0.0004))),
            "TLT": 100.0 * np.exp(np.cumsum(np.full(len(idx), 0.0002))),
        },
        index=idx,
    )
    close.to_parquet(prices_dir / "close.parquet")

    macro_dir = data_root / "macro" / "fred"
    macro_dir.mkdir(parents=True, exist_ok=True)
    m_idx = pd.to_datetime(
        ["2022-12-01", "2023-01-01", "2023-02-01", "2023-03-01", "2023-04-01", "2023-05-01", "2023-06-01", "2023-07-01", "2023-08-01"]
    )
    for sid, base in {"UNRATE": 3.5, "CPIAUCSL": 280.0, "INDPRO": 100.0, "DFF": 1.0}.items():
        df = pd.DataFrame({"value": base + np.linspace(0.0, 1.0, len(m_idx))}, index=m_idx)
        df.to_parquet(macro_dir / f"{sid}.parquet")


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_run_fails_fast_without_data_with_actionable_error(tmp_path: Path) -> None:
    repo = _repo_root()
    cfg_path = _write_configs(tmp_path)

    env = dict(os.environ)
    env["LAB_DATA_ROOT"] = str(tmp_path / "data_empty")
    env["LAB_RUNS_ROOT"] = str(tmp_path / "runs")

    proc = _run(
        [
            sys.executable,
            str(repo / "scripts" / "run_experiment.py"),
            "--exp",
            "macro_allocator_ls",
            "--config",
            str(cfg_path),
        ],
        cwd=repo,
        env=env,
    )

    assert proc.returncode != 0
    merged = f"{proc.stdout}\n{proc.stderr}"
    assert "make ingest_prices" in merged


def test_run_succeeds_with_real_data_and_embeds_snapshot_id(tmp_path: Path) -> None:
    repo = _repo_root()
    cfg_path = _write_configs(tmp_path)
    data_root = tmp_path / "data"
    _write_data_artifacts(data_root)

    env = dict(os.environ)
    env["LAB_DATA_ROOT"] = str(data_root)
    env["LAB_RUNS_ROOT"] = str(tmp_path / "runs")

    proc = _run(
        [
            sys.executable,
            str(repo / "scripts" / "run_experiment.py"),
            "--exp",
            "macro_allocator_ls",
            "--config",
            str(cfg_path),
            "--use-feature-store",
        ],
        cwd=repo,
        env=env,
    )

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    run_dirs = sorted((tmp_path / "runs").glob("*"))
    assert run_dirs
    latest = run_dirs[-1]
    results = json.loads((latest / "results.json").read_text())
    meta = json.loads((latest / "meta.json").read_text())
    assert results["run"]["data_snapshot_id"]
    assert meta["data_snapshot_id"] == results["run"]["data_snapshot_id"]
