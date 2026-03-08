"""Comparison helpers for side-by-side analysis of multiple EvaluationReports.

Usage::

    from apps.research.reporting.comparisons import compare_reports, rank_reports

    df = compare_reports([report_a, report_b, report_c])
    ranked = rank_reports(df, primary="sharpe_ratio", secondary="calmar_ratio")
"""

from __future__ import annotations

import pandas as pd

import alpha_core.evaluation.evaluator as evaluator_mod


def compare_reports(reports: list[evaluator_mod.EvaluationReport]) -> pd.DataFrame:
    """Return a tidy DataFrame with one row per report, one column per metric.

    Delegates to :meth:`~alpha_core.evaluation.evaluator.BacktestEvaluator.compare`.
    """
    return evaluator_mod.BacktestEvaluator().compare(reports)


def rank_reports(
    comparison_df: pd.DataFrame,
    primary: str = "sharpe_ratio",
    secondary: str = "calmar_ratio",
    ascending: bool = False,
) -> pd.DataFrame:
    """Sort a comparison DataFrame by *primary* then *secondary* metric.

    Parameters
    ----------
    comparison_df:
        Output of :func:`compare_reports`.
    primary:
        Column to sort by first.
    secondary:
        Tie-break column.
    ascending:
        Sort direction.  ``False`` (default) = best score first.

    Returns
    -------
    pd.DataFrame
        Sorted copy with an integer ``rank`` column (1-indexed).
    """
    if comparison_df.empty:
        return comparison_df.copy()

    missing = [c for c in (primary, secondary) if c not in comparison_df.columns]
    if missing:
        available = list(comparison_df.columns)
        raise ValueError(f"Columns {missing} not found in comparison_df.  Available: {available}")

    ranked = comparison_df.sort_values(
        [primary, secondary],
        ascending=[ascending, ascending],
        kind="stable",
    ).reset_index(drop=True)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked


def pivot_metric(
    reports: list[evaluator_mod.EvaluationReport],
    metric: str,
) -> pd.Series:
    """Extract a single metric from a list of reports as a labelled Series.

    Parameters
    ----------
    reports:
        List of :class:`~alpha_core.evaluation.evaluator.EvaluationReport`.
    metric:
        Column name in the comparison DataFrame (e.g. ``"sharpe_ratio"``).

    Returns
    -------
    pd.Series
        Indexed by ``backtest_id``, values are the requested metric.
    """
    df = compare_reports(reports)
    if df.empty or metric not in df.columns:
        return pd.Series(dtype=float)
    return df.set_index("backtest_id")[metric]


__all__ = ["compare_reports", "pivot_metric", "rank_reports"]
