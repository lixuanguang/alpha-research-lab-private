"""Schema regression tests for run manifest models (LA-014).

These tests pin the exact field sets and schema version constants of every
Pydantic manifest model in the pipeline.  **Any field change (add / remove /
rename / type change) will fail these tests** and requires an explicit update:

1. Bump the corresponding ``_EXPECTED_*_VERSION`` constant **and** the
   ``schema_version`` constant in the source module.
2. Update the ``_EXPECTED_*_KEYS`` frozenset to match the new field set.
3. Record the reason in the commit message.

This file IS the regression snapshot — no external snapshot files required.

Modules under test
------------------
- alpha_core.research.manifest          → RunManifest, RUN_MANIFEST_SCHEMA_VERSION
- alpha_core.research.backtest_runner   → BacktestManifest
- alpha_core.research.evaluate_runner   → EvaluateManifest
- alpha_core.research.feature_runner    → FeatureManifest
- alpha_core.research.dataset           → DatasetManifest
- alpha_core.research.optimize_runner   → OptimizeManifest, TrialRecord
- alpha_core.research.run_summary       → RunSummary, RUN_SUMMARY_SCHEMA_VERSION
- alpha_core.research.run_context       → RunContext
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from alpha_core.research.backtest_runner import BacktestManifest
from alpha_core.research.dataset import DatasetManifest
from alpha_core.research.evaluate_runner import EvaluateManifest
from alpha_core.research.feature_runner import FeatureManifest
from alpha_core.research.manifest import RUN_MANIFEST_SCHEMA_VERSION, RunManifest
from alpha_core.research.optimize_runner import OptimizeManifest, TrialRecord
from alpha_core.research.run_context import RunContext
from alpha_core.research.run_summary import RUN_SUMMARY_SCHEMA_VERSION, RunSummary

# ---------------------------------------------------------------------------
# Pinned schema version constants
#
# Edit ONLY when you intentionally change the corresponding source model.
# ---------------------------------------------------------------------------

_EXPECTED_RUN_MANIFEST_VERSION: int = 2
_EXPECTED_BACKTEST_MANIFEST_VERSION: int = 2
_EXPECTED_EVALUATE_MANIFEST_VERSION: int = 1
_EXPECTED_FEATURE_MANIFEST_VERSION: int = 2
_EXPECTED_OPTIMIZE_MANIFEST_VERSION: int = 1
_EXPECTED_TRIAL_RECORD_VERSION: int = 1
_EXPECTED_RUN_SUMMARY_VERSION: int = 1

# ---------------------------------------------------------------------------
# Pinned field sets
#
# frozensets of field names.  Fail on any add / remove / rename.
# ---------------------------------------------------------------------------

_EXPECTED_RUN_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "run_id",
        "run_type",
        "config_hash",
        "session_id",
        "git_commit",
        "started_at_utc",
        "completed_at_utc",
    }
)

_EXPECTED_RUN_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "run",
        "artifacts",
        "parent_run_id",
    }
)

_EXPECTED_BACKTEST_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "run_id",
        "dataset_id",
        "feature_set_version",
        "strategy_id",
        "engine",
        "starting_cash",
        "built_at",
        "trade_count",
        "final_equity",
        "total_return",
        "artifacts",
        "parent_run_id",
        "strategy_recipe_id",
        "strategy_recipe_version",
    }
)

_EXPECTED_EVALUATE_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "run_id",
        "backtest_run_id",
        "metrics_profile",
        "built_at",
        "metrics",
        "artifacts",
        "parent_run_id",
    }
)

_EXPECTED_FEATURE_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "run_id",
        "dataset_id",
        "feature_set_version",
        "built_at",
        "lookback_bars",
        "row_count",
        "feature_count",
        "feature_names",
        "artifacts",
        "parent_run_id",
        "factor_pack_id",
        "factor_pack_version",
    }
)

_EXPECTED_DATASET_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "run_id",
        "dataset_id",
        "config",
        "built_at",
        "row_counts",
        "instrument_count",
        "date_range",
        "quality_summary",
        "schema_version",
    }
)

_EXPECTED_OPTIMIZE_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "run_id",
        "dataset_id",
        "feature_set_version",
        "strategy_id",
        "search_mode",
        "objective",
        "objective_minimize",
        "total_trials",
        "feasible_trials",
        "best_backtest_run_id",
        "best_objective_value",
        "built_at",
        "artifacts",
        "parent_run_id",
    }
)

_EXPECTED_TRIAL_RECORD_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "optimize_run_id",
        "trial_index",
        "backtest_run_id",
        "evaluate_run_id",
        "params",
        "metrics",
        "objective_value",
        "constraint_pass",
        "status",
    }
)

_EXPECTED_RUN_SUMMARY_KEYS: frozenset[str] = frozenset(
    {
        "summary_version",
        "run_id",
        "run_type",
        "status",
        "config_hash",
        "git_commit",
        "started_at_utc",
        "completed_at_utc",
        "artifact_keys",
        "extra",
    }
)

# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------


class TestRunContextSchema:
    def test_field_set_stable(self) -> None:
        actual = frozenset(RunContext.model_fields.keys())
        assert actual == _EXPECTED_RUN_CONTEXT_KEYS, (
            "RunContext fields changed from snapshot. "
            "Update _EXPECTED_RUN_CONTEXT_KEYS after reviewing the change."
        )

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            RunContext(  # type: ignore[call-arg]
                run_id="x",
                run_type="backtest",
                config_hash="abc",
                started_at_utc=datetime.now(tz=UTC),
                unknown_field="oops",
            )

    def test_round_trip_json(self) -> None:
        ctx = RunContext(
            run_id="abc123",
            run_type="backtest",
            config_hash="deadbeef",
            session_id="session_001",
            git_commit="a1b2c3d",
            started_at_utc=datetime(2026, 3, 7, 10, 0, 0, tzinfo=UTC),
        )
        payload = ctx.model_dump(mode="json")
        raw = json.dumps(payload)
        restored = RunContext.model_validate_json(raw)
        assert restored.run_id == ctx.run_id
        assert restored.config_hash == ctx.config_hash
        assert restored.session_id == "session_001"


# ---------------------------------------------------------------------------
# RunManifest
# ---------------------------------------------------------------------------


class TestRunManifestSchema:
    def test_schema_version_constant_pinned(self) -> None:
        """Fails when RUN_MANIFEST_SCHEMA_VERSION is bumped without updating snapshot."""
        assert RUN_MANIFEST_SCHEMA_VERSION == _EXPECTED_RUN_MANIFEST_VERSION, (
            f"RUN_MANIFEST_SCHEMA_VERSION changed to {RUN_MANIFEST_SCHEMA_VERSION}. "
            f"Update _EXPECTED_RUN_MANIFEST_VERSION={_EXPECTED_RUN_MANIFEST_VERSION} "
            "and review the field set."
        )

    def test_field_set_stable(self) -> None:
        actual = frozenset(RunManifest.model_fields.keys())
        assert actual == _EXPECTED_RUN_MANIFEST_KEYS, (
            "RunManifest fields changed from snapshot. "
            "Update _EXPECTED_RUN_MANIFEST_KEYS after reviewing the change."
        )

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            RunManifest(  # type: ignore[call-arg]
                run=RunContext(
                    run_id="x",
                    run_type="backtest",
                    config_hash="abc",
                    started_at_utc=datetime.now(tz=UTC),
                ),
                artifacts={},
                phantom_field="oops",
            )

    def test_round_trip_serialisation(self) -> None:
        ctx = RunContext(
            run_id="r1",
            run_type="backtest",
            config_hash="hash1",
            started_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        )
        manifest = RunManifest(run=ctx, artifacts={"config": "/data/runs/r1/config.json"})
        payload = manifest.model_dump(mode="json")
        raw = json.dumps(payload)
        restored = RunManifest.model_validate_json(raw)
        assert restored.run.run_id == "r1"
        assert restored.schema_version == _EXPECTED_RUN_MANIFEST_VERSION

    def test_schema_version_in_serialised_payload(self) -> None:
        ctx = RunContext(
            run_id="r2",
            run_type="live",
            config_hash="h2",
            started_at_utc=datetime.now(tz=UTC),
        )
        manifest = RunManifest(run=ctx, artifacts={})
        payload = manifest.model_dump(mode="json")
        assert payload["schema_version"] == _EXPECTED_RUN_MANIFEST_VERSION


# ---------------------------------------------------------------------------
# BacktestManifest
# ---------------------------------------------------------------------------


class TestBacktestManifestSchema:
    def test_schema_version_pinned(self) -> None:
        assert (
            BacktestManifest.model_fields["schema_version"].default
            == _EXPECTED_BACKTEST_MANIFEST_VERSION
        )

    def test_field_set_stable(self) -> None:
        actual = frozenset(BacktestManifest.model_fields.keys())
        assert actual == _EXPECTED_BACKTEST_MANIFEST_KEYS, (
            "BacktestManifest fields changed. Update _EXPECTED_BACKTEST_MANIFEST_KEYS."
        )

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            BacktestManifest(  # type: ignore[call-arg]
                run_id="x",
                dataset_id="d",
                feature_set_version="v1",
                strategy_id="s",
                engine="event",
                starting_cash=1000.0,
                built_at=datetime.now(tz=UTC),
                trade_count=0,
                final_equity=1000.0,
                total_return=0.0,
                artifacts={},
                phantom="bad",
            )

    def test_round_trip_json(self) -> None:
        m = BacktestManifest(
            run_id="bt1",
            dataset_id="ds1",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            engine="event",
            starting_cash=10_000.0,
            built_at=datetime(2026, 3, 1, tzinfo=UTC),
            trade_count=42,
            final_equity=11_200.0,
            total_return=0.12,
            artifacts={"trades": "/data/bt1/trades.parquet"},
            strategy_recipe_id="zscore_momentum",
            strategy_recipe_version="1.0.0",
        )
        payload = m.model_dump(mode="json")
        restored = BacktestManifest.model_validate(payload)
        assert restored.run_id == "bt1"
        assert restored.schema_version == _EXPECTED_BACKTEST_MANIFEST_VERSION

    def test_parent_run_id_nullable(self) -> None:
        m = BacktestManifest(
            run_id="bt2",
            dataset_id="ds1",
            feature_set_version="v1",
            strategy_id="s",
            engine="event",
            starting_cash=1000.0,
            built_at=datetime.now(tz=UTC),
            trade_count=0,
            final_equity=1000.0,
            total_return=0.0,
            artifacts={},
            parent_run_id=None,
        )
        assert m.parent_run_id is None


# ---------------------------------------------------------------------------
# EvaluateManifest
# ---------------------------------------------------------------------------


class TestEvaluateManifestSchema:
    def test_schema_version_pinned(self) -> None:
        assert (
            EvaluateManifest.model_fields["schema_version"].default
            == _EXPECTED_EVALUATE_MANIFEST_VERSION
        )

    def test_field_set_stable(self) -> None:
        actual = frozenset(EvaluateManifest.model_fields.keys())
        assert actual == _EXPECTED_EVALUATE_MANIFEST_KEYS, (
            "EvaluateManifest fields changed. Update _EXPECTED_EVALUATE_MANIFEST_KEYS."
        )

    def test_round_trip_json(self) -> None:
        m = EvaluateManifest(
            run_id="ev1",
            backtest_run_id="bt1",
            metrics_profile="pm_core",
            built_at=datetime(2026, 3, 2, tzinfo=UTC),
            metrics={"total_return": 0.12, "sharpe_ratio": 1.4},
            artifacts={"metrics_json": "/data/ev1/metrics.json"},
        )
        payload = m.model_dump(mode="json")
        restored = EvaluateManifest.model_validate(payload)
        assert restored.run_id == "ev1"
        assert restored.schema_version == _EXPECTED_EVALUATE_MANIFEST_VERSION


# ---------------------------------------------------------------------------
# FeatureManifest
# ---------------------------------------------------------------------------


class TestFeatureManifestSchema:
    def test_schema_version_pinned(self) -> None:
        assert (
            FeatureManifest.model_fields["schema_version"].default
            == _EXPECTED_FEATURE_MANIFEST_VERSION
        )

    def test_field_set_stable(self) -> None:
        actual = frozenset(FeatureManifest.model_fields.keys())
        assert actual == _EXPECTED_FEATURE_MANIFEST_KEYS, (
            "FeatureManifest fields changed. Update _EXPECTED_FEATURE_MANIFEST_KEYS."
        )

    def test_round_trip_json(self) -> None:
        m = FeatureManifest(
            run_id="ft1",
            dataset_id="ds1",
            feature_set_version="v1",
            built_at=datetime(2026, 2, 15, tzinfo=UTC),
            lookback_bars=20,
            row_count=500,
            feature_count=4,
            feature_names=["midprice_ema20", "spread_ma5", "vol_ratio", "momentum"],
            artifacts={"features": "/data/ft1/features.parquet"},
            factor_pack_id="momentum",
            factor_pack_version="1.0.0",
        )
        payload = m.model_dump(mode="json")
        restored = FeatureManifest.model_validate(payload)
        assert restored.run_id == "ft1"
        assert restored.schema_version == _EXPECTED_FEATURE_MANIFEST_VERSION


# ---------------------------------------------------------------------------
# DatasetManifest
# ---------------------------------------------------------------------------


class TestDatasetManifestSchema:
    def test_field_set_stable(self) -> None:
        actual = frozenset(DatasetManifest.model_fields.keys())
        assert actual == _EXPECTED_DATASET_MANIFEST_KEYS, (
            "DatasetManifest fields changed. Update _EXPECTED_DATASET_MANIFEST_KEYS."
        )

    def test_schema_version_default_pinned(self) -> None:
        assert DatasetManifest.model_fields["schema_version"].default == 1


# ---------------------------------------------------------------------------
# OptimizeManifest
# ---------------------------------------------------------------------------


class TestOptimizeManifestSchema:
    def test_schema_version_pinned(self) -> None:
        assert (
            OptimizeManifest.model_fields["schema_version"].default
            == _EXPECTED_OPTIMIZE_MANIFEST_VERSION
        )

    def test_field_set_stable(self) -> None:
        actual = frozenset(OptimizeManifest.model_fields.keys())
        assert actual == _EXPECTED_OPTIMIZE_MANIFEST_KEYS, (
            "OptimizeManifest fields changed. Update _EXPECTED_OPTIMIZE_MANIFEST_KEYS."
        )

    def test_round_trip_json(self) -> None:
        m = OptimizeManifest(
            run_id="op1",
            dataset_id="ds1",
            feature_set_version="v1",
            strategy_id="zscore_v1",
            search_mode="grid",
            objective="sharpe_ratio",
            objective_minimize=False,
            total_trials=9,
            feasible_trials=7,
            best_backtest_run_id="bt_best",
            best_objective_value=1.85,
            built_at=datetime(2026, 3, 5, tzinfo=UTC),
            artifacts={"leaderboard": "/data/op1/leaderboard.json"},
        )
        payload = m.model_dump(mode="json")
        restored = OptimizeManifest.model_validate(payload)
        assert restored.run_id == "op1"
        assert restored.schema_version == _EXPECTED_OPTIMIZE_MANIFEST_VERSION


# ---------------------------------------------------------------------------
# TrialRecord
# ---------------------------------------------------------------------------


class TestTrialRecordSchema:
    def test_schema_version_pinned(self) -> None:
        assert TrialRecord.model_fields["schema_version"].default == _EXPECTED_TRIAL_RECORD_VERSION

    def test_field_set_stable(self) -> None:
        actual = frozenset(TrialRecord.model_fields.keys())
        assert actual == _EXPECTED_TRIAL_RECORD_KEYS, (
            "TrialRecord fields changed. Update _EXPECTED_TRIAL_RECORD_KEYS."
        )


# ---------------------------------------------------------------------------
# RunSummary
# ---------------------------------------------------------------------------


class TestRunSummarySchema:
    def test_schema_version_constant_pinned(self) -> None:
        assert RUN_SUMMARY_SCHEMA_VERSION == _EXPECTED_RUN_SUMMARY_VERSION, (
            f"RUN_SUMMARY_SCHEMA_VERSION changed to {RUN_SUMMARY_SCHEMA_VERSION}. "
            f"Update _EXPECTED_RUN_SUMMARY_VERSION and _EXPECTED_RUN_SUMMARY_KEYS."
        )

    def test_field_set_stable(self) -> None:
        actual = frozenset(RunSummary.model_fields.keys())
        assert actual == _EXPECTED_RUN_SUMMARY_KEYS, (
            "RunSummary fields changed. Update _EXPECTED_RUN_SUMMARY_KEYS."
        )

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            RunSummary(  # type: ignore[call-arg]
                run_id="x",
                run_type="backtest",
                status="completed",
                unknown_field="bad",
            )

    def test_round_trip_json(self) -> None:
        s = RunSummary(
            run_id="r1",
            run_type="backtest",
            status="materialized",
            config_hash="abc123",
            git_commit="d4e5f6",
            started_at_utc=datetime(2026, 3, 7, 9, 0, 0, tzinfo=UTC),
            completed_at_utc=datetime(2026, 3, 7, 9, 1, 0, tzinfo=UTC),
            artifact_keys=["config", "manifest", "trades"],
            extra={"strategy_id": "zscore_v1", "trade_count": 42},
        )
        payload = s.model_dump(mode="json")
        raw = json.dumps(payload)
        restored = RunSummary.model_validate_json(raw)
        assert restored.run_id == "r1"
        assert restored.summary_version == _EXPECTED_RUN_SUMMARY_VERSION
        assert "config" in restored.artifact_keys

    def test_summary_version_in_payload(self) -> None:
        s = RunSummary(run_id="r2", run_type="live", status="planned")
        payload = s.model_dump(mode="json")
        assert payload["summary_version"] == _EXPECTED_RUN_SUMMARY_VERSION

    def test_from_run_context_factory(self) -> None:
        ctx = RunContext(
            run_id="rc1",
            run_type="evaluate",
            config_hash="hhhhhhhh",
            git_commit="abc",
            started_at_utc=datetime(2026, 3, 7, tzinfo=UTC),
            completed_at_utc=datetime(2026, 3, 7, 0, 1, tzinfo=UTC),
        )
        s = RunSummary.from_run_context(
            ctx,
            status="materialized",
            artifact_keys=["metrics_json", "metrics_parquet"],
            extra={"backtest_run_id": "bt1"},
        )
        assert s.run_id == "rc1"
        assert s.run_type == "evaluate"
        assert s.config_hash == "hhhhhhhh"
        assert s.artifact_keys == ["metrics_json", "metrics_parquet"]  # sorted
        assert s.extra["backtest_run_id"] == "bt1"

    def test_as_text_contains_core_fields(self) -> None:
        s = RunSummary(
            run_id="rtext1",
            run_type="backtest",
            status="materialized",
            config_hash="abc123",
        )
        text = s.as_text()
        assert "rtext1" in text
        assert "backtest" in text
        assert "materialized" in text

    def test_as_json_str_is_valid_json(self) -> None:
        s = RunSummary(run_id="rjson1", run_type="live", status="planned")
        raw = s.as_json_str()
        parsed = json.loads(raw)
        assert parsed["run_id"] == "rjson1"
        assert parsed["summary_version"] == _EXPECTED_RUN_SUMMARY_VERSION


# ---------------------------------------------------------------------------
# Cross-schema invariants
# ---------------------------------------------------------------------------


class TestCrossSchemaInvariants:
    def test_all_manifest_schema_versions_are_positive_integers(self) -> None:
        for name, version in [
            ("RunManifest", RUN_MANIFEST_SCHEMA_VERSION),
            ("RunSummary", RUN_SUMMARY_SCHEMA_VERSION),
        ]:
            assert isinstance(version, int) and version >= 1, (
                f"{name} schema_version must be a positive integer"
            )

    def test_manifest_model_configs_all_forbid_extra(self) -> None:
        """All manifest models must have extra='forbid' to catch schema drift."""
        from alpha_core.research.backtest_runner import BacktestManifest
        from alpha_core.research.evaluate_runner import EvaluateManifest
        from alpha_core.research.feature_runner import FeatureManifest
        from alpha_core.research.manifest import RunManifest
        from alpha_core.research.optimize_runner import OptimizeManifest, TrialRecord
        from alpha_core.research.run_summary import RunSummary

        for model_cls in [
            RunManifest,
            BacktestManifest,
            EvaluateManifest,
            FeatureManifest,
            OptimizeManifest,
            TrialRecord,
            RunSummary,
        ]:
            config = model_cls.model_config  # type: ignore[attr-defined]
            assert config.get("extra") == "forbid", (
                f"{model_cls.__name__}.model_config must set extra='forbid'"
            )
