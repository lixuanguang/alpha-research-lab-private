"""Acceptance tests for adapter/caching/batching ingestion behavior."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from lab.core.paths import data_dir
from lab.data.adapters.base import PriceDataAdapter
from lab.data.ingestion import RetryConfig, run_price_ingestion


def _write_universe(path: Path, tickers: list[str]) -> Path:
    raw = {
        "tickers": tickers,
        "ticker_meta": {
            t: {
                "bucket": "equities",
                "cost_bps": 3,
                "per_asset_cap": 0.35,
            }
            for t in tickers
        },
    }
    cfg = path / "universe.yaml"
    cfg.write_text(yaml.safe_dump(raw))
    return cfg


def _price_frame(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    idx = pd.bdate_range(start, end)
    data = {}
    for i, t in enumerate(tickers):
        base = 100.0 + i
        ramp = np.linspace(0.0, 5.0, len(idx))
        data[t] = base + ramp
    return pd.DataFrame(data, index=idx, dtype=float)


class CountingAdapter(PriceDataAdapter):
    source = "yf"

    def __init__(self) -> None:
        self.calls = 0

    def download_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        return _price_frame(tickers, start, end)


class FlakyAdapter(PriceDataAdapter):
    source = "yf"

    def __init__(self, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.calls = 0

    def download_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError("temporary rate limit")
        return _price_frame(tickers, start, end)


class AlwaysFailAdapter(PriceDataAdapter):
    source = "yf"

    def __init__(self) -> None:
        self.calls = 0

    def download_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        raise RuntimeError("upstream unavailable")


def test_ingestion_cache_hit_skips_network_and_preserves_close_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))
    cfg = _write_universe(tmp_path, ["SPY", "TLT", "GLD"])
    adapter = CountingAdapter()

    first = run_price_ingestion(
        config_path=cfg,
        start="2024-01-02",
        end="2024-03-29",
        source="yf",
        batch_size=2,
        adapter=adapter,
        sleep_fn=lambda _s: None,
    )
    assert first.cache_hit is False
    assert adapter.calls == 2  # 3 tickers with batch_size=2 => 2 batches

    close_path = data_dir() / "prices" / "close.parquet"
    before = close_path.read_bytes()

    second = run_price_ingestion(
        config_path=cfg,
        start="2024-01-02",
        end="2024-03-29",
        source="yf",
        batch_size=2,
        adapter=adapter,
        sleep_fn=lambda _s: None,
    )
    assert second.cache_hit is True
    assert adapter.calls == 2

    after = close_path.read_bytes()
    assert before == after
    assert first.raw_path.name.startswith("yf_2024-01-02_2024-03-29_")


def test_ingestion_retries_with_exponential_backoff_on_temporary_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))
    cfg = _write_universe(tmp_path, ["SPY", "TLT"])
    adapter = FlakyAdapter(failures_before_success=2)
    sleeps: list[float] = []

    result = run_price_ingestion(
        config_path=cfg,
        start="2024-01-02",
        end="2024-01-31",
        source="yf",
        batch_size=2,
        adapter=adapter,
        sleep_fn=sleeps.append,
        retry=RetryConfig(
            max_attempts=4,
            backoff_initial_s=0.1,
            backoff_factor=2.0,
            backoff_max_s=1.0,
        ),
    )

    assert result.cache_hit is False
    assert adapter.calls == 3
    assert sleeps == [0.1, 0.2]
    assert result.close_path.exists()


def test_ingestion_failure_keeps_existing_cache_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))
    cfg = _write_universe(tmp_path, ["SPY", "TLT"])

    priming = CountingAdapter()
    run_price_ingestion(
        config_path=cfg,
        start="2024-01-02",
        end="2024-01-31",
        source="yf",
        batch_size=2,
        adapter=priming,
        sleep_fn=lambda _s: None,
    )
    cache_root = data_dir() / "prices" / "cache"
    before = {p.name: p.read_bytes() for p in cache_root.glob("*.parquet")}
    assert before

    failing = AlwaysFailAdapter()
    with pytest.raises(RuntimeError, match="Failed to download prices for #1"):
        run_price_ingestion(
            config_path=cfg,
            start="2024-02-01",  # new key: forces cache miss and download attempt
            end="2024-02-29",
            source="yf",
            batch_size=2,
            adapter=failing,
            sleep_fn=lambda _s: None,
            retry=RetryConfig(max_attempts=2, backoff_initial_s=0.01, backoff_factor=2.0),
        )

    after = {p.name: p.read_bytes() for p in cache_root.glob("*.parquet")}
    assert after == before
