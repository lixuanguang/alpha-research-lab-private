"""Adversarial tests for exact governance package-evidence profiles."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

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
CHANGE_POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "change-risk-policy.toml"


def _manifest() -> EvidenceManifest:
    return validate_manifest(
        MANIFEST_PATH,
        expected_commit_sha="2" * 40,
        change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
    )


def _profile(manifest: EvidenceManifest) -> PackageEvidenceProfile:
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
    return EvidenceManifest.model_validate({**manifest.model_dump(round_trip=True), **updates})


def _wrong_owner(manifest: EvidenceManifest) -> EvidenceManifest:
    return _copy_manifest_with_updates(manifest, owner_role="security")


def _changed_risk_fact(manifest: EvidenceManifest) -> EvidenceManifest:
    changed = ChangeRiskInput.model_validate(
        {**manifest.change.model_dump(), "security_privilege": "shared_sensitive"}
    )
    return _copy_manifest_with_updates(manifest, change=changed)


def _missing_gate(manifest: EvidenceManifest) -> EvidenceManifest:
    return _copy_manifest_with_updates(manifest, gates=manifest.gates[:-1])


def _additional_gate(manifest: EvidenceManifest) -> EvidenceManifest:
    extra = GateEvidence(
        gate_id="QG15",
        status="passed",
        rationale="Adversarial additional gate.",
        evidence_ids=(manifest.artifacts[0].evidence_id,),
    )
    return _copy_manifest_with_updates(manifest, gates=(*manifest.gates, extra))


def _changed_gate_status(manifest: EvidenceManifest) -> EvidenceManifest:
    failed_gate = GateEvidence.model_validate(
        {**manifest.gates[0].model_dump(), "status": "failed"}
    )
    return _copy_manifest_with_updates(manifest, gates=(failed_gate, *manifest.gates[1:]))


def _unexpected_approval(manifest: EvidenceManifest) -> EvidenceManifest:
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
    return _copy_manifest_with_updates(manifest, waived_controls=("synthetic-control",))


def _caller_additional_gate(manifest: EvidenceManifest) -> EvidenceManifest:
    return _copy_manifest_with_updates(manifest, additional_required_gates=("QG01",))


def _wrong_findings(manifest: EvidenceManifest) -> EvidenceManifest:
    return _copy_manifest_with_updates(manifest, open_finding_ids=("A06-F01", "A06-F02"))


def _wrong_roadmap(manifest: EvidenceManifest) -> EvidenceManifest:
    return _copy_manifest_with_updates(manifest, roadmap_id="A07")


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
    mutation: Callable[[EvidenceManifest], EvidenceManifest], message: str
) -> None:
    manifest = _manifest()

    with pytest.raises(EvidenceGovernanceError, match=message):
        validate_package_evidence(mutation(manifest), _profile(manifest))


def test_package_profile_is_strict_and_immutable() -> None:
    manifest = _manifest()
    profile = _profile(manifest)

    with pytest.raises(ValidationError, match="frozen"):
        profile.approvals_permitted = True
    with pytest.raises(ValidationError):
        PackageEvidenceProfile.model_validate({**profile.model_dump(), "risk_class": "R2"})
    with pytest.raises(ValidationError):
        PackageEvidenceProfile.model_validate({**profile.model_dump(), "unknown_permission": False})
