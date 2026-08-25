"""Domain models shared by the A04 change-risk controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChangeRiskPolicyError(ValueError):
    """Report invalid policy, classification, or approval evidence."""


class RiskClass(str, Enum):
    """Ordered institutional change-risk classes."""

    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"

    @property
    def rank(self) -> int:
        """Return the class ordering used for conservative escalation."""
        return int(self.value[1])


@dataclass(frozen=True)
class ChangeRiskInput:
    """Validated dimensions and conditional-gate facts for one change."""

    capital_at_risk: bool
    blast_radius: str
    data_model_materiality: str
    security_privilege: str
    reversibility: str
    computationally_material: bool = False
    economically_or_risk_relevant: bool = False
    model_or_trading_relevant: bool = False
    declared_class: RiskClass | None = None

    def dimension_values(self) -> tuple[tuple[str, bool | str], ...]:
        """Return dimensions in stable policy order."""
        return (
            ("capital_at_risk", self.capital_at_risk),
            ("blast_radius", self.blast_radius),
            ("data_model_materiality", self.data_model_materiality),
            ("security_privilege", self.security_privilege),
            ("reversibility", self.reversibility),
        )

    def trigger_is_active(self, trigger: str) -> bool:
        """Return a conditional-gate fact without dynamic attribute access."""
        values = {
            "computationally_material": self.computationally_material,
            "economically_or_risk_relevant": self.economically_or_risk_relevant,
            "model_or_trading_relevant": self.model_or_trading_relevant,
        }
        try:
            return values[trigger]
        except KeyError as error:
            raise ChangeRiskPolicyError(f"unknown applicability trigger {trigger!r}") from error


@dataclass(frozen=True)
class DimensionPolicy:
    """Allowed values and minimum class for one risk dimension."""

    name: str
    levels: tuple[tuple[bool | str, RiskClass], ...]

    def minimum_class(self, value: bool | str) -> RiskClass:
        """Return the minimum class for an exact typed value."""
        for allowed, minimum in self.levels:
            if type(allowed) is type(value) and allowed == value:
                return minimum
        allowed_values = ", ".join(repr(item) for item, _ in self.levels)
        raise ChangeRiskPolicyError(
            f"{self.name}: unsupported value {value!r}; expected one of {allowed_values}"
        )


@dataclass(frozen=True)
class ConditionalGateRule:
    """Additional mandatory gates activated by an explicit change fact."""

    trigger: str
    gates: tuple[str, ...]


@dataclass(frozen=True)
class ReviewerGroup:
    """A reviewer role group that distinct approval evidence must satisfy."""

    group_id: str
    roles: frozenset[str]
    minimum_approvals: int
    independent: bool


@dataclass(frozen=True)
class RiskClassPolicy:
    """Gate, review, rollout, activation, and retention policy for a class."""

    risk_class: RiskClass
    mandatory_gates: tuple[str, ...]
    conditional_gate_rules: tuple[ConditionalGateRule, ...]
    reviewer_groups: tuple[ReviewerGroup, ...]
    minimum_approvals: int
    minimum_independent_approvals: int
    minimum_activation_approvals: int
    hard_control_waiver_allowed: bool
    rollout_modes: tuple[str, ...]
    evidence_retention_class: str


@dataclass(frozen=True)
class SampleChange:
    """Machine-readable classifier example retained with the policy."""

    change_id: str
    change: ChangeRiskInput
    expected_class: RiskClass


@dataclass(frozen=True)
class ChangeRiskPolicy:
    """Complete versioned A04 policy."""

    dimensions: tuple[DimensionPolicy, ...]
    risk_classes: tuple[RiskClassPolicy, ...]
    hard_controls: frozenset[str]
    author_may_lower_classification: bool
    author_may_satisfy_independent_review: bool
    package_status: str
    samples: tuple[SampleChange, ...]
    findings: tuple[str, ...]

    def dimension(self, name: str) -> DimensionPolicy:
        """Return a named dimension or fail closed."""
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        raise ChangeRiskPolicyError(f"policy has no dimension {name!r}")

    def class_policy(self, risk_class: RiskClass) -> RiskClassPolicy:
        """Return the policy for a risk class or fail closed."""
        for class_policy in self.risk_classes:
            if class_policy.risk_class is risk_class:
                return class_policy
        raise ChangeRiskPolicyError(f"policy has no class {risk_class.value}")


@dataclass(frozen=True)
class ClassificationDecision:
    """Deterministic classifier output used by later evidence tooling."""

    risk_class: RiskClass
    drivers: tuple[str, ...]
    mandatory_gates: tuple[str, ...]
    reviewer_groups: tuple[ReviewerGroup, ...]
    minimum_approvals: int
    minimum_independent_approvals: int
    minimum_activation_approvals: int
    rollout_modes: tuple[str, ...]
    evidence_retention_class: str


@dataclass(frozen=True)
class ReviewApproval:
    """One identified review approval supplied to the policy check."""

    reviewer_id: str
    roles: frozenset[str]
    independent: bool = False
    is_author: bool = False
