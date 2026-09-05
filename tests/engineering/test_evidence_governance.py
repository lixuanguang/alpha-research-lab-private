"""Deterministic and adversarial tests for evidence governance."""

from __future__ import annotations

# standard library imports
import json
import shutil
import subprocess
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research.change_risk import load_policy as load_change_risk_policy
from alpha_research.evidence import (
    EvidenceGovernanceError,
    classify_mr,
    lint_github_event,
    load_policy,
    main,
    validate_github_event,
    validate_manifest,
    validate_mr_body,
    validate_repository,
    validate_template,
)
from alpha_research_governance.operating_model import Operation, load_operating_model

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "merge-evidence-policy.toml"
CHANGE_POLICY_PATH = REPOSITORY_ROOT / "docs" / "governance" / "change-risk-policy.toml"
EXAMPLE_ROOT = REPOSITORY_ROOT / "docs" / "governance" / "evidence" / "examples" / "a05-valid"
EXAMPLE_SHA = "1" * 40
FOUNDER_BODY = EXAMPLE_ROOT.parent / "founder-pr.md"
LEGACY_FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "governance" / "evidence"


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
    assert tuple(field.key for field in policy.fields) == (
        "problem_change",
        "affected_scope",
        "validation_result",
        "risks_reversal",
    )
    assert policy.schema_version == 2
    assert set(policy.mandatory_package_gates) == {"QG01", "QG13", "QG15"}
    assert manifest.commit_sha == EXAMPLE_SHA
    assert manifest.open_finding_ids == ("A05-F01", "A05-F02")


@pytest.mark.parametrize(
    ("bundle", "commit_sha"),
    (("b01a-r2-partial", "5" * 40), ("b01b-r2-partial", "6" * 40)),
)
def test_legacy_slice_bundles_remain_readable_test_fixtures(bundle: str, commit_sha: str) -> None:
    manifest = validate_manifest(
        LEGACY_FIXTURE_ROOT / bundle / "manifest.toml",
        expected_commit_sha=commit_sha,
        change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
    )

    assert manifest.schema_version == 1
    assert manifest.bundle_status == "partial"


def test_template_must_match_policy_order_and_markers() -> None:
    policy = load_policy(POLICY_PATH)
    template = (REPOSITORY_ROOT / policy.template_path).read_text(encoding="utf-8")

    validate_template(template, policy)

    with pytest.raises(EvidenceGovernanceError, match="headings and order"):
        validate_template(template.replace("## Affected scope", "## Changed scope", 1), policy)
    with pytest.raises(EvidenceGovernanceError, match="required:affected_scope"):
        validate_template(template.replace("<!-- required:affected_scope -->", "", 1), policy)


def test_mr_linter_rejects_missing_duplicate_and_placeholder_fields() -> None:
    policy = load_policy(POLICY_PATH)
    valid = FOUNDER_BODY.read_text(encoding="utf-8")
    validate_mr_body(valid, policy)

    missing = valid.replace("## Affected scope", "## Missing scope", 1)
    with pytest.raises(EvidenceGovernanceError, match="missing required MR field 'Affected scope'"):
        validate_mr_body(missing, policy)

    duplicate = valid + "\n## Affected scope\nA second scope is not permitted.\n"
    with pytest.raises(
        EvidenceGovernanceError, match="duplicate required MR field 'Affected scope'"
    ):
        validate_mr_body(duplicate, policy)

    placeholder = valid.replace(
        "Documentation for the development workflow; no executable or policy files change.",
        "<!-- the comment is ignored -->\nTBD",
        1,
    )
    with pytest.raises(EvidenceGovernanceError, match="empty or placeholder-only"):
        validate_mr_body(placeholder, policy)


def test_github_event_lints_body_and_requires_full_head_sha(tmp_path: Path) -> None:
    policy = load_policy(POLICY_PATH)
    body = FOUNDER_BODY.read_text(encoding="utf-8")
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
            'key = "problem_change"',
            "key = 1",
            r"mr_fields\[1\]\.key must be lower_snake_case",
            id="wrong-mr-field-type",
        ),
        pytest.param(
            'heading = "Problem / change"',
            'heading = "Problem / change"\nunexpected_field = true',
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
                "docs/governance/evidence/examples/founder-pr.md",
                "--manifest",
                "docs/governance/evidence/examples/a05-valid/manifest.toml",
                "--expected-commit-sha",
                EXAMPLE_SHA,
            ]
        )
        == 0
    )


def test_version_one_policy_and_institutional_example_keep_their_contract(tmp_path: Path) -> None:
    text = POLICY_PATH.read_text(encoding="utf-8")
    root = text.split("founder_example_mr_body_path", 1)[0].replace(
        "schema_version = 2", "schema_version = 1"
    )
    legacy_fields = text.split("[[institutional_mr_fields]]", 1)[1]
    legacy = (
        root
        + "[[mr_fields]]"
        + legacy_fields.replace("[[institutional_mr_fields]]", "[[mr_fields]]")
    )
    path = tmp_path / "legacy.toml"
    path.write_text(legacy, encoding="utf-8")
    policy = load_policy(path)
    body = (EXAMPLE_ROOT / "mr.md").read_text(encoding="utf-8")
    assert (
        validate_mr_body(body, policy)["evidence_manifest"]
        == policy.example_manifest_path.as_posix()
    )
    assert validate_mr_body(body, load_policy(POLICY_PATH), profile="institutional")
    with pytest.raises(EvidenceGovernanceError, match="missing required"):
        validate_mr_body(FOUNDER_BODY.read_text(encoding="utf-8"), policy)


@pytest.mark.parametrize("wrapper", ["<!--\n{}\n-->", "```markdown\n{}\n```"])
def test_commented_or_fenced_headings_cannot_satisfy_the_pr(wrapper: str) -> None:
    body = FOUNDER_BODY.read_text(encoding="utf-8")
    with pytest.raises(EvidenceGovernanceError, match="missing required"):
        validate_mr_body(wrapper.format(body), load_policy(POLICY_PATH))


@pytest.mark.parametrize(
    ("paths", "context", "heading"),
    [
        (("schemas/order.proto",), "", "Migration / compatibility"),
        (("benchmarks/latency.py",), "", "Benchmark"),
        (("deploy/service.yaml",), "", "Operational plan"),
        (("docs/guide.md",), '{"migration":true}', "Migration / compatibility"),
        (("src/algorithm.py",), '{"benchmark":true}', "Benchmark"),
        (("docs/runbook.md",), '{"operation":"release"}', "Operational plan"),
    ],
)
def test_conditional_sections_follow_detected_or_declared_impact(
    paths: tuple[str, ...], context: str, heading: str
) -> None:
    policy = load_policy(POLICY_PATH)
    body = FOUNDER_BODY.read_text(encoding="utf-8")
    if context:
        body += f"\n<!-- evidence-context: {context} -->\n"
    with pytest.raises(EvidenceGovernanceError, match="missing required"):
        validate_mr_body(body, policy, changed_paths=paths)
    validate_mr_body(
        body + f"\n## {heading}\nConcrete plan and validation results.\n",
        policy,
        changed_paths=paths,
    )


@pytest.mark.parametrize(
    "context", ['{"benchmark":"false"}', '{"unexpected":true}', "{broken", '{"operation":"deploy"}']
)
def test_malformed_context_fails_closed(context: str) -> None:
    body = FOUNDER_BODY.read_text(encoding="utf-8") + f"\n<!-- evidence-context: {context} -->\n"
    with pytest.raises(EvidenceGovernanceError, match="invalid evidence-context"):
        validate_mr_body(body, load_policy(POLICY_PATH))


def test_metadata_distinguishes_inferred_scope_from_unknown_semantic_risk() -> None:
    body = FOUNDER_BODY.read_text(encoding="utf-8")
    assert classify_mr(body, changed_paths=("docs/guide.md",))["risk_class"] == "R0"
    metadata = classify_mr(body, changed_paths=("src/runtime.py",))
    assert metadata["risk_class"] is None
    assert metadata["classification_source"] == "requires_change_facts"
    assert metadata["required_extras"] == []
    assert classify_mr(body)["risk_class"] is None


def test_declared_facts_are_recomputed_and_activate_high_risk_evidence() -> None:
    body = FOUNDER_BODY.read_text(encoding="utf-8")
    facts = {
        "capital_at_risk": False,
        "blast_radius": "non_capital_runtime",
        "data_model_materiality": "production_serving",
        "security_privilege": "nonproduction_privileged",
        "reversibility": "staged_operational_rollback",
        "computationally_material": False,
        "economically_or_risk_relevant": False,
        "model_or_trading_relevant": False,
        "declared_class": "R3",
    }
    body += f"\n<!-- evidence-context: {json.dumps({'change': facts})} -->\n"
    metadata = classify_mr(
        body,
        changed_paths=("src/runtime.py",),
        change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
    )
    assert metadata["risk_class"] == "R3"
    assert metadata["classification_source"] == "declared_facts"
    assert metadata["required_extras"] == ["operational"]
    with pytest.raises(EvidenceGovernanceError, match="missing required"):
        validate_mr_body(
            body,
            load_policy(POLICY_PATH),
            changed_paths=("src/runtime.py",),
            change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
        )


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Evidence Test",
            "-c",
            "user.email=evidence@example.invalid",
            *arguments,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_hosted_cli_uses_real_diff_accepts_four_sections_and_blocks_missing_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    policy = load_policy(POLICY_PATH)
    for relative in (
        ".github/pull_request_template.md",
        "docs/governance/merge-evidence-policy.toml",
        "docs/governance/change-risk-policy.toml",
        "docs/governance/evidence/examples/founder-pr.md",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / relative, target)
    shutil.copytree(EXAMPLE_ROOT, root / EXAMPLE_ROOT.relative_to(REPOSITORY_ROOT))
    _git(root, "init", "-q")
    changed = root / "docs/change.md"
    changed.write_text("Before\n", encoding="utf-8")
    _git(root, "add", "docs/change.md")
    _git(root, "commit", "-qm", "baseline")
    base = _git(root, "rev-parse", "HEAD")
    changed.write_text("After\n", encoding="utf-8")
    _git(root, "add", "docs/change.md")
    _git(root, "commit", "-qm", "documentation change")
    head = _git(root, "rev-parse", "HEAD")
    body = FOUNDER_BODY.read_text(encoding="utf-8")
    event = tmp_path / "event.json"

    def write_event(event_body: str, head_sha: str = head) -> None:
        event.write_text(
            json.dumps(
                {
                    "pull_request": {
                        "body": event_body,
                        "head": {"sha": head_sha},
                        "base": {"sha": base},
                    }
                }
            ),
            encoding="utf-8",
        )

    write_event(body)
    # The same entry point and --github-event form used by the hosted workflow.
    assert main([str(root), "--github-event", str(event)]) == 0
    metadata = json.loads(capsys.readouterr().out.splitlines()[0])
    assert metadata["head_commit_sha"] == head
    assert metadata["base_commit_sha"] == base
    assert metadata["changed_paths"] == ["docs/change.md"]
    assert metadata["risk_class"] == "R0"
    assert metadata["required_extras"] == []
    write_event(body.replace("## Validation result", "## Missing result"))
    assert main([str(root), "--github-event", str(event)]) == 1
    write_event(body, "0" * 40)
    assert main([str(root), "--github-event", str(event)]) == 1

    schema = root / "schemas/contract.proto"
    schema.parent.mkdir()
    schema.write_text('syntax = "proto3";\n', encoding="utf-8")
    _git(root, "add", "schemas/contract.proto")
    _git(root, "commit", "-qm", "add contract")
    schema_head = _git(root, "rev-parse", "HEAD")
    write_event(body, schema_head)
    assert main([str(root), "--github-event", str(event)]) == 1
    write_event(
        body + "\n## Migration / compatibility\nAdditive schema; revert before use.\n", schema_head
    )
    assert lint_github_event(event, policy, repository_root=root)["required_extras"] == [
        "migration"
    ]
    assert main([str(root), "--github-event", str(event)]) == 0


def _implementation_bundle(tmp_path: Path) -> Path:
    source = EXAMPLE_ROOT.parent / "a06-r2-partial"
    bundle = tmp_path / "implementation"
    shutil.copytree(source, bundle)
    path = bundle / "manifest.toml"
    text = path.read_text(encoding="utf-8").split("\n[[findings]]", 1)[0]
    text = text.replace("schema_version = 1", "schema_version = 2")
    text = text.replace('bundle_status = "partial"', 'bundle_status = "implementation_accepted"')
    text = text.replace(
        'open_finding_ids = ["A06-F01", "A06-F02", "A06-F03"]',
        "open_finding_ids = []\nfindings = []\n"
        'operating_domain = "repository_platform"\n'
        'accepted_by = "@lixuanguang"\naccepted_on = "2026-09-05"',
    )
    path.write_text(text + "\n", encoding="utf-8")
    return path


def test_founder_r2_implementation_acceptance_needs_no_external_approvals_or_findings(
    tmp_path: Path,
) -> None:
    path = _implementation_bundle(tmp_path)
    manifest = validate_manifest(
        path,
        expected_commit_sha="2" * 40,
        change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
        operating_model=load_operating_model(
            REPOSITORY_ROOT / "docs/governance/domain-ownership.toml"
        ),
    )
    assert manifest.bundle_status == "implementation_accepted"
    assert manifest.schema_version == 2
    assert manifest.approvals == ()
    assert manifest.open_finding_ids == ()
    assert manifest.risk_class == "R2"


@pytest.mark.parametrize("operation", ["release", "activation", "institutional_acceptance"])
def test_implementation_bundle_cannot_authorize_institutional_operations(
    tmp_path: Path, operation: Operation
) -> None:
    with pytest.raises(EvidenceGovernanceError, match="cannot authorize institutional operations"):
        validate_manifest(
            _implementation_bundle(tmp_path),
            expected_commit_sha="2" * 40,
            change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
            operating_model=load_operating_model(
                REPOSITORY_ROOT / "docs/governance/domain-ownership.toml"
            ),
            operation=operation,
        )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('status = "passed"', 'status = "failed"', "passing repository-local evidence"),
        ('status = "passed"', 'status = "deferred"', "passing repository-local evidence"),
        ('gate_id = "QG01"', 'gate_id = "QG15"', "required gates are missing"),
        ('accepted_by = "@lixuanguang"', 'accepted_by = "@someone"', "recorded founder"),
        ('accepted_on = "2026-09-05"', 'accepted_on = "2026-09-01"', "not active"),
        (
            'operating_domain = "repository_platform"',
            'operating_domain = "unknown"',
            "unknown operating domain",
        ),
        (
            'bundle_status = "implementation_accepted"',
            'bundle_status = "accepted"',
            "schema_version 2 requires",
        ),
        ("schema_version = 2", "schema_version = 1", "fields must be exactly"),
        (
            "waived_controls = []",
            'waived_controls = ["technical_failure"]',
            "cannot contain institutional approvals or waivers",
        ),
    ],
)
def test_implementation_acceptance_rejects_technical_failure_and_false_authority(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = _implementation_bundle(tmp_path)
    _replace_evidence_fixture_text(path, old, new)
    with pytest.raises(EvidenceGovernanceError, match=message):
        validate_manifest(
            path,
            expected_commit_sha="2" * 40,
            change_policy=load_change_risk_policy(CHANGE_POLICY_PATH),
            operating_model=load_operating_model(
                REPOSITORY_ROOT / "docs/governance/domain-ownership.toml"
            ),
        )


def test_implementation_acceptance_still_checks_source_identity_and_artifact_digest(
    tmp_path: Path,
) -> None:
    path = _implementation_bundle(tmp_path)
    model = load_operating_model(REPOSITORY_ROOT / "docs/governance/domain-ownership.toml")
    policy = load_change_risk_policy(CHANGE_POLICY_PATH)
    with pytest.raises(EvidenceGovernanceError, match="does not match expected commit"):
        validate_manifest(
            path, expected_commit_sha="3" * 40, change_policy=policy, operating_model=model
        )
    report = next((path.parent / "reports").iterdir())
    report.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(EvidenceGovernanceError, match="SHA-256 mismatch"):
        validate_manifest(
            path, expected_commit_sha="2" * 40, change_policy=policy, operating_model=model
        )
