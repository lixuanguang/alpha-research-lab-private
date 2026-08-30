"""Domain models for A05 merge-request and evidence governance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alpha_research.change_risk import ChangeRiskInput, ReviewApproval


class EvidenceGovernanceError(ValueError):
    """Report one or more deterministic A05 validation findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


@dataclass(frozen=True)
class MrField:
    """One required merge-request field and its Markdown heading."""

    key: str
    heading: str


@dataclass(frozen=True)
class EvidencePolicy:
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


@dataclass(frozen=True)
class GateEvidence:
    """One quality-gate disposition in an evidence manifest."""

    gate_id: str
    status: str
    rationale: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactEvidence:
    """One immutable bundle artifact reference."""

    evidence_id: str
    artifact_type: str
    path: str
    sha256: str


@dataclass(frozen=True)
class ApprovalEvidence:
    """One retained approval record bound to the manifest commit."""

    reviewer_id: str
    roles: frozenset[str]
    independent: bool
    is_author: bool
    status: str
    commit_sha: str
    evidence_url: str

    def as_review_approval(self) -> ReviewApproval:
        """Return the A04 approval view used for accepted-bundle enforcement."""
        return ReviewApproval(
            reviewer_id=self.reviewer_id,
            roles=self.roles,
            independent=self.independent,
            is_author=self.is_author,
        )


@dataclass(frozen=True)
class EvidenceManifest:
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
