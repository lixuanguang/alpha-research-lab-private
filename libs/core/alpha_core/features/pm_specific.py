"""Prediction-market-specific feature implementations.

PM features treat price as implied probability (price ∈ [0, 1]) and layer on
market-microstructure signals unique to prediction markets: time-to-resolution
decay, cross-venue arbitrage spreads, category-level momentum, and order-book
imbalance.

Missing-column policy
---------------------
When a required column is absent from the input table (e.g. ``resolution_date``,
``category``, ``bid_volume``), the feature returns an all-NaN result *without*
raising.  This keeps pipelines forward-compatible — callers can join metadata
later without breaking existing code paths.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

import alpha_core.features.base as feature_base


def _to_df(table: pa.Table) -> pd.DataFrame:
    return table.to_pandas()


def _has_col(df: pd.DataFrame, *cols: str) -> bool:
    return all(column_name in df.columns for column_name in cols)


def _lagged_delta(series: pd.Series) -> pd.Series:
    return series.diff(1).shift(1)


def _rolling_mean(series: pd.Series, *, window: int, min_periods: int) -> pd.Series:
    return series.rolling(window, min_periods=min_periods).mean()


def _rolling_std(series: pd.Series, *, window: int, min_periods: int) -> pd.Series:
    return series.rolling(window, min_periods=min_periods).std(ddof=1)


def _implied_prob_momentum(series: pd.Series, *, window: int) -> pd.Series:
    lagged_delta = _lagged_delta(series)
    mean = _rolling_mean(lagged_delta, window=window, min_periods=window)
    std = _rolling_std(lagged_delta, window=window, min_periods=window)
    return mean / std.replace(0.0, np.nan)


def _prob_acceleration(series: pd.Series, *, fast: int, slow: int) -> pd.Series:
    lagged_delta = _lagged_delta(series)
    fast_ewm = lagged_delta.ewm(span=fast, adjust=False, min_periods=1).mean()
    slow_ewm = lagged_delta.ewm(span=slow, adjust=False, min_periods=1).mean()
    return fast_ewm - slow_ewm


class ImpliedProbMomentum(feature_base.Feature):
    """Lagged probability-momentum z-score within each instrument."""

    def __init__(self, window: int = 20) -> None:
        self._window = window

    @property
    def name(self) -> str:
        return f"implied_prob_momentum_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "instrument_id"):
            return self._empty_result(len(df))

        transform = partial(_implied_prob_momentum, window=self._window)
        result = (
            df["price"].astype(float).groupby(df["instrument_id"], sort=False).transform(transform)
        )
        values = result.to_numpy(dtype=float, na_value=np.nan)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class CrossVenueSpread(feature_base.Feature):
    """Price spread between equivalent markets on different venues."""

    @property
    def name(self) -> str:
        return "cross_venue_spread"

    @property
    def params(self) -> dict[str, Any]:
        return {}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "instrument_id", "ts_event"):
            return self._empty_result(len(df))

        parsed = df["instrument_id"].str.split(":", n=2, expand=True)
        if parsed.shape[1] < 3:
            return self._empty_result(len(df))

        df = df.copy()
        df["_cross_key"] = parsed[1].str.cat(parsed[2], sep=":")
        df["_price_f"] = df["price"].astype(float)

        spread_map = df.groupby(["ts_event", "_cross_key"])["_price_f"].agg(_spread)
        idx = pd.MultiIndex.from_arrays([df["ts_event"], df["_cross_key"]])
        values = spread_map.reindex(idx).to_numpy(dtype=float, na_value=np.nan)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


def _spread(series: pd.Series) -> float:
    return float(series.max() - series.min()) if len(series) > 1 else float("nan")


class VolumeWeightedProb(feature_base.Feature):
    """Lagged volume-weighted average probability over a rolling window."""

    def __init__(self, window: int = 50) -> None:
        self._window = window

    @property
    def name(self) -> str:
        return f"volume_weighted_prob_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "size", "instrument_id"):
            return self._empty_result(len(df))

        df = df.copy()
        df["_price_f"] = df["price"].astype(float)
        df["_size_f"] = df["size"].astype(float)
        df["_pv"] = df["_price_f"] * df["_size_f"]

        grouped = df.groupby("instrument_id", sort=False)
        pv_history = grouped["_pv"].shift(1)
        size_history = grouped["_size_f"].shift(1)
        pv_roll = (
            pv_history.groupby(df["instrument_id"], sort=False)
            .rolling(self._window, min_periods=self._window)
            .sum()
            .reset_index(level=0, drop=True)
        )
        size_roll = (
            size_history.groupby(df["instrument_id"], sort=False)
            .rolling(self._window, min_periods=self._window)
            .sum()
            .reset_index(level=0, drop=True)
        )
        values = (pv_roll / size_roll.replace(0.0, np.nan)).to_numpy(
            dtype=float,
            na_value=np.nan,
        )
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class TimeToResolutionDecay(feature_base.Feature):
    """Normalised time remaining until resolution."""

    @property
    def name(self) -> str:
        return "time_to_resolution_decay"

    @property
    def params(self) -> dict[str, Any]:
        return {}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "resolution_date", "ts_event"):
            return self._empty_result(len(df))

        res_dt = pd.to_datetime(df["resolution_date"], utc=True)
        ts = pd.to_datetime(df["ts_event"], utc=True)
        ttr_seconds = (res_dt - ts).dt.total_seconds().clip(lower=0.0)

        if "instrument_id" in df.columns:
            max_ttr = ttr_seconds.groupby(df["instrument_id"], sort=False).transform("max")
            denom = max_ttr.replace(0.0, np.nan)
        else:
            denom = float(max(ttr_seconds.max(), 0.0))
            if denom == 0.0:
                denom = float("nan")

        values = (ttr_seconds / denom).clip(0.0, 1.0)
        return feature_base.FeatureResult(
            name=self.name,
            values=values.to_numpy(dtype=float, na_value=np.nan),
            params=self.params,
        )


class CategoryMomentum(feature_base.Feature):
    """Lagged average implied-probability momentum within the same market category."""

    def __init__(self, window: int = 10) -> None:
        self._window = window

    @property
    def name(self) -> str:
        return f"category_momentum_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "ts_event", "category", "instrument_id"):
            return self._empty_result(len(df))

        df = df.copy()
        price_series = df["price"].astype(float)
        instrument_delta = price_series.groupby(df["instrument_id"], sort=False).diff(1)
        df["_ret"] = instrument_delta.groupby(df["instrument_id"], sort=False).shift(1)

        cat_ts_avg = df.groupby(["ts_event", "category"], sort=False)["_ret"].mean()
        smoother = partial(_rolling_mean, window=self._window, min_periods=1)
        cat_roll = cat_ts_avg.groupby(level="category", sort=False).transform(smoother)

        idx = pd.MultiIndex.from_arrays([df["ts_event"], df["category"]])
        values = cat_roll.reindex(idx).to_numpy(dtype=float, na_value=np.nan)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class BookImbalance(feature_base.Feature):
    """Order-book imbalance at best N levels."""

    def __init__(self, levels: int = 3) -> None:
        self._levels = levels

    @property
    def name(self) -> str:
        return f"book_imbalance_{self._levels}"

    @property
    def params(self) -> dict[str, Any]:
        return {"levels": self._levels}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "bid_volume", "ask_volume"):
            return self._empty_result(len(df))

        bid = df["bid_volume"].astype(float)
        ask = df["ask_volume"].astype(float)
        total = bid + ask
        values = ((bid - ask) / total.replace(0.0, np.nan)).to_numpy(
            dtype=float,
            na_value=np.nan,
        )
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class ProbAcceleration(feature_base.Feature):
    """Lagged probability acceleration: fast_ewm - slow_ewm of prior price changes."""

    def __init__(self, fast: int = 5, slow: int = 20) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self._fast = fast
        self._slow = slow

    @property
    def name(self) -> str:
        return f"prob_acceleration_{self._fast}_{self._slow}"

    @property
    def params(self) -> dict[str, Any]:
        return {"fast": self._fast, "slow": self._slow}

    def compute(
        self,
        data: pa.Table,
        *,
        instrument_id: str | None = None,
    ) -> feature_base.FeatureResult:
        del instrument_id
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "instrument_id"):
            return self._empty_result(len(df))

        transform = partial(_prob_acceleration, fast=self._fast, slow=self._slow)
        result = (
            df["price"].astype(float).groupby(df["instrument_id"], sort=False).transform(transform)
        )
        values = result.to_numpy(dtype=float, na_value=np.nan)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


__all__ = [
    "BookImbalance",
    "CategoryMomentum",
    "CrossVenueSpread",
    "ImpliedProbMomentum",
    "ProbAcceleration",
    "TimeToResolutionDecay",
    "VolumeWeightedProb",
]
