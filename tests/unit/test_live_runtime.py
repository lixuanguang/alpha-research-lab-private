"""Unit tests for live runtime and order router (LA-011).

Covers:
- LiveRuntime lifecycle: startup / step / shutdown
- RuntimeMetrics accumulation
- Strategy component injection (shared with backtest contracts)
- CycleResult schema
- OrderRouter: dry_run mode, normal routing, per-order rejection, adapter errors
- VenueAdapter Protocol conformance
- LiveRuntime step() raises on unstarted runtime
- CLI --help surface exposes expected commands/flags
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import apps.live_system.main as live_main
import click.testing
import pytest
from apps.live_system.order_router import (
    OrderRouter,
    SubmissionResult,
    VenueAdapter,
)
from apps.live_system.runtime import (
    CycleResult,
    LiveRuntime,
    LiveRuntimeConfig,
)

from alpha_core.strategy_framework import models as strategy_models

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

_INSTRUMENT_A = "p:m1:yes"
_INSTRUMENT_B = "p:m1:no"


def _make_state(*instruments: str) -> strategy_models.MarketState:
    return strategy_models.MarketState(
        as_of_utc=datetime.now(tz=UTC),
        universe=list(instruments),
    )


# ---------------------------------------------------------------------------
# Mock strategy components
# ---------------------------------------------------------------------------


class FixedSignalAlpha:
    """Alpha that emits one LONG signal per instrument in the state universe."""

    def __init__(self, strength: Decimal = Decimal("0.8")) -> None:
        self._strength = strength
        self.call_count = 0

    def generate(self, state: strategy_models.MarketState) -> list[strategy_models.Signal]:
        self.call_count += 1
        return [
            strategy_models.Signal(
                instrument_id=iid,
                direction=strategy_models.SignalDirection.LONG,
                strength=self._strength,
                confidence=Decimal("0.9"),
            )
            for iid in state.universe
        ]


class HalfWeightPortfolio:
    """Portfolio that weights every signal at 0.5 regardless of count."""

    def targets(
        self,
        signals: list[strategy_models.Signal],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]:
        del state
        return [
            strategy_models.Target(
                instrument_id=s.instrument_id,
                target_weight=Decimal("0.5"),
                direction=s.direction,
            )
            for s in signals
        ]


class NullRisk:
    """Risk model that passes all targets through unchanged."""

    def apply(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]:
        del state
        return targets


class DropAllRisk:
    """Risk model that rejects all targets."""

    def apply(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.Target]:
        del state
        return []


# ---------------------------------------------------------------------------
# Mock venue adapters
# ---------------------------------------------------------------------------


class AlwaysAcceptAdapter:
    """Adapter that accepts every order."""

    def __init__(self) -> None:
        self.submitted: list[strategy_models.OrderIntent] = []

    def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
        self.submitted.append(order)
        return SubmissionResult(order_id=f"ord_{order.instrument_id}", accepted=True)

    def cancel(self, order_id: str) -> bool:
        return True

    def adapter_id(self) -> str:
        return "mock_accept"


class AlwaysRejectAdapter:
    """Adapter that rejects every order."""

    def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
        return SubmissionResult(
            order_id=order.instrument_id,
            accepted=False,
            reject_reason="insufficient_liquidity",
        )

    def cancel(self, order_id: str) -> bool:
        return False

    def adapter_id(self) -> str:
        return "mock_reject"


class RaisingAdapter:
    """Adapter that raises on submit."""

    def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
        raise ConnectionError("venue unreachable")

    def cancel(self, order_id: str) -> bool:
        return False

    def adapter_id(self) -> str:
        return "mock_raise"


# ---------------------------------------------------------------------------
# VenueAdapter protocol conformance
# ---------------------------------------------------------------------------


class TestVenueAdapterProtocol:
    def test_accept_adapter_satisfies_protocol(self) -> None:
        assert isinstance(AlwaysAcceptAdapter(), VenueAdapter)

    def test_reject_adapter_satisfies_protocol(self) -> None:
        assert isinstance(AlwaysRejectAdapter(), VenueAdapter)

    def test_raising_adapter_satisfies_protocol(self) -> None:
        assert isinstance(RaisingAdapter(), VenueAdapter)


# ---------------------------------------------------------------------------
# LiveRuntime lifecycle
# ---------------------------------------------------------------------------


class TestLiveRuntimeLifecycle:
    def test_not_running_before_startup(self) -> None:
        rt = LiveRuntime()
        assert not rt.is_running

    def test_running_after_startup(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        assert rt.is_running
        rt.shutdown()

    def test_not_running_after_shutdown(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        rt.shutdown()
        assert not rt.is_running

    def test_double_startup_is_idempotent(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        rt.startup()  # second call is a no-op
        assert rt.is_running
        rt.shutdown()

    def test_double_shutdown_is_idempotent(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        rt.shutdown()
        rt.shutdown()  # second call is a no-op
        assert not rt.is_running

    def test_step_before_startup_raises(self) -> None:
        rt = LiveRuntime()
        state = _make_state(_INSTRUMENT_A)
        with pytest.raises(RuntimeError, match="must be started"):
            rt.step(state)

    def test_step_after_shutdown_raises(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        rt.shutdown()
        state = _make_state(_INSTRUMENT_A)
        with pytest.raises(RuntimeError, match="must be started"):
            rt.step(state)


# ---------------------------------------------------------------------------
# LiveRuntime.step — default components
# ---------------------------------------------------------------------------


class TestLiveRuntimeStep:
    def test_default_components_emit_orders_for_instruments(self) -> None:
        config = LiveRuntimeConfig(instruments=[_INSTRUMENT_A, _INSTRUMENT_B])
        rt = LiveRuntime(config)
        rt.startup()
        state = _make_state(_INSTRUMENT_A, _INSTRUMENT_B)
        result = rt.step(state)
        rt.shutdown()
        assert isinstance(result, CycleResult)
        assert len(result.orders) == 2
        instrument_ids = {o.instrument_id for o in result.orders}
        assert instrument_ids == {_INSTRUMENT_A, _INSTRUMENT_B}

    def test_default_components_emit_market_orders(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A]))
        rt.startup()
        result = rt.step(_make_state(_INSTRUMENT_A))
        rt.shutdown()
        assert all(o.order_type == strategy_models.OrderType.MARKET for o in result.orders)

    def test_empty_universe_yields_no_orders(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[]))
        rt.startup()
        result = rt.step(_make_state())
        rt.shutdown()
        assert result.orders == []

    def test_cycle_index_increments(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A]))
        rt.startup()
        r1 = rt.step(_make_state(_INSTRUMENT_A))
        r2 = rt.step(_make_state(_INSTRUMENT_A))
        rt.shutdown()
        assert r1.cycle_index == 0
        assert r2.cycle_index == 1

    def test_result_contains_as_of_utc(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A]))
        rt.startup()
        state = _make_state(_INSTRUMENT_A)
        result = rt.step(state)
        rt.shutdown()
        assert result.as_of_utc == state.as_of_utc

    def test_result_contains_metrics_snapshot(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A]))
        rt.startup()
        result = rt.step(_make_state(_INSTRUMENT_A))
        rt.shutdown()
        snap = result.metrics_snapshot
        assert "cycles_completed" in snap
        assert "total_orders" in snap
        assert snap["cycles_completed"] == 1


# ---------------------------------------------------------------------------
# LiveRuntime — custom injected components
# ---------------------------------------------------------------------------


class TestLiveRuntimeInjection:
    def test_custom_alpha_model_used(self) -> None:
        alpha = FixedSignalAlpha(strength=Decimal("0.99"))
        config = LiveRuntimeConfig(
            instruments=[_INSTRUMENT_A],
            alpha_model=alpha,
        )
        rt = LiveRuntime(config)
        rt.startup()
        rt.step(_make_state(_INSTRUMENT_A))
        rt.shutdown()
        assert alpha.call_count == 1

    def test_drop_all_risk_yields_no_orders(self) -> None:
        config = LiveRuntimeConfig(
            instruments=[_INSTRUMENT_A, _INSTRUMENT_B],
            risk_model=DropAllRisk(),
        )
        rt = LiveRuntime(config)
        rt.startup()
        result = rt.step(_make_state(_INSTRUMENT_A, _INSTRUMENT_B))
        rt.shutdown()
        assert result.orders == []

    def test_strategy_components_satisfy_protocols(self) -> None:
        """Components used in backtest also satisfy live protocol interfaces."""
        from alpha_core.strategy_framework.interfaces import (
            AlphaModel,
            PortfolioConstructionModel,
            RiskModel,
        )

        assert isinstance(FixedSignalAlpha(), AlphaModel)
        assert isinstance(HalfWeightPortfolio(), PortfolioConstructionModel)
        assert isinstance(NullRisk(), RiskModel)
        assert isinstance(DropAllRisk(), RiskModel)


# ---------------------------------------------------------------------------
# RuntimeMetrics accumulation
# ---------------------------------------------------------------------------


class TestRuntimeMetrics:
    def test_metrics_count_cycles_and_orders(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A, _INSTRUMENT_B]))
        rt.startup()
        rt.step(_make_state(_INSTRUMENT_A, _INSTRUMENT_B))
        rt.step(_make_state(_INSTRUMENT_A, _INSTRUMENT_B))
        rt.shutdown()
        m = rt.metrics
        assert m.cycles_completed == 2
        assert m.total_orders == 4  # 2 per cycle

    def test_metrics_count_signals_and_targets(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A, _INSTRUMENT_B]))
        rt.startup()
        rt.step(_make_state(_INSTRUMENT_A, _INSTRUMENT_B))
        rt.shutdown()
        m = rt.metrics
        assert m.total_signals == 2
        assert m.total_targets == 2

    def test_metrics_started_at_set_on_startup(self) -> None:
        rt = LiveRuntime()
        before = datetime.now(tz=UTC)
        rt.startup()
        after = datetime.now(tz=UTC)
        assert rt.metrics.started_at is not None
        assert before <= rt.metrics.started_at <= after
        rt.shutdown()

    def test_metrics_last_cycle_at_updated(self) -> None:
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A]))
        rt.startup()
        rt.step(_make_state(_INSTRUMENT_A))
        assert rt.metrics.last_cycle_at is not None
        rt.shutdown()

    def test_metrics_as_dict_serializable(self) -> None:
        import json

        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A]))
        rt.startup()
        rt.step(_make_state(_INSTRUMENT_A))
        rt.shutdown()
        d = rt.metrics.as_dict()
        _ = json.dumps(d)  # must not raise
        assert isinstance(d["cycles_completed"], int)

    def test_error_count_increments_on_component_exception(self) -> None:
        class BrokenAlpha:
            def generate(self, state: strategy_models.MarketState) -> list[strategy_models.Signal]:
                raise RuntimeError("broken")

        config = LiveRuntimeConfig(
            instruments=[_INSTRUMENT_A],
            alpha_model=BrokenAlpha(),
        )
        rt = LiveRuntime(config)
        rt.startup()
        with pytest.raises(RuntimeError):
            rt.step(_make_state(_INSTRUMENT_A))
        rt.shutdown()
        assert rt.metrics.total_errors == 1


# ---------------------------------------------------------------------------
# OrderRouter — dry_run
# ---------------------------------------------------------------------------


class TestOrderRouterDryRun:
    def _make_order(self, iid: str = _INSTRUMENT_A) -> strategy_models.OrderIntent:
        return strategy_models.OrderIntent(
            instrument_id=iid,
            order_type=strategy_models.OrderType.MARKET,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
        )

    def test_dry_run_accepts_all_orders(self) -> None:
        router = OrderRouter(AlwaysRejectAdapter(), dry_run=True)
        orders = [self._make_order(_INSTRUMENT_A), self._make_order(_INSTRUMENT_B)]
        result = router.route(orders, _make_state())
        assert result.accepted == 2
        assert result.rejected == 0

    def test_dry_run_does_not_call_adapter(self) -> None:
        adapter = AlwaysAcceptAdapter()
        router = OrderRouter(adapter, dry_run=True)
        router.route([self._make_order()], _make_state())
        assert adapter.submitted == []

    def test_dry_run_order_id_is_dry_run(self) -> None:
        router = OrderRouter(AlwaysAcceptAdapter(), dry_run=True)
        result = router.route([self._make_order()], _make_state())
        assert result.details[0].order_id == "dry_run"


# ---------------------------------------------------------------------------
# OrderRouter — normal routing
# ---------------------------------------------------------------------------


class TestOrderRouterRouting:
    def _make_order(self, iid: str = _INSTRUMENT_A) -> strategy_models.OrderIntent:
        return strategy_models.OrderIntent(
            instrument_id=iid,
            order_type=strategy_models.OrderType.MARKET,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
        )

    def test_accept_adapter_all_accepted(self) -> None:
        adapter = AlwaysAcceptAdapter()
        router = OrderRouter(adapter)
        orders = [self._make_order(_INSTRUMENT_A), self._make_order(_INSTRUMENT_B)]
        result = router.route(orders, _make_state())
        assert result.total == 2
        assert result.accepted == 2
        assert result.rejected == 0
        assert result.errors == 0
        assert result.all_accepted

    def test_accept_adapter_submits_orders(self) -> None:
        adapter = AlwaysAcceptAdapter()
        router = OrderRouter(adapter)
        router.route([self._make_order()], _make_state())
        assert len(adapter.submitted) == 1
        assert adapter.submitted[0].instrument_id == _INSTRUMENT_A

    def test_reject_adapter_all_rejected(self) -> None:
        router = OrderRouter(AlwaysRejectAdapter())
        result = router.route([self._make_order()], _make_state())
        assert result.accepted == 0
        assert result.rejected == 1
        assert not result.all_accepted
        assert result.details[0].reject_reason == "insufficient_liquidity"

    def test_raising_adapter_counted_as_errors(self) -> None:
        router = OrderRouter(RaisingAdapter())
        result = router.route([self._make_order()], _make_state())
        assert result.errors == 1
        assert result.accepted == 0
        assert result.rejected == 0
        assert not result.all_accepted

    def test_routing_result_has_correct_adapter_id(self) -> None:
        router = OrderRouter(AlwaysAcceptAdapter())
        result = router.route([self._make_order()], _make_state())
        assert result.adapter_id == "mock_accept"

    def test_cumulative_metrics_across_batches(self) -> None:
        adapter = AlwaysAcceptAdapter()
        router = OrderRouter(adapter)
        router.route([self._make_order(_INSTRUMENT_A)], _make_state())
        router.route([self._make_order(_INSTRUMENT_B)], _make_state())
        assert router.total_routed == 2
        assert router.total_accepted == 2

    def test_empty_batch_returns_zero_counts(self) -> None:
        router = OrderRouter(AlwaysAcceptAdapter())
        result = router.route([], _make_state())
        assert result.total == 0
        assert result.accepted == 0
        assert result.all_accepted


# ---------------------------------------------------------------------------
# Integration: LiveRuntime + OrderRouter
# ---------------------------------------------------------------------------


class TestLiveRuntimeWithRouter:
    def test_runtime_orders_flow_through_router(self) -> None:
        """End-to-end: live runtime produces orders that router submits."""
        adapter = AlwaysAcceptAdapter()
        router = OrderRouter(adapter)
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A, _INSTRUMENT_B]))
        rt.startup()
        state = _make_state(_INSTRUMENT_A, _INSTRUMENT_B)
        cycle = rt.step(state)
        routing = router.route(cycle.orders, state)
        rt.shutdown()

        assert routing.accepted == len(cycle.orders)
        assert len(adapter.submitted) == len(cycle.orders)

    def test_runtime_and_router_share_order_types(self) -> None:
        """Orders produced by runtime are valid inputs to router (type compatibility)."""
        rt = LiveRuntime(LiveRuntimeConfig(instruments=[_INSTRUMENT_A]))
        rt.startup()
        cycle = rt.step(_make_state(_INSTRUMENT_A))
        rt.shutdown()
        for order in cycle.orders:
            assert isinstance(order, strategy_models.OrderIntent)
            assert isinstance(order.order_type, strategy_models.OrderType)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestLiveCliSurface:
    def test_help_shows_run_and_status_commands(self) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(live_main.main, ["--help"])
        assert result.exit_code == 0, result.output
        assert "run" in result.output
        assert "status" in result.output

    def test_run_help_shows_expected_options(self) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(live_main.main, ["run", "--help"])
        assert result.exit_code == 0
        for flag in ("--instrument", "--cycles", "--strategy-id", "--storage-root", "--execute"):
            assert flag in result.output, f"missing flag: {flag}"

    def test_run_plan_only_exits_zero(self, tmp_path: Path) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(
            live_main.main,
            [
                "run",
                "--instrument",
                _INSTRUMENT_A,
                "--storage-root",
                str(tmp_path),
                "--plan-only",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "status=planned" in result.output

    def test_run_execute_writes_manifest(self, tmp_path: Path) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(
            live_main.main,
            [
                "run",
                "--instrument",
                _INSTRUMENT_A,
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "status=materialized" in result.output
        assert "manifest=" in result.output
        manifest_line = next(
            line for line in result.output.splitlines() if line.startswith("manifest=")
        )
        manifest_path = Path(manifest_line.split("=", maxsplit=1)[1].strip())
        assert manifest_path.exists()

    def test_run_execute_persists_strategy_id_in_run_record(self, tmp_path: Path) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(
            live_main.main,
            [
                "run",
                "--instrument",
                _INSTRUMENT_A,
                "--strategy-id",
                "zscore_v1",
                "--storage-root",
                str(tmp_path),
                "--execute",
            ],
        )
        assert result.exit_code == 0, result.output
        manifest_line = next(
            line for line in result.output.splitlines() if line.startswith("manifest=")
        )
        manifest_path = Path(manifest_line.split("=", maxsplit=1)[1].strip())
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest_payload["artifacts"]["strategy_id"] == "zscore_v1"

        config_path = manifest_path.parent / "config.json"
        config_payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert config_payload["strategy_id"] == "zscore_v1"

    def test_run_with_zero_cycles_exits_nonzero(self, tmp_path: Path) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(
            live_main.main,
            ["run", "--cycles", "0", "--storage-root", str(tmp_path), "--execute"],
        )
        assert result.exit_code != 0

    def test_status_no_runs_shows_no_runs_found(self, tmp_path: Path) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(
            live_main.main,
            ["status", "--storage-root", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "No live runs found" in result.output

    def test_run_strategy_id_appears_in_output(self, tmp_path: Path) -> None:
        runner = click.testing.CliRunner()
        result = runner.invoke(
            live_main.main,
            [
                "run",
                "--instrument",
                _INSTRUMENT_A,
                "--strategy-id",
                "zscore_v1",
                "--storage-root",
                str(tmp_path),
                "--plan-only",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "zscore_v1" in result.output
