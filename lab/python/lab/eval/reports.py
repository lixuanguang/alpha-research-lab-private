"""
lab.eval.reports
~~~~~~~~~~~~~~~~
Generate structured experiment reports (Markdown + HTML).

``markdown_report`` now accepts a pre-built metrics dict (with operational
fields like ``avg_turnover`` and ``total_costs``) and an optional list of
figure filenames (relative to the report directory, e.g. ``figures/cumulative_returns.png``).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from lab.core.logging import get_logger
from lab.eval.metrics import summary

log = get_logger("eval.reports")

# Formatting map used by both metrics_table and markdown_report
_FMT: dict[str, str] = {
    "cumulative_return": "{:.2%}",
    "cagr": "{:.2%}",
    "ann_vol": "{:.2%}",
    "sharpe": "{:.2f}",
    "sortino": "{:.2f}",
    "max_dd": "{:.2%}",
    "calmar": "{:.2f}",
    "hit_rate": "{:.2%}",
    "profit_factor": "{:.2f}",
    "tail_ratio": "{:.2f}",
    "avg_turnover": "{:.4f}",
    "total_costs": "{:.6f}",
}


def metrics_table(
    returns: pd.Series,
    rf: float = 0.0,
    *,
    turnover: pd.Series | None = None,
    gross_returns: pd.Series | None = None,
) -> pd.DataFrame:
    """Compute metrics and return as a single-row DataFrame.

    Useful for stacking results from multiple experiments.
    """
    s = summary(returns, rf=rf, turnover=turnover, gross_returns=gross_returns)
    return pd.DataFrame([s])


def markdown_report(
    name: str,
    returns: pd.Series | None = None,
    rf: float = 0.0,
    *,
    metrics: dict[str, float] | None = None,
    turnover: pd.Series | None = None,
    gross_returns: pd.Series | None = None,
    figure_filenames: Sequence[str] = (),
    meta: dict[str, Any] | None = None,
) -> str:
    """Generate a Markdown-formatted report string.

    Either ``returns`` or a pre-built ``metrics`` dict must be provided.

    Parameters
    ----------
    name : str
        Experiment name (used as heading).
    returns : pd.Series | None
        Daily simple returns (used to build metrics if *metrics* not given).
    rf : float
        Annualised risk-free rate.
    metrics : dict | None
        Pre-computed metrics dict — skips recomputation.
    turnover, gross_returns : pd.Series | None
        Optional operational data forwarded to ``summary()``.
    figure_filenames : Sequence[str]
        Relative paths for figures to embed, e.g. ``["figures/cumulative_returns.png"]``.
    meta : dict | None
        Run provenance metadata (config_hash, git_commit, …).

    Returns
    -------
    str
        Markdown text.
    """
    if metrics is None:
        if returns is None:
            raise ValueError("Either 'returns' or 'metrics' must be provided")
        metrics = summary(returns, rf=rf, turnover=turnover, gross_returns=gross_returns)

    lines: list[str] = [
        f"# {name}",
        "",
    ]

    # Provenance section
    if meta:
        lines.append("## Provenance\n")
        lines.append(f"- **Config hash:** `{meta.get('config_hash', 'n/a')}`")
        lines.append(f"- **Git commit:** `{meta.get('git_commit', 'n/a')}`")
        lines.append(f"- **Start time:** {meta.get('start_time', 'n/a')}")
        lines.append(f"- **Platform:** {meta.get('platform', 'n/a')}")
        lines.append("")

    lines += [
        "## Performance Metrics\n",
        "| Metric | Value |",
        "|--------|------:|",
    ]
    for k, v in metrics.items():
        lines.append(f"| {k} | {_FMT.get(k, '{:.4f}').format(v)} |")
    lines.append("")

    # Figures section
    for fname in figure_filenames:
        label = Path(fname).stem.replace("_", " ").title()
        lines.append(f"## {label}\n")
        lines.append(f"![{label}]({fname})\n")

    return "\n".join(lines)


def save_report(
    name: str,
    returns: pd.Series | None = None,
    output_dir: str | Path | None = None,
    rf: float = 0.0,
    *,
    metrics: dict[str, float] | None = None,
    turnover: pd.Series | None = None,
    gross_returns: pd.Series | None = None,
    figure_filenames: Sequence[str] = (),
    meta: dict[str, Any] | None = None,
) -> Path:
    """Write a Markdown report to disk.

    Returns the path to the written file.
    """
    if output_dir is None:
        raise ValueError("output_dir is required")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_text = markdown_report(
        name,
        returns=returns,
        rf=rf,
        metrics=metrics,
        turnover=turnover,
        gross_returns=gross_returns,
        figure_filenames=figure_filenames,
        meta=meta,
    )
    path = output_dir / "report.md"
    path.write_text(report_text)
    log.info("Report saved → %s", path)
    return path


def _dict_table_md(
    title: str, data: dict[str, float], fmt: dict[str, str] | None = None
) -> list[str]:
    lines = [f"### {title}", "", "| Metric | Value |", "|---|---:|"]
    for k, v in data.items():
        formatter = (fmt or {}).get(k, "{:.4f}")
        lines.append(f"| {k} | {formatter.format(v)} |")
    lines.append("")
    return lines


def _metrics_matrix_md(title: str, rows: dict[str, dict[str, float]]) -> list[str]:
    if not rows:
        return [f"### {title}", "", "_n/a_", ""]
    metrics = sorted({m for d in rows.values() for m in d})
    lines = [f"### {title}", "", "| Strategy | " + " | ".join(metrics) + " |"]
    lines.append("|---|" + "---:|" * len(metrics))
    for name, vals in rows.items():
        rendered = []
        for metric in metrics:
            v = vals.get(metric, float("nan"))
            if pd.isna(v):
                rendered.append("n/a")
            else:
                rendered.append(_FMT.get(metric, "{:.4f}").format(v))
        lines.append("| " + name + " | " + " | ".join(rendered) + " |")
    lines.append("")
    return lines


def macro_allocator_markdown_report(
    name: str,
    *,
    metrics: dict[str, float],
    baselines: dict[str, dict[str, float]],
    cost_stress: dict[str, dict[str, float]],
    regime_split: dict[str, dict[str, float]],
    exposure_summary: dict[str, float],
    risk_summary: dict[str, float],
    figure_filenames: Sequence[str] = (),
    meta: dict[str, Any] | None = None,
) -> str:
    """Build a Week-2 macro allocator report with diagnostics sections."""
    lines: list[str] = [f"# {name}", ""]

    if meta:
        lines.append("## Provenance\n")
        lines.append(f"- **Run ID:** `{meta.get('run_id', 'n/a')}`")
        lines.append(f"- **Config hash:** `{meta.get('config_hash', 'n/a')}`")
        lines.append(f"- **Git commit:** `{meta.get('git_commit', 'n/a')}`")
        lines.append("")

    lines.append("## Pre/Post Cost Performance\n")
    lines.extend(_dict_table_md("Post-cost strategy metrics", metrics, _FMT))

    lines.append("## Baselines\n")
    lines.extend(_metrics_matrix_md("Baseline comparison", baselines))

    lines.append("## Turnover And Costs\n")
    lines.extend(_dict_table_md("Exposure / turnover summary", exposure_summary))

    lines.append("## Cost Stress (1x/2x/4x)\n")
    lines.extend(_metrics_matrix_md("Cost stress metrics", cost_stress))

    lines.append("## Exposure Diagnostics\n")
    lines.extend(_dict_table_md("Gross / net summary", exposure_summary))

    lines.append("## Risk Contributions\n")
    lines.extend(_dict_table_md("Risk contribution summary", risk_summary))

    lines.append("## Regime Split Metrics\n")
    lines.extend(_metrics_matrix_md("Risk-on vs risk-off", regime_split))

    for fname in figure_filenames:
        label = Path(fname).stem.replace("_", " ").title()
        lines.append(f"## {label}\n")
        lines.append(f"![{label}]({fname})\n")

    return "\n".join(lines)


def save_macro_allocator_report(
    name: str,
    output_dir: str | Path,
    *,
    metrics: dict[str, float],
    baselines: dict[str, dict[str, float]],
    cost_stress: dict[str, dict[str, float]],
    regime_split: dict[str, dict[str, float]],
    exposure_summary: dict[str, float],
    risk_summary: dict[str, float],
    figure_filenames: Sequence[str] = (),
    meta: dict[str, Any] | None = None,
) -> Path:
    """Write Week-2 macro allocator report to ``report.md``."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_text = macro_allocator_markdown_report(
        name,
        metrics=metrics,
        baselines=baselines,
        cost_stress=cost_stress,
        regime_split=regime_split,
        exposure_summary=exposure_summary,
        risk_summary=risk_summary,
        figure_filenames=figure_filenames,
        meta=meta,
    )
    path = out_dir / "report.md"
    path.write_text(report_text)
    log.info("Macro allocator report saved → %s", path)
    return path
