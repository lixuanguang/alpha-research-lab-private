"""Base interfaces for price-data adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class PriceDataAdapter(ABC):
    """Abstract adapter contract for market-data sources."""

    source: str

    @abstractmethod
    def download_prices(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """Return a daily close panel indexed by date with ticker columns."""

    def download_ohlcv(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame | None:
        """Return optional OHLCV panel with MultiIndex columns (ticker, field)."""
        del tickers, start, end
        return None

    def download_actions(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame | None:
        """Return optional corporate actions (dividends/splits)."""
        del tickers, start, end
        return None
