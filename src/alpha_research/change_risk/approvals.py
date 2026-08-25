"""Approval and hard-control enforcement for A04 classification decisions."""

from __future__ import annotations

from collections.abc import Sequence

from alpha_research.change_risk.classification import classify_change
from alpha_research.change_risk.constraints import ROLE_PATTERN
from alpha_research.change_risk.models import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ClassificationDecision,
    ReviewApproval,
    ReviewerGroup,
)


def validate_merge_approvals(
    decision: ClassificationDecision,
    approvals: Sequence[ReviewApproval],
    *,
    change: ChangeRiskInput,
    waived_controls: Sequence[str],
    policy: ChangeRiskPolicy,
) -> None:
    """Reject an unbound decision, insufficient review, or a prohibited waiver."""
    findings: list[str] = []
    trusted_decision = classify_change(change, policy)
    if decision != trusted_decision:
        findings.append(
            "classification decision does not match the deterministic result for change input"
        )

    reviewer_ids = [approval.reviewer_id for approval in approvals]
    if any(not reviewer_id.strip() for reviewer_id in reviewer_ids):
        findings.append("reviewer_id must not be empty")
    if len(reviewer_ids) != len(set(reviewer_ids)):
        findings.append("reviewer approvals must have distinct identities")
    if len(set(reviewer_ids)) < trusted_decision.minimum_approvals:
        findings.append(
            f"{trusted_decision.risk_class.value} requires at least "
            f"{trusted_decision.minimum_approvals} distinct approvers"
        )
    for approval in approvals:
        if not approval.roles or any(
            ROLE_PATTERN.fullmatch(role) is None for role in approval.roles
        ):
            findings.append(f"reviewer {approval.reviewer_id!r} has invalid roles")

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
    if not _reviewer_groups_have_distinct_approvers(trusted_decision.reviewer_groups, approvals):
        findings.append("reviewer groups require distinct qualifying identities")

    class_policy = policy.class_policy(trusted_decision.risk_class)
    waived_hard_controls = policy.hard_controls & set(waived_controls)
    if waived_hard_controls and not class_policy.hard_control_waiver_allowed:
        findings.append(
            f"{trusted_decision.risk_class.value} cannot waive hard controls: "
            f"{sorted(waived_hard_controls)}"
        )
    if findings:
        raise ChangeRiskPolicyError("\n".join(findings))


def _reviewer_groups_have_distinct_approvers(
    groups: Sequence[ReviewerGroup], approvals: Sequence[ReviewApproval]
) -> bool:
    slots = tuple(group for group in groups for _ in range(group.minimum_approvals))

    def assign(slot_index: int, used_reviewer_ids: frozenset[str]) -> bool:
        if slot_index == len(slots):
            return True
        group = slots[slot_index]
        for approval in approvals:
            is_eligible = (
                approval.reviewer_id not in used_reviewer_ids
                and bool(approval.roles & group.roles)
                and (not group.independent or (approval.independent and not approval.is_author))
            )
            if is_eligible and assign(slot_index + 1, used_reviewer_ids | {approval.reviewer_id}):
                return True
        return False

    return assign(0, frozenset())
