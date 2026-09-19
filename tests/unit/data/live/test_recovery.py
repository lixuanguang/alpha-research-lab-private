"""Verify the installed session lifecycle outside the checkout with synthetic endpoints."""

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest

_ROOT = Path(__file__).parents[4]


class TestRecovery:
    """Retain the notebook's recovery and exact duplicate failures as regression coverage."""

    @pytest.mark.integration
    def test_installed_recovery(self, tmp_path: Path) -> None:
        """Bound pending-snapshot recovery, retain raw duplicates and reject stale responses."""
        for source in (
            "configs/live/coinbase-btc-usd.json",
            "tests/fixtures/market_data/coinbase/coinbase-schema.json",
            "tests/fixtures/market_data/coinbase/coinbase-snapshot.json",
            "tests/integration/consumers/capture/recovery_consumer.py",
        ):
            shutil.copyfile(_ROOT / source, tmp_path / Path(source).name)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(tmp_path / "recovery_consumer.py"),
                str(tmp_path),
                str(tmp_path / "run"),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (tmp_path / "run/result.json").read_bytes(), type=dict[str, object]
        )
        assert summary["duplicate_and_stale"] == {
            "duplicate_receipt_ns": [5, 6],
            "economic_matches": 1,
            "remaining_size": "0.200000000000000001",
            "conflicting_duplicate": "invalid_frame",
            "stale_snapshots": 2,
            "new_epoch_synchronized": False,
        }
