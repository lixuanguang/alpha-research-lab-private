"""Validate financial-unit evidence under the C03 solo-bootstrap policy."""

from __future__ import annotations

# standard library imports
import hashlib
import shutil
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.change_risk import ChangeRiskInput, RiskClass
from alpha_research_governance.change_risk import load_policy as load_change_risk_policy
from alpha_research_governance.evidence import (
    PackageEvidenceProfile,
    PackageGateRequirement,
    validate_manifest,
    validate_package_evidence,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
FINANCIAL_UNITS_ROADMAP_PACKAGE_ID = "C03"
FINANCIAL_UNITS_EVIDENCE_MANIFEST_PATH = (
    REPOSITORY_ROOT / "docs/governance/evidence/examples/c03-r2-partial/manifest.toml"
)
CHANGE_RISK_POLICY_PATH = REPOSITORY_ROOT / "docs/governance/change-risk-policy.toml"
FINANCIAL_UNITS_GOLDEN_FIXTURE_PATH = (
    REPOSITORY_ROOT / "tests/golden/financial_units/c03_units.json"
)
FINANCIAL_UNITS_GOLDEN_FIXTURE_SHA256 = (
    "fc89baa1fa2062a5b29a372b3682b8a988b45348252395ba7c6a98a2d7b7fa19"
)
FINANCIAL_UNITS_APPLICABLE_QUALITY_GATES = (
    "QG01",
    "QG02",
    "QG03",
    "QG04",
    "QG05",
    "QG06",
    "QG07",
    "QG08",
    "QG09",
    "QG10",
    "QG11",
    "QG12",
    "QG13",
    "QG14",
)


def test_financial_units_manifest_matches_partial_r2_profile_and_golden_digest(
    tmp_path: Path,
) -> None:
    # Bazel supplies symlinked runfiles. Materialize fixture bytes; keep the
    # production validator's rejection of symlinked manifests/artifacts intact.
    fixture_root = shutil.copytree(
        FINANCIAL_UNITS_EVIDENCE_MANIFEST_PATH.parent, tmp_path / "c03-r2-partial"
    )
    financial_units_evidence_manifest = validate_manifest(
        fixture_root / "manifest.toml",
        expected_commit_sha="3" * 40,
        change_policy=load_change_risk_policy(CHANGE_RISK_POLICY_PATH),
    )
    expected_financial_units_evidence_profile = PackageEvidenceProfile(
        roadmap_package_id=FINANCIAL_UNITS_ROADMAP_PACKAGE_ID,
        accountable_owner_role="domain_architecture",
        risk_class=RiskClass.R2,
        classification_facts=ChangeRiskInput(
            capital_at_risk=False,
            blast_radius="shared_domain",
            data_model_materiality="shared_or_candidate",
            security_privilege="shared_sensitive",
            reversibility="compatibility_window",
            computationally_material=True,
            economically_or_risk_relevant=True,
            model_or_trading_relevant=False,
            declared_class=RiskClass.R2,
        ),
        gate_requirements=tuple(
            PackageGateRequirement(gate_id=gate_id, status="passed")
            for gate_id in FINANCIAL_UNITS_APPLICABLE_QUALITY_GATES
        ),
        expected_package_status="partial",
        expected_finding_ids=("C03-F01", "C03-F02", "C03-F03"),
        approvals_permitted=False,
        waivers_permitted=False,
        additional_required_gates_permitted=False,
    )

    validate_package_evidence(
        financial_units_evidence_manifest,
        expected_financial_units_evidence_profile,
    )

    actual_golden_fixture_sha256 = hashlib.sha256(
        FINANCIAL_UNITS_GOLDEN_FIXTURE_PATH.read_bytes()
    ).hexdigest()
    assert actual_golden_fixture_sha256 == FINANCIAL_UNITS_GOLDEN_FIXTURE_SHA256
    contract_and_goldens_report = (
        FINANCIAL_UNITS_EVIDENCE_MANIFEST_PATH.parent / "reports/contract-and-goldens.txt"
    ).read_text(encoding="utf-8")
    assert (
        f"Fixture SHA-256: {FINANCIAL_UNITS_GOLDEN_FIXTURE_SHA256}." in contract_and_goldens_report
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-W", "error"]))
