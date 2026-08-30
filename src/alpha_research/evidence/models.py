"""Domain models for A05 merge-request and evidence governance."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_serializer, field_validator

from alpha_research._models import ImmutableModel
from alpha_research.change_risk import ChangeRiskInput, ReviewApproval


class EvidenceGovernanceError(ValueError):
    """Report one or more deterministic A05 validation findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class MrField(ImmutableModel):
    """One required merge-request field and its Markdown heading."""

    key: str
    heading: str


class EvidencePolicy(ImmutableModel):
    """Authoritative repository-local A05 policy."""

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
        """Return the A04 approval view used for accepted-bundle enforcement."""
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
