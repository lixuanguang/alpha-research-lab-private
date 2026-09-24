"""Expose lightweight experiment identity, temporal folds and retained attempts.

The package boundary contains only records needed to describe and retain an
experiment.  Optional reporting, comparison, diagnostics and tracking APIs
remain in their owning modules so importing :class:`AttemptStore` does not
initialize their third-party SDKs.
"""

# project library imports
from research.experiments.candidates import (
    CandidateArtifact,
    CandidateAssessment,
    CandidateBundle,
    CandidateComponent,
    CandidateManifest,
    CandidateMetricContract,
    CandidateStateContract,
)
from research.experiments.identity import ExperimentSpec, Fingerprint
from research.experiments.splits import SampleInterval, TemporalSplit, TimeWindow
from research.experiments.store import AttemptEvent, AttemptHistory, AttemptStart, AttemptStore

__all__ = [
    "AttemptEvent",
    "AttemptHistory",
    "AttemptStart",
    "AttemptStore",
    "CandidateArtifact",
    "CandidateAssessment",
    "CandidateBundle",
    "CandidateComponent",
    "CandidateManifest",
    "CandidateMetricContract",
    "CandidateStateContract",
    "ExperimentSpec",
    "Fingerprint",
    "SampleInterval",
    "TemporalSplit",
    "TimeWindow",
]
