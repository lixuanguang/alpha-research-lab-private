"""Contract tests for the runtime and governance-tool distributions."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).parents[2]
EXPECTED_RUNTIME_REQUIREMENTS: set[str] = set()
EXPECTED_TOOL_REQUIREMENTS = {"pydantic==2.13.5"}
EXPECTED_DEV_REQUIREMENTS = {
    "alpha-research-governance",
    "bandit[toml]==1.9.4",
    "hatchling==1.32.0",
    "mypy==2.3.1",
    "pre-commit==4.6.2",
    "pre-commit-hooks==6.0.0",
    "pytest==9.1.1",
    "pytest-cov==7.1.0",
    "ruff==0.16.5",
}


def _load_pyproject(relative_path: str = "pyproject.toml") -> dict[str, object]:
    parsed_document: object = tomllib.loads(
        (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
    )
    assert isinstance(parsed_document, dict)
    return cast(dict[str, object], parsed_document)


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
    tool_distribution = importlib.metadata.distribution("alpha-research-governance")

    assert distribution.metadata["Name"] == "alpha-research-lab"
    assert distribution.version == "0.1.0"
    assert distribution.metadata["Requires-Python"] == "==3.12.*"
    assert set(distribution.requires or ()) == EXPECTED_RUNTIME_REQUIREMENTS
    assert tool_distribution.version == "0.1.0"
    assert set(tool_distribution.requires or ()) == EXPECTED_TOOL_REQUIREMENTS


def test_project_has_only_declared_and_exact_direct_dependencies() -> None:
    configuration = _load_pyproject()
    tool_configuration = _load_pyproject("tools/governance/pyproject.toml")
    project = _require_table(configuration, "project")
    tool_project = _require_table(tool_configuration, "project")
    dependency_groups = _require_table(configuration, "dependency-groups")

    assert set(_require_string_list(project, "dependencies")) == EXPECTED_RUNTIME_REQUIREMENTS
    assert set(_require_string_list(tool_project, "dependencies")) == EXPECTED_TOOL_REQUIREMENTS
    assert set(_require_string_list(dependency_groups, "dev")) == EXPECTED_DEV_REQUIREMENTS


def test_governance_path_target_and_owned_commands_are_explicit() -> None:
    configuration = _load_pyproject()
    tool_configuration = _load_pyproject("tools/governance/pyproject.toml")
    uv = _require_table(_require_table(configuration, "tool"), "uv")
    sources = _require_table(uv, "sources")
    scripts = _require_table(_require_table(tool_configuration, "project"), "scripts")

    assert sources == {
        "alpha-research-governance": {
            "editable": False,
            "path": "tools/governance",
        }
    }
    assert set(scripts) == {
        "alpha-governance-architecture",
        "alpha-governance-change-risk",
        "alpha-governance-evidence",
        "alpha-governance-inventory",
        "alpha-governance-ownership",
        "alpha-governance-program",
        "alpha-governance-security",
        "alpha-governance-topology",
    }


def test_runtime_source_contains_only_core_and_compatibility_facades() -> None:
    implementation_names = {
        "approvals.py",
        "classification.py",
        "constraints.py",
        "manifest.py",
        "models.py",
        "mr.py",
        "package.py",
        "policy.py",
    }
    runtime_paths = tuple((REPOSITORY_ROOT / "src/alpha_research").rglob("*.py"))
    tool_paths = {
        path.name
        for path in (REPOSITORY_ROOT / "tools/governance/src/alpha_research_governance").rglob(
            "*.py"
        )
    }

    assert {path.name for path in runtime_paths}.isdisjoint(implementation_names)
    assert implementation_names <= tool_paths
    for path in runtime_paths:
        source = path.read_text(encoding="utf-8")
        assert "def " not in source
        assert "class " not in source


def test_build_backend_and_python_are_exactly_pinned() -> None:
    configuration = _load_pyproject()
    tool_configuration = _load_pyproject("tools/governance/pyproject.toml")
    build_system = _require_table(configuration, "build-system")
    tool_build_system = _require_table(tool_configuration, "build-system")
    project = _require_table(configuration, "project")
    tool = _require_table(configuration, "tool")
    uv = _require_table(tool, "uv")

    assert _require_string_list(build_system, "requires") == ["hatchling==1.32.0"]
    assert _require_string_list(tool_build_system, "requires") == ["hatchling==1.32.0"]
    assert project["requires-python"] == "==3.12.*"
    assert uv["required-version"] == "==0.12.7"
    assert (REPOSITORY_ROOT / ".python-version").read_text(encoding="utf-8") == "3.12.14\n"


def test_uv_lock_contains_project_and_exact_package_versions() -> None:
    parsed_lock_document: object = tomllib.loads(
        (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")
    )
    assert isinstance(parsed_lock_document, dict)
    lock = cast(dict[str, object], parsed_lock_document)
    packages_value = lock.get("package")
    assert isinstance(packages_value, list)
    packages = cast(list[object], packages_value)

    locked_names: set[str] = set()
    project_is_locked = False
    tool_is_locked = False
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
        tool_is_locked = tool_is_locked or (
            name == "alpha-research-governance"
            and package.get("source") == {"directory": "tools/governance"}
        )

    direct_names = {
        requirement.partition("[")[0].partition("==")[0].replace("_", "-")
        for requirement in EXPECTED_RUNTIME_REQUIREMENTS | EXPECTED_DEV_REQUIREMENTS
    }
    assert project_is_locked
    assert tool_is_locked
    assert direct_names <= locked_names
