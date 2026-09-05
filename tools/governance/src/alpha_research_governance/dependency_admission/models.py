"""Immutable values for dependency admission and signal assessment.

Normal construction enforces strict field types and the explicit ``Field`` and
``Literal`` constraints below. The admission loader and wheel-evidence APIs check
policy scope, dates, paths, digests and attestations; these records perform no I/O.
"""

from __future__ import annotations

# standard library imports
from datetime import date
from typing import Annotated, Literal

# third party library imports
from pydantic import Field

# project library imports
from alpha_research_governance._models import ImmutableModel


class DependencyAdmissionError(ValueError):
    """Report dependency-admission findings in their supplied order.

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


class PythonPackageAdmission(ImmutableModel):
    """Declare admission of one exact external Python package in the uv lock.

    Attributes:
        name: Normalized package name matched against the lock.
        version: Exact admitted version string.
        license_expression: Reviewed license expression for this package.
        native_artifacts: Whether policy identifies the package as containing native code.
    """

    name: str
    version: str
    license_expression: str
    native_artifacts: bool


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SourceArchive(ImmutableModel):
    """Identify an upstream source or build-input archive by revision and bytes.

    Attributes:
        uri: Credential-free HTTPS archive URI containing the immutable revision.
        revision: Full lowercase 40-character hexadecimal source revision.
        sha256: Lowercase 64-character hexadecimal digest of the archive bytes.
        license_expression: Admitted license expression for this source archive.
    """

    uri: str
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    sha256: Sha256
    license_expression: str


class EvidenceFile(ImmutableModel):
    """Identify retained repository-local verification input by path and digest.

    Attributes:
        path: Canonical repository-relative path, checked for symlinks when read.
        sha256: Lowercase 64-character hexadecimal digest expected for the file bytes.
    """

    path: str
    sha256: Sha256


class WheelProvenance(ImmutableModel):
    """Associate one locked wheel with a retained Sigstore attestation bundle.

    Attributes:
        filename: Wheel basename matched to the admitted package and version.
        sha256: Lowercase 64-character hexadecimal digest of the locked wheel bytes.
        bundle: Retained attestation bundle path and expected file digest.
    """

    filename: str
    sha256: Sha256
    bundle: EvidenceFile


class WheelEvidenceAdmission(ImmutableModel):
    """Describe the shared evidence required by the two wheel-admission profiles.

    Attributes:
        name: Exact normalized native-package admission name.
        version: Exact admitted package version.
        owner_role: Governed role accountable for the admission.
        rationale: Admission explanation containing 40 to 2,000 characters.
        sources: Reviewed upstream source and build-input archive identities.
        certificate_identity: Exact HTTPS certificate identity accepted by verification.
        oidc_issuer: Expected HTTPS OIDC issuer for the attestation certificate.
        trusted_root: Retained Sigstore trust-root file and expected digest.
        wheels: Locked wheel identities and their retained attestation bundles.
    """

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
    """Specify authenticated SLSA source evidence for an absent PyPI source archive.

    Inherits package, signer and archive identities from ``WheelEvidenceAdmission``.
    The verifier checks their source-to-wheel binding against these build claims.

    Attributes:
        builder_id: Expected HTTPS builder identity in the SLSA predicate.
        build_type: Expected HTTPS build-definition type in the SLSA predicate.
        build_parameters_sha256: Digest of canonical JSON external and internal parameters.
    """

    builder_id: str
    build_type: str
    build_parameters_sha256: Sha256


class BootstrapWheelAdmission(WheelEvidenceAdmission):
    """Record an explicit source-to-wheel evidence gap for bounded bootstrap use.

    Inherits package, signer and archive identities from ``WheelEvidenceAdmission``.
    Publication authentication does not establish the missing source-to-wheel
    binding. The parser requires review before expiry, with expiry no later than
    30 days after review or the enclosing policy's review deadline.

    Attributes:
        usage: Restricted to ``isolated_development_and_ci``.
        source_to_wheel_binding: Explicitly ``unverified`` for this profile.
        finding_id: Owned ``B07-DEP-NNN`` finding tracking the unresolved binding.
        reviewed_on: Review date, no earlier than the policy assessment date.
        expires_on: Last admitted date of the bounded review window.
        residual_risk: Remaining risk explanation containing 40 to 2,000 characters.
        closure_condition: Required resolution, containing 40 to 2,000 characters.
        source_review: Retained source-review report identity.
        security_review: Retained security-review report identity.
        native_inventory: Retained native-component inventory identity.
        compatibility_report: Retained platform/behavior compatibility report identity.
    """

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
    """Store a repository-owned disposition for an exact package-version finding.

    Attributes:
        vulnerability_id: Scanner finding identifier to which the decision applies.
        package_name: Exact normalized admitted package name.
        affected_version: Exact admitted version covered by the decision.
        disposition: Reviewed treatment of the finding, validated by the policy loader.
        owner_role: Governed role accountable for the decision.
        rationale: Explanation supporting the disposition.
        expires_on: Last admitted date relative to the policy assessment window.
        evidence_url: Retained HTTPS evidence supporting the decision.
    """

    vulnerability_id: str
    package_name: str
    affected_version: str
    disposition: str
    owner_role: str
    rationale: str
    expires_on: date
    evidence_url: str


class EmergencyOverride(ImmutableModel):
    """Record a time-bounded emergency exception for an identified component.

    Attributes:
        override_id: Unique override identifier within the admission policy.
        component_id: Component identity to which the override applies.
        owner_role: Governed role accountable for the exception.
        rationale: Explanation justifying emergency treatment.
        expires_on: Last admitted date relative to the policy assessment window.
        evidence_url: Retained HTTPS evidence supporting the override.
    """

    override_id: str
    component_id: str
    owner_role: str
    rationale: str
    expires_on: date
    evidence_url: str


class DependencyAdmission(ImmutableModel):
    """Store the B07 dependency-admission policy produced by the owning loader.

    Attributes:
        package_status: Declared roadmap completion status.
        successor_package: Roadmap package receiving deferred work.
        as_of_date: Assessment date for signal and exception-window validation.
        review_due_on: Last admitted date of the policy review window.
        pip_audit_version: Exact version of the vulnerability scanner.
        vulnerability_service: Admitted vulnerability service used by the scanner.
        scorecard_version: Exact version of the advisory OpenSSF Scorecard tool.
        maximum_signal_age_days: Maximum accepted Scorecard signal age in days.
        emergency_override_maximum_days: Maximum decision/override lifetime from assessment.
        supported_platforms: Ordered platform identities covered by admission.
        approved_python_indexes: Python package index URLs permitted in the lock.
        lock_paths: Ordered repository-relative lock surfaces requiring digest binding.
        lock_digests: Path/digest pairs in the same order as ``lock_paths``.
        migrated_record_paths: Ordered predecessor dependency records retained for validation.
        runtime_scan_roots: Repository-relative roots scanned for runtime installation calls.
        packages: Exact admitted external Python packages and their license decisions.
        vulnerability_decisions: Owned, expiring dispositions for scanner findings.
        emergency_overrides: Owned, expiring component exceptions.
        applicable_gate_ids: Ordered quality gates required for this package.
        local_evidence_manifest_path: Repository-relative package evidence manifest.
        local_evidence_commit_sha: Commit to which the local evidence is bound.
        open_finding_ids: Declared unresolved package findings.
        wheel_source_admissions: Authenticated source-binding alternatives; empty by default.
        bootstrap_wheel_admissions: Explicit temporary binding gaps; empty by default.
    """

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
