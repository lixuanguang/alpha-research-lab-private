"""Package a completed study of installed extension components outside the checkout."""

from __future__ import annotations

# standard library imports
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest


class TestCandidatePackaging:
    """Run the packaging consumer as an isolated installed workflow."""

    @pytest.mark.integration
    def test_study_packages_verifies_loads_and_refuses_altered_requests(
        self, tmp_path: Path
    ) -> None:
        """The packaged candidate decides; changed, missing or unretained code is refused."""
        source = Path(__file__).parent / "consumers/research"
        shutil.copyfile(source / "candidate_packaging.py", tmp_path / "candidate_packaging.py")
        shutil.copytree(source / "research_workflows", tmp_path / "research_workflows")
        result = subprocess.run(
            [
                sys.executable,
                "-E",
                "-s",
                str(tmp_path / "candidate_packaging.py"),
                str(tmp_path / "output"),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (tmp_path / "output/summary.json").read_bytes(), type=dict[str, object]
        )
        assert summary["components"] == [
            "smoothed-imbalance",
            "imbalance-target",
            "fold-net",
            "fold-net-path",
        ]
        assert summary["requirements"] == [
            "authored-imbalance",
            "reference",
            "calendar",
            "valuation",
            "account",
            "execution",
        ]
        assert (summary["warm_status"], summary["decided_status"]) == ("warming", "decided")
        refusals = summary["refusals"]
        assert isinstance(refusals, dict)
        assert "different identity" in str(refusals["changed_parameters"])
        assert "one selection per study chart" in str(refusals["missing_chart"])
        assert "did not retain the installed extension" in str(refusals["unretained_extension"])
