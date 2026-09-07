"""Typed records used by the repository dependency boundary.

The records describe bytes, package versions, and the one retained native
dependency exception.  They do not model review roles, package-roadmap state,
or evidence workflow state; those concerns are outside this small boundary.
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
        """Capture ordered diagnostics and expose them as one exception message.

        Args:
            findings: Ordered diagnostic messages. Empty input is allowed so callers can
                construct an error while preserving a common error boundary.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PythonPackageAdmission(ImmutableModel):
    """Declare one exact package, license, and native-artifact classification.

    Attributes:
        name: Normalized package name as it appears in ``uv.lock``.
        version: Exact locked version.
        license_expression: License expression accepted for the package.
        native_artifacts: Whether platform-specific wheel coverage is required.
    """

    name: str
    version: str
    license_expression: str
    native_artifacts: bool


class SourceArchive(ImmutableModel):
    """Identify a source archive by immutable revision and byte digest.

    Attributes:
        uri: Credential-free HTTPS archive URI containing ``revision``.
        revision: Full lowercase Git revision.
        sha256: Lowercase SHA-256 digest of the archive bytes.
        license_expression: License expression accepted for the archive.
    """

    uri: str
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    sha256: Sha256
    license_expression: str


class EvidenceFile(ImmutableModel):
    """Identify a repository-local file retained for native source evidence.

    Attributes:
        path: Canonical repository-relative path.
        sha256: Lowercase SHA-256 digest expected for the file bytes.
    """

    path: str
    sha256: Sha256


class WheelProvenance(ImmutableModel):
    """Bind one locked wheel to its retained attestation bundle.

    Attributes:
        filename: Wheel basename from the lock.
        sha256: Lowercase SHA-256 digest named by the lock.
        bundle: Repository-local attestation bundle identity.
    """

    filename: str
    sha256: Sha256
    bundle: EvidenceFile


class WheelEvidenceAdmission(ImmutableModel):
    """Describe retained evidence for a native package wheel set.

    Attributes:
        name: Exact normalized package name.
        version: Exact package version.
        rationale: Explanation of why native wheel evidence is retained.
        sources: Reviewed upstream source and build-input archives.
        certificate_identity: Certificate identity accepted by Cosign.
        oidc_issuer: OIDC issuer accepted by Cosign.
        trusted_root: Retained Sigstore trust-root identity.
        wheels: Locked wheel identities and their attestation bundles.
    """

    name: str
    version: str
    rationale: Annotated[str, Field(min_length=40, max_length=2000)]
    sources: tuple[SourceArchive, ...]
    certificate_identity: str
    oidc_issuer: str
    trusted_root: EvidenceFile
    wheels: tuple[WheelProvenance, ...]


class WheelSourceAdmission(WheelEvidenceAdmission):
    """Specify authenticated SLSA source-to-wheel evidence."""

    builder_id: str
    build_type: str
    build_parameters_sha256: Sha256


class BootstrapWheelAdmission(WheelEvidenceAdmission):
    """Record the bounded QuantLib source-to-wheel exception.

    Attributes:
        usage: The only permitted use of this unresolved admission.
        source_to_wheel_binding: Explicit unresolved provenance state.
        finding_id: Stable identifier for the retained exception.
        reviewed_on: First date on which the exception is effective.
        expires_on: Last date on which isolated development and CI may use it.
        residual_risk: Remaining source-to-wheel uncertainty.
        closure_condition: Evidence needed before release use can be enabled.
        source_review: Source-review report identity.
        security_review: Security-review report identity.
        native_inventory: Native-component inventory identity.
        compatibility_report: Compatibility report identity.
    """

    usage: Literal["isolated_development_and_ci"]
    source_to_wheel_binding: Literal["unverified"]
    finding_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9._-]{2,63}$")]
    reviewed_on: date
    expires_on: date
    residual_risk: Annotated[str, Field(min_length=40, max_length=2000)]
    closure_condition: Annotated[str, Field(min_length=40, max_length=2000)]
    source_review: EvidenceFile
    security_review: EvidenceFile
    native_inventory: EvidenceFile
    compatibility_report: EvidenceFile


class VulnerabilityDecision(ImmutableModel):
    """Store a time-bounded disposition for one package-version finding."""

    vulnerability_id: str
    package_name: str
    affected_version: str
    disposition: str
    rationale: str
    expires_on: date
    evidence_url: str


class EmergencyOverride(ImmutableModel):
    """Store a time-bounded exception for a concrete locked component."""

    override_id: str
    component_id: str
    rationale: str
    expires_on: date
    evidence_url: str


class DependencyAdmission(ImmutableModel):
    """Store the compact frozen dependency policy.

    Attributes:
        schema_version: Version of this policy's machine-readable shape.
        as_of_date: Date on which the policy was assessed.
        review_due_on: Last date for the current admission review.
        pip_audit_version: Exact scanner version used for the locked graph.
        vulnerability_service: Scanner service name.
        scorecard_version: Exact advisory Scorecard version.
        maximum_signal_age_days: Maximum age of an advisory Scorecard signal.
        supported_platforms: Platform tags covered by locked wheel checks.
        approved_python_indexes: Exact package indexes allowed by the lock.
        lock_paths: Repository-relative lock files covered by digest binding.
        lock_digests: Ordered lock path and SHA-256 pairs.
        runtime_scan_roots: Source roots checked for runtime installation commands.
        packages: Exact admitted package versions and license/native facts.
        vulnerability_decisions: Expiring dispositions for scanner findings.
        emergency_overrides: Expiring concrete dependency exceptions.
        wheel_source_admissions: Authenticated native wheel evidence.
        bootstrap_wheel_admissions: Bounded unresolved native wheel evidence.
    """

    schema_version: int
    as_of_date: date
    review_due_on: date
    pip_audit_version: str
    vulnerability_service: str
    scorecard_version: str
    maximum_signal_age_days: int
    supported_platforms: tuple[str, ...]
    approved_python_indexes: tuple[str, ...]
    lock_paths: tuple[str, ...]
    lock_digests: tuple[tuple[str, str], ...]
    runtime_scan_roots: tuple[str, ...]
    packages: tuple[PythonPackageAdmission, ...]
    vulnerability_decisions: tuple[VulnerabilityDecision, ...]
    emergency_overrides: tuple[EmergencyOverride, ...]
    wheel_source_admissions: tuple[WheelSourceAdmission, ...] = ()
    bootstrap_wheel_admissions: tuple[BootstrapWheelAdmission, ...] = ()
