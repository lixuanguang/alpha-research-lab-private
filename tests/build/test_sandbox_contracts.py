"""Contract tests for sandbox runfiles and host-environment diagnostics."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest
from sandbox_test import SandboxInputCheck


class TestSandboxInputCheck:
    """Verify selected leak diagnostics and repeat-call behavior."""

    def test_visible_runfile_is_reported_and_later_clean_state_passes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Report a visible undeclared file without retaining stale state."""
        environment = {
            "TEST_SRCDIR": str(tmp_path),
            "TEST_WORKSPACE": "workspace",
        }
        runfiles = tmp_path / "workspace"
        leaked_path = runfiles / "docs" / "README.md"
        leaked_path.parent.mkdir(parents=True)
        leaked_path.write_text("undeclared", encoding="utf-8")
        checker = SandboxInputCheck.from_environment(environment)

        assert checker.run() == 1
        assert "undeclared inputs leaked into the sandbox" in capsys.readouterr().err

        leaked_path.unlink()
        assert checker.run() == 0
        assert capsys.readouterr().err == ""

    def test_host_secret_sentinel_reports_environment_diagnostic(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Report the sentinel even when no undeclared path is visible."""
        environment = {
            "TEST_SRCDIR": str(tmp_path),
            "TEST_WORKSPACE": "workspace",
            "UNDECLARED_HOST_SECRET": "present",
        }
        checker = SandboxInputCheck.from_environment(environment)

        assert checker.run() == 1
        assert capsys.readouterr().err == ("undeclared host environment leaked into the sandbox\n")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
