"""Verify complete stronger typing checks fail directly on diagnostics."""

from __future__ import annotations

# standard library imports
import subprocess
from pathlib import Path

# third party library imports
import pytest

# project library imports
from alpha_research_governance.engineering_standards.python_typing import TypingChecker
from alpha_research_governance.operating_model import OperatingModelError, load_operating_model


def _clean_probe(_checker: TypingChecker) -> str:
    """Return no diagnostics for the isolated command contract test."""
    return ""


class TestTypingChecker:
    """Keep stronger mypy enforcement direct and baseline-free."""

    @pytest.mark.parametrize(
        ("status", "output", "error"),
        [
            (2, "", "crashed"),
            (1, '{"file":"src/sample.py","message":"Expression has type Any"}', ""),
            (1, "", ""),
            (0, "", "warning"),
            (0, "not JSON", ""),
        ],
    )
    def test_probe_fails_closed_on_tool_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
        output: str,
        error: str,
    ) -> None:
        """Reject failed processes, stderr and diagnostics without consulting a baseline."""

        def _complete(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
            """Return a controlled checker result with the requested streams.

            Args:
                command: Checker argument vector retained in the fake process result.
                options: Execution options accepted without running a child process.

            Returns:
                Completed process containing the parametrized status and streams.
            """
            return subprocess.CompletedProcess(command, status, output, error)

        monkeypatch.setattr(
            "alpha_research_governance.engineering_standards.python_typing.subprocess.run",
            _complete,
        )
        with pytest.raises(ValueError):
            TypingChecker(tmp_path)._probe()

    def test_probe_uses_complete_scope_and_stronger_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pass all governed roots and strict stronger flags to the pinned checker."""
        calls: list[list[str]] = []

        def _complete(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
            """Record the command and return a clean process result."""
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr(
            "alpha_research_governance.engineering_standards.python_typing.subprocess.run",
            _complete,
        )

        assert TypingChecker(tmp_path)._probe() == ""
        assert calls == [
            [
                calls[0][0],
                "-m",
                "mypy",
                "--strict",
                "--disallow-any-expr",
                "--disallow-any-decorated",
                "--output=json",
                "src",
                "tests",
                "tools/governance/src",
                "tools/typing/stubs",
            ]
        ]

    def test_run_reports_success_without_reading_an_inventory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Allow a clean check in a root that has no legacy inventory file."""
        monkeypatch.setattr(TypingChecker, "_probe", _clean_probe)

        assert TypingChecker(tmp_path).run() == 0
        assert "native stubs" in capsys.readouterr().out


class TestParsedBoundaries:
    """Reject malformed ownership tables before nested access."""

    @pytest.mark.parametrize(
        "settings",
        ['"not a table"', "{founder_principal = 2026-09-05}", "{founder_principal = 42}"],
    )
    def test_operating_settings_reject_wrong_shapes(self, tmp_path: Path, settings: str) -> None:
        """Keep TOML dates distinct from JSON scalars and reject invalid principals."""
        path = tmp_path / "ownership.toml"
        path.write_text(
            f"schema_version = 2\noperating_model = {settings}\n"
            "domains = []\nrole_assignments = []\n",
            encoding="utf-8",
        )
        with pytest.raises(OperatingModelError):
            load_operating_model(path)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
