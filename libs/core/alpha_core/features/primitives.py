"""Time-series feature primitives for the feature registry.

All primitives:
- Operate per-instrument (group by ``instrument_id``).
- Use one-step-lagged history by default so the feature at row ``t`` only
  depends on information available before that row.
- Propagate NaN for warm-up rows where insufficient history exists.
- Preserve input row order — output index matches input index.
- Accept a ``source_col`` parameter (default ``"price"``) to support
  computing on any numeric column.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa

import alpha_core.features.base as feature_base

FloatArray = npt.NDArray[np.float64]
SeriesTransform = Callable[[pd.Series], pd.Series]


def _to_df(table: pa.Table) -> pd.DataFrame:
    return table.to_pandas()


def _lag_history(series: pd.Series) -> pd.Series:
    return series.shift(1)


def _per_instrument_result(
    df: pd.DataFrame,
    func: SeriesTransform,
    source_col: str,
) -> FloatArray:
    series = df[source_col].astype(float)
    result = series.groupby(df["instrument_id"], sort=False).transform(func)
    return cast(FloatArray, result.to_numpy(dtype=float, na_value=np.nan))


def _rolling_mean_lagged(series: pd.Series, *, window: int) -> pd.Series:
    return _lag_history(series).rolling(window, min_periods=window).mean()


def _rolling_std_lagged(series: pd.Series, *, window: int) -> pd.Series:
    return _lag_history(series).rolling(window, min_periods=window).std(ddof=1)


def _ewm_lagged(series: pd.Series, *, span: int) -> pd.Series:
    return _lag_history(series).ewm(span=span, adjust=False, min_periods=1).mean()


def _zscore_lagged(series: pd.Series, *, window: int) -> pd.Series:
    history = _lag_history(series)
    mean = history.rolling(window, min_periods=window).mean()
    std = history.rolling(window, min_periods=window).std(ddof=1)
    return (history - mean) / std.replace(0.0, np.nan)


def _rank_last_window(values: npt.NDArray[np.float64], *, window: int) -> float:
    valid = values[~np.isnan(values)]
    if len(valid) < window:
        return float("nan")
    last_value = valid[-1]
    return float(np.sum(valid <= last_value)) / float(len(valid))


def _time_series_rank_lagged(series: pd.Series, *, window: int) -> pd.Series:
    history = _lag_history(series)
    ranker = partial(_rank_last_window, window=window)
    return history.rolling(window, min_periods=window).apply(ranker, raw=True)


def _cross_sectional_rank(df: pd.DataFrame, source_col: str) -> FloatArray:
    ts_col = "ts_event" if "ts_event" in df.columns else df.columns[0]
    ranked = df.groupby(ts_col)[source_col].rank(pct=True)
    return cast(FloatArray, ranked.to_numpy(dtype=float, na_value=np.nan))


def _lagged_values(series: pd.Series, *, periods: int) -> pd.Series:
    return series.shift(periods)


def _diff_lagged(series: pd.Series, *, periods: int) -> pd.Series:
    return _lag_history(series).diff(periods)


def _return_lagged(series: pd.Series, *, periods: int) -> pd.Series:
    history = _lag_history(series)
    lagged = history.shift(periods)
    return (history - lagged) / lagged.replace(0.0, np.nan)


def _volatility_lagged(
    series: pd.Series,
    *,
    window: int,
    periods_per_year: int,
) -> pd.Series:
    scale = periods_per_year**0.5
    returns = _lag_history(series).pct_change()
    return returns.rolling(window, min_periods=window).std(ddof=1) * scale


class RollingMean(feature_base.Feature):
    """Rolling arithmetic mean of a column within each instrument."""

    def __init__(self, window: int = 20, source_col: str = "price") -> None:
        self._window = window
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"rolling_mean_{self._source_col}_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window, "source_col": self._source_col}

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
        transform = partial(_rolling_mean_lagged, window=self._window)
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class RollingStd(feature_base.Feature):
    """Rolling standard deviation (ddof=1) of a column within each instrument."""

    def __init__(self, window: int = 20, source_col: str = "price") -> None:
        self._window = window
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"rolling_std_{self._source_col}_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window, "source_col": self._source_col}

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
        transform = partial(_rolling_std_lagged, window=self._window)
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class EWM(feature_base.Feature):
    """Exponentially-weighted moving average (span-parametrised)."""

    def __init__(self, span: int = 10, source_col: str = "price") -> None:
        self._span = span
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"ewm_{self._source_col}_{self._span}"

    @property
    def params(self) -> dict[str, Any]:
        return {"span": self._span, "source_col": self._source_col}

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
        transform = partial(_ewm_lagged, span=self._span)
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class ZScore(feature_base.Feature):
    """Lagged rolling z-score per instrument."""

    def __init__(self, window: int = 50, source_col: str = "price") -> None:
        self._window = window
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"zscore_{self._source_col}_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window, "source_col": self._source_col}

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
        transform = partial(_zscore_lagged, window=self._window)
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class Rank(feature_base.Feature):
    """Rank normalised to [0, 1].

    ``method="time_series"`` ranks within per-instrument rolling history.
    ``method="cross_sectional"`` ranks across instruments at the same timestamp.
    """

    def __init__(
        self,
        window: int = 50,
        source_col: str = "price",
        method: str = "time_series",
    ) -> None:
        if method not in ("time_series", "cross_sectional"):
            raise ValueError("method must be 'time_series' or 'cross_sectional'")
        self._window = window
        self._source_col = source_col
        self._method = method

    @property
    def name(self) -> str:
        return f"rank_{self._method}_{self._source_col}_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "window": self._window,
            "source_col": self._source_col,
            "method": self._method,
        }

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

        if self._method == "time_series":
            transform = partial(_time_series_rank_lagged, window=self._window)
            values = _per_instrument_result(df, transform, self._source_col)
        else:
            values = _cross_sectional_rank(df, self._source_col)

        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class Lag(feature_base.Feature):
    """Lag (shift) a column by *periods* within each instrument."""

    def __init__(self, periods: int = 1, source_col: str = "price") -> None:
        self._periods = periods
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"lag_{self._source_col}_{self._periods}"

    @property
    def params(self) -> dict[str, Any]:
        return {"periods": self._periods, "source_col": self._source_col}

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
        transform = partial(_lagged_values, periods=self._periods)
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class Diff(feature_base.Feature):
    """Lagged difference within each instrument."""

    def __init__(self, periods: int = 1, source_col: str = "price") -> None:
        self._periods = periods
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"diff_{self._source_col}_{self._periods}"

    @property
    def params(self) -> dict[str, Any]:
        return {"periods": self._periods, "source_col": self._source_col}

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
        transform = partial(_diff_lagged, periods=self._periods)
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class Return(feature_base.Feature):
    """Lagged percentage return within each instrument."""

    def __init__(self, periods: int = 1, source_col: str = "price") -> None:
        self._periods = periods
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"return_{self._source_col}_{self._periods}"

    @property
    def params(self) -> dict[str, Any]:
        return {"periods": self._periods, "source_col": self._source_col}

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
        transform = partial(_return_lagged, periods=self._periods)
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


class Volatility(feature_base.Feature):
    """Lagged rolling annualised volatility of returns."""

    def __init__(
        self,
        window: int = 20,
        periods_per_year: int = 252,
        source_col: str = "price",
    ) -> None:
        self._window = window
        self._periods_per_year = periods_per_year
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"volatility_{self._source_col}_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "window": self._window,
            "periods_per_year": self._periods_per_year,
            "source_col": self._source_col,
        }

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
        transform = partial(
            _volatility_lagged,
            window=self._window,
            periods_per_year=self._periods_per_year,
        )
        values = _per_instrument_result(df, transform, self._source_col)
        return feature_base.FeatureResult(name=self.name, values=values, params=self.params)


__all__ = [
    "EWM",
    "Diff",
    "Lag",
    "Rank",
    "Return",
    "RollingMean",
    "RollingStd",
    "Volatility",
    "ZScore",
]
