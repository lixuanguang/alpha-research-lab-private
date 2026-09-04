"""Validate exact package profiles for synthetic local evidence."""

from __future__ import annotations

from alpha_research_governance.change_risk import RiskClass
from alpha_research_governance.evidence.models import (
    EvidenceGovernanceError,
    EvidenceManifest,
    PackageEvidenceProfile,
)


def validate_package_evidence(manifest: EvidenceManifest, profile: PackageEvidenceProfile) -> None:
    """Require a manifest to match every immutable package-profile binding."""
    package_id = profile.roadmap_package_id
    context = f"{package_id} local evidence bundle"
    findings: list[str] = []

    if manifest.roadmap_id != package_id:
        findings.append(f"{context} roadmap ID must be {package_id}")
    if manifest.owner_role != profile.accountable_owner_role:
        findings.append(
            f"{context} owner must match accountable owner role {profile.accountable_owner_role!r}"
        )
    if manifest.risk_class != profile.risk_class.value:
        findings.append(f"{context} risk class must be {profile.risk_class.value}")

    expected_change = profile.classification_facts
    for field_name in type(expected_change).model_fields:
        actual_value = getattr(manifest.change, field_name)
        expected_value = getattr(expected_change, field_name)
        if actual_value != expected_value:
            display_value = (
                expected_value.value if isinstance(expected_value, RiskClass) else expected_value
            )
            findings.append(f"{context} change.{field_name} must be {display_value!r}")

    expected_gates = {
        requirement.gate_id: requirement.status for requirement in profile.gate_requirements
    }
    actual_gates = {gate.gate_id: gate.status for gate in manifest.gates}
    missing_gates = sorted(set(expected_gates) - set(actual_gates))
    additional_gates = sorted(set(actual_gates) - set(expected_gates))
    if missing_gates or additional_gates:
        findings.append(
            f"{context} must record the exact applicable gate set; "
            f"missing={missing_gates!r}, additional={additional_gates!r}"
        )
    mismatched_statuses = tuple(
        (gate_id, actual_gates[gate_id], expected_status)
        for gate_id, expected_status in expected_gates.items()
        if gate_id in actual_gates and actual_gates[gate_id] != expected_status
    )
    if mismatched_statuses:
        findings.append(
            f"{context} must use the required gate statuses; mismatches={mismatched_statuses!r}"
        )

    expected_bundle_status = {
        "validated": "accepted",
        "partial": "partial",
        "implementation_complete": "implementation_accepted",
    }[profile.expected_package_status]
    if manifest.bundle_status != expected_bundle_status:
        findings.append(f"{context} package status must be {profile.expected_package_status!r}")
    if manifest.open_finding_ids != profile.expected_finding_ids:
        findings.append(f"{context} must retain the expected findings exactly")
    if not profile.approvals_permitted and manifest.approvals:
        findings.append(f"{package_id} synthetic local evidence cannot contain approvals")
    if not profile.waivers_permitted and manifest.waived_controls:
        findings.append(f"{package_id} synthetic local evidence cannot contain control waivers")
    if not profile.additional_required_gates_permitted and manifest.additional_required_gates:
        findings.append(f"{package_id} synthetic local evidence cannot redefine applicable gates")

    if findings:
        raise EvidenceGovernanceError(findings)
