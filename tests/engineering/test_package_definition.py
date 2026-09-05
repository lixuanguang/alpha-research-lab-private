"""Contract tests for the runtime and governance-tool distributions."""

from __future__ import annotations

# standard library imports
import importlib.metadata
import tomllib
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).parents[2]
EXPECTED_RUNTIME_REQUIREMENTS = {
    "alpha-research-governance==0.1.0",
    "exchange-calendars==4.13.2",
    "pydantic==2.13.5",
    "quantlib==1.43",
}
EXPECTED_TOOL_REQUIREMENTS = {"pydantic==2.13.5", "typer==0.27.2"}


def _load_pyproject(relative_path: str = "pyproject.toml") -> dict[str, object]:
    """Load a repository-relative TOML project file for metadata assertions.

    Args:
        relative_path: Path from the repository root, defaulting to the runtime project file.

    Returns:
        The parsed top-level TOML table.

    Raises:
        OSError: The project file cannot be read.
        tomllib.TOMLDecodeError: The file is not valid TOML.
        AssertionError: The parsed document is not a top-level table.
    """
    parsed_document: object = tomllib.loads(
        (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
    )
    assert isinstance(parsed_document, dict)
    return cast(dict[str, object], parsed_document)


def _require_table(container: dict[str, object], key: str) -> dict[str, object]:
    """Return one required TOML table from a parsed mapping.

    Args:
        container: Parsed TOML mapping containing the requested value.
        key: Table key that must resolve to a mapping.

    Returns:
        The nested TOML table associated with ``key``.

    Raises:
        AssertionError: The key is absent or its value is not a TOML table.
    """
    value = container.get(key)
    assert isinstance(value, dict), f"{key} must be a TOML table"
    return cast(dict[str, object], value)


def test_installed_distribution_exposes_expected_metadata() -> None:
    """Verify installed runtime and governance distributions expose pinned metadata."""
    distribution = importlib.metadata.distribution("alpha-research-lab")
    tool_distribution = importlib.metadata.distribution("alpha-research-governance")

    assert distribution.metadata["Name"] == "alpha-research-lab"
    assert distribution.version == "0.1.0"
    assert distribution.metadata["Requires-Python"] == "==3.12.*"
    assert set(distribution.requires or ()) == EXPECTED_RUNTIME_REQUIREMENTS
    assert tool_distribution.version == "0.1.0"
    assert set(tool_distribution.requires or ()) == EXPECTED_TOOL_REQUIREMENTS


def test_governance_path_target_and_owned_commands_are_explicit() -> None:
    """Verify project TOML declares the non-editable governance path and owned commands."""
    configuration = _load_pyproject()
    tool_configuration = _load_pyproject("tools/governance/pyproject.toml")
    uv = _require_table(_require_table(configuration, "tool"), "uv")
    sources = _require_table(uv, "sources")
    scripts = _require_table(_require_table(tool_configuration, "project"), "scripts")
    compatibility_scripts = _require_table(configuration, "project")["scripts"]

    assert sources == {
        "alpha-research-governance": {
            "editable": False,
            "path": "tools/governance",
        }
    }
    assert uv["constraint-dependencies"] == ["numpy==2.4.6"]
    assert set(scripts) == {
        "alpha-governance-architecture",
        "alpha-governance-artifacts",
        "alpha-governance-change-risk",
        "alpha-governance-ci",
        "alpha-governance-dependencies",
        "alpha-governance-engineering-standards",
        "alpha-governance-evidence",
        "alpha-governance-inventory",
        "alpha-governance-ownership",
        "alpha-governance-program",
        "alpha-governance-remote-execution",
        "alpha-governance-security",
        "alpha-governance-topology",
    }
    assert compatibility_scripts == {"alpha-research-ci": "alpha_research.ci_policy:main"}
