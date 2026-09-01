"""Compatibility facade for program-registry operations."""

from alpha_research_governance.program_governance.registry import (
    APPLICABLE_GATE_IDS,
    METRIC_IDS,
    PACKAGE_IDS,
    load_observations,
    load_program,
    load_roadmap,
    validate_repository,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "METRIC_IDS",
    "PACKAGE_IDS",
    "load_observations",
    "load_program",
    "load_roadmap",
    "validate_repository",
]
