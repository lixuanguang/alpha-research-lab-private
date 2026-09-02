"""Contract tests for the repository root command interface."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
GOVERNANCE_COMMANDS = (
    "alpha-governance-architecture",
    "alpha-governance-change-risk",
    "alpha-governance-ci",
    "alpha-governance-engineering-standards",
    "alpha-governance-evidence",
    "alpha-governance-inventory",
    "alpha-governance-program",
    "alpha-governance-remote-execution",
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


def test_uv_backend_preserves_the_legacy_rollback_path() -> None:
    rollback_dry_run = _run_make("-n", "BUILD_BACKEND=uv", "check")

    assert rollback_dry_run.returncode == 0, rollback_dry_run.stderr
    assert "bazel " not in rollback_dry_run.stdout
    assert rollback_dry_run.stdout.splitlines() == [
        "uv lock --check",
        "uv run --frozen ruff check src tests tools/governance/src",
        "uv run --frozen ruff format --check src tests tools/governance/src",
        "uv run --frozen mypy --strict src tests tools/governance/src",
        "uv run --frozen alpha-governance-engineering-standards",
        "uv run --frozen alpha-governance-architecture",
        "uv run --frozen alpha-governance-ownership",
        "uv run --frozen alpha-governance-change-risk",
        "uv run --frozen alpha-governance-evidence",
        "uv run --frozen alpha-governance-topology",
        "uv run --frozen alpha-governance-inventory",
        "uv run --frozen alpha-governance-security",
        "uv run --frozen alpha-governance-program",
        "uv run --frozen alpha-governance-ci",
        "uv run --frozen alpha-governance-remote-execution",
        "uv run --frozen bandit -q -c pyproject.toml -r src tools/governance/src",
        "uv run --frozen --no-editable pytest -q",
        "uv run --frozen --no-editable pytest -q -m integration",
        'uv run --frozen --no-editable python -c "import alpha_research"',
        "uv build --no-sources",
    ]


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
    assert "make ci-full" in continuous_integration
    assert "make ci-fast" in continuous_integration
    assert "make remote-build" in continuous_integration
    assert "make remote-test" in continuous_integration
    assert "github.event_name == 'push'" in continuous_integration

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
    assert "rollback-check" in makefile
    assert 'version: "0.12.7"' in continuous_integration
    assert "repo: local" in pre_commit
    assert "uv lock --check" in pre_commit
    for make_target in (
        "ci-policy-check",
        "ci-secrets-check",
        "ci-schema-check",
        "engineering-standards-check",
        "inventory-check",
        "program-governance-check",
        "security-controls-check",
    ):
        assert f"make {make_target}" in documentation


def test_affected_and_authoritative_full_ci_root_interfaces_are_explicit() -> None:
    fast = _run_make("-n", "ci-fast", "CI_BASE_REF=HEAD", "CI_HEAD_REF=HEAD")
    full = _run_make("-n", "ci-full", "CI_BASE_REF=HEAD")

    assert fast.returncode == 0, fast.stderr
    assert "alpha-governance-ci fast" in fast.stdout
    assert "--base-ref HEAD --head-ref HEAD" in fast.stdout
    assert full.returncode == 0, full.stderr
    assert "alpha-governance-ci full" in full.stdout
    assert "--base-ref HEAD" in full.stdout
