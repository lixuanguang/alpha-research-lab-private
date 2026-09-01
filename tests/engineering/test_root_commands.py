"""Contract tests for the repository root command interface."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]


def _run_make(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "target",
    [
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
    ],
)
def test_documented_root_target_is_available(target: str) -> None:
    dry_run = _run_make("-n", target)

    assert dry_run.returncode == 0, dry_run.stderr


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


def test_topology_target_propagates_canonical_tool_failure() -> None:
    topology_failure = _run_make("UV=false", "topology-check")

    assert topology_failure.returncode != 0
    assert "false run --frozen alpha-governance-topology" in topology_failure.stdout


def test_root_interface_is_documented() -> None:
    documentation = (REPOSITORY_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    for command in (
        "make sync",
        "make format",
        "make format-check",
        "make lint",
        "make typecheck",
        "make architecture-check",
        "make ownership-check",
        "make change-risk-check",
        "make evidence-check",
        "make topology-check",
        "make inventory-check",
        "make security-controls-check",
        "make program-governance-check",
        "make security",
        "make bazel-build",
        "make bazel-test",
        "make bazel-check",
        "make rollback-check",
        "make test",
        "make smoke",
        "make build",
        "make check",
    ):
        assert f"`{command}`" in documentation
