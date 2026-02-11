"""Acceptance tests for adapter/caching/batching ingestion behavior."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from lab.core.paths import data_dir
from lab.data.adapters.base import PriceDataAdapter
from lab.data.adapters.local import LocalCSVAdapter
from lab.data.adapters.yfinance import YFinanceAdapter
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


class LeadingNaNAdapter(PriceDataAdapter):
    source = "yf"

    def __init__(self, leading_nan_rows: int = 5) -> None:
        self.leading_nan_rows = int(leading_nan_rows)

    def download_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        panel = _price_frame(tickers, start, end)
        if tickers:
            n = min(self.leading_nan_rows, len(panel))
            panel.loc[panel.index[:n], tickers[-1]] = np.nan
        return panel


class OHLCVOnlyAdapter(PriceDataAdapter):
    source = "yf"

    def download_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        del tickers, start, end
        raise AssertionError("download_prices should not be called when OHLCV is available")

    def download_ohlcv(self, tickers: list[str], start: str, end: str) -> pd.DataFrame | None:
        idx = pd.bdate_range(start, end)
        cols = pd.MultiIndex.from_product([tickers, ["close", "open", "high", "low", "volume"]])
        out = pd.DataFrame(index=idx, columns=cols, dtype=float)
        for i, ticker in enumerate(tickers):
            base = 100.0 + i
            ramp = np.linspace(0.0, 3.0, len(idx))
            out[(ticker, "close")] = base + ramp
            out[(ticker, "open")] = base + ramp - 0.2
            out[(ticker, "high")] = base + ramp + 0.4
            out[(ticker, "low")] = base + ramp - 0.5
            out[(ticker, "volume")] = 1_000_000 + 1_000 * i
        out.columns = pd.MultiIndex.from_tuples(out.columns, names=["ticker", "field"])
        return out


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


def test_ingestion_drops_incomplete_leading_rows_instead_of_backfilling_future_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))
    cfg = _write_universe(tmp_path, ["SPY", "TLT"])

    start = "2024-01-02"
    end = "2024-02-29"
    run_price_ingestion(
        config_path=cfg,
        start=start,
        end=end,
        source="yf",
        batch_size=2,
        adapter=LeadingNaNAdapter(leading_nan_rows=5),
        sleep_fn=lambda _s: None,
    )

    close = pd.read_parquet(data_dir() / "prices" / "close.parquet")
    raw = _price_frame(["SPY", "TLT"], start, end)
    raw.loc[raw.index[:5], "TLT"] = np.nan

    first_valid = raw["TLT"].first_valid_index()
    assert first_valid is not None
    assert close.index.min() == first_valid
    assert close.index.min() > pd.Timestamp(start)
    assert np.isfinite(close.to_numpy(dtype=float)).all()
    pd.testing.assert_series_equal(
        close["TLT"],
        raw.loc[close.index, "TLT"],
        check_names=False,
    )


def test_local_csv_adapter_empty_tickers_returns_empty_panel(tmp_path: Path) -> None:
    adapter = LocalCSVAdapter(root=tmp_path / "raw" / "prices")
    out = adapter.download_prices([], start="2024-01-02", end="2024-01-31")
    assert out.empty
    assert list(out.columns) == []


def test_yfinance_adapter_empty_tickers_short_circuits_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = YFinanceAdapter()

    def _should_not_run(*_args: object, **_kwargs: object) -> pd.DataFrame:
        raise AssertionError("download should not be called for empty ticker lists")

    monkeypatch.setattr(adapter, "_download", _should_not_run)

    prices = adapter.download_prices([], start="2024-01-02", end="2024-01-31")
    actions = adapter.download_actions([], start="2024-01-02", end="2024-01-31")

    assert prices.empty
    assert list(prices.columns) == []
    assert isinstance(actions, pd.DataFrame)
    assert list(actions.columns) == ["date", "ticker", "dividends", "splits"]


def test_yfinance_adapter_normalizes_ticker_grouped_ohlcv_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = YFinanceAdapter()
    dates = pd.bdate_range("2024-01-02", periods=3)
    raw_cols = pd.MultiIndex.from_tuples(
        [
            ("SPY", "Volume"),
            ("SPY", "Close"),
            ("SPY", "Open"),
            ("SPY", "High"),
            ("SPY", "Low"),
            ("TLT", "Open"),
            ("TLT", "High"),
            ("TLT", "Low"),
            ("TLT", "Close"),
            ("TLT", "Volume"),
        ]
    )
    raw = pd.DataFrame(
        [
            [1000.0, 100.0, 99.5, 100.5, 99.0, 101.0, 101.5, 100.2, 100.8, 800.0],
            [1100.0, 101.0, 100.5, 101.5, 100.0, 102.0, 102.5, 101.1, 101.8, 820.0],
            [1200.0, 102.0, 101.5, 102.5, 101.0, 103.0, 103.5, 102.0, 102.8, 840.0],
        ],
        index=dates,
        columns=raw_cols,
    )

    monkeypatch.setattr(adapter, "_download", lambda **_kwargs: raw)

    ohlcv = adapter.download_ohlcv(["SPY", "TLT"], start="2024-01-02", end="2024-01-31")
    assert isinstance(ohlcv, pd.DataFrame)
    assert isinstance(ohlcv.columns, pd.MultiIndex)
    assert ohlcv.columns.names == ["ticker", "field"]
    expected_cols = pd.MultiIndex.from_product(
        [["SPY", "TLT"], ["close", "open", "high", "low", "volume"]],
        names=["ticker", "field"],
    )
    assert ohlcv.columns.equals(expected_cols)

    close = adapter.download_prices(["SPY", "TLT"], start="2024-01-02", end="2024-01-31")
    assert list(close.columns) == ["SPY", "TLT"]
    assert close["SPY"].iloc[0] == pytest.approx(100.0)
    assert close["TLT"].iloc[-1] == pytest.approx(102.8)


def test_ingestion_uses_ohlcv_when_available_and_persists_ohlcv_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))
    cfg = _write_universe(tmp_path, ["SPY", "TLT"])

    result = run_price_ingestion(
        config_path=cfg,
        start="2024-01-02",
        end="2024-01-31",
        source="yf",
        batch_size=2,
        adapter=OHLCVOnlyAdapter(),
        sleep_fn=lambda _s: None,
    )

    assert result.ohlcv_path is not None
    assert result.ohlcv_path.exists()
    close = pd.read_parquet(result.close_path)
    assert list(close.columns) == ["SPY", "TLT"]
    assert close.index.is_monotonic_increasing
    assert close.index.is_unique


def test_ingestion_batch_throttle_pause_applies_between_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))
    cfg = _write_universe(tmp_path, ["SPY", "TLT", "GLD"])
    adapter = CountingAdapter()
    sleeps: list[float] = []

    run_price_ingestion(
        config_path=cfg,
        start="2024-01-02",
        end="2024-01-31",
        source="yf",
        batch_size=2,
        adapter=adapter,
        sleep_fn=sleeps.append,
        batch_pause_s=0.25,
        batch_jitter_s=0.0,
    )

    # Two batches => one inter-batch pause.
    assert sleeps == [0.25]


@pytest.mark.parametrize(
    ("meta_override", "error_match"),
    [
        ({"cost_bps": -1.0}, "cost_bps"),
        ({"per_asset_cap": 0.0}, "per_asset_cap"),
        ({"cost_bps": float("nan")}, "finite"),
        ({"per_asset_cap": float("nan")}, "finite"),
    ],
)
def test_ingestion_rejects_invalid_meta_before_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, meta_override: dict[str, float], error_match: str
) -> None:
    monkeypatch.setenv("LAB_DATA_ROOT", str(tmp_path))

    raw = {
        "tickers": ["SPY"],
        "ticker_meta": {
            "SPY": {
                "bucket": "equities",
                "cost_bps": 3.0,
                "per_asset_cap": 0.35,
                **meta_override,
            }
        },
    }
    cfg = tmp_path / "universe.yaml"
    cfg.write_text(yaml.safe_dump(raw))

    with pytest.raises(ValueError, match=error_match):
        run_price_ingestion(
            config_path=cfg,
            start="2024-01-02",
            end="2024-01-31",
            source="yf",
            adapter=CountingAdapter(),
            sleep_fn=lambda _s: None,
        )
