"""Verify the paper services operating profile, its local closure and installed commands."""

from __future__ import annotations

# standard library imports
from pathlib import Path

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
