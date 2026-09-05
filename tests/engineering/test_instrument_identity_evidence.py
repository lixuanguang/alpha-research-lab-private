"""Validate instrument-identity evidence under the C01 solo-bootstrap policy."""

from __future__ import annotations

# standard library imports
import hashlib
from pathlib import Path

# project library imports
from alpha_research_governance.change_risk import (
    ChangeRiskInput,
    RiskClass,
)
from alpha_research_governance.change_risk import (
    load_policy as load_change_risk_policy,
)
from alpha_research_governance.evidence import (
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
INSTRUMENT_IDENTITY_ROADMAP_PACKAGE_ID = "C01"
INSTRUMENT_IDENTITY_EVIDENCE_MANIFEST_PATH = (
    REPOSITORY_ROOT / "docs/governance/evidence/examples/c01-r2-partial/manifest.toml"
)
CHANGE_RISK_POLICY_PATH = REPOSITORY_ROOT / "docs/governance/change-risk-policy.toml"
INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_PATH = (
    REPOSITORY_ROOT / "tests/golden/instrument_identity/c01_symbology.json"
)
INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_SHA256 = (
    "181281a439f2cb6da13ca9268eebcc8d4bd34b6e016edcd685ad25741d993c30"
)
INSTRUMENT_IDENTITY_APPLICABLE_QUALITY_GATES = (
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
)


def test_instrument_identity_manifest_matches_partial_r2_profile_and_golden_digest() -> None:
    instrument_identity_evidence_manifest = validate_manifest(
        INSTRUMENT_IDENTITY_EVIDENCE_MANIFEST_PATH,
        expected_commit_sha="c" * 40,
        change_policy=load_change_risk_policy(CHANGE_RISK_POLICY_PATH),
    )
    expected_instrument_identity_evidence_profile = PackageEvidenceProfile(
        roadmap_package_id=INSTRUMENT_IDENTITY_ROADMAP_PACKAGE_ID,
        accountable_owner_role="domain_architecture",
        risk_class=RiskClass.R2,
        classification_facts=ChangeRiskInput(
            capital_at_risk=False,
            blast_radius="shared_domain",
            data_model_materiality="shared_or_candidate",
            security_privilege="none",
            reversibility="compatibility_window",
            computationally_material=False,
            economically_or_risk_relevant=False,
            model_or_trading_relevant=False,
            declared_class=RiskClass.R2,
        ),
        gate_requirements=tuple(
            PackageGateRequirement(gate_id=gate_id, status="passed")
            for gate_id in INSTRUMENT_IDENTITY_APPLICABLE_QUALITY_GATES
        ),
        expected_package_status="partial",
        expected_finding_ids=("C01-F01", "C01-F02", "C01-F03"),
        approvals_permitted=False,
        waivers_permitted=False,
        additional_required_gates_permitted=False,
    )

    validate_package_evidence(
        instrument_identity_evidence_manifest,
        expected_instrument_identity_evidence_profile,
    )

    actual_golden_fixture_sha256 = hashlib.sha256(
        INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_PATH.read_bytes()
    ).hexdigest()
    assert actual_golden_fixture_sha256 == INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_SHA256
    contract_and_goldens_report = (
        INSTRUMENT_IDENTITY_EVIDENCE_MANIFEST_PATH.parent / "reports/contract-and-goldens.txt"
    ).read_text(encoding="utf-8")
    assert (
        f"Fixture SHA-256: {INSTRUMENT_IDENTITY_GOLDEN_FIXTURE_SHA256}."
        in contract_and_goldens_report
    )
