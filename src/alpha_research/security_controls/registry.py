"""Compatibility facade for A07 security-control registry operations."""

from alpha_research_governance.security_controls.registry import (
    APPLICABLE_GATE_IDS,
    DEPENDENCY_PACKAGE_IDS,
    JURISDICTION_IDS,
    THREAT_CATEGORIES,
    load_control_map,
    validate_repository,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "DEPENDENCY_PACKAGE_IDS",
    "JURISDICTION_IDS",
    "THREAT_CATEGORIES",
    "load_control_map",
    "validate_repository",
]
