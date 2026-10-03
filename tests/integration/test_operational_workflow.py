"""Verify installed local operational workflows with independent exact account results."""

from __future__ import annotations

# standard library imports
import hashlib
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
                "-E",
                "-s",
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
        assert type(summary["installed_implementation"]) is str
        assert Path(str(summary["installed_interpreter"])).is_absolute()
        assert "/site-packages/" in str(summary["installed_paper_monitoring_source"])
        assert (
            summary["reference_consumer_sha256"]
            == hashlib.sha256((tmp_path / "output/reference-consumer.py").read_bytes()).hexdigest()
        )
        alerts = msgspec.convert(summary["dashboard_alerts"], type=dict[str, object], strict=True)
        assert alerts["socket_send_status"] == ["delivered", "failed", "delivered"]
        assert alerts["socket_accepted"] == [True, False, True]
        assert alerts["receiver_observed"] == [True, False, True]
        assert alerts["human_acknowledged"] == "not_tested"
        assert alerts["failed_attempt_replayed"] is False
        identities = msgspec.convert(alerts["delivery_identities"], type=list[str], strict=True)
        assert len(set(identities)) == 3
        assert (tmp_path / "output/dashboard-alert-evidence.json").is_file()
        for label in ("socket-accepted", "receiver-unavailable", "receiver-restored"):
            assert (tmp_path / "output" / f"dashboard-{label}/manifest.json").is_file()
