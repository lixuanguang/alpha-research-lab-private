"""Expose configured candidate paper/shadow composition without executable authority."""

# project library imports
from applications.paper.shared import SharedPaperDecision, SharedPaperResult, run_shared_paper
from applications.paper.workflow import (
    LivePaperRunResult,
    PaperRunResult,
    PaperTimer,
    run_live_paper,
    run_paper,
)

__all__ = [
    "LivePaperRunResult",
    "PaperRunResult",
    "PaperTimer",
    "SharedPaperDecision",
    "SharedPaperResult",
    "run_live_paper",
    "run_paper",
    "run_shared_paper",
]
