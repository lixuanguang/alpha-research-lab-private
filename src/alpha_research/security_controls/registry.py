"""Compatibility facade for security-control registry operations."""

from alpha_research_governance.security_controls.registry import (
    APPLICABLE_GATE_IDS,
    JURISDICTION_IDS,
    SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS,
    THREAT_CATEGORIES,
    load_control_map,
    validate_repository,
)

__all__ = [
    "APPLICABLE_GATE_IDS",
    "JURISDICTION_IDS",
    "SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS",
    "THREAT_CATEGORIES",
    "load_control_map",
    "validate_repository",
]
