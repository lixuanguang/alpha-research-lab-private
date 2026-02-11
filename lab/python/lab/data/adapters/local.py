"""Local CSV adapter for daily close ingestion."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from lab.core.paths import data_dir
from lab.data.adapters.base import PriceDataAdapter

_CLOSE_COLUMN_CANDIDATES = [
    "adj_close",
    "Adj Close",
    "close",
    "Close",
]

_DATE_COLUMN_CANDIDATES = [
    "date",
    "Date",
    "timestamp",
    "Timestamp",
]


def _load_one_csv(path: Path) -> pd.Series:
    raw = pd.read_csv(path)

    date_col = next((c for c in _DATE_COLUMN_CANDIDATES if c in raw.columns), None)
    close_col = next((c for c in _CLOSE_COLUMN_CANDIDATES if c in raw.columns), None)

    if date_col is None or close_col is None:
        raise ValueError(
            f"CSV {path} must include date and close columns (got {list(raw.columns)})."
        )

    s = pd.Series(raw[close_col].to_numpy(), index=pd.to_datetime(raw[date_col]), name=path.stem)
    s = s[~s.index.duplicated(keep="last")]
    s = s.sort_index()
    return s.astype(float)


class LocalCSVAdapter(PriceDataAdapter):
    source = "local"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else data_dir() / "raw" / "prices"

    def download_prices(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame(columns=[])

        self.root.mkdir(parents=True, exist_ok=True)
        parts: list[pd.Series] = []
        missing: list[str] = []
        for ticker in tickers:
            p = self.root / f"{ticker}.csv"
            if not p.exists():
                missing.append(ticker)
                continue
            parts.append(_load_one_csv(p).rename(ticker))

        if missing:
            miss = ", ".join(missing)
            raise FileNotFoundError(f"Missing local CSV files for tickers: {miss}")

        panel = pd.concat(parts, axis=1).sort_index()
        panel = panel.loc[start:end]
        return panel.reindex(columns=tickers)
