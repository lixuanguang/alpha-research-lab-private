"""Exercise MR05 candidate packaging through an isolated installed consumer."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
from pathlib import Path

# third party library imports
import msgspec
import pytest


class TestCandidateWorkflow:
    """Keep the MR03 study and MR05 handoff together outside the checkout."""

    @pytest.mark.integration
    def test_installed_study_candidate_replay_and_restart(self, tmp_path: Path) -> None:
        """Retain actual study reports, load factories and resume two isolated placements."""
        source = Path(__file__).parent / "consumers/research"
        for name in ("candidate_workflow.py", "decision_study.py"):
            shutil.copyfile(source / name, tmp_path / name)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(tmp_path / "candidate_workflow.py"),
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
            (tmp_path / "output/summary.json").read_bytes(),
            type=dict[str, dict[str, str | int | bool] | bool],
        )
        assert summary["fresh_process_restart_equal"] is True
        rule, learned = summary["rule"], summary["learned"]
        assert isinstance(rule, dict) and isinstance(learned, dict)
        assert rule["output"] == "order"
        assert learned["output"] == "target"
        assert rule["qualification"] == learned["qualification"] == "engineering"
        assert rule["candidate"] != learned["candidate"]
        assert rule["admission_rejections_before_source_reads"] == 5
        assert learned["admission_rejections_before_source_reads"] == 5
        for name in ("rule", "learned"):
            assert (tmp_path / "output" / name / "manifest.json").is_file()
            assert (tmp_path / "output" / f"{name}-runtime-resumed.json").is_file()
            proof = summary[f"{name}_features"]
            assert isinstance(proof, dict)
            assert proof["source_offline_equal"] is True

    @pytest.mark.integration
    def test_real_feast_serving_preserves_candidate_intent(self, tmp_path: Path) -> None:
        """Qualify the same packaged candidates against the isolated real Feast worker."""
        if not os.environ.get("ALPHA_FEAST_WORKER_PYTHON"):
            pytest.skip("isolated Feast worker interpreter is unavailable")
        source = Path(__file__).parent / "consumers/research"
        for name in ("candidate_workflow.py", "decision_study.py"):
            shutil.copyfile(source / name, tmp_path / name)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(tmp_path / "candidate_workflow.py"),
                str(tmp_path / "output"),
                "feast",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=360,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        summary = msgspec.json.decode(
            (tmp_path / "output/summary.json").read_bytes(),
            type=dict[str, dict[str, str | bool | int] | bool],
        )
        for name in ("rule_features", "learned_features"):
            proof = summary[name]
            assert isinstance(proof, dict)
            assert proof["source_offline_online_equal"] is True
            assert proof["stale_paused"] is True
            assert proof["service_loss_paused"] is True
            assert proof["version_change_paused"] is True
