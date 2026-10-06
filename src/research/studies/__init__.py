"""Expose retained research studies, reports and external integration capabilities."""

# project library imports
from research.models import EvaluationRecord
from research.studies.book_reports import BookReport
from research.studies.captured_market import CapturedStudyMarket
from research.studies.comparison import ComparisonEvaluator, ComparisonStudy, ParameterComparison
from research.studies.configuration import BacktestRun
from research.studies.decision_studies import DecisionComparison, DecisionStudy, StudyFold
from research.studies.diagnostic_runs import WindowDiagnosticRun
from research.studies.diagnostics import (
    AlphalensDiagnostics,
    AlphalensReport,
    AlphalensStudy,
    DiagnosticDrop,
    DiagnosticMetric,
    FactorDirection,
    PriceConvention,
    QuantileRule,
)
from research.studies.evaluation import TrialEvaluation
from research.studies.extensions import (
    LedgerCurveChart,
    NetReturnMetric,
    StudyReport,
    StudyReportBuilder,
    StudyReportReader,
)
from research.studies.inputs import ResearchInputs
from research.studies.monitoring import (
    ReportChartAdapter,
    ReportMetricAdapter,
    ReportMonitoringBridge,
    StudyMonitoringExporter,
)
from research.studies.pipelines import PipelineRun, PipelineStepTask, ResearchPipeline
from research.studies.publication import PublicationPolicy
from research.studies.reports import BenchmarkPeriod, EconomicReport, QuantStatsReport, ReportPolicy
from research.studies.results import ResultManifest, RunCheckpoint
from research.studies.study_inputs import (
    StudyArtifact,
    StudyMarketManifest,
    StudyMarketSource,
    StudyOutcomeSource,
)
from research.studies.study_results import StudyFoldResult, StudyResult
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
    "CapturedStudyMarket",
    "ClearMLDestination",
    "ClearMLPublication",
    "ComparisonEvaluator",
    "ComparisonStudy",
    "DecisionComparison",
    "DecisionStudy",
    "DiagnosticDrop",
    "DiagnosticMetric",
    "DiagnosticObservation",
    "DiagnosticSource",
    "DistributionDiagnostic",
    "EconomicReport",
    "EvaluationRecord",
    "FactorDirection",
    "LedgerCurveChart",
    "NetReturnMetric",
    "ParameterComparison",
    "PipelineRun",
    "PipelineStepTask",
    "PredictiveDiagnostic",
    "PriceConvention",
    "PublicationPolicy",
    "PublicationReceipt",
    "QuantStatsReport",
    "QuantileRule",
    "ReportChartAdapter",
    "ReportMetricAdapter",
    "ReportMonitoringBridge",
    "ReportPolicy",
    "ResearchInputs",
    "ResearchPipeline",
    "ResultManifest",
    "RunCheckpoint",
    "StudyArtifact",
    "StudyFold",
    "StudyFoldResult",
    "StudyMarketManifest",
    "StudyMarketSource",
    "StudyMonitoringExporter",
    "StudyOutcomeSource",
    "StudyReport",
    "StudyReportBuilder",
    "StudyReportReader",
    "StudyResult",
    "TrackedModel",
    "TrialEvaluation",
    "WindowDiagnosticReport",
    "WindowDiagnosticRun",
    "WindowDiagnosticStudy",
    "WindowDiagnostics",
]
