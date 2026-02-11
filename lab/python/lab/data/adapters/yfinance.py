"""Yahoo Finance adapter with explicit price-adjustment policy.

Policy
------
Canonical normalized closes use Yahoo's dividend/split-adjusted close
(`Adj Close`) with `auto_adjust=False`. We intentionally avoid re-applying
corporate action math downstream. Raw actions are fetched separately for audit.
"""

from __future__ import annotations

import pandas as pd

from lab.data.adapters.base import PriceDataAdapter


def _to_wide_prices(
    raw: pd.DataFrame,
    tickers: list[str],
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=tickers)

    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)
        if "Adj Close" in level0:
            out = raw["Adj Close"].copy()
        elif "Close" in level0:
            out = raw["Close"].copy()
        else:
            raise ValueError("Yahoo download does not contain 'Adj Close' or 'Close' columns.")
    else:
        col = "Adj Close" if "Adj Close" in raw.columns else "Close"
        if col not in raw.columns:
            raise ValueError("Yahoo download does not contain 'Adj Close' or 'Close' columns.")
        series = raw[col]
        out = series.to_frame(name=tickers[0] if tickers else "ticker")

    out.index = pd.DatetimeIndex(out.index).tz_localize(None)
    out = out.sort_index()
    return out.reindex(columns=tickers)


def _to_actions(
    raw: pd.DataFrame,
    tickers: list[str],
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["date", "ticker", "dividends", "splits"])

    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)
        if "Dividends" not in level0 or "Stock Splits" not in level0:
            return pd.DataFrame(columns=["date", "ticker", "dividends", "splits"])
        div = raw["Dividends"].copy()
        spl = raw["Stock Splits"].copy()
    else:
        if "Dividends" not in raw.columns or "Stock Splits" not in raw.columns:
            return pd.DataFrame(columns=["date", "ticker", "dividends", "splits"])
        t = tickers[0] if tickers else "ticker"
        div = raw["Dividends"].to_frame(name=t)
        spl = raw["Stock Splits"].to_frame(name=t)

    div = div.reindex(columns=tickers).fillna(0.0)
    spl = spl.reindex(columns=tickers).fillna(0.0)

    actions = (
        pd.concat(
            {
                "dividends": div.stack(),
                "splits": spl.stack(),
            },
            axis=1,
        )
        .reset_index()
        .rename(columns={"level_0": "date", "level_1": "ticker"})
    )
    actions["date"] = pd.to_datetime(actions["date"]).dt.tz_localize(None)
    mask = (actions["dividends"] != 0.0) | (actions["splits"] != 0.0)
    return actions.loc[mask].sort_values(["date", "ticker"]).reset_index(drop=True)


class YFinanceAdapter(PriceDataAdapter):
    source = "yf"

    def __init__(self, *, threads: bool = False) -> None:
        # Keep requests serialized by default to be friendlier to rate limits.
        self.threads = bool(threads)

    def _download(
        self,
        *,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "yfinance is required for source='yf'. Install it via `pip install yfinance`."
            ) from exc

        yf_tickers: str | list[str] = tickers[0] if len(tickers) == 1 else tickers

        raw = yf.download(
            tickers=yf_tickers,
            start=start,
            end=end,
            auto_adjust=False,
            actions=True,
            progress=False,
            group_by="column",
            threads=self.threads,
            interval="1d",
        )
        if not isinstance(raw, pd.DataFrame):
            raise RuntimeError("yfinance returned unexpected payload type.")
        return raw

    def download_prices(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        raw = self._download(tickers=tickers, start=start, end=end)
        return _to_wide_prices(raw, tickers=tickers)

    def download_actions(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame | None:
        raw = self._download(tickers=tickers, start=start, end=end)
        return _to_actions(raw, tickers=tickers)
