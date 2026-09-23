"""Verify fresh research extensions and reload-only continuation through the installed artifact."""

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import pytest


class TestDecisionWorkflow:
    """Run a copied standalone consumer without access to repository test helpers."""

    @pytest.mark.integration
    def test_installed_custom_components_and_fresh_process_restart(self, tmp_path: Path) -> None:
        """Carry fresh components through the public decision workflow."""
        source = Path(__file__).parent / "consumers/research/decision_extensions.py"
        script = tmp_path / source.name
        shutil.copyfile(source, script)
        result = subprocess.run(
            [sys.executable, "-I", str(script), str(tmp_path / "output")],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert '"restart_equal":true' in result.stdout
