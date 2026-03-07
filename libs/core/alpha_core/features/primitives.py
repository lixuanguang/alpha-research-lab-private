"""Time-series feature primitives for the feature registry.

All primitives:
- Operate per-instrument (group by ``instrument_id``).
- Propagate NaN for warm-up rows where insufficient history exists.
- Preserve input row order — output index matches input index.
- Accept a ``source_col`` parameter (default ``"price"``) to support
  computing on any numeric column.
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


def _per_instrument_result(
    df: pd.DataFrame,
    func: "Any",  # (group: pd.Series) -> pd.Series
    source_col: str,
    feature_name: str,
) -> np.ndarray:
    """Apply *func* per instrument group, preserving original row order."""
    series = df[source_col].astype(float)
    result = (
        series.groupby(df["instrument_id"], sort=False)
        .transform(func)
    )
    return result.to_numpy(dtype=float, na_value=np.nan)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class RollingMean(Feature):
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

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        w = self._window
        values = _per_instrument_result(
            df,
            lambda s: s.rolling(w, min_periods=w).mean(),
            self._source_col,
            self.name,
        )
        return FeatureResult(name=self.name, values=values, params=self.params)


class RollingStd(Feature):
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

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        w = self._window
        values = _per_instrument_result(
            df,
            lambda s: s.rolling(w, min_periods=w).std(ddof=1),
            self._source_col,
            self.name,
        )
        return FeatureResult(name=self.name, values=values, params=self.params)


class EWM(Feature):
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

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        span = self._span
        values = _per_instrument_result(
            df,
            lambda s: s.ewm(span=span, adjust=False).mean(),
            self._source_col,
            self.name,
        )
        return FeatureResult(name=self.name, values=values, params=self.params)


class ZScore(Feature):
    """Rolling z-score: (x - rolling_mean) / rolling_std per instrument."""

    def __init__(self, window: int = 50, source_col: str = "price") -> None:
        self._window = window
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"zscore_{self._source_col}_{self._window}"

    @property
    def params(self) -> dict[str, Any]:
        return {"window": self._window, "source_col": self._source_col}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        w = self._window
        col = df[self._source_col].astype(float)

        def _zscore(s: pd.Series) -> pd.Series:
            mu = s.rolling(w, min_periods=w).mean()
            sigma = s.rolling(w, min_periods=w).std(ddof=1)
            return (s - mu) / sigma.replace(0.0, np.nan)

        values = _per_instrument_result(df, _zscore, self._source_col, self.name)
        return FeatureResult(name=self.name, values=values, params=self.params)


class Rank(Feature):
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

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        col = df[self._source_col].astype(float)

        if self._method == "time_series":
            w = self._window

            def _ts_rank(s: pd.Series) -> pd.Series:
                def _rank_last(arr: Any) -> float:
                    valid = arr[~np.isnan(arr)]
                    if len(valid) < w:
                        return np.nan
                    return float(np.sum(valid <= arr[-1])) / len(valid)

                return s.rolling(w, min_periods=w).apply(_rank_last, raw=True)

            values = _per_instrument_result(df, _ts_rank, self._source_col, self.name)

        else:  # cross_sectional
            ts_col = "ts_event" if "ts_event" in df.columns else df.columns[0]
            ranked = df.groupby(ts_col)[self._source_col].rank(pct=True)
            values = ranked.to_numpy(dtype=float, na_value=np.nan)

        return FeatureResult(name=self.name, values=values, params=self.params)


class Lag(Feature):
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

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        p = self._periods
        values = _per_instrument_result(
            df, lambda s: s.shift(p), self._source_col, self.name
        )
        return FeatureResult(name=self.name, values=values, params=self.params)


class Diff(Feature):
    """x[t] - x[t - periods] within each instrument."""

    def __init__(self, periods: int = 1, source_col: str = "price") -> None:
        self._periods = periods
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"diff_{self._source_col}_{self._periods}"

    @property
    def params(self) -> dict[str, Any]:
        return {"periods": self._periods, "source_col": self._source_col}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        p = self._periods
        values = _per_instrument_result(
            df, lambda s: s.diff(p), self._source_col, self.name
        )
        return FeatureResult(name=self.name, values=values, params=self.params)


class Return(Feature):
    """Percentage return: (x[t] - x[t-periods]) / x[t-periods] per instrument."""

    def __init__(self, periods: int = 1, source_col: str = "price") -> None:
        self._periods = periods
        self._source_col = source_col

    @property
    def name(self) -> str:
        return f"return_{self._source_col}_{self._periods}"

    @property
    def params(self) -> dict[str, Any]:
        return {"periods": self._periods, "source_col": self._source_col}

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        p = self._periods

        def _pct(s: pd.Series) -> pd.Series:
            lagged = s.shift(p)
            return (s - lagged) / lagged.replace(0.0, np.nan)

        values = _per_instrument_result(df, _pct, self._source_col, self.name)
        return FeatureResult(name=self.name, values=values, params=self.params)


class Volatility(Feature):
    """Rolling annualised volatility of returns (rolling std of 1-period returns)."""

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

    def compute(self, data: pa.Table, *, instrument_id: str | None = None) -> FeatureResult:
        if data.num_rows == 0:
            return self._empty_result(0)
        df = _to_df(data)
        w = self._window
        scale = self._periods_per_year ** 0.5

        def _vol(s: pd.Series) -> pd.Series:
            rets = s.pct_change()
            return rets.rolling(w, min_periods=w).std(ddof=1) * scale

        values = _per_instrument_result(df, _vol, self._source_col, self.name)
        return FeatureResult(name=self.name, values=values, params=self.params)


__all__ = [
    "RollingMean",
    "RollingStd",
    "EWM",
    "ZScore",
    "Rank",
    "Lag",
    "Diff",
    "Return",
    "Volatility",
]
