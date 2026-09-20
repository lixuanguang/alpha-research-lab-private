"""Retain one fresh-process test spanning acquisition recovery through saved EDA."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest

_ROOT = Path(__file__).parents[2]


class TestIngestionWorkflow:
    """Use installed commands outside the checkout; only source HTTP is synthetic."""

    @pytest.mark.integration
    def test_saved_feature_label_study(self, tmp_path: Path) -> None:
        """Reopen evidenced synthetic revisions through the installed retained diagnostic."""
        for source in (
            "configs/data-jobs/binance-archive.json",
            "configs/reference/binance-archive-spot.json",
            "tests/fixtures/eligibility/membership-corrections.json",
            "tests/integration/consumers/research/feature_study.py",
        ):
            shutil.copyfile(_ROOT / source, tmp_path / Path(source).name)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(tmp_path / "feature_study.py"),
                str(tmp_path),
                str(tmp_path / "run"),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert (tmp_path / "run/result.json").is_file()

    @pytest.mark.integration
    def test_acquire_resume_publish_reopen_and_eda(self, tmp_path: Path) -> None:
        """Reject partial acquisition, preserve resume lineage and consume the published ID."""
        for source in (
            "configs/data-jobs/binance-archive.json",
            "configs/live/okx-btc-usdt.json",
            "configs/reference/binance-archive-spot.json",
            "tests/fixtures/eligibility/membership-corrections.json",
            "tests/integration/consumers/datasets/ingestion_workflow.py",
            "tests/support/subprocesses/interrupt_command.py",
        ):
            shutil.copyfile(_ROOT / source, tmp_path / Path(source).name)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(tmp_path / "ingestion_workflow.py"),
                str(tmp_path),
                str(tmp_path / "run"),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (tmp_path / "run/result.json").read_bytes(), type=dict[str, object]
        )
        assert summary["experiment_attempts"] == 2 and summary["experiment_run_identity"]
        assert summary["research_inputs"] == 3 and summary["book_market_rows"] == 1
        assert summary["configured_job"] == "spot-comparison" and summary["selection_identity"]
        assert summary["partitions"] == 2 and summary["history_rows"] == 6
        assert summary["cutoff_rows"] == 0 and summary["scope"] == "exploratory_degraded"
        assert summary["repeat_fetches"] == 0 and summary["incomplete_publish_exit"] == 3
        assert summary["interrupted_publish_exit"] == 75
