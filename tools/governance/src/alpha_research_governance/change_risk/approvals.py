"""Enforce approvals and hard controls for change-risk decisions."""

from __future__ import annotations

# standard library imports
from collections.abc import Sequence
from unicodedata import normalize

# project library imports
from alpha_research_governance.change_risk.classification import ChangeRiskClassifier
from alpha_research_governance.change_risk.constraints import ROLE_PATTERN
from alpha_research_governance.change_risk.models import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ClassificationDecision,
    ReviewApproval,
    ReviewerGroup,
)


class ChangeRiskApprovalEvaluator:
    """Evaluate independent merge and activation requests under one immutable policy.

    A classifier bound to the same policy verifies caller-supplied decisions.
    Construction performs no I/O; findings and reviewer assignments are never
    retained between calls. Identity and role claims remain supplied evidence,
    without implying external authentication or changing founder/team policy.
    """

    def __init__(self, policy: ChangeRiskPolicy) -> None:
        """Bind approval requirements and their deterministic classifier.

        Args:
            policy: Validated review, activation, and hard-control requirements.
        """
        self._policy = policy
        self._classifier = ChangeRiskClassifier(policy)

    def validate_merge(
        self,
        decision: ClassificationDecision,
        approvals: Sequence[ReviewApproval],
        *,
        change: ChangeRiskInput,
        waived_controls: Sequence[str],
    ) -> None:
        """Validate merge review and hard controls against the bound policy.

        Args:
            decision: Caller-supplied evidence, checked against a fresh classification.
            approvals: Claimed identities, roles, independence, and authorship flags.
            change: Original dimensions and gate facts used to recompute the decision.
            waived_controls: Requested control waivers; prohibited hard controls fail.

        Raises:
            ChangeRiskPolicyError: Classification fails or review evidence violates
                policy. Findings retain deterministic order and are local to this call.
        """
        findings: list[str] = []
        trusted_decision = self._trusted_decision(decision, change, findings)

        reviewer_ids = _validate_approval_inputs(approvals, findings=findings)
        if len(set(reviewer_ids)) < trusted_decision.minimum_approvals:
            findings.append(
                f"{trusted_decision.risk_class.value} requires at least "
                f"{trusted_decision.minimum_approvals} distinct approvers"
            )

        eligible_independent = [
            approval for approval in approvals if approval.independent and not approval.is_author
        ]
        if len(eligible_independent) < trusted_decision.minimum_independent_approvals:
            findings.append(
                f"{trusted_decision.risk_class.value} requires at least "
                f"{trusted_decision.minimum_independent_approvals} independent approvers"
            )
        for group in trusted_decision.reviewer_groups:
            matches = [
                approval
                for approval in approvals
                if approval.roles & group.roles
                and (not group.independent or (approval.independent and not approval.is_author))
            ]
            if len(matches) < group.minimum_approvals:
                findings.append(f"reviewer group {group.group_id!r} is unsatisfied")
        if not _reviewer_groups_have_distinct_approvers(
            trusted_decision.reviewer_groups, approvals, reviewer_ids
        ):
            findings.append("reviewer groups require distinct qualifying identities")

        class_policy = self._policy.class_policy(trusted_decision.risk_class)
        waived_hard_controls = self._policy.hard_controls & set(waived_controls)
        if waived_hard_controls and not class_policy.hard_control_waiver_allowed:
            findings.append(
                f"{trusted_decision.risk_class.value} cannot waive hard controls: "
                f"{sorted(waived_hard_controls)}"
            )
        if findings:
            raise ChangeRiskPolicyError("\n".join(findings))

    def validate_activation(
        self,
        decision: ClassificationDecision,
        approvals: Sequence[ReviewApproval],
        *,
        change: ChangeRiskInput,
    ) -> None:
        """Validate activation identities against a fresh classification.

        Args:
            decision: Caller-supplied evidence, checked against the bound policy.
            approvals: Claimed activation identities and roles, canonicalized for counting.
            change: Original dimensions and gate facts used to recompute the decision.

        Raises:
            ChangeRiskPolicyError: Classification fails, the decision is unbound,
                identities or roles are invalid, or too few distinct approvers remain.
                Findings retain deterministic order and are local to this call.
        """
        findings: list[str] = []
        trusted_decision = self._trusted_decision(decision, change, findings)

        reviewer_ids = _validate_approval_inputs(approvals, findings=findings)
        if len(set(reviewer_ids)) < trusted_decision.minimum_activation_approvals:
            findings.append(
                f"{trusted_decision.risk_class.value} activation requires at least "
                f"{trusted_decision.minimum_activation_approvals} distinct approvers"
            )
        if findings:
            raise ChangeRiskPolicyError("\n".join(findings))

    def _trusted_decision(
        self,
        decision: ClassificationDecision,
        change: ChangeRiskInput,
        findings: list[str],
    ) -> ClassificationDecision:
        """Recompute the decision and append a binding error to this call's findings."""
        trusted_decision = self._classifier.classify(change)
        if decision != trusted_decision:
            findings.append(
                "classification decision does not match the deterministic result for change input"
            )
        return trusted_decision


def validate_merge_approvals(
    decision: ClassificationDecision,
    approvals: Sequence[ReviewApproval],
    *,
    change: ChangeRiskInput,
    waived_controls: Sequence[str],
    policy: ChangeRiskPolicy,
) -> None:
    """Delegate merge validation through the supported function API.

    Args:
        decision: Caller-supplied classification to verify against the change.
        approvals: Claimed review identities, roles, independence, and authorship.
        change: Original risk dimensions and conditional-gate facts.
        waived_controls: Requested control waivers to check against hard controls.
        policy: Validated requirements to bind for this call.

    Raises:
        ChangeRiskPolicyError: Classification, decision binding, review, or waivers fail.
    """
    ChangeRiskApprovalEvaluator(policy).validate_merge(
        decision, approvals, change=change, waived_controls=waived_controls
    )


def validate_activation_approvals(
    decision: ClassificationDecision,
    approvals: Sequence[ReviewApproval],
    *,
    change: ChangeRiskInput,
    policy: ChangeRiskPolicy,
) -> None:
    """Delegate activation validation through the supported function API.

    Args:
        decision: Caller-supplied classification to verify against the change.
        approvals: Claimed activation identities and roles.
        change: Original risk dimensions and conditional-gate facts.
        policy: Validated requirements to bind for this call.

    Raises:
        ChangeRiskPolicyError: Classification, binding, identities, roles, or counts fail.
    """
    ChangeRiskApprovalEvaluator(policy).validate_activation(decision, approvals, change=change)


def _canonical_reviewer_id(reviewer_id: str) -> str:
    """Canonicalize a caller identity for deterministic distinctness checks."""
    return normalize("NFKC", reviewer_id).strip().casefold()


def _validate_approval_inputs(
    approvals: Sequence[ReviewApproval], *, findings: list[str]
) -> tuple[str, ...]:
    """Validate role claims and return canonical reviewer identities."""
    reviewer_ids = tuple(_canonical_reviewer_id(approval.reviewer_id) for approval in approvals)
    if any(not reviewer_id for reviewer_id in reviewer_ids):
        findings.append("reviewer_id must not be empty")
    if len(reviewer_ids) != len(set(reviewer_ids)):
        findings.append("reviewer approvals must have distinct identities after canonicalization")
    for approval in approvals:
        if not approval.roles or any(
            ROLE_PATTERN.fullmatch(role) is None for role in approval.roles
        ):
            findings.append(f"reviewer {approval.reviewer_id!r} has invalid roles")
    return reviewer_ids


def _reviewer_groups_have_distinct_approvers(
    groups: Sequence[ReviewerGroup],
    approvals: Sequence[ReviewApproval],
    reviewer_ids: Sequence[str],
) -> bool:
    """Test whether role slots admit a distinct eligible identity assignment."""
    slots = tuple(group for group in groups for _ in range(group.minimum_approvals))

    def assign_reviewer(slot_index: int, used_reviewer_ids: frozenset[str]) -> bool:
        """Backtrack over eligible identities without reusing a reviewer."""
        if slot_index == len(slots):
            return True
        group = slots[slot_index]
        for approval, reviewer_id in zip(approvals, reviewer_ids, strict=True):
            is_eligible = (
                reviewer_id not in used_reviewer_ids
                and bool(approval.roles & group.roles)
                and (not group.independent or (approval.independent and not approval.is_author))
            )
            if is_eligible and assign_reviewer(slot_index + 1, used_reviewer_ids | {reviewer_id}):
                return True
        return False

    return assign_reviewer(0, frozenset())
