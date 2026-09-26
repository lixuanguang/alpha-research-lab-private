"""Run native scripted test-venue execution from an isolated installed consumer."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
import msgspec
import pytest


@pytest.mark.integration
class TestVenueWorkflow:
    """Keep both initial spot venues on the same installed account contract."""

    @pytest.mark.parametrize("venue", ["okx", "bitfinex"])
    def test_native_protocol_to_exact_shared_account(
        self, tmp_path: Path, venue: Literal["okx", "bitfinex"]
    ) -> None:
        """Both protocol adapters reconcile one physical and two child positions."""
        consumer = Path(__file__).resolve().parent / "consumers" / "runtime" / "venue_execution.py"
        copied_consumer = tmp_path / "venue_execution.py"
        shutil.copy2(consumer, copied_consumer)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(copied_consumer),
                "--venue",
                venue,
                "--state",
                str(tmp_path / venue),
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        facts = msgspec.json.decode(result.stdout.encode(), type=dict[str, object])
        assert facts["venue"] == venue
        assert facts["qualification"] == "scripted-native-http"
        assert Decimal(str(facts["cash"])) == Decimal("899.90")
        assert Decimal(str(facts["base_position"])) == Decimal("1")
        assert Decimal(str(facts["fee"])) == Decimal("0.10")
        assert facts["child_positions"] == ["0.500000000000000000", "0.500000000000000000"]
        assert facts["child_fees"] == ["0.050000000000000000", "0.050000000000000000"]
        assert facts["terminal_status"] == "cancelled"
        assert facts["submits"] == 1
        assert facts["cancels"] == 1
