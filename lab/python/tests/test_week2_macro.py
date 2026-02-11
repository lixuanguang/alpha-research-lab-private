"""Week-2 macro allocator regression tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.backtest.leakage_checks import assert_no_lookahead, assert_splits_time_ordered
from lab.backtest.splits import rolling_splits
from lab.data.loaders.prices import load_asset_meta, load_close_prices
from lab.portfolio.allocator_ls import build_weights


def test_rolling_splits_day_mode_with_embargo() -> None:
    dates = pd.bdate_range("2010-01-04", periods=2200)
    folds = list(
        rolling_splits(
            dates,
            train_days=756,
            test_days=126,
            step_days=126,
            embargo_days=5,
        )
    )

    assert len(folds) > 0
    assert_splits_time_ordered(folds)

    for train, test in folds:
        assert len(train) == 756
        assert len(test) == 126
        assert train.max() < test.min()


def test_no_lookahead_guard_detects_future_signal() -> None:
    dates = pd.bdate_range("2020-01-02", periods=300)
    rng = np.random.default_rng(42)
    prices = pd.DataFrame(
        {
            "SPY": 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(dates)))),
            "TLT": 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.008, len(dates)))),
        },
        index=dates,
    )

    good_signal = prices.pct_change(21).shift(1).fillna(0.0)
    assert_no_lookahead(good_signal, prices, min_lag=1)

    bad_signal = prices.pct_change().shift(-1).fillna(0.0)
    with pytest.raises(AssertionError, match="lookahead"):
        assert_no_lookahead(bad_signal, prices, min_lag=1)


def test_allocator_constraints_respected() -> None:
    tickers = ["SPY", "EFA", "EEM", "IEF", "TLT", "GLD", "DBC", "LQD"]
    meta = pd.DataFrame(
        {
            "ticker": tickers,
            "bucket": [
                "equities",
                "equities",
                "equities",
                "rates",
                "rates",
                "commodities",
                "commodities",
                "credit",
            ],
            "cost_bps": [3, 4, 5, 2, 3, 4, 6, 4],
            "per_asset_cap": [0.35, 0.35, 0.35, 0.35, 0.35, 0.30, 0.25, 0.30],
        }
    )

    scores = pd.Series([1.0, 0.8, -0.9, 0.7, -0.5, 0.6, -0.4, -0.2], index=tickers)
    vol = pd.Series([0.15, 0.18, 0.22, 0.09, 0.11, 0.20, 0.25, 0.12], index=tickers)

    bucket_caps = {
        "equities": 0.8,
        "rates": 0.9,
        "commodities": 0.4,
        "credit": 0.3,
    }

    w = build_weights(
        scores_t=scores,
        vol_t=vol,
        meta=meta,
        gross_cap=1.5,
        net_target=0.0,
        net_band=0.15,
        per_asset_cap=0.35,
        bucket_caps=bucket_caps,
    )

    assert w.abs().sum() <= 1.5 + 1e-8
    caps = meta.set_index("ticker")["per_asset_cap"]
    assert ((w.abs() - caps) <= 1e-8).all()

    bucket_map = meta.set_index("ticker")["bucket"]
    for b, cap in bucket_caps.items():
        members = bucket_map[bucket_map == b].index
        assert w[members].abs().sum() <= cap + 1e-8

    assert abs(w.sum()) <= 0.15 + 1e-8


def test_price_loader_alignment_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

    dates = pd.bdate_range("2020-01-02", periods=60)
    close = pd.DataFrame(
        {
            "SPY": np.linspace(100, 120, len(dates)),
            "TLT": np.linspace(100, 110, len(dates)),
            "GLD": np.linspace(100, 115, len(dates)),
        },
        index=dates,
    )

    prices_dir = tmp_path / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    close.to_parquet(prices_dir / "close.parquet")

    meta = pd.DataFrame(
        {
            "ticker": ["SPY", "TLT", "GLD"],
            "bucket": ["equities", "rates", "commodities"],
            "cost_bps": [3, 2, 4],
            "per_asset_cap": [0.35, 0.35, 0.30],
        }
    )
    meta.to_parquet(prices_dir / "meta.parquet", index=False)

    loaded_prices = load_close_prices(["SPY", "TLT", "GLD"], "2020-01-02", "2020-12-31")
    loaded_meta = load_asset_meta()

    assert loaded_prices.index.is_monotonic_increasing
    assert loaded_prices.index.is_unique
    assert loaded_prices.columns.is_unique
    assert set(loaded_prices.columns) == set(loaded_meta["ticker"])


def test_price_loader_partial_synthetic_backfill_preserves_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

    # Simulate a real panel with an exchange-specific calendar (missing Fridays).
    all_days = pd.bdate_range("2020-01-02", periods=80)
    no_fridays = all_days[all_days.weekday != 4]
    close = pd.DataFrame({"SPY": np.linspace(100, 120, len(no_fridays))}, index=no_fridays)

    prices_dir = tmp_path / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    close.to_parquet(prices_dir / "close.parquet")

    loaded = load_close_prices(["SPY", "TLT"], "2020-01-02", "2020-12-31")

    assert loaded.index.equals(no_fridays)
    assert list(loaded.columns) == ["SPY", "TLT"]
    assert not loaded.isna().any().any()


def test_price_loader_empty_requested_window_falls_back_to_synthetic(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

    dates = pd.bdate_range("2020-01-02", periods=60)
    close = pd.DataFrame({"SPY": np.linspace(100, 120, len(dates))}, index=dates)

    prices_dir = tmp_path / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    close.to_parquet(prices_dir / "close.parquet")

    loaded = load_close_prices(["SPY", "TLT"], "2025-01-02", "2025-03-31")

    assert not loaded.empty
    assert list(loaded.columns) == ["SPY", "TLT"]


def test_price_loader_fails_fast_on_non_positive_or_non_finite_prices(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

    dates = pd.bdate_range("2020-01-02", periods=40)
    close = pd.DataFrame(
        {
            "SPY": np.linspace(100, 120, len(dates)),
            "TLT": np.linspace(100, 110, len(dates)),
        },
        index=dates,
    )
    close.loc[dates[10], "SPY"] = 0.0
    close.loc[dates[11], "TLT"] = np.inf

    prices_dir = tmp_path / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    close.to_parquet(prices_dir / "close.parquet")

    with pytest.raises(ValueError, match=r"NaN/inf|non-positive"):
        load_close_prices(["SPY", "TLT"], "2020-01-02", "2020-12-31")
