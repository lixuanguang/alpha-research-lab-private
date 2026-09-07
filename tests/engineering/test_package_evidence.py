"""Adversarial tests for exact governance package-evidence profiles."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research.change_risk import ChangeRiskInput, RiskClass
from alpha_research.change_risk import load_policy as load_change_risk_policy
from alpha_research.evidence import (
    ApprovalEvidence,
    EvidenceGovernanceError,
    EvidenceManifest,
    GateEvidence,
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "governance"
    / "evidence"
    / "examples"
    / "a06-r2-partial"
    / "manifest.toml"
)
BUILD_GRAPH_MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "governance"
    / "evidence"
    / "examples"
    / "b02-r2-partial"
    / "manifest.toml"
)
DEVELOPER_ENVIRONMENT_MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "governance"
    / "evidence"
    / "examples"
    / "b03-r2-partial"
    / "manifest.toml"
)
CHANGE_POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "change-risk-policy.toml"


def _manifest() -> EvidenceManifest:
    """Load and validate the A06 synthetic partial-R2 evidence manifest.

    Returns:
        The locally checked manifest bound to the expected synthetic commit and change-risk
        policy, including its retained artifact digests.

    Raises:
        ChangeRiskPolicyError: The change-risk policy cannot be loaded or is invalid.
        EvidenceGovernanceError: The fixture, its retained artifacts, or its policy bindings
            fail manifest validation.
        OSError: The policy, manifest, or retained artifact cannot be read.
    """
    return validate_manifest(
        MANIFEST_PATH,
        expected_commit_sha="2" * 40,
        change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
    )


def _profile(manifest: EvidenceManifest) -> PackageEvidenceProfile:
    """Build the exact A06 profile expected by the partial-evidence checks.

    Args:
        manifest: Validated A06 manifest whose change facts and gate IDs are copied into the
            expected profile.

    Returns:
        A profile requiring A06's partial status and three open findings, with approvals,
        waivers, and caller-added gates disallowed.
    """
    return PackageEvidenceProfile(
        roadmap_package_id="A06",
        accountable_owner_role="platform",
        risk_class=RiskClass.R2,
        classification_facts=manifest.change,
        gate_requirements=tuple(
            PackageGateRequirement(gate_id=gate.gate_id, status="passed") for gate in manifest.gates
        ),
        expected_package_status="partial",
        expected_finding_ids=("A06-F01", "A06-F02", "A06-F03"),
        approvals_permitted=False,
        waivers_permitted=False,
        additional_required_gates_permitted=False,
    )


def _copy_manifest_with_updates(manifest: EvidenceManifest, **updates: object) -> EvidenceManifest:
    """Return a schema-valid immutable manifest copy with selected fields replaced.

    Args:
        manifest: EvidenceManifest model to copy without mutating the original.
        updates: Field replacements applied to the round-trip model representation.

    Returns:
        A new EvidenceManifest after model-level validation. This does not rerun
        ``validate_manifest`` file, digest, commit, classification, or policy checks, and
        it does not compare the result with a package profile.

    Raises:
        pydantic.ValidationError: An update does not satisfy the manifest model contract.
    """
    payload: dict[str, object] = {
        "bundle_id": manifest.bundle_id,
        "roadmap_id": manifest.roadmap_id,
        "commit_sha": manifest.commit_sha,
        "owner_role": manifest.owner_role,
        "risk_class": manifest.risk_class,
        "evidence_retention_class": manifest.evidence_retention_class,
        "additional_required_gates": manifest.additional_required_gates,
        "bundle_status": manifest.bundle_status,
        "waived_controls": manifest.waived_controls,
        "open_finding_ids": manifest.open_finding_ids,
        "change": manifest.change,
        "gates": manifest.gates,
        "artifacts": manifest.artifacts,
        "approvals": manifest.approvals,
        "schema_version": manifest.schema_version,
        "operating_domain": manifest.operating_domain,
        "accepted_by": manifest.accepted_by,
        "accepted_on": manifest.accepted_on,
    }
    payload.update(updates)
    return EvidenceManifest.model_validate(payload)


def _wrong_owner(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy with an owner role that disagrees with the A06 profile.

    Args:
        manifest: Manifest model produced by the A06 fixture loader.

    Returns:
        A schema-valid manifest whose owner role is ``security`` for A06 profile drift testing.
    """
    return _copy_manifest_with_updates(manifest, owner_role="security")


def _changed_risk_fact(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy with a changed security classification fact.

    Args:
        manifest: Manifest model produced by the A06 fixture loader.

    Returns:
        A schema-valid manifest whose security privilege is ``shared_sensitive`` and therefore
        differs from the A06 profile's declared risk facts.
    """
    changed = ChangeRiskInput(
        capital_at_risk=manifest.change.capital_at_risk,
        blast_radius=manifest.change.blast_radius,
        data_model_materiality=manifest.change.data_model_materiality,
        security_privilege="shared_sensitive",
        reversibility=manifest.change.reversibility,
        computationally_material=manifest.change.computationally_material,
        economically_or_risk_relevant=manifest.change.economically_or_risk_relevant,
        model_or_trading_relevant=manifest.change.model_or_trading_relevant,
        declared_class=manifest.change.declared_class,
    )
    return _copy_manifest_with_updates(manifest, change=changed)


def _missing_gate(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy omitting the final required quality gate.

    Args:
        manifest: Manifest model produced by the A06 fixture loader with its complete gate set.

    Returns:
        A schema-valid manifest with its last gate removed so the A06 profile's exact gate
        coverage fails.
    """
    return _copy_manifest_with_updates(manifest, gates=manifest.gates[:-1])


def _additional_gate(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy with an unprofiled passed gate appended.

    Args:
        manifest: Manifest model produced by the A06 fixture loader whose first artifact
            supports the synthetic gate.

    Returns:
        A schema-valid manifest with a synthetic QG15 entry that violates the A06 profile's
        exact gate set.
    """
    extra = GateEvidence(
        gate_id="QG15",
        status="passed",
        rationale="Adversarial additional gate.",
        evidence_ids=(manifest.artifacts[0].evidence_id,),
    )
    return _copy_manifest_with_updates(manifest, gates=(*manifest.gates, extra))


def _changed_gate_status(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy changing the first required gate from passed to failed.

    Args:
        manifest: Manifest model produced by the A06 fixture loader with required gates in
            profile order.

    Returns:
        A schema-valid manifest whose first gate status disagrees with the A06 profile.
    """
    first_gate = manifest.gates[0]
    failed_gate = GateEvidence(
        gate_id=first_gate.gate_id,
        status="failed",
        rationale=first_gate.rationale,
        evidence_ids=first_gate.evidence_ids,
    )
    return _copy_manifest_with_updates(manifest, gates=(failed_gate, *manifest.gates[1:]))


def _unexpected_approval(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy containing a pending synthetic approval claim.

    Args:
        manifest: Manifest model produced by the A06 fixture loader, supplying the approval's
            commit binding.

    Returns:
        A schema-valid manifest with a non-independent code-owner approval that the configured
        A06 profile rejects.
    """
    approval = ApprovalEvidence(
        reviewer_id="synthetic-reviewer",
        roles=frozenset({"code_owner"}),
        independent=False,
        is_author=False,
        status="pending",
        commit_sha=manifest.commit_sha,
        evidence_url="",
    )
    return _copy_manifest_with_updates(manifest, approvals=(approval,))


def _waiver(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy declaring a synthetic waived control.

    Args:
        manifest: Manifest model produced by the A06 fixture loader.

    Returns:
        A schema-valid manifest whose ``waived_controls`` is replaced with the one-item tuple
        ``("synthetic-control",)`` that the configured A06 profile rejects.
    """
    return _copy_manifest_with_updates(manifest, waived_controls=("synthetic-control",))


def _caller_additional_gate(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy declaring an additional caller-required gate.

    Args:
        manifest: Manifest model produced by the A06 fixture loader.

    Returns:
        A schema-valid manifest with QG01 declared as an additional required gate, which the
        A06 profile disallows redefining.
    """
    return _copy_manifest_with_updates(manifest, additional_required_gates=("QG01",))


def _wrong_findings(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy with a shortened declared open-finding ID tuple.

    Args:
        manifest: Manifest model produced by the A06 fixture loader.

    Returns:
        A schema-valid manifest declaring only A06-F01 and A06-F02 open while retaining all
        original finding records.
    """
    return _copy_manifest_with_updates(manifest, open_finding_ids=("A06-F01", "A06-F02"))


def _wrong_roadmap(manifest: EvidenceManifest) -> EvidenceManifest:
    """Return a copy bound to a different roadmap package.

    Args:
        manifest: Manifest model produced by the A06 fixture loader.

    Returns:
        A schema-valid manifest whose roadmap ID is A07 instead of the A06 profile's package
        ID.
    """
    return _copy_manifest_with_updates(manifest, roadmap_id="A07")


class TestPackageEvidenceProfiles:
    """Exercise exact package-evidence profiles and adversarial manifest drift."""

    def test_build_graph_manifest_matches_its_exact_partial_r2_profile(self) -> None:
        """Validate that the B02 synthetic partial-R2 manifest matches its exact profile."""
        manifest = validate_manifest(
            BUILD_GRAPH_MANIFEST_PATH,
            expected_commit_sha="8" * 40,
            change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
        )
        profile = PackageEvidenceProfile(
            roadmap_package_id="B02",
            accountable_owner_role="platform",
            risk_class=RiskClass.R2,
            classification_facts=ChangeRiskInput(
                capital_at_risk=False,
                blast_radius="shared_domain",
                data_model_materiality="shared_or_candidate",
                security_privilege="none",
                reversibility="compatibility_window",
                computationally_material=True,
                economically_or_risk_relevant=False,
                model_or_trading_relevant=False,
                declared_class=RiskClass.R2,
            ),
            gate_requirements=tuple(
                PackageGateRequirement(gate_id=gate.gate_id, status="passed")
                for gate in manifest.gates
            ),
            expected_package_status="partial",
            expected_finding_ids=("B02-F01", "B02-F02", "B02-F03"),
            approvals_permitted=False,
            waivers_permitted=False,
            additional_required_gates_permitted=False,
        )

        validate_package_evidence(manifest, profile)

    def test_developer_environment_manifest_matches_its_exact_partial_r2_profile(
        self,
    ) -> None:
        """Validate that the B03 synthetic partial-R2 manifest matches its exact profile."""
        manifest = validate_manifest(
            DEVELOPER_ENVIRONMENT_MANIFEST_PATH,
            expected_commit_sha="9" * 40,
            change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
        )
        profile = PackageEvidenceProfile(
            roadmap_package_id="B03",
            accountable_owner_role="platform",
            risk_class=RiskClass.R2,
            classification_facts=ChangeRiskInput(
                capital_at_risk=False,
                blast_radius="shared_domain",
                data_model_materiality="shared_or_candidate",
                security_privilege="none",
                reversibility="compatibility_window",
                computationally_material=True,
                economically_or_risk_relevant=False,
                model_or_trading_relevant=False,
                declared_class=RiskClass.R2,
            ),
            gate_requirements=tuple(
                PackageGateRequirement(gate_id=gate.gate_id, status="passed")
                for gate in manifest.gates
            ),
            expected_package_status="partial",
            expected_finding_ids=("B03-F01", "B03-F02", "B03-F03"),
            approvals_permitted=False,
            waivers_permitted=False,
            additional_required_gates_permitted=False,
        )

        validate_package_evidence(manifest, profile)

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            (_wrong_owner, "owner must match"),
            (_changed_risk_fact, "change.security_privilege"),
            (_missing_gate, "missing=\\['QG14'\\]"),
            (_additional_gate, "additional=\\['QG15'\\]"),
            (_changed_gate_status, "required gate statuses"),
            (_unexpected_approval, "cannot contain approvals"),
            (_waiver, "cannot contain control waivers"),
            (_caller_additional_gate, "cannot redefine applicable gates"),
            (_wrong_findings, "expected findings exactly"),
            (_wrong_roadmap, "roadmap ID must be A06"),
        ],
    )
    def test_package_profile_rejects_manifest_drift(
        self, mutation: Callable[[EvidenceManifest], EvidenceManifest], message: str
    ) -> None:
        """Reject each adversarial manifest mutation with its expected profile diagnostic."""
        manifest = _manifest()

        with pytest.raises(EvidenceGovernanceError, match=message):
            validate_package_evidence(mutation(manifest), _profile(manifest))
