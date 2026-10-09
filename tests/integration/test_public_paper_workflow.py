"""Qualify separate installed native-source paper workflows and adverse/no-trade controls."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest


class TestPublicPaperWorkflow:
    """Run one maintained consumer outside the checkout for both supported native venues."""

    @pytest.mark.integration
    @pytest.mark.parametrize("venue", ("okx", "bitfinex"))
    @pytest.mark.parametrize(
        ("dedicated", "no_trade", "adverse"),
        (
            (False, False, "0.50"),
            (True, False, "0.50"),
            (False, True, "0.50"),
            (False, False, "1.00"),
        ),
    )
    def test_native_matching_costs_reconciliation_and_restart(
        self, tmp_path: Path, venue: str, dedicated: bool, no_trade: bool, adverse: str
    ) -> None:
        """Prove losing/no-trade reports, attributed fills and replay with independent goldens."""
        repository = Path(__file__).parents[2]
        consumer = tmp_path / "public_paper.py"
        shutil.copyfile(Path(__file__).parent / "consumers/runtime/public_paper.py", consumer)
        config = tmp_path / "capture.json"
        suffix = "usdt" if venue == "okx" else "usd"
        shutil.copyfile(repository / f"configs/live/{venue}-btc-{suffix}.json", config)
        output = tmp_path / "output"
        command = [
            sys.executable,
            "-I",
            str(consumer),
            "--config",
            str(config),
            "--output",
            str(output),
            "--adverse",
            adverse,
        ]
        if dedicated:
            command.append("--dedicated")
        if no_trade:
            command.append("--no-trade")
        result = subprocess.run(
            command, cwd=tmp_path, capture_output=True, text=True, timeout=90, check=False
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (output / "summary.json").read_bytes(), type=dict[str, object]
        )
        assert summary["source"] == "scripted-native"
        assert summary["venue"] == venue
        assert summary["active_strategies"] == (["fixed"] if dedicated else ["fixed", "liquidity"])
        assert summary["attributed_fills"] == (0 if no_trade else 1 if dedicated else 2)
        assert summary["restart_replay_equal"] is True
        assert summary["independent_reconciliation"] is True
        assert summary["submission_attempted"] is False
        assert summary["gas_applicable"] is False
        assert summary["monitoring_reconciled"] is True
        assert (output / "monitoring-reconciliation.json").is_file()
        pnl = summary["net_pnl"]
        assert isinstance(pnl, str)
        fee = Decimal("0") if no_trade else (Decimal("100") + Decimal(adverse)) * Decimal("0.002")
        if venue == "bitfinex":
            fee = fee.quantize(Decimal("0.01"))
        expected = Decimal(0) if no_trade else -Decimal(2) - 2 * Decimal(adverse) - fee
        assert Decimal(pnl) == expected
        assert (output / "run/manifest.json").is_file()
        assert (output / "run/deliveries.jsonl").is_file()
        assert (output / "run/cost-report.json").is_file()
        assert (output / "run/execution-traces.json").is_file()
        assert (output / "reconciliation.json").is_file()
        retained = (
            "summary.json",
            "report.json",
            "traces.json",
            "reconciliation.json",
            "run/manifest.json",
            "run/deliveries.jsonl",
            "run/cost-report.json",
            "run/execution-traces.json",
        )
        original = {name: (output / name).read_bytes() for name in retained}
        replay = subprocess.run(
            [*command, "--replay"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert replay.returncode == 0, (replay.stdout, replay.stderr)
        verification = msgspec.json.decode(
            (output / "replay-verification.json").read_bytes(), type=dict[str, object]
        )
        assert verification["schema_version"] == "public-paper-replay"
        assert verification["equal"] is True
        assert verification["monitoring_equal"] is True
        assert verification["monitoring_inserted"] == 0
        assert verification["deliveries_replayed"] == len(
            (output / "run/deliveries.jsonl").read_bytes().splitlines()
        )
        assert verification["reference_consumer_sha256"] == summary["reference_consumer"]
        assert verification["before"] == verification["after"]
        before_digests = msgspec.convert(verification["before"], type=dict[str, str], strict=True)
        assert set(before_digests) == {
            "accounts",
            "orders",
            "net_orders",
            "paper_traces",
        }
        assert original == {name: (output / name).read_bytes() for name in retained}
        if not dedicated and not no_trade and adverse == "0.50":
            # A delivery log in the replaced format is refused at its first line.
            deliveries = output / "run/deliveries.jsonl"
            verified = (output / "replay-verification.json").read_bytes()
            deliveries.write_bytes(
                original["run/deliveries.jsonl"].replace(
                    b'"shared-compressed-book-delivery"', b'"shared-eligible-book-delivery"'
                )
            )
            refused = subprocess.run(
                [*command, "--replay"],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            deliveries.write_bytes(original["run/deliveries.jsonl"])
            assert refused.returncode != 0
            assert "unsupported shared book delivery schema" in refused.stderr
            assert (output / "replay-verification.json").read_bytes() == verified

    @pytest.mark.integration
    def test_a_relative_output_directory_receives_the_trace_export(self, tmp_path: Path) -> None:
        """A run given a relative output resolves it before any effect and exports there."""
        repository = Path(__file__).parents[2]
        consumer = tmp_path / "public_paper.py"
        shutil.copyfile(Path(__file__).parent / "consumers/runtime/public_paper.py", consumer)
        config = tmp_path / "capture.json"
        shutil.copyfile(repository / "configs/live/okx-btc-usdt.json", config)
        command = [
            sys.executable,
            "-I",
            str(consumer),
            "--config",
            str(config),
            "--output",
            "relative-output",
        ]
        result = subprocess.run(
            command, cwd=tmp_path, capture_output=True, text=True, timeout=90, check=False
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        exported = tmp_path / "relative-output/run/execution-traces.json"
        assert exported.read_bytes().startswith(b"[{")
        assert (tmp_path / "relative-output/run/cost-report.json").is_file()
