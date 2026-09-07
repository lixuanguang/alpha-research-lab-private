"""Immutable values for B08 artifact supply-chain controls.

Construction checks field types through ``ImmutableModel``. Policy admission,
file digests and signature verification belong to the policy and bundle APIs;
constructing these records performs no I/O or cryptographic verification.
"""

from __future__ import annotations

# standard library imports
from datetime import date

# project library imports
from alpha_research_governance._models import ImmutableModel


class ArtifactSupplyChainError(ValueError):
    """Report artifact findings in their supplied order.

    Attributes:
        findings: Immutable snapshot of the supplied messages, including duplicates.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Capture findings and join them with newlines for the exception message.

        Args:
            findings: Ordered diagnostic messages; an empty sequence is permitted.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class LockIdentity(ImmutableModel):
    """Identify the expected bytes of one repository lock.

    Attributes:
        path: Repository-relative lockfile path.
        sha256: Expected lowercase hexadecimal SHA-256 digest of the complete file.
    """

    path: str
    sha256: str


class ArtifactTool(ImmutableModel):
    """Declare one exact externally executed artifact tool.

    Attributes:
        command: Executable name resolved by the artifact operations.
        version: Exact version required before execution.
    """

    command: str
    version: str


class ArtifactSupplyChainPolicy(ImmutableModel):
    """Store the B08 policy admitted by the artifact policy loader.

    Attributes:
        package_status: Declared roadmap completion status.
        successor_package: Roadmap package receiving deferred work.
        as_of_date: Policy assessment date used for review-window checks.
        review_due_on: Last admitted date of the policy review window.
        supported_artifact_kinds: Permitted archive formats for whole-artifact bundles.
        native_library_markers: Filename suffixes or infixes identifying native libraries.
        maximum_artifact_bytes: Inclusive upper bound on artifact file size in bytes.
        maximum_archive_members: Inclusive upper bound on inspected archive members.
        statement_type: Required in-toto statement type identifier.
        provenance_predicate_type: Required provenance predicate type identifier.
        spdx_version: Required SPDX version for the generated SBOM.
        builder_id: Expected builder identity in provenance.
        build_type: Expected build definition type in provenance.
        source_repository: Canonical source repository URI bound into provenance.
        signer_identity: Exact certificate identity accepted for bundle signatures.
        oidc_issuer: Expected certificate OIDC issuer.
        trusted_signing_context: CI context permitted to request signing.
        signing_environment: Ordered environment-variable names and required values.
        revoked_signer_identities: Signer identities rejected even if otherwise trusted.
        project_path: Repository-relative project manifest path used by the uv build.
        project_sha256: Expected SHA-256 digest of the project manifest.
        locks: Ordered lockfile identities bound into provenance.
        syft: Executable and version used to generate the SBOM.
        cosign: Executable and version used for signing and verification.
        applicable_gate_ids: Ordered quality gates required for this package.
        local_evidence_manifest_path: Repository-relative package evidence manifest.
        local_evidence_commit_sha: Commit to which the local evidence is bound.
        open_finding_ids: Declared unresolved package findings.
    """

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
    project_path: str
    project_sha256: str
    locks: tuple[LockIdentity, ...]
    syft: ArtifactTool
    cosign: ArtifactTool
    applicable_gate_ids: tuple[str, ...]
    local_evidence_manifest_path: str
    local_evidence_commit_sha: str
    open_finding_ids: tuple[str, ...]


class ArtifactBundle(ImmutableModel):
    """Summarize a prepared or verified whole-artifact bundle.

    Preparation returns this record before signing. Its presence alone does not
    establish signature validity; consumer acceptance uses ``verify_bundle``.

    Attributes:
        artifact_name: Archive filename recorded in the bundle manifest.
        artifact_kind: Supported archive format, such as a wheel or source archive.
        artifact_sha256: SHA-256 digest of the complete artifact file.
        source_commit: Source revision bound into the bundle's build identity.
        build_command: Canonical uv build command recorded for the artifact.
        build_platform: Declared platform on which the artifact was built.
        manifest_sha256: SHA-256 digest of the bundle manifest bytes.
    """

    artifact_name: str
    artifact_kind: str
    artifact_sha256: str
    source_commit: str
    build_command: str
    build_platform: str
    manifest_sha256: str
