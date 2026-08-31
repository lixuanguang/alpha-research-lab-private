"""Canonical A04 change-risk API and repository policy-check command."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alpha_research_governance.change_risk.approvals import (
    validate_activation_approvals,
    validate_merge_approvals,
)
from alpha_research_governance.change_risk.classification import classify_change
from alpha_research_governance.change_risk.models import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ClassificationDecision,
    ConditionalGateRule,
    DimensionPolicy,
    ReviewApproval,
    ReviewerGroup,
    RiskClass,
    RiskClassPolicy,
    SampleChange,
)
from alpha_research_governance.change_risk.policy import load_policy

__all__ = [
    "ChangeRiskInput",
    "ChangeRiskPolicy",
    "ChangeRiskPolicyError",
    "ClassificationDecision",
    "ConditionalGateRule",
    "DimensionPolicy",
    "ReviewApproval",
    "ReviewerGroup",
    "RiskClass",
    "RiskClassPolicy",
    "SampleChange",
    "classify_change",
    "load_policy",
    "main",
    "validate_activation_approvals",
    "validate_merge_approvals",
    "validate_repository",
]


def validate_repository(repository_root: Path) -> ChangeRiskPolicy:
    """Validate the repository's authoritative A04 policy."""
    return load_policy(
        repository_root.resolve() / "docs" / "governance" / "change-risk-policy.toml"
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the A04 policy checker from the command line."""
    provided = list(sys.argv[1:] if arguments is None else arguments)
    if len(provided) > 1:
        print(
            "usage: python -m alpha_research_governance.change_risk [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(provided[0]) if provided else Path.cwd()
    try:
        policy = validate_repository(repository_root)
    except (ChangeRiskPolicyError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"Change-risk policy passed for {len(policy.risk_classes)} classes and "
        f"{len(policy.samples)} samples; package status is {policy.package_status}."
    )
    return 0
