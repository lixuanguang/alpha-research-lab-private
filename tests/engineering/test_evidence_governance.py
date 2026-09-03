"""Deterministic and adversarial tests for evidence governance."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from alpha_research.change_risk import load_policy as load_change_risk_policy
from alpha_research.evidence import (
    EvidenceGovernanceError,
    load_policy,
    main,
    validate_github_event,
    validate_manifest,
    validate_mr_body,
    validate_repository,
    validate_template,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "merge-evidence-policy.toml"
CHANGE_POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "change-risk-policy.toml"
EXAMPLE_ROOT = REPOSITORY_ROOT / "docs" / "governance" / "evidence" / "examples" / "a05-valid"
EXAMPLE_SHA = "1" * 40


def _bundle_fixture(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    shutil.copytree(EXAMPLE_ROOT, bundle)
    return bundle


def _replace_evidence_fixture_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _validate_fixture_manifest(bundle: Path) -> None:
    validate_manifest(
        bundle / "manifest.toml",
        expected_commit_sha=EXAMPLE_SHA,
        change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
    )


def test_repository_evidence_policy_template_and_example_validate_end_to_end() -> None:
    policy, manifest = validate_repository(REPOSITORY_ROOT)

    assert policy.package_status == "partial"
    assert len(policy.fields) == 29
    assert set(policy.mandatory_package_gates) == {"QG01", "QG13", "QG15"}
    assert manifest.commit_sha == EXAMPLE_SHA
    assert manifest.open_finding_ids == ("A05-F01", "A05-F02")


def test_template_must_match_policy_order_and_markers() -> None:
    policy = load_policy(POLICY_PATH)
    template = (REPOSITORY_ROOT / policy.template_path).read_text(encoding="utf-8")

    validate_template(template, policy)

    with pytest.raises(EvidenceGovernanceError, match="headings and order"):
        validate_template(template.replace("### Scope", "### Changed scope", 1), policy)
    with pytest.raises(EvidenceGovernanceError, match="required:scope"):
        validate_template(template.replace("<!-- required:scope -->", "", 1), policy)


def test_mr_linter_rejects_missing_duplicate_and_placeholder_fields() -> None:
    policy = load_policy(POLICY_PATH)
    valid = (EXAMPLE_ROOT / "mr.md").read_text(encoding="utf-8")
    validate_mr_body(valid, policy)

    missing = valid.replace("### Scope", "### Missing scope", 1)
    with pytest.raises(EvidenceGovernanceError, match="missing required MR field 'Scope'"):
        validate_mr_body(missing, policy)

    duplicate = valid + "\n### Scope\nA second scope is not permitted.\n"
    with pytest.raises(EvidenceGovernanceError, match="duplicate required MR field 'Scope'"):
        validate_mr_body(duplicate, policy)

    placeholder = valid.replace(
        "Platform.",
        "<!-- the comment is ignored -->\nTBD",
        1,
    )
    with pytest.raises(EvidenceGovernanceError, match="empty or placeholder-only"):
        validate_mr_body(placeholder, policy)


def test_github_event_lints_body_and_requires_full_head_sha(tmp_path: Path) -> None:
    policy = load_policy(POLICY_PATH)
    body = (EXAMPLE_ROOT / "mr.md").read_text(encoding="utf-8")
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"body": body, "head": {"sha": EXAMPLE_SHA}}}),
        encoding="utf-8",
    )

    assert validate_github_event(event, policy) == EXAMPLE_SHA

    event.write_text(
        json.dumps({"pull_request": {"body": body, "head": {"sha": "short"}}}),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceGovernanceError, match="full lowercase SHA"):
        validate_github_event(event, policy)


def test_manifest_rejects_expected_commit_mismatch(tmp_path: Path) -> None:
    bundle = _bundle_fixture(tmp_path)

    with pytest.raises(EvidenceGovernanceError, match="does not match expected commit"):
        validate_manifest(
            bundle / "manifest.toml",
            expected_commit_sha="2" * 40,
            change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
        )


def test_manifest_rejects_artifact_tampering(tmp_path: Path) -> None:
    bundle = _bundle_fixture(tmp_path)
    (bundle / "reports" / "sha-binding.txt").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(EvidenceGovernanceError, match="SHA-256 mismatch"):
        _validate_fixture_manifest(bundle)


@pytest.mark.parametrize("unsafe_path", ["../outside.txt", "/tmp/outside.txt"])
def test_manifest_rejects_artifact_path_escape(tmp_path: Path, unsafe_path: str) -> None:
    bundle = _bundle_fixture(tmp_path)
    _replace_evidence_fixture_text(
        bundle / "manifest.toml", 'path = "reports/source-hygiene.txt"', f'path = "{unsafe_path}"'
    )

    with pytest.raises(EvidenceGovernanceError, match="escapes the bundle"):
        _validate_fixture_manifest(bundle)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        pytest.param(
            "\n\n[change]",
            "\nunexpected_field = true\n\n[change]",
            "fields must be exactly",
            id="unknown-root-field",
        ),
        pytest.param(
            "schema_version = 1",
            "schema_version = true",
            "schema_version must be 1",
            id="wrong-schema-version-type",
        ),
        pytest.param(
            'additional_required_gates = ["QG15"]',
            "additional_required_gates = [1]",
            "additional_required_gates must be an array of non-empty strings",
            id="wrong-root-array-item-type",
        ),
        pytest.param(
            "capital_at_risk = false",
            'capital_at_risk = "false"',
            r"change\.capital_at_risk must be Boolean",
            id="wrong-change-boolean-type",
        ),
        pytest.param(
            'evidence_ids = ["source-hygiene"]',
            'evidence_ids = ["source-hygiene"]\nunexpected_field = true',
            r"gates\[1\] has missing or unknown fields",
            id="unknown-gate-field",
        ),
        pytest.param(
            'path = "reports/source-hygiene.txt"',
            "path = 1",
            r"artifacts\[1\]\.path must be a non-empty string",
            id="wrong-artifact-path-type",
        ),
        pytest.param(
            'owner_role = "platform_ci"',
            "owner_role = 1",
            r"findings\[1\]\.owner_role must be a non-empty string",
            id="wrong-finding-owner-type",
        ),
    ],
)
def test_manifest_input_schema_preserves_structural_error_contract(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    bundle = _bundle_fixture(tmp_path)
    _replace_evidence_fixture_text(bundle / "manifest.toml", old, new)

    with pytest.raises(EvidenceGovernanceError, match=message):
        _validate_fixture_manifest(bundle)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('risk_class = "R0"', 'risk_class = "R1"', "does not match A04 classification"),
        (
            'evidence_retention_class = "source_governance_record"',
            'evidence_retention_class = "short_lived"',
            "does not match A04 classification",
        ),
        ('gate_id = "QG13"', 'gate_id = "QG02"', "required gates are missing"),
        (
            'evidence_ids = ["source-hygiene"]',
            'evidence_ids = ["unknown-evidence"]',
            "unknown evidence",
        ),
    ],
)
def test_manifest_recomputes_risk_and_rejects_missing_or_unknown_evidence(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    bundle = _bundle_fixture(tmp_path)
    _replace_evidence_fixture_text(bundle / "manifest.toml", old, new)

    with pytest.raises(EvidenceGovernanceError, match=message):
        _validate_fixture_manifest(bundle)


def test_required_gate_cannot_be_not_applicable(tmp_path: Path) -> None:
    bundle = _bundle_fixture(tmp_path)
    _replace_evidence_fixture_text(
        bundle / "manifest.toml", 'status = "passed"', 'status = "not_applicable"'
    )

    with pytest.raises(EvidenceGovernanceError, match="required gates cannot be not_applicable"):
        _validate_fixture_manifest(bundle)


def test_partial_bundle_requires_owned_findings(tmp_path: Path) -> None:
    bundle = _bundle_fixture(tmp_path)
    manifest = bundle / "manifest.toml"
    text = manifest.read_text(encoding="utf-8").split("\n[[findings]]", maxsplit=1)[0]
    text = text.replace(
        'open_finding_ids = ["A05-F01", "A05-F02"]',
        "open_finding_ids = []",
    )
    text = text.replace("approvals = []", "approvals = []\nfindings = []")
    manifest.write_text(text + "\n", encoding="utf-8")

    with pytest.raises(EvidenceGovernanceError, match="partial bundle requires"):
        _validate_fixture_manifest(bundle)


def test_accepted_bundle_requires_commit_bound_class_approvals(tmp_path: Path) -> None:
    bundle = _bundle_fixture(tmp_path)
    manifest = bundle / "manifest.toml"
    text = manifest.read_text(encoding="utf-8").split("\n[[findings]]", maxsplit=1)[0]
    text = text.replace('bundle_status = "partial"', 'bundle_status = "accepted"')
    text = text.replace(
        'open_finding_ids = ["A05-F01", "A05-F02"]',
        "open_finding_ids = []",
    )
    text = text.replace("approvals = []", "approvals = []\nfindings = []")
    manifest.write_text(text + "\n", encoding="utf-8")

    with pytest.raises(EvidenceGovernanceError, match="requires at least 1 distinct approvers"):
        _validate_fixture_manifest(bundle)


def test_accepted_bundle_passes_with_commit_bound_class_approval(tmp_path: Path) -> None:
    bundle = _bundle_fixture(tmp_path)
    manifest = bundle / "manifest.toml"
    text = manifest.read_text(encoding="utf-8").split("\n[[findings]]", maxsplit=1)[0]
    text = text.replace('bundle_status = "partial"', 'bundle_status = "accepted"')
    text = text.replace(
        'open_finding_ids = ["A05-F01", "A05-F02"]',
        "open_finding_ids = []",
    )
    approval = f"""findings = []

[[approvals]]
reviewer_id = "code-owner"
roles = ["code_owner"]
independent = false
is_author = false
status = "approved"
commit_sha = "{EXAMPLE_SHA}"
evidence_url = "https://forge.example/reviews/a05-fixture"
"""
    text = text.replace("approvals = []", approval.rstrip())
    manifest.write_text(text + "\n", encoding="utf-8")

    validated = validate_manifest(
        manifest,
        expected_commit_sha=EXAMPLE_SHA,
        change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
    )

    assert validated.bundle_status == "accepted"
    assert len(validated.approvals) == 1
    assert validated.approvals[0].status == "approved"


@pytest.mark.parametrize(
    "evidence_url",
    [
        "https://:synthetic-secret@forge.example/reviews/a05-fixture",
        "https://[malformed/reviews/a05-fixture",
    ],
)
def test_accepted_bundle_rejects_credentialed_or_malformed_approval_urls(
    tmp_path: Path, evidence_url: str
) -> None:
    bundle = _bundle_fixture(tmp_path)
    manifest = bundle / "manifest.toml"
    text = manifest.read_text(encoding="utf-8").split("\n[[findings]]", maxsplit=1)[0]
    text = text.replace('bundle_status = "partial"', 'bundle_status = "accepted"')
    text = text.replace(
        'open_finding_ids = ["A05-F01", "A05-F02"]',
        "open_finding_ids = []",
    )
    approval = f'''findings = []

[[approvals]]
reviewer_id = "code-owner"
roles = ["code_owner"]
independent = false
is_author = false
status = "approved"
commit_sha = "{EXAMPLE_SHA}"
evidence_url = "{evidence_url}"
'''
    text = text.replace("approvals = []", approval.rstrip())
    manifest.write_text(text + "\n", encoding="utf-8")

    with pytest.raises(EvidenceGovernanceError, match="HTTPS URL"):
        _validate_fixture_manifest(bundle)


def test_policy_cannot_weaken_required_evidence_gates_or_hide_findings(tmp_path: Path) -> None:
    policy = tmp_path / "merge-evidence-policy.toml"
    policy.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    _replace_evidence_fixture_text(policy, '["QG01", "QG13", "QG15"]', '["QG01", "QG13"]')
    with pytest.raises(EvidenceGovernanceError, match="requires QG01, QG13, and QG15"):
        load_policy(policy)

    policy.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    _replace_evidence_fixture_text(policy, 'finding_id = "A05-F02"', 'finding_id = "A05-OTHER"')
    with pytest.raises(EvidenceGovernanceError, match="partial status requires findings"):
        load_policy(policy)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        pytest.param(
            "\n\n[[mr_fields]]",
            "\nunexpected_field = true\n\n[[mr_fields]]",
            "fields must be exactly",
            id="unknown-root-field",
        ),
        pytest.param(
            'applicable_gates = ["QG01", "QG03", "QG12", "QG13", "QG15"]',
            "applicable_gates = [1]",
            "applicable_gates must contain non-empty strings",
            id="wrong-gate-item-type",
        ),
        pytest.param(
            'key = "problem_or_hypothesis"',
            "key = 1",
            r"mr_fields\[1\]\.key must be lower_snake_case",
            id="wrong-mr-field-type",
        ),
        pytest.param(
            'heading = "Problem or hypothesis"',
            'heading = "Problem or hypothesis"\nunexpected_field = true',
            r"mr_fields\[1\] must contain key and heading",
            id="unknown-mr-field",
        ),
    ],
)
def test_policy_input_schema_preserves_structural_error_contract(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    policy = tmp_path / "merge-evidence-policy.toml"
    policy.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    _replace_evidence_fixture_text(policy, old, new)

    with pytest.raises(EvidenceGovernanceError, match=message):
        load_policy(policy)


def test_command_accepts_repository_relative_mr_and_manifest_paths() -> None:
    assert (
        main(
            [
                str(REPOSITORY_ROOT),
                "--mr-body",
                "docs/governance/evidence/examples/a05-valid/mr.md",
                "--manifest",
                "docs/governance/evidence/examples/a05-valid/manifest.toml",
                "--expected-commit-sha",
                EXAMPLE_SHA,
            ]
        )
        == 0
    )
