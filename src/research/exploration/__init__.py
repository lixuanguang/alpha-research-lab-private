"""Expose the research exploration public contract."""

# project library imports
from research.exploration.analysis import (
    AnalysisComparison,
    AnalysisMismatch,
    AnalysisQuery,
    AnalysisResult,
    BoundedFeatureAnalysis,
    DuckDBFeatureAnalysis,
    PolarsFeatureAnalysis,
    VerifiedFeatureRows,
)
from research.exploration.feature_study import FeatureStudy
from research.exploration.query import EdaQuery, QuerySummary
from research.exploration.selection import (
    BookResearchInput,
    BookSelection,
    PublicTradeResearchInput,
    PublicTradeSelection,
    ReferenceResearchInput,
    ReferenceSelection,
    ResearchDataset,
    ResearchReader,
    ResearchSelection,
    TradeCoverage,
    TradeResearchInput,
    TradeSelection,
)
from research.exploration.study import ExplorationStudy

__all__ = [
    "AnalysisComparison",
    "AnalysisMismatch",
    "AnalysisQuery",
    "AnalysisResult",
    "BookResearchInput",
    "BookSelection",
    "BoundedFeatureAnalysis",
    "DuckDBFeatureAnalysis",
    "EdaQuery",
    "ExplorationStudy",
    "FeatureStudy",
    "PolarsFeatureAnalysis",
    "PublicTradeResearchInput",
    "PublicTradeSelection",
    "QuerySummary",
    "ReferenceResearchInput",
    "ReferenceSelection",
    "ResearchDataset",
    "ResearchReader",
    "ResearchSelection",
    "TradeCoverage",
    "TradeResearchInput",
    "TradeSelection",
    "VerifiedFeatureRows",
]
