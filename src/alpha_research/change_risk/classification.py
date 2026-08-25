"""Pure classification behavior for A04 change-risk inputs."""

from __future__ import annotations

from alpha_research.change_risk.models import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ClassificationDecision,
)


def classify_change(change: ChangeRiskInput, policy: ChangeRiskPolicy) -> ClassificationDecision:
    """Classify by the highest dimension and reject a declared downgrade."""
    dimension_classes = tuple(
        (name, policy.dimension(name).minimum_class(value))
        for name, value in change.dimension_values()
    )
    computed = max((minimum for _, minimum in dimension_classes), key=lambda item: item.rank)
    final = computed
    drivers = tuple(name for name, minimum in dimension_classes if minimum is computed)
    if change.declared_class is not None:
        if change.declared_class.rank < computed.rank:
            raise ChangeRiskPolicyError(
                f"declared class {change.declared_class.value} is below required {computed.value}"
            )
        if change.declared_class.rank > computed.rank:
            final = change.declared_class
            drivers = ("declared_class",)

    class_policy = policy.class_policy(final)
    gates = set(class_policy.mandatory_gates)
    for rule in class_policy.conditional_gate_rules:
        if change.trigger_is_active(rule.trigger):
            gates.update(rule.gates)
    ordered_gates = tuple(sorted(gates, key=lambda gate: int(gate[2:])))
    return ClassificationDecision(
        risk_class=final,
        drivers=drivers,
        mandatory_gates=ordered_gates,
        reviewer_groups=class_policy.reviewer_groups,
        minimum_approvals=class_policy.minimum_approvals,
        minimum_independent_approvals=class_policy.minimum_independent_approvals,
        minimum_activation_approvals=class_policy.minimum_activation_approvals,
        rollout_modes=class_policy.rollout_modes,
        evidence_retention_class=class_policy.evidence_retention_class,
    )
