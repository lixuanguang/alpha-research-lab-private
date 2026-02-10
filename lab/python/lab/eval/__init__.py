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
from lab.eval.plots import (
    bucket_exposure_plot,
    cumulative_returns,
    drawdown,
    gross_net_exposure,
    risk_contribution_plot,
    rolling_sharpe,
    turnover_plot,
)
from lab.eval.reports import (
    macro_allocator_markdown_report,
    markdown_report,
    metrics_table,
    save_macro_allocator_report,
    save_report,
)
from lab.eval.risk_attribution import compute_risk_contributions

__all__ = [
    "annualised_vol",
    "average_turnover",
    "bucket_exposure_plot",
    "cagr",
    "calmar_ratio",
    "compute_risk_contributions",
    "cumulative_return",
    "cumulative_returns",
    "drawdown",
    "gross_net_exposure",
    "hit_rate",
    "macro_allocator_markdown_report",
    "markdown_report",
    "max_drawdown",
    "metrics_table",
    "profit_factor",
    "risk_contribution_plot",
    "rolling_sharpe",
    "save_macro_allocator_report",
    "save_report",
    "sharpe_ratio",
    "sortino_ratio",
    "summary",
    "tail_ratio",
    "total_costs_paid",
    "turnover_plot",
]
