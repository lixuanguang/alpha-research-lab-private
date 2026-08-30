"""Strict TOML parsing and blueprint-bound validation for the A04 policy."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from alpha_research.change_risk.classification import classify_change
from alpha_research.change_risk.constraints import (
    APPLICABILITY_TRIGGERS,
    BLUEPRINT_CONDITIONAL_GATES,
    BLUEPRINT_REQUIRED_GATES,
    EXPECTED_DIMENSIONS,
    EXPECTED_OPEN_FINDING_IDS,
    EXPECTED_RETENTION_CLASSES,
    EXPECTED_REVIEWER_GROUPS,
    EXPECTED_ROLLOUT_MODES,
    GATE_PATTERN,
    MINIMUM_APPROVALS,
    NON_WAIVABLE_LIVE_CONTROLS,
    ROLE_PATTERN,
)
from alpha_research.change_risk.models import (
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


def _as_table(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ChangeRiskPolicyError(f"{context} must be a TOML table")
    return cast(dict[str, object], value)


def _as_table_list(value: object, *, context: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ChangeRiskPolicyError(f"{context} must be an array of TOML tables")
    return cast(list[dict[str, object]], value)


def _as_string_list(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ChangeRiskPolicyError(f"{context} must be an array of strings")
    strings = cast(list[str], value)
    if not strings or len(strings) != len(set(strings)):
        raise ChangeRiskPolicyError(f"{context} must contain unique non-empty values")
    return tuple(strings)


def _as_nonnegative_int(value: object, *, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ChangeRiskPolicyError(f"{context} must be a non-negative integer")
    return value


def _risk_class(value: object, *, context: str) -> RiskClass:
    if not isinstance(value, str):
        raise ChangeRiskPolicyError(f"{context} must be an R0-R4 string")
    try:
        return RiskClass(value)
    except ValueError as error:
        raise ChangeRiskPolicyError(f"{context} must be one of R0, R1, R2, R3, R4") from error


def _parse_dimension(name: str, value: object) -> DimensionPolicy:
    entries = _as_table_list(value, context=f"dimensions.{name}")
    levels: list[tuple[bool | str, RiskClass]] = []
    for index, entry in enumerate(entries, start=1):
        level_value = entry.get("value")
        if name == "capital_at_risk":
            if not isinstance(level_value, bool):
                raise ChangeRiskPolicyError(f"dimensions.{name}[{index}].value must be Boolean")
        elif not isinstance(level_value, str) or not level_value:
            raise ChangeRiskPolicyError(f"dimensions.{name}[{index}].value must be a string")
        minimum = _risk_class(
            entry.get("minimum_class"), context=f"dimensions.{name}[{index}].minimum_class"
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


def _parse_reviewer_group(value: dict[str, object], *, context: str) -> ReviewerGroup:
    group_id = value.get("group_id")
    if not isinstance(group_id, str) or ROLE_PATTERN.fullmatch(group_id) is None:
        raise ChangeRiskPolicyError(f"{context}.group_id must be lower_snake_case")
    roles = _as_string_list(value.get("roles"), context=f"{context}.roles")
    if any(ROLE_PATTERN.fullmatch(role) is None for role in roles):
        raise ChangeRiskPolicyError(f"{context}.roles must be lower_snake_case")
    independent = value.get("independent")
    if not isinstance(independent, bool):
        raise ChangeRiskPolicyError(f"{context}.independent must be Boolean")
    minimum = _as_nonnegative_int(
        value.get("minimum_approvals"), context=f"{context}.minimum_approvals"
    )
    if minimum < 1:
        raise ChangeRiskPolicyError(f"{context}.minimum_approvals must be at least one")
    return ReviewerGroup(
        group_id=group_id,
        roles=frozenset(roles),
        minimum_approvals=minimum,
        independent=independent,
    )


def _parse_class(risk_class: RiskClass, value: object) -> RiskClassPolicy:
    context = f"risk_classes.{risk_class.value}"
    table = _as_table(value, context=context)
    gates = _as_string_list(table.get("mandatory_gates"), context=f"{context}.mandatory_gates")
    if any(GATE_PATTERN.fullmatch(gate) is None for gate in gates):
        raise ChangeRiskPolicyError(f"{context}.mandatory_gates contains an invalid gate")
    missing = BLUEPRINT_REQUIRED_GATES[risk_class.value] - set(gates)
    if missing:
        raise ChangeRiskPolicyError(f"{context} weakens mandatory gates: {sorted(missing)}")

    conditional_values = _as_table_list(
        table.get("conditional_gate_rules"), context=f"{context}.conditional_gate_rules"
    )
    conditional_rules: list[ConditionalGateRule] = []
    for index, rule in enumerate(conditional_values, start=1):
        trigger = rule.get("trigger")
        if not isinstance(trigger, str) or trigger not in APPLICABILITY_TRIGGERS:
            raise ChangeRiskPolicyError(
                f"{context}.conditional_gate_rules[{index}] has bad trigger"
            )
        rule_gates = _as_string_list(
            rule.get("gates"), context=f"{context}.conditional_gate_rules[{index}].gates"
        )
        if any(GATE_PATTERN.fullmatch(gate) is None for gate in rule_gates):
            raise ChangeRiskPolicyError(f"{context}.conditional_gate_rules[{index}] has bad gate")
        conditional_rules.append(ConditionalGateRule(trigger=trigger, gates=rule_gates))
    actual_conditional = {rule.trigger: set(rule.gates) for rule in conditional_rules}
    if actual_conditional != BLUEPRINT_CONDITIONAL_GATES[risk_class.value]:
        raise ChangeRiskPolicyError(f"{context}.conditional_gate_rules must match the blueprint")

    group_values = _as_table_list(
        table.get("reviewer_groups"), context=f"{context}.reviewer_groups"
    )
    reviewer_groups = tuple(
        _parse_reviewer_group(group, context=f"{context}.reviewer_groups[{index}]")
        for index, group in enumerate(group_values, start=1)
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

    minimum_approvals = _as_nonnegative_int(
        table.get("minimum_approvals"), context=f"{context}.minimum_approvals"
    )
    minimum_independent = _as_nonnegative_int(
        table.get("minimum_independent_approvals"),
        context=f"{context}.minimum_independent_approvals",
    )
    minimum_activation = _as_nonnegative_int(
        table.get("minimum_activation_approvals"),
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

    waiver_allowed = table.get("hard_control_waiver_allowed")
    if not isinstance(waiver_allowed, bool):
        raise ChangeRiskPolicyError(f"{context}.hard_control_waiver_allowed must be Boolean")
    if risk_class is RiskClass.R4 and waiver_allowed:
        raise ChangeRiskPolicyError("R4 cannot permit a hard-control waiver")
    if risk_class is RiskClass.R4 and minimum_activation < 2:
        raise ChangeRiskPolicyError("R4 requires dual-control activation")

    rollout_modes = _as_string_list(table.get("rollout_modes"), context=f"{context}.rollout_modes")
    if rollout_modes != EXPECTED_ROLLOUT_MODES[risk_class.value]:
        raise ChangeRiskPolicyError(f"{context}.rollout_modes must match the blueprint mapping")
    retention = table.get("evidence_retention_class")
    if not isinstance(retention, str) or ROLE_PATTERN.fullmatch(retention) is None:
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
        hard_control_waiver_allowed=waiver_allowed,
        rollout_modes=rollout_modes,
        evidence_retention_class=retention,
    )


def _sample_change(value: dict[str, object], *, index: int) -> SampleChange:
    context = f"sample_changes[{index}]"
    change_id = value.get("change_id")
    if not isinstance(change_id, str) or not change_id:
        raise ChangeRiskPolicyError(f"{context}.change_id must be a non-empty string")

    def required_string(key: str) -> str:
        result = value.get(key)
        if not isinstance(result, str) or not result:
            raise ChangeRiskPolicyError(f"{context}.{key} must be a non-empty string")
        return result

    capital_at_risk = value.get("capital_at_risk")
    if not isinstance(capital_at_risk, bool):
        raise ChangeRiskPolicyError(f"{context}.capital_at_risk must be Boolean")
    optional_flags: dict[str, bool] = {}
    for trigger in sorted(APPLICABILITY_TRIGGERS):
        trigger_value = value.get(trigger, False)
        if not isinstance(trigger_value, bool):
            raise ChangeRiskPolicyError(f"{context}.{trigger} must be Boolean")
        optional_flags[trigger] = trigger_value
    change = ChangeRiskInput(
        capital_at_risk=capital_at_risk,
        blast_radius=required_string("blast_radius"),
        data_model_materiality=required_string("data_model_materiality"),
        security_privilege=required_string("security_privilege"),
        reversibility=required_string("reversibility"),
        computationally_material=optional_flags["computationally_material"],
        economically_or_risk_relevant=optional_flags["economically_or_risk_relevant"],
        model_or_trading_relevant=optional_flags["model_or_trading_relevant"],
    )
    expected = _risk_class(value.get("expected_class"), context=f"{context}.expected_class")
    return SampleChange(change_id=change_id, change=change, expected_class=expected)


def _load_policy(path: Path) -> ChangeRiskPolicy:
    """Load and validate the complete A04 policy and its retained sample changes."""
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ChangeRiskPolicyError(f"{path}: invalid TOML: {error}") from error
    root = _as_table(parsed, context=str(path))
    expected_scalars: dict[str, object] = {
        "schema_version": 1,
        "roadmap_package": "A04",
        "operating_track": "solo_bootstrap",
        "author_may_lower_classification": False,
        "author_may_satisfy_independent_review": False,
    }
    for key, expected in expected_scalars.items():
        if root.get(key) != expected:
            raise ChangeRiskPolicyError(f"{path}: {key} must be {expected!r}")

    dimensions_table = _as_table(root.get("dimensions"), context=f"{path}: dimensions")
    if set(dimensions_table) != EXPECTED_DIMENSIONS:
        raise ChangeRiskPolicyError(
            f"{path}: dimensions must be exactly {sorted(EXPECTED_DIMENSIONS)}"
        )
    dimensions = tuple(
        _parse_dimension(name, dimensions_table[name]) for name in sorted(EXPECTED_DIMENSIONS)
    )

    classes_table = _as_table(root.get("risk_classes"), context=f"{path}: risk_classes")
    if set(classes_table) != {item.value for item in RiskClass}:
        raise ChangeRiskPolicyError(f"{path}: risk_classes must be exactly R0-R4")
    risk_classes = tuple(_parse_class(item, classes_table[item.value]) for item in RiskClass)

    hard_controls = frozenset(
        _as_string_list(root.get("hard_controls"), context=f"{path}: hard_controls")
    )
    missing_controls = NON_WAIVABLE_LIVE_CONTROLS - hard_controls
    if missing_controls:
        raise ChangeRiskPolicyError(f"{path}: missing hard controls {sorted(missing_controls)}")

    findings_values = _as_table_list(root.get("findings"), context=f"{path}: findings")
    findings: list[str] = []
    for index, finding in enumerate(findings_values, start=1):
        for key in ("finding_id", "owner_role", "unavailable_evidence", "closure_condition"):
            if not isinstance(finding.get(key), str) or not finding.get(key):
                raise ChangeRiskPolicyError(f"{path}: findings[{index}].{key} is required")
        findings.append(cast(str, finding["finding_id"]))
    if len(findings) != len(set(findings)):
        raise ChangeRiskPolicyError(f"{path}: finding IDs must be unique")

    package_status = root.get("package_status")
    if package_status == "partial":
        if tuple(findings) != EXPECTED_OPEN_FINDING_IDS:
            raise ChangeRiskPolicyError(
                f"{path}: partial status requires findings {list(EXPECTED_OPEN_FINDING_IDS)!r}"
            )
    elif package_status == "validated":
        if root.get("operating_track") == "solo_bootstrap":
            raise ChangeRiskPolicyError(
                f"{path}: solo_bootstrap packages cannot claim validated status"
            )
        if findings:
            raise ChangeRiskPolicyError(
                f"{path}: validated status requires retained evidence and no findings"
            )
        _as_string_list(root.get("validation_evidence"), context=f"{path}: validation_evidence")
    else:
        raise ChangeRiskPolicyError(f"{path}: package_status must be partial or validated")

    sample_values = _as_table_list(root.get("sample_changes"), context=f"{path}: sample_changes")
    samples = tuple(
        _sample_change(sample, index=index) for index, sample in enumerate(sample_values, start=1)
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
    for sample in samples:
        actual = classify_change(sample.change, policy).risk_class
        if actual is not sample.expected_class:
            raise ChangeRiskPolicyError(
                f"{path}: sample {sample.change_id!r} expected {sample.expected_class.value}, "
                f"got {actual.value}"
            )
    return policy


def load_policy(path: Path) -> ChangeRiskPolicy:
    """Load the A04 policy while preserving its public domain-error contract."""
    try:
        return _load_policy(path)
    except ValidationError as error:
        raise ChangeRiskPolicyError(f"{path}: policy model validation failed") from error
