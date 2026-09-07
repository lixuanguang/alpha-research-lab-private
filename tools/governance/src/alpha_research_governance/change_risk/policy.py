"""Parse and validate the blueprint-bound change-risk TOML policy."""

from __future__ import annotations

# standard library imports
import tomllib
from pathlib import Path

# third party library imports
from pydantic import ConfigDict, TypeAdapter, ValidationError

# project library imports
from alpha_research_governance._models import ImmutableModel
from alpha_research_governance.change_risk.classification import ChangeRiskClassifier
from alpha_research_governance.change_risk.constraints import (
    APPLICABILITY_TRIGGERS,
    BLUEPRINT_CONDITIONAL_GATES,
    BLUEPRINT_REQUIRED_GATES,
    CHANGE_RISK_OPEN_FINDING_IDS,
    EXPECTED_DIMENSIONS,
    EXPECTED_RETENTION_CLASSES,
    EXPECTED_REVIEWER_GROUPS,
    EXPECTED_ROLLOUT_MODES,
    GATE_PATTERN,
    MINIMUM_APPROVALS,
    NON_WAIVABLE_LIVE_CONTROLS,
    ROLE_PATTERN,
)
from alpha_research_governance.change_risk.models import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ConditionalGateRule,
    DimensionPolicy,
    ReviewerGroup,
    RiskClass,
    RiskClassPolicy,
    SampleChange,
)

_EXPECTED_SCALARS: dict[str, object] = {
    "schema_version": 1,
    "roadmap_package": "A04",
    "operating_track": "solo_bootstrap",
    "author_may_lower_classification": False,
    "author_may_satisfy_independent_review": False,
}
_SAMPLE_BOOLEAN_FIELDS = frozenset({"capital_at_risk", *APPLICABILITY_TRIGGERS})


class _ExtensibleInput(ImmutableModel):
    """Provide a strict typed TOML boundary that retains unknown fields.

    The inherited model configuration keeps known fields strict and the model
    shallowly frozen while allowing extension fields for compatibility.
    Attribute reassignment is blocked, but contained mutable lists are not deep
    frozen. This boundary performs no change-risk semantic checks; the loader
    projects the accepted fields into domain models later.
    """

    model_config = ConfigDict(extra="allow")


class _DimensionLevelInput(_ExtensibleInput):
    """Hold one dimension value and its declared minimum class.

    The boundary accepts a Boolean or string ``value`` and a string
    ``minimum_class`` with strict field types. It permits unknown fields through
    ``_ExtensibleInput`` and does not enforce non-empty strings, known risk
    classes, or ordering. The closed ``_DimensionsInput`` supplies the allowed
    dimension names; ``_parse_dimension`` applies the per-name value and class
    semantics.

    Attributes:
        value: Boolean for ``capital_at_risk`` or a policy token for other
            dimensions.
        minimum_class: Text representation of the minimum R0-R4 class.
    """

    value: bool | str
    minimum_class: str


class _DimensionsInput(ImmutableModel):
    """Hold the five closed dimension tables at the structural boundary.

    The model requires exactly the declared dimension fields with strict list
    and nested-model types; unknown root fields are rejected and lists may be
    empty at this stage. The parser later requires the fixed capital mapping
    ``False -> R0`` and ``True -> R4``; other dimensions retain caller-defined
    non-empty string values but must provide minimum classes in R0-R4 order.
    Duplicate values and those semantic mappings are checked by
    ``_parse_dimension``.

    Attributes:
        capital_at_risk: Boolean-valued dimension levels.
        blast_radius: Blast-radius dimension levels.
        data_model_materiality: Data/model-materiality dimension levels.
        security_privilege: Security-privilege dimension levels.
        reversibility: Reversibility dimension levels.
    """

    capital_at_risk: list[_DimensionLevelInput]
    blast_radius: list[_DimensionLevelInput]
    data_model_materiality: list[_DimensionLevelInput]
    security_privilege: list[_DimensionLevelInput]
    reversibility: list[_DimensionLevelInput]


class _ConditionalGateRuleInput(_ExtensibleInput):
    """Hold one conditional trigger and its gate list before semantic checks.

    Strict field types are required, while unknown fields, empty strings and
    empty gate lists remain accepted by this extensible boundary. Trigger names,
    gate syntax, duplicate handling and the blueprint mapping are enforced by
    ``_parse_class``.

    Attributes:
        trigger: Applicability fact name supplied by the policy.
        gates: Gate identifiers activated by the trigger.
    """

    trigger: str
    gates: list[str]


class _ReviewerGroupInput(_ExtensibleInput):
    """Hold one reviewer-group record before semantic policy checks.

    The boundary requires strict field types and permits unknown fields, but it
    does not yet check role syntax, non-empty or unique roles, approval floors,
    or group identity uniqueness.

    Attributes:
        group_id: Reviewer-group identifier.
        roles: Role identifiers that can satisfy the group.
        minimum_approvals: Required reviewer count for this group.
        independent: Whether the group requires independent review.
    """

    group_id: str
    roles: list[str]
    minimum_approvals: int
    independent: bool


class _RiskClassInput(_ExtensibleInput):
    """Hold one risk-class rule set with strict field types.

    Unknown fields are retained by the extensible boundary. Empty lists,
    negative integers, unsupported gate or rollout tokens, duplicate entries,
    reviewer mappings and class-specific control floors are structurally
    deferred to field-specific checks in ``_parse_class``. An empty conditional
    rule list can be valid, while duplicate trigger records are retained and
    the final record for each trigger controls the comparison mapping.

    Attributes:
        mandatory_gates: Unconditional gate identifiers.
        conditional_gate_rules: Trigger-to-gate records.
        minimum_approvals: Minimum merge approvals declared for the class.
        minimum_independent_approvals: Minimum independent approvals.
        minimum_activation_approvals: Minimum activation approvals.
        hard_control_waiver_allowed: Whether hard-control waivers are declared allowed.
        rollout_modes: Permitted rollout mode tokens.
        evidence_retention_class: Retention-class token.
        reviewer_groups: Reviewer-group records.
    """

    mandatory_gates: list[str]
    conditional_gate_rules: list[_ConditionalGateRuleInput]
    minimum_approvals: int
    minimum_independent_approvals: int
    minimum_activation_approvals: int
    hard_control_waiver_allowed: bool
    rollout_modes: list[str]
    evidence_retention_class: str
    reviewer_groups: list[_ReviewerGroupInput]


class _RiskClassesInput(ImmutableModel):
    """Hold exactly one structural rule table for each R0-R4 class.

    The root is closed: all five class fields are required and unknown class
    fields are rejected. Nested class fields use the extensible input model, so
    their semantic gate, reviewer, approval, rollout and retention requirements
    are validated later by ``_parse_class``.

    Attributes:
        R0: Structural input for the R0 policy.
        R1: Structural input for the R1 policy.
        R2: Structural input for the R2 policy.
        R3: Structural input for the R3 policy.
        R4: Structural input for the R4 policy.
    """

    R0: _RiskClassInput
    R1: _RiskClassInput
    R2: _RiskClassInput
    R3: _RiskClassInput
    R4: _RiskClassInput


class _SampleChangeInput(_ExtensibleInput):
    """Hold one retained sample change with strict fields and false defaults.

    Unknown fields are retained at this boundary. The three applicability
    booleans default to ``False`` when omitted; all five dimensions, the change
    ID and expected class remain required strings or Boolean as declared. This
    model checks field shape only; non-empty values and supported classes are
    checked by ``_parse_sample_change`` and the classifier.

    Attributes:
        change_id: Stable sample identifier.
        capital_at_risk: Capital-risk Boolean dimension.
        blast_radius: Blast-radius token.
        data_model_materiality: Data/model-materiality token.
        security_privilege: Security-privilege token.
        reversibility: Reversibility token.
        computationally_material: Optional applicability fact; defaults to ``False``.
        economically_or_risk_relevant: Optional applicability fact; defaults to ``False``.
        model_or_trading_relevant: Optional applicability fact; defaults to ``False``.
        expected_class: Expected R0-R4 class text.
    """

    change_id: str
    capital_at_risk: bool
    blast_radius: str
    data_model_materiality: str
    security_privilege: str
    reversibility: str
    computationally_material: bool = False
    economically_or_risk_relevant: bool = False
    model_or_trading_relevant: bool = False
    expected_class: str


class _FindingInput(_ExtensibleInput):
    """Hold one retained finding with strict string fields.

    Unknown fields are retained by the input boundary, and empty strings are
    structurally accepted. The loader later requires every field to be truthy,
    rejects duplicate finding IDs, and checks the exact finding sequence for a
    partial package.

    Attributes:
        finding_id: Finding identifier.
        owner_role: Accountable role for the finding.
        unavailable_evidence: Evidence that is currently unavailable.
        closure_condition: Condition that closes the finding.
    """

    finding_id: str
    owner_role: str
    unavailable_evidence: str
    closure_condition: str


class _ChangeRiskPolicyInput(_ExtensibleInput):
    """Hold the complete TOML document before semantic policy validation.

    Known fields use strict types and the root remains extensible for compatible
    policy additions. ``validation_evidence`` defaults to ``None`` and is
    checked only for a validated package status; partial status skips that
    field's boundary-content check. The nested closed models enforce the
    dimension and R0-R4 class keys structurally; this root model does not
    enforce exact scalar values, control floors, findings, or sample coverage.

    Attributes:
        schema_version: Policy schema version.
        roadmap_package: Roadmap package identifier.
        operating_track: Operating-track token.
        author_may_lower_classification: Whether declarations may lower risk.
        author_may_satisfy_independent_review: Whether authors may satisfy
            independent review.
        hard_controls: Declared hard-control identifiers.
        dimensions: Closed structural dimension table.
        risk_classes: Closed structural R0-R4 table.
        package_status: Package status token.
        sample_changes: Retained classifier examples.
        findings: Retained finding records.
        validation_evidence: Evidence references for validated status; defaults
            to ``None``.
    """

    schema_version: int
    roadmap_package: str
    operating_track: str
    author_may_lower_classification: bool
    author_may_satisfy_independent_review: bool
    hard_controls: list[str]
    dimensions: _DimensionsInput
    risk_classes: _RiskClassesInput
    package_status: str
    sample_changes: list[_SampleChangeInput]
    findings: list[_FindingInput]
    validation_evidence: object | None = None


_DIMENSION_KEYS = frozenset(_DimensionsInput.model_fields)
_RISK_CLASS_KEYS = frozenset(_RiskClassesInput.model_fields)
_STRING_LIST_ADAPTER = TypeAdapter(list[str], config=ConfigDict(strict=True))


def _dimension_input_error(
    path: Path, location: tuple[int | str, ...], error_type: str
) -> ChangeRiskPolicyError:
    """Translate one dimension-model validation location into a domain error.

    Args:
        path: Policy file path used in root-level diagnostics.
        location: Pydantic error location identifying the dimension field or
            indexed level.
        error_type: Pydantic error kind, used to recognize missing or unknown
            root dimension fields.

    Returns:
        A ``ChangeRiskPolicyError`` describing the most specific supported
        structural failure for the location.

    Notes:
        The caller raises the returned error from the original Pydantic
        ``ValidationError``. This helper does not perform semantic dimension
        validation or raise the returned exception itself.
    """
    if len(location) == 1:
        return ChangeRiskPolicyError(f"{path}: dimensions must be a TOML table")
    if len(location) == 2 and error_type in {"missing", "extra_forbidden"}:
        return ChangeRiskPolicyError(
            f"{path}: dimensions must be exactly {sorted(_DIMENSION_KEYS)}"
        )
    name = str(location[1])
    if len(location) < 4 or not isinstance(location[2], int):
        return ChangeRiskPolicyError(f"dimensions.{name} must be an array of TOML tables")
    context = f"dimensions.{name}[{location[2] + 1}]"
    field = str(location[3])
    if field == "value":
        qualifier = "Boolean" if name == "capital_at_risk" else "a string"
        return ChangeRiskPolicyError(f"{context}.value must be {qualifier}")
    if field == "minimum_class":
        return ChangeRiskPolicyError(f"{context}.minimum_class must be an R0-R4 string")
    return ChangeRiskPolicyError(f"{path}: policy model validation failed")


def _risk_class_input_error(
    path: Path, location: tuple[int | str, ...], error_type: str
) -> ChangeRiskPolicyError:
    """Translate one risk-class model error into a stable domain diagnostic.

    Args:
        path: Policy file path used in root-level diagnostics.
        location: Pydantic error location for the class or nested field.
        error_type: Pydantic error kind, used for missing or unknown root
            class fields.

    Returns:
        A ``ChangeRiskPolicyError`` describing the recognized structural shape
        failure, with a one-based index for conditional rules or reviewer
        groups when available.

    Notes:
        This helper reports field shape only. ``_parse_class`` performs the
        semantic gate, reviewer, approval, rollout and retention checks later.
    """
    if len(location) == 1:
        return ChangeRiskPolicyError(f"{path}: risk_classes must be a TOML table")
    if len(location) == 2 and error_type in {"missing", "extra_forbidden"}:
        return ChangeRiskPolicyError(f"{path}: risk_classes must be exactly R0-R4")

    risk_class = str(location[1])
    context = f"risk_classes.{risk_class}"
    if len(location) == 2:
        return ChangeRiskPolicyError(f"{context} must be a TOML table")
    field = str(location[2])
    if field in {"mandatory_gates", "rollout_modes"}:
        return ChangeRiskPolicyError(f"{context}.{field} must be an array of strings")
    if field in {
        "minimum_approvals",
        "minimum_independent_approvals",
        "minimum_activation_approvals",
    }:
        return ChangeRiskPolicyError(f"{context}.{field} must be a non-negative integer")
    if field == "hard_control_waiver_allowed":
        return ChangeRiskPolicyError(f"{context}.{field} must be Boolean")
    if field == "evidence_retention_class":
        return ChangeRiskPolicyError(f"{context}.{field} must be lower_snake_case")
    if field == "conditional_gate_rules":
        rules_context = f"{context}.conditional_gate_rules"
        if len(location) < 5 or not isinstance(location[3], int):
            return ChangeRiskPolicyError(f"{rules_context} must be an array of TOML tables")
        rule_context = f"{rules_context}[{location[3] + 1}]"
        rule_field = str(location[4])
        if rule_field == "trigger":
            return ChangeRiskPolicyError(f"{rule_context} has bad trigger")
        if rule_field == "gates":
            return ChangeRiskPolicyError(f"{rule_context}.gates must be an array of strings")
    if field == "reviewer_groups":
        groups_context = f"{context}.reviewer_groups"
        if len(location) < 5 or not isinstance(location[3], int):
            return ChangeRiskPolicyError(f"{groups_context} must be an array of TOML tables")
        group_context = f"{groups_context}[{location[3] + 1}]"
        group_field = str(location[4])
        if group_field == "group_id":
            return ChangeRiskPolicyError(f"{group_context}.group_id must be lower_snake_case")
        if group_field == "roles":
            return ChangeRiskPolicyError(f"{group_context}.roles must be an array of strings")
        if group_field == "minimum_approvals":
            return ChangeRiskPolicyError(
                f"{group_context}.minimum_approvals must be a non-negative integer"
            )
        if group_field == "independent":
            return ChangeRiskPolicyError(f"{group_context}.independent must be Boolean")
    return ChangeRiskPolicyError(f"{path}: policy model validation failed")


def _sample_input_error(path: Path, location: tuple[int | str, ...]) -> ChangeRiskPolicyError:
    """Translate one retained-sample model error into a domain diagnostic.

    Args:
        path: Policy file path used when the sample collection itself is
            malformed.
        location: Pydantic error location for the sample or one of its fields.

    Returns:
        A ``ChangeRiskPolicyError`` with a one-based sample index and a
        field-specific type message when the location is recognized.

    Notes:
        Applicability flags omitted from the input model use their ``False``
        defaults, so this helper handles only fields that Pydantic reports as
        invalid or missing.
    """
    if len(location) < 3 or not isinstance(location[1], int):
        return ChangeRiskPolicyError(f"{path}: sample_changes must be an array of TOML tables")
    context = f"sample_changes[{location[1] + 1}]"
    field = str(location[2])
    if field == "change_id" or field in {
        "blast_radius",
        "data_model_materiality",
        "security_privilege",
        "reversibility",
    }:
        return ChangeRiskPolicyError(f"{context}.{field} must be a non-empty string")
    if field in _SAMPLE_BOOLEAN_FIELDS:
        return ChangeRiskPolicyError(f"{context}.{field} must be Boolean")
    if field == "expected_class":
        return ChangeRiskPolicyError(f"{context}.expected_class must be an R0-R4 string")
    return ChangeRiskPolicyError(f"{path}: policy model validation failed")


def _policy_input_error(path: Path, error: ValidationError) -> ChangeRiskPolicyError:
    """Choose the public structural error for a Pydantic policy failure.

    Args:
        path: Policy file path included in the returned diagnostic.
        error: Pydantic validation failure from the root input model.

    Returns:
        A ``ChangeRiskPolicyError``. Missing or extra dimension/class root
        fields take priority across all reported details; otherwise the first
        Pydantic detail is mapped to a field-specific message when supported.

    Notes:
        The caller preserves ``error`` as the exception cause. This function
        does not validate policy semantics or raise the returned error.
    """
    details = error.errors(include_url=False, include_input=False)
    for root_field, expected_keys in (
        ("dimensions", _DIMENSION_KEYS),
        ("risk_classes", _RISK_CLASS_KEYS),
    ):
        if any(
            len(detail["loc"]) == 2
            and detail["loc"][0] == root_field
            and detail["type"] in {"missing", "extra_forbidden"}
            for detail in details
        ):
            if root_field == "dimensions":
                return ChangeRiskPolicyError(
                    f"{path}: dimensions must be exactly {sorted(expected_keys)}"
                )
            return ChangeRiskPolicyError(f"{path}: risk_classes must be exactly R0-R4")

    detail = details[0]
    location = detail["loc"]
    error_type = detail["type"]
    if not location:
        return ChangeRiskPolicyError(f"{path} must be a TOML table")

    root_field = str(location[0])
    if root_field in _EXPECTED_SCALARS:
        scalar_expected = _EXPECTED_SCALARS[root_field]
        return ChangeRiskPolicyError(f"{path}: {root_field} must be {scalar_expected!r}")
    if root_field == "dimensions":
        return _dimension_input_error(path, location, error_type)
    if root_field == "risk_classes":
        return _risk_class_input_error(path, location, error_type)
    if root_field == "hard_controls":
        return ChangeRiskPolicyError(f"{path}: hard_controls must be an array of strings")
    if root_field == "findings":
        if len(location) < 3 or not isinstance(location[1], int):
            return ChangeRiskPolicyError(f"{path}: findings must be an array of TOML tables")
        return ChangeRiskPolicyError(
            f"{path}: findings[{location[1] + 1}].{location[2]} is required"
        )
    if root_field == "package_status":
        return ChangeRiskPolicyError(f"{path}: package_status must be partial or validated")
    if root_field == "sample_changes":
        return _sample_input_error(path, location)
    return ChangeRiskPolicyError(f"{path}: policy model validation failed")


def _validated_string_list(value: list[str], *, context: str) -> tuple[str, ...]:
    """Require a non-empty list with unique values while preserving order.

    Args:
        value: Typed string list to inspect. Empty string elements are allowed
            by this helper; callers apply any token or non-empty checks needed
            for their field.
        context: Field path used in the domain error.

    Returns:
        A tuple containing the original values in list order.

    Raises:
        ChangeRiskPolicyError: If the list is empty or contains duplicate
            values.
    """
    if not value or len(value) != len(set(value)):
        raise ChangeRiskPolicyError(f"{context} must contain unique non-empty values")
    return tuple(value)


def _validated_boundary_string_list(value: object, *, context: str) -> tuple[str, ...]:
    """Validate a boundary value as a strict unique string list.

    Args:
        value: Untrusted boundary value expected to be a list whose elements
            are strings; no coercion is performed.
        context: Field path used in the domain error.

    Returns:
        The validated values as a tuple in their original order. Empty string
            elements remain possible because the uniqueness helper does not
            reject them.

    Raises:
        ChangeRiskPolicyError: If the value is not a strict string list, is
            empty, or contains duplicates. Type-shape failures preserve the
            Pydantic validation error as their cause.
    """
    try:
        strings = _STRING_LIST_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise ChangeRiskPolicyError(f"{context} must be an array of strings") from error
    return _validated_string_list(strings, context=context)


def _validated_nonnegative_int(value: int, *, context: str) -> int:
    """Reject a negative integer without changing the accepted value.

    Args:
        value: Integer already type-checked by the input model.
        context: Field path used in the domain error.

    Returns:
        The original non-negative integer.

    Raises:
        ChangeRiskPolicyError: If ``value`` is less than zero.
    """
    if value < 0:
        raise ChangeRiskPolicyError(f"{context} must be a non-negative integer")
    return value


def _validated_nonempty_string(value: str, *, context: str) -> str:
    """Require a truthy string and preserve its exact spelling.

    Args:
        value: String already type-checked by the input model; whitespace is
            not stripped.
        context: Field path used in the domain error.

    Returns:
        The original string without normalization.

    Raises:
        ChangeRiskPolicyError: If ``value`` is empty.
    """
    if not value:
        raise ChangeRiskPolicyError(f"{context} must be a non-empty string")
    return value


def _parse_risk_class(value: str, *, context: str) -> RiskClass:
    """Parse an R0-R4 token into its enum member.

    Args:
        value: Risk-class token to parse without case or whitespace
            normalization.
        context: Field path used in the domain error.

    Returns:
        The matching ``RiskClass`` member.

    Raises:
        ChangeRiskPolicyError: If ``value`` is not exactly one of ``R0``
            through ``R4``; the enum error is preserved as the cause.
    """
    try:
        return RiskClass(value)
    except ValueError as error:
        raise ChangeRiskPolicyError(f"{context} must be one of R0, R1, R2, R3, R4") from error


def _parse_dimension(name: str, value: list[_DimensionLevelInput]) -> DimensionPolicy:
    """Validate one dimension's levels and project them to a domain policy.

    Args:
        name: Dimension name used in diagnostics. ``capital_at_risk`` receives
            its Boolean-specific contract; every other name uses the ordered
            R0-R4 level contract.
        value: Structural dimension levels in policy-file order.

    Returns:
        An immutable ``DimensionPolicy`` retaining the input level order and
        parsed ``RiskClass`` members.

    Raises:
        ChangeRiskPolicyError: If a value has the wrong dimension type, is
            empty, has an unsupported class, duplicates an earlier value with
            the same exact type, or violates the exact capital or ordered R0-R4
            mapping. String values are not normalized.
    """
    levels: list[tuple[bool | str, RiskClass]] = []
    for index, entry in enumerate(value, start=1):
        level_value = entry.value
        if name == "capital_at_risk":
            if not isinstance(level_value, bool):
                raise ChangeRiskPolicyError(f"dimensions.{name}[{index}].value must be Boolean")
        elif not isinstance(level_value, str) or not level_value:
            raise ChangeRiskPolicyError(f"dimensions.{name}[{index}].value must be a string")
        minimum = _parse_risk_class(
            entry.minimum_class, context=f"dimensions.{name}[{index}].minimum_class"
        )
        typed_value = level_value
        if any(
            type(existing) is type(typed_value) and existing == typed_value
            for existing, _ in levels
        ):
            raise ChangeRiskPolicyError(f"dimensions.{name}: duplicate value {typed_value!r}")
        levels.append((typed_value, minimum))

    if name == "capital_at_risk":
        if levels != [(False, RiskClass.R0), (True, RiskClass.R4)]:
            raise ChangeRiskPolicyError("capital_at_risk must map false to R0 and true to R4")
    elif [minimum for _, minimum in levels] != list(RiskClass):
        raise ChangeRiskPolicyError(f"dimensions.{name} must provide one ordered level for R0-R4")
    return DimensionPolicy(name=name, levels=tuple(levels))


def _parse_reviewer_group(value: _ReviewerGroupInput, *, context: str) -> ReviewerGroup:
    """Validate and project one reviewer group into an immutable record.

    Args:
        value: Strictly typed reviewer-group input.
        context: Field path used in validation findings.

    Returns:
        A ``ReviewerGroup`` whose roles are projected to a ``frozenset``;
        input role order is therefore not retained in the domain record.

    Raises:
        ChangeRiskPolicyError: If the group ID or roles are not lower_snake_case,
            the role list is empty or duplicated, or the approval count is
            negative or below one.
    """
    if ROLE_PATTERN.fullmatch(value.group_id) is None:
        raise ChangeRiskPolicyError(f"{context}.group_id must be lower_snake_case")
    roles = _validated_string_list(value.roles, context=f"{context}.roles")
    if any(ROLE_PATTERN.fullmatch(role) is None for role in roles):
        raise ChangeRiskPolicyError(f"{context}.roles must be lower_snake_case")
    minimum = _validated_nonnegative_int(
        value.minimum_approvals, context=f"{context}.minimum_approvals"
    )
    if minimum < 1:
        raise ChangeRiskPolicyError(f"{context}.minimum_approvals must be at least one")
    return ReviewerGroup(
        group_id=value.group_id,
        roles=frozenset(roles),
        minimum_approvals=minimum,
        independent=value.independent,
    )


def _parse_class(risk_class: RiskClass, value: _RiskClassInput) -> RiskClassPolicy:
    """Validate one class rule set against the immutable blueprint bounds.

    Args:
        risk_class: Class whose blueprint requirements are being checked.
        value: Strictly typed class input, including gates, reviewer groups,
            approval floors, rollout modes and retention token.

    Returns:
        A ``RiskClassPolicy`` retaining mandatory-gate, conditional-rule,
        reviewer-group and rollout order from the input. Reviewer roles are
        normalized to frozensets by ``_parse_reviewer_group``.

    Raises:
        ChangeRiskPolicyError: If any check fails, in validation order:
            mandatory gates must be valid, unique and include the blueprint
            minimum; each conditional rule must be valid and the final rule for
            a repeated trigger determines the comparison mapping; reviewer
            groups must be valid, unique and exactly match the blueprint;
            approval and activation counts must meet their minimums; R4 cannot
            permit hard-control waivers; rollout modes and retention must match
            the exact blueprint values. Extra mandatory gates are permitted,
            while rollout and retention values are exact.
    """
    context = f"risk_classes.{risk_class.value}"
    gates = _validated_string_list(value.mandatory_gates, context=f"{context}.mandatory_gates")
    if any(GATE_PATTERN.fullmatch(gate) is None for gate in gates):
        raise ChangeRiskPolicyError(f"{context}.mandatory_gates contains an invalid gate")
    missing = BLUEPRINT_REQUIRED_GATES[risk_class.value] - set(gates)
    if missing:
        raise ChangeRiskPolicyError(f"{context} weakens mandatory gates: {sorted(missing)}")

    conditional_rules: list[ConditionalGateRule] = []
    for index, rule in enumerate(value.conditional_gate_rules, start=1):
        if rule.trigger not in APPLICABILITY_TRIGGERS:
            raise ChangeRiskPolicyError(
                f"{context}.conditional_gate_rules[{index}] has bad trigger"
            )
        rule_gates = _validated_string_list(
            rule.gates, context=f"{context}.conditional_gate_rules[{index}].gates"
        )
        if any(GATE_PATTERN.fullmatch(gate) is None for gate in rule_gates):
            raise ChangeRiskPolicyError(f"{context}.conditional_gate_rules[{index}] has bad gate")
        conditional_rules.append(ConditionalGateRule(trigger=rule.trigger, gates=rule_gates))
    actual_conditional = {rule.trigger: set(rule.gates) for rule in conditional_rules}
    if actual_conditional != BLUEPRINT_CONDITIONAL_GATES[risk_class.value]:
        raise ChangeRiskPolicyError(f"{context}.conditional_gate_rules must match the blueprint")

    reviewer_groups = tuple(
        _parse_reviewer_group(group, context=f"{context}.reviewer_groups[{index}]")
        for index, group in enumerate(value.reviewer_groups, start=1)
    )
    group_ids = [group.group_id for group in reviewer_groups]
    if len(group_ids) != len(set(group_ids)):
        raise ChangeRiskPolicyError(f"{context}.reviewer_groups has duplicate group_id values")
    actual_reviewer_groups = {
        group.group_id: (group.roles, group.minimum_approvals, group.independent)
        for group in reviewer_groups
    }
    if actual_reviewer_groups != EXPECTED_REVIEWER_GROUPS[risk_class.value]:
        raise ChangeRiskPolicyError(f"{context}.reviewer_groups must match the blueprint mapping")

    minimum_approvals = _validated_nonnegative_int(
        value.minimum_approvals, context=f"{context}.minimum_approvals"
    )
    minimum_independent = _validated_nonnegative_int(
        value.minimum_independent_approvals,
        context=f"{context}.minimum_independent_approvals",
    )
    minimum_activation = _validated_nonnegative_int(
        value.minimum_activation_approvals,
        context=f"{context}.minimum_activation_approvals",
    )
    if minimum_approvals < MINIMUM_APPROVALS[risk_class.value]:
        raise ChangeRiskPolicyError(f"{context}.minimum_approvals weakens the blueprint")
    if risk_class.rank >= RiskClass.R1.rank and minimum_independent < 1:
        raise ChangeRiskPolicyError(f"{context} requires an independent reviewer")
    group_approvals = sum(group.minimum_approvals for group in reviewer_groups)
    if minimum_approvals < group_approvals:
        raise ChangeRiskPolicyError(f"{context}.minimum_approvals cannot omit a reviewer group")
    independent_group_approvals = sum(
        group.minimum_approvals for group in reviewer_groups if group.independent
    )
    if minimum_independent < independent_group_approvals:
        raise ChangeRiskPolicyError(
            f"{context}.minimum_independent_approvals cannot omit an independent group"
        )

    if risk_class is RiskClass.R4 and value.hard_control_waiver_allowed:
        raise ChangeRiskPolicyError("R4 cannot permit a hard-control waiver")
    if risk_class is RiskClass.R4 and minimum_activation < 2:
        raise ChangeRiskPolicyError("R4 requires dual-control activation")

    rollout_modes = _validated_string_list(value.rollout_modes, context=f"{context}.rollout_modes")
    if rollout_modes != EXPECTED_ROLLOUT_MODES[risk_class.value]:
        raise ChangeRiskPolicyError(f"{context}.rollout_modes must match the blueprint mapping")
    retention = value.evidence_retention_class
    if ROLE_PATTERN.fullmatch(retention) is None:
        raise ChangeRiskPolicyError(f"{context}.evidence_retention_class must be lower_snake_case")
    if retention != EXPECTED_RETENTION_CLASSES[risk_class.value]:
        raise ChangeRiskPolicyError(f"{context}.evidence_retention_class cannot be weakened")
    return RiskClassPolicy(
        risk_class=risk_class,
        mandatory_gates=gates,
        conditional_gate_rules=tuple(conditional_rules),
        reviewer_groups=reviewer_groups,
        minimum_approvals=minimum_approvals,
        minimum_independent_approvals=minimum_independent,
        minimum_activation_approvals=minimum_activation,
        hard_control_waiver_allowed=value.hard_control_waiver_allowed,
        rollout_modes=rollout_modes,
        evidence_retention_class=retention,
    )


def _parse_sample_change(value: _SampleChangeInput, *, index: int) -> SampleChange:
    """Validate one retained example and project it to a sample change.

    Args:
        value: Strictly typed sample input, including its optional applicability
            flags and expected class token.
        index: One-based sample index used in validation messages.

    Returns:
        A ``SampleChange`` containing a typed ``ChangeRiskInput`` and parsed
        expected ``RiskClass``. Dimension strings are preserved without
        normalization.

    Raises:
        ChangeRiskPolicyError: If the ID or any dimension string is empty, or
            the expected class is not R0-R4.
        ValidationError: If construction of a typed domain model fails after
            the boundary checks.
    """
    context = f"sample_changes[{index}]"
    change_id = _validated_nonempty_string(value.change_id, context=f"{context}.change_id")
    change = ChangeRiskInput(
        capital_at_risk=value.capital_at_risk,
        blast_radius=_validated_nonempty_string(
            value.blast_radius, context=f"{context}.blast_radius"
        ),
        data_model_materiality=_validated_nonempty_string(
            value.data_model_materiality,
            context=f"{context}.data_model_materiality",
        ),
        security_privilege=_validated_nonempty_string(
            value.security_privilege, context=f"{context}.security_privilege"
        ),
        reversibility=_validated_nonempty_string(
            value.reversibility, context=f"{context}.reversibility"
        ),
        computationally_material=value.computationally_material,
        economically_or_risk_relevant=value.economically_or_risk_relevant,
        model_or_trading_relevant=value.model_or_trading_relevant,
    )
    expected = _parse_risk_class(value.expected_class, context=f"{context}.expected_class")
    return SampleChange(change_id=change_id, change=change, expected_class=expected)


class _ChangeRiskPolicyLoader:
    """Load and semantically project one blueprint change-risk policy path."""

    def __init__(self, path: Path) -> None:
        """Bind the policy path without performing I/O."""
        self._path = path

    def _load(self) -> ChangeRiskPolicy:
        """Load the TOML policy and validate its complete semantic contract.

        Validation first parses the strict structural input model, then checks
        exact metadata, parses dimensions in sorted-name order and classes in R0-R4
        order, validates the non-waivable hard-control minimum (extra controls are
        allowed) and findings, applies package-status rules, projects retained
        samples, and finally reclassifies every sample through
        ``ChangeRiskClassifier``. Partial status requires the exact ordered
        open-finding IDs; samples require unique IDs and coverage of every R0-R4
        expected class, while additional samples are allowed. Validated status is
        rejected for ``solo_bootstrap`` before any validation-evidence list is
        checked. The output projection drops extensible input fields and freezes
        the top-level domain model shallowly.

        Returns:
            The fully validated immutable ``ChangeRiskPolicy``.

        Raises:
            ChangeRiskPolicyError: If TOML syntax, structural input, exact metadata,
                semantic policy bounds, package status, findings, sample coverage,
                or sample classifier results fail. Structural and TOML failures are
                translated with their original causes where handled; domain errors
                from semantic helpers propagate unchanged.
            OSError: If the policy file cannot be opened or read.
            UnicodeDecodeError: If the policy file is not valid UTF-8.
            ValidationError: If an unhandled Pydantic validation failure occurs
                during domain-model projection; the public ``load_policy`` wrapper
                translates it to ``ChangeRiskPolicyError``.
        """
        path = self._path
        try:
            parsed_document: object = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise ChangeRiskPolicyError(f"{path}: invalid TOML: {error}") from error
        try:
            policy_document = _ChangeRiskPolicyInput.model_validate(parsed_document)
        except ValidationError as error:
            raise _policy_input_error(path, error) from error

        actual_scalars: dict[str, object] = {
            "schema_version": policy_document.schema_version,
            "roadmap_package": policy_document.roadmap_package,
            "operating_track": policy_document.operating_track,
            "author_may_lower_classification": policy_document.author_may_lower_classification,
            "author_may_satisfy_independent_review": (
                policy_document.author_may_satisfy_independent_review
            ),
        }
        for key, expected in _EXPECTED_SCALARS.items():
            if actual_scalars[key] != expected:
                raise ChangeRiskPolicyError(f"{path}: {key} must be {expected!r}")

        dimension_values = {
            "capital_at_risk": policy_document.dimensions.capital_at_risk,
            "blast_radius": policy_document.dimensions.blast_radius,
            "data_model_materiality": policy_document.dimensions.data_model_materiality,
            "security_privilege": policy_document.dimensions.security_privilege,
            "reversibility": policy_document.dimensions.reversibility,
        }
        dimensions = tuple(
            _parse_dimension(name, dimension_values[name]) for name in sorted(EXPECTED_DIMENSIONS)
        )

        class_values = {
            RiskClass.R0: policy_document.risk_classes.R0,
            RiskClass.R1: policy_document.risk_classes.R1,
            RiskClass.R2: policy_document.risk_classes.R2,
            RiskClass.R3: policy_document.risk_classes.R3,
            RiskClass.R4: policy_document.risk_classes.R4,
        }
        risk_classes = tuple(_parse_class(item, class_values[item]) for item in RiskClass)

        hard_controls = frozenset(
            _validated_string_list(policy_document.hard_controls, context=f"{path}: hard_controls")
        )
        missing_controls = NON_WAIVABLE_LIVE_CONTROLS - hard_controls
        if missing_controls:
            raise ChangeRiskPolicyError(f"{path}: missing hard controls {sorted(missing_controls)}")

        findings: list[str] = []
        for index, finding in enumerate(policy_document.findings, start=1):
            values = {
                "finding_id": finding.finding_id,
                "owner_role": finding.owner_role,
                "unavailable_evidence": finding.unavailable_evidence,
                "closure_condition": finding.closure_condition,
            }
            for key, value in values.items():
                if not value:
                    raise ChangeRiskPolicyError(f"{path}: findings[{index}].{key} is required")
            findings.append(finding.finding_id)
        if len(findings) != len(set(findings)):
            raise ChangeRiskPolicyError(f"{path}: finding IDs must be unique")

        package_status = policy_document.package_status
        if package_status == "partial":
            if tuple(findings) != CHANGE_RISK_OPEN_FINDING_IDS:
                raise ChangeRiskPolicyError(
                    f"{path}: partial status requires findings "
                    f"{list(CHANGE_RISK_OPEN_FINDING_IDS)!r}"
                )
        elif package_status == "validated":
            if policy_document.operating_track == "solo_bootstrap":
                raise ChangeRiskPolicyError(
                    f"{path}: solo_bootstrap packages cannot claim validated status"
                )
            if findings:
                raise ChangeRiskPolicyError(
                    f"{path}: validated status requires retained evidence and no findings"
                )
            _validated_boundary_string_list(
                policy_document.validation_evidence,
                context=f"{path}: validation_evidence",
            )
        else:
            raise ChangeRiskPolicyError(f"{path}: package_status must be partial or validated")

        samples = tuple(
            _parse_sample_change(sample, index=index)
            for index, sample in enumerate(policy_document.sample_changes, start=1)
        )
        sample_ids = [sample.change_id for sample in samples]
        if len(sample_ids) != len(set(sample_ids)) or {
            sample.expected_class for sample in samples
        } != set(RiskClass):
            raise ChangeRiskPolicyError(f"{path}: samples require unique IDs and coverage of R0-R4")

        policy = ChangeRiskPolicy(
            dimensions=dimensions,
            risk_classes=risk_classes,
            hard_controls=hard_controls,
            author_may_lower_classification=False,
            author_may_satisfy_independent_review=False,
            package_status=package_status,
            samples=samples,
            findings=tuple(findings),
        )
        classifier = ChangeRiskClassifier(policy)
        for sample in samples:
            actual = classifier.classify(sample.change).risk_class
            if actual is not sample.expected_class:
                raise ChangeRiskPolicyError(
                    f"{path}: sample {sample.change_id!r} expected {sample.expected_class.value}, "
                    f"got {actual.value}"
                )
        return policy


def load_policy(path: Path) -> ChangeRiskPolicy:
    """Load the change-risk policy while preserving its domain-error contract.

    Args:
        path: UTF-8 TOML policy file to validate. The file is not modified.

    Returns:
        The validated ``ChangeRiskPolicy`` produced by the policy loader service.

    Raises:
        ChangeRiskPolicyError: For errors already translated or raised by the
            policy loader, including malformed TOML, structural failures and
            semantic policy violations. An unhandled Pydantic validation error
            is translated to a generic policy-model failure with its cause.
        OSError: If opening or reading the policy file fails; filesystem errors
            propagate from the loader service.
        UnicodeDecodeError: If UTF-8 decoding fails; decoding errors are not
            caught by either loader layer.
    """
    try:
        return _ChangeRiskPolicyLoader(path)._load()
    except ValidationError as error:
        raise ChangeRiskPolicyError(f"{path}: policy model validation failed") from error
