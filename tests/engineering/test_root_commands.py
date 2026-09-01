"""Contract tests for the repository root command interface."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
ROOT_TARGETS = (
    "sync",
    "lock-check",
    "format",
    "format-check",
    "lint",
    "typecheck",
    "architecture-check",
    "ownership-check",
    "change-risk-check",
    "evidence-check",
    "topology-check",
    "inventory-check",
    "security-controls-check",
    "program-governance-check",
    "security",
    "bazel-build",
    "bazel-test",
    "bazel-check",
    "rollback-test",
    "rollback-build",
    "rollback-check",
    "test",
    "smoke",
    "build",
    "check",
)
GOVERNANCE_COMMANDS = (
    "alpha-governance-change-risk",
    "alpha-governance-evidence",
    "alpha-governance-inventory",
    "alpha-governance-program",
    "alpha-governance-security",
    "alpha-governance-topology",
)


def _run_make(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_documented_root_targets_are_available() -> None:
    failures: dict[str, str] = {}
    for target in ROOT_TARGETS:
        dry_run = _run_make("-n", target)
        if dry_run.returncode != 0:
            failures[target] = dry_run.stderr

    assert failures == {}


def test_check_runs_every_configured_non_mutating_command() -> None:
    check_dry_run = _run_make("-n", "check")

    assert check_dry_run.returncode == 0, check_dry_run.stderr
    assert check_dry_run.stdout.splitlines() == [
        "bazel build --config=ci //src/alpha_research:alpha_research "
        "//tools/governance/src/alpha_research_governance:all "
        "//tests/build/fixtures/sql:build_evidence //:docs_bundle",
        "B02_UNDECLARED_SECRET=synthetic-host-only bazel test --config=ci //:b02_tests",
        "uv lock --check",
        "uv run --frozen ruff check src tests tools/governance/src",
        "uv run --frozen ruff format --check src tests tools/governance/src",
        "uv run --frozen mypy --strict src tests tools/governance/src",
        "uv run --frozen alpha-governance-architecture",
        "uv run --frozen alpha-governance-ownership",
        "uv run --frozen alpha-governance-change-risk",
        "uv run --frozen alpha-governance-evidence",
        "uv run --frozen alpha-governance-topology",
        "uv run --frozen alpha-governance-inventory",
        "uv run --frozen alpha-governance-security",
        "uv run --frozen alpha-governance-program",
        "uv run --frozen bandit -q -c pyproject.toml -r src tools/governance/src",
        "uv run --frozen --no-editable pytest -q",
        'uv run --frozen --no-editable python -c "import alpha_research"',
        "uv build --no-sources",
    ]


def test_uv_backend_preserves_the_legacy_rollback_path() -> None:
    rollback_dry_run = _run_make("-n", "BUILD_BACKEND=uv", "check")

    assert rollback_dry_run.returncode == 0, rollback_dry_run.stderr
    assert "bazel " not in rollback_dry_run.stdout
    assert rollback_dry_run.stdout.splitlines() == [
        "uv lock --check",
        "uv run --frozen ruff check src tests tools/governance/src",
        "uv run --frozen ruff format --check src tests tools/governance/src",
        "uv run --frozen mypy --strict src tests tools/governance/src",
        "uv run --frozen alpha-governance-architecture",
        "uv run --frozen alpha-governance-ownership",
        "uv run --frozen alpha-governance-change-risk",
        "uv run --frozen alpha-governance-evidence",
        "uv run --frozen alpha-governance-topology",
        "uv run --frozen alpha-governance-inventory",
        "uv run --frozen alpha-governance-security",
        "uv run --frozen alpha-governance-program",
        "uv run --frozen bandit -q -c pyproject.toml -r src tools/governance/src",
        "uv run --frozen --no-editable pytest -q",
        'uv run --frozen --no-editable python -c "import alpha_research"',
        "uv build --no-sources",
    ]


def test_unknown_build_backend_fails_closed() -> None:
    invalid_backend = _run_make("-n", "BUILD_BACKEND=unknown", "check")

    assert invalid_backend.returncode != 0
    assert "BUILD_BACKEND must be 'bazel' or 'uv'" in invalid_backend.stderr


def test_format_and_format_check_have_distinct_mutation_behavior() -> None:
    format_result = _run_make("-n", "format")
    check_result = _run_make("-n", "format-check")

    assert format_result.stdout.strip() == (
        "uv run --frozen ruff format src tests tools/governance/src"
    )
    assert check_result.stdout.strip() == (
        "uv run --frozen ruff format --check src tests tools/governance/src"
    )


def test_root_target_propagates_tool_failure() -> None:
    smoke_failure = _run_make("UV=false", "smoke")

    assert smoke_failure.returncode != 0
    assert (
        'false run --frozen --no-editable python -c "import alpha_research"' in smoke_failure.stdout
    )


def test_bazel_delegate_propagates_failure() -> None:
    bazel_failure = _run_make("BAZEL=false", "test")

    assert bazel_failure.returncode != 0
    assert (
        "B02_UNDECLARED_SECRET=synthetic-host-only false test --config=ci //:b02_tests"
        in bazel_failure.stdout
    )


def test_repository_automation_wires_current_toolchain_and_governance_checks() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    pre_commit = (REPOSITORY_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    continuous_integration = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    documentation = (REPOSITORY_ROOT / "docs/README.md").read_text(encoding="utf-8")

    for canonical_command in GOVERNANCE_COMMANDS:
        assert canonical_command in makefile
        assert canonical_command in pre_commit
        assert canonical_command in continuous_integration

    assert "tools/governance/src/alpha_research_governance/change_risk/[a-z_]+\\.py" in (pre_commit)
    assert "--github-event" in continuous_integration
    for command_suffix in ("ownership", "change-risk", "evidence"):
        assert f"uv run --frozen alpha-governance-{command_suffix}" in pre_commit
    assert "id: repository-topology" in pre_commit
    assert "always_run: true" in pre_commit

    automation_configuration = makefile + pre_commit + continuous_integration
    assert "python -m alpha_research." not in automation_configuration
    assert "PYTHONPATH=src" not in automation_configuration
    assert all(
        fragment not in automation_configuration
        for fragment in (
            "alpha_core",
            "apps/",
            "duckdb",
            "libs/core",
            "research-smoke",
            'python-version: ["3.11"]',
            ".[dev,research]",
        )
    )

    assert "uv sync --frozen" in continuous_integration
    assert "uv build --no-sources" in continuous_integration
    assert 'version: "0.12.7"' in continuous_integration
    assert "repo: local" in pre_commit
    assert "uv lock --check" in pre_commit
    for make_target in (
        "inventory-check",
        "program-governance-check",
        "security-controls-check",
    ):
        assert f"make {make_target}" in documentation
