"""Domain models for the A07 threat and regulatory control map."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class SecurityControlError(ValueError):
    """Report one or more deterministic A07 validation findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


@dataclass(frozen=True)
class ProtectedAsset:
    """One governed asset or authority represented in the threat model."""

    asset_id: str
    name: str
    owner_role: str
    security_objectives: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "owner_role": self.owner_role,
            "security_objectives": list(self.security_objectives),
        }


@dataclass(frozen=True)
class TrustBoundary:
    """One change in trust, authority, or security zone."""

    boundary_id: str
    name: str
    source_zone: str
    destination_zone: str
    asset_ids: tuple[str, ...]
    trust_change: str
    owner_role: str
    control_ids: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "asset_ids": list(self.asset_ids),
            "boundary_id": self.boundary_id,
            "control_ids": list(self.control_ids),
            "destination_zone": self.destination_zone,
            "name": self.name,
            "owner_role": self.owner_role,
            "source_zone": self.source_zone,
            "trust_change": self.trust_change,
        }


@dataclass(frozen=True)
class ThreatScenario:
    """One abuse case with explicit affected assets and controls."""

    threat_id: str
    title: str
    category: str
    actor: str
    abuse_case: str
    impact: str
    boundary_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    control_ids: tuple[str, ...]
    owner_role: str

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "abuse_case": self.abuse_case,
            "actor": self.actor,
            "asset_ids": list(self.asset_ids),
            "boundary_ids": list(self.boundary_ids),
            "category": self.category,
            "control_ids": list(self.control_ids),
            "impact": self.impact,
            "owner_role": self.owner_role,
            "threat_id": self.threat_id,
            "title": self.title,
        }


@dataclass(frozen=True)
class SecurityControl:
    """One owned, testable preventive, detective, or responsive control."""

    control_id: str
    title: str
    domain: str
    owner_role: str
    independent_review_roles: tuple[str, ...]
    objective: str
    control_functions: tuple[str, ...]
    implementation_packages: tuple[str, ...]
    implementation_status: str
    test_procedure: str
    fail_safe_response: str
    evidence_source_ids: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "control_functions": list(self.control_functions),
            "control_id": self.control_id,
            "domain": self.domain,
            "evidence_source_ids": list(self.evidence_source_ids),
            "fail_safe_response": self.fail_safe_response,
            "implementation_packages": list(self.implementation_packages),
            "implementation_status": self.implementation_status,
            "independent_review_roles": list(self.independent_review_roles),
            "objective": self.objective,
            "owner_role": self.owner_role,
            "test_procedure": self.test_procedure,
            "title": self.title,
        }


@dataclass(frozen=True)
class EvidenceSource:
    """One available or explicitly deferred source of control evidence."""

    evidence_source_id: str
    name: str
    source_type: str
    status: str
    owner_role: str
    location: str
    required_packages: tuple[str, ...]
    closure_condition: str

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "closure_condition": self.closure_condition,
            "evidence_source_id": self.evidence_source_id,
            "location": self.location,
            "name": self.name,
            "owner_role": self.owner_role,
            "required_packages": list(self.required_packages),
            "source_type": self.source_type,
            "status": self.status,
        }


@dataclass(frozen=True)
class AuthoritySource:
    """One official legal, supervisory, or reference-framework source."""

    source_id: str
    jurisdiction_id: str
    authority: str
    title: str
    citation: str
    source_class: str
    url: str
    last_verified_on: date

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "authority": self.authority,
            "citation": self.citation,
            "jurisdiction_id": self.jurisdiction_id,
            "last_verified_on": self.last_verified_on.isoformat(),
            "source_class": self.source_class,
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
        }


@dataclass(frozen=True)
class JurisdictionProfile:
    """A jurisdiction-specific scope awaiting qualified applicability review."""

    jurisdiction_id: str
    name: str
    scope: str
    applicability_status: str
    legal_owner_role: str
    source_ids: tuple[str, ...]
    review_due_on: date

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "applicability_status": self.applicability_status,
            "jurisdiction_id": self.jurisdiction_id,
            "legal_owner_role": self.legal_owner_role,
            "name": self.name,
            "review_due_on": self.review_due_on.isoformat(),
            "scope": self.scope,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class RegulatoryMapping:
    """A non-conclusive mapping from one authority source to platform controls."""

    mapping_id: str
    jurisdiction_id: str
    topic: str
    source_ids: tuple[str, ...]
    control_ids: tuple[str, ...]
    applicability_status: str
    applicability_rationale: str
    owner_role: str
    evidence_source_ids: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return a stable JSON representation."""
        return {
            "applicability_rationale": self.applicability_rationale,
            "applicability_status": self.applicability_status,
            "control_ids": list(self.control_ids),
            "evidence_source_ids": list(self.evidence_source_ids),
            "jurisdiction_id": self.jurisdiction_id,
            "mapping_id": self.mapping_id,
            "owner_role": self.owner_role,
            "source_ids": list(self.source_ids),
            "topic": self.topic,
        }


@dataclass(frozen=True)
class SecurityControlMap:
    """Validated A07 package contract and queryable control map."""

    schema_version: int
    roadmap_package: str
    operating_track: str
    accountable_owner_role: str
    risk_class: str
    dependency_package_ids: tuple[str, ...]
    applicable_gate_ids: tuple[str, ...]
    as_of_date: date
    package_status: str
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    assets: tuple[ProtectedAsset, ...]
    boundaries: tuple[TrustBoundary, ...]
    threats: tuple[ThreatScenario, ...]
    controls: tuple[SecurityControl, ...]
    evidence_sources: tuple[EvidenceSource, ...]
    authority_sources: tuple[AuthoritySource, ...]
    jurisdictions: tuple[JurisdictionProfile, ...]
    regulatory_mappings: tuple[RegulatoryMapping, ...]
    finding_ids: tuple[str, ...]

    def threats_by_category(self, category: str) -> tuple[ThreatScenario, ...]:
        """Return threats in stable source order for one category."""
        return tuple(threat for threat in self.threats if threat.category == category)

    def controls_by_owner(self, owner_role: str) -> tuple[SecurityControl, ...]:
        """Return controls in stable source order for one owner role."""
        return tuple(control for control in self.controls if control.owner_role == owner_role)

    def mappings_for_jurisdiction(self, jurisdiction_id: str) -> tuple[RegulatoryMapping, ...]:
        """Return mappings in stable source order for one jurisdiction."""
        return tuple(
            mapping
            for mapping in self.regulatory_mappings
            if mapping.jurisdiction_id == jurisdiction_id
        )
