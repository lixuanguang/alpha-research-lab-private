"""Typed records for the retained build artifact boundary."""

from __future__ import annotations

# project library imports
from alpha_research_governance._models import ImmutableModel


class ArtifactSupplyChainError(ValueError):
    """Report artifact-boundary findings in their supplied order."""

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Capture ordered artifact diagnostics.

        Args:
            findings: Ordered diagnostic messages.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class LockIdentity(ImmutableModel):
    """Identify expected bytes of one repository lock file."""

    path: str
    sha256: str


class ArtifactTool(ImmutableModel):
    """Declare one exact executable used to inspect or sign an artifact."""

    command: str
    version: str


class ArtifactSupplyChainPolicy(ImmutableModel):
    """Store artifact format, provenance, signing, and lock identities.

    The policy contains only facts consumed by bundle creation and verification.
    Release status is determined by dependency admission at operation time.
    """

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
    project_path: str
    project_sha256: str
    locks: tuple[LockIdentity, ...]
    syft: ArtifactTool
    cosign: ArtifactTool


class ArtifactBundle(ImmutableModel):
    """Summarize a prepared or verified content-addressed artifact bundle."""

    artifact_name: str
    artifact_kind: str
    artifact_sha256: str
    source_commit: str
    build_command: str
    build_platform: str
    manifest_sha256: str
