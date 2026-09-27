"""Expose configured candidate paper/shadow composition without executable authority."""

# project library imports
from applications.paper.installed import InstalledPaperAccount, SocketPaperAccount
from applications.paper.monitoring import (
    PaperMonitoringInput,
    PaperMonitoringResult,
    render_paper_monitoring,
)
from applications.paper.public import SharedPublicPaperResult, run_live_shared_paper
from applications.paper.shared import SharedPaperDecision, SharedPaperResult, run_shared_paper
from applications.paper.workflow import (
    LivePaperRunResult,
    PaperRunResult,
    PaperTimer,
    run_live_paper,
    run_paper,
)

__all__ = [
    "InstalledPaperAccount",
    "LivePaperRunResult",
    "PaperMonitoringInput",
    "PaperMonitoringResult",
    "PaperRunResult",
    "PaperTimer",
    "SharedPaperDecision",
    "SharedPaperResult",
    "SharedPublicPaperResult",
    "SocketPaperAccount",
    "render_paper_monitoring",
    "run_live_paper",
    "run_live_shared_paper",
    "run_paper",
    "run_shared_paper",
]
