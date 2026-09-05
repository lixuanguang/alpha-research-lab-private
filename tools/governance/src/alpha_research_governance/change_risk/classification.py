"""Classify change-risk inputs deterministically."""

from __future__ import annotations

# project library imports
from alpha_research_governance.change_risk.models import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ClassificationDecision,
    RiskClass,
    RiskClassPolicy,
)


def _required_gates(change: ChangeRiskInput, class_policy: RiskClassPolicy) -> set[str]:
    """Return mandatory and active conditional gates for one class policy."""
    gates = set(class_policy.mandatory_gates)
    for rule in class_policy.conditional_gate_rules:
        if change.trigger_is_active(rule.trigger):
            gates.update(rule.gates)
    return gates


class ChangeRiskClassifier:
    """Apply one immutable policy to independent change-classification requests.

    Construction retains the policy without I/O. Decisions and gate sets belong
    to each call, so a rejected or escalated change cannot affect later requests.
    """

    def __init__(self, policy: ChangeRiskPolicy) -> None:
        """Bind the validated policy used for every classification.

        Args:
            policy: Versioned dimension, gate, review, and rollout requirements.
        """
        self._policy = policy

    def classify(self, change: ChangeRiskInput) -> ClassificationDecision:
        """Classify by the highest dimension, preserving gates on escalation.

        Args:
            change: Risk dimensions, conditional-gate facts, and optional declared class.

        Returns:
            A fresh decision with drivers in dimension order and unique gates in
            numeric order. A higher declaration becomes the sole driver while
            retaining all gates required by the computed class.

        Raises:
            ChangeRiskPolicyError: A dimension, class, or trigger is unsupported,
                or the declaration would lower the class required by the facts.
        """

        def _class_rank(item: RiskClass) -> int:
            """Order classes by their conservative escalation rank."""
            return item.rank

        def _gate_number(gate: str) -> int:
            """Order validated gate IDs by their numeric suffix."""
            return int(gate[2:])

        dimension_classes = tuple(
            (name, self._policy.dimension(name).minimum_class(value))
            for name, value in change.dimension_values()
        )
        computed = max((minimum for _, minimum in dimension_classes), key=_class_rank)
        final = computed
        drivers = tuple(name for name, minimum in dimension_classes if minimum is computed)
        if change.declared_class is not None:
            if change.declared_class.rank < computed.rank:
                raise ChangeRiskPolicyError(
                    f"declared class {change.declared_class.value} "
                    f"is below required {computed.value}"
                )
            if change.declared_class.rank > computed.rank:
                final = change.declared_class
                drivers = ("declared_class",)

        computed_policy = self._policy.class_policy(computed)
        class_policy = self._policy.class_policy(final)
        gates = _required_gates(change, class_policy)
        if final is not computed:
            # A conservative declaration may add controls but must not discard the
            # gates required by the facts that produced the computed class.
            gates.update(_required_gates(change, computed_policy))
        ordered_gates = tuple(sorted(gates, key=_gate_number))
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


def classify_change(change: ChangeRiskInput, policy: ChangeRiskPolicy) -> ClassificationDecision:
    """Delegate classification through the supported function API.

    Args:
        change: Risk dimensions, conditional-gate facts, and optional declared class.
        policy: Validated requirements to bind for this call.

    Returns:
        The deterministic decision produced by ``ChangeRiskClassifier.classify``.

    Raises:
        ChangeRiskPolicyError: The input is unsupported or declares a downgrade.
    """
    return ChangeRiskClassifier(policy).classify(change)
