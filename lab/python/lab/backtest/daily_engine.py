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
from lab.costs.daily import apply_linear_costs, estimate_turnover

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
        ``'daily'``, ``'weekly'``, or ``'monthly'``.
    min_warmup : int
        Minimum number of trading days before the first rebalance (for signal
        lookback).
    """
    if len(dates) == 0:
        return dates

    offset = _FREQ_MAP.get(freq, "BMS")
    # If history is shorter than warmup, start scheduling from the first date.
    warmup_idx = 0 if len(dates) <= min_warmup else min_warmup
    anchor = dates[warmup_idx]

    # Generate theoretical rebalance schedule, then snap to actual trading days
    sched = pd.date_range(anchor, dates[-1], freq=offset)
    valid = dates[dates >= anchor]
    weekend_gap = valid.to_series().diff().dt.days.gt(5).fillna(False).to_numpy()
    rebal = valid[valid.isin(sched) | weekend_gap]
    # Fallback: if snapping left us with nothing, just use monthly iloc
    if len(rebal) < 2:
        rebal = valid[::21]
    return rebal


def run_daily_backtest(
    config: ExperimentConfig,
    prices: pd.DataFrame,
    signal_fn: callable,
) -> BacktestResult:
    """Execute a walk-forward daily backtest.

    No-leakage guarantee
    --------------------
    At each date ``dt``, the engine first books that day's return using the
    *previous* weights.  If ``dt`` is a rebalance date, new weights are then
    computed from ``prices.loc[:dt]`` and become active from the next trading
    day onward.  This prevents same-day look-ahead leakage.

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
        Daily returns (net & gross), weights, and turnover.
    """
    log.info("Starting daily backtest: %s", config.exp)

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
    rebal_dates = _rebalance_dates(dates, config.rebalance)
    log.info("  %d rebalance dates over %d trading days", len(rebal_dates), len(dates))
    rebal_set = set(rebal_dates)

    # Containers
    weight_records: list[tuple[pd.Timestamp, pd.Series]] = []
    current_weights = pd.Series(0.0, index=prices.columns)
    turnover_records: dict[pd.Timestamp, float] = {}

    port_gross = pd.Series(0.0, index=dates, dtype=float, name="gross_return")

    for dt in dates:
        # Daily PnL uses weights known before today's return.
        day_ret = (current_weights * daily_ret.loc[dt]).sum()
        port_gross.loc[dt] = day_ret

        if dt in rebal_set:
            # New weights are computed after observing today's close and only
            # affect subsequent returns.
            new_weights = signal_fn(config, prices.loc[:dt])
            new_weights = new_weights.reindex(prices.columns, fill_value=0.0)

            to = estimate_turnover(current_weights, new_weights)
            turnover_records[dt] = to
            current_weights = new_weights
            weight_records.append((dt, new_weights.copy()))

    # ── Assemble turnover series ─────────────────────────────────────────
    turnover = pd.Series(turnover_records, name="turnover").reindex(dates, fill_value=0.0)

    # ── Apply costs ──────────────────────────────────────────────────────
    # Uses the vectorised helper (consistent with apply_costs per-rebalance)
    net_returns = apply_linear_costs(port_gross, turnover, config.costs_bps)
    net_returns.name = "net_return"

    # ── Weight history ───────────────────────────────────────────────────
    if weight_records:
        weight_df = pd.DataFrame(
            {dt: w for dt, w in weight_records},
        ).T
        weight_df.index.name = "date"
    else:
        weight_df = pd.DataFrame()

    # ── Summary metrics ──────────────────────────────────────────────────
    from lab.eval.metrics import summary as _summary_metrics

    metrics = _summary_metrics(net_returns)

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
    )
