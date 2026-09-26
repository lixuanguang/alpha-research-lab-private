"""Exercise MR05 candidate packaging through an isolated installed consumer."""

from __future__ import annotations

# standard library imports
import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

# third party library imports
import msgspec
import pytest


class TestCandidateWorkflow:
    """Keep the MR03 study and MR05 handoff together outside the checkout."""

    @staticmethod
    def _copy_consumer(source: Path, destination: Path) -> None:
        """Copy stable entry scripts and their explicit authored support package."""
        for name in ("candidate_workflow.py", "decision_study.py"):
            shutil.copyfile(source / name, destination / name)
        shutil.copytree(source / "research_workflows", destination / "research_workflows")

    @pytest.mark.integration
    def test_installed_study_candidate_replay_and_restart(self, tmp_path: Path) -> None:
        """Retain actual study reports, load factories and resume two isolated placements."""
        source = Path(__file__).parent / "consumers/research"
        self._copy_consumer(source, tmp_path)
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
        monitoring = summary["learned_monitoring"]
        assert isinstance(monitoring, dict)
        assert monitoring["saved_paper_prediction"] is True
        assert monitoring["pending_before_label"] is True
        assert monitoring["observed_after_label"] is True
        assert isinstance(monitoring["metric_identity"], str)
        assert len(monitoring["metric_identity"]) == 64
        assert rule["admission_rejections_before_source_reads"] == 5
        assert learned["admission_rejections_before_source_reads"] == 5
        for name in ("rule", "learned"):
            assert (tmp_path / "output" / name / "manifest.json").is_file()
            assert (tmp_path / "output" / f"{name}-runtime-resumed.json").is_file()
            proof = summary[f"{name}_features"]
            assert isinstance(proof, dict)
            assert proof["source_offline_equal"] is True
            paper = summary[f"{name}_paper"]
            assert isinstance(paper, dict)
            assert paper["paper_shadow_intent_equal"] is True
            assert paper["paper_status"] == "filled"
            assert paper["shadow_status"] == "intent"
            for field, expected in (
                ("paper_fill_quantity", "1"),
                ("paper_fill_price", "99" if name == "rule" else "100"),
                ("paper_fee", "0.20"),
                ("paper_cash", "900.80" if name == "rule" else "899.80"),
            ):
                actual = paper[field]
                assert isinstance(actual, str)
                assert Decimal(actual) == Decimal(expected)
            assert paper["shadow_zero_fills"] is True
            assert paper["restart_no_duplicate_effects"] is True
            assert paper["submission_attempted"] is False

    @pytest.mark.integration
    def test_real_feast_serving_preserves_candidate_intent(self, tmp_path: Path) -> None:
        """Qualify the same packaged candidates against the isolated real Feast worker."""
        if not os.environ.get("ALPHA_FEAST_WORKER_PYTHON"):
            pytest.skip("isolated Feast worker interpreter is unavailable")
        source = Path(__file__).parent / "consumers/research"
        self._copy_consumer(source, tmp_path)
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
            assert proof["online_paper_intent_equal"] is True
            assert proof["online_paper_fill_count"] == 1
            assert proof["online_paper_service_loss_paused"] is True
            assert proof["online_paper_version_change_paused"] is True
            assert proof["stale_paused"] is True
            assert proof["service_loss_paused"] is True
            assert proof["version_change_paused"] is True
