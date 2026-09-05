"""Deterministic, property, and state-machine tests for engineering standards."""

from __future__ import annotations

# standard library imports
import os
from datetime import date
from pathlib import Path
from time import perf_counter

# third party library imports
import pytest
from hypothesis import given, settings, strategies

# project library imports
from alpha_research_governance.engineering_standards import (
    EngineeringStandardsError,
    load_standards,
    main,
    source_tree_findings,
    validate_repository,
    validate_suppression_line,
)
from alpha_research_governance.engineering_standards.policy import (
    _locked_packages,
    _validate_dependency_record,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
POLICY_PATH = REPOSITORY_ROOT / "docs/architecture/engineering-standards.toml"
VALIDATION_DATE = date(2026, 9, 2)
OWNER_ROLES = frozenset({"platform", "security"})
UNDER_BAZEL = bool(os.environ.get("TEST_SRCDIR"))
VALID_SUPPRESSION = (
    "value = call()  # noqa: RUF100 - retained compatibility "
    "[owner=platform; rationale=preserve public behavior; expires=2026-12-31]"
)
REPRESENTATIVE_POLICY_MUTATIONS = (
    ("schema_version = 1", "schema_version = 2"),
    ('roadmap_package = "B04"', 'roadmap_package = "B05"'),
    ('package_status = "partial"', 'package_status = "validated"'),
    ('risk_class = "R2"', 'risk_class = "R1"'),
    ('successor_package = "B05"', 'successor_package = "B06"'),
    ("global_epsilon_allowed = false", "global_epsilon_allowed = true"),
    ('non_finite_default = "reject"', 'non_finite_default = "allow"'),
    ("maximum_examples = 50", "maximum_examples = 1"),
    ("mutation_cases_rejected = 12", "mutation_cases_rejected = 11"),
    (
        'language_id = "c_cpp"\nadmission_status = "dormant"',
        'language_id = "c_cpp"\nadmission_status = "admitted"',
    ),
    (
        'sanitizers = ["address", "undefined_behavior", "thread_for_shared_memory"]',
        'sanitizers = ["address"]',
    ),
    (
        'open_finding_ids = ["B04-F01", "B04-F02", "B04-F03"]',
        'open_finding_ids = ["B04-F01", "B04-F02"]',
    ),
)


def _policy_fixture(tmp_path: Path) -> Path:
    """Copy and overwrite the repository policy in a temporary TOML fixture.

    Args:
        tmp_path: Pytest temporary directory for the current test case.

    Returns:
        Temporary policy path containing the repository's exact policy text.

    Raises:
        OSError: If reading the source policy or writing the fixture fails.
    """
    path = tmp_path / "engineering-standards.toml"
    path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return path


@pytest.mark.skipif(UNDER_BAZEL, reason="repository evidence rejects Bazel runfile symlinks")
def test_repository_standards_bind_exact_tools_languages_and_baselines() -> None:
    """Validate exact tool, language, baseline, and open-finding policy bindings."""
    standards = validate_repository(REPOSITORY_ROOT, validation_date=VALIDATION_DATE)

    assert standards.package_status == "partial"
    assert standards.successor_package == "B05"
    assert standards.hypothesis_version == "6.167.1"
    assert standards.hypothesis_maximum_examples == 50
    assert standards.coverage_statement_percent == 81
    assert (
        standards.mutation_cases
        == standards.mutation_cases_rejected
        == len(REPRESENTATIVE_POLICY_MUTATIONS)
    )
    assert tuple(tool.tool_id for tool in standards.tools) == tuple(
        sorted(tool.tool_id for tool in standards.tools)
    )
    assert tuple(language.language_id for language in standards.languages) == (
        "python",
        "c_cpp",
        "rust",
    )
    assert standards.open_finding_ids == ("B04-F01", "B04-F02", "B04-F03")


@pytest.mark.parametrize(("old", "new"), REPRESENTATIVE_POLICY_MUTATIONS)
def test_representative_policy_mutations_are_rejected(tmp_path: Path, old: str, new: str) -> None:
    """Reject representative mutations that alter or weaken governed policy values."""
    path = _policy_fixture(tmp_path)
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(EngineeringStandardsError):
        load_standards(path)


def test_unknown_field_and_malformed_toml_fail_closed(tmp_path: Path) -> None:
    """Reject unknown policy fields and malformed TOML with controlled errors."""
    unknown = _policy_fixture(tmp_path)
    unknown.write_text(unknown.read_text(encoding="utf-8") + "\nunknown = true\n", encoding="utf-8")
    with pytest.raises(EngineeringStandardsError, match="missing or unknown fields"):
        load_standards(unknown)

    malformed = tmp_path / "malformed.toml"
    malformed.write_text("schema_version = [\n", encoding="utf-8")
    with pytest.raises(EngineeringStandardsError, match="invalid TOML"):
        load_standards(malformed)


def test_dependency_record_version_and_native_artifact_drift_fail_closed(tmp_path: Path) -> None:
    """Reject dependency-version drift and removed native-artifact evidence."""
    architecture = tmp_path / "docs/architecture"
    architecture.mkdir(parents=True)
    dependency_record = architecture / "engineering-tool-dependencies.toml"
    source_record = REPOSITORY_ROOT / "docs/architecture/engineering-tool-dependencies.toml"
    dependency_record.write_text(source_record.read_text(encoding="utf-8"), encoding="utf-8")
    locked = _locked_packages(REPOSITORY_ROOT / "uv.lock")
    assert _validate_dependency_record(tmp_path, locked) == []

    content = dependency_record.read_text(encoding="utf-8")
    content = content.replace('version = "6.167.1"', 'version = "6.167.0"', 1)
    content = content.replace(
        '  "hypothesis==6.167.1 platform wheels contain upstream native extension artifacts",\n',
        "",
        1,
    )
    dependency_record.write_text(content, encoding="utf-8")

    findings = _validate_dependency_record(tmp_path, locked)
    assert any("identity, version, source, or license" in finding for finding in findings)
    assert any("transitive dependency record" in finding for finding in findings)


@settings(max_examples=50, derandomize=True, deadline=None)
@given(
    owner=strategies.sampled_from(sorted(OWNER_ROLES)),
    rationale=strategies.text(
        alphabet=strategies.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=12,
        max_size=40,
    ),
    days=strategies.integers(min_value=0, max_value=180),
)
def test_suppression_metadata_accepts_governed_bounded_values(
    owner: str, rationale: str, days: int
) -> None:
    """Accept governed suppression metadata with valid ownership and bounded expiry."""
    expiry = date.fromordinal(VALIDATION_DATE.toordinal() + days)
    line = (
        "value = call()  # nosec B603 "
        f"[owner={owner}; rationale={rationale}; expires={expiry.isoformat()}]"
    )

    assert (
        validate_suppression_line(
            line,
            owner_roles=OWNER_ROLES,
            validation_date=VALIDATION_DATE,
            maximum_lifetime_days=180,
            minimum_rationale_characters=12,
        )
        == ()
    )


@settings(max_examples=50, derandomize=True, deadline=None)
@given(field=strategies.sampled_from(("owner", "rationale", "expires")))
def test_suppression_metadata_rejects_a_missing_required_field(field: str) -> None:
    """Reject suppression metadata missing any required owner, rationale, or expiry field."""
    metadata = {
        "owner": "owner=platform",
        "rationale": "rationale=preserve public behavior",
        "expires": "expires=2026-12-31",
    }
    metadata.pop(field)
    line = "value = call()  # noqa: RUF100 [" + "; ".join(metadata.values()) + "]"

    assert validate_suppression_line(
        line,
        owner_roles=OWNER_ROLES,
        validation_date=VALIDATION_DATE,
        maximum_lifetime_days=180,
        minimum_rationale_characters=12,
    )


def test_expired_unknown_owner_and_excessive_lifetime_are_rejected() -> None:
    """Report expired, ungoverned-owner, and overlong suppression metadata."""
    cases = (
        (
            "[owner=platform; rationale=preserve behavior; expires=2026-09-01]",
            "expired",
        ),
        (
            "[owner=former_owner; rationale=preserve behavior; expires=2026-12-31]",
            "not a governed role",
        ),
        (
            "[owner=platform; rationale=preserve behavior; expires=2027-09-02]",
            "maximum lifetime",
        ),
    )
    for metadata, message in cases:
        findings = validate_suppression_line(
            f"value = call()  # nosec B603 {metadata}",
            owner_roles=OWNER_ROLES,
            validation_date=VALIDATION_DATE,
            maximum_lifetime_days=180,
            minimum_rationale_characters=12,
        )
        assert any(message in finding for finding in findings)


def test_source_scan_rejects_generated_and_unadmitted_native_source(tmp_path: Path) -> None:
    """Report generated source, unadmitted native source, and malformed Python input."""
    standards = load_standards(POLICY_PATH)
    for source_root in standards.source_roots:
        (tmp_path / source_root).mkdir(parents=True)
    (tmp_path / "src/alpha_research/generated.py").write_text(
        "# @generated\nvalue = 1\n", encoding="utf-8"
    )
    (tmp_path / "tools/governance/src/alpha_research_governance/native.rs").write_text(
        "fn main() {}\n", encoding="utf-8"
    )
    (tmp_path / "tests/malformed.py").write_text("'''unterminated\n", encoding="utf-8")

    findings = source_tree_findings(
        tmp_path,
        standards,
        owner_roles=OWNER_ROLES,
        validation_date=VALIDATION_DATE,
    )

    assert any("generated source" in finding for finding in findings)
    assert any("native language source" in finding for finding in findings)
    assert any("cannot tokenize Python source" in finding for finding in findings)


@pytest.mark.performance
def test_suppression_validation_workload_stays_within_budget() -> None:
    """Keep repeated suppression validation within the configured performance budget."""
    standards = load_standards(POLICY_PATH)
    started_at = perf_counter()
    for _ in range(standards.validation_workload_iterations):
        assert (
            validate_suppression_line(
                VALID_SUPPRESSION,
                owner_roles=OWNER_ROLES,
                validation_date=VALIDATION_DATE,
                maximum_lifetime_days=standards.suppression_maximum_lifetime_days,
                minimum_rationale_characters=standards.suppression_minimum_rationale_characters,
            )
            == ()
        )
    elapsed_ms = (perf_counter() - started_at) * 1_000

    assert elapsed_ms <= standards.validation_workload_budget_ms


def test_cli_reports_success_usage_error_and_missing_repository(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Return success, usage-error, and missing-repository statuses with matching output."""
    if not UNDER_BAZEL:
        assert main([str(REPOSITORY_ROOT)]) == 0
        assert "package status is partial" in capsys.readouterr().out
    assert main(["one", "two"]) == 2
    assert "usage:" in capsys.readouterr().err
    assert main([str(REPOSITORY_ROOT / "missing")]) == 1
    assert "No such file" in capsys.readouterr().err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
