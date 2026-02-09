"""lab.eval — performance metrics, reports, and diagnostic plots."""

from lab.eval.metrics import (
    annualised_vol,
    average_turnover,
    cagr,
    calmar_ratio,
    cumulative_return,
    hit_rate,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    summary,
    tail_ratio,
    total_costs_paid,
)
from lab.eval.plots import cumulative_returns, drawdown, rolling_sharpe, turnover_plot
from lab.eval.reports import markdown_report, metrics_table, save_report

__all__ = [
    "annualised_vol",
    "average_turnover",
    "cagr",
    "calmar_ratio",
    "cumulative_return",
    "cumulative_returns",
    "drawdown",
    "hit_rate",
    "markdown_report",
    "max_drawdown",
    "metrics_table",
    "profit_factor",
    "rolling_sharpe",
    "save_report",
    "sharpe_ratio",
    "sortino_ratio",
    "summary",
    "tail_ratio",
    "total_costs_paid",
    "turnover_plot",
]
