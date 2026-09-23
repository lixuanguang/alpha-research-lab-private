"""Keep installed economic regression scenarios in the domain test lane."""

# standard library imports
import os
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import pytest


class TestInstalledEconomics:
    """Exercise existing synthetic fixtures without opting into external publication."""

    @pytest.mark.integration
    @pytest.mark.parametrize("consumer", ("economic_workflow", "engineering_sample"))
    def test_saved_economics(self, tmp_path: Path, consumer: str) -> None:
        """Retain exact reports, source refusals, interrupted publication and process restart."""
        root = Path(__file__).parents[2]
        for source in (
            "configs/data-jobs/binance-archive.json",
            "configs/reference/binance-archive-spot.json",
            "tests/fixtures/eligibility/membership-corrections.json",
            "tests/fixtures/economics/spec.json",
            "configs/backtests/p1-btcusdt-return-v1.json",
            "configs/backtests/p1-btcusdt-no-trade-v1.json",
            f"tests/integration/consumers/backtest/{consumer}.py",
        ):
            shutil.copyfile(root / source, tmp_path / Path(source).name)
        environment = os.environ.copy()
        environment.pop("ALPHA_CLEARML_LOCAL_ENV", None)
        environment["MPLCONFIGDIR"] = str(tmp_path / "matplotlib-cache")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(tmp_path / f"{consumer}.py"),
                str(tmp_path),
                str(tmp_path / "run"),
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
