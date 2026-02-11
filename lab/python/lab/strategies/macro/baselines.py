"""Baseline portfolio definitions for macro allocator evaluation."""

from __future__ import annotations

import pandas as pd


def equal_weight_long_only(
    tickers: list[str],
    gross_cap: float = 1.0,
) -> pd.Series:
    """Equal-weight long-only baseline across all tickers."""
    if not tickers:
        return pd.Series(dtype=float)
    w = pd.Series(gross_cap / len(tickers), index=tickers, dtype=float)
    return w


def sixty_forty_proxy(
    tickers: list[str],
    gross_cap: float = 1.0,
    equity_ticker: str = "SPY",
    rates_ticker: str = "IEF",
) -> pd.Series:
    """60/40 proxy baseline, falling back to first two available assets."""
    if not tickers:
        return pd.Series(dtype=float)

    eq = equity_ticker if equity_ticker in tickers else tickers[0]
    rt = (
        rates_ticker
        if rates_ticker in tickers
        else (tickers[1] if len(tickers) > 1 else tickers[0])
    )

    w = pd.Series(0.0, index=tickers, dtype=float)
    if eq == rt:
        w.loc[eq] = gross_cap
    else:
        w.loc[eq] = 0.6 * gross_cap
        w.loc[rt] = 0.4 * gross_cap
    return w
