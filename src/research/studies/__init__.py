"""Expose retained research studies, reports and external integration capabilities."""

# project library imports
from research.studies.book_reports import BookReport
from research.studies.comparison import ComparisonEvaluator, ComparisonStudy, ParameterComparison
from research.studies.configuration import BacktestRun
from research.studies.diagnostic_runs import WindowDiagnosticRun
from research.studies.diagnostics import (
    AlphalensDiagnostics,
    AlphalensReport,
    AlphalensStudy,
    DiagnosticDrop,
    DiagnosticMetric,
    FactorDirection,
    FeatureLabelPayload,
    PriceConvention,
    QuantileRule,
)
from research.studies.evaluation import EvaluationRecord, TrialEvaluation
from research.studies.inputs import ResearchInputs
from research.studies.pipelines import PipelineRun, ResearchPipeline
from research.studies.reports import BenchmarkPeriod, EconomicReport, QuantStatsReport, ReportPolicy
from research.studies.results import ResultManifest, RunCheckpoint
from research.studies.tracking import (
    ClearMLDestination,
    ClearMLPublication,
    PublicationReceipt,
    TrackedModel,
)
from research.studies.window_diagnostics import (
    DiagnosticObservation,
    DiagnosticSource,
    DistributionDiagnostic,
    PredictiveDiagnostic,
    WindowDiagnosticReport,
    WindowDiagnostics,
    WindowDiagnosticStudy,
)

__all__ = [
    "AlphalensDiagnostics",
    "AlphalensReport",
    "AlphalensStudy",
    "BacktestRun",
    "BenchmarkPeriod",
    "BookReport",
    "ClearMLDestination",
    "ClearMLPublication",
    "ComparisonEvaluator",
    "ComparisonStudy",
    "DiagnosticDrop",
    "DiagnosticMetric",
    "DiagnosticObservation",
    "DiagnosticSource",
    "DistributionDiagnostic",
    "EconomicReport",
    "EvaluationRecord",
    "FactorDirection",
    "FeatureLabelPayload",
    "ParameterComparison",
    "PipelineRun",
    "PredictiveDiagnostic",
    "PriceConvention",
    "PublicationReceipt",
    "QuantStatsReport",
    "QuantileRule",
    "ReportPolicy",
    "ResearchInputs",
    "ResearchPipeline",
    "ResultManifest",
    "RunCheckpoint",
    "TrackedModel",
    "TrialEvaluation",
    "WindowDiagnosticReport",
    "WindowDiagnosticRun",
    "WindowDiagnosticStudy",
    "WindowDiagnostics",
]
