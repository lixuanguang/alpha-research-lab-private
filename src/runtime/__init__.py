"""Expose the runtime public contract."""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from runtime.identity import ImplementationIdentity, InstalledIdentity, RuntimeFiles
from runtime.supervision import ProcessSupervisor

if TYPE_CHECKING:
    # project library imports
    from runtime.account_recovery import AccountRecoveryReceipt, AccountWorkspace
    from runtime.authored_candidates import AuthoredCandidates, ReferenceCandidates
    from runtime.candidate_worker import (
        CandidateProcessFailure,
        LocalCandidateExecutor,
        ProcessCandidateExecutor,
    )
    from runtime.candidates import (
        CandidateCheckpoint,
        CandidateLoader,
        CandidateSession,
        CandidateStep,
        LoadedCandidate,
    )
    from runtime.components import (
        CandidateComponents,
        ChartFactory,
        EstimatorFactory,
        FeatureFactory,
        MetricFactory,
        PolicyFactory,
        TransformFactory,
    )
    from runtime.extensions import ExtensionFactories, ExtensionProvider, InstalledExtensions
    from runtime.feature_feed import CandidateFeatureFeed
    from runtime.jobs import (
        JobHandler,
        JobHealth,
        JobProgress,
        JobQueue,
        JobRun,
        JobSpec,
        JobState,
        JobWorkerPool,
    )
    from runtime.live_paper import LiveBookDelivery, PaperCaptureObserver
    from runtime.monitoring import CandidateMonitoringExporter
    from runtime.paper import PaperCandidateRuntime, PaperCheckpoint
    from runtime.paper_capabilities import PaperCapabilities
    from runtime.portfolio import (
        CandidateExecutor,
        SharedCandidateCheckpoint,
        SharedDecisionRuntime,
        SharedStrategyBinding,
        SharedStrategyInput,
    )
    from runtime.shared_paper import (
        SharedBookDelivery,
        SharedDecisionGroup,
        SharedPaperCaptureObserver,
    )
    from runtime.workspace import WorkspaceBackup, WorkspaceFile, WorkspaceManifest


def __getattr__(name: str) -> object:
    """Load research and workspace services only for their explicit consumers."""
    if name in {"SharedBookDelivery", "SharedDecisionGroup", "SharedPaperCaptureObserver"}:
        # project library imports
        from runtime import shared_paper

        exports: dict[str, object] = {
            "SharedBookDelivery": shared_paper.SharedBookDelivery,
            "SharedDecisionGroup": shared_paper.SharedDecisionGroup,
            "SharedPaperCaptureObserver": shared_paper.SharedPaperCaptureObserver,
        }
        return exports[name]
    if name in {"ExtensionFactories", "ExtensionProvider", "InstalledExtensions"}:
        # project library imports
        from runtime import extensions

        exports = {
            "ExtensionFactories": extensions.ExtensionFactories,
            "ExtensionProvider": extensions.ExtensionProvider,
            "InstalledExtensions": extensions.InstalledExtensions,
        }
        return exports[name]
    if name in {"PaperCapabilities"}:
        # project library imports
        from runtime import paper_capabilities

        exports = {"PaperCapabilities": paper_capabilities.PaperCapabilities}
        return exports[name]
    if name in {"AuthoredCandidates", "ReferenceCandidates"}:
        # project library imports
        from runtime import authored_candidates

        exports = {
            "AuthoredCandidates": authored_candidates.AuthoredCandidates,
            "ReferenceCandidates": authored_candidates.ReferenceCandidates,
        }
        return exports[name]
    if name in {"AccountRecoveryReceipt", "AccountWorkspace"}:
        # project library imports
        from runtime import account_recovery

        exports = {
            "AccountRecoveryReceipt": account_recovery.AccountRecoveryReceipt,
            "AccountWorkspace": account_recovery.AccountWorkspace,
        }
        return exports[name]
    if name in {
        "CandidateExecutor",
        "SharedCandidateCheckpoint",
        "SharedDecisionRuntime",
        "SharedStrategyBinding",
        "SharedStrategyInput",
    }:
        # project library imports
        from runtime import portfolio

        exports = {
            "CandidateExecutor": portfolio.CandidateExecutor,
            "SharedCandidateCheckpoint": portfolio.SharedCandidateCheckpoint,
            "SharedDecisionRuntime": portfolio.SharedDecisionRuntime,
            "SharedStrategyBinding": portfolio.SharedStrategyBinding,
            "SharedStrategyInput": portfolio.SharedStrategyInput,
        }
        return exports[name]
    if name in {"LiveBookDelivery", "PaperCaptureObserver"}:
        # project library imports
        from runtime import live_paper

        exports = {
            "LiveBookDelivery": live_paper.LiveBookDelivery,
            "PaperCaptureObserver": live_paper.PaperCaptureObserver,
        }
        return exports[name]
    if name in {"PaperCandidateRuntime", "PaperCheckpoint"}:
        # project library imports
        from runtime import paper

        exports = {
            "PaperCandidateRuntime": paper.PaperCandidateRuntime,
            "PaperCheckpoint": paper.PaperCheckpoint,
        }
        return exports[name]
    if name in {"CandidateProcessFailure", "LocalCandidateExecutor", "ProcessCandidateExecutor"}:
        # project library imports
        from runtime import candidate_worker

        exports = {
            "CandidateProcessFailure": candidate_worker.CandidateProcessFailure,
            "LocalCandidateExecutor": candidate_worker.LocalCandidateExecutor,
            "ProcessCandidateExecutor": candidate_worker.ProcessCandidateExecutor,
        }
        return exports[name]
    if name in {"CandidateFeatureFeed"}:
        # project library imports
        from runtime import feature_feed

        exports = {
            "CandidateFeatureFeed": feature_feed.CandidateFeatureFeed,
        }
        return exports[name]
    if name in {"CandidateMonitoringExporter"}:
        # project library imports
        from runtime import monitoring

        exports = {
            "CandidateMonitoringExporter": monitoring.CandidateMonitoringExporter,
        }
        return exports[name]
    if name in {
        "CandidateCheckpoint",
        "CandidateLoader",
        "CandidateSession",
        "CandidateStep",
        "LoadedCandidate",
    }:
        # project library imports
        from runtime import candidates

        exports = {
            "CandidateCheckpoint": candidates.CandidateCheckpoint,
            "CandidateLoader": candidates.CandidateLoader,
            "CandidateSession": candidates.CandidateSession,
            "CandidateStep": candidates.CandidateStep,
            "LoadedCandidate": candidates.LoadedCandidate,
        }
        return exports[name]
    if name in {
        "CandidateComponents",
        "ChartFactory",
        "EstimatorFactory",
        "FeatureFactory",
        "MetricFactory",
        "PolicyFactory",
        "TransformFactory",
    }:
        # project library imports
        from runtime import components

        exports = {
            "CandidateComponents": components.CandidateComponents,
            "ChartFactory": components.ChartFactory,
            "EstimatorFactory": components.EstimatorFactory,
            "FeatureFactory": components.FeatureFactory,
            "MetricFactory": components.MetricFactory,
            "PolicyFactory": components.PolicyFactory,
            "TransformFactory": components.TransformFactory,
        }
        return exports[name]
    if name in {
        "JobHandler",
        "JobHealth",
        "JobProgress",
        "JobQueue",
        "JobRun",
        "JobSpec",
        "JobState",
        "JobWorkerPool",
    }:
        # project library imports
        from runtime import jobs

        exports = {
            "JobHandler": jobs.JobHandler,
            "JobHealth": jobs.JobHealth,
            "JobProgress": jobs.JobProgress,
            "JobQueue": jobs.JobQueue,
            "JobRun": jobs.JobRun,
            "JobSpec": jobs.JobSpec,
            "JobState": jobs.JobState,
            "JobWorkerPool": jobs.JobWorkerPool,
        }
        return exports[name]
    if name in {"WorkspaceBackup", "WorkspaceFile", "WorkspaceManifest"}:
        # project library imports
        from runtime import workspace

        exports = {
            "WorkspaceBackup": workspace.WorkspaceBackup,
            "WorkspaceFile": workspace.WorkspaceFile,
            "WorkspaceManifest": workspace.WorkspaceManifest,
        }
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "AccountRecoveryReceipt",
    "AccountWorkspace",
    "AuthoredCandidates",
    "CandidateCheckpoint",
    "CandidateComponents",
    "CandidateExecutor",
    "CandidateFeatureFeed",
    "CandidateLoader",
    "CandidateMonitoringExporter",
    "CandidateProcessFailure",
    "CandidateSession",
    "CandidateStep",
    "ChartFactory",
    "EstimatorFactory",
    "ExtensionFactories",
    "ExtensionProvider",
    "FeatureFactory",
    "ImplementationIdentity",
    "InstalledExtensions",
    "InstalledIdentity",
    "JobHandler",
    "JobHealth",
    "JobProgress",
    "JobQueue",
    "JobRun",
    "JobSpec",
    "JobState",
    "JobWorkerPool",
    "LiveBookDelivery",
    "LoadedCandidate",
    "LocalCandidateExecutor",
    "MetricFactory",
    "PaperCandidateRuntime",
    "PaperCapabilities",
    "PaperCaptureObserver",
    "PaperCheckpoint",
    "PolicyFactory",
    "ProcessCandidateExecutor",
    "ProcessSupervisor",
    "ReferenceCandidates",
    "RuntimeFiles",
    "SharedBookDelivery",
    "SharedCandidateCheckpoint",
    "SharedDecisionGroup",
    "SharedDecisionRuntime",
    "SharedPaperCaptureObserver",
    "SharedStrategyBinding",
    "SharedStrategyInput",
    "TransformFactory",
    "WorkspaceBackup",
    "WorkspaceFile",
    "WorkspaceManifest",
]
