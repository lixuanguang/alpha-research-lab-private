"""Verify a fresh decision study consumer against the installed wheel."""

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import pytest


class TestStudyWorkflow:
    """Run one copied consumer without repository test-helper imports."""

    @pytest.mark.integration
    def test_installed_temporal_study_search_and_retained_results(self, tmp_path: Path) -> None:
        """Prove fresh components reach exact economics, reports and durable attempts."""
        source = Path(__file__).parent / "consumers/research/decision_study.py"
        script = tmp_path / source.name
        shutil.copyfile(source, script)
        process = subprocess.run(
            [sys.executable, "-I", str(script), str(tmp_path / "retained")],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        assert process.returncode == 0, (process.stdout, process.stderr)
        assert '"walk_forward_folds":2' in process.stdout
        assert '"failed_holdout_recorded":true' in process.stdout
