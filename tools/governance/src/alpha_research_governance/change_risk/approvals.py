"""Enforce approvals and hard controls for change-risk decisions."""

from __future__ import annotations

from collections.abc import Sequence
from unicodedata import normalize

from alpha_research_governance.change_risk.classification import classify_change
from alpha_research_governance.change_risk.constraints import ROLE_PATTERN
from alpha_research_governance.change_risk.models import (
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

    class_policy = policy.class_policy(trusted_decision.risk_class)
    waived_hard_controls = policy.hard_controls & set(waived_controls)
    if waived_hard_controls and not class_policy.hard_control_waiver_allowed:
        findings.append(
            f"{trusted_decision.risk_class.value} cannot waive hard controls: "
            f"{sorted(waived_hard_controls)}"
        )
    if findings:
        raise ChangeRiskPolicyError("\n".join(findings))


def validate_activation_approvals(
    decision: ClassificationDecision,
    approvals: Sequence[ReviewApproval],
    *,
    change: ChangeRiskInput,
    policy: ChangeRiskPolicy,
) -> None:
    """Reject an unbound activation decision or insufficient dual control."""
    findings: list[str] = []
    trusted_decision = classify_change(change, policy)
    if decision != trusted_decision:
        findings.append(
            "classification decision does not match the deterministic result for change input"
        )

    reviewer_ids = _validate_approval_inputs(approvals, findings=findings)
    if len(set(reviewer_ids)) < trusted_decision.minimum_activation_approvals:
        findings.append(
            f"{trusted_decision.risk_class.value} activation requires at least "
            f"{trusted_decision.minimum_activation_approvals} distinct approvers"
        )
    if findings:
        raise ChangeRiskPolicyError("\n".join(findings))


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
    slots = tuple(group for group in groups for _ in range(group.minimum_approvals))

    def assign_reviewer(slot_index: int, used_reviewer_ids: frozenset[str]) -> bool:
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
