"""Verify installed local operational workflows with independent exact account results."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest


class TestOperationalWorkflow:
    """Exercise one shared operating path under both initial spot fixture identities."""

    @pytest.mark.integration
    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    def test_installed_recovery_preserves_account_and_controls(
        self, tmp_path: Path, venue: str
    ) -> None:
        """Preserve partial fills, pending cancels, recovery blocks and alert outcomes."""
        source = Path(__file__).parent / "consumers/runtime"
        for name in ("account_operations.py", "portfolio_account_facts.py"):
            shutil.copyfile(source / name, tmp_path / name)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(tmp_path / "account_operations.py"),
                "--output",
                str(tmp_path / "output"),
                "--venue",
                venue,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (tmp_path / "output/summary.json").read_bytes(), type=dict[str, object]
        )
        assert summary["qualification"] == "local-paper-fixture"
        assert summary["physical_venue_evidence"] is False
        assert summary["submission_attempted"] is False
        assert summary["cash"] == "49799.98"
        assert summary["position"] == "2"
        assert summary["fees"] == "0.02"
        assert summary["restored_cancel_pending_quantity"] == "2"
        assert summary["duplicate_fill_preserved"] is True
        assert summary["active_strategies"] == ["inventory-target", "limit-order"]
        assert summary["alert_delivery"] == ["delivered", "failed"]
        assert summary["monitoring_preserved_account"] is True
        assert type(summary["dashboard_identity"]) is str
