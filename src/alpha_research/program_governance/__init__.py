"""Compatibility facade for the canonical program-governance tool."""

from alpha_research_governance.program_governance import (
    APPLICABLE_GATE_IDS,
    METRIC_IDS,
    ROADMAP_PACKAGE_IDS,
    MetricDefinition,
    MetricObservation,
    MetricSummary,
    PackageNode,
    PackageState,
    ProgramGovernance,
    ProgramGovernanceError,
    load_observations,
    load_program,
    load_roadmap,
    main,
    validate_repository,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "METRIC_IDS",
    "ROADMAP_PACKAGE_IDS",
    "MetricDefinition",
    "MetricObservation",
    "MetricSummary",
    "PackageNode",
    "PackageState",
    "ProgramGovernance",
    "ProgramGovernanceError",
    "load_observations",
    "load_program",
    "load_roadmap",
    "main",
    "validate_repository",
]
