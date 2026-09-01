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
        "make test",
        "make smoke",
        "make build",
        "make check",
    ):
        assert f"`{command}`" in documentation
