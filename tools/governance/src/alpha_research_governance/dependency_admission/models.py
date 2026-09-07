"""Immutable records for the frozen dependency and native evidence boundary.

The package keeps only records consumed by the current lock validator: exact
package admissions and the bounded QuantLib publication evidence. Retired
Scorecard, vulnerability-waiver, emergency-override, and source-bound wheel
profiles are intentionally absent from this contract.
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
    """Report ordered dependency-boundary findings as one domain exception.

    Attributes:
        findings: Immutable snapshot of supplied diagnostics, including duplicates.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Capture ordered diagnostics and expose their joined message.

        Args:
            findings: Ordered diagnostic messages. Empty input is allowed so a
                caller can preserve the same error boundary while assembling findings.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PythonPackageAdmission(ImmutableModel):
    """Declare one exact locked package, license, and native-artifact requirement."""

    name: str
    version: str
    license_expression: str
    native_artifacts: bool


class SourceArchive(ImmutableModel):
    """Identify reviewed source bytes by credential-free URI, revision, and digest."""

    uri: str
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    sha256: Sha256
    license_expression: str


class EvidenceFile(ImmutableModel):
    """Identify repository-local evidence by canonical relative path and digest."""

    path: str
    sha256: Sha256


class WheelProvenance(ImmutableModel):
    """Bind one locked wheel identity to its publication attestation bundle."""

    filename: str
    sha256: Sha256
    bundle: EvidenceFile


class BootstrapWheelAdmission(ImmutableModel):
    """Record bounded publication evidence for the unresolved QuantLib exception.

    The record binds reviewed source identities, publisher/trust identities, all
    locked wheels, four review reports, and the inclusive development-only window.
    """

    name: str
    version: str
    rationale: Annotated[str, Field(min_length=40, max_length=2000)]
    sources: tuple[SourceArchive, ...]
    certificate_identity: str
    oidc_issuer: str
    trusted_root: EvidenceFile
    wheels: tuple[WheelProvenance, ...]
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


class DependencyAdmission(ImmutableModel):
    """Store policy dates, package facts, lock digests, and native evidence."""

    schema_version: int
    as_of_date: date
    review_due_on: date
    lock_digests: tuple[tuple[str, str], ...]
    packages: tuple[PythonPackageAdmission, ...]
    bootstrap_wheel_admissions: tuple[BootstrapWheelAdmission, ...] = ()
