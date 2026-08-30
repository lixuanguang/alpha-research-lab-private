"""Deterministic and adversarial tests for the A04 change-risk policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_research.change_risk import (
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ReviewApproval,
    RiskClass,
    classify_change,
    load_policy,
    main,
    validate_activation_approvals,
    validate_merge_approvals,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "change-risk-policy.toml"


@pytest.fixture
def policy() -> ChangeRiskPolicy:
    return load_policy(POLICY_PATH)


def _change_for(risk_class: RiskClass, *, declared: RiskClass | None = None) -> ChangeRiskInput:
    levels = {
        RiskClass.R0: (False, "documentation_only", "none", "none", "immediate"),
        RiskClass.R1: (
            False,
            "research_only",
            "research_local",
            "research_scoped",
            "reproducible_recompute",
        ),
        RiskClass.R2: (
            False,
            "shared_domain",
            "shared_or_candidate",
            "shared_sensitive",
            "compatibility_window",
        ),
        RiskClass.R3: (
            False,
            "non_capital_runtime",
            "production_serving",
            "nonproduction_privileged",
            "staged_operational_rollback",
        ),
        RiskClass.R4: (
            True,
            "capital_path",
            "capital_decision",
            "production_or_market_access",
            "capital_state_reconciliation",
        ),
    }
    capital, blast, materiality, privilege, reversibility = levels[risk_class]
    return ChangeRiskInput(
        capital_at_risk=capital,
        blast_radius=blast,
        data_model_materiality=materiality,
        security_privilege=privilege,
        reversibility=reversibility,
        declared_class=declared,
    )


def _r4_approvals() -> tuple[ReviewApproval, ...]:
    return (
        ReviewApproval(reviewer_id="owner", roles=frozenset({"domain_owner"})),
        ReviewApproval(
            reviewer_id="risk",
            roles=frozenset({"independent_risk"}),
            independent=True,
        ),
        ReviewApproval(reviewer_id="sre", roles=frozenset({"sre"}), independent=True),
        ReviewApproval(
            reviewer_id="security",
            roles=frozenset({"security"}),
            independent=True,
        ),
    )


def _validated_change_update(
    change: ChangeRiskInput, **updates: bool | RiskClass | None
) -> ChangeRiskInput:
    values = change.model_dump()
    values.update(updates)
    return ChangeRiskInput.model_validate(values)


def _mutated_policy(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "change-risk-policy.toml"
    text = POLICY_PATH.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_repository_policy_is_valid_partial_and_covers_every_class() -> None:
    loaded = validate_repository(REPOSITORY_ROOT)

    assert loaded.package_status == "partial"
    assert len(loaded.findings) == 3
    assert [sample.expected_class for sample in loaded.samples] == list(RiskClass)


def test_policy_checker_is_integrated_with_local_and_hosted_checks() -> None:
    command = "python -m alpha_research.change_risk"
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    pre_commit = (REPOSITORY_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    continuous_integration = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert command in makefile
    assert command in pre_commit
    assert command in continuous_integration
    assert "change_risk/[a-z_]+\\.py" in pre_commit


@pytest.mark.parametrize("risk_class", list(RiskClass))
def test_classifier_maps_representative_changes_to_each_class(
    policy: ChangeRiskPolicy, risk_class: RiskClass
) -> None:
    decision = classify_change(_change_for(risk_class), policy)

    assert decision.risk_class is risk_class
    assert decision.drivers
    assert decision.mandatory_gates
    assert decision.rollout_modes
    assert decision.evidence_retention_class


def test_highest_dimension_wins_at_the_r3_boundary(policy: ChangeRiskPolicy) -> None:
    change = ChangeRiskInput(
        capital_at_risk=False,
        blast_radius="documentation_only",
        data_model_materiality="shared_or_candidate",
        security_privilege="nonproduction_privileged",
        reversibility="immediate",
    )

    decision = classify_change(change, policy)

    assert decision.risk_class is RiskClass.R3
    assert decision.drivers == ("security_privilege",)


def test_capital_at_risk_always_classifies_as_r4(policy: ChangeRiskPolicy) -> None:
    change = ChangeRiskInput(
        capital_at_risk=True,
        blast_radius="documentation_only",
        data_model_materiality="none",
        security_privilege="none",
        reversibility="immediate",
    )

    assert classify_change(change, policy).risk_class is RiskClass.R4


def test_declared_downgrade_is_rejected_and_conservative_escalation_is_allowed(
    policy: ChangeRiskPolicy,
) -> None:
    with pytest.raises(ChangeRiskPolicyError, match="below required R4"):
        classify_change(_change_for(RiskClass.R4, declared=RiskClass.R3), policy)

    decision = classify_change(_change_for(RiskClass.R0, declared=RiskClass.R2), policy)
    assert decision.risk_class is RiskClass.R2
    assert decision.drivers == ("declared_class",)


def test_conservative_escalation_preserves_computed_conditional_gates(
    policy: ChangeRiskPolicy,
) -> None:
    base = _change_for(RiskClass.R2)
    computed_change = _validated_change_update(base, economically_or_risk_relevant=True)
    escalated_change = _validated_change_update(
        computed_change,
        declared_class=RiskClass.R3,
    )

    computed = classify_change(computed_change, policy)
    escalated = classify_change(escalated_change, policy)

    assert escalated.risk_class is RiskClass.R3
    assert set(computed.mandatory_gates) <= set(escalated.mandatory_gates)
    assert {"QG06", "QG07", "QG08"} <= set(escalated.mandatory_gates)


def test_unknown_dimension_value_fails_closed(policy: ChangeRiskPolicy) -> None:
    change = ChangeRiskInput(
        capital_at_risk=False,
        blast_radius="unknown",
        data_model_materiality="none",
        security_privilege="none",
        reversibility="immediate",
    )

    with pytest.raises(ChangeRiskPolicyError, match="unsupported value 'unknown'"):
        classify_change(change, policy)


@pytest.mark.parametrize(
    ("risk_class", "flag", "expected_gates"),
    [
        (RiskClass.R1, "computationally_material", {"QG10"}),
        (RiskClass.R2, "economically_or_risk_relevant", {"QG07", "QG08"}),
        (RiskClass.R3, "model_or_trading_relevant", {"QG06", "QG07", "QG08"}),
    ],
)
def test_conditional_gate_facts_become_mandatory(
    policy: ChangeRiskPolicy,
    risk_class: RiskClass,
    flag: str,
    expected_gates: set[str],
) -> None:
    base = _change_for(risk_class)
    values = {
        "computationally_material": base.computationally_material,
        "economically_or_risk_relevant": base.economically_or_risk_relevant,
        "model_or_trading_relevant": base.model_or_trading_relevant,
    }
    values[flag] = True
    change = ChangeRiskInput(
        capital_at_risk=base.capital_at_risk,
        blast_radius=base.blast_radius,
        data_model_materiality=base.data_model_materiality,
        security_privilege=base.security_privilege,
        reversibility=base.reversibility,
        computationally_material=values["computationally_material"],
        economically_or_risk_relevant=values["economically_or_risk_relevant"],
        model_or_trading_relevant=values["model_or_trading_relevant"],
    )

    assert expected_gates <= set(classify_change(change, policy).mandatory_gates)


def test_r4_requires_distinct_review_groups_and_independent_approvers(
    policy: ChangeRiskPolicy,
) -> None:
    change = _change_for(RiskClass.R4)
    decision = classify_change(change, policy)

    validate_merge_approvals(
        decision,
        _r4_approvals(),
        change=change,
        waived_controls=(),
        policy=policy,
    )

    with pytest.raises(ChangeRiskPolicyError, match="at least 4 distinct approvers"):
        validate_merge_approvals(
            decision,
            [ReviewApproval(reviewer_id="owner", roles=frozenset({"domain_owner"}))],
            change=change,
            waived_controls=(),
            policy=policy,
        )


def test_r4_activation_requires_two_distinct_canonical_identities(
    policy: ChangeRiskPolicy,
) -> None:
    change = _change_for(RiskClass.R4)
    decision = classify_change(change, policy)

    validate_activation_approvals(
        decision,
        (
            ReviewApproval(reviewer_id="operations", roles=frozenset({"sre"})),
            ReviewApproval(reviewer_id="risk", roles=frozenset({"independent_risk"})),
        ),
        change=change,
        policy=policy,
    )

    with pytest.raises(ChangeRiskPolicyError, match="activation requires at least 2"):
        validate_activation_approvals(
            decision,
            (ReviewApproval(reviewer_id="operations", roles=frozenset({"sre"})),),
            change=change,
            policy=policy,
        )

    with pytest.raises(ChangeRiskPolicyError, match="after canonicalization"):
        validate_activation_approvals(
            decision,
            (
                ReviewApproval(reviewer_id="Alice", roles=frozenset({"sre"})),
                ReviewApproval(
                    reviewer_id=" alice ",
                    roles=frozenset({"independent_risk"}),
                ),
            ),
            change=change,
            policy=policy,
        )


def test_approval_validation_rejects_a_decision_for_another_change(
    policy: ChangeRiskPolicy,
) -> None:
    capital_change = _change_for(RiskClass.R4)
    untrusted_decision = classify_change(_change_for(RiskClass.R0), policy)

    with pytest.raises(ChangeRiskPolicyError, match="does not match the deterministic result"):
        validate_merge_approvals(
            untrusted_decision,
            [ReviewApproval(reviewer_id="owner", roles=frozenset({"code_owner"}))],
            change=capital_change,
            waived_controls=(),
            policy=policy,
        )


def test_approval_validation_rejects_same_class_decision_tampering(
    policy: ChangeRiskPolicy,
) -> None:
    change = _change_for(RiskClass.R4)
    trusted_decision = classify_change(change, policy)
    # Deliberately bypass validation to represent untrusted, tampered evidence.
    tampered_decision = trusted_decision.model_copy(update={"minimum_approvals": 1})

    with pytest.raises(ChangeRiskPolicyError, match="does not match the deterministic result"):
        validate_merge_approvals(
            tampered_decision,
            [ReviewApproval(reviewer_id="owner", roles=frozenset({"domain_owner"}))],
            change=change,
            waived_controls=(),
            policy=policy,
        )


def test_author_cannot_satisfy_an_independent_r4_group(policy: ChangeRiskPolicy) -> None:
    change = _change_for(RiskClass.R4)
    decision = classify_change(change, policy)
    approvals = list(_r4_approvals())
    approvals[1] = ReviewApproval(
        reviewer_id="risk",
        roles=frozenset({"independent_risk"}),
        independent=True,
        is_author=True,
    )

    with pytest.raises(ChangeRiskPolicyError, match=r"independent_control.*unsatisfied"):
        validate_merge_approvals(
            decision,
            approvals,
            change=change,
            waived_controls=(),
            policy=policy,
        )


def test_r4_rejects_a_waived_hard_control(policy: ChangeRiskPolicy) -> None:
    change = _change_for(RiskClass.R4)
    decision = classify_change(change, policy)

    with pytest.raises(ChangeRiskPolicyError, match="cannot waive hard controls"):
        validate_merge_approvals(
            decision,
            _r4_approvals(),
            change=change,
            waived_controls=("kill_capability",),
            policy=policy,
        )


def test_one_multi_role_reviewer_cannot_satisfy_multiple_r4_groups(
    policy: ChangeRiskPolicy,
) -> None:
    change = _change_for(RiskClass.R4)
    decision = classify_change(change, policy)
    approvals = (
        ReviewApproval(
            reviewer_id="multi-role",
            roles=frozenset({"domain_owner", "independent_risk", "sre", "security"}),
            independent=True,
        ),
        ReviewApproval(reviewer_id="second", roles=frozenset({"peer"}), independent=True),
        ReviewApproval(reviewer_id="third", roles=frozenset({"peer"}), independent=True),
        ReviewApproval(reviewer_id="fourth", roles=frozenset({"peer"})),
    )

    with pytest.raises(ChangeRiskPolicyError, match="distinct qualifying identities"):
        validate_merge_approvals(
            decision,
            approvals,
            change=change,
            waived_controls=(),
            policy=policy,
        )


def test_duplicate_reviewer_identity_cannot_count_twice(policy: ChangeRiskPolicy) -> None:
    change = _change_for(RiskClass.R2)
    decision = classify_change(change, policy)
    approvals = (
        ReviewApproval(reviewer_id="same", roles=frozenset({"code_owner"})),
        ReviewApproval(
            reviewer_id="same",
            roles=frozenset({"domain_reviewer"}),
            independent=True,
        ),
    )

    with pytest.raises(ChangeRiskPolicyError, match="distinct identities"):
        validate_merge_approvals(
            decision,
            approvals,
            change=change,
            waived_controls=(),
            policy=policy,
        )


def test_canonical_reviewer_identity_cannot_count_twice(policy: ChangeRiskPolicy) -> None:
    change = _change_for(RiskClass.R2)
    decision = classify_change(change, policy)
    approvals = (
        ReviewApproval(reviewer_id="Alice", roles=frozenset({"code_owner"})),
        ReviewApproval(
            reviewer_id=" alice ",
            roles=frozenset({"domain_reviewer"}),
            independent=True,
        ),
    )

    with pytest.raises(ChangeRiskPolicyError, match="after canonicalization"):
        validate_merge_approvals(
            decision,
            approvals,
            change=change,
            waived_controls=(),
            policy=policy,
        )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('  "QG08",\n  "QG09",', '  "QG09",', "weakens mandatory gates"),
        ("minimum_approvals = 4", "minimum_approvals = 1", "minimum_approvals weakens"),
        (
            "hard_control_waiver_allowed = false",
            "hard_control_waiver_allowed = true",
            "cannot permit a hard-control waiver",
        ),
        (
            '{ value = "shared_domain", minimum_class = "R2" }',
            '{ value = "research_only", minimum_class = "R2" }',
            "duplicate value",
        ),
        (
            'roles = ["security"], minimum_approvals = 1, independent = true',
            'roles = ["code_owner"], minimum_approvals = 1, independent = true',
            "reviewer_groups must match",
        ),
        ('  "bounded_canary",', '  "direct_production",', "rollout_modes must match"),
        (
            'evidence_retention_class = "release_activation_and_audit_lifecycle"',
            'evidence_retention_class = "short_lived"',
            "evidence_retention_class cannot be weakened",
        ),
    ],
)
def test_policy_mutations_cannot_weaken_hard_boundaries(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = _mutated_policy(tmp_path, old, new)

    with pytest.raises(ChangeRiskPolicyError, match=message):
        load_policy(path)


def test_partial_policy_cannot_hide_open_findings(tmp_path: Path) -> None:
    path = tmp_path / "change-risk-policy.toml"
    text = POLICY_PATH.read_text(encoding="utf-8").split("[[findings]]", maxsplit=1)[0]
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ChangeRiskPolicyError, match="findings"):
        load_policy(path)


def test_partial_policy_requires_the_registered_a04_findings(tmp_path: Path) -> None:
    path = _mutated_policy(tmp_path, 'finding_id = "A04-F02"', 'finding_id = "A04-OTHER"')

    with pytest.raises(ChangeRiskPolicyError, match="partial status requires findings"):
        load_policy(path)


def test_solo_bootstrap_policy_cannot_claim_validated_status(tmp_path: Path) -> None:
    path = tmp_path / "change-risk-policy.toml"
    text = POLICY_PATH.read_text(encoding="utf-8").split("[[findings]]", maxsplit=1)[0]
    text = text.replace(
        'package_status = "partial"',
        'package_status = "validated"\n'
        'validation_evidence = ["https://forge.example/evidence"]\n'
        "findings = []",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ChangeRiskPolicyError, match=r"solo_bootstrap.*cannot claim validated"):
        load_policy(path)


def test_command_reports_missing_policy_and_usage_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path)]) == 1
    assert "change-risk-policy.toml" in capsys.readouterr().err

    assert main(["one", "two"]) == 2
    assert "usage:" in capsys.readouterr().err
