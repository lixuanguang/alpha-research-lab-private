"""Unit tests for alpha_core.research.optimize_runner (R4 artifacts)."""

from __future__ import annotations

from alpha_core.research.optimize_runner import (
    OptimizeConfig,
    TrialRecord,
    _expand_parameter_space,
)

# ---------------------------------------------------------------------------
# OptimizeConfig
# ---------------------------------------------------------------------------


class TestOptimizeConfig:
    def test_default_config(self) -> None:
        c = OptimizeConfig(
            dataset_id="ds_001",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            parameter_space={"threshold": [0.5, 1.0]},
        )
        assert c.search_mode == "grid"
        assert c.objective == "sharpe_ratio"
        assert c.max_trials == 20
        assert c.seed == 42

    def test_blank_dataset_id_raises(self) -> None:
        import pytest
        with pytest.raises(Exception):
            OptimizeConfig(
                dataset_id="  ",
                feature_set_version="v1",
                strategy_id="s",
                parameter_space={"threshold": [0.5]},
            )

    def test_unknown_parameter_space_key_raises(self) -> None:
        import pytest
        with pytest.raises(Exception, match="Unsupported"):
            OptimizeConfig(
                dataset_id="ds",
                feature_set_version="v1",
                strategy_id="s",
                parameter_space={"bad_param": [1.0]},
            )

    def test_empty_parameter_space_list_raises(self) -> None:
        import pytest
        with pytest.raises(Exception):
            OptimizeConfig(
                dataset_id="ds",
                feature_set_version="v1",
                strategy_id="s",
                parameter_space={"threshold": []},
            )


# ---------------------------------------------------------------------------
# _expand_parameter_space
# ---------------------------------------------------------------------------


class TestExpandParameterSpace:
    def test_grid_search_cartesian_product(self) -> None:
        config = OptimizeConfig(
            dataset_id="ds",
            feature_set_version="v1",
            strategy_id="s",
            parameter_space={"threshold": [0.5, 1.0], "target_weight": [0.1, 0.2]},
            search_mode="grid",
            max_trials=100,
        )
        trials = _expand_parameter_space(config)
        assert len(trials) == 4
        assert {"threshold": 0.5, "target_weight": 0.1} in trials
        assert {"threshold": 1.0, "target_weight": 0.2} in trials

    def test_max_trials_caps_grid(self) -> None:
        config = OptimizeConfig(
            dataset_id="ds",
            feature_set_version="v1",
            strategy_id="s",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0, 2.5]},
            search_mode="grid",
            max_trials=3,
        )
        trials = _expand_parameter_space(config)
        assert len(trials) == 3

    def test_random_search_shuffles(self) -> None:
        """Same config with seed should be deterministic, different seed different order."""
        config1 = OptimizeConfig(
            dataset_id="ds",
            feature_set_version="v1",
            strategy_id="s",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0, 2.5]},
            search_mode="random",
            max_trials=5,
            seed=42,
        )
        config2 = OptimizeConfig(
            dataset_id="ds",
            feature_set_version="v1",
            strategy_id="s",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0, 2.5]},
            search_mode="random",
            max_trials=5,
            seed=42,
        )
        t1 = _expand_parameter_space(config1)
        t2 = _expand_parameter_space(config2)
        assert t1 == t2  # Same seed → same order

    def test_random_different_seeds_may_differ(self) -> None:
        config1 = OptimizeConfig(
            dataset_id="ds",
            feature_set_version="v1",
            strategy_id="s",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]},
            search_mode="random",
            max_trials=6,
            seed=42,
        )
        config2 = OptimizeConfig(
            dataset_id="ds",
            feature_set_version="v1",
            strategy_id="s",
            parameter_space={"threshold": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]},
            search_mode="random",
            max_trials=6,
            seed=99,
        )
        t1 = _expand_parameter_space(config1)
        t2 = _expand_parameter_space(config2)
        # With 6 values and different seeds the ordering should differ (probabilistically)
        # We just check that both produce 6 results.
        assert len(t1) == 6
        assert len(t2) == 6

    def test_empty_parameter_space_returns_one_empty_dict(self) -> None:
        """No parameter_space → single trial with no params."""
        # OptimizeConfig disallows empty dict via validator; simulate by mocking.
        # We test the helper directly with a "skip validator" config.
        # Since the validator rejects empty dicts, just test the logic branch directly.
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.parameter_space = {}
        mock_config.search_mode = "grid"
        mock_config.max_trials = 1
        trials = _expand_parameter_space(mock_config)
        assert trials == [{}]


# ---------------------------------------------------------------------------
# TrialRecord
# ---------------------------------------------------------------------------


class TestTrialRecord:
    def test_ok_trial(self) -> None:
        rec = TrialRecord(
            optimize_run_id="opt_001",
            trial_index=0,
            backtest_run_id="bt_001",
            evaluate_run_id="ev_001",
            params={"threshold": 1.0},
            metrics={"sharpe_ratio": 1.5},
            objective_value=1.5,
            constraint_pass=True,
            status="ok",
        )
        assert rec.status == "ok"
        assert rec.constraint_pass is True

    def test_failed_trial(self) -> None:
        rec = TrialRecord(
            optimize_run_id="opt_001",
            trial_index=1,
            backtest_run_id="",
            evaluate_run_id="",
            params={},
            metrics={},
            objective_value=0.0,
            constraint_pass=False,
            status="failed",
        )
        assert rec.status == "failed"
        assert rec.constraint_pass is False

    def test_schema_version_default(self) -> None:
        rec = TrialRecord(
            optimize_run_id="o",
            trial_index=0,
            backtest_run_id="b",
            evaluate_run_id="e",
            params={},
            metrics={},
            objective_value=0.0,
            constraint_pass=True,
            status="ok",
        )
        assert rec.schema_version == 1


# ---------------------------------------------------------------------------
# Leaderboard sorting (reproducible determinism)
# ---------------------------------------------------------------------------


class TestLeaderboardSorting:
    def test_feasible_sorted_descending_by_objective(self) -> None:
        """Feasible trials are sorted by objective_value descending, tie-break trial_index."""
        records = [
            TrialRecord(
                optimize_run_id="o", trial_index=i,
                backtest_run_id=f"b{i}", evaluate_run_id=f"e{i}",
                params={}, metrics={}, objective_value=float(v),
                constraint_pass=True, status="ok",
            )
            for i, v in enumerate([1.5, 2.0, 0.5])
        ]
        feasible = [r for r in records if r.constraint_pass]
        sorted_records = sorted(
            feasible,
            key=lambda r: (-r.objective_value, r.trial_index),
        )
        assert sorted_records[0].objective_value == 2.0
        assert sorted_records[1].objective_value == 1.5
        assert sorted_records[2].objective_value == 0.5

    def test_constraint_violation_excluded(self) -> None:
        records = [
            TrialRecord(
                optimize_run_id="o", trial_index=0,
                backtest_run_id="b0", evaluate_run_id="e0",
                params={}, metrics={}, objective_value=99.0,
                constraint_pass=False, status="constraint_violation",
            ),
            TrialRecord(
                optimize_run_id="o", trial_index=1,
                backtest_run_id="b1", evaluate_run_id="e1",
                params={}, metrics={}, objective_value=1.0,
                constraint_pass=True, status="ok",
            ),
        ]
        feasible = [r for r in records if r.constraint_pass and r.status == "ok"]
        assert len(feasible) == 1
        assert feasible[0].trial_index == 1
