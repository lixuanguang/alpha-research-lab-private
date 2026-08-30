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
        "inventory-check",
        "security",
        "test",
        "smoke",
        "build",
        "check",
    ],
)
def test_documented_root_target_is_available(target: str) -> None:
    result = _run_make("-n", target)

    assert result.returncode == 0, result.stderr


def test_check_runs_every_configured_non_mutating_command() -> None:
    result = _run_make("-n", "check")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "uv lock --check",
        "uv run --frozen ruff check src tests",
        "uv run --frozen ruff format --check src tests",
        "uv run --frozen mypy --strict src tests",
        "PYTHONPATH=src uv run --frozen python -m alpha_research.architecture_governance",
        "PYTHONPATH=src uv run --frozen python -m alpha_research.ownership_governance",
        "PYTHONPATH=src uv run --frozen python -m alpha_research.change_risk",
        "PYTHONPATH=src uv run --frozen python -m alpha_research.evidence",
        "PYTHONPATH=src uv run --frozen python -m alpha_research.inventory",
        "uv run --frozen bandit -q -c pyproject.toml -r src",
        "PYTHONPATH=src uv run --frozen pytest -q",
        'PYTHONPATH=src uv run --frozen python -c "import alpha_research"',
        "uv build --no-sources",
    ]


def test_format_and_format_check_have_distinct_mutation_behavior() -> None:
    format_result = _run_make("-n", "format")
    check_result = _run_make("-n", "format-check")

    assert format_result.stdout.strip() == "uv run --frozen ruff format src tests"
    assert check_result.stdout.strip() == "uv run --frozen ruff format --check src tests"


def test_root_target_propagates_tool_failure() -> None:
    result = _run_make("UV=false", "smoke")

    assert result.returncode != 0
    assert 'false run --frozen python -c "import alpha_research"' in result.stdout


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
        "make inventory-check",
        "make security",
        "make test",
        "make smoke",
        "make build",
        "make check",
    ):
        assert f"`{command}`" in documentation
