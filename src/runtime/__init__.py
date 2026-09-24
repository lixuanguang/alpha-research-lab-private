"""Expose the runtime public contract."""

# standard library imports
from typing import TYPE_CHECKING

# project library imports
from runtime.identity import ImplementationIdentity, InstalledIdentity, RuntimeFiles
from runtime.supervision import ProcessSupervisor

if TYPE_CHECKING:
    # project library imports
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
    from runtime.workspace import WorkspaceBackup, WorkspaceFile, WorkspaceManifest


def __getattr__(name: str) -> object:
    """Load research and workspace services only for their explicit consumers."""
    if name in {
        "CandidateCheckpoint",
        "CandidateLoader",
        "CandidateSession",
        "CandidateStep",
        "LoadedCandidate",
    }:
        # project library imports
        from runtime import candidates

        exports: dict[str, object] = {
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
    "CandidateCheckpoint",
    "CandidateComponents",
    "CandidateLoader",
    "CandidateSession",
    "CandidateStep",
    "ChartFactory",
    "EstimatorFactory",
    "FeatureFactory",
    "ImplementationIdentity",
    "InstalledIdentity",
    "JobHandler",
    "JobHealth",
    "JobProgress",
    "JobQueue",
    "JobRun",
    "JobSpec",
    "JobState",
    "JobWorkerPool",
    "LoadedCandidate",
    "MetricFactory",
    "PolicyFactory",
    "ProcessSupervisor",
    "RuntimeFiles",
    "TransformFactory",
    "WorkspaceBackup",
    "WorkspaceFile",
    "WorkspaceManifest",
]
