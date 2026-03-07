"""Schema regression tests for metrics, reports, and live runtime observability (LA-014).

Pins the exact key sets produced by:
- ``EvaluateRunner`` metrics output per profile
- ``RuntimeMetrics.as_dict()``
- ``ExecutionReport`` (execution layer)
- ``RunSummary`` JSON payload (cross-check with test_run_manifest_schema.py)

**Update process when a key changes:**

1. Edit the corresponding ``_EXPECTED_*_KEYS`` frozenset below.
2. If the change affects a versioned model, bump its ``schema_version`` constant
   in the source module AND update the ``_EXPECTED_*_VERSION`` in
   ``test_run_manifest_schema.py``.
3. Record the reason in the commit message.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from apps.live_system.runtime import RuntimeMetrics

from alpha_core.execution.order_models import (
    ExecutionReport,
    OrderLifecycleStatus,
)
from alpha_core.research.run_context import RunContext
from alpha_core.research.run_summary import RunSummary

# ---------------------------------------------------------------------------
# Pinned key sets — edit deliberately, document why
# ---------------------------------------------------------------------------

# RuntimeMetrics.as_dict() output keys
_EXPECTED_RUNTIME_METRICS_KEYS: frozenset[str] = frozenset(
    {
        "cycles_completed",
        "total_signals",
        "total_targets",
        "total_orders",
        "total_errors",
        "started_at",
        "last_cycle_at",
    }
)

# Minimum set of keys every evaluate metrics dict must contain ("minimal" profile)
_EXPECTED_METRICS_MINIMAL_KEYS: frozenset[str] = frozenset(
    {
        "total_return",
        "trade_count",
    }
)

# Full set for the "pm_core" / "default" profile (superset of minimal)
_EXPECTED_METRICS_PM_CORE_KEYS: frozenset[str] = frozenset(
    {
        "total_return",
        "trade_count",
        "annualized_return",
        "sharpe_ratio",
        "max_drawdown",
        "win_rate",
        "avg_trade_return",
        "profit_factor",
    }
)

# Microstructure adds one additional key on top of pm_core
_EXPECTED_METRICS_MICROSTRUCTURE_KEYS: frozenset[str] = (
    _EXPECTED_METRICS_PM_CORE_KEYS | frozenset({"avg_spread_cost_bps"})
)

# ExecutionReport serialised field keys
_EXPECTED_EXECUTION_REPORT_KEYS: frozenset[str] = frozenset(
    {
        "order_id",
        "instrument_id",
        "status",
        "fill_price",
        "fill_size",
        "fill_ts",
        "fee",
        "slippage",
        "realized_pnl",
        "notes",
        "source_intent",
        "metadata",
    }
)

# RunSummary serialised field keys (mirrors test_run_manifest_schema.py)
_EXPECTED_RUN_SUMMARY_PAYLOAD_KEYS: frozenset[str] = frozenset(
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
# Helpers
# ---------------------------------------------------------------------------


def _make_run_summary(**overrides: object) -> RunSummary:
    defaults: dict[str, object] = {
        "run_id": "test_run_001",
        "run_type": "backtest",
        "status": "materialized",
        "config_hash": "abc123def456",
        "git_commit": "a1b2c3d",
        "started_at_utc": datetime(2026, 3, 7, 10, 0, 0, tzinfo=UTC),
        "completed_at_utc": datetime(2026, 3, 7, 10, 1, 0, tzinfo=UTC),
        "artifact_keys": ["config", "manifest", "trades"],
        "extra": {"strategy_id": "zscore_v1"},
    }
    defaults.update(overrides)
    return RunSummary(**defaults)  # type: ignore[arg-type]


def _limit_order() -> Any:
    import alpha_core.strategy_framework.models as sm
    return sm.OrderIntent(
        instrument_id="p:m1:yes",
        order_type=sm.OrderType.LIMIT,
        direction=sm.SignalDirection.LONG,
        size=Decimal("1"),
        price_limit=Decimal("0.55"),
    )


# ---------------------------------------------------------------------------
# RuntimeMetrics
# ---------------------------------------------------------------------------


class TestRuntimeMetricsSchema:
    def test_as_dict_key_set_stable(self) -> None:
        metrics = RuntimeMetrics()
        actual = frozenset(metrics.as_dict().keys())
        assert actual == _EXPECTED_RUNTIME_METRICS_KEYS, (
            "RuntimeMetrics.as_dict() keys changed. "
            "Update _EXPECTED_RUNTIME_METRICS_KEYS after reviewing the change."
        )

    def test_all_keys_present_when_started(self) -> None:
        metrics = RuntimeMetrics(
            cycles_completed=5,
            total_signals=10,
            total_targets=10,
            total_orders=8,
            total_errors=1,
            started_at=datetime(2026, 3, 7, 9, 0, 0, tzinfo=UTC),
            last_cycle_at=datetime(2026, 3, 7, 9, 2, 0, tzinfo=UTC),
        )
        d = metrics.as_dict()
        for key in _EXPECTED_RUNTIME_METRICS_KEYS:
            assert key in d, f"Missing key '{key}' in RuntimeMetrics.as_dict()"

    def test_as_dict_is_json_serialisable(self) -> None:
        metrics = RuntimeMetrics(
            cycles_completed=2,
            started_at=datetime(2026, 3, 7, tzinfo=UTC),
            last_cycle_at=datetime(2026, 3, 7, 0, 5, tzinfo=UTC),
        )
        raw = json.dumps(metrics.as_dict())  # must not raise
        parsed = json.loads(raw)
        assert parsed["cycles_completed"] == 2

    def test_null_datetimes_serialise(self) -> None:
        metrics = RuntimeMetrics()  # started_at / last_cycle_at are None
        d = metrics.as_dict()
        assert d["started_at"] is None
        assert d["last_cycle_at"] is None
        raw = json.dumps(d)  # None → null in JSON
        parsed = json.loads(raw)
        assert parsed["started_at"] is None


# ---------------------------------------------------------------------------
# Evaluate metrics profiles
# ---------------------------------------------------------------------------


class TestEvaluateMetricsSchema:
    """Regression tests for EvaluateRunner metrics output key sets.

    These tests use the runner's private computation helper directly via a small
    shim to avoid requiring real Parquet artifacts on disk.
    """

    def _run_metrics(self, profile: str) -> dict[str, float]:
        """Run the evaluate metrics computation with empty (but valid) dataframes."""
        import pandas as pd

        from alpha_core.research.evaluate_runner import (
            _compute_metrics,
        )

        trades_df = pd.DataFrame(columns=["realized_pnl"])
        equity_df = pd.DataFrame(columns=["ts_event", "equity"])
        return _compute_metrics(
            trades_df=trades_df,
            equity_df=equity_df,
            profile=profile,  # type: ignore[arg-type]
            starting_cash=1000.0,
        )

    def test_minimal_profile_key_set_stable(self) -> None:
        metrics = self._run_metrics("minimal")
        actual = frozenset(metrics.keys())
        assert actual == _EXPECTED_METRICS_MINIMAL_KEYS, (
            "minimal profile metrics keys changed. "
            "Update _EXPECTED_METRICS_MINIMAL_KEYS."
        )

    def test_pm_core_profile_key_set_stable(self) -> None:
        metrics = self._run_metrics("pm_core")
        actual = frozenset(metrics.keys())
        assert actual == _EXPECTED_METRICS_PM_CORE_KEYS, (
            "pm_core profile metrics keys changed. "
            "Update _EXPECTED_METRICS_PM_CORE_KEYS."
        )

    def test_default_profile_same_keys_as_pm_core(self) -> None:
        default_metrics = self._run_metrics("default")
        pm_core_metrics = self._run_metrics("pm_core")
        assert frozenset(default_metrics.keys()) == frozenset(pm_core_metrics.keys())

    def test_microstructure_profile_key_set_stable(self) -> None:
        metrics = self._run_metrics("microstructure")
        actual = frozenset(metrics.keys())
        assert actual == _EXPECTED_METRICS_MICROSTRUCTURE_KEYS, (
            "microstructure profile metrics keys changed. "
            "Update _EXPECTED_METRICS_MICROSTRUCTURE_KEYS."
        )

    def test_microstructure_is_superset_of_pm_core(self) -> None:
        """Microstructure must be backward-compatible with pm_core."""
        assert _EXPECTED_METRICS_PM_CORE_KEYS.issubset(_EXPECTED_METRICS_MICROSTRUCTURE_KEYS)

    def test_all_metrics_values_are_finite_floats(self) -> None:
        import math
        for profile in ("minimal", "pm_core", "default", "microstructure"):
            metrics = self._run_metrics(profile)
            for k, v in metrics.items():
                assert isinstance(v, float), f"{profile}/{k} must be float, got {type(v)}"
                assert math.isfinite(v), f"{profile}/{k} must be finite float, got {v}"

    def test_metrics_json_serialisable(self) -> None:
        for profile in ("minimal", "pm_core", "default", "microstructure"):
            metrics = self._run_metrics(profile)
            raw = json.dumps(metrics)  # must not raise
            parsed = json.loads(raw)
            assert "total_return" in parsed


# ---------------------------------------------------------------------------
# ExecutionReport schema
# ---------------------------------------------------------------------------


class TestExecutionReportSchema:
    def test_field_set_stable(self) -> None:
        actual = frozenset(ExecutionReport.model_fields.keys())
        assert actual == _EXPECTED_EXECUTION_REPORT_KEYS, (
            "ExecutionReport fields changed. Update _EXPECTED_EXECUTION_REPORT_KEYS."
        )

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            ExecutionReport(  # type: ignore[call-arg]
                order_id="x",
                instrument_id="p:m:yes",
                status=OrderLifecycleStatus.FILLED,
                source_intent=_limit_order(),
                unknown="bad",
            )

    def test_serialised_payload_keys_stable(self) -> None:
        report = ExecutionReport(
            order_id="ord001",
            instrument_id="p:m:yes",
            status=OrderLifecycleStatus.FILLED,
            fill_price=Decimal("0.62"),
            fill_size=Decimal("1"),
            fee=Decimal("0.001"),
            slippage=Decimal("0.0005"),
            source_intent=_limit_order(),
        )
        payload = report.model_dump(mode="json")
        actual_keys = frozenset(payload.keys())
        assert actual_keys == _EXPECTED_EXECUTION_REPORT_KEYS, (
            "ExecutionReport serialised keys changed. "
            "Update _EXPECTED_EXECUTION_REPORT_KEYS."
        )

    def test_report_json_serialisable(self) -> None:
        report = ExecutionReport(
            order_id="ord002",
            instrument_id="p:m:yes",
            status=OrderLifecycleStatus.CANCELLED,
            source_intent=_limit_order(),
        )
        raw = json.dumps(report.model_dump(mode="json"))
        parsed = json.loads(raw)
        assert parsed["order_id"] == "ord002"
        assert parsed["status"] == "cancelled"


# ---------------------------------------------------------------------------
# RunSummary payload (cross-check with test_run_manifest_schema.py)
# ---------------------------------------------------------------------------


class TestRunSummaryPayloadSchema:
    def test_serialised_payload_key_set_stable(self) -> None:
        s = _make_run_summary()
        payload = s.model_dump(mode="json")
        actual_keys = frozenset(payload.keys())
        assert actual_keys == _EXPECTED_RUN_SUMMARY_PAYLOAD_KEYS, (
            "RunSummary serialised keys changed. "
            "Update _EXPECTED_RUN_SUMMARY_PAYLOAD_KEYS."
        )

    def test_traceability_fields_populated(self) -> None:
        """Core traceability fields must not be None for a completed run."""
        s = _make_run_summary()
        assert s.run_id is not None and s.run_id != ""
        assert s.run_type is not None and s.run_type != ""
        assert s.status is not None
        assert s.config_hash is not None
        assert s.git_commit is not None
        assert s.started_at_utc is not None
        assert s.completed_at_utc is not None

    def test_planned_run_has_nullable_completion(self) -> None:
        """A planned run has no completed_at_utc."""
        s = RunSummary(
            run_id="plan1",
            run_type="backtest",
            status="planned",
            completed_at_utc=None,
        )
        assert s.completed_at_utc is None
        payload = s.model_dump(mode="json")
        assert payload["completed_at_utc"] is None

    def test_extra_dict_is_json_safe(self) -> None:
        s = _make_run_summary(extra={"n": 42, "ratio": 1.5, "label": "test"})
        raw = json.dumps(s.model_dump(mode="json"))
        parsed = json.loads(raw)
        assert parsed["extra"]["n"] == 42
        assert parsed["extra"]["ratio"] == 1.5

    def test_artifact_keys_sorted(self) -> None:
        ctx = RunContext(
            run_id="rc1",
            run_type="backtest",
            config_hash="h",
            started_at_utc=datetime.now(tz=UTC),
        )
        s = RunSummary.from_run_context(
            ctx,
            status="materialized",
            artifact_keys=["manifest", "config", "trades"],  # unsorted input
        )
        assert s.artifact_keys == sorted(["manifest", "config", "trades"])

    def test_from_run_context_round_trip(self) -> None:
        ctx = RunContext(
            run_id="rc2",
            run_type="live",
            config_hash="deadbeef0123",
            git_commit="abcdef1",
            started_at_utc=datetime(2026, 3, 7, 8, 0, 0, tzinfo=UTC),
            completed_at_utc=datetime(2026, 3, 7, 8, 5, 0, tzinfo=UTC),
        )
        s = RunSummary.from_run_context(
            ctx,
            status="materialized",
            artifact_keys=["config", "live_summary", "manifest"],
            extra={"strategy_id": "default", "cycles": 5},
        )
        payload = s.model_dump(mode="json")
        restored = RunSummary.model_validate(payload)
        assert restored.run_id == "rc2"
        assert restored.config_hash == "deadbeef0123"
        assert restored.git_commit == "abcdef1"
        assert restored.extra["cycles"] == 5


# ---------------------------------------------------------------------------
# Live CLI summary shape (integration with live_system/main.py contract)
# ---------------------------------------------------------------------------


class TestLiveCLISummaryContract:
    """Verify the shape of RunSummary emitted by apps/live_system/main.py."""

    def test_live_summary_run_type_is_live(self) -> None:
        s = RunSummary(
            run_id="live1",
            run_type="live",
            status="planned",
            extra={"strategy_id": "default", "cycles": 1, "orders_emitted": 0},
        )
        assert s.run_type == "live"

    def test_live_summary_extra_has_required_keys(self) -> None:
        """The live run command must include strategy_id, cycles, and orders_emitted in extra."""
        s = RunSummary(
            run_id="live2",
            run_type="live",
            status="materialized",
            config_hash="abc",
            extra={"strategy_id": "my_strat", "cycles": 3, "orders_emitted": 6},
        )
        assert "strategy_id" in s.extra
        assert "cycles" in s.extra
        assert "orders_emitted" in s.extra

    def test_live_summary_json_contains_all_traceability_keys(self) -> None:
        s = RunSummary(
            run_id="live3",
            run_type="live",
            status="planned",
            config_hash="h",
        )
        payload = s.model_dump(mode="json")
        for key in ("run_id", "run_type", "status", "config_hash", "summary_version"):
            assert key in payload
