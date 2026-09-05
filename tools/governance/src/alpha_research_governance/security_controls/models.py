"""Define domain models for the threat and regulatory control map.

These immutable records and serializers perform no file or network I/O.
Registry loading establishes cross-record references, policy constraints and
evidence consistency; direct construction validates strict field types only.
"""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class SecurityControlError(ValueError):
    """Report ordered security-control findings in one exception.

    Attributes:
        findings: Immutable tuple preserving supplied diagnostic order and duplicates.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Retain findings and join them into the exception message.

        Args:
            findings: Messages copied to a tuple and joined with newlines, without sorting.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class ProtectedAsset(ImmutableModel):
    """Identify a governed asset or authority and its security objectives.

    Attributes:
        asset_id: Asset key used by boundaries and threats.
        name: Human-readable asset name.
        owner_role: Role accountable for protecting the asset.
        security_objectives: Declared objectives in source order.
    """

    asset_id: str
    name: str
    owner_role: str
    security_objectives: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with security_objectives copied to a list.
            Source order and scalar values are preserved; no JSON text is encoded.
        """
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "owner_role": self.owner_role,
            "security_objectives": list(self.security_objectives),
        }


class TrustBoundary(ImmutableModel):
    """Describe a declared change in trust, authority or security zone.

    Attributes:
        boundary_id: Boundary key used by threat scenarios.
        name: Human-readable boundary name.
        source_zone: Zone from which the interaction originates.
        destination_zone: Zone entered by the interaction; the loader checks that zones
            differ.
        asset_ids: Assets affected by the crossing.
        trust_change: Explanation of the authority or trust transition.
        owner_role: Role accountable for the boundary.
        control_ids: Controls assigned to the boundary.
    """

    boundary_id: str
    name: str
    source_zone: str
    destination_zone: str
    asset_ids: tuple[str, ...]
    trust_change: str
    owner_role: str
    control_ids: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with asset_ids and control_ids copied to
            lists. Source order and scalar values are preserved; no JSON text is encoded.
        """
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


class ThreatScenario(ImmutableModel):
    """Bind an abuse scenario to affected assets, boundaries and controls.

    Attributes:
        threat_id: Stable threat key.
        title: Human-readable threat title.
        category: Exact threat-category token used by category queries.
        actor: Declared actor or actor class.
        abuse_case: Sequence or misuse represented by the scenario.
        impact: Declared consequence of successful abuse.
        boundary_ids: Affected trust boundaries.
        asset_ids: Affected protected assets.
        control_ids: Controls mapped to the scenario.
        owner_role: Role accountable for the threat record.
    """

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
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with asset_ids, boundary_ids and control_ids
            copied to lists. Source order and scalar values are preserved; no JSON text is
            encoded.
        """
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


class SecurityControl(ImmutableModel):
    """Describe an owned control and the evidence expected to support it.

    The control-map loader checks role independence, supported functions and
    status/evidence consistency. This record does not execute the test procedure
    or establish that the control operates in a deployed environment.

    Attributes:
        control_id: Stable control key.
        title: Human-readable control title.
        domain: Declared control domain.
        owner_role: Accountable implementation role.
        independent_review_roles: Roles expected to review independently of the owner.
        objective: Security outcome the control is intended to achieve.
        control_functions: Declared prevent, detect, respond or recover functions.
        implementation_packages: Roadmap packages expected to implement the control.
        implementation_status: Declared planned or repository_local implementation state.
        test_procedure: Procedure for checking the control.
        fail_safe_response: Specified response when the control check fails.
        evidence_source_ids: Evidence sources used to support the declared state.
    """

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
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with control_functions,
            implementation_packages, independent_review_roles and evidence_source_ids copied to
            lists. Source order and scalar values are preserved; no JSON text is encoded.
        """
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


class EvidenceSource(ImmutableModel):
    """Describe available control evidence or its explicit deferral requirements.

    The loader requires available evidence to name a repository file, with no
    future packages or closure condition. Deferred evidence names prerequisites
    and a closure condition, with no location. Construction does not inspect files.

    Attributes:
        evidence_source_id: Evidence-source key used by controls and mappings.
        name: Human-readable evidence name.
        source_type: Declared evidence category token.
        status: available or deferred disposition checked by the loader.
        owner_role: Role responsible for producing or retaining evidence.
        location: Repository-relative file path for available evidence, otherwise empty.
        required_packages: Future prerequisite packages for deferred evidence.
        closure_condition: What must be established to resolve the deferral.
    """

    evidence_source_id: str
    name: str
    source_type: str
    status: str
    owner_role: str
    location: str
    required_packages: tuple[str, ...]
    closure_condition: str

    def as_json(self) -> dict[str, object]:
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with required_packages copied to a list.
            Source order and scalar values are preserved; no JSON text is encoded.
        """
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


class AuthoritySource(ImmutableModel):
    """Record an authority citation and its declared verification date.

    The loader checks source class, trusted URL shape and verification age.
    Constructing or serializing the record does not fetch the source or determine
    legal applicability.

    Attributes:
        source_id: Authority-source key used by profiles and mappings.
        jurisdiction_id: Jurisdiction or reference scope to which the source is assigned.
        authority: Named issuing authority.
        title: Source title.
        citation: Citation identifying the referenced material.
        source_class: Declared statute, binding_rule, supervisory_guidance or
            reference_framework.
        url: Recorded official source URL.
        last_verified_on: Declared verification date, compared with map as_of_date by the
            loader.
    """

    source_id: str
    jurisdiction_id: str
    authority: str
    title: str
    citation: str
    source_class: str
    url: str
    last_verified_on: date

    def as_json(self) -> dict[str, object]:
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with last_verified_on rendered as ISO
            calendar-date text. Source order and scalar values are preserved; no JSON text is
            encoded.
        """
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


class JurisdictionProfile(ImmutableModel):
    """Retain a jurisdiction scope and its unresolved applicability review.

    Attributes:
        jurisdiction_id: Exact profile key used by source and mapping references.
        name: Human-readable jurisdiction or reference-scope name.
        scope: Declared scope to be assessed.
        applicability_status: Recorded requires_legal_review or reference_only disposition.
        legal_owner_role: Role responsible for the applicability review.
        source_ids: Authority citations assigned to this profile.
        review_due_on: Review date checked against the map snapshot date by the loader.
    """

    jurisdiction_id: str
    name: str
    scope: str
    applicability_status: str
    legal_owner_role: str
    source_ids: tuple[str, ...]
    review_due_on: date

    def as_json(self) -> dict[str, object]:
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with source_ids copied to a list and
            review_due_on rendered as ISO calendar-date text. Source order and scalar values are
            preserved; no JSON text is encoded.
        """
        return {
            "applicability_status": self.applicability_status,
            "jurisdiction_id": self.jurisdiction_id,
            "legal_owner_role": self.legal_owner_role,
            "name": self.name,
            "review_due_on": self.review_due_on.isoformat(),
            "scope": self.scope,
            "source_ids": list(self.source_ids),
        }


class RegulatoryMapping(ImmutableModel):
    """Record a non-conclusive mapping from authority sources to platform controls.

    Attributes:
        mapping_id: Stable mapping key.
        jurisdiction_id: Profile governing the mapping scope and review disposition.
        topic: Topic represented by the mapping.
        source_ids: Authority citations in this jurisdiction.
        control_ids: Platform controls mapped to the cited topic.
        applicability_status: Review disposition expected to match the jurisdiction profile.
        applicability_rationale: Recorded explanation for the applicability disposition.
        owner_role: Role expected to match the profile legal owner.
        evidence_source_ids: Evidence sources supporting the mapping and any required
            review.
    """

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
        """Return the stable JSON-compatible record representation.

        Returns:
            A fresh dictionary of the record fields with source_ids, control_ids and
            evidence_source_ids copied to lists. Source order and scalar values are preserved;
            no JSON text is encoded.
        """
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


class SecurityControlMap(ImmutableModel):
    """Hold the security package records used by control-map queries.

    Use load_control_map to check references, ordering, ownership, status/evidence
    consistency, authority URLs and review dates. Direct construction checks field
    types only. Queries preserve stored order and do not assert control efficacy
    or conclusive legal applicability.

    Attributes:
        schema_version: Control-map schema version.
        roadmap_package: Roadmap package owning the capability.
        operating_track: Declared governance operating track.
        accountable_owner_role: Role accountable for the map.
        risk_class: Declared package risk class.
        dependency_package_ids: Prerequisite roadmap packages.
        applicable_gate_ids: Quality gates applicable to the capability.
        as_of_date: Snapshot date used for verification-age and review-deadline checks.
        package_status: Declared status of the capability.
        local_evidence_manifest_path: Recorded local evidence manifest path.
        local_evidence_commit_sha: Commit identity used to bind local evidence.
        assets: Protected assets in stored order.
        boundaries: Trust boundaries in stored order.
        threats: Threat scenarios in stored order.
        controls: Control records in stored order.
        evidence_sources: Available or deferred evidence records.
        authority_sources: Authority citations and verification dates.
        jurisdictions: Jurisdiction applicability-review profiles.
        regulatory_mappings: Non-conclusive source/control mappings.
        finding_ids: Retained unresolved security-governance findings.
    """

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
        """Return threats in stored order for one exact category.

        Args:
            category: Case-sensitive category token; no token validation or normalization
                occurs.

        Returns:
            A tuple of stored matching threat objects, or an empty tuple for any unmatched
            token.
        """
        return tuple(threat for threat in self.threats if threat.category == category)

    def controls_by_owner(self, owner_role: str) -> tuple[SecurityControl, ...]:
        """Return controls in stored order for one exact owner role.

        Args:
            owner_role: Case-sensitive role token; role-catalog membership is not checked here.

        Returns:
            A tuple of stored matching controls, or an empty tuple for any unmatched role.
        """
        return tuple(control for control in self.controls if control.owner_role == owner_role)

    def mappings_for_jurisdiction(self, jurisdiction_id: str) -> tuple[RegulatoryMapping, ...]:
        """Return mappings in stored order for one exact jurisdiction.

        Args:
            jurisdiction_id: Case-sensitive jurisdiction key; membership is not checked here.

        Returns:
            A tuple of stored matching mappings, or an empty tuple for any unmatched key.
        """
        return tuple(
            mapping
            for mapping in self.regulatory_mappings
            if mapping.jurisdiction_id == jurisdiction_id
        )
