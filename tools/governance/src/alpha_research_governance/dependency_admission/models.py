"""Immutable values for dependency admission and signal assessment."""

from __future__ import annotations

from datetime import date

from alpha_research_governance._models import ImmutableModel


class DependencyAdmissionError(ValueError):
    """Report one or more fail-closed dependency-admission findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class PythonPackageAdmission(ImmutableModel):
    """One exact external Python package admitted from the uv lock."""

    name: str
    version: str
    license_expression: str
    native_artifacts: bool


class VulnerabilityDecision(ImmutableModel):
    """Repository-owned disposition for one scanner finding."""

    vulnerability_id: str
    package_name: str
    affected_version: str
    disposition: str
    owner_role: str
    rationale: str
    expires_on: date
    evidence_url: str


class EmergencyOverride(ImmutableModel):
    """Audited and time-bounded exception for one admitted component."""

    override_id: str
    component_id: str
    owner_role: str
    rationale: str
    expires_on: date
    evidence_url: str


class DependencyAdmission(ImmutableModel):
    """Complete repository-local dependency-admission contract for package B07."""

    package_status: str
    successor_package: str
    as_of_date: date
    review_due_on: date
    pip_audit_version: str
    vulnerability_service: str
    scorecard_version: str
    maximum_signal_age_days: int
    emergency_override_maximum_days: int
    supported_platforms: tuple[str, ...]
    approved_python_indexes: tuple[str, ...]
    lock_paths: tuple[str, ...]
    lock_digests: tuple[tuple[str, str], ...]
    migrated_record_paths: tuple[str, ...]
    runtime_scan_roots: tuple[str, ...]
    packages: tuple[PythonPackageAdmission, ...]
    vulnerability_decisions: tuple[VulnerabilityDecision, ...]
    emergency_overrides: tuple[EmergencyOverride, ...]
    applicable_gate_ids: tuple[str, ...]
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    open_finding_ids: tuple[str, ...]
