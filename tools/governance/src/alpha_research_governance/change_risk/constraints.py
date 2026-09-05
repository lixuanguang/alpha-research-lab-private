"""Define non-negotiable blueprint lower bounds for change-risk policy."""

from __future__ import annotations

# standard library imports
import re

EXPECTED_DIMENSIONS = {
    "blast_radius",
    "capital_at_risk",
    "data_model_materiality",
    "reversibility",
    "security_privilege",
}
APPLICABILITY_TRIGGERS = {
    "computationally_material",
    "economically_or_risk_relevant",
    "model_or_trading_relevant",
}
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
GATE_PATTERN = re.compile(r"^QG(?:0[1-9]|1[0-5])$")
BLUEPRINT_REQUIRED_GATES = {
    "R0": {"QG01", "QG13"},
    "R1": {"QG01", "QG02", "QG03", "QG04", "QG05", "QG06", "QG13"},
    "R2": {
        "QG01",
        "QG02",
        "QG03",
        "QG04",
        "QG05",
        "QG06",
        "QG09",
        "QG10",
        "QG11",
        "QG12",
        "QG13",
        "QG14",
    },
    "R3": {
        "QG01",
        "QG02",
        "QG03",
        "QG04",
        "QG05",
        "QG09",
        "QG10",
        "QG11",
        "QG12",
        "QG13",
        "QG14",
        "QG15",
    },
    "R4": {f"QG{number:02d}" for number in range(1, 16)},
}
BLUEPRINT_CONDITIONAL_GATES = {
    "R0": {},
    "R1": {"computationally_material": {"QG10"}},
    "R2": {"economically_or_risk_relevant": {"QG07", "QG08"}},
    "R3": {"model_or_trading_relevant": {"QG06", "QG07", "QG08"}},
    "R4": {},
}
MINIMUM_APPROVALS = {"R0": 1, "R1": 2, "R2": 2, "R3": 2, "R4": 2}
EXPECTED_REVIEWER_GROUPS = {
    "R0": {"code_owner": (frozenset({"code_owner"}), 1, False)},
    "R1": {
        "research_owner": (frozenset({"research_owner"}), 1, False),
        "peer": (frozenset({"peer"}), 1, True),
    },
    "R2": {
        "code_owner": (frozenset({"code_owner"}), 1, False),
        "independent_domain": (
            frozenset({"data_reviewer", "model_validation", "domain_reviewer"}),
            1,
            True,
        ),
    },
    "R3": {
        "code_owner": (frozenset({"code_owner"}), 1, False),
        "platform_operations": (frozenset({"platform", "sre"}), 1, True),
        "security": (frozenset({"security"}), 1, True),
    },
    "R4": {
        "domain_owner": (frozenset({"domain_owner"}), 1, False),
        "independent_control": (
            frozenset({"independent_risk", "model_validation"}),
            1,
            True,
        ),
        "platform_operations": (frozenset({"platform", "sre"}), 1, True),
        "security_compliance": (frozenset({"security", "compliance"}), 1, True),
    },
}
EXPECTED_ROLLOUT_MODES = {
    "R0": ("fast_lane",),
    "R1": ("reproducible_batch", "no_production_promotion"),
    "R2": ("merged_result", "compatibility_replay", "impact_analysis"),
    "R3": ("staging", "failure_injection", "shadow_or_synthetic"),
    "R4": (
        "full_certification",
        "paper",
        "shadow",
        "bounded_canary",
        "signed_activation",
        "rehearsed_rollback",
    ),
}
EXPECTED_RETENTION_CLASSES = {
    "R0": "source_governance_record",
    "R1": "governed_research_lifecycle",
    "R2": "shared_contract_compatibility_lifecycle",
    "R3": "deployable_service_lifecycle",
    "R4": "release_activation_and_audit_lifecycle",
}
CHANGE_RISK_OPEN_FINDING_IDS = ("A04-F01", "A04-F02", "A04-F03")
NON_WAIVABLE_LIVE_CONTROLS = {
    "point_in_time_causality",
    "immutable_artifact_identity",
    "independent_hard_risk",
    "kill_capability",
}
