"""Verify installed saved-book workflow entrypoints in a fresh process outside the checkout."""

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import pytest


class TestInstalledBookBacktest:
    """Exercise actual native archives, configuration, CLI, reports and serialized restart."""

    @pytest.mark.integration
    def test_saved_book_cli_recovery_and_second_spot(self, tmp_path: Path) -> None:
        """Retain three isolated accounts and recover every instance from an unseen-update fill."""
        root = Path(__file__).parents[2]
        for source, name in (
            ("configs/backtests/okx-eth-usdt-book.json", "book-config.json"),
            ("configs/history/okx-btc-usdt.json", "btc-history.json"),
            ("tests/integration/consumers/backtest/book_workflow.py", "book_workflow.py"),
        ):
            shutil.copyfile(root / source, tmp_path / name)
        result = subprocess.run(
            [sys.executable, "-I", str(tmp_path / "book_workflow.py"), str(tmp_path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert (tmp_path / "result.json").is_file()
