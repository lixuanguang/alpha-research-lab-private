"""Research-plane modules.

This package exports module namespaces only:
- artifact path helpers
- as-of join helpers
- dataset contracts and builder
- run-context and manifest contracts
- universe management
"""

import alpha_core.research.artifact_paths as artifact_paths
import alpha_core.research.artifact_store as artifact_store
import alpha_core.research.as_of as as_of
import alpha_core.research.backtest_runner as backtest_runner
import alpha_core.research.dataset as dataset
import alpha_core.research.dataset_builder as dataset_builder
import alpha_core.research.evaluate_runner as evaluate_runner
import alpha_core.research.feature_runner as feature_runner
import alpha_core.research.manifest as manifest
import alpha_core.research.optimize_runner as optimize_runner
import alpha_core.research.run_context as run_context
import alpha_core.research.run_summary as run_summary
import alpha_core.research.universe as universe

__all__ = [
    "artifact_paths",
    "artifact_store",
    "as_of",
    "backtest_runner",
    "dataset",
    "dataset_builder",
    "evaluate_runner",
    "feature_runner",
    "manifest",
    "optimize_runner",
    "run_context",
    "run_summary",
    "universe",
]
