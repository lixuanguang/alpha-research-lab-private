"""Integration tests for the live system: dry-run and mocked-adapter paths (LA-013).

Coverage:
- Full signal → intent → pre-trade validation → execution report pipeline
  using only in-process mocks — no network, no venue API, no clock dependency.
- Tests verify both accepted and rejected order scenarios.
- All assertions are structural (counts, types, field values); no sleep/time waits.

No external resources are required; tests are safe to run in CI / offline mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

import alpha_core.strategy_framework.interfaces as strategy_interfaces
import alpha_core.strategy_framework.models as strategy_models
from alpha_core.execution.order_models import (
    ExecutionReport,
    OrderLifecycleStatus,
    RejectReasonCode,
    ValidatedOrder,
)
from alpha_core.execution.pretrade import PreTradeConfig, PreTradeValidator
from alpha_core.execution.simulator import FillConfig, FillSimulator
from apps.live_system.order_router import (
    OrderRouter,
    RoutingResult,
    SubmissionResult,
    VenueAdapter,
)
from apps.live_system.runtime import (
    CycleResult,
    LiveRuntime,
    LiveRuntimeConfig,
    RuntimeMetrics,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_INST_YES = "p:mkt1:yes"
_INST_NO = "p:mkt1:no"
_INSTRUMENTS = [_INST_YES, _INST_NO]


def _market_state(
    instruments: list[str] | None = None,
) -> strategy_models.MarketState:
    return strategy_models.MarketState(
        as_of_utc=datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC),
        universe=instruments or _INSTRUMENTS,
    )


# ---------------------------------------------------------------------------
# Mock venue adapters
# ---------------------------------------------------------------------------


@dataclass
class RecordingAdapter:
    """Accepts every order and records the submission for later assertion."""

    adapter_name: str = "mock_accept"
    submitted: list[strategy_models.OrderIntent] = field(default_factory=list)
    order_counter: int = 0

    def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
        self.order_counter += 1
        self.submitted.append(order)
        return SubmissionResult(
            order_id=f"mock_{order.instrument_id}_{self.order_counter}",
            accepted=True,
        )

    def cancel(self, order_id: str) -> bool:
        return True

    def adapter_id(self) -> str:
        return self.adapter_name


@dataclass
class RejectingAdapter:
    """Rejects every order with a venue-side reason."""

    adapter_name: str = "mock_reject"
    reject_reason: str = "venue_liquidity_insufficient"

    def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
        return SubmissionResult(
            order_id=order.instrument_id,
            accepted=False,
            reject_reason=self.reject_reason,
        )

    def cancel(self, order_id: str) -> bool:
        return False

    def adapter_id(self) -> str:
        return self.adapter_name


@dataclass
class ExplodingAdapter:
    """Raises on every submit call — simulates adapter infrastructure failure."""

    adapter_name: str = "mock_explode"

    def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
        raise RuntimeError("connection refused: venue unreachable")

    def cancel(self, order_id: str) -> bool:
        raise RuntimeError("connection refused")

    def adapter_id(self) -> str:
        return self.adapter_name


# ---------------------------------------------------------------------------
# Custom strategy components for deterministic testing
# ---------------------------------------------------------------------------


class _FixedLimitExecution:
    """Emits LIMIT orders at a fixed price — makes pre-trade outcomes predictable."""

    def __init__(
        self,
        price: str = "0.60",
        size: str = "2",
    ) -> None:
        self._price = Decimal(price)
        self._size = Decimal(size)

    def create_orders(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.OrderIntent]:
        del state
        return [
            strategy_models.OrderIntent(
                instrument_id=target.instrument_id,
                order_type=strategy_models.OrderType.LIMIT,
                direction=target.direction,
                size=self._size,
                price_limit=self._price,
            )
            for target in targets
        ]


class _MarketExecution:
    """Emits MARKET orders (used to trigger MARKET_ORDER_NOT_ALLOWED rejection)."""

    def __init__(self, size: str = "1") -> None:
        self._size = Decimal(size)

    def create_orders(
        self,
        targets: list[strategy_models.Target],
        state: strategy_models.MarketState,
    ) -> list[strategy_models.OrderIntent]:
        del state
        return [
            strategy_models.OrderIntent(
                instrument_id=target.instrument_id,
                order_type=strategy_models.OrderType.MARKET,
                direction=target.direction,
                size=self._size,
            )
            for target in targets
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def recording_adapter() -> RecordingAdapter:
    return RecordingAdapter()


@pytest.fixture()
def limit_runtime() -> LiveRuntime:
    """Runtime that emits LIMIT orders at 0.60 — always passes default pre-trade config."""
    cfg = LiveRuntimeConfig(
        instruments=_INSTRUMENTS,
        execution_model=_FixedLimitExecution(price="0.60", size="2"),
    )
    rt = LiveRuntime(cfg)
    rt.startup()
    yield rt
    rt.shutdown()


@pytest.fixture()
def market_runtime() -> LiveRuntime:
    """Runtime that emits MARKET orders — blocked by pre-trade when allow_market_orders=False."""
    cfg = LiveRuntimeConfig(
        instruments=_INSTRUMENTS,
        execution_model=_MarketExecution(size="1"),
    )
    rt = LiveRuntime(cfg)
    rt.startup()
    yield rt
    rt.shutdown()


@pytest.fixture()
def permissive_validator() -> PreTradeValidator:
    return PreTradeValidator(PreTradeConfig(allow_market_orders=True))


@pytest.fixture()
def strict_validator() -> PreTradeValidator:
    """Blocks MARKET orders."""
    return PreTradeValidator(PreTradeConfig(allow_market_orders=False))


# ---------------------------------------------------------------------------
# 1. LiveRuntime lifecycle — no network
# ---------------------------------------------------------------------------


class TestLiveRuntimeLifecycle:
    def test_startup_marks_runtime_running(self) -> None:
        rt = LiveRuntime()
        assert not rt.is_running
        rt.startup()
        assert rt.is_running
        rt.shutdown()

    def test_shutdown_marks_runtime_stopped(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        rt.shutdown()
        assert not rt.is_running

    def test_step_raises_before_startup(self) -> None:
        rt = LiveRuntime()
        with pytest.raises(RuntimeError, match="must be started"):
            rt.step(_market_state())

    def test_startup_idempotent(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        rt.startup()  # second call is a no-op
        rt.shutdown()

    def test_shutdown_idempotent(self) -> None:
        rt = LiveRuntime()
        rt.startup()
        rt.shutdown()
        rt.shutdown()  # second call is a no-op

    def test_metrics_started_at_set_on_startup(self) -> None:
        before = datetime.now(tz=UTC)
        rt = LiveRuntime()
        rt.startup()
        after = datetime.now(tz=UTC)
        assert rt.metrics.started_at is not None
        assert before <= rt.metrics.started_at <= after
        rt.shutdown()

    def test_step_returns_cycle_result(self, limit_runtime: LiveRuntime) -> None:
        result = limit_runtime.step(_market_state())
        assert isinstance(result, CycleResult)

    def test_step_increments_cycle_counter(self, limit_runtime: LiveRuntime) -> None:
        limit_runtime.step(_market_state())
        assert limit_runtime.metrics.cycles_completed == 1

    def test_step_cycle_index_monotonic(self, limit_runtime: LiveRuntime) -> None:
        r1 = limit_runtime.step(_market_state())
        r2 = limit_runtime.step(_market_state())
        assert r2.cycle_index == r1.cycle_index + 1

    def test_step_emits_orders_for_every_instrument(
        self, limit_runtime: LiveRuntime
    ) -> None:
        result = limit_runtime.step(_market_state())
        assert len(result.orders) == len(_INSTRUMENTS)
        instrument_ids = {o.instrument_id for o in result.orders}
        assert instrument_ids == set(_INSTRUMENTS)

    def test_metrics_snapshot_in_cycle_result(self, limit_runtime: LiveRuntime) -> None:
        result = limit_runtime.step(_market_state())
        snap = result.metrics_snapshot
        assert "cycles_completed" in snap
        assert "total_orders" in snap


# ---------------------------------------------------------------------------
# 2. Dry-run path — no adapter, no network
# ---------------------------------------------------------------------------


class TestOrderRouterDryRun:
    def test_dry_run_accepts_all_orders(self, recording_adapter: RecordingAdapter) -> None:
        router = OrderRouter(recording_adapter, dry_run=True)
        orders = [
            strategy_models.OrderIntent(
                instrument_id=_INST_YES,
                order_type=strategy_models.OrderType.LIMIT,
                direction=strategy_models.SignalDirection.LONG,
                size=Decimal("1"),
                price_limit=Decimal("0.50"),
            ),
            strategy_models.OrderIntent(
                instrument_id=_INST_NO,
                order_type=strategy_models.OrderType.LIMIT,
                direction=strategy_models.SignalDirection.SHORT,
                size=Decimal("1"),
                price_limit=Decimal("0.50"),
            ),
        ]
        result = router.route(orders, _market_state())
        assert result.total == 2
        assert result.accepted == 2
        assert result.rejected == 0

    def test_dry_run_does_not_reach_adapter(
        self, recording_adapter: RecordingAdapter
    ) -> None:
        router = OrderRouter(recording_adapter, dry_run=True)
        order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.55"),
        )
        router.route([order], _market_state())
        assert recording_adapter.submitted == []

    def test_dry_run_order_id_is_dry_run_sentinel(
        self, recording_adapter: RecordingAdapter
    ) -> None:
        router = OrderRouter(recording_adapter, dry_run=True)
        order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.50"),
        )
        result = router.route([order], _market_state())
        assert result.details[0].order_id == "dry_run"

    def test_dry_run_with_validator_still_fires_pretrade(
        self, recording_adapter: RecordingAdapter, strict_validator: PreTradeValidator
    ) -> None:
        """Pre-trade rejection happens *before* the dry_run path."""
        router = OrderRouter(recording_adapter, dry_run=True, validator=strict_validator)
        market_order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.MARKET,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
        )
        result = router.route([market_order], _market_state())
        assert result.pretrade_rejected == 1
        assert result.accepted == 0
        assert recording_adapter.submitted == []


# ---------------------------------------------------------------------------
# 3. LiveRuntime → OrderRouter — accepted scenario
# ---------------------------------------------------------------------------


class TestLiveRuntimeToRouterAccepted:
    def test_full_cycle_all_orders_accepted(
        self,
        limit_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
        permissive_validator: PreTradeValidator,
    ) -> None:
        router = OrderRouter(recording_adapter, validator=permissive_validator)
        state = _market_state()
        cycle = limit_runtime.step(state)
        result = router.route(cycle.orders, state)

        assert result.accepted == len(_INSTRUMENTS)
        assert result.rejected == 0
        assert result.pretrade_rejected == 0

    def test_accepted_orders_reach_adapter(
        self,
        limit_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
        permissive_validator: PreTradeValidator,
    ) -> None:
        router = OrderRouter(recording_adapter, validator=permissive_validator)
        state = _market_state()
        cycle = limit_runtime.step(state)
        router.route(cycle.orders, state)
        assert len(recording_adapter.submitted) == len(_INSTRUMENTS)

    def test_routing_details_contain_instrument_ids(
        self,
        limit_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
    ) -> None:
        router = OrderRouter(recording_adapter)
        state = _market_state()
        cycle = limit_runtime.step(state)
        result = router.route(cycle.orders, state)
        detail_instruments = {d.instrument_id for d in result.details}
        assert detail_instruments == set(_INSTRUMENTS)

    def test_multi_cycle_metrics_accumulate(
        self,
        limit_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
    ) -> None:
        router = OrderRouter(recording_adapter)
        state = _market_state()
        for _ in range(3):
            cycle = limit_runtime.step(state)
            router.route(cycle.orders, state)

        assert router.total_routed == 3 * len(_INSTRUMENTS)
        assert router.total_accepted == 3 * len(_INSTRUMENTS)
        assert limit_runtime.metrics.cycles_completed == 3


# ---------------------------------------------------------------------------
# 4. LiveRuntime → OrderRouter — pre-trade rejected scenario
# ---------------------------------------------------------------------------


class TestLiveRuntimeToRouterRejected:
    def test_market_orders_rejected_by_strict_validator(
        self,
        market_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
        strict_validator: PreTradeValidator,
    ) -> None:
        router = OrderRouter(recording_adapter, validator=strict_validator)
        state = _market_state()
        cycle = market_runtime.step(state)
        result = router.route(cycle.orders, state)

        assert result.pretrade_rejected == len(_INSTRUMENTS)
        assert result.accepted == 0
        assert recording_adapter.submitted == []

    def test_rejected_routing_records_have_pretrade_flag(
        self,
        market_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
        strict_validator: PreTradeValidator,
    ) -> None:
        router = OrderRouter(recording_adapter, validator=strict_validator)
        state = _market_state()
        cycle = market_runtime.step(state)
        result = router.route(cycle.orders, state)
        for detail in result.details:
            assert detail.pretrade_rejected is True
            assert detail.accepted is False
            assert "pretrade:" in (detail.reject_reason or "")

    def test_rejected_routing_records_contain_reject_code(
        self,
        market_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
        strict_validator: PreTradeValidator,
    ) -> None:
        router = OrderRouter(recording_adapter, validator=strict_validator)
        state = _market_state()
        cycle = market_runtime.step(state)
        result = router.route(cycle.orders, state)
        for detail in result.details:
            assert RejectReasonCode.MARKET_ORDER_NOT_ALLOWED.value in (
                detail.reject_reason or ""
            )

    def test_cumulative_pretrade_counter_across_cycles(
        self,
        market_runtime: LiveRuntime,
        recording_adapter: RecordingAdapter,
        strict_validator: PreTradeValidator,
    ) -> None:
        router = OrderRouter(recording_adapter, validator=strict_validator)
        state = _market_state()
        for _ in range(2):
            cycle = market_runtime.step(state)
            router.route(cycle.orders, state)

        assert router.total_pretrade_rejected == 2 * len(_INSTRUMENTS)

    def test_venue_rejected_orders_not_counted_as_pretrade(
        self, recording_adapter: RecordingAdapter
    ) -> None:
        rejecting = RejectingAdapter()
        router = OrderRouter(rejecting)
        order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.50"),
        )
        result = router.route([order], _market_state())
        assert result.pretrade_rejected == 0
        assert result.rejected == 1
        assert result.details[0].pretrade_rejected is False


# ---------------------------------------------------------------------------
# 5. Signal → intent → validation → execution report (full pipeline)
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_accepted_path_produces_filled_report(
        self,
        limit_runtime: LiveRuntime,
        permissive_validator: PreTradeValidator,
    ) -> None:
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0")))
        state = _market_state()
        cycle = limit_runtime.step(state)

        reports: list[ExecutionReport] = []
        for order in cycle.orders:
            validated = permissive_validator.validate(order, state=state)
            report = sim.simulate(validated)
            reports.append(report)

        assert all(r.status == OrderLifecycleStatus.FILLED for r in reports)
        assert all(r.fill_price is not None for r in reports)
        assert len(reports) == len(_INSTRUMENTS)

    def test_rejected_path_produces_cancelled_report(
        self,
        market_runtime: LiveRuntime,
        strict_validator: PreTradeValidator,
    ) -> None:
        sim = FillSimulator()
        state = _market_state()
        cycle = market_runtime.step(state)

        reports: list[ExecutionReport] = []
        for order in cycle.orders:
            validated = strict_validator.validate(order, state=state)
            report = sim.simulate(validated)
            reports.append(report)

        assert all(r.status == OrderLifecycleStatus.CANCELLED for r in reports)
        assert all(r.fill_price is None for r in reports)

    def test_execution_reports_are_json_serialisable(
        self,
        limit_runtime: LiveRuntime,
        permissive_validator: PreTradeValidator,
    ) -> None:
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0")))
        state = _market_state()
        cycle = limit_runtime.step(state)

        for order in cycle.orders:
            validated = permissive_validator.validate(order, state=state)
            report = sim.simulate(validated)
            payload = report.model_dump(mode="json")
            raw = json.dumps(payload)  # must not raise
            parsed = json.loads(raw)
            assert parsed["status"] == "filled"
            assert parsed["instrument_id"] == order.instrument_id

    def test_mixed_batch_correct_accepted_and_rejected_counts(
        self, recording_adapter: RecordingAdapter
    ) -> None:
        """Limit orders pass; market orders fail — both in the same batch."""
        strict = PreTradeValidator(PreTradeConfig(allow_market_orders=False))
        router = OrderRouter(recording_adapter, validator=strict)

        limit_order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.55"),
        )
        market_order = strategy_models.OrderIntent(
            instrument_id=_INST_NO,
            order_type=strategy_models.OrderType.MARKET,
            direction=strategy_models.SignalDirection.SHORT,
            size=Decimal("1"),
        )

        result = router.route([limit_order, market_order], _market_state())
        assert result.accepted == 1
        assert result.pretrade_rejected == 1
        assert result.total == 2
        assert len(recording_adapter.submitted) == 1
        assert recording_adapter.submitted[0].instrument_id == _INST_YES


# ---------------------------------------------------------------------------
# 6. Adapter error handling — infrastructure failures
# ---------------------------------------------------------------------------


class TestAdapterErrorHandling:
    def test_exploding_adapter_counted_as_errors(self) -> None:
        router = OrderRouter(ExplodingAdapter())
        order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.50"),
        )
        result = router.route([order], _market_state())
        assert result.errors == 1
        assert result.accepted == 0
        assert result.pretrade_rejected == 0

    def test_one_error_does_not_block_rest_of_batch(
        self, recording_adapter: RecordingAdapter
    ) -> None:
        """First order explodes; second should still be submitted."""

        class _ExplodeFirstAdapter:
            _call_count = 0

            def submit(self, order: strategy_models.OrderIntent) -> SubmissionResult:
                self._call_count += 1
                if self._call_count == 1:
                    raise RuntimeError("transient error on first order")
                return SubmissionResult(order_id="ok", accepted=True)

            def cancel(self, order_id: str) -> bool:
                return True

            def adapter_id(self) -> str:
                return "explode_first"

        adapter = _ExplodeFirstAdapter()
        router = OrderRouter(adapter)  # type: ignore[arg-type]
        orders = [
            strategy_models.OrderIntent(
                instrument_id=_INST_YES,
                order_type=strategy_models.OrderType.LIMIT,
                direction=strategy_models.SignalDirection.LONG,
                size=Decimal("1"),
                price_limit=Decimal("0.50"),
            ),
            strategy_models.OrderIntent(
                instrument_id=_INST_NO,
                order_type=strategy_models.OrderType.LIMIT,
                direction=strategy_models.SignalDirection.LONG,
                size=Decimal("1"),
                price_limit=Decimal("0.50"),
            ),
        ]
        result = router.route(orders, _market_state())
        assert result.errors == 1
        assert result.accepted == 1


# ---------------------------------------------------------------------------
# 7. Deterministic output / log summary assertions (no timing dependency)
# ---------------------------------------------------------------------------


class TestDeterministicSummary:
    def test_routing_result_is_json_serialisable(
        self, limit_runtime: LiveRuntime, recording_adapter: RecordingAdapter
    ) -> None:
        router = OrderRouter(recording_adapter)
        state = _market_state()
        cycle = limit_runtime.step(state)
        result = router.route(cycle.orders, state)

        summary = {
            "adapter_id": result.adapter_id,
            "total": result.total,
            "accepted": result.accepted,
            "rejected": result.rejected,
            "pretrade_rejected": result.pretrade_rejected,
            "errors": result.errors,
            "routed_at": result.routed_at.isoformat(),
        }
        raw = json.dumps(summary)
        parsed = json.loads(raw)
        assert parsed["accepted"] == len(_INSTRUMENTS)
        assert parsed["rejected"] == 0

    def test_metrics_dict_serialisable(self, limit_runtime: LiveRuntime) -> None:
        limit_runtime.step(_market_state())
        snap = limit_runtime.metrics.as_dict()
        raw = json.dumps(snap)
        parsed = json.loads(raw)
        assert parsed["cycles_completed"] == 1
        assert parsed["total_orders"] == len(_INSTRUMENTS)

    def test_same_config_same_order_count_across_cycles(
        self, limit_runtime: LiveRuntime
    ) -> None:
        """Determinism check: every cycle with the same state emits the same number
        of orders for the same universe."""
        counts = set()
        state = _market_state()
        for _ in range(5):
            cycle = limit_runtime.step(state)
            counts.add(len(cycle.orders))
        assert counts == {len(_INSTRUMENTS)}

    def test_no_side_effects_between_two_runtimes(self) -> None:
        """Two independent LiveRuntime instances share no state."""
        cfg_a = LiveRuntimeConfig(
            instruments=[_INST_YES],
            execution_model=_FixedLimitExecution(price="0.60"),
        )
        cfg_b = LiveRuntimeConfig(
            instruments=[_INST_NO],
            execution_model=_FixedLimitExecution(price="0.40"),
        )
        rt_a = LiveRuntime(cfg_a)
        rt_b = LiveRuntime(cfg_b)
        rt_a.startup()
        rt_b.startup()

        state_a = _market_state([_INST_YES])
        state_b = _market_state([_INST_NO])

        result_a = rt_a.step(state_a)
        result_b = rt_b.step(state_b)

        assert result_a.orders[0].instrument_id == _INST_YES
        assert result_b.orders[0].instrument_id == _INST_NO
        assert result_a.orders[0].price_limit == Decimal("0.60")
        assert result_b.orders[0].price_limit == Decimal("0.40")

        rt_a.shutdown()
        rt_b.shutdown()

    def test_routing_result_all_accepted_property(
        self, limit_runtime: LiveRuntime, recording_adapter: RecordingAdapter
    ) -> None:
        router = OrderRouter(recording_adapter)
        state = _market_state()
        cycle = limit_runtime.step(state)
        result = router.route(cycle.orders, state)
        assert result.all_accepted


# ---------------------------------------------------------------------------
# 8. CI / offline guard — no sockets opened
# ---------------------------------------------------------------------------


class TestNoNetworkDependency:
    def test_live_runtime_step_opens_no_sockets(
        self, limit_runtime: LiveRuntime
    ) -> None:
        """Smoke-test: if this passes offline the runtime is network-free.

        There is no explicit socket patching — this test simply exercises the
        full step() path and confirms it completes without ImportError or
        connection errors.  Real network guard is enforced by running the suite
        with the network interface disabled in CI.
        """
        result = limit_runtime.step(_market_state())
        assert isinstance(result, CycleResult)

    def test_order_router_dry_run_offline(self, recording_adapter: RecordingAdapter) -> None:
        router = OrderRouter(recording_adapter, dry_run=True)
        order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.55"),
        )
        result = router.route([order], _market_state())
        assert result.accepted == 1
        assert recording_adapter.submitted == []

    def test_pretrade_validator_offline(self, permissive_validator: PreTradeValidator) -> None:
        order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.55"),
        )
        result = permissive_validator.validate(order)
        assert result.is_valid

    def test_fill_simulator_offline(self, permissive_validator: PreTradeValidator) -> None:
        order = strategy_models.OrderIntent(
            instrument_id=_INST_YES,
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("1"),
            price_limit=Decimal("0.55"),
        )
        validated = permissive_validator.validate(order)
        sim = FillSimulator(FillConfig(slippage_bps=Decimal("0"), fee_bps=Decimal("0")))
        report = sim.simulate(validated)
        assert report.status == OrderLifecycleStatus.FILLED
