"""Data-source adapters for ingestion."""

from lab.data.adapters.base import PriceDataAdapter
from lab.data.adapters.fred import DEFAULT_WEEK3_SERIES_IDS, load_fred
from lab.data.adapters.local import LocalCSVAdapter
from lab.data.adapters.synthetic import SyntheticAdapter
from lab.data.adapters.yfinance import YFinanceAdapter

__all__ = [
    "LocalCSVAdapter",
    "PriceDataAdapter",
    "SyntheticAdapter",
    "YFinanceAdapter",
    "load_fred",
    "DEFAULT_WEEK3_SERIES_IDS",
]
