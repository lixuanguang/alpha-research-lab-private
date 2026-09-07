"""Deterministic and adversarial tests for the change-risk policy."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research.change_risk import (
    ChangeRiskApprovalEvaluator,
    ChangeRiskClassifier,
    ChangeRiskInput,
    ChangeRiskPolicy,
    ChangeRiskPolicyError,
    ReviewApproval,
    RiskClass,
    classify_change,
    load_policy,
    validate_activation_approvals,
    validate_merge_approvals,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "change-risk-policy.toml"


class TestChangeRiskServices:
    """Exercise service reuse without leaking classification or approval state."""

    def test_classifier_recovers_after_escalation_and_downgrade(
        self, policy: ChangeRiskPolicy
    ) -> None:
        """Keep gates, drivers, and policy data independent across one classifier's calls."""
        classifier = ChangeRiskClassifier(policy)
        base = _change_for(RiskClass.R2)
        snapshot = policy.model_dump_json()
        expected = classifier.classify(base)
        escalated = classifier.classify(
            _validated_change_update(
                base, declared_class=RiskClass.R3, economically_or_risk_relevant=True
            )
        )
        assert escalated.drivers == ("declared_class",)
        assert {"QG06", "QG07", "QG08"} <= set(escalated.mandatory_gates)
        with pytest.raises(ChangeRiskPolicyError, match="below required R4"):
            classifier.classify(_change_for(RiskClass.R4, declared=RiskClass.R3))

        repeated = classifier.classify(base)
        assert repeated == expected
        assert repeated is not expected
        assert repeated.risk_class is RiskClass.R2
        assert "QG07" not in repeated.mandatory_gates
        assert policy.model_dump_json() == snapshot

    @pytest.mark.parametrize("risk_class", list(RiskClass))
    def test_service_and_facade_preserve_serialized_decisions(
        self, policy: ChangeRiskPolicy, risk_class: RiskClass
    ) -> None:
        """Preserve the supported facade output across every class and repeated calls."""
        classifier = ChangeRiskClassifier(policy)
        change = _change_for(risk_class)
        expected = classify_change(change, policy).model_dump_json()
        for _ in range(2):
            decision = classifier.classify(change)
            assert decision.model_dump_json() == expected
            gate_numbers = tuple(int(gate[2:]) for gate in decision.mandatory_gates)
            assert gate_numbers == tuple(sorted(set(gate_numbers)))

    def test_merge_findings_do_not_leak_into_later_requests(self, policy: ChangeRiskPolicy) -> None:
        """Recover after failed merge review and preserve deterministic failure order."""
        evaluator = ChangeRiskApprovalEvaluator(policy)
        change = _change_for(RiskClass.R4)
        decision = classify_change(change, policy)
        approvals = _highest_risk_class_approvals()
        messages: list[str] = []
        for _ in range(2):
            with pytest.raises(
                ChangeRiskPolicyError, match="at least 4 distinct approvers"
            ) as error:
                evaluator.validate_merge(
                    decision, (), change=change, waived_controls=("kill_capability",)
                )
            messages.append(str(error.value))
            evaluator.validate_merge(decision, approvals, change=change, waived_controls=())
            evaluator.validate_activation(decision, approvals[:2], change=change)
        assert messages[0] == messages[1]
        assert messages[0].splitlines()[0] == "R4 requires at least 4 distinct approvers"
        assert messages[0].splitlines()[-1] == "R4 cannot waive hard controls: ['kill_capability']"

    def test_activation_rebinds_decisions_and_recovers_after_invalid_identities(
        self, policy: ChangeRiskPolicy
    ) -> None:
        """Reject each request's mismatched evidence without retaining earlier failures."""
        evaluator = ChangeRiskApprovalEvaluator(policy)
        change = _change_for(RiskClass.R4)
        decision = classify_change(change, policy)
        unbound = classify_change(_change_for(RiskClass.R0), policy)
        valid = _highest_risk_class_approvals()[:2]
        duplicates = (
            # Fullwidth "Alice" must normalize to the same ASCII identity.
            ReviewApproval(reviewer_id="\uff21\uff4c\uff49\uff43\uff45", roles=frozenset({"sre"})),
            ReviewApproval(reviewer_id=" alice ", roles=frozenset({"independent_risk"})),
        )
        for _ in range(2):
            with pytest.raises(ChangeRiskPolicyError, match="does not match the deterministic"):
                evaluator.validate_activation(unbound, valid, change=change)
            with pytest.raises(ChangeRiskPolicyError, match="after canonicalization"):
                evaluator.validate_activation(decision, duplicates, change=change)
            evaluator.validate_activation(decision, valid, change=change)
            evaluator.validate_merge(
                decision, _highest_risk_class_approvals(), change=change, waived_controls=()
            )


@pytest.fixture()
def policy() -> ChangeRiskPolicy:
    """Load the checked-in change-risk policy for service and facade tests.

    Returns:
        The validated policy loaded from the repository policy file.

    Raises:
        ChangeRiskPolicyError: The checked-in policy violates its validation contract.
        OSError: The checked-in policy file cannot be read.
    """
    return load_policy(POLICY_PATH)


def _change_for(risk_class: RiskClass, *, declared: RiskClass | None = None) -> ChangeRiskInput:
    """Build and validate a representative change input for one risk class.

    Args:
        risk_class: Risk class whose canonical dimension values should be populated.
        declared: Optional declared class, which may disagree until classification.

    Returns:
        A validated input with class dimensions, default-false conditional flags, and
        the optional declared class.

    Raises:
        ValidationError: The assembled change input violates its model contract.
    """
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


def _highest_risk_class_approvals() -> tuple[ReviewApproval, ...]:
    """Build the four approvals required by the representative R4 merge decision.

    Returns:
        Approvals covering domain ownership, independent risk, SRE, and security.
    """
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
    """Copy a change input with field updates and validate the resulting model.

    Args:
        change: Existing change input to copy.
        updates: Field values to replace before model validation.

    Returns:
        A new validated change input containing ``updates``.

    Raises:
        ValidationError: An updated value violates the change-input model contract.
    """
    values: dict[str, object] = {
        "capital_at_risk": change.capital_at_risk,
        "blast_radius": change.blast_radius,
        "data_model_materiality": change.data_model_materiality,
        "security_privilege": change.security_privilege,
        "reversibility": change.reversibility,
        "computationally_material": change.computationally_material,
        "economically_or_risk_relevant": change.economically_or_risk_relevant,
        "model_or_trading_relevant": change.model_or_trading_relevant,
        "declared_class": change.declared_class,
    }
    values.update(updates)
    return ChangeRiskInput.model_validate(values)


def _mutated_policy(tmp_path: Path, old: str, new: str) -> Path:
    """Write one expected policy replacement to an isolated mutation fixture.

    Args:
        tmp_path: Temporary directory receiving the mutated policy file.
        old: Exact policy fragment required before the replacement.
        new: Replacement text for the first occurrence of ``old``.

    Returns:
        Path to the UTF-8 policy fixture containing the requested mutation.

    Raises:
        AssertionError: ``old`` is absent from the checked-in policy.
        OSError: The source policy cannot be read or the fixture cannot be written.
    """
    path = tmp_path / "change-risk-policy.toml"
    text = POLICY_PATH.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


class TestChangeRiskClassification:
    """Validate classification, approval and identity contracts across risk classes."""

    def test_repository_policy_is_valid_partial_and_covers_every_class(self) -> None:
        """Validate partial status, three findings, and one sample for every risk class."""
        loaded = validate_repository(REPOSITORY_ROOT)

        assert loaded.package_status == "partial"
        assert len(loaded.findings) == 3
        assert [sample.expected_class for sample in loaded.samples] == list(RiskClass)

    @pytest.mark.parametrize("risk_class", list(RiskClass))
    def test_classifier_maps_representative_changes_to_each_class(
        self, policy: ChangeRiskPolicy, risk_class: RiskClass
    ) -> None:
        """Map representative inputs to their classes and populate decision requirements."""
        decision = classify_change(_change_for(risk_class), policy)

        assert decision.risk_class is risk_class
        assert decision.drivers
        assert decision.mandatory_gates
        assert decision.rollout_modes
        assert decision.evidence_retention_class

    def test_highest_dimension_wins_at_the_r3_boundary(self, policy: ChangeRiskPolicy) -> None:
        """Select R3 when nonproduction privilege is the highest dimension at the boundary."""
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

    def test_capital_at_risk_always_classifies_as_r4(self, policy: ChangeRiskPolicy) -> None:
        """Classify a capital-at-risk change as R4 despite otherwise minimal dimensions."""
        change = ChangeRiskInput(
            capital_at_risk=True,
            blast_radius="documentation_only",
            data_model_materiality="none",
            security_privilege="none",
            reversibility="immediate",
        )

        assert classify_change(change, policy).risk_class is RiskClass.R4

    def test_declared_downgrade_is_rejected_and_conservative_escalation_is_allowed(
        self,
        policy: ChangeRiskPolicy,
    ) -> None:
        """Reject declared downgrades while allowing conservative declared escalations."""
        with pytest.raises(ChangeRiskPolicyError, match="below required R4"):
            classify_change(_change_for(RiskClass.R4, declared=RiskClass.R3), policy)

        decision = classify_change(_change_for(RiskClass.R0, declared=RiskClass.R2), policy)
        assert decision.risk_class is RiskClass.R2
        assert decision.drivers == ("declared_class",)

    def test_conservative_escalation_preserves_computed_conditional_gates(
        self,
        policy: ChangeRiskPolicy,
    ) -> None:
        """Retain computed conditional gates when a declaration conservatively escalates risk."""
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

    def test_unknown_dimension_value_fails_closed(self, policy: ChangeRiskPolicy) -> None:
        """Reject an unsupported dimension value instead of producing a decision."""
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
        self,
        policy: ChangeRiskPolicy,
        risk_class: RiskClass,
        flag: str,
        expected_gates: set[str],
    ) -> None:
        """Require the gates associated with each enabled conditional fact."""
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
        self,
        policy: ChangeRiskPolicy,
    ) -> None:
        """Accept four qualifying approvers and reject an incomplete R4 approval set."""
        change = _change_for(RiskClass.R4)
        decision = classify_change(change, policy)

        validate_merge_approvals(
            decision,
            _highest_risk_class_approvals(),
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
        self,
        policy: ChangeRiskPolicy,
    ) -> None:
        """Require two distinct canonical reviewer identities for R4 activation."""
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
        self,
        policy: ChangeRiskPolicy,
    ) -> None:
        """Reject approval evidence whose decision belongs to a different change."""
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
        self,
        policy: ChangeRiskPolicy,
    ) -> None:
        """Reject tampered decision evidence even when its risk class remains R4."""
        change = _change_for(RiskClass.R4)
        trusted_decision = classify_change(change, policy)
        # Deliberately bypass validation to represent untrusted, tampered evidence.
        tampered_decision = trusted_decision.model_copy()
        object.__setattr__(tampered_decision, "minimum_approvals", 1)

        with pytest.raises(ChangeRiskPolicyError, match="does not match the deterministic result"):
            validate_merge_approvals(
                tampered_decision,
                [ReviewApproval(reviewer_id="owner", roles=frozenset({"domain_owner"}))],
                change=change,
                waived_controls=(),
                policy=policy,
            )

    def test_author_cannot_satisfy_an_independent_r4_group(self, policy: ChangeRiskPolicy) -> None:
        """Reject an author approval from satisfying an independent R4 reviewer group."""
        change = _change_for(RiskClass.R4)
        decision = classify_change(change, policy)
        approvals = list(_highest_risk_class_approvals())
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

    def test_r4_rejects_a_waived_hard_control(self, policy: ChangeRiskPolicy) -> None:
        """Reject R4 merge validation when a hard control is waived."""
        change = _change_for(RiskClass.R4)
        decision = classify_change(change, policy)

        with pytest.raises(ChangeRiskPolicyError, match="cannot waive hard controls"):
            validate_merge_approvals(
                decision,
                _highest_risk_class_approvals(),
                change=change,
                waived_controls=("kill_capability",),
                policy=policy,
            )

    def test_one_multi_role_reviewer_cannot_satisfy_multiple_r4_groups(
        self,
        policy: ChangeRiskPolicy,
    ) -> None:
        """Prevent one multi-role reviewer from satisfying multiple R4 groups."""
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

    def test_duplicate_reviewer_identity_cannot_count_twice(self, policy: ChangeRiskPolicy) -> None:
        """Reject duplicate reviewer IDs from counting as distinct approvals."""
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

    def test_canonical_reviewer_identity_cannot_count_twice(self, policy: ChangeRiskPolicy) -> None:
        """Reject reviewer IDs that collide after canonicalization."""
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


class TestChangeRiskPolicySchema:
    """Validate policy schema errors, extensions and hard-boundary mutations."""

    @pytest.mark.parametrize(
        ("old", "new", "message"),
        [
            pytest.param(
                "schema_version = 1",
                "schema_version = true",
                "schema_version must be 1",
                id="wrong-schema-version-type",
            ),
            pytest.param(
                "\n\n[risk_classes.R0]",
                "\nunknown_dimension = []\n\n[risk_classes.R0]",
                "dimensions must be exactly",
                id="unknown-dimension",
            ),
            pytest.param(
                '{ value = "documentation_only", minimum_class = "R0" }',
                '{ value = 1, minimum_class = "R0" }',
                r"dimensions\.blast_radius\[1\]\.value must be a string",
                id="wrong-dimension-value-type",
            ),
            pytest.param(
                "minimum_approvals = 1",
                'minimum_approvals = "1"',
                r"risk_classes\.R0\.minimum_approvals must be a non-negative integer",
                id="wrong-class-approval-count-type",
            ),
            pytest.param(
                '{ trigger = "computationally_material", gates = ["QG10"] }',
                '{ trigger = "computationally_material", gates = [1] }',
                r"risk_classes\.R1\.conditional_gate_rules\[1\]\.gates must be an array",
                id="wrong-conditional-gate-type",
            ),
            pytest.param(
                'roles = ["code_owner"], minimum_approvals = 1, independent = false',
                'roles = ["code_owner"], minimum_approvals = 1, independent = "false"',
                r"risk_classes\.R0\.reviewer_groups\[1\]\.independent must be Boolean",
                id="wrong-reviewer-independence-type",
            ),
            pytest.param(
                "capital_at_risk = false",
                'capital_at_risk = "false"',
                r"sample_changes\[1\]\.capital_at_risk must be Boolean",
                id="wrong-sample-boolean-type",
            ),
            pytest.param(
                'owner_role = "platform_ci"',
                "owner_role = 1",
                r"findings\[1\]\.owner_role is required",
                id="wrong-finding-owner-type",
            ),
        ],
    )
    def test_policy_input_schema_preserves_structural_error_contract(
        self, tmp_path: Path, old: str, new: str, message: str
    ) -> None:
        """Preserve structural schema errors for malformed policy fields."""
        path = _mutated_policy(tmp_path, old, new)

        with pytest.raises(ChangeRiskPolicyError, match=message):
            load_policy(path)

    def test_policy_input_schema_preserves_existing_extensible_root_contract(
        self,
        tmp_path: Path,
    ) -> None:
        """Accept an otherwise valid policy extension at the document root."""
        path = _mutated_policy(
            tmp_path,
            "schema_version = 1",
            'schema_version = 1\nextension_note = "synthetic"',
        )

        assert load_policy(path).package_status == "partial"

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
        self, tmp_path: Path, old: str, new: str, message: str
    ) -> None:
        """Reject mutations that weaken hard boundaries or break policy identity."""
        path = _mutated_policy(tmp_path, old, new)

        with pytest.raises(ChangeRiskPolicyError, match=message):
            load_policy(path)

    def test_partial_policy_cannot_hide_open_findings(self, tmp_path: Path) -> None:
        """Reject partial policy text that hides required open findings."""
        path = tmp_path / "change-risk-policy.toml"
        text = POLICY_PATH.read_text(encoding="utf-8").split("[[findings]]", maxsplit=1)[0]
        path.write_text(text, encoding="utf-8")

        with pytest.raises(ChangeRiskPolicyError, match="findings"):
            load_policy(path)

    def test_solo_bootstrap_policy_cannot_claim_validated_status(self, tmp_path: Path) -> None:
        """Reject solo-bootstrap policy text that falsely claims validated status."""
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
