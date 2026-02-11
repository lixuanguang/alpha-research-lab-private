"""Synthetic fallback adapter for deterministic local testing."""

from __future__ import annotations

import pandas as pd

from lab.data.adapters.base import PriceDataAdapter
from lab.data.synthetic import generate_gbm_prices


class SyntheticAdapter(PriceDataAdapter):
    source = "synthetic"

    def __init__(self, seed: int = 42) -> None:
        self.seed = int(seed)

    def download_prices(
        self,
        tickers: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        return generate_gbm_prices(
            tickers=tickers,
            start=start,
            end=end,
            seed=self.seed,
        )
