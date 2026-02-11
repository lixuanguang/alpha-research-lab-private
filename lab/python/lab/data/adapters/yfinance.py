"""Yahoo Finance adapter with canonical adjusted OHLCV normalization.

Policy
------
Canonical tradable prices are downloaded with ``auto_adjust=True`` so split
and dividend adjustments are handled upstream by Yahoo. We normalize bars to
the schema: ``close, open, high, low, volume`` (lowercase).
"""

from __future__ import annotations

import pandas as pd

from lab.data.adapters.base import PriceDataAdapter

_CANONICAL_FIELDS = ["close", "open", "high", "low", "volume"]
_FIELD_ALIASES = {
    "close": "close",
    "adj close": "close",
    "open": "open",
    "high": "high",
    "low": "low",
    "volume": "volume",
}


def _normalize_field_name(field: object) -> str | None:
    key = str(field).strip().lower()
    return _FIELD_ALIASES.get(key)


def _ensure_datetime_index(raw: pd.DataFrame) -> pd.DataFrame:
    out = raw.copy()
    out.index = pd.DatetimeIndex(out.index).tz_localize(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _detect_ticker_level(
    cols: pd.MultiIndex,
    tickers: list[str],
) -> int:
    lvl0 = set(map(str, cols.get_level_values(0)))
    lvl1 = set(map(str, cols.get_level_values(1)))
    tick = set(map(str, tickers))
    if len(tick & lvl0) >= len(tick & lvl1):
        return 0
    return 1


def _one_ticker_ohlcv(
    raw: pd.DataFrame,
    *,
    ticker: str,
) -> pd.DataFrame:
    rename_map: dict[object, str] = {}
    for col in raw.columns:
        mapped = _normalize_field_name(col)
        if mapped is not None:
            rename_map[col] = mapped

    norm = raw.rename(columns=rename_map)
    if "close" not in norm.columns:
        raise ValueError(f"Yahoo download for {ticker} is missing adjusted close/close.")

    out = pd.DataFrame(index=norm.index, dtype=float)
    for field in _CANONICAL_FIELDS:
        if field in norm.columns:
            out[field] = pd.to_numeric(norm[field], errors="coerce")
        else:
            out[field] = pd.Series(index=norm.index, dtype=float)
    return out


def _to_canonical_ohlcv(
    raw: pd.DataFrame,
    *,
    tickers: list[str],
) -> pd.DataFrame:
    if raw.empty:
        empty = pd.DataFrame(
            index=pd.DatetimeIndex([]),
            columns=pd.MultiIndex.from_product(
                [tickers, _CANONICAL_FIELDS], names=["ticker", "field"]
            ),
            dtype=float,
        )
        return empty

    base = _ensure_datetime_index(raw)
    per_ticker: dict[str, pd.DataFrame] = {}

    if isinstance(base.columns, pd.MultiIndex):
        ticker_level = _detect_ticker_level(base.columns, tickers)
        field_level = 1 - ticker_level
        available_tickers = {
            str(v) for v in base.columns.get_level_values(ticker_level).unique().tolist()
        }
        for ticker in tickers:
            if ticker not in available_tickers:
                per_ticker[ticker] = pd.DataFrame(index=base.index, columns=_CANONICAL_FIELDS)
                continue
            one = base.xs(ticker, axis=1, level=ticker_level, drop_level=True)
            per_ticker[ticker] = _one_ticker_ohlcv(
                one.rename(columns=lambda c: str(c) if field_level == 0 else c),
                ticker=ticker,
            )
    else:
        ticker = tickers[0] if tickers else "ticker"
        per_ticker[ticker] = _one_ticker_ohlcv(base, ticker=ticker)
        for t in tickers[1:]:
            per_ticker[t] = pd.DataFrame(index=base.index, columns=_CANONICAL_FIELDS)

    out = pd.concat(per_ticker, axis=1, names=["ticker", "field"]).sort_index(axis=1)
    cols = pd.MultiIndex.from_product([tickers, _CANONICAL_FIELDS], names=["ticker", "field"])
    out = out.reindex(columns=cols)
    return out.astype(float)


def _to_wide_prices(
    canonical_ohlcv: pd.DataFrame,
    *,
    tickers: list[str],
) -> pd.DataFrame:
    if canonical_ohlcv.empty:
        return pd.DataFrame(columns=tickers)

    if not isinstance(canonical_ohlcv.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex OHLCV columns.")

    close = canonical_ohlcv.xs("close", axis=1, level="field", drop_level=True)
    close = close.reindex(columns=tickers)
    missing = [t for t in tickers if t not in close.columns or close[t].isna().all()]
    if missing:
        raise ValueError(f"Missing adjusted close series for tickers: {', '.join(missing)}")

    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    close = close.sort_index()
    return close


def _to_actions(
    raw: pd.DataFrame,
    tickers: list[str],
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["date", "ticker", "dividends", "splits"])

    base = _ensure_datetime_index(raw)
    per_div: dict[str, pd.Series] = {}
    per_spl: dict[str, pd.Series] = {}

    if isinstance(base.columns, pd.MultiIndex):
        ticker_level = _detect_ticker_level(base.columns, tickers)
        available_tickers = {
            str(v) for v in base.columns.get_level_values(ticker_level).unique().tolist()
        }
        for ticker in tickers:
            if ticker not in available_tickers:
                per_div[ticker] = pd.Series(0.0, index=base.index, dtype=float)
                per_spl[ticker] = pd.Series(0.0, index=base.index, dtype=float)
                continue
            one = base.xs(ticker, axis=1, level=ticker_level, drop_level=True)
            div_col = next((c for c in one.columns if str(c).strip().lower() == "dividends"), None)
            spl_col = next(
                (c for c in one.columns if str(c).strip().lower() == "stock splits"),
                None,
            )
            per_div[ticker] = (
                pd.to_numeric(one[div_col], errors="coerce")
                if div_col is not None
                else pd.Series(0.0, index=base.index, dtype=float)
            )
            per_spl[ticker] = (
                pd.to_numeric(one[spl_col], errors="coerce")
                if spl_col is not None
                else pd.Series(0.0, index=base.index, dtype=float)
            )
    else:
        ticker = tickers[0] if tickers else "ticker"
        div_col = next((c for c in base.columns if str(c).strip().lower() == "dividends"), None)
        spl_col = next(
            (c for c in base.columns if str(c).strip().lower() == "stock splits"),
            None,
        )
        per_div[ticker] = (
            pd.to_numeric(base[div_col], errors="coerce")
            if div_col is not None
            else pd.Series(0.0, index=base.index, dtype=float)
        )
        per_spl[ticker] = (
            pd.to_numeric(base[spl_col], errors="coerce")
            if spl_col is not None
            else pd.Series(0.0, index=base.index, dtype=float)
        )

    div = pd.DataFrame(per_div, index=base.index).reindex(columns=tickers).fillna(0.0)
    spl = pd.DataFrame(per_spl, index=base.index).reindex(columns=tickers).fillna(0.0)

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
        if not tickers:
            return pd.DataFrame()

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
            auto_adjust=True,
            actions=True,
            progress=False,
            group_by="ticker",
            threads=self.threads,
            interval="1d",
        )
        if not isinstance(raw, pd.DataFrame):
            raise RuntimeError("yfinance returned unexpected payload type.")
        return raw

    def download_ohlcv(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame | None:
        if not tickers:
            cols = pd.MultiIndex.from_product([[], _CANONICAL_FIELDS], names=["ticker", "field"])
            return pd.DataFrame(columns=cols, dtype=float)
        raw = self._download(tickers=tickers, start=start, end=end)
        return _to_canonical_ohlcv(raw, tickers=tickers)

    def download_prices(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame(columns=[])
        canonical_ohlcv = self.download_ohlcv(tickers=tickers, start=start, end=end)
        if canonical_ohlcv is None:
            raise RuntimeError("Failed to download OHLCV data from yfinance.")
        return _to_wide_prices(canonical_ohlcv, tickers=tickers)

    def download_actions(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame | None:
        if not tickers:
            return pd.DataFrame(columns=["date", "ticker", "dividends", "splits"])
        raw = self._download(tickers=tickers, start=start, end=end)
        return _to_actions(raw, tickers=tickers)
