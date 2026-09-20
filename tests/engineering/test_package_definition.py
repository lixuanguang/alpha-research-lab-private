"""Contract tests for the runtime and governance-tool distributions."""

from __future__ import annotations

# standard library imports
import importlib.metadata
import subprocess
import sys
import tomllib
from pathlib import Path

# third party library imports
from pydantic import TypeAdapter

REPOSITORY_ROOT = Path(__file__).parents[2]


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
    return TypeAdapter(dict[str, object]).validate_python(parsed_document)


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
    return TypeAdapter(dict[str, object]).validate_python(value)


class TestPackageDefinitionContracts:
    """Verify installed metadata and the explicit wheel-smoke entrypoint."""

    def test_installed_distribution_exposes_expected_metadata(self) -> None:
        """Verify installed metadata matches each distribution's current project definition."""
        runtime_project = _require_table(_load_pyproject(), "project")
        tool_project = _require_table(_load_pyproject("tools/governance/pyproject.toml"), "project")
        distribution = importlib.metadata.distribution("alpha-research-lab")
        tool_distribution = importlib.metadata.distribution("alpha-research-governance")

        assert distribution.metadata["Name"] == "alpha-research-lab"
        assert distribution.version == runtime_project["version"]
        assert distribution.metadata["Requires-Python"] == runtime_project["requires-python"]
        runtime_dependencies = TypeAdapter(list[str]).validate_python(
            runtime_project["dependencies"]
        )
        assert {requirement.lower() for requirement in distribution.requires or ()} == {
            requirement.lower() for requirement in runtime_dependencies
        }
        assert tool_distribution.metadata["Name"] == "alpha-research-governance"
        assert tool_distribution.version == tool_project["version"]
        assert tool_distribution.metadata["Requires-Python"] == tool_project["requires-python"]
        tool_dependencies = TypeAdapter(list[str]).validate_python(tool_project["dependencies"])
        assert {requirement.lower() for requirement in tool_distribution.requires or ()} == {
            requirement.lower() for requirement in tool_dependencies
        }

    def test_governance_is_available_only_to_development_tools(self) -> None:
        """Keep governance outside runtime while exposing the maintained data commands."""
        configuration = _load_pyproject()
        tool_configuration = _load_pyproject("tools/governance/pyproject.toml")
        uv = _require_table(_require_table(configuration, "tool"), "uv")
        sources = _require_table(uv, "sources")
        scripts = _require_table(_require_table(tool_configuration, "project"), "scripts")
        runtime_project = _require_table(configuration, "project")
        runtime_dependencies = TypeAdapter(list[str]).validate_python(
            runtime_project["dependencies"]
        )
        development_dependencies = TypeAdapter(list[str]).validate_python(
            _require_table(configuration, "dependency-groups")["dev"]
        )

        governance_source = _require_table(sources, "alpha-research-governance")
        assert governance_source["path"] == "tools/governance"
        assert governance_source["editable"] is False
        constraints = TypeAdapter(list[str]).validate_python(uv["constraint-dependencies"])
        assert "numpy==2.4.6" in constraints
        assert scripts["alpha-governance-ci"] == "alpha_research_governance.ci_policy:main"
        assert not any("governance" in requirement for requirement in runtime_dependencies)
        assert "alpha-research-governance==0.1.0" in development_dependencies
        runtime_scripts = _require_table(runtime_project, "scripts")
        assert runtime_scripts == {
            "alpha-backtest": "applications.backtest:main",
            "alpha-acquire": "applications.acquire:main",
            "alpha-collect": "applications.collect:main",
            "alpha-dataset": "applications.publish_dataset:main",
            "alpha-inspect-fixture": "applications.inspect_fixture:main",
        }
        installed_commands = {
            entry.name
            for entry in importlib.metadata.distribution("alpha-research-lab").entry_points
        }
        assert installed_commands == {
            "alpha-backtest",
            "alpha-acquire",
            "alpha-collect",
            "alpha-dataset",
            "alpha-inspect-fixture",
        }

    def test_wheel_smoke_is_the_build_install_boundary(self) -> None:
        """Require the root interface to invoke the isolated installed-wheel smoke."""
        makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
        smoke = (
            REPOSITORY_ROOT
            / "tools"
            / "governance"
            / "src"
            / "alpha_research_governance"
            / "wheel_smoke.py"
        ).read_text(encoding="utf-8")

        assert "wheel-smoke:" in makefile
        assert "python -m alpha_research_governance.wheel_smoke" in makefile
        assert "wheel_layout.py" in smoke
        assert "--no-dev" in smoke
        assert "alpha_research_lab-" in smoke
        assert "--require-hashes" in smoke
        assert '"-I"' in smoke
        assert "PYTHONPATH" in smoke

    def test_installed_development_cli_rejects_an_empty_scan_scope(self) -> None:
        """Exercise the installed tool boundary and preserve its nonzero failure status."""
        command = Path(sys.executable).parent / "alpha-governance-ci"
        result = subprocess.run(
            [str(command), "scan-secrets"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1
        assert "scan-secrets accepts" in result.stderr
