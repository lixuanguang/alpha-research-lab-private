"""Data QA checks for price and volume artifacts."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd


@dataclasses.dataclass(frozen=True)
class QAThresholds:
    max_missing_pct: float = 5.0
    jump_multiple: float = 50.0
    max_zero_volume_streak: int = 5
    max_missing_trading_days: int = 2


@dataclasses.dataclass
class QAResult:
    failures: list[str]
    missingness: pd.DataFrame
    jumps: pd.DataFrame
    zero_prices: pd.DataFrame
    volume_zero_streaks: pd.DataFrame
    missing_index_dates: pd.DataFrame

    @property
    def ok(self) -> bool:
        return len(self.failures) == 0

    def raise_for_failures(self) -> None:
        if self.ok:
            return
        lines = "\n".join(f"- {msg}" for msg in self.failures)
        raise ValueError(f"Data QA failed:\n{lines}")


def _coerce_panel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.reindex(columns=sorted(out.columns))
    return out


def _extract_volume_panel(ohlcv: pd.DataFrame | None) -> pd.DataFrame:
    if ohlcv is None or ohlcv.empty:
        return pd.DataFrame()
    if isinstance(ohlcv.columns, pd.MultiIndex):
        level = "field" if "field" in ohlcv.columns.names else -1
        if "volume" not in set(map(str, ohlcv.columns.get_level_values(level))):
            return pd.DataFrame()
        vol = ohlcv.xs("volume", axis=1, level=level, drop_level=True)
        vol.index = pd.DatetimeIndex(vol.index)
        return vol.sort_index()
    candidates = [c for c in ohlcv.columns if str(c).strip().lower() == "volume"]
    if not candidates:
        return pd.DataFrame()
    return pd.DataFrame({"volume": pd.to_numeric(ohlcv[candidates[0]], errors="coerce")}, index=ohlcv.index)


def _max_zero_streak(s: pd.Series) -> int:
    zeros = s.fillna(0.0).eq(0.0)
    if not zeros.any():
        return 0
    grp = zeros.ne(zeros.shift(fill_value=False)).cumsum()
    streak = zeros.groupby(grp).sum()
    return int(streak.max())


def run_price_data_qa(
    close: pd.DataFrame,
    *,
    ohlcv: pd.DataFrame | None = None,
    thresholds: QAThresholds | None = None,
) -> QAResult:
    cfg = thresholds if thresholds is not None else QAThresholds()
    px = _coerce_panel(close)
    if px.empty:
        raise ValueError("Price QA requires a non-empty close panel.")

    failures: list[str] = []

    missing_pct = (px.isna().mean(axis=0) * 100.0).astype(float)
    missingness = (
        missing_pct.rename("missing_pct")
        .to_frame()
        .reset_index()
        .rename(columns={"index": "ticker"})
        .sort_values("missing_pct", ascending=False)
        .reset_index(drop=True)
    )
    bad_missing = missingness[missingness["missing_pct"] > float(cfg.max_missing_pct)]
    if not bad_missing.empty:
        failures.append(
            f"Missingness exceeds {cfg.max_missing_pct:.2f}% for tickers: "
            + ", ".join(bad_missing["ticker"].astype(str).tolist())
        )

    ratio = px.div(px.shift(1))
    jump_mask = (ratio >= float(cfg.jump_multiple)) | (
        ratio <= (1.0 / float(cfg.jump_multiple))
    )
    jump_rows = jump_mask.stack()
    jump_rows = jump_rows[jump_rows].index
    jumps = pd.DataFrame(columns=["date", "ticker", "prev_price", "price", "ratio"])
    if len(jump_rows) > 0:
        jumps = pd.DataFrame(
            {
                "date": [idx[0] for idx in jump_rows],
                "ticker": [idx[1] for idx in jump_rows],
                "prev_price": [float(px.shift(1).loc[idx[0], idx[1]]) for idx in jump_rows],
                "price": [float(px.loc[idx[0], idx[1]]) for idx in jump_rows],
                "ratio": [float(ratio.loc[idx[0], idx[1]]) for idx in jump_rows],
            }
        )
        failures.append(f"Detected {len(jumps)} suspicious price jumps >= {cfg.jump_multiple}x.")

    zero_mask = px <= 0.0
    zero_rows = zero_mask.stack()
    zero_rows = zero_rows[zero_rows].index
    zero_prices = pd.DataFrame(columns=["date", "ticker", "price"])
    if len(zero_rows) > 0:
        zero_prices = pd.DataFrame(
            {
                "date": [idx[0] for idx in zero_rows],
                "ticker": [idx[1] for idx in zero_rows],
                "price": [float(px.loc[idx[0], idx[1]]) for idx in zero_rows],
            }
        )
        failures.append(f"Detected {len(zero_prices)} non-positive prices.")

    volume = _extract_volume_panel(ohlcv).reindex(index=px.index, columns=px.columns)
    streak_rows: list[dict[str, object]] = []
    if not volume.empty:
        for ticker in volume.columns:
            streak_rows.append(
                {
                    "ticker": str(ticker),
                    "max_zero_streak": _max_zero_streak(pd.to_numeric(volume[ticker], errors="coerce")),
                }
            )
    volume_zero_streaks = pd.DataFrame(streak_rows)
    if not volume_zero_streaks.empty:
        bad_streaks = volume_zero_streaks[
            volume_zero_streaks["max_zero_streak"] > int(cfg.max_zero_volume_streak)
        ]
        if not bad_streaks.empty:
            failures.append(
                f"Zero-volume streak exceeds {cfg.max_zero_volume_streak} days for tickers: "
                + ", ".join(bad_streaks["ticker"].astype(str).tolist())
            )

    expected_days = pd.bdate_range(px.index.min(), px.index.max())
    missing_days = expected_days.difference(px.index)
    missing_index_dates = pd.DataFrame({"date": missing_days})
    if len(missing_days) > int(cfg.max_missing_trading_days):
        failures.append(
            "Index continuity check failed: "
            f"{len(missing_days)} missing business days (max allowed {cfg.max_missing_trading_days})."
        )

    return QAResult(
        failures=failures,
        missingness=missingness,
        jumps=jumps.sort_values(["date", "ticker"]).reset_index(drop=True),
        zero_prices=zero_prices.sort_values(["date", "ticker"]).reset_index(drop=True),
        volume_zero_streaks=volume_zero_streaks.sort_values("max_zero_streak", ascending=False)
        if not volume_zero_streaks.empty
        else volume_zero_streaks,
        missing_index_dates=missing_index_dates,
    )


def write_qa_tables(result: QAResult, *, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "missingness": out_dir / "missingness.csv",
        "jumps": out_dir / "jumps.csv",
        "zero_prices": out_dir / "zero_prices.csv",
        "volume_zero_streaks": out_dir / "volume_zero_streaks.csv",
        "missing_index_dates": out_dir / "missing_index_dates.csv",
    }
    result.missingness.to_csv(tables["missingness"], index=False)
    result.jumps.to_csv(tables["jumps"], index=False)
    result.zero_prices.to_csv(tables["zero_prices"], index=False)
    result.volume_zero_streaks.to_csv(tables["volume_zero_streaks"], index=False)
    result.missing_index_dates.to_csv(tables["missing_index_dates"], index=False)
    return tables
