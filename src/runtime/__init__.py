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
    from runtime.feature_feed import CandidateFeatureFeed, ServedFeature, ServedFeatures
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
    from runtime.live_inputs import FollowedFeed, LiveInputs
    from runtime.live_paper import LiveBookDelivery, PaperCaptureObserver
    from runtime.monitoring import CandidateMonitoringExporter
    from runtime.packaging import CandidatePackager, ComponentSelection
    from runtime.paper import PaperCandidateRuntime, PaperCheckpoint
    from runtime.paper_capabilities import PaperCapabilities
    from runtime.paper_inputs import PaperInputs
    from runtime.portfolio import (
        CandidateExecutor,
        SharedCandidateCheckpoint,
        SharedDecisionRuntime,
        SharedStrategyBinding,
        SharedStrategyInput,
    )
    from runtime.requirements import CandidateRequirements
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
    if name in {"FollowedFeed", "LiveInputs"}:
        # project library imports
        from runtime import live_inputs

        exports = {"FollowedFeed": live_inputs.FollowedFeed, "LiveInputs": live_inputs.LiveInputs}
        return exports[name]
    if name in {"PaperCapabilities"}:
        # project library imports
        from runtime import paper_capabilities

        exports = {"PaperCapabilities": paper_capabilities.PaperCapabilities}
        return exports[name]
    if name in {"CandidatePackager", "ComponentSelection"}:
        # project library imports
        from runtime import packaging

        exports = {
            "CandidatePackager": packaging.CandidatePackager,
            "ComponentSelection": packaging.ComponentSelection,
        }
        return exports[name]
    if name in {"CandidateRequirements"}:
        # project library imports
        from runtime import requirements

        exports = {"CandidateRequirements": requirements.CandidateRequirements}
        return exports[name]
    if name in {"PaperInputs"}:
        # project library imports
        from runtime import paper_inputs

        exports = {"PaperInputs": paper_inputs.PaperInputs}
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
    if name in {"CandidateFeatureFeed", "ServedFeature", "ServedFeatures"}:
        # project library imports
        from runtime import feature_feed

        exports = {
            "CandidateFeatureFeed": feature_feed.CandidateFeatureFeed,
            "ServedFeature": feature_feed.ServedFeature,
            "ServedFeatures": feature_feed.ServedFeatures,
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
    "CandidatePackager",
    "CandidateProcessFailure",
    "CandidateRequirements",
    "CandidateSession",
    "CandidateStep",
    "ChartFactory",
    "ComponentSelection",
    "EstimatorFactory",
    "ExtensionFactories",
    "ExtensionProvider",
    "FeatureFactory",
    "FollowedFeed",
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
    "LiveInputs",
    "LoadedCandidate",
    "LocalCandidateExecutor",
    "MetricFactory",
    "PaperCandidateRuntime",
    "PaperCapabilities",
    "PaperCaptureObserver",
    "PaperCheckpoint",
    "PaperInputs",
    "PolicyFactory",
    "ProcessCandidateExecutor",
    "ProcessSupervisor",
    "ReferenceCandidates",
    "RuntimeFiles",
    "ServedFeature",
    "ServedFeatures",
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
