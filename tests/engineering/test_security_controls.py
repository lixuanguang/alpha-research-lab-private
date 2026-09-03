"""Deterministic and adversarial tests for the security control map."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from alpha_research.security_controls import (
    APPLICABLE_GATE_IDS,
    JURISDICTION_IDS,
    SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS,
    THREAT_CATEGORIES,
    SecurityControlError,
    load_control_map,
    main,
    validate_repository,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
MAP_PATH = REPOSITORY_ROOT / "docs" / "governance" / "security-control-map.toml"


def _map_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "security-control-map.toml"
    path.write_text(MAP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _replace_security_fixture_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _replace_security_fixture_text_after_marker(
    path: Path, marker: str, old: str, new: str
) -> None:
    text = path.read_text(encoding="utf-8")
    marker_index = text.index(marker)
    prefix = text[:marker_index]
    suffix = text[marker_index:]
    assert old in suffix
    path.write_text(prefix + suffix.replace(old, new, 1), encoding="utf-8")


def _repository_fixture(tmp_path: Path) -> Path:
    relative_paths = (
        Path("docs/governance/change-risk-policy.toml"),
        Path("docs/governance/domain-ownership.toml"),
        Path("docs/governance/security-control-map.toml"),
        Path("docs/governance/threat-model.md"),
        Path("tests/engineering/test_security_controls.py"),
        Path("docs/governance/evidence/examples/a07-r2-partial/manifest.toml"),
        Path("docs/governance/evidence/examples/b08-r2-partial/manifest.toml"),
        Path("docs/governance/evidence/examples/a07-r2-partial/reports/contract-and-tests.txt"),
        Path(
            "docs/governance/evidence/examples/a07-r2-partial/reports/"
            "documentation-and-monitoring.txt"
        ),
        Path(
            "docs/governance/evidence/examples/a07-r2-partial/reports/"
            "integration-and-control-coverage.txt"
        ),
        Path(
            "docs/governance/evidence/examples/a07-r2-partial/reports/"
            "resilience-security-and-regulation.txt"
        ),
    )
    for relative_path in relative_paths:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative_path, destination)
    return tmp_path


def _validate_security_fixture(path: Path) -> None:
    load_control_map(path, repository_root=REPOSITORY_ROOT)


def test_repository_map_is_versioned_partial_and_complete_for_current_scope() -> None:
    control_map = validate_repository(REPOSITORY_ROOT)

    assert control_map.package_status == "partial"
    assert control_map.schema_version == 1
    assert control_map.roadmap_package == "A07"
    assert control_map.operating_track == "solo_bootstrap"
    assert control_map.accountable_owner_role == "security"
    assert control_map.risk_class == "R2"
    assert control_map.dependency_package_ids == SECURITY_CONTROL_DEPENDENCY_PACKAGE_IDS
    assert control_map.applicable_gate_ids == APPLICABLE_GATE_IDS
    assert control_map.local_evidence_commit_sha == "3" * 40
    assert control_map.finding_ids == ("A07-F01", "A07-F02", "A07-F03", "A07-F04")
    assert len(control_map.assets) == 8
    assert len(control_map.boundaries) == 8
    assert len(control_map.threats) == 12
    assert len(control_map.controls) == 12
    assert len(control_map.evidence_sources) == 16
    assert tuple(item.jurisdiction_id for item in control_map.jurisdictions) == (JURISDICTION_IDS)
    assert {item.category for item in control_map.threats} == set(THREAT_CATEGORIES)
    assert {item.implementation_status for item in control_map.controls} == {
        "planned",
        "repository_local",
    }


def test_security_control_dates_require_extended_calendar_format(tmp_path: Path) -> None:
    path = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        path,
        'as_of_date = "2026-08-30"',
        'as_of_date = "20260830"',
    )

    with pytest.raises(SecurityControlError, match="must use YYYY-MM-DD"):
        _validate_security_fixture(path)


def test_machine_metadata_is_strict_and_complete(tmp_path: Path) -> None:
    boolean_schema = _map_fixture(tmp_path)
    _replace_security_fixture_text(boolean_schema, "schema_version = 1", "schema_version = true")
    with pytest.raises(SecurityControlError, match="schema_version must be an integer"):
        _validate_security_fixture(boolean_schema)

    missing_dependency = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        missing_dependency,
        'dependency_package_ids = ["A02", "A06"]',
        'dependency_package_ids = ["A02"]',
    )
    with pytest.raises(SecurityControlError, match="dependency_package_ids must be exactly"):
        _validate_security_fixture(missing_dependency)

    missing_gate = _map_fixture(tmp_path)
    _replace_security_fixture_text(missing_gate, '  "QG13",\n  "QG14",\n]', '  "QG13",\n]')
    with pytest.raises(SecurityControlError, match="applicable_gate_ids must be exactly"):
        _validate_security_fixture(missing_gate)


def test_unknown_reference_and_missing_category_fail_closed(tmp_path: Path) -> None:
    unknown = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        unknown, 'control_ids = ["A07-C01", "A07-C12"]', 'control_ids = ["A07-C99"]'
    )
    with pytest.raises(SecurityControlError, match="unknown references"):
        _validate_security_fixture(unknown)

    missing_category = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        missing_category,
        'category = "software_supply_chain"',
        'category = "privileged_access"',
    )
    with pytest.raises(SecurityControlError, match="required categories"):
        _validate_security_fixture(missing_category)


def test_control_owner_cannot_self_review_and_roles_must_be_registered(tmp_path: Path) -> None:
    self_review = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        self_review,
        (
            'control_id = "A07-C01"\n'
            'title = "Protected source and independent review"\n'
            'domain = "source_governance"\n'
            'owner_role = "platform"\n'
            'independent_review_roles = ["security"]'
        ),
        (
            'control_id = "A07-C01"\n'
            'title = "Protected source and independent review"\n'
            'domain = "source_governance"\n'
            'owner_role = "platform"\n'
            'independent_review_roles = ["platform"]'
        ),
    )
    with pytest.raises(SecurityControlError, match="owner cannot independently review"):
        _validate_security_fixture(self_review)

    stale_owner = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        stale_owner,
        (
            'asset_id = "ASSET01"\n'
            'name = "Governed source and review evidence"\n'
            'owner_role = "platform"'
        ),
        (
            'asset_id = "ASSET01"\n'
            'name = "Governed source and review evidence"\n'
            'owner_role = "former_owner"'
        ),
    )
    with pytest.raises(SecurityControlError, match="stale ownership roles"):
        _validate_security_fixture(stale_owner)


def test_available_and_deferred_evidence_have_distinct_fail_closed_states(
    tmp_path: Path,
) -> None:
    unsafe_path = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        unsafe_path,
        'location = "docs/governance/security-control-map.toml"',
        'location = "../security-control-map.toml"',
    )
    with pytest.raises(SecurityControlError, match="repository path escapes the root"):
        _validate_security_fixture(unsafe_path)

    available_with_future_package = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        available_with_future_package, "required_packages = []", 'required_packages = ["K08"]'
    )
    with pytest.raises(SecurityControlError, match="available evidence cannot require"):
        _validate_security_fixture(available_with_future_package)

    deferred_without_closure = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        deferred_without_closure,
        (
            'closure_condition = "Protected main retains exact-commit pass and blocking '
            'exercises with non-author Code Owner and required independent approvals."'
        ),
        'closure_condition = ""',
    )
    with pytest.raises(SecurityControlError, match="deferred evidence needs packages"):
        _validate_security_fixture(deferred_without_closure)


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://handbook.fca.org.uk/handbook/mar7a",
        "https://user@handbook.fca.org.uk/handbook/mar7a",
        "https://handbook.fca.org.uk:443/handbook/mar7a",
    ],
)
def test_authority_source_urls_require_credential_free_https(
    tmp_path: Path, unsafe_url: str
) -> None:
    path = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        path,
        "https://handbook.fca.org.uk/handbook/mar7a?timeline=true",
        unsafe_url,
    )

    with pytest.raises(SecurityControlError, match="HTTPS without credentials"):
        _validate_security_fixture(path)


def test_authority_source_urls_require_trusted_hosts_and_valid_syntax(tmp_path: Path) -> None:
    untrusted = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        untrusted,
        "https://handbook.fca.org.uk/handbook/mar7a?timeline=true",
        "https://example.com/handbook/mar7a",
    )
    with pytest.raises(SecurityControlError, match="trusted official publisher"):
        _validate_security_fixture(untrusted)

    malformed = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        malformed,
        "https://handbook.fca.org.uk/handbook/mar7a?timeline=true",
        "https://[invalid/handbook/mar7a",
    )
    with pytest.raises(SecurityControlError, match="source URL is malformed"):
        _validate_security_fixture(malformed)


def test_map_cannot_claim_legal_advice_or_conclusive_applicability(tmp_path: Path) -> None:
    legal_advice = _map_fixture(tmp_path)
    _replace_security_fixture_text(legal_advice, "legal_advice = false", "legal_advice = true")
    with pytest.raises(SecurityControlError, match="legal_advice must be False"):
        _validate_security_fixture(legal_advice)

    conclusive = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        conclusive,
        'applicability_status = "requires_legal_review"',
        'applicability_status = "applicable"',
    )
    with pytest.raises(SecurityControlError, match="applicability_status must be"):
        _validate_security_fixture(conclusive)


def test_source_profile_consistency_and_review_dates_fail_closed(tmp_path: Path) -> None:
    mismatched_source = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        mismatched_source,
        'source_ids = ["A07-SRC-GB-01", "A07-SRC-GB-02"]',
        'source_ids = ["A07-SRC-GB-01"]',
    )
    with pytest.raises(SecurityControlError, match="source_ids must match"):
        _validate_security_fixture(mismatched_source)

    overdue = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        overdue, 'review_due_on = "2026-11-30"', 'review_due_on = "2026-08-29"'
    )
    with pytest.raises(SecurityControlError, match="legal review is overdue"):
        _validate_security_fixture(overdue)

    excessive_horizon = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        excessive_horizon,
        'review_due_on = "2026-11-30"',
        'review_due_on = "2027-08-30"',
    )
    with pytest.raises(SecurityControlError, match="review horizon exceeds 93 days"):
        _validate_security_fixture(excessive_horizon)

    stale_source = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        stale_source,
        'last_verified_on = "2026-08-30"',
        'last_verified_on = "2026-01-01"',
    )
    with pytest.raises(SecurityControlError, match="verification is older than 31 days"):
        _validate_security_fixture(stale_source)


def test_legal_mappings_bind_owner_and_review_evidence(tmp_path: Path) -> None:
    wrong_owner = _map_fixture(tmp_path)
    _replace_security_fixture_text_after_marker(
        wrong_owner,
        'mapping_id = "A07-MAP-GB-01"',
        'owner_role = "compliance"',
        'owner_role = "security"',
    )
    with pytest.raises(SecurityControlError, match="owner must match"):
        _validate_security_fixture(wrong_owner)

    missing_legal_evidence = _map_fixture(tmp_path)
    _replace_security_fixture_text_after_marker(
        missing_legal_evidence,
        'mapping_id = "A07-MAP-GB-01"',
        'evidence_source_ids = ["A07-EV15"]',
        'evidence_source_ids = ["A07-EV01"]',
    )
    with pytest.raises(SecurityControlError, match="requires A07-EV15"):
        _validate_security_fixture(missing_legal_evidence)


def test_control_status_and_map_coverage_are_evidence_backed(tmp_path: Path) -> None:
    planned_without_deferred = _map_fixture(tmp_path)
    _replace_security_fixture_text_after_marker(
        planned_without_deferred,
        'control_id = "A07-C01"',
        'evidence_source_ids = ["A07-EV05"]',
        'evidence_source_ids = ["A07-EV01"]',
    )
    with pytest.raises(SecurityControlError, match="planned status requires deferred evidence"):
        _validate_security_fixture(planned_without_deferred)

    local_without_available = _map_fixture(tmp_path)
    _replace_security_fixture_text_after_marker(
        local_without_available,
        'control_id = "A07-C12"',
        'evidence_source_ids = ["A07-EV01", "A07-EV02", "A07-EV03", "A07-EV04", "A07-EV05"]',
        'evidence_source_ids = ["A07-EV05"]',
    )
    with pytest.raises(SecurityControlError, match="repository_local status requires"):
        _validate_security_fixture(local_without_available)

    orphan_boundary = _map_fixture(tmp_path)
    _replace_security_fixture_text_after_marker(
        orphan_boundary,
        'threat_id = "A07-T02"',
        'boundary_ids = ["TB02", "TB05"]',
        'boundary_ids = ["TB05"]',
    )
    with pytest.raises(SecurityControlError, match="every trust boundary"):
        _validate_security_fixture(orphan_boundary)

    orphan_asset = _map_fixture(tmp_path)
    for marker, old, new in (
        (
            'boundary_id = "TB02"',
            'asset_ids = ["ASSET01", "ASSET02"]',
            'asset_ids = ["ASSET01"]',
        ),
        (
            'boundary_id = "TB05"',
            'asset_ids = ["ASSET02", "ASSET05"]',
            'asset_ids = ["ASSET05"]',
        ),
        (
            'threat_id = "A07-T02"',
            'asset_ids = ["ASSET01", "ASSET02", "ASSET05"]',
            'asset_ids = ["ASSET01", "ASSET05"]',
        ),
        (
            'threat_id = "A07-T06"',
            'asset_ids = ["ASSET02", "ASSET04", "ASSET05"]',
            'asset_ids = ["ASSET04", "ASSET05"]',
        ),
    ):
        _replace_security_fixture_text_after_marker(orphan_asset, marker, old, new)
    with pytest.raises(SecurityControlError, match="every protected asset"):
        _validate_security_fixture(orphan_asset)

    orphan_evidence = _map_fixture(tmp_path)
    _replace_security_fixture_text_after_marker(
        orphan_evidence,
        'control_id = "A07-C10"',
        'evidence_source_ids = ["A07-EV14"]',
        'evidence_source_ids = ["A07-EV10"]',
    )
    _replace_security_fixture_text_after_marker(
        orphan_evidence,
        'control_id = "A07-C11"',
        'evidence_source_ids = ["A07-EV07", "A07-EV14"]',
        'evidence_source_ids = ["A07-EV07"]',
    )
    with pytest.raises(SecurityControlError, match="every evidence source"):
        _validate_security_fixture(orphan_evidence)


def test_trust_boundary_must_change_zones(tmp_path: Path) -> None:
    path = _map_fixture(tmp_path)
    _replace_security_fixture_text_after_marker(
        path,
        'boundary_id = "TB01"',
        'destination_zone = "protected_forge"',
        'destination_zone = "developer_workstation_and_automation"',
    )
    with pytest.raises(SecurityControlError, match="trust boundary zones must differ"):
        _validate_security_fixture(path)


def test_local_evidence_binds_owner_risk_drivers_and_waivers(tmp_path: Path) -> None:
    wrong_owner_root = _repository_fixture(tmp_path / "owner")
    owner_manifest = (
        wrong_owner_root / "docs/governance/evidence/examples/a07-r2-partial/manifest.toml"
    )
    _replace_security_fixture_text(
        owner_manifest, 'owner_role = "security"', 'owner_role = "platform"'
    )
    with pytest.raises(SecurityControlError, match="owner must match"):
        validate_repository(wrong_owner_root)

    wrong_driver_root = _repository_fixture(tmp_path / "driver")
    driver_manifest = (
        wrong_driver_root / "docs/governance/evidence/examples/a07-r2-partial/manifest.toml"
    )
    _replace_security_fixture_text(
        driver_manifest,
        'security_privilege = "shared_sensitive"',
        'security_privilege = "none"',
    )
    with pytest.raises(SecurityControlError, match="security_privilege"):
        validate_repository(wrong_driver_root)

    waiver_root = _repository_fixture(tmp_path / "waiver")
    waiver_manifest = waiver_root / "docs/governance/evidence/examples/a07-r2-partial/manifest.toml"
    _replace_security_fixture_text(
        waiver_manifest, "waived_controls = []", 'waived_controls = ["synthetic"]'
    )
    with pytest.raises(SecurityControlError, match="cannot contain control waivers"):
        validate_repository(waiver_root)


def test_solo_bootstrap_requires_exact_partial_findings(tmp_path: Path) -> None:
    validated = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        validated, 'package_status = "partial"', 'package_status = "validated"'
    )
    with pytest.raises(SecurityControlError, match="must remain partial"):
        _validate_security_fixture(validated)

    wrong_finding = _map_fixture(tmp_path)
    _replace_security_fixture_text(
        wrong_finding, 'finding_id = "A07-F02"', 'finding_id = "A07-OTHER"'
    )
    with pytest.raises(SecurityControlError, match="must remain partial"):
        _validate_security_fixture(wrong_finding)


def test_cli_emits_byte_stable_filtered_json(capsys: pytest.CaptureFixture[str]) -> None:
    arguments = [str(REPOSITORY_ROOT), "--threat-category", "market_integrity"]
    assert main(arguments) == 0
    first_output = capsys.readouterr().out
    assert main(arguments) == 0
    second_output = capsys.readouterr().out
    assert first_output == second_output

    control_map_payload = json.loads(first_output)
    assert control_map_payload["schema_version"] == 1
    assert control_map_payload["roadmap_package"] == "A07"
    assert control_map_payload["risk_class"] == "R2"
    assert control_map_payload["dependency_package_ids"] == ["A02", "A06"]
    assert control_map_payload["applicable_gate_ids"] == list(APPLICABLE_GATE_IDS)
    assert [item["threat_id"] for item in control_map_payload["threats"]] == [
        "A07-T08",
        "A07-T09",
    ]
    assert control_map_payload["open_finding_ids"] == [
        "A07-F01",
        "A07-F02",
        "A07-F03",
        "A07-F04",
    ]

    assert main([str(REPOSITORY_ROOT), "--jurisdiction", "SG"]) == 0
    jurisdiction_result = json.loads(capsys.readouterr().out)
    assert [item["jurisdiction_id"] for item in jurisdiction_result["jurisdictions"]] == ["SG"]
    assert [item["mapping_id"] for item in jurisdiction_result["regulatory_mappings"]] == [
        "A07-MAP-SG-01"
    ]
