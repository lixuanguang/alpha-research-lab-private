"""Validate exact package profiles for synthetic local evidence."""

from __future__ import annotations

# project library imports
from alpha_research_governance.change_risk import RiskClass
from alpha_research_governance.evidence.models import (
    EvidenceGovernanceError,
    EvidenceManifest,
    PackageEvidenceProfile,
)


class _PackageEvidenceValidator:
    """Compare one manifest with its exact package-evidence profile contract."""

    def __init__(self, profile: PackageEvidenceProfile) -> None:
        """Bind the immutable expected package profile."""
        self._profile = profile

    def _validate(self, manifest: EvidenceManifest) -> None:
        """Require a manifest to match an exact package-evidence profile.

        Compare the roadmap ID, owner role, serialized risk class, every classification
        fact in model declaration order, exact gate-ID coverage, expected gate statuses,
        mapped bundle status, and the exact ordered open-finding tuple. The profile
        status mapping is ``validated`` to ``accepted``, ``partial`` to ``partial``,
        and ``implementation_complete`` to ``implementation_accepted``. When any of
        ``approvals_permitted``, ``waivers_permitted``, or
        ``additional_required_gates_permitted`` is false, a non-empty corresponding
        manifest collection is rejected. Missing and additional gate IDs are sorted;
        status mismatches follow profile gate order, and all findings retain check order.

        The profile model rejects duplicate expected gate IDs, while ``validate_manifest``
        rejects duplicate manifest gate IDs before normal use. This function itself
        compares dictionaries, so a manually constructed manifest with duplicate gate
        IDs would use the last status for that ID. It performs no I/O, risk
        recomputation, artifact inspection, commit binding, approval or waiver
        inspection, or input mutation; true permission flags allow corresponding
        non-empty collections without inspecting or authenticating their contents.
        Callers should supply prevalidated manifest and profile models.

        Args:
            manifest: Prevalidated evidence manifest whose package bindings are compared.

        Raises:
            EvidenceGovernanceError: If any binding differs or a disallowed manifest collection is
                non-empty. All detected findings are aggregated in deterministic check order.
        """
        profile = self._profile
        package_id = profile.roadmap_package_id
        context = f"{package_id} local evidence bundle"
        findings: list[str] = []

        if manifest.roadmap_id != package_id:
            findings.append(f"{context} roadmap ID must be {package_id}")
        if manifest.owner_role != profile.accountable_owner_role:
            findings.append(
                f"{context} owner must match accountable owner role "
                f"{profile.accountable_owner_role!r}"
            )
        if manifest.risk_class != profile.risk_class.value:
            findings.append(f"{context} risk class must be {profile.risk_class.value}")

        expected_change = profile.classification_facts
        actual_values: dict[str, bool | str | RiskClass | None] = {
            "capital_at_risk": manifest.change.capital_at_risk,
            "blast_radius": manifest.change.blast_radius,
            "data_model_materiality": manifest.change.data_model_materiality,
            "security_privilege": manifest.change.security_privilege,
            "reversibility": manifest.change.reversibility,
            "computationally_material": manifest.change.computationally_material,
            "economically_or_risk_relevant": manifest.change.economically_or_risk_relevant,
            "model_or_trading_relevant": manifest.change.model_or_trading_relevant,
            "declared_class": manifest.change.declared_class,
        }
        expected_values: dict[str, bool | str | RiskClass | None] = {
            "capital_at_risk": expected_change.capital_at_risk,
            "blast_radius": expected_change.blast_radius,
            "data_model_materiality": expected_change.data_model_materiality,
            "security_privilege": expected_change.security_privilege,
            "reversibility": expected_change.reversibility,
            "computationally_material": expected_change.computationally_material,
            "economically_or_risk_relevant": expected_change.economically_or_risk_relevant,
            "model_or_trading_relevant": expected_change.model_or_trading_relevant,
            "declared_class": expected_change.declared_class,
        }
        for field_name, actual_value in actual_values.items():
            expected_value = expected_values[field_name]
            if actual_value != expected_value:
                display_value = (
                    expected_value.value
                    if isinstance(expected_value, RiskClass)
                    else expected_value
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
            findings.append(
                f"{package_id} synthetic local evidence cannot redefine applicable gates"
            )

        if findings:
            raise EvidenceGovernanceError(findings)


def validate_package_evidence(manifest: EvidenceManifest, profile: PackageEvidenceProfile) -> None:
    """Require a manifest to match an exact package-evidence profile.

    Compare the roadmap ID, owner role, serialized risk class, every classification
    fact in model declaration order, exact gate-ID coverage, expected gate statuses,
    mapped bundle status, and the exact ordered open-finding tuple. The profile
    status mapping is ``validated`` to ``accepted``, ``partial`` to ``partial``,
    and ``implementation_complete`` to ``implementation_accepted``. When any of
    ``approvals_permitted``, ``waivers_permitted``, or
    ``additional_required_gates_permitted`` is false, a non-empty corresponding
    manifest collection is rejected. Missing and additional gate IDs are sorted;
    status mismatches follow profile gate order, and all findings retain check order.

    The profile model rejects duplicate expected gate IDs, while ``validate_manifest``
    rejects duplicate manifest gate IDs before normal use. This function itself
    compares dictionaries, so a manually constructed manifest with duplicate gate
    IDs would use the last status for that ID. It performs no I/O, risk
    recomputation, artifact inspection, commit binding, approval or waiver
    inspection, or input mutation; true permission flags allow corresponding
    non-empty collections without inspecting or authenticating their contents.
    Callers should supply prevalidated manifest and profile models.

    Args:
        manifest: Prevalidated evidence manifest whose package bindings are compared.
        profile: Immutable package profile defining the expected bindings, gates, statuses,
            findings, and collection permissions.

    Raises:
        EvidenceGovernanceError: If any binding differs or a disallowed manifest collection is
            non-empty. All detected findings are aggregated in deterministic check order.
    """
    _PackageEvidenceValidator(profile)._validate(manifest)
