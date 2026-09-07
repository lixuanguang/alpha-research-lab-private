"""Define merge-request and evidence-governance models.

Validation callbacks raise ValueError when called directly. Normal Pydantic
construction and validation report callback failures as ValidationError; owning
loaders translate those failures to their domain error where specified.
"""

from __future__ import annotations

# standard library imports
import re
from datetime import date
from pathlib import Path
from typing import Literal

# third party library imports
from pydantic import field_serializer, field_validator, model_validator

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.change_risk import ChangeRiskInput, ReviewApproval, RiskClass
from alpha_research_governance.operating_model import Operation

_GATE = re.compile(r"^QG(?:0[1-9]|1[0-5])$")
_FINDING_ID = re.compile(r"^(?P<package>[A-L]0[1-8])-F[0-9]{2}$")
_PACKAGE_ID = re.compile(r"^[A-L]0[1-8]$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]*$")


class EvidenceGovernanceError(ValueError):
    """Report ordered evidence-governance findings in one exception.

    Attributes:
        findings: Immutable tuple preserving supplied order and duplicate messages.
    """

    def __init__(self, findings: list[str] | tuple[str, ...]) -> None:
        """Retain the supplied findings and join them into the exception message.

        Args:
            findings: Messages in diagnostic order; copied to a tuple and joined with newlines.
        """
        self.findings = tuple(findings)
        super().__init__("\n".join(self.findings))


class MrField(ImmutableModel):
    """Bind a merge-request field key to its expected Markdown heading.

    The evidence policy loader validates key syntax and heading uniqueness.

    Attributes:
        key: Machine-readable field key.
        heading: Heading text expected by template and merge-request validation.
    """

    key: str
    heading: str


class ConditionalMrField(MrField):
    """Declare an extra merge-request section for detected or declared impact.

    Attributes:
        trigger: Migration, benchmark or operational impact selecting this inherited field.
    """

    trigger: Literal["migration", "benchmark", "operational"]


class MrContext(ImmutableModel):
    """Supply semantic facts that cannot reliably be inferred from filenames.

    Attributes:
        migration: Explicit migration impact, combined with detected impact by the linter.
        benchmark: Explicit benchmark impact, combined with detected impact by the linter.
        operation: Requested operating scope; defaults to implementation.
        change: Optional declared risk facts to classify; absence preserves inferred scope.
    """

    migration: bool = False
    benchmark: bool = False
    operation: Operation = "implementation"
    change: ChangeRiskInput | None = None


class EvidencePolicy(ImmutableModel):
    """Retain repository-local evidence requirements and example paths.

    Construction checks strict field types and lexical relative-path bounds.
    The policy loader verifies gate sets, field uniqueness, example revisions and
    other policy-specific constraints. Paths are not read or resolved by the model.

    Attributes:
        template_path: Repository-relative merge-request template path.
        example_mr_body_path: Repository-relative example body path.
        example_manifest_path: Repository-relative example manifest path.
        example_commit_sha: Commit identity expected for the example manifest.
        applicable_gates: Gate IDs admitted for the policy package.
        mandatory_package_gates: Gate IDs the package must satisfy.
        fields: Ordered baseline merge-request sections.
        package_status: Declared status of the evidence-governance package.
        finding_ids: Retained unresolved governance findings.
        schema_version: Supported policy schema version, 1 or 2; defaults to 1.
        institutional_fields: Version-2 sections for institutional operations.
        conditional_fields: Version-2 sections selected by impact triggers.
        founder_example_mr_body_path: Optional repository-relative founder example path.
    """

    template_path: Path
    example_mr_body_path: Path
    example_manifest_path: Path
    example_commit_sha: str
    applicable_gates: tuple[str, ...]
    mandatory_package_gates: tuple[str, ...]
    fields: tuple[MrField, ...]
    package_status: str
    finding_ids: tuple[str, ...]
    schema_version: Literal[1, 2] = 1
    institutional_fields: tuple[MrField, ...] = ()
    conditional_fields: tuple[ConditionalMrField, ...] = ()
    founder_example_mr_body_path: Path | None = None

    @field_validator(
        "template_path",
        "example_mr_body_path",
        "example_manifest_path",
        "founder_example_mr_body_path",
    )
    @classmethod
    def repository_relative_path(cls, value: Path | None) -> Path | None:
        """Reject absolute paths and explicit parent traversal in policy inputs.

        Args:
            value: Candidate relative Path, or None for the optional founder example.

        Returns:
            The same Path or None after lexical checking; existence and symlinks are not
            resolved.

        Raises:
            ValueError: The path is absolute or contains a .. component.
        """
        if value is not None and (value.is_absolute() or ".." in value.parts):
            raise ValueError("path must stay inside the repository")
        return value


class GateEvidence(ImmutableModel):
    """Carry one quality-gate disposition from a validated manifest.

    The manifest validator checks gate IDs, statuses, rationales and evidence
    references; direct construction checks typed fields only.

    Attributes:
        gate_id: Quality-gate identifier.
        status: Declared gate disposition.
        rationale: Explanation supporting that disposition.
        evidence_ids: Artifact reference IDs supporting the gate.
    """

    gate_id: str
    status: str
    rationale: str
    evidence_ids: tuple[str, ...]


class PackageGateRequirement(ImmutableModel):
    """Require one canonical gate and its expected package-evidence disposition.

    Attributes:
        gate_id: Canonical QG01 through QG15 identifier.
        status: Exact deferred, failed, not_applicable or passed disposition.
    """

    gate_id: str
    status: Literal["deferred", "failed", "not_applicable", "passed"]

    @field_validator("gate_id")
    @classmethod
    def valid_gate_id(cls, value: str) -> str:
        """Require a canonical quality-gate identifier.

        Args:
            value: Exact QG prefix followed by two digits in the range 01 through 15.

        Returns:
            The original gate ID without normalization.

        Raises:
            ValueError: The string is not a canonical QG01-QG15 identifier.
        """
        if _GATE.fullmatch(value) is None:
            raise ValueError("gate_id must be QG01-QG15")
        return value


class PackageEvidenceProfile(ImmutableModel):
    """Define an exact package contract for synthetic local evidence.

    Model validation binds the declared class, unique gate requirements and
    package-local findings. It does not recompute risk or inspect bundle files.
    validate_package_evidence compares these expectations with a validated manifest.

    Attributes:
        roadmap_package_id: Canonical package key: letter A-L and number 01-08.
        accountable_owner_role: Role token expected as the manifest owner.
        risk_class: Expected RiskClass enum member.
        classification_facts: Exact input facts, with declared_class equal to risk_class.
        gate_requirements: Nonempty tuple of requirements with unique gate IDs.
        expected_package_status: Partial, validated or implementation_complete; determines
            the expected bundle status.
        expected_finding_ids: Exact ordered findings; nonempty only for partial profiles,
            unique and package-local.
        approvals_permitted: Whether the manifest may contain approval records.
        waivers_permitted: Whether the manifest may contain waived controls.
        additional_required_gates_permitted: Whether the manifest may declare additional
            required gates.
    """

    roadmap_package_id: str
    accountable_owner_role: str
    risk_class: RiskClass
    classification_facts: ChangeRiskInput
    gate_requirements: tuple[PackageGateRequirement, ...]
    expected_package_status: Literal["partial", "validated", "implementation_complete"]
    expected_finding_ids: tuple[str, ...]
    approvals_permitted: bool
    waivers_permitted: bool
    additional_required_gates_permitted: bool

    @field_validator("roadmap_package_id")
    @classmethod
    def valid_package_id(cls, value: str) -> str:
        """Require a canonical roadmap package identifier.

        Args:
            value: Exact uppercase letter A through L followed by 01 through 08.

        Returns:
            The original package ID without checking roadmap membership.

        Raises:
            ValueError: The string does not match the supported package-ID syntax.
        """
        if _PACKAGE_ID.fullmatch(value) is None:
            raise ValueError("roadmap_package_id must be A01-L08")
        return value

    @field_validator("accountable_owner_role")
    @classmethod
    def valid_owner_role(cls, value: str) -> str:
        """Require the same role syntax used by evidence manifests.

        Args:
            value: ASCII lowercase initial letter, followed by lowercase letters, digits or
                underscores.

        Returns:
            The original role token without checking role-catalog membership.

        Raises:
            ValueError: The string does not match the owner-role syntax.
        """
        if _ROLE.fullmatch(value) is None:
            raise ValueError("accountable_owner_role must be lower_snake_case")
        return value

    @model_validator(mode="after")
    def coherent_profile(self) -> PackageEvidenceProfile:
        """Reject ambiguous or internally inconsistent profile bindings.

        Returns:
            This profile after checking gates, declared class, package status and finding IDs.

        Raises:
            ValueError: Gates are empty or repeated, the declared class disagrees, findings are
                duplicated or belong to another package, or findings disagree with
                partial/completed status.
        """
        gate_ids = tuple(requirement.gate_id for requirement in self.gate_requirements)
        if not gate_ids or len(gate_ids) != len(set(gate_ids)):
            raise ValueError("gate_requirements must contain unique gates")
        if self.classification_facts.declared_class is not self.risk_class:
            raise ValueError("classification_facts.declared_class must match risk_class")
        if len(self.expected_finding_ids) != len(set(self.expected_finding_ids)):
            raise ValueError("expected_finding_ids must contain unique values")
        if self.expected_package_status == "partial" and not self.expected_finding_ids:
            raise ValueError("partial package profiles require expected_finding_ids")
        if self.expected_package_status != "partial" and self.expected_finding_ids:
            raise ValueError("completed package profiles cannot retain expected_finding_ids")
        for finding_id in self.expected_finding_ids:
            matched = _FINDING_ID.fullmatch(finding_id)
            if matched is None or matched.groups(default="")[0] != self.roadmap_package_id:
                raise ValueError(
                    "expected_finding_ids must be canonical IDs belonging to roadmap_package_id"
                )
        return self


class ArtifactEvidence(ImmutableModel):
    """Retain a bundle artifact reference and its claimed digest.

    The manifest validator checks path containment, file bytes and SHA-256.
    Constructing this record alone performs no filesystem or digest validation.

    Attributes:
        evidence_id: Artifact reference key used by gates.
        artifact_type: Declared artifact category.
        path: Artifact path relative to the bundle manifest directory.
        sha256: Expected SHA-256 digest of the file bytes.
    """

    evidence_id: str
    artifact_type: str
    path: str
    sha256: str


class ApprovalEvidence(ImmutableModel):
    """Retain approval claims and their commit/evidence references.

    The manifest validator checks approval status, commit binding and evidence
    URL before using this record for acceptance. Construction validates types
    only; role serialization sorts the set without changing the claimed identity.

    Attributes:
        reviewer_id: Claimed reviewer identity.
        roles: Claimed reviewer-role set.
        independent: Claim that the review is independent.
        is_author: Whether the reviewer is the change author.
        status: Declared approval disposition.
        commit_sha: Commit against which approval was recorded.
        evidence_url: Reference to retained approval evidence.
    """

    reviewer_id: str
    roles: frozenset[str]
    independent: bool
    is_author: bool
    status: str
    commit_sha: str
    evidence_url: str

    @field_serializer("roles", when_used="json")
    def sorted_roles(self, roles: frozenset[str]) -> tuple[str, ...]:
        """Serialize an unordered immutable set deterministically.

        Python-mode serialization retains the frozenset; the source set is unchanged.

        Args:
            roles: Role identifiers supplied to the JSON serializer.

        Returns:
            A lexicographically sorted tuple, represented as an array in JSON mode.
        """
        return tuple(sorted(roles))

    def as_review_approval(self) -> ReviewApproval:
        """Project identity and role claims into a change-risk approval record.

        The projection does not inspect status, commit_sha or evidence_url. Callers
        must validate those evidence bindings before using the result for acceptance.

        Returns:
            A fresh ReviewApproval carrying reviewer_id, roles, independent and is_author.
        """
        return ReviewApproval(
            reviewer_id=self.reviewer_id,
            roles=self.roles,
            independent=self.independent,
            is_author=self.is_author,
        )


class EvidenceManifest(ImmutableModel):
    """Retain typed manifest contents returned by evidence validation.

    Use validate_manifest for revision binding, recomputed risk, gate coverage,
    artifact digests, approvals and operation-specific acceptance. Direct model
    construction enforces field types but does not perform those external checks.

    Attributes:
        bundle_id: Identity of the evidence bundle.
        roadmap_id: Roadmap package to which the evidence belongs.
        commit_sha: Commit identity against which evidence is bound.
        owner_role: Accountable role named by the manifest.
        risk_class: Declared class string, checked against recomputed risk by the validator.
        evidence_retention_class: Declared retention-policy token.
        additional_required_gates: Additional quality gates declared by the bundle.
        bundle_status: Partial, accepted or implementation_accepted disposition, checked by
            the validator.
        waived_controls: Declared waived control IDs.
        open_finding_ids: Ordered unresolved finding IDs.
        change: Typed classification facts for the change.
        gates: Gate dispositions and evidence references.
        artifacts: Artifact references and claimed digests.
        approvals: Approval claims and retained evidence references.
        schema_version: Manifest schema version; defaults to 1.
        operating_domain: Version-2 domain used for local implementation acceptance.
        accepted_by: Version-2 accepting principal.
        accepted_on: Version-2 acceptance date used to resolve effective operating rules.
    """

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
    schema_version: Literal[1, 2] = 1
    operating_domain: str | None = None
    accepted_by: str | None = None
    accepted_on: date | None = None
