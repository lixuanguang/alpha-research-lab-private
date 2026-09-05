"""Compatibility facade for the canonical change-risk tool."""

# project library imports
from alpha_research_governance.change_risk import (
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
    classify_change,
    load_policy,
    main,
    validate_activation_approvals,
    validate_merge_approvals,
    validate_repository,
)

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
