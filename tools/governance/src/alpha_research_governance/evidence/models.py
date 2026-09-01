"""Define merge-request and evidence-governance models."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import field_serializer, field_validator, model_validator

from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.change_risk import ChangeRiskInput, ReviewApproval, RiskClass

_GATE = re.compile(r"^QG(?:0[1-9]|1[0-5])$")
_FINDING_ID = re.compile(r"^(?P<package>[A-L]0[1-8])-F[0-9]{2}$")
_PACKAGE_ID = re.compile(r"^[A-L]0[1-8]$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")


class EvidenceGovernanceError(ValueError):
    """Report one or more deterministic evidence-governance findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class MrField(ImmutableModel):
    """One required merge-request field and its Markdown heading."""

    key: str
    heading: str


class EvidencePolicy(ImmutableModel):
    """Authoritative repository-local evidence policy."""

    template_path: Path
    example_mr_body_path: Path
    example_manifest_path: Path
    example_commit_sha: str
    applicable_gates: tuple[str, ...]
    mandatory_package_gates: tuple[str, ...]
    fields: tuple[MrField, ...]
    package_status: str
    finding_ids: tuple[str, ...]

    @field_validator("template_path", "example_mr_body_path", "example_manifest_path")
    @classmethod
    def repository_relative_path(cls, value: Path) -> Path:
        """Reject paths that cannot represent repository-contained policy inputs."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("path must stay inside the repository")
        return value


class GateEvidence(ImmutableModel):
    """One quality-gate disposition in an evidence manifest."""

    gate_id: str
    status: str
    rationale: str
    evidence_ids: tuple[str, ...]


class PackageGateRequirement(ImmutableModel):
    """Required disposition for one gate in a package-evidence profile."""

    gate_id: str
    status: Literal["deferred", "failed", "not_applicable", "passed"]

    @field_validator("gate_id")
    @classmethod
    def valid_gate_id(cls, value: str) -> str:
        """Require a canonical quality-gate identifier."""
        if _GATE.fullmatch(value) is None:
            raise ValueError("gate_id must be QG01-QG15")
        return value


class PackageEvidenceProfile(ImmutableModel):
    """Exact package contract for validating synthetic local evidence."""

    roadmap_package_id: str
    accountable_owner_role: str
    risk_class: RiskClass
    classification_facts: ChangeRiskInput
    gate_requirements: tuple[PackageGateRequirement, ...]
    expected_package_status: Literal["partial", "validated"]
    expected_finding_ids: tuple[str, ...]
    approvals_permitted: bool
    waivers_permitted: bool
    additional_required_gates_permitted: bool

    @field_validator("roadmap_package_id")
    @classmethod
    def valid_package_id(cls, value: str) -> str:
        """Require a canonical roadmap package identifier."""
        if _PACKAGE_ID.fullmatch(value) is None:
            raise ValueError("roadmap_package_id must be A01-L08")
        return value

    @field_validator("accountable_owner_role")
    @classmethod
    def valid_owner_role(cls, value: str) -> str:
        """Require the same role syntax used by evidence manifests."""
        if _ROLE.fullmatch(value) is None:
            raise ValueError("accountable_owner_role must be lower_snake_case")
        return value

    @model_validator(mode="after")
    def coherent_profile(self) -> PackageEvidenceProfile:
        """Reject ambiguous or internally inconsistent profile bindings."""
        gate_ids = tuple(requirement.gate_id for requirement in self.gate_requirements)
        if not gate_ids or len(gate_ids) != len(set(gate_ids)):
            raise ValueError("gate_requirements must contain unique gates")
        if self.classification_facts.declared_class is not self.risk_class:
            raise ValueError("classification_facts.declared_class must match risk_class")
        if len(self.expected_finding_ids) != len(set(self.expected_finding_ids)):
            raise ValueError("expected_finding_ids must contain unique values")
        if self.expected_package_status == "partial" and not self.expected_finding_ids:
            raise ValueError("partial package profiles require expected_finding_ids")
        if self.expected_package_status == "validated" and self.expected_finding_ids:
            raise ValueError("validated package profiles cannot retain expected_finding_ids")
        if any(
            (matched := _FINDING_ID.fullmatch(finding_id)) is None
            or matched.group("package") != self.roadmap_package_id
            for finding_id in self.expected_finding_ids
        ):
            raise ValueError(
                "expected_finding_ids must be canonical IDs belonging to roadmap_package_id"
            )
        return self


class ArtifactEvidence(ImmutableModel):
    """One immutable bundle artifact reference."""

    evidence_id: str
    artifact_type: str
    path: str
    sha256: str


class ApprovalEvidence(ImmutableModel):
    """One retained approval record bound to the manifest commit."""

    reviewer_id: str
    roles: frozenset[str]
    independent: bool
    is_author: bool
    status: str
    commit_sha: str
    evidence_url: str

    @field_serializer("roles", when_used="json")
    def sorted_roles(self, roles: frozenset[str]) -> tuple[str, ...]:
        """Serialize an unordered immutable set deterministically."""
        return tuple(sorted(roles))

    def as_review_approval(self) -> ReviewApproval:
        """Return the change-risk approval view used for accepted-bundle enforcement."""
        return ReviewApproval(
            reviewer_id=self.reviewer_id,
            roles=self.roles,
            independent=self.independent,
            is_author=self.is_author,
        )


class EvidenceManifest(ImmutableModel):
    """Validated, SHA-bound evidence-manifest contents."""

    bundle_id: str
    roadmap_id: str
    commit_sha: str
    owner_role: str
    risk_class: str
    evidence_retention_class: str
    additional_required_gates: tuple[str, ...]
    bundle_status: str
    waived_controls: tuple[str, ...]
    open_finding_ids: tuple[str, ...]
    change: ChangeRiskInput
    gates: tuple[GateEvidence, ...]
    artifacts: tuple[ArtifactEvidence, ...]
    approvals: tuple[ApprovalEvidence, ...]
