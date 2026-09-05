"""Compatibility facade for the canonical program-governance tool."""

# project library imports
from alpha_research_governance.program_governance import (
    APPLICABLE_GATE_IDS,
    METRIC_IDS,
    ROADMAP_PACKAGE_IDS,
    FindingDispositionGroup,
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
    render_status_markdown,
    validate_repository,
    validate_status_document,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "METRIC_IDS",
    "ROADMAP_PACKAGE_IDS",
    "FindingDispositionGroup",
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
    "render_status_markdown",
    "validate_repository",
    "validate_status_document",
]
