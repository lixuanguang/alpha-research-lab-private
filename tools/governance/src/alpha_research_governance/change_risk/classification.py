"""Classify change-risk inputs deterministically."""

from __future__ import annotations

# project library imports
from alpha_research_governance.change_risk.models import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ClassificationDecision,
    RiskClassPolicy,
)


def _required_gates(change: ChangeRiskInput, class_policy: RiskClassPolicy) -> set[str]:
    """Return mandatory and active conditional gates for one class policy."""
    gates = set(class_policy.mandatory_gates)
    for rule in class_policy.conditional_gate_rules:
        if change.trigger_is_active(rule.trigger):
            gates.update(rule.gates)
    return gates


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

    computed_policy = policy.class_policy(computed)
    class_policy = policy.class_policy(final)
    gates = _required_gates(change, class_policy)
    if final is not computed:
        # A conservative declaration may add controls but must not discard the
        # gates required by the facts that produced the computed class.
        gates.update(_required_gates(change, computed_policy))
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
