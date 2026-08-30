"""Contract tests for the initial Python package and locked tool environment."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).parents[2]
EXPECTED_RUNTIME_REQUIREMENTS = {"pydantic==2.13.5"}
EXPECTED_DEV_REQUIREMENTS = {
    "bandit[toml]==1.9.4",
    "hatchling==1.32.0",
    "mypy==2.3.1",
    "pre-commit==4.6.2",
    "pre-commit-hooks==6.0.0",
    "pytest==9.1.1",
    "pytest-cov==7.1.0",
    "ruff==0.16.5",
}


def _load_pyproject() -> dict[str, object]:
    parsed: object = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return cast(dict[str, object], parsed)


def _require_table(container: dict[str, object], key: str) -> dict[str, object]:
    value = container.get(key)
    assert isinstance(value, dict), f"{key} must be a TOML table"
    return cast(dict[str, object], value)


def _require_string_list(container: dict[str, object], key: str) -> list[str]:
    value = container.get(key)
    assert isinstance(value, list), f"{key} must be a TOML array"
    assert all(isinstance(item, str) for item in value), f"{key} must contain only strings"
    return cast(list[str], value)


def test_installed_distribution_exposes_expected_metadata() -> None:
    distribution = importlib.metadata.distribution("alpha-research-lab")

    assert distribution.metadata["Name"] == "alpha-research-lab"
    assert distribution.version == "0.1.0"
    assert distribution.metadata["Requires-Python"] == "==3.12.*"
    assert set(distribution.requires or ()) == EXPECTED_RUNTIME_REQUIREMENTS


def test_project_has_only_declared_and_exact_direct_dependencies() -> None:
    configuration = _load_pyproject()
    project = _require_table(configuration, "project")
    dependency_groups = _require_table(configuration, "dependency-groups")

    assert set(_require_string_list(project, "dependencies")) == EXPECTED_RUNTIME_REQUIREMENTS
    assert set(_require_string_list(dependency_groups, "dev")) == EXPECTED_DEV_REQUIREMENTS


def test_build_backend_and_python_are_exactly_pinned() -> None:
    configuration = _load_pyproject()
    build_system = _require_table(configuration, "build-system")
    project = _require_table(configuration, "project")
    tool = _require_table(configuration, "tool")
    uv = _require_table(tool, "uv")

    assert _require_string_list(build_system, "requires") == ["hatchling==1.32.0"]
    assert project["requires-python"] == "==3.12.*"
    assert uv["required-version"] == "==0.12.7"
    assert (REPOSITORY_ROOT / ".python-version").read_text(encoding="utf-8") == "3.12.14\n"


def test_uv_lock_contains_project_and_exact_package_versions() -> None:
    parsed: object = tomllib.loads((REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    lock = cast(dict[str, object], parsed)
    packages_value = lock.get("package")
    assert isinstance(packages_value, list)
    packages = cast(list[object], packages_value)

    locked_names: set[str] = set()
    project_is_locked = False
    for package_value in packages:
        assert isinstance(package_value, dict)
        package = cast(dict[str, object], package_value)
        name = package.get("name")
        version = package.get("version")
        assert isinstance(name, str)
        assert isinstance(version, str) and version
        locked_names.add(name)
        project_is_locked = project_is_locked or (
            name == "alpha-research-lab" and package.get("source") == {"editable": "."}
        )

    direct_names = {
        requirement.partition("[")[0].partition("==")[0].replace("_", "-")
        for requirement in EXPECTED_RUNTIME_REQUIREMENTS | EXPECTED_DEV_REQUIREMENTS
    }
    assert project_is_locked
    assert direct_names <= locked_names


def test_repository_automation_targets_only_the_current_uv_package() -> None:
    continuous_integration = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    pre_commit = (REPOSITORY_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    automation = continuous_integration + pre_commit

    stale_fragments = (
        "alpha_core",
        "apps/",
        "duckdb",
        "libs/core",
        "research-smoke",
        'python-version: ["3.11"]',
        ".[dev,research]",
    )
    assert all(fragment not in automation for fragment in stale_fragments)
    assert "uv sync --frozen" in continuous_integration
    assert "uv build --no-sources" in continuous_integration
    assert 'version: "0.12.7"' in continuous_integration
    assert "repo: local" in pre_commit
    assert "uv lock --check" in pre_commit
