"""Exercise explicit artifact command parsing and the whole-research release restriction."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.artifact_supply_chain import ArtifactArguments, main

REPOSITORY_ROOT = Path(__file__).parents[2]


class TestArtifactCommands:
    """Keep unsupported invocations and unresolved research releases fail-closed."""

    @pytest.mark.parametrize("arguments", ((), ("unknown",), ("release-check", "extra")))
    def test_unknown_or_malformed_commands_fail(
        self, arguments: tuple[str, ...], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reject unsupported command shapes without entering a release path."""
        assert main(arguments) == 2
        assert "usage: alpha-governance-artifacts" in capsys.readouterr().err

    def test_whole_research_graph_has_no_native_admission_block(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With no wheel-only package admitted, only the operating profile gate remains."""
        monkeypatch.chdir(REPOSITORY_ROOT)
        assert main(["release-check"]) == 1
        error = capsys.readouterr().err
        assert "select an admitted operating build profile" in error
        assert "unresolved native dependency admission" not in error

    def test_missing_repository_cannot_write_artifacts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reject absent admission inputs before any build or publication."""
        monkeypatch.chdir(tmp_path)
        assert main(["release-check"]) == 1
        assert "dependency-admission.toml" in capsys.readouterr().err
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize(
        "arguments",
        (
            ("install",),
            ("verify", "--policy", "absent", "--policy", "other"),
            ("build", "--unknown", "path"),
            ("run", "--target", "absent", "--policy", "absent"),
        ),
    )
    def test_new_commands_require_explicit_inputs(
        self, arguments: tuple[str, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A partial administrative command never supplies implicit trust or target paths."""
        monkeypatch.chdir(tmp_path)
        assert main(arguments) == 1
        assert list(tmp_path.iterdir()) == []

    def test_explicit_options_preserve_paths(self, tmp_path: Path) -> None:
        """Parse exact caller paths without interpreting them as shell syntax."""
        path = tmp_path / "has spaces;literal"
        assert ArtifactArguments.options(["--target", str(path)], {"--target"}, set()) == {
            "--target": path
        }
