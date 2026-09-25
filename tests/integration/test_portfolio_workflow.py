"""Qualify shared portfolio behavior through an isolated installed execution wheel."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest


class TestPortfolioWorkflow:
    """Run one maintained installed consumer under two authored spot identities."""

    @pytest.mark.integration
    @pytest.mark.parametrize(
        ("venue", "venue_label", "currency"),
        (("okx", "OKX", "USDT"), ("bitfinex", "Bitfinex", "USD")),
    )
    def test_installed_shared_portfolio_attribution_and_recovery(
        self, tmp_path: Path, venue: str, venue_label: str, currency: str
    ) -> None:
        """Check both strategy and physical balances through one installed public path."""
        source = Path(__file__).parent / "consumers/runtime/portfolio_account.py"
        consumer = tmp_path / "portfolio_account.py"
        shutil.copyfile(source, consumer)
        output = tmp_path / "output"
        result = subprocess.run(
            [sys.executable, "-I", str(consumer), "--output", str(output), "--venue", venue],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        assert summary["qualification"] == "local-paper-fixture"
        assert summary["venue_label"] == venue_label
        assert summary["currency"] == currency
        assert summary["active_strategies"] == ["inventory-target", "limit-order"]
        assert summary["budget_rejection"] == "account_limit"
        assert summary["stopped_rejection"] == "instance_stopped"
        assert summary["physical_order_quantity"] == "4"
        assert summary["partial_allocation"] == ["1", "1"]
        assert summary["partial_cash"] == "49799.98"
        assert summary["residual_owner"] == "beta"
        assert summary["settled_cash"] == "49699.97"
        assert summary["settled_position"] == "3"
        assert summary["settled_fees"] == "0.03"
        assert summary["corrected_cash"] == "49699.95"
        assert summary["corrected_fees"] == "0.05"
        assert summary["corrected_alpha_fee"] == "0.02"
        assert summary["corrected_beta_fee"] == "0.03"
        assert summary["crossed_alpha_cash"] == "-0.01"
        assert summary["crossed_beta_cash"] == "-300.02"
        assert summary["crossed_alpha_position"] == "0"
        assert summary["crossed_beta_position"] == "3"
        assert summary["internal_fill_count"] == 2
        assert summary["incompatible_rejection"] == "incompatible_crossing_scope"
        assert summary["crossing_rejection"] == "self_trade_conflict"
        assert summary["conflicting_receipt_rejection"] == "physical_event_break"
        assert summary["malformed_request_rejected"] is True
        assert summary["submission_attempted"] is False
        assert summary["physical_venue_evidence"] is False
