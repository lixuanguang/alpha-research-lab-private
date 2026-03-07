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

from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from alpha_core.features.base import Feature, FeatureResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_df(table: pa.Table) -> pd.DataFrame:
    return table.to_pandas()


def _has_col(df: pd.DataFrame, *cols: str) -> bool:
    return all(c in df.columns for c in cols)


# ---------------------------------------------------------------------------
# PM Features
# ---------------------------------------------------------------------------

class ImpliedProbMomentum(Feature):
    """Rate of change in implied probability (price) over a rolling window.

    For prediction markets price ≈ probability, so this directly measures
    probability momentum.  Computed as rolling mean of 1-period price changes,
    normalised by the rolling std to give a momentum z-score.
    """

    def __init__(self, window: int = 20) -> None:
        self._window = window

    @property
    def name(self) -> str:
        return f"implied_prob_momentum_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "instrument_id"):
            return self._empty_result(len(df))

        w = self._window

        def _momentum(s: pd.Series) -> pd.Series:
            delta = s.diff(1)
            mu = delta.rolling(w, min_periods=w).mean()
            sigma = delta.rolling(w, min_periods=w).std(ddof=1)
            return mu / sigma.replace(0.0, np.nan)

        result = (
            df["price"].astype(float)
            .groupby(df["instrument_id"], sort=False)
            .transform(_momentum)
        )
        return FeatureResult(name=self.name, values=result.to_numpy(dtype=float, na_value=np.nan), params=self.params)


class CrossVenueSpread(Feature):
    """Price spread between equivalent markets on different venues.

    Parses canonical instrument IDs (``venue:market_id:outcome_id``) and groups
    by ``market_id:outcome_id`` to identify cross-venue equivalents.  At each
    timestamp the spread is ``max_price - min_price`` across all venues carrying
    that question.  Returns NaN for instruments with no cross-venue counterpart.
    """

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "cross_venue_spread"

    @property
    def params(self) -> dict[str, Any]:
        return {}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "instrument_id", "ts_event"):
            return self._empty_result(len(df))

        # Parse canonical IDs to extract the cross-venue key.
        parsed = df["instrument_id"].str.split(":", n=2, expand=True)
        if parsed.shape[1] < 3:
            # IDs don't follow {venue}:{market_id}:{outcome_id} format → NaN.
            return self._empty_result(len(df))

        df = df.copy()
        df["_cross_key"] = parsed[1].str.cat(parsed[2], sep=":")
        df["_price_f"] = df["price"].astype(float)

        def _spread(s: pd.Series) -> float:
            return float(s.max() - s.min()) if len(s) > 1 else np.nan

        spread_map = df.groupby(["ts_event", "_cross_key"])["_price_f"].agg(_spread)
        idx = pd.MultiIndex.from_arrays([df["ts_event"], df["_cross_key"]])
        values = spread_map.reindex(idx).to_numpy(dtype=float, na_value=np.nan)
        return FeatureResult(name=self.name, values=values, params=self.params)


class VolumeWeightedProb(Feature):
    """Volume-weighted average price (probability) over a rolling window.

    Heavier-volume trades carry stronger conviction; VWAP is a consensus
    probability estimate weighted by market participation intensity.
    """

    def __init__(self, window: int = 50) -> None:
        self._window = window

    @property
    def name(self) -> str:
        return f"volume_weighted_prob_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "size", "instrument_id"):
            return self._empty_result(len(df))

        w = self._window
        df = df.copy()
        df["_pv"] = df["price"].astype(float) * df["size"].astype(float)

        def _vwap(grp: pd.DataFrame) -> pd.Series:
            pv_roll = grp["_pv"].rolling(w, min_periods=w).sum()
            vol_roll = grp["_size_f"].rolling(w, min_periods=w).sum()
            return pv_roll / vol_roll.replace(0.0, np.nan)

        df["_vol"] = df["size"].astype(float)

        def _vwap(s: pd.Series) -> pd.Series:
            # s is the _pv series; companion _vol series accessed via df
            # Use transform on each group individually.
            pv_roll = s.rolling(w, min_periods=w).sum()
            vol_roll = df.loc[s.index, "_vol"].rolling(w, min_periods=w).sum()
            return pv_roll / vol_roll.replace(0.0, np.nan)

        result = (
            df.groupby("instrument_id", sort=False)["_pv"]
            .transform(lambda s: _vwap(s))
        )
        return FeatureResult(
            name=self.name,
            values=result.to_numpy(dtype=float, na_value=np.nan),
            params=self.params,
        )


class TimeToResolutionDecay(Feature):
    """Normalised time remaining until resolution.

    Returns a value in [0, 1] where 1 = maximum horizon (start of observation
    window) and 0 = resolution imminent.  Requires a ``resolution_date`` column
    in the input table (UTC-aware timestamp).  Rows missing a resolution date
    are assigned NaN.

    Formula: clip((resolution_date - ts_event) / max_horizon, 0, 1)
    where max_horizon is the max such duration in the instrument's history.
    """

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "time_to_resolution_decay"

    @property
    def params(self) -> dict[str, Any]:
        return {}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "resolution_date", "ts_event"):
            return self._empty_result(len(df))

        res_dt = pd.to_datetime(df["resolution_date"], utc=True)
        ts = pd.to_datetime(df["ts_event"], utc=True)
        ttr_seconds = (res_dt - ts).dt.total_seconds().clip(lower=0.0)

        # Normalise per instrument by the maximum observed TTR for that instrument.
        if "instrument_id" in df.columns:
            max_ttr = ttr_seconds.groupby(df["instrument_id"], sort=False).transform("max")
        else:
            max_ttr = ttr_seconds.max()

        values = (ttr_seconds / max_ttr.replace(0.0, np.nan)).clip(0.0, 1.0)
        return FeatureResult(
            name=self.name,
            values=values.to_numpy(dtype=float, na_value=np.nan),
            params=self.params,
        )


class CategoryMomentum(Feature):
    """Average implied-probability momentum within the same market category.

    Captures thematic drifts (e.g., all politics markets moving together).
    Requires a ``category`` column in the input table.  Rows without a
    category are assigned the dataset-wide average.
    """

    def __init__(self, window: int = 10) -> None:
        self._window = window

    @property
    def name(self) -> str:
        return f"category_momentum_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "ts_event", "category"):
            return self._empty_result(len(df))

        w = self._window
        df = df.copy()

        # Per-instrument 1-period price delta.
        if "instrument_id" in df.columns:
            df["_ret"] = (
                df["price"].astype(float)
                .groupby(df["instrument_id"], sort=False)
                .transform(lambda s: s.diff(1))
            )
        else:
            df["_ret"] = df["price"].astype(float).diff(1)

        # Average category return at each timestamp.
        cat_ts_avg: pd.Series = df.groupby(["ts_event", "category"])["_ret"].mean()

        # Rolling mean of category averages over time.
        cat_roll = (
            cat_ts_avg
            .groupby(level="category", sort=False)
            .transform(lambda s: s.rolling(w, min_periods=1).mean())
        )

        # Map back to each source row.
        idx = pd.MultiIndex.from_arrays([df["ts_event"], df["category"]])
        values = cat_roll.reindex(idx).to_numpy(dtype=float, na_value=np.nan)
        return FeatureResult(name=self.name, values=values, params=self.params)


class BookImbalance(Feature):
    """Order-book imbalance at best N levels.

    Formula: (bid_volume - ask_volume) / (bid_volume + ask_volume)
    Result range: [-1, +1].  Positive → more bid pressure → price likely to rise.

    Requires ``bid_volume`` and ``ask_volume`` columns (typically from book data
    joined to trades).  Returns NaN when columns are absent.
    """

    def __init__(self, levels: int = 3) -> None:
        self._levels = levels

    @property
    def name(self) -> str:
        return f"book_imbalance_{self._levels}"

    @property
    def params(self) -> dict[str, Any]:
        return {"levels": self._levels}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "bid_volume", "ask_volume"):
            return self._empty_result(len(df))

        bid = df["bid_volume"].astype(float)
        ask = df["ask_volume"].astype(float)
        total = bid + ask
        values = ((bid - ask) / total.replace(0.0, np.nan)).to_numpy(dtype=float, na_value=np.nan)
        return FeatureResult(name=self.name, values=values, params=self.params)


class ProbAcceleration(Feature):
    """Probability acceleration: fast_ewm - slow_ewm of price changes.

    Captures momentum-of-momentum — whether the rate of probability change
    itself is accelerating or decelerating.

    ``fast`` and ``slow`` are EWM span parameters (in periods).
    """

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

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        if not _has_col(df, "price", "instrument_id"):
            return self._empty_result(len(df))

        fast, slow = self._fast, self._slow

        def _accel(s: pd.Series) -> pd.Series:
            delta = s.diff(1)
            return (
                delta.ewm(span=fast, adjust=False).mean()
                - delta.ewm(span=slow, adjust=False).mean()
            )

        result = (
            df["price"].astype(float)
            .groupby(df["instrument_id"], sort=False)
            .transform(_accel)
        )
        return FeatureResult(
            name=self.name,
            values=result.to_numpy(dtype=float, na_value=np.nan),
            params=self.params,
        )


__all__ = [
    "ImpliedProbMomentum",
    "CrossVenueSpread",
    "VolumeWeightedProb",
    "TimeToResolutionDecay",
    "CategoryMomentum",
    "BookImbalance",
    "ProbAcceleration",
]
