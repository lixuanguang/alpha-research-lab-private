"""Canonical change-risk API and repository policy-check command."""

from __future__ import annotations

# standard library imports
import sys
from collections.abc import Sequence
from pathlib import Path

# project library imports
from alpha_research_governance.change_risk.approvals import (
    ChangeRiskApprovalEvaluator,
    validate_activation_approvals,
    validate_merge_approvals,
)
from alpha_research_governance.change_risk.classification import (
    ChangeRiskClassifier,
    classify_change,
)
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
    "ChangeRiskApprovalEvaluator",
    "ChangeRiskClassifier",
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
    """Validate the repository's authoritative change-risk policy.

    Args:
        repository_root: Repository root whose ``docs/governance/change-risk-policy.toml``
            file supplies the policy.

    Returns:
        The fully validated change-risk policy, including its retained sample changes.

    Raises:
        ChangeRiskPolicyError: If the policy is malformed, violates its schema, or fails
            sample classification checks.
        OSError: If the policy file cannot be resolved or read.
        UnicodeDecodeError: If the policy file is not valid UTF-8.
    """
    return load_policy(
        repository_root.resolve() / "docs" / "governance" / "change-risk-policy.toml"
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the change-risk policy checker from the command line.

    ``ChangeRiskPolicyError`` and ``OSError`` failures from ``validate_repository`` are
    caught and converted to status ``1``; decoding failures and errors while resolving the
    default working directory, writing output, or handling unexpected conditions propagate
    to the caller.

    Args:
        arguments: Optional command-line arguments. Omit this value to consume
            ``sys.argv[1:]``; provide at most one repository-root argument.

    Returns:
        ``0`` after printing the validation summary to stdout, ``1`` after printing a
        handled policy or filesystem failure to stderr, or ``2`` after printing usage
        for too many arguments.

    Raises:
        OSError: If resolving the default working directory or writing output fails
            outside the policy-validation handler.
        UnicodeDecodeError: If the selected policy file is not valid UTF-8.
    """
    cli_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(cli_arguments) > 1:
        print(
            "usage: python -m alpha_research_governance.change_risk [repository-root]",
            file=sys.stderr,
        )
        return 2
    repository_root = Path(cli_arguments[0]) if cli_arguments else Path.cwd()
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
