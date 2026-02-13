"""Reusable ingestion pipeline with adapters, batching, retries, and caching."""

from __future__ import annotations

import dataclasses
import math
import random
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from lab.core.logging import get_logger
from lab.core.paths import data_dir
from lab.data.adapters import (
    LocalCSVAdapter,
    PriceDataAdapter,
    SyntheticAdapter,
    YFinanceAdapter,
)
from lab.data.cache import PriceCache, write_parquet_if_changed
from lab.data.loaders.prices import (
    _coerce_price_panel,
    _validate_close_panel,
    write_price_artifacts,
)

log = get_logger("data.ingestion")


@dataclasses.dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 4
    backoff_initial_s: float = 1.0
    backoff_factor: float = 2.0
    backoff_max_s: float = 30.0


@dataclasses.dataclass(frozen=True)
class IngestionResult:
    cache_hit: bool
    source: str
    cache_key_id: str
    raw_path: Path
    close_path: Path
    meta_path: Path
    actions_path: Path | None
    ohlcv_path: Path | None


def _chunked(items: list[str], n: int) -> Iterable[list[str]]:
    if n <= 0:
        raise ValueError("batch size must be > 0")
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _load_universe(path: Path) -> tuple[list[str], pd.DataFrame]:
    raw = yaml.safe_load(path.read_text()) or {}
    tickers = raw.get("tickers", [])
    if not isinstance(tickers, list) or not tickers:
        raise ValueError("universe config must define a non-empty 'tickers' list.")
    if len(set(tickers)) != len(tickers):
        raise ValueError("universe config 'tickers' must not contain duplicates.")

    ticker_meta = raw.get("ticker_meta", {})
    if not isinstance(ticker_meta, dict):
        raise ValueError("universe config 'ticker_meta' must be a mapping.")

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        info = ticker_meta.get(ticker, {})
        if not isinstance(info, dict):
            raise ValueError(f"ticker_meta['{ticker}'] must be a mapping.")
        row: dict[str, Any] = {
            "ticker": ticker,
            "bucket": info.get("bucket", "other"),
            "cost_bps": float(info.get("cost_bps", 5.0)),
            "per_asset_cap": float(info.get("per_asset_cap", 0.35)),
        }
        for key, value in info.items():
            if key in row:
                continue
            row[key] = value
        rows.append(row)

    meta = pd.DataFrame.from_records(rows)
    return tickers, meta


def _normalize_close_panel(
    raw_panel: pd.DataFrame,
    *,
    tickers: list[str],
    start: str,
    end: str,
    ffill_limit: int = 3,
) -> pd.DataFrame:
    out = _coerce_price_panel(raw_panel.reindex(columns=tickers))
    out = out.loc[start:end]
    if out.empty:
        raise ValueError(f"Downloaded price panel is empty for requested window {start}..{end}.")

    out = out.replace([np.inf, -np.inf], np.nan)
    # Use conservative forward-fill only (never back-fill), and only for short
    # gaps typical of exchange/trading-halt mismatches.
    if ffill_limit > 0:
        out = out.ffill(limit=int(ffill_limit))
    complete_rows = out.notna().all(axis=1)
    if not complete_rows.any():
        raise ValueError(
            "Downloaded price panel has no fully-observed rows after conservative forward-fill; "
            "at least one asset has no valid history in the requested window."
        )
    dropped = int((~complete_rows).sum())
    if dropped > 0:
        log.warning(
            "Dropping %d leading/incomplete rows to preserve no-lookahead data integrity.",
            dropped,
        )
    out = out.loc[complete_rows]
    out = _coerce_price_panel(out)
    _validate_close_panel(out)
    return out


def _download_with_retry(
    *,
    download_fn: Callable[[], pd.DataFrame | None],
    retry: RetryConfig,
    sleep_fn: Callable[[float], None],
    batch_label: str,
    payload: str,
    allow_none: bool = False,
) -> pd.DataFrame | None:
    if retry.max_attempts < 1:
        raise ValueError("retry.max_attempts must be >= 1.")

    for attempt in range(1, retry.max_attempts + 1):
        try:
            out = download_fn()
            if out is None:
                if allow_none:
                    return None
                raise RuntimeError(f"adapter returned None payload for {payload}.")
            if not isinstance(out, pd.DataFrame):
                raise RuntimeError(f"adapter returned non-DataFrame payload for {payload}.")
            return out
        except Exception as exc:
            if attempt >= retry.max_attempts:
                raise RuntimeError(
                    f"Failed to download {payload} for {batch_label} after "
                    f"{retry.max_attempts} attempts: {exc}"
                ) from exc
            delay = min(
                retry.backoff_max_s,
                retry.backoff_initial_s * math.pow(retry.backoff_factor, attempt - 1),
            )
            log.warning(
                "Batch %s attempt %d/%d failed (%s). Retrying in %.2fs",
                batch_label,
                attempt,
                retry.max_attempts,
                exc,
                delay,
            )
            sleep_fn(delay)

    raise RuntimeError("unreachable retry state")


def _sleep_between_batches(
    *,
    idx: int,
    n_batches: int,
    batch_pause_s: float,
    batch_jitter_s: float,
    sleep_fn: Callable[[float], None],
    rng: random.Random,
) -> None:
    if idx >= n_batches:
        return
    base = max(0.0, float(batch_pause_s))
    jitter = max(0.0, float(batch_jitter_s))
    delay = base + (rng.uniform(0.0, jitter) if jitter > 0.0 else 0.0)
    if delay > 0.0:
        sleep_fn(delay)


def _batched_download_prices(
    *,
    adapter: PriceDataAdapter,
    tickers: list[str],
    start: str,
    end: str,
    batch_size: int,
    retry: RetryConfig,
    sleep_fn: Callable[[float], None],
    batch_pause_s: float = 0.0,
    batch_jitter_s: float = 0.0,
    rng: random.Random | None = None,
) -> pd.DataFrame:
    batches = list(_chunked(tickers, batch_size))
    prng = rng if rng is not None else random.Random()
    parts: list[pd.DataFrame] = []
    for idx, batch in enumerate(batches, start=1):
        label = f"#{idx} ({batch[0]}..{batch[-1]}, n={len(batch)})"
        log.info("Downloading batch %s", label)
        part = _download_with_retry(
            download_fn=lambda batch=batch: adapter.download_prices(
                tickers=batch,
                start=start,
                end=end,
            ),
            retry=retry,
            sleep_fn=sleep_fn,
            batch_label=label,
            payload="prices",
        )
        if part is None:
            raise RuntimeError("adapter returned None payload for prices.")
        part = _coerce_price_panel(part).reindex(columns=batch)
        parts.append(part)
        _sleep_between_batches(
            idx=idx,
            n_batches=len(batches),
            batch_pause_s=batch_pause_s,
            batch_jitter_s=batch_jitter_s,
            sleep_fn=sleep_fn,
            rng=prng,
        )

    if not parts:
        return pd.DataFrame(columns=tickers)

    merged = pd.concat(parts, axis=1)
    merged = merged.loc[:, ~merged.columns.duplicated(keep="last")]
    return merged.reindex(columns=tickers)


def _batched_download_ohlcv(
    *,
    adapter: PriceDataAdapter,
    tickers: list[str],
    start: str,
    end: str,
    batch_size: int,
    retry: RetryConfig,
    sleep_fn: Callable[[float], None],
    batch_pause_s: float = 0.0,
    batch_jitter_s: float = 0.0,
    rng: random.Random | None = None,
) -> pd.DataFrame | None:
    batches = list(_chunked(tickers, batch_size))
    prng = rng if rng is not None else random.Random()
    parts: list[pd.DataFrame] = []
    for idx, batch in enumerate(batches, start=1):
        label = f"#{idx} ({batch[0]}..{batch[-1]}, n={len(batch)})"
        log.info("Downloading OHLCV batch %s", label)
        part = _download_with_retry(
            download_fn=lambda batch=batch: adapter.download_ohlcv(
                tickers=batch,
                start=start,
                end=end,
            ),
            retry=retry,
            sleep_fn=sleep_fn,
            batch_label=label,
            payload="OHLCV",
            allow_none=True,
        )
        if part is None:
            return None
        part = part.sort_index()
        parts.append(part)
        _sleep_between_batches(
            idx=idx,
            n_batches=len(batches),
            batch_pause_s=batch_pause_s,
            batch_jitter_s=batch_jitter_s,
            sleep_fn=sleep_fn,
            rng=prng,
        )

    if not parts:
        return pd.DataFrame()

    merged = pd.concat(parts, axis=1)
    if isinstance(merged.columns, pd.MultiIndex):
        merged = merged.loc[:, ~merged.columns.duplicated(keep="last")]
    return merged


def _extract_close_from_ohlcv(
    ohlcv: pd.DataFrame,
    *,
    tickers: list[str],
) -> pd.DataFrame:
    if ohlcv.empty:
        return pd.DataFrame(columns=tickers)
    if not isinstance(ohlcv.columns, pd.MultiIndex):
        raise ValueError("Expected OHLCV DataFrame with MultiIndex columns.")

    level = "field" if "field" in ohlcv.columns.names else -1
    close = ohlcv.xs("close", axis=1, level=level, drop_level=True)
    close = _coerce_price_panel(close).reindex(columns=tickers)
    missing = [t for t in tickers if t not in close.columns or close[t].isna().all()]
    if missing:
        raise ValueError(f"Missing close columns for tickers: {', '.join(missing)}")
    return close


def _adapter_for_source(source: str) -> PriceDataAdapter:
    src = source.strip().lower()
    if src in {"yf", "yfinance"}:
        return YFinanceAdapter()
    if src == "local":
        return LocalCSVAdapter()
    if src == "synthetic":
        return SyntheticAdapter()
    raise ValueError(f"unknown source '{source}'")


def run_price_ingestion(
    *,
    config_path: Path,
    start: str,
    end: str,
    source: str,
    batch_size: int = 20,
    retry: RetryConfig | None = None,
    cache: PriceCache | None = None,
    adapter: PriceDataAdapter | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    cache_params: dict[str, Any] | None = None,
    batch_pause_s: float = 0.0,
    batch_jitter_s: float = 0.0,
    rng: random.Random | None = None,
) -> IngestionResult:
    """Ingest, cache, normalize, and persist price artifacts."""
    tickers, meta = _load_universe(config_path)
    resolved_adapter = adapter or _adapter_for_source(source)
    source_key = resolved_adapter.source

    prices_root = data_dir() / "prices"
    raw_root = prices_root / "raw"
    cache_root = prices_root / "cache"
    raw_root.mkdir(parents=True, exist_ok=True)
    cache_obj = cache if cache is not None else PriceCache(cache_root)
    retry_cfg = retry if retry is not None else RetryConfig()

    key = cache_obj.key(
        source=source_key,
        tickers=tickers,
        start=start,
        end=end,
        params=cache_params
        or {
            "batch_size": batch_size,
            "batch_pause_s": batch_pause_s,
            "batch_jitter_s": batch_jitter_s,
        },
    )
    cache_hit = False
    ohlcv_panel: pd.DataFrame | None = None
    cached = cache_obj.load(key)
    if cached is not None:
        raw_panel, close_panel = cached
        cache_hit = True
        log.info("Cache hit: %s", key.id)
    else:
        log.info("Cache miss: %s", key.id)
        ohlcv_panel = _batched_download_ohlcv(
            adapter=resolved_adapter,
            tickers=tickers,
            start=start,
            end=end,
            batch_size=batch_size,
            retry=retry_cfg,
            sleep_fn=sleep_fn,
            batch_pause_s=batch_pause_s,
            batch_jitter_s=batch_jitter_s,
            rng=rng,
        )
        if ohlcv_panel is not None:
            raw_panel = _extract_close_from_ohlcv(ohlcv_panel, tickers=tickers)
        else:
            raw_panel = _batched_download_prices(
                adapter=resolved_adapter,
                tickers=tickers,
                start=start,
                end=end,
                batch_size=batch_size,
                retry=retry_cfg,
                sleep_fn=sleep_fn,
                batch_pause_s=batch_pause_s,
                batch_jitter_s=batch_jitter_s,
                rng=rng,
            )
        close_panel = _normalize_close_panel(raw_panel, tickers=tickers, start=start, end=end)
        # Store only after full successful processing.
        cache_obj.store(key, raw=raw_panel, normalized=close_panel)

    date_range = f"{pd.Timestamp(start).date()}_{pd.Timestamp(end).date()}"
    raw_name = f"{source_key}_{date_range}_{key.short_hash}.parquet"
    raw_path = raw_root / raw_name
    write_parquet_if_changed(_coerce_price_panel(raw_panel), raw_path, index=True)
    ohlcv_path: Path | None = None
    ohlcv_name = f"{source_key}_{date_range}_{key.short_hash}_ohlcv.parquet"
    candidate_ohlcv_path = raw_root / ohlcv_name
    if isinstance(ohlcv_panel, pd.DataFrame) and not ohlcv_panel.empty:
        write_parquet_if_changed(ohlcv_panel, candidate_ohlcv_path, index=True)
        ohlcv_path = candidate_ohlcv_path
    elif candidate_ohlcv_path.exists():
        ohlcv_path = candidate_ohlcv_path

    write_price_artifacts(close_panel, meta, only_if_changed=True)

    actions_path: Path | None = None
    try:
        actions = resolved_adapter.download_actions(tickers=tickers, start=start, end=end)
        if isinstance(actions, pd.DataFrame) and not actions.empty:
            actions_path = raw_root / f"{source_key}_{date_range}_{key.short_hash}_actions.parquet"
            write_parquet_if_changed(actions, actions_path, index=False)
    except Exception as exc:
        log.warning("Actions download skipped due to adapter error: %s", exc)

    # Keep week-1 compatibility artifact stable.
    write_parquet_if_changed(close_panel, data_dir() / "prices.parquet", index=True)

    return IngestionResult(
        cache_hit=cache_hit,
        source=source_key,
        cache_key_id=key.id,
        raw_path=raw_path,
        close_path=prices_root / "close.parquet",
        meta_path=prices_root / "meta.parquet",
        actions_path=actions_path,
        ohlcv_path=ohlcv_path,
    )
