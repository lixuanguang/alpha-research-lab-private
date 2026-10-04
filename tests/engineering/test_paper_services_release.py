"""Verify the paper services operating profile, its local closure and installed commands."""

from __future__ import annotations

# standard library imports
import ast
import tomllib
from pathlib import Path
from typing import cast

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain.installation import LocalInstallation
from alpha_research_governance.artifact_supply_chain.records import ReleaseRuntime
from alpha_research_governance.dependency_admission.selected_closure import (
    SelectedClosureAdmission,
)


class TestPaperServicesRelease:
    """Keep paper services' runtime, local projects and commands explicitly bounded."""

    @staticmethod
    def _runtime(**changes: str) -> ReleaseRuntime:
        """Declare one paper services runtime, optionally with changed fields."""
        values = {
            "python_version": "3.14.7",
            "platform": "darwin_arm64",
            "contract_version": "1",
            "application": "paper-services",
            "mode": "paper",
            "config_schema": "paper-services",
            "state_schema": "none",
        } | changes
        return ReleaseRuntime.model_validate(values)

    def test_runtime_requires_paper_mode_service_schema_and_no_state(self) -> None:
        """Paper services run paper or shadow mode, with their own schema and no state."""
        assert self._runtime(mode="shadow").application == "paper-services"
        for changes in (
            {"mode": "collection"},
            {"state_schema": "account-journal"},
            {"config_schema": "account-runtime"},
        ):
            with pytest.raises(ValueError):
                self._runtime(**changes)
        with pytest.raises(ValueError, match="paper services configuration"):
            self._runtime(application="execution", config_schema="paper-services")

    def test_local_closure_admits_platform_projects_and_bounded_extensions_only(self) -> None:
        """Only paper services may select extensions, each from extensions/<name>."""
        root = "alpha-research-paper-services"
        local = SelectedClosureAdmission._local_source
        assert local(root, root, {"editable": "."})
        assert local(root, "alpha-research-execution", {"directory": "../execution"})
        assert local(root, "alpha-research-contracts", {"directory": "../contracts"})
        assert local(root, "engineering-candidates", {"directory": "../../extensions/engineering"})
        assert not local(root, "engineering-candidates", {"directory": "../../tools/escape"})
        assert not local(root, "alpha-research-lab", {"directory": "../../extensions/lab"})
        assert not local(
            "alpha-research-execution",
            "engineering-candidates",
            {"directory": "../../extensions/x"},
        )
        assert not local(
            "alpha-research-collector", "alpha-research-execution", {"directory": "../execution"}
        )

    def test_installed_commands_bind_signed_configuration_and_candidates(
        self, tmp_path: Path
    ) -> None:
        """Deployment and its check receive signed bytes; control receives nothing signed."""
        runtime = self._runtime()
        config, candidates = tmp_path / "config.json", tmp_path / "candidates"
        bind = LocalInstallation._bound_arguments
        assert bind(
            runtime,
            ("deployment", "--owners", "/owners.json"),
            config,
            tmp_path / "journal",
            release_identity="a" * 64,
            candidates=candidates,
        ) == [
            "deployment",
            "--owners",
            "/owners.json",
            "--config",
            str(config),
            "--candidates",
            str(candidates),
        ]
        assert bind(
            runtime,
            ("deployment-control", "--socket", "/s.sock"),
            config,
            tmp_path / "journal",
            release_identity="a" * 64,
            candidates=candidates,
        ) == ["deployment-control", "--socket", "/s.sock"]
        for arguments in (
            ("deployment", "--config", "/other.json"),
            ("deployment", "--candidates=/other"),
            ("account",),
        ):
            with pytest.raises(ValueError):
                bind(
                    runtime,
                    arguments,
                    config,
                    tmp_path / "journal",
                    release_identity="a" * 64,
                    candidates=candidates,
                )

    def test_outer_bound_follows_the_signed_supervisor_duration(self, tmp_path: Path) -> None:
        """An installed supervisor run is bounded by its declared duration plus 60 seconds."""
        config = tmp_path / "config.json"
        config.write_text('{"schema_version":"paper-services","duration_seconds":2880}')
        assert LocalInstallation._outer_seconds(self._runtime(), config) == 2940
        config.write_text('{"schema_version":"paper-services","duration_seconds":0}')
        with pytest.raises(ValueError, match="finite declared bound"):
            LocalInstallation._outer_seconds(self._runtime(), config)


class TestPaperServicesRuntimeModules:
    """Ship every runtime module that the shipped supervisor code imports."""

    _WHEELS = ("contracts", "execution", "paper-services")

    @classmethod
    def _shipped(cls) -> set[str]:
        """Return repository source files the three operating wheels include."""
        shipped: set[str] = set()
        for wheel in cls._WHEELS:
            project = Path("packages") / wheel
            table: object = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
            for key in ("tool", "hatch", "build", "targets", "wheel"):
                table = cls._table(table, key)
            includes = cls._table(table, "force-include")
            for source in includes:
                path = (project / source).resolve().relative_to(Path.cwd().resolve())
                if path.is_dir():
                    shipped.update(item.as_posix() for item in path.rglob("*.py"))
                else:
                    shipped.add(path.as_posix())
        return shipped

    @staticmethod
    def _table(value: object, key: str) -> dict[str, object]:
        """Return one nested TOML table as a typed mapping."""
        if not isinstance(value, dict):
            raise TypeError("expected a TOML table")
        child = cast(dict[str, object], value).get(key)
        if not isinstance(child, dict):
            raise TypeError(f"expected TOML table {key}")
        return cast(dict[str, object], child)

    @staticmethod
    def _exported_modules() -> dict[str, str]:
        """Map each runtime export to the module that defines it."""
        tree = ast.parse(Path("src/runtime/__init__.py").read_text(encoding="utf-8"))
        names: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("runtime."):
                for alias in node.names:
                    names[alias.name] = str(node.module)
        return names

    def test_every_runtime_import_of_shipped_code_is_shipped(self) -> None:
        """A module reached only through a lazy runtime export still has to be in a wheel."""
        shipped = self._shipped()
        exported = self._exported_modules()
        missing: set[str] = set()
        for source in sorted(shipped):
            # The runtime initializer's exports are type-only or lazy, not imports.
            if (
                not source.startswith(("src/runtime/", "src/applications/execute/"))
                or source == "src/runtime/__init__.py"
            ):
                continue
            tree = ast.parse(Path(source).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level:
                    continue
                modules: set[str] = set()
                if node.module == "runtime":
                    modules = {
                        exported[alias.name] for alias in node.names if alias.name in exported
                    }
                elif (node.module or "").startswith("runtime."):
                    modules = {str(node.module)}
                missing.update(
                    f"{source}: {module}"
                    for module in modules
                    if "src/" + module.replace(".", "/") + ".py" not in shipped
                )
        assert not missing, sorted(missing)
