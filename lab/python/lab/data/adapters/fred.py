"""FRED macro-data ingestion and local loading utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from lab.core.paths import data_dir
from lab.data.cache import write_parquet_if_changed

FRED_API_ENV = "FRED_API_KEY"
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


class FredAPIError(RuntimeError):
    """Raised when FRED API calls fail or return malformed payloads."""


def fred_root(root: Path | None = None) -> Path:
    base = root if root is not None else data_dir() / "macro" / "fred"
    base.mkdir(parents=True, exist_ok=True)
    return base


def require_fred_api_key() -> str:
    key = os.environ.get(FRED_API_ENV, "").strip()
    if not key:
        raise RuntimeError(
            f"Missing {FRED_API_ENV}. Set it in your shell, e.g. "
            f"`export {FRED_API_ENV}=your_api_key`."
        )
    return key


def _parse_observations(payload: dict[str, object], series_id: str) -> pd.DataFrame:
    raw = payload.get("observations")
    if not isinstance(raw, list):
        raise FredAPIError(f"FRED payload for {series_id} missing 'observations'.")

    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        value = row.get("value")
        if not isinstance(date, str):
            continue
        dates.append(pd.Timestamp(date))
        if isinstance(value, str):
            values.append(float("nan") if value.strip() == "." else float(value))
        else:
            values.append(float("nan"))

    out = pd.DataFrame({"value": values}, index=pd.DatetimeIndex(dates))
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.index.name = "date"
    return out


def fetch_fred_series(
    *,
    series_id: str,
    start: str,
    end: str,
    api_key: str,
    timeout_s: float = 30.0,
) -> pd.DataFrame:
    params = urlencode(
        {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": str(pd.Timestamp(start).date()),
            "observation_end": str(pd.Timestamp(end).date()),
            "sort_order": "asc",
        }
    )
    url = f"{FRED_OBSERVATIONS_URL}?{params}"

    try:
        with urlopen(url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise FredAPIError(f"FRED request failed for {series_id}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise FredAPIError(f"FRED request failed for {series_id}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FredAPIError(f"FRED response for {series_id} is not valid JSON.") from exc

    if isinstance(payload, dict) and isinstance(payload.get("error_message"), str):
        raise FredAPIError(f"FRED error for {series_id}: {payload['error_message']}")
    if not isinstance(payload, dict):
        raise FredAPIError(f"FRED response for {series_id} has unexpected structure.")

    return _parse_observations(payload, series_id)


def ingest_fred_series(
    *,
    series_ids: list[str],
    start: str,
    end: str,
    api_key: str,
    root: Path | None = None,
) -> dict[str, Path]:
    out_paths: dict[str, Path] = {}
    target = fred_root(root)
    unique_ids = list(dict.fromkeys(series_ids))
    for series_id in unique_ids:
        values = fetch_fred_series(
            series_id=series_id,
            start=start,
            end=end,
            api_key=api_key,
        )
        path = target / f"{series_id}.parquet"
        write_parquet_if_changed(values, path, index=True)
        out_paths[series_id] = path
    return out_paths


def _load_fred_file(path: Path, series_id: str) -> pd.Series:
    raw = pd.read_parquet(path)
    if isinstance(raw, pd.Series):
        s = pd.to_numeric(raw, errors="coerce")
        s.index = pd.DatetimeIndex(s.index)
        return s.rename(series_id)

    if "value" in raw.columns:
        s = pd.to_numeric(raw["value"], errors="coerce")
    elif series_id in raw.columns:
        s = pd.to_numeric(raw[series_id], errors="coerce")
    else:
        raise ValueError(f"FRED parquet {path} must contain a 'value' column.")

    idx = pd.DatetimeIndex(raw.index if "date" not in raw.columns else pd.to_datetime(raw["date"]))
    s = pd.Series(s.to_numpy(), index=idx, name=series_id)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def load_fred(
    series_ids: list[str],
    start: str,
    end: str,
    *,
    root: Path | None = None,
) -> pd.DataFrame:
    target = fred_root(root)
    unique_ids = list(dict.fromkeys(series_ids))
    if not unique_ids:
        return pd.DataFrame()

    parts: list[pd.Series] = []
    for series_id in unique_ids:
        path = target / f"{series_id}.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"Missing FRED series parquet for {series_id}: {path}. "
                "Run scripts/ingest_macro_fred.py first."
            )
        series = _load_fred_file(path, series_id)
        parts.append(series.loc[start:end])

    panel = pd.concat(parts, axis=1)
    panel.index = pd.DatetimeIndex(panel.index)
    panel = panel.sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    return panel.reindex(columns=unique_ids)
