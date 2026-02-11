"""
lab.eval.plots
~~~~~~~~~~~~~~
Standard diagnostic plots for back-test results.

All functions return ``matplotlib.figure.Figure`` objects so callers can
``fig.savefig(...)`` or display inline in notebooks.

Week-1: cumulative returns + drawdown chart.  More plots in later weeks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from matplotlib.figure import Figure


def cumulative_returns(
    returns: pd.Series,
    *,
    title: str = "Cumulative Returns",
    benchmark: pd.Series | None = None,
) -> Figure:
    """Plot cumulative return curve (and optional benchmark).

    Parameters
    ----------
    returns : pd.Series
        Daily simple returns.
    title : str
        Chart title.
    benchmark : pd.Series | None
        Optional benchmark return series for comparison.

    Returns
    -------
    Figure
    """
    fig, ax = plt.subplots(figsize=(12, 5))
    cum = (1 + returns).cumprod()
    ax.plot(cum.index, cum.values, label="Strategy", linewidth=1.2)

    if benchmark is not None:
        cum_bm = (1 + benchmark).cumprod()
        ax.plot(cum_bm.index, cum_bm.values, label="Benchmark", linewidth=1.0, alpha=0.7)

    ax.set_title(title)
    ax.set_ylabel("Cumulative Return")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def drawdown(
    returns: pd.Series,
    *,
    title: str = "Drawdown",
) -> Figure:
    """Plot the drawdown curve.

    Parameters
    ----------
    returns : pd.Series
        Daily simple returns.
    title : str
        Chart title.

    Returns
    -------
    Figure
    """
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak

    fig, ax = plt.subplots(figsize=(12, 3))
    ax.fill_between(dd.index, dd.values, 0, color="red", alpha=0.35, label="Drawdown")
    ax.set_title(title)
    ax.set_ylabel("Drawdown")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def rolling_sharpe(
    returns: pd.Series,
    window: int = 63,
    *,
    title: str = "Rolling Sharpe (63-day)",
) -> Figure:
    """Plot rolling annualised Sharpe ratio.

    Parameters
    ----------
    returns : pd.Series
        Daily simple returns.
    window : int
        Rolling window in trading days (default 63 ≈ 3 months).
    title : str
        Chart title.

    Returns
    -------
    Figure
    """
    rolling_mean = returns.rolling(window).mean() * 252
    rolling_std = returns.rolling(window).std() * np.sqrt(252)
    rolling_sr = rolling_mean / rolling_std

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(rolling_sr.index, rolling_sr.values, linewidth=1.0)
    ax.axhline(0, color="grey", linewidth=0.5)
    ax.set_title(title)
    ax.set_ylabel("Sharpe Ratio")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def turnover_plot(
    turnover: pd.Series,
    *,
    title: str = "Portfolio Turnover Over Time",
) -> Figure:
    """Plot one-way turnover fraction over time.

    Non-rebalance days (turnover == 0) are included so the x-axis shows the
    full date range.  Rebalance spikes are clearly visible.

    Parameters
    ----------
    turnover : pd.Series
        Daily one-way turnover (0 on non-rebalance days).
    title : str
        Chart title.

    Returns
    -------
    Figure
    """
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.bar(turnover.index, turnover.values, width=1.0, color="steelblue", alpha=0.7)
    ax.set_title(title)
    ax.set_ylabel("Turnover (one-way)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def gross_net_exposure(
    gross: pd.Series,
    net: pd.Series,
    *,
    title: str = "Gross / Net Exposure",
) -> Figure:
    """Plot gross and net exposure time series."""
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(gross.index, gross.values, label="Gross", linewidth=1.2)
    ax.plot(net.index, net.values, label="Net", linewidth=1.0)
    ax.axhline(0, color="grey", linewidth=0.7)
    ax.set_title(title)
    ax.set_ylabel("Exposure")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def bucket_exposure_plot(
    bucket_exposure: pd.DataFrame,
    *,
    title: str = "Bucket Exposure",
) -> Figure:
    """Plot bucket-level net exposures over time."""
    fig, ax = plt.subplots(figsize=(12, 4))
    for col in bucket_exposure.columns:
        ax.plot(bucket_exposure.index, bucket_exposure[col], label=col, linewidth=1.0)
    ax.axhline(0, color="grey", linewidth=0.7)
    ax.set_title(title)
    ax.set_ylabel("Net Exposure")
    ax.legend(loc="upper left", ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def risk_contribution_plot(
    bucket_risk: pd.DataFrame,
    *,
    title: str = "Risk Contribution by Bucket",
) -> Figure:
    """Plot rolling risk contributions by bucket."""
    fig, ax = plt.subplots(figsize=(12, 4))
    for col in bucket_risk.columns:
        ax.plot(bucket_risk.index, bucket_risk[col], label=col, linewidth=1.0)
    ax.axhline(0, color="grey", linewidth=0.7)
    ax.set_title(title)
    ax.set_ylabel("Risk Contribution")
    ax.legend(loc="upper left", ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def capacity_participation_plot(
    participation: pd.DataFrame,
    *,
    limit: float | None = None,
    title: str = "Capacity Participation",
) -> Figure:
    """Plot capacity participation diagnostics over time.

    The chart shows daily max and p95 participation across assets.
    """
    p = participation.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    if p.empty:
        max_part = pd.Series(dtype=float)
        p95_part = pd.Series(dtype=float)
    else:
        max_part = p.max(axis=1)
        p95_part = p.quantile(0.95, axis=1)

    fig, ax = plt.subplots(figsize=(12, 4))
    if len(max_part) > 0:
        ax.plot(max_part.index, max_part.values, label="Max Participation", linewidth=1.2)
        ax.plot(
            p95_part.index, p95_part.values, label="P95 Participation", linewidth=1.0, alpha=0.8
        )
    if limit is not None:
        ax.axhline(float(limit), color="red", linestyle="--", linewidth=1.0, label="Capacity Limit")
    ax.set_title(title)
    ax.set_ylabel("Participation (fraction of ADV)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig
