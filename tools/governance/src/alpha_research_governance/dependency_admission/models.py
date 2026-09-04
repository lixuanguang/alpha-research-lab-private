"""Immutable values for dependency admission and signal assessment."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

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


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SourceArchive(ImmutableModel):
    """Identify an upstream source or build-input archive by immutable revision and bytes."""

    uri: str
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    sha256: Sha256
    license_expression: str


class EvidenceFile(ImmutableModel):
    """Bind retained repository-local verification input to exact bytes."""

    path: str
    sha256: Sha256


class WheelProvenance(ImmutableModel):
    """Bind one locked wheel to a retained Sigstore attestation bundle."""

    filename: str
    sha256: Sha256
    bundle: EvidenceFile


class WheelEvidenceAdmission(ImmutableModel):
    """Identify reviewed sources, locked wheels and their expected attestation signer."""

    name: str
    version: str
    owner_role: str
    rationale: Annotated[str, Field(min_length=40, max_length=2000)]
    sources: tuple[SourceArchive, ...]
    certificate_identity: str
    oidc_issuer: str
    trusted_root: EvidenceFile
    wheels: tuple[WheelProvenance, ...]


class WheelSourceAdmission(WheelEvidenceAdmission):
    """Require authenticated SLSA source evidence in place of an absent PyPI sdist."""

    builder_id: str
    build_type: str
    build_parameters_sha256: Sha256


class BootstrapWheelAdmission(WheelEvidenceAdmission):
    """Accept an explicit source-to-wheel evidence gap for bounded bootstrap use only."""

    usage: Literal["isolated_development_and_ci"]
    source_to_wheel_binding: Literal["unverified"]
    finding_id: Annotated[str, Field(pattern=r"^B07-DEP-[0-9]{3}$")]
    reviewed_on: date
    expires_on: date
    residual_risk: Annotated[str, Field(min_length=40, max_length=2000)]
    closure_condition: Annotated[str, Field(min_length=40, max_length=2000)]
    source_review: EvidenceFile
    security_review: EvidenceFile
    native_inventory: EvidenceFile
    compatibility_report: EvidenceFile


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
    wheel_source_admissions: tuple[WheelSourceAdmission, ...] = ()
    bootstrap_wheel_admissions: tuple[BootstrapWheelAdmission, ...] = ()
