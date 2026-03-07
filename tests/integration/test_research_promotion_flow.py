"""Integration tests for the LA-018 promotion-gate workflow (LA-018).

Coverage
--------
- ``session start / status / list`` CLI commands.
- ``catalog add / list / show`` CLI commands.
- ``promote`` gate pass scenario using a synthetic evaluate manifest.
- ``promote`` gate fail scenario (each gate independently and combined).
- ``promote`` force override skipping failed gates.
- Reviewer metadata is persisted in catalog entries.
- Machine-readable JSON output for all governance commands.
- Non-zero exit codes on gate failures.

No full pipeline execution is required: the tests seed synthetic
``evaluate_manifest.json`` artifacts directly via the artifact store so
that promote can load metrics without running the backtest/evaluate chain.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import apps.research.main as research_main
from apps.research.commands.promote import PromotionGateConfig, evaluate_gates
from click.testing import CliRunner, Result

import alpha_core.research.artifact_store as artifact_store_mod
import alpha_core.research.evaluate_runner as evaluate_runner_mod
import alpha_core.research.experiment_catalog as catalog_mod
import alpha_core.research.session as session_mod

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_STRATEGY_ID = "zscore_v1"

# Metrics that pass all default gates
_PASSING_METRICS: dict[str, float] = {
    "sharpe_ratio": 1.8,
    "max_drawdown": -0.08,
    "trade_count": 30.0,
    "total_return": 0.12,
    "win_rate": 0.60,
}

# Metrics that violate all three default gates
_FAILING_METRICS: dict[str, float] = {
    "sharpe_ratio": 0.3,
    "max_drawdown": -0.45,
    "trade_count": 2.0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_evaluate_manifest(
    storage_root: Path,
    metrics: dict[str, float],
) -> tuple[str, str]:
    """Write a synthetic evaluate_manifest.json and return (run_id, entry_id).

    Creates an evaluate manifest in the artifact store so `promote` can load
    metrics without running the backtest/evaluate pipeline.
    """
    run_id = uuid.uuid4().hex
    store = artifact_store_mod.FilesystemArtifactStore(storage_root)
    manifest = evaluate_runner_mod.EvaluateManifest(
        run_id=run_id,
        backtest_run_id=uuid.uuid4().hex,
        metrics_profile="pm_core",
        built_at=datetime(2026, 3, 7, tzinfo=UTC),
        metrics=metrics,
        artifacts={},
    )
    path = store.prepare_path(run_id, "evaluate_manifest.json")
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    entry = catalog_mod.add_entry(
        storage_root,
        run_id=run_id,
        strategy_id=_STRATEGY_ID,
    )
    return run_id, entry.entry_id


def _invoke(args: list[str], storage_root: Path) -> Result:
    """Invoke the research CLI with common --output-dir flag."""
    runner = CliRunner()
    return runner.invoke(
        research_main.main,
        ["--output-dir", str(storage_root), *args],
        catch_exceptions=False,
    )


# ===========================================================================
# Gate unit tests
# ===========================================================================


class TestPromotionGateLogic:
    """Pure unit tests for the evaluate_gates function, no CLI or I/O."""

    def test_passing_metrics_returns_no_violations(self) -> None:
        result = evaluate_gates(_PASSING_METRICS, PromotionGateConfig())
        assert result.passed
        assert result.violations == []

    def test_low_sharpe_is_caught(self) -> None:
        result = evaluate_gates(
            {"sharpe_ratio": 0.5, "max_drawdown": -0.05, "trade_count": 20},
            PromotionGateConfig(),
        )
        assert not result.passed
        names = {v.metric for v in result.violations}
        assert "sharpe_ratio" in names

    def test_excessive_drawdown_is_caught(self) -> None:
        result = evaluate_gates(
            {"sharpe_ratio": 2.0, "max_drawdown": -0.50, "trade_count": 20},
            PromotionGateConfig(),
        )
        assert not result.passed
        names = {v.metric for v in result.violations}
        assert "max_drawdown" in names

    def test_insufficient_trades_is_caught(self) -> None:
        result = evaluate_gates(
            {"sharpe_ratio": 2.0, "max_drawdown": -0.05, "trade_count": 3},
            PromotionGateConfig(),
        )
        assert not result.passed
        names = {v.metric for v in result.violations}
        assert "trade_count" in names

    def test_all_violations_reported_together(self) -> None:
        result = evaluate_gates(_FAILING_METRICS, PromotionGateConfig())
        assert not result.passed
        assert len(result.violations) == 3

    def test_custom_thresholds_applied(self) -> None:
        cfg = PromotionGateConfig(min_sharpe=0.1, max_drawdown=-0.99, min_trades=1)
        result = evaluate_gates(_FAILING_METRICS, cfg)
        assert result.passed

    def test_metrics_snapshot_captured(self) -> None:
        result = evaluate_gates(_PASSING_METRICS, PromotionGateConfig())
        assert result.metrics["sharpe_ratio"] == _PASSING_METRICS["sharpe_ratio"]


# ===========================================================================
# Session CLI tests
# ===========================================================================


class TestSessionCommands:
    def test_session_start_creates_session(self, tmp_path: Path) -> None:
        result = _invoke(
            ["session", "start", "--strategy-id", _STRATEGY_ID, "--storage-root", str(tmp_path)],
            tmp_path,
        )
        assert result.exit_code == 0, result.output
        assert _STRATEGY_ID in result.output

    def test_session_start_json_output(self, tmp_path: Path) -> None:
        result = _invoke(
            [
                "--format",
                "json",
                "session",
                "start",
                "--strategy-id",
                _STRATEGY_ID,
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["strategy_id"] == _STRATEGY_ID
        assert "session_id" in data

    def test_session_status_shows_correct_session(self, tmp_path: Path) -> None:
        sess = session_mod.create_session(tmp_path, strategy_id=_STRATEGY_ID)
        result = _invoke(
            ["session", "status", sess.session_id, "--storage-root", str(tmp_path)],
            tmp_path,
        )
        assert result.exit_code == 0
        assert sess.session_id in result.output

    def test_session_status_missing_raises_error(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--output-dir",
                str(tmp_path),
                "session",
                "status",
                "nonexistent_id",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_session_list_json_returns_array(self, tmp_path: Path) -> None:
        session_mod.create_session(tmp_path, strategy_id="s1")
        session_mod.create_session(tmp_path, strategy_id="s2")
        result = _invoke(
            ["--format", "json", "session", "list", "--storage-root", str(tmp_path)],
            tmp_path,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_session_list_empty_is_handled(self, tmp_path: Path) -> None:
        result = _invoke(
            ["session", "list", "--storage-root", str(tmp_path)],
            tmp_path,
        )
        assert result.exit_code == 0
        assert "No sessions" in result.output


# ===========================================================================
# Catalog CLI tests
# ===========================================================================


class TestCatalogCommands:
    def test_catalog_add_creates_candidate_entry(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4().hex
        result = _invoke(
            [
                "catalog",
                "add",
                "--run-id",
                run_id,
                "--strategy-id",
                _STRATEGY_ID,
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0
        assert "entry_id" in result.output

    def test_catalog_add_json_output(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4().hex
        result = _invoke(
            [
                "--format",
                "json",
                "catalog",
                "add",
                "--run-id",
                run_id,
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["run_id"] == run_id
        assert data["status"] == "candidate"

    def test_catalog_list_filters_by_status(self, tmp_path: Path) -> None:
        _, _ = _seed_evaluate_manifest(tmp_path, _PASSING_METRICS)
        run_id2 = uuid.uuid4().hex
        e2 = catalog_mod.add_entry(tmp_path, run_id=run_id2, strategy_id=_STRATEGY_ID)
        catalog_mod.update_status(tmp_path, e2.entry_id, status="needs_review")
        catalog_mod.update_status(
            tmp_path,
            e2.entry_id,
            status="rejected",
            reviewed_by="bob",
            reason="test",
        )

        result = _invoke(
            [
                "--format",
                "json",
                "catalog",
                "list",
                "--status",
                "candidate",
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(e["status"] == "candidate" for e in data)

    def test_catalog_show_returns_entry(self, tmp_path: Path) -> None:
        _, entry_id = _seed_evaluate_manifest(tmp_path, _PASSING_METRICS)
        result = _invoke(
            ["--format", "json", "catalog", "show", entry_id, "--storage-root", str(tmp_path)],
            tmp_path,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["entry_id"] == entry_id

    def test_catalog_show_missing_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--output-dir",
                str(tmp_path),
                "catalog",
                "show",
                "no_such_entry",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0


# ===========================================================================
# Promote CLI tests
# ===========================================================================


class TestPromoteCommand:
    def test_promote_pass_approved_for_paper(self, tmp_path: Path) -> None:
        _, entry_id = _seed_evaluate_manifest(tmp_path, _PASSING_METRICS)
        result = _invoke(
            [
                "--format",
                "json",
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "approved_for_paper",
                "--reviewed-by",
                "alice",
                "--reason",
                "Meets all thresholds",
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "approved_for_paper"
        assert data["reviewed_by"] == "alice"
        assert data["reason"] == "Meets all thresholds"
        # gate metrics included in output
        assert data["gate"]["passed"] is True

    def test_promote_fail_gates_exits_nonzero(self, tmp_path: Path) -> None:
        _, entry_id = _seed_evaluate_manifest(tmp_path, _FAILING_METRICS)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--output-dir",
                str(tmp_path),
                "--format",
                "json",
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "approved_for_paper",
                "--reviewed-by",
                "alice",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_promote_fail_gates_json_error_output(self, tmp_path: Path) -> None:
        """Gate failure emits a JSON payload containing violations in output (stderr mixed in)."""
        _, entry_id = _seed_evaluate_manifest(tmp_path, _FAILING_METRICS)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--output-dir",
                str(tmp_path),
                "--format",
                "json",
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "approved_for_paper",
                "--reviewed-by",
                "alice",
                "--storage-root",
                str(tmp_path),
            ],
        )
        # stderr is mixed into output by default; parse the JSON block
        error_payload = json.loads(result.output)
        assert error_payload["status"] == "gate_failed"
        assert len(error_payload["violations"]) == 3

    def test_promote_force_overrides_failed_gates(self, tmp_path: Path) -> None:
        _, entry_id = _seed_evaluate_manifest(tmp_path, _FAILING_METRICS)
        result = _invoke(
            [
                "--format",
                "json",
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "approved_for_paper",
                "--reviewed-by",
                "alice",
                "--reason",
                "Manual override approved by team",
                "--force",
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "approved_for_paper"

    def test_promote_to_needs_review_no_gates(self, tmp_path: Path) -> None:
        """needs_review transitions never check gates regardless of metrics."""
        _, entry_id = _seed_evaluate_manifest(tmp_path, _FAILING_METRICS)
        result = _invoke(
            [
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "needs_review",
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0

    def test_promote_reject_records_reviewer(self, tmp_path: Path) -> None:
        _, entry_id = _seed_evaluate_manifest(tmp_path, _FAILING_METRICS)
        result = _invoke(
            [
                "--format",
                "json",
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "rejected",
                "--reviewed-by",
                "charlie",
                "--reason",
                "Below threshold",
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "rejected"
        assert data["reviewed_by"] == "charlie"
        assert data["reviewed_at_utc"] is not None

    def test_promote_approved_requires_reviewed_by(self, tmp_path: Path) -> None:
        _, entry_id = _seed_evaluate_manifest(tmp_path, _PASSING_METRICS)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--output-dir",
                str(tmp_path),
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "approved_for_paper",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_promote_custom_thresholds_block_borderline(self, tmp_path: Path) -> None:
        """A run with Sharpe 1.5 passes default gate but fails --min-sharpe 2.0."""
        borderline_metrics = {**_PASSING_METRICS, "sharpe_ratio": 1.5}
        _, entry_id = _seed_evaluate_manifest(tmp_path, borderline_metrics)
        runner = CliRunner()
        result = runner.invoke(
            research_main.main,
            [
                "--output-dir",
                str(tmp_path),
                "--format",
                "json",
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "approved_for_paper",
                "--reviewed-by",
                "alice",
                "--min-sharpe",
                "2.0",
                "--storage-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_promote_catalog_entry_is_traceable_to_run(self, tmp_path: Path) -> None:
        """After promotion, catalog entry retains run_id linkage."""
        run_id, entry_id = _seed_evaluate_manifest(tmp_path, _PASSING_METRICS)
        _invoke(
            [
                "--format",
                "json",
                "promote",
                "--entry-id",
                entry_id,
                "--target-status",
                "approved_for_paper",
                "--reviewed-by",
                "alice",
                "--storage-root",
                str(tmp_path),
            ],
            tmp_path,
        )
        entry = catalog_mod.get_entry(tmp_path, entry_id)
        assert entry.run_id == run_id
        assert entry.status == "approved_for_paper"
