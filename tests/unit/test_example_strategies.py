"""Unit tests for example research strategies.

Tests cover:
- ProbabilityMomentumStrategy: order generation on sample data, empty universe,
  threshold boundary, on_resolution cleanup.
- CrossVenueArbStrategy: multi-venue spread detection, below-threshold suppression,
  single-venue no-trade, position deduplication.
- MeanReversionStrategy: signal generation, z-score threshold, empty universe,
  no price-column fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
from apps.research.backtester.strategy import StrategyState
from apps.research.strategies.cross_venue_arb import CrossVenueArbStrategy
from apps.research.strategies.mean_reversion import MeanReversionStrategy
from apps.research.strategies.probability_momentum import ProbabilityMomentumStrategy

from alpha_core.portfolio.models import PortfolioState, Side

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_portfolio() -> PortfolioState:
    return PortfolioState(
        timestamp=_T0,
        cash=Decimal("10000"),
        positions={},
        total_fees=_ZERO,
        equity=Decimal("10000"),
    )


def _state(
    universe: list[str],
    prices: dict[str, float],
    portfolio: PortfolioState | None = None,
    features: dict[str, dict[str, float]] | None = None,
) -> StrategyState:
    return StrategyState(
        timestamp=_T0,
        portfolio=portfolio or _empty_portfolio(),
        latest_prices={k: Decimal(str(v)) for k, v in prices.items()},
        features=features,
        universe=universe,
    )


# ============================================================================
# ProbabilityMomentumStrategy
# ============================================================================


class TestProbabilityMomentumStrategy:
    def test_name_encodes_params(self) -> None:
        s = ProbabilityMomentumStrategy(momentum_threshold=0.05, window=10)
        assert "0.05" in s.name
        assert "10" in s.name

    def test_no_orders_before_window_fills(self) -> None:
        s = ProbabilityMomentumStrategy(momentum_threshold=0.01, window=5)
        s.on_init(["A"])
        universe = ["A"]
        for price in [0.5, 0.52, 0.54]:
            orders = s.on_data(_T0, _state(universe, {"A": price}))
        assert orders == []

    def test_long_order_on_positive_momentum(self) -> None:
        s = ProbabilityMomentumStrategy(momentum_threshold=0.01, window=2)
        s.on_init(["A"])
        universe = ["A"]
        # first event fills history[0]
        s.on_data(_T0, _state(universe, {"A": 0.40}))
        # second event: momentum = 0.50 - 0.40 = 0.10 > 0.01
        orders = s.on_data(_T0, _state(universe, {"A": 0.50}))
        assert len(orders) == 1
        assert orders[0].side == Side.LONG
        assert orders[0].instrument_id == "A"

    def test_short_order_on_negative_momentum(self) -> None:
        s = ProbabilityMomentumStrategy(momentum_threshold=0.01, window=2)
        s.on_init(["A"])
        universe = ["A"]
        s.on_data(_T0, _state(universe, {"A": 0.60}))
        orders = s.on_data(_T0, _state(universe, {"A": 0.40}))
        assert len(orders) == 1
        assert orders[0].side == Side.SHORT

    def test_no_order_below_threshold(self) -> None:
        s = ProbabilityMomentumStrategy(momentum_threshold=0.10, window=2)
        s.on_init(["A"])
        universe = ["A"]
        s.on_data(_T0, _state(universe, {"A": 0.50}))
        orders = s.on_data(_T0, _state(universe, {"A": 0.501}))
        assert orders == []

    def test_empty_universe_returns_no_orders(self) -> None:
        s = ProbabilityMomentumStrategy()
        s.on_init([])
        orders = s.on_data(_T0, _state([], {}))
        assert orders == []

    def test_on_resolution_clears_history(self) -> None:
        s = ProbabilityMomentumStrategy(momentum_threshold=0.01, window=2)
        s.on_init(["A"])
        s.on_data(_T0, _state(["A"], {"A": 0.5}))
        s.on_resolution("A", Decimal("1"))
        # After resolution history is cleared; next event can't produce a signal
        orders = s.on_data(_T0, _state(["A"], {"A": 0.7}))
        assert orders == []

    def test_does_not_duplicate_long_if_already_long(self) -> None:
        from alpha_core.portfolio.models import PositionState

        s = ProbabilityMomentumStrategy(momentum_threshold=0.01, window=2)
        s.on_init(["A"])

        position = PositionState(
            instrument_id="A",
            side=Side.LONG,
            size=Decimal("10"),
            entry_price=Decimal("0.40"),
            current_price=Decimal("0.50"),
            unrealised_pnl=Decimal("1.0"),
            opened_at=_T0,
            last_updated=_T0,
        )
        portfolio = PortfolioState(
            timestamp=_T0,
            cash=Decimal("9000"),
            positions={"A": position},
            total_fees=_ZERO,
            equity=Decimal("9001"),
        )

        s.on_data(_T0, _state(["A"], {"A": 0.40}, portfolio=portfolio))
        orders = s.on_data(_T0, _state(["A"], {"A": 0.55}, portfolio=portfolio))
        # Already long — should not add another LONG
        long_orders = [o for o in orders if o.side == Side.LONG]
        assert len(long_orders) == 0


# ============================================================================
# CrossVenueArbStrategy
# ============================================================================


class TestCrossVenueArbStrategy:
    def test_name_encodes_threshold(self) -> None:
        s = CrossVenueArbStrategy(spread_threshold=0.07)
        assert "0.07" in s.name

    def test_orders_when_spread_exceeds_threshold(self) -> None:
        s = CrossVenueArbStrategy(spread_threshold=0.05)
        s.on_init(["poly:q1", "multi:q1"])
        universe = ["poly:q1", "multi:q1"]
        prices = {"poly:q1": 0.40, "multi:q1": 0.50}
        orders = s.on_data(_T0, _state(universe, prices))
        assert len(orders) == 2
        sides = {o.instrument_id: o.side for o in orders}
        assert sides["poly:q1"] == Side.LONG  # cheaper → buy
        assert sides["multi:q1"] == Side.SHORT  # dearer → sell

    def test_no_orders_when_spread_below_threshold(self) -> None:
        s = CrossVenueArbStrategy(spread_threshold=0.20)
        s.on_init(["poly:q1", "multi:q1"])
        universe = ["poly:q1", "multi:q1"]
        prices = {"poly:q1": 0.45, "multi:q1": 0.50}
        orders = s.on_data(_T0, _state(universe, prices))
        assert orders == []

    def test_single_venue_no_orders(self) -> None:
        s = CrossVenueArbStrategy(spread_threshold=0.01)
        s.on_init(["only:q1"])
        orders = s.on_data(_T0, _state(["only:q1"], {"only:q1": 0.5}))
        assert orders == []

    def test_empty_universe_no_orders(self) -> None:
        s = CrossVenueArbStrategy()
        s.on_init([])
        assert s.on_data(_T0, _state([], {})) == []

    def test_does_not_retrade_existing_legs(self) -> None:
        from alpha_core.portfolio.models import PositionState

        s = CrossVenueArbStrategy(spread_threshold=0.05, size=Decimal("5"))
        s.on_init(["poly:q1", "multi:q1"])

        existing_long = PositionState(
            instrument_id="poly:q1",
            side=Side.LONG,
            size=Decimal("5"),
            entry_price=Decimal("0.40"),
            current_price=Decimal("0.40"),
            unrealised_pnl=_ZERO,
            opened_at=_T0,
            last_updated=_T0,
        )
        portfolio = PortfolioState(
            timestamp=_T0,
            cash=Decimal("9975"),
            positions={"poly:q1": existing_long},
            total_fees=_ZERO,
            equity=Decimal("9975"),
        )
        st = _state(
            ["poly:q1", "multi:q1"],
            {"poly:q1": 0.40, "multi:q1": 0.55},
            portfolio=portfolio,
        )
        orders = s.on_data(_T0, st)
        # LONG for poly:q1 should be suppressed (already long)
        long_ids = [o.instrument_id for o in orders if o.side == Side.LONG]
        assert "poly:q1" not in long_ids


# ============================================================================
# MeanReversionStrategy
# ============================================================================


class TestMeanReversionStrategy:
    def test_name_encodes_params(self) -> None:
        s = MeanReversionStrategy(zscore_threshold=1.5, lookback=30)
        assert "1.5" in s.name
        assert "30" in s.name

    def test_generates_signals_from_price_column(self) -> None:
        s = MeanReversionStrategy(zscore_threshold=0.5)
        features = pd.DataFrame(
            {
                "ts_event": [_T0] * 4,
                "instrument_id": ["A", "B", "C", "D"],
                "price": [0.2, 0.4, 0.6, 0.8],
            }
        )
        signals = s.generate_signals(features, ["A", "B", "C", "D"])
        assert set(signals.columns) == {"instrument_id", "signal"}
        assert len(signals) == 4
        # A and B are below mean → positive z-score reversed → negative → ... wait
        # mean=0.5, std≈0.258; z_A≈-1.16, z_B≈-0.39, z_C≈0.39, z_D≈1.16
        # signal = -z, clamped to |z|>=0.5 → signal_A=+1.16, D=-1.16, B=C=0
        sig_map = dict(zip(signals["instrument_id"], signals["signal"]))
        assert sig_map["A"] > 0, "Under-valued A should have positive (long) signal"
        assert sig_map["D"] < 0, "Over-valued D should have negative (short) signal"

    def test_empty_universe_returns_empty_df(self) -> None:
        s = MeanReversionStrategy()
        signals = s.generate_signals(pd.DataFrame(), [])
        assert signals.empty
        assert "instrument_id" in signals.columns
        assert "signal" in signals.columns

    def test_flat_universe_no_signals(self) -> None:
        """When all prices are identical std=0 → all z-scores=0 → no signals."""
        s = MeanReversionStrategy(zscore_threshold=0.1)
        features = pd.DataFrame(
            {
                "ts_event": [_T0] * 3,
                "instrument_id": ["A", "B", "C"],
                "price": [0.5, 0.5, 0.5],
            }
        )
        signals = s.generate_signals(features, ["A", "B", "C"])
        assert (signals["signal"] == 0.0).all()

    def test_missing_price_column_returns_zeros(self) -> None:
        s = MeanReversionStrategy()
        features = pd.DataFrame(
            {
                "ts_event": [_T0] * 2,
                "instrument_id": ["A", "B"],
                "some_other_col": [1.0, 2.0],
            }
        )
        signals = s.generate_signals(features, ["A", "B"])
        assert (signals["signal"] == 0.0).all()

    def test_size_positions_delegates_to_sizer(self) -> None:
        s = MeanReversionStrategy()
        signals = pd.DataFrame({"instrument_id": ["A", "B"], "signal": [1.0, -1.0]})
        weights = s.size_positions(signals, Decimal("10000"), 10)
        assert set(weights.columns) == {"instrument_id", "target_weight"}
        assert abs(weights["target_weight"].abs().sum() - 1.0) < 1e-6
