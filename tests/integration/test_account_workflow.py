"""Qualify the shared account application from an installed, isolated interpreter."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest


class TestAccountWorkflow:
    """Run the maintained account consumer without checkout imports."""

    @pytest.mark.integration
    def test_installed_shared_account_admission_and_recovery(self, tmp_path: Path) -> None:
        """Check exact paper economics and hard controls through installed APIs and CLI."""
        source = Path(__file__).parent / "consumers/runtime/shared_account.py"
        consumer = tmp_path / "shared_account.py"
        shutil.copyfile(source, consumer)
        result = subprocess.run(
            [sys.executable, "-I", str(consumer), "--output", str(tmp_path / "output")],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (tmp_path / "output/summary.json").read_bytes(), type=dict[str, object]
        )
        assert summary["qualification"] == "local-paper-fixture"
        assert summary["competing_admission"] == "account_limit"
        assert summary["partial_cash"] == "19799.80"
        assert summary["final_cash"] == "11900.50"
        assert summary["final_position"] == "80"
        assert summary["submission_attempted"] is False
        assert summary["operator_block"] == "operator-stop"
