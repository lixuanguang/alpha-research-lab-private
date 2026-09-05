"""Immutable values for B08 artifact supply-chain controls."""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class ArtifactSupplyChainError(ValueError):
    """Report one or more fail-closed artifact findings."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class LockIdentity(ImmutableModel):
    """One repository lock bound into provenance."""

    path: str
    sha256: str


class ArtifactTool(ImmutableModel):
    """One exact externally executed artifact tool."""

    command: str
    version: str


class ArtifactSupplyChainPolicy(ImmutableModel):
    """Complete repository-local B08 artifact policy."""

    package_status: str
    successor_package: str
    as_of_date: date
    review_due_on: date
    supported_artifact_kinds: tuple[str, ...]
    native_library_markers: tuple[str, ...]
    maximum_artifact_bytes: int
    maximum_archive_members: int
    statement_type: str
    provenance_predicate_type: str
    spdx_version: str
    builder_id: str
    build_type: str
    source_repository: str
    signer_identity: str
    oidc_issuer: str
    trusted_signing_context: str
    signing_environment: tuple[tuple[str, str], ...]
    revoked_signer_identities: tuple[str, ...]
    toolchain_path: str
    toolchain_sha256: str
    locks: tuple[LockIdentity, ...]
    syft: ArtifactTool
    cosign: ArtifactTool
    applicable_gate_ids: tuple[str, ...]
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    open_finding_ids: tuple[str, ...]


class ArtifactBundle(ImmutableModel):
    """Validated metadata from one signed whole-artifact bundle."""

    artifact_name: str
    artifact_kind: str
    artifact_sha256: str
    source_commit: str
    build_target: str
    build_platform: str
    manifest_sha256: str
