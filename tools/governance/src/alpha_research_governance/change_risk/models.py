"""Define domain models shared by the change-risk controls."""

from __future__ import annotations

# standard library imports
from enum import Enum

# third party library imports
from pydantic import field_serializer

# project library imports
from alpha_research_governance._models import ImmutableModel


class ChangeRiskPolicyError(ValueError):
    """Report invalid policy, classification, or approval evidence."""


class RiskClass(str, Enum):  # noqa: UP042 - StrEnum changes behavior. [owner=platform; rationale=preserve serialized string API; expires=2026-12-31]
    """Order institutional change-risk classes from R0 through R4.

    Use rank for severity comparisons. The string-valued Enum representation is
    retained for compatibility; Python mode keeps enum members and JSON uses values.
    """

    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"

    @property
    def rank(self) -> int:
        """Return the class ordering used for conservative escalation.

        Returns:
            Integer severity from 0 for R0 through 4 for R4.
        """
        return int(self.value[1])


class ChangeRiskInput(ImmutableModel):
    """Retain typed dimensions and conditional-gate facts for one change.

    Construction checks field types; policy-specific dimension values are checked
    by the classifier. A declared class is a request, not a computed decision.

    Attributes:
        capital_at_risk: Boolean risk dimension for changes putting capital at risk.
        blast_radius: Policy token describing the affected scope.
        data_model_materiality: Policy token describing data/model impact.
        security_privilege: Policy token describing privilege impact.
        reversibility: Policy token describing recovery or rollback constraints.
        computationally_material: Whether computational validation gates apply; defaults to
            False.
        economically_or_risk_relevant: Whether economic/risk validation gates apply;
            defaults to False.
        model_or_trading_relevant: Whether model/trading validation gates apply; defaults to
            False.
        declared_class: Optional requested class, subject to classifier escalation/downgrade
            rules.
    """

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
        """Return dimensions in stable policy order.

        Returns:
            Name/value pairs for capital_at_risk, blast_radius, data_model_materiality,
            security_privilege and reversibility, in that order. Trigger facts and
            declared_class are excluded.
        """
        return (
            ("capital_at_risk", self.capital_at_risk),
            ("blast_radius", self.blast_radius),
            ("data_model_materiality", self.data_model_materiality),
            ("security_privilege", self.security_privilege),
            ("reversibility", self.reversibility),
        )

    def trigger_is_active(self, trigger: str) -> bool:
        """Return a conditional-gate fact without dynamic attribute access.

        Args:
            trigger: Exact computationally_material, economically_or_risk_relevant or
                model_or_trading_relevant key.

        Returns:
            The stored Boolean fact for the selected trigger.

        Raises:
            ChangeRiskPolicyError: The trigger is not one of the three supported keys.
        """
        values = {
            "computationally_material": self.computationally_material,
            "economically_or_risk_relevant": self.economically_or_risk_relevant,
            "model_or_trading_relevant": self.model_or_trading_relevant,
        }
        try:
            return values[trigger]
        except KeyError as error:
            raise ChangeRiskPolicyError(f"unknown applicability trigger {trigger!r}") from error


class DimensionPolicy(ImmutableModel):
    """Associate exact typed dimension values with their minimum risk classes.

    Attributes:
        name: Dimension key used in classifier input and errors.
        levels: Ordered value/class pairs; lookup requires both type identity and value
            equality.
    """

    name: str
    levels: tuple[tuple[bool | str, RiskClass], ...]

    def minimum_class(self, value: bool | str) -> RiskClass:
        """Return the minimum class for an exact typed value.

        Args:
            value: Boolean or string level to find; no case folding or Boolean/string conversion
                occurs.

        Returns:
            The class from the first pair matching both the value and its exact type.

        Raises:
            ChangeRiskPolicyError: No level matches; the error includes the dimension and
                allowed values.
        """
        for allowed, minimum in self.levels:
            if type(allowed) is type(value) and allowed == value:
                return minimum
        allowed_values = ", ".join(repr(item) for item, _ in self.levels)
        raise ChangeRiskPolicyError(
            f"{self.name}: unsupported value {value!r}; expected one of {allowed_values}"
        )


class ConditionalGateRule(ImmutableModel):
    """Declare additional mandatory gates activated by one change fact.

    Attributes:
        trigger: Exact applicability key resolved by ChangeRiskInput.trigger_is_active.
        gates: Gate IDs added when that fact is active.
    """

    trigger: str
    gates: tuple[str, ...]


class ReviewerGroup(ImmutableModel):
    """Declare a role group to satisfy with distinct approval evidence.

    The approval evaluator checks role intersection, counts and independence;
    constructing this record does not establish that a reviewer qualifies.

    Attributes:
        group_id: Stable label used in approval findings.
        roles: Any one of these roles can qualify a reviewer; JSON serialization sorts the
            set.
        minimum_approvals: Number of distinct reviewer slots required for this group.
        independent: Whether qualifying reviewers must claim independence and not be the
            author.
    """

    group_id: str
    roles: frozenset[str]
    minimum_approvals: int
    independent: bool

    @field_serializer("roles", when_used="json")
    def sorted_roles(self, roles: frozenset[str]) -> tuple[str, ...]:
        """Serialize an unordered immutable set deterministically.

        Python-mode serialization retains the frozenset. The source set is unchanged.

        Args:
            roles: Set of role identifiers supplied to the JSON serializer.

        Returns:
            A lexicographically sorted tuple, represented as an array by JSON serialization.
        """
        return tuple(sorted(roles))


class RiskClassPolicy(ImmutableModel):
    """Retain gate, review, rollout, activation and retention requirements for a class.

    The policy loader checks the admissible values and required control floors.
    Constructing this typed record alone does not validate those policy constraints.

    Attributes:
        risk_class: Class to which these requirements apply.
        mandatory_gates: Unconditional gate IDs.
        conditional_gate_rules: Additional gates activated by explicit change facts.
        reviewer_groups: Role groups whose reviewer slots are enforced separately.
        minimum_approvals: Minimum distinct merge approvers.
        minimum_independent_approvals: Minimum independent non-author merge approvers.
        minimum_activation_approvals: Minimum distinct activation approvers.
        hard_control_waiver_allowed: Whether this class permits a waiver of a hard control.
        rollout_modes: Admitted rollout strategies.
        evidence_retention_class: Retention-policy token attached to resulting decisions.
    """

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


class SampleChange(ImmutableModel):
    """Bind a retained classifier example to its expected risk class.

    Attributes:
        change_id: Stable example identifier.
        change: Typed input facts to classify.
        expected_class: Expected computed class checked by the policy loader.
    """

    change_id: str
    change: ChangeRiskInput
    expected_class: RiskClass


class ChangeRiskPolicy(ImmutableModel):
    """Retain the complete policy used by classification and approval services.

    Use the policy loader to check supported dimensions, class coverage, control
    floors and examples. Direct model construction validates typed fields only;
    lookup methods return the first matching entry without rebuilding the policy.

    Attributes:
        dimensions: Dimension definitions searched by exact name.
        risk_classes: Class requirements searched by RiskClass member identity.
        hard_controls: Control IDs subject to waiver restrictions; serialized in sorted
            order.
        author_may_lower_classification: Whether author-declared downgrades are permitted by
            policy.
        author_may_satisfy_independent_review: Recorded author-independence policy; loader
            constraints also apply.
        package_status: Declared implementation status of the policy package.
        samples: Retained classification examples.
        findings: Unresolved findings retained by the policy.
    """

    dimensions: tuple[DimensionPolicy, ...]
    risk_classes: tuple[RiskClassPolicy, ...]
    hard_controls: frozenset[str]
    author_may_lower_classification: bool
    author_may_satisfy_independent_review: bool
    package_status: str
    samples: tuple[SampleChange, ...]
    findings: tuple[str, ...]

    @field_serializer("hard_controls", when_used="json")
    def sorted_hard_controls(self, controls: frozenset[str]) -> tuple[str, ...]:
        """Serialize an unordered immutable set deterministically.

        Python-mode serialization retains the frozenset. The source set is unchanged.

        Args:
            controls: Set of hard-control identifiers supplied to the JSON serializer.

        Returns:
            A lexicographically sorted tuple, represented as an array by JSON serialization.
        """
        return tuple(sorted(controls))

    def dimension(self, name: str) -> DimensionPolicy:
        """Return a named dimension or fail closed.

        Args:
            name: Exact dimension key; case and spelling are preserved.

        Returns:
            The first stored dimension with that name.

        Raises:
            ChangeRiskPolicyError: The policy has no dimension with the supplied name.
        """
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        raise ChangeRiskPolicyError(f"policy has no dimension {name!r}")

    def class_policy(self, risk_class: RiskClass) -> RiskClassPolicy:
        """Return the policy for a risk class or fail closed.

        Args:
            risk_class: RiskClass enum member to match by identity.

        Returns:
            The first stored class policy for that enum member.

        Raises:
            ChangeRiskPolicyError: No policy entry exists for the supplied class.
        """
        for class_policy in self.risk_classes:
            if class_policy.risk_class is risk_class:
                return class_policy
        raise ChangeRiskPolicyError(f"policy has no class {risk_class.value}")


class ClassificationDecision(ImmutableModel):
    """Carry deterministic classifier requirements into evidence evaluation.

    Classifier output preserves driver order and sorts the unique mandatory
    gates. Approval evaluation recomputes and binds these requirements to the
    supplied change and policy; constructing a decision is not authorization.

    Attributes:
        risk_class: Computed or conservatively escalated class.
        drivers: Highest-risk dimension names in input order, or declared_class after
            escalation.
        mandatory_gates: Unconditional and activated conditional gates.
        reviewer_groups: Groups whose distinct reviewer slots must be satisfied.
        minimum_approvals: Required distinct merge approvers.
        minimum_independent_approvals: Required independent non-author merge approvers.
        minimum_activation_approvals: Required distinct activation approvers.
        rollout_modes: Permitted rollout strategies for the selected class.
        evidence_retention_class: Retention-policy token for resulting evidence.
    """

    risk_class: RiskClass
    drivers: tuple[str, ...]
    mandatory_gates: tuple[str, ...]
    reviewer_groups: tuple[ReviewerGroup, ...]
    minimum_approvals: int
    minimum_independent_approvals: int
    minimum_activation_approvals: int
    rollout_modes: tuple[str, ...]
    evidence_retention_class: str


class ReviewApproval(ImmutableModel):
    """Carry one reviewer identity and its claimed approval attributes.

    Identity canonicalization, duplicate detection, role syntax and eligibility
    are checked by the approval evaluator, not by constructing this record.

    Attributes:
        reviewer_id: Claimed reviewer identity, retained as supplied.
        roles: Claimed roles; JSON serialization sorts the immutable set.
        independent: Claim of independent review; defaults to False.
        is_author: Whether the reviewer is the author; defaults to False.
    """

    reviewer_id: str
    roles: frozenset[str]
    independent: bool = False
    is_author: bool = False

    @field_serializer("roles", when_used="json")
    def sorted_roles(self, roles: frozenset[str]) -> tuple[str, ...]:
        """Serialize an unordered immutable set deterministically.

        Python-mode serialization retains the frozenset. The source set is unchanged.

        Args:
            roles: Set of role identifiers supplied to the JSON serializer.

        Returns:
            A lexicographically sorted tuple, represented as an array by JSON serialization.
        """
        return tuple(sorted(roles))
