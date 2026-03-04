"""Unit tests for alpha_core.strategy_framework contracts and models.

Covers:
- Protocol interface compile-time contracts (runtime_checkable isinstance checks)
- Datamodel construction, validation, and serialization round-trips
- strategy_engine.StrategyEngine step() orchestration with minimal stub implementations
- Invalid-input rejection (extra="forbid", field bounds)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import alpha_core.strategy_framework.engine as strategy_engine
import alpha_core.strategy_framework.interfaces as strategy_interfaces
import alpha_core.strategy_framework.models as strategy_models

# ---------------------------------------------------------------------------
# Stub implementations used across multiple tests
# ---------------------------------------------------------------------------


class _PassthroughUniverse:
    """Returns universe unchanged."""

    def select(self, state: strategy_models.MarketState) -> list[str]:
        return state.universe


class _ConstantAlpha:
    """Always returns a single LONG signal for every instrument in the universe."""

    def generate(self, state: strategy_models.MarketState) -> list[strategy_models.Signal]:
        return [
            strategy_models.Signal(
                instrument_id=iid,
                direction=strategy_models.SignalDirection.LONG,
                strength=Decimal("0.8"),
                confidence=Decimal("0.9"),
            )
            for iid in state.universe
        ]


class _EqualWeightPortfolio:
    """Assigns equal target_weight to every signal."""

    def targets(
        self, signals: list[strategy_models.Signal], state: strategy_models.MarketState
    ) -> list[strategy_models.Target]:
        del state
        w = Decimal("1") / Decimal(len(signals)) if signals else Decimal("0")
        return [
            strategy_models.Target(
                instrument_id=s.instrument_id,
                target_weight=w,
                direction=s.direction,
            )
            for s in signals
        ]


class _PassthroughRisk:
    """Returns targets unchanged."""

    def apply(
        self, targets: list[strategy_models.Target], state: strategy_models.MarketState
    ) -> list[strategy_models.Target]:
        del state
        return targets


class _MarketOrderExecution:
    """Produces one MARKET strategy_models.OrderIntent per target."""

    def create_orders(
        self, targets: list[strategy_models.Target], state: strategy_models.MarketState
    ) -> list[strategy_models.OrderIntent]:
        del state
        return [
            strategy_models.OrderIntent(
                instrument_id=t.instrument_id,
                order_type=strategy_models.OrderType.MARKET,
                direction=t.direction,
                size=Decimal("10"),
            )
            for t in targets
        ]


def _make_engine() -> strategy_engine.StrategyEngine:
    return strategy_engine.StrategyEngine(
        universe=_PassthroughUniverse(),
        alpha=_ConstantAlpha(),
        portfolio=_EqualWeightPortfolio(),
        risk=_PassthroughRisk(),
        execution=_MarketOrderExecution(),
    )


def _make_state(*instrument_ids: str) -> strategy_models.MarketState:
    return strategy_models.MarketState(
        as_of_utc=datetime.now(tz=UTC),
        universe=list(instrument_ids),
    )


# ---------------------------------------------------------------------------
# Protocol interface checks
# ---------------------------------------------------------------------------


class TestProtocolInterfaces:
    def test_stub_universe_is_universe_model(self) -> None:
        assert isinstance(_PassthroughUniverse(), strategy_interfaces.UniverseModel)

    def test_stub_alpha_is_alpha_model(self) -> None:
        assert isinstance(_ConstantAlpha(), strategy_interfaces.AlphaModel)

    def test_stub_portfolio_is_portfolio_construction_model(self) -> None:
        assert isinstance(_EqualWeightPortfolio(), strategy_interfaces.PortfolioConstructionModel)

    def test_stub_risk_is_risk_model(self) -> None:
        assert isinstance(_PassthroughRisk(), strategy_interfaces.RiskModel)

    def test_stub_execution_is_execution_model(self) -> None:
        assert isinstance(_MarketOrderExecution(), strategy_interfaces.ExecutionModel)

    def test_non_conforming_object_is_not_universe_model(self) -> None:
        class _Bad:
            pass  # no select()

        assert not isinstance(_Bad(), strategy_interfaces.UniverseModel)


# ---------------------------------------------------------------------------
# strategy_models.MarketState and strategy_models.InstrumentState
# ---------------------------------------------------------------------------


class TestMarketState:
    def test_default_construction(self) -> None:
        state = strategy_models.MarketState()
        assert state.universe == []
        assert state.instruments == {}
        assert state.portfolio == {}
        assert state.as_of_utc.tzinfo is not None

    def test_construction_with_instrument_state(self) -> None:
        iid = "kalshi:abc:yes"
        inst = strategy_models.InstrumentState(
            instrument_id=iid,
            mid_price=Decimal("0.55"),
            best_bid=Decimal("0.54"),
            best_ask=Decimal("0.56"),
            volume_24h=Decimal("1000"),
        )
        state = strategy_models.MarketState(universe=[iid], instruments={iid: inst})
        assert state.instruments[iid].mid_price == Decimal("0.55")

    def test_extra_allow_on_market_state(self) -> None:
        """strategy_models.MarketState uses extra='allow' so subclasses/runtimes can attach data."""
        state = strategy_models.MarketState(custom_field="value")  # type: ignore[call-arg]
        assert state.model_extra == {"custom_field": "value"}

    def test_instrument_state_rejects_price_above_one(self) -> None:
        with pytest.raises(Exception):
            strategy_models.InstrumentState(instrument_id="k:m:o", mid_price=Decimal("1.01"))

    def test_instrument_state_extra_forbid(self) -> None:
        with pytest.raises(Exception):
            strategy_models.InstrumentState(instrument_id="k:m:o", unknown_field="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# strategy_models.Signal
# ---------------------------------------------------------------------------


class TestSignal:
    def test_valid_long_signal(self) -> None:
        sig = strategy_models.Signal(
            instrument_id="kalshi:abc:yes",
            direction=strategy_models.SignalDirection.LONG,
            strength=Decimal("1.0"),
            confidence=Decimal("0.75"),
        )
        assert sig.direction is strategy_models.SignalDirection.LONG

    def test_strength_below_zero_rejected(self) -> None:
        with pytest.raises(Exception):
            strategy_models.Signal(
                instrument_id="k:m:o",
                direction=strategy_models.SignalDirection.LONG,
                strength=Decimal("-0.01"),
                confidence=Decimal("0.5"),
            )

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(Exception):
            strategy_models.Signal(
                instrument_id="k:m:o",
                direction=strategy_models.SignalDirection.SHORT,
                strength=Decimal("0.5"),
                confidence=Decimal("1.01"),
            )

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(Exception):
            strategy_models.Signal(
                instrument_id="k:m:o",
                direction=strategy_models.SignalDirection.FLAT,
                strength=Decimal("0"),
                confidence=Decimal("0"),
                phantom_field=True,  # type: ignore[call-arg]
            )

    def test_serialization_round_trip(self) -> None:
        sig = strategy_models.Signal(
            instrument_id="polymarket:xyz:no",
            direction=strategy_models.SignalDirection.SHORT,
            strength=Decimal("0.6"),
            confidence=Decimal("0.8"),
            metadata={"model": "momentum_v1"},
        )
        restored = strategy_models.Signal.model_validate(sig.model_dump(mode="python"))
        assert restored.instrument_id == sig.instrument_id
        assert restored.strength == sig.strength
        assert restored.metadata["model"] == "momentum_v1"

    @pytest.mark.parametrize("direction", list(strategy_models.SignalDirection))
    def test_all_signal_directions_valid(self, direction: strategy_models.SignalDirection) -> None:
        sig = strategy_models.Signal(
            instrument_id="k:m:o",
            direction=direction,
            strength=Decimal("0.5"),
            confidence=Decimal("0.5"),
        )
        assert sig.direction == direction


# ---------------------------------------------------------------------------
# strategy_models.Target
# ---------------------------------------------------------------------------


class TestTarget:
    def test_weight_bounds(self) -> None:
        t = strategy_models.Target(
            instrument_id="k:m:o",
            target_weight=Decimal("-0.5"),
            direction=strategy_models.SignalDirection.SHORT,
        )
        assert t.target_weight == Decimal("-0.5")

    def test_weight_above_one_rejected(self) -> None:
        with pytest.raises(Exception):
            strategy_models.Target(instrument_id="k:m:o", target_weight=Decimal("1.01"))

    def test_size_negative_rejected(self) -> None:
        with pytest.raises(Exception):
            strategy_models.Target(instrument_id="k:m:o", target_size=Decimal("-1"))

    def test_default_direction_is_flat(self) -> None:
        t = strategy_models.Target(instrument_id="k:m:o")
        assert t.direction is strategy_models.SignalDirection.FLAT


# ---------------------------------------------------------------------------
# strategy_models.OrderIntent
# ---------------------------------------------------------------------------


class TestOrderIntent:
    def test_limit_order(self) -> None:
        oi = strategy_models.OrderIntent(
            instrument_id="kalshi:xyz:yes",
            order_type=strategy_models.OrderType.LIMIT,
            direction=strategy_models.SignalDirection.LONG,
            size=Decimal("5"),
            price_limit=Decimal("0.62"),
        )
        assert oi.order_type is strategy_models.OrderType.LIMIT
        assert oi.price_limit == Decimal("0.62")

    def test_size_must_be_positive(self) -> None:
        with pytest.raises(Exception):
            strategy_models.OrderIntent(
                instrument_id="k:m:o",
                direction=strategy_models.SignalDirection.LONG,
                size=Decimal("0"),
            )

    def test_price_limit_above_one_rejected(self) -> None:
        with pytest.raises(Exception):
            strategy_models.OrderIntent(
                instrument_id="k:m:o",
                direction=strategy_models.SignalDirection.LONG,
                size=Decimal("1"),
                price_limit=Decimal("1.1"),
            )

    def test_serialization_round_trip(self) -> None:
        oi = strategy_models.OrderIntent(
            instrument_id="limitless:abc:no",
            order_type=strategy_models.OrderType.MARKET,
            direction=strategy_models.SignalDirection.SHORT,
            size=Decimal("3"),
        )
        restored = strategy_models.OrderIntent.model_validate(oi.model_dump(mode="python"))
        assert restored.instrument_id == oi.instrument_id
        assert restored.size == oi.size


# ---------------------------------------------------------------------------
# strategy_engine.StrategyEngine
# ---------------------------------------------------------------------------


class TestStrategyEngine:
    def test_step_returns_orders(self) -> None:
        engine = _make_engine()
        state = _make_state("kalshi:a:yes", "polymarket:b:no")
        orders = engine.step(state)
        assert len(orders) == 2  # one order per instrument

    def test_step_increments_cycle_count(self) -> None:
        engine = _make_engine()
        state = _make_state("k:m:o")
        assert engine.cycle_count == 0
        engine.step(state)
        assert engine.cycle_count == 1
        engine.step(state)
        assert engine.cycle_count == 2

    def test_empty_universe_produces_no_orders(self) -> None:
        engine = _make_engine()
        state = _make_state()  # no instruments
        orders = engine.step(state)
        assert orders == []

    def test_universe_model_narrows_state(self) -> None:
        """strategy_interfaces.UniverseModel.select() should update state.universe."""

        class _FilterUniverse:
            def select(self, state: strategy_models.MarketState) -> list[str]:
                return [iid for iid in state.universe if "kalshi" in iid]

        engine = strategy_engine.StrategyEngine(
            universe=_FilterUniverse(),
            alpha=_ConstantAlpha(),
            portfolio=_EqualWeightPortfolio(),
            risk=_PassthroughRisk(),
            execution=_MarketOrderExecution(),
        )
        state = _make_state("kalshi:a:yes", "polymarket:b:no")
        orders = engine.step(state)
        assert len(orders) == 1
        assert orders[0].instrument_id == "kalshi:a:yes"

    def test_risk_model_can_drop_targets(self) -> None:
        """strategy_interfaces.RiskModel.apply() returning empty list produces no orders."""

        class _KillAllRisk:
            def apply(
                self, targets: list[strategy_models.Target], state: strategy_models.MarketState
            ) -> list[strategy_models.Target]:
                del targets, state
                return []

        engine = strategy_engine.StrategyEngine(
            universe=_PassthroughUniverse(),
            alpha=_ConstantAlpha(),
            portfolio=_EqualWeightPortfolio(),
            risk=_KillAllRisk(),
            execution=_MarketOrderExecution(),
        )
        orders = engine.step(_make_state("k:m:o"))
        assert orders == []

    def test_engine_repr_contains_component_names(self) -> None:
        engine = _make_engine()
        r = repr(engine)
        assert "universe" in r
        assert "alpha" in r
