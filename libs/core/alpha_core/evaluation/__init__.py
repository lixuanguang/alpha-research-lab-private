"""alpha_core.evaluation — R5 evaluation metrics and reporting contracts.

Modules
-------
financial    Standard financial performance metrics (Sharpe, drawdown, etc.)
pm_metrics   Prediction-market-specific metrics (Brier, log-loss, calibration)
calibration  Calibration curve and Expected Calibration Error (ECE)
evaluator    BacktestEvaluator — orchestrates all metrics into EvaluationReport
"""

from alpha_core.evaluation.calibration import (
    calibration_curve,
    expected_calibration_error,
)
from alpha_core.evaluation.evaluator import (
    EVALUATION_REPORT_SCHEMA_VERSION,
    BacktestEvaluator,
    EvaluationReport,
)
from alpha_core.evaluation.financial import (
    FinancialMetrics,
    compute_financial_metrics,
)
from alpha_core.evaluation.pm_metrics import (
    PMMetrics,
    compute_pm_metrics,
)

__all__ = [
    "EVALUATION_REPORT_SCHEMA_VERSION",
    "BacktestEvaluator",
    "EvaluationReport",
    "FinancialMetrics",
    "PMMetrics",
    "calibration_curve",
    "compute_financial_metrics",
    "compute_pm_metrics",
    "expected_calibration_error",
]
