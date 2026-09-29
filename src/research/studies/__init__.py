"""Expose retained research studies, reports and external integration capabilities."""

# project library imports
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
from research.studies.evaluation import EvaluationRecord, TrialEvaluation
from research.studies.extensions import (
    ChartDefinition,
    ChartSpec,
    FoldSummary,
    LedgerCurveChart,
    LedgerPoint,
    MetricDefinition,
    MetricValue,
    NetReturnMetric,
    ReportContext,
    ReportObservation,
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
from research.studies.pipelines import PipelineRun, ResearchPipeline
from research.studies.publication import PublicationPolicy
from research.studies.reports import BenchmarkPeriod, EconomicReport, QuantStatsReport, ReportPolicy
from research.studies.results import ResultManifest, RunCheckpoint
from research.studies.study_inputs import StudyArtifact, StudyMarketSource, StudyOutcomeSource
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
    "ChartDefinition",
    "ChartSpec",
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
    "FoldSummary",
    "LedgerCurveChart",
    "LedgerPoint",
    "MetricDefinition",
    "MetricValue",
    "NetReturnMetric",
    "ParameterComparison",
    "PipelineRun",
    "PredictiveDiagnostic",
    "PriceConvention",
    "PublicationPolicy",
    "PublicationReceipt",
    "QuantStatsReport",
    "QuantileRule",
    "ReportChartAdapter",
    "ReportContext",
    "ReportMetricAdapter",
    "ReportMonitoringBridge",
    "ReportObservation",
    "ReportPolicy",
    "ResearchInputs",
    "ResearchPipeline",
    "ResultManifest",
    "RunCheckpoint",
    "StudyArtifact",
    "StudyFold",
    "StudyFoldResult",
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
