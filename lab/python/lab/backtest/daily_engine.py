"""
lab.backtest.daily_engine
~~~~~~~~~~~~~~~~~~~~~~~~~
Walk-forward daily backtesting engine.

Design
------
- **Walk-forward**: for each rebalance date, the strategy sees only data up to
  that point (no look-ahead).
- **Daily PnL accounting**: positions × returns, minus transaction costs.
- Supports expanding and rolling train windows (configured in ``BacktestConfig``).
- Returns a ``BacktestResult`` dataclass for downstream eval.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pandas as pd

from lab.core.logging import get_logger
from lab.costs.daily import estimate_turnover

if TYPE_CHECKING:
    from lab.core.config import ExperimentConfig

log = get_logger("backtest.engine")

_FREQ_MAP = {
    "daily": "B",
    "weekly": "W-FRI",
    "monthly": "BMS",  # business month start
}


@dataclasses.dataclass
class BacktestResult:
    """Container for a single back-test run."""

    # Daily portfolio returns (net of costs)
    returns: pd.Series  # index=DatetimeIndex, dtype=float
    # Daily gross returns (before costs)
    gross_returns: pd.Series
    # Position weights at each rebalance date
    weights: pd.DataFrame  # index=DatetimeIndex, columns=tickers
    # Turnover at each rebalance
    turnover: pd.Series
    # Summary metrics dict (populated after run)
    summary_metrics: dict | None = None
    # Metadata
    config: ExperimentConfig | None = None

    # Week-2 diagnostics
    gross_exposure: pd.Series = dataclasses.field(
        default_factory=lambda: pd.Series(dtype=float, name="gross_exposure")
    )
    net_exposure: pd.Series = dataclasses.field(
        default_factory=lambda: pd.Series(dtype=float, name="net_exposure")
    )
    turnover_by_asset: pd.DataFrame = dataclasses.field(default_factory=pd.DataFrame)
    costs: pd.Series = dataclasses.field(default_factory=lambda: pd.Series(dtype=float, name="costs"))
    costs_by_asset: pd.DataFrame = dataclasses.field(default_factory=pd.DataFrame)


class _ConfigLike:
    """Minimal protocol adapter for internal typing/runtime checks."""

    exp: str
    rebalance: str
    costs: float | dict



def _rebalance_dates(
    dates: pd.DatetimeIndex,
    freq: str,
    min_warmup: int = 252,
) -> pd.DatetimeIndex:
    """Return the subset of *dates* that are rebalance points.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Full trading-day calendar.
    freq : str
        ``'daily'``, ``'weekly'``, ``'monthly'`` or any pandas offset alias.
    min_warmup : int
        Minimum number of trading days before the first rebalance (for signal
        lookback).
    """
    if len(dates) == 0:
        return dates

    offset = _FREQ_MAP.get(freq, freq)
    warmup_idx = 0 if len(dates) <= min_warmup else min_warmup
    anchor = dates[warmup_idx]

    valid = dates[dates >= anchor]

    # Generate theoretical schedule and snap each point to the next observed
    # trading day. This avoids silently missing rebalances when target dates
    # fall on exchange holidays (e.g., Friday holiday for W-FRI schedules).
    sched = pd.date_range(anchor, dates[-1], freq=offset)
    if len(valid) == 0:
        return pd.DatetimeIndex([])
    if len(sched) == 0:
        rebal = valid[::21]
        return pd.DatetimeIndex(rebal)

    pos = valid.searchsorted(sched, side="left")
    pos = pos[(pos >= 0) & (pos < len(valid))]
    rebal = pd.DatetimeIndex(valid[pos]).unique()

    if len(rebal) < 2:
        rebal = valid[::21]
    return pd.DatetimeIndex(rebal)


def _resolve_asset_cost_bps(config: _ConfigLike, columns: pd.Index) -> pd.Series:
    """Return per-asset one-way costs (bps) for the current run."""
    default_bps = float(getattr(config, "costs_bps", 0.0))
    costs = getattr(config, "costs", default_bps)

    if isinstance(costs, dict):
        if "per_asset_bps" in costs:
            m = costs.get("per_asset_bps", {})
            s = pd.Series({k: float(v) for k, v in m.items()}, dtype=float)
            return s.reindex(columns, fill_value=float(costs.get("bps", default_bps)))
        return pd.Series(float(costs.get("bps", default_bps)), index=columns, dtype=float)

    return pd.Series(float(default_bps if default_bps != 0 else costs), index=columns, dtype=float)


def run_daily_backtest(
    config: ExperimentConfig,
    prices: pd.DataFrame,
    signal_fn: callable,
) -> BacktestResult:
    """Execute a walk-forward daily backtest.

    No-leakage guarantee
    --------------------
    At each date ``dt``, the engine first books that day's return using the
    *previous* weights. If ``dt`` is a rebalance date, new weights are then
    computed from ``prices.loc[:dt]`` and become active from the next trading
    day onward. This prevents same-day look-ahead leakage.

    Parameters
    ----------
    config : ExperimentConfig
        Full experiment configuration.
    prices : pd.DataFrame
        Adjusted close prices (DatetimeIndex × tickers).
    signal_fn : callable
        ``(config, prices_up_to_date) -> target_weights_series`` at each rebalance.

    Returns
    -------
    BacktestResult
        Daily returns (net & gross), weights, turnover, costs, and exposures.
    """
    log.info("Starting daily backtest: %s", getattr(config, "exp", "unknown"))

    if prices.empty:
        log.warning("Empty prices — returning empty BacktestResult.")
        return BacktestResult(
            returns=pd.Series(dtype=float, name="net_return"),
            gross_returns=pd.Series(dtype=float, name="gross_return"),
            weights=pd.DataFrame(),
            turnover=pd.Series(dtype=float, name="turnover"),
            config=config,
        )

    daily_ret = prices.pct_change().fillna(0.0)
    dates = prices.index
    rebal_dates = _rebalance_dates(dates, getattr(config, "rebalance", "monthly"))
    log.info("  %d rebalance dates over %d trading days", len(rebal_dates), len(dates))
    rebal_set = set(rebal_dates)

    # Containers
    weight_records: list[tuple[pd.Timestamp, pd.Series]] = []
    current_weights = pd.Series(0.0, index=prices.columns, dtype=float)
    turnover_records: dict[pd.Timestamp, float] = {}

    port_gross = pd.Series(0.0, index=dates, dtype=float, name="gross_return")
    gross_exposure = pd.Series(0.0, index=dates, dtype=float, name="gross_exposure")
    net_exposure = pd.Series(0.0, index=dates, dtype=float, name="net_exposure")
    turnover_by_asset = pd.DataFrame(0.0, index=dates, columns=prices.columns, dtype=float)

    for dt in dates:
        # Daily PnL uses weights known before today's return.
        gross_exposure.loc[dt] = current_weights.abs().sum()
        net_exposure.loc[dt] = current_weights.sum()

        day_ret = (current_weights * daily_ret.loc[dt]).sum()
        port_gross.loc[dt] = day_ret

        if dt in rebal_set:
            # New weights are computed after observing today's close and only
            # affect subsequent returns.
            new_weights = signal_fn(config, prices.loc[:dt])
            if not isinstance(new_weights, pd.Series):
                new_weights = pd.Series(new_weights, index=prices.columns, dtype=float)
            new_weights = new_weights.reindex(prices.columns, fill_value=0.0).astype(float)

            per_asset_turnover = (new_weights - current_weights).abs() / 2.0
            turnover_by_asset.loc[dt] = per_asset_turnover

            to = estimate_turnover(current_weights, new_weights)
            turnover_records[dt] = to
            current_weights = new_weights
            weight_records.append((dt, new_weights.copy()))

    # ── Turnover and costs ───────────────────────────────────────────────
    turnover = pd.Series(turnover_records, name="turnover").reindex(dates, fill_value=0.0)

    asset_cost_bps = _resolve_asset_cost_bps(config, prices.columns)
    costs_by_asset = turnover_by_asset.mul(asset_cost_bps, axis=1) / 1e4
    costs = costs_by_asset.sum(axis=1)
    costs.name = "costs"

    net_returns = port_gross - costs
    net_returns.name = "net_return"

    # ── Weight history ───────────────────────────────────────────────────
    if weight_records:
        weight_df = pd.DataFrame({dt: w for dt, w in weight_records}).T
        weight_df.index.name = "date"
    else:
        weight_df = pd.DataFrame(columns=prices.columns)

    # ── Summary metrics ──────────────────────────────────────────────────
    from lab.eval.metrics import summary as _summary_metrics

    metrics = _summary_metrics(net_returns, turnover=turnover, gross_returns=port_gross)

    log.info(
        "  Backtest done. %d days, mean net ret %.4f bps/day",
        len(net_returns),
        net_returns.mean() * 1e4,
    )

    return BacktestResult(
        returns=net_returns,
        gross_returns=port_gross,
        weights=weight_df,
        turnover=turnover,
        summary_metrics=metrics,
        config=config,
        gross_exposure=gross_exposure,
        net_exposure=net_exposure,
        turnover_by_asset=turnover_by_asset,
        costs=costs,
        costs_by_asset=costs_by_asset,
    )
