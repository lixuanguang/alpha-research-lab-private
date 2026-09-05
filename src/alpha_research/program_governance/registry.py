"""Compatibility facade for program-registry operations."""

# project library imports
from alpha_research_governance.program_governance.registry import (
    APPLICABLE_GATE_IDS,
    METRIC_IDS,
    ROADMAP_PACKAGE_IDS,
    load_observations,
    load_program,
    load_roadmap,
    validate_repository,
)
from alpha_research_governance.program_governance.status import (
    render_status_markdown,
    validate_status_document,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "METRIC_IDS",
    "ROADMAP_PACKAGE_IDS",
    "load_observations",
    "load_program",
    "load_roadmap",
    "render_status_markdown",
    "validate_repository",
    "validate_status_document",
]
