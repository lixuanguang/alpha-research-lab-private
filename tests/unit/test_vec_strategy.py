"""Unit tests for apps.research.backtester.vec_strategy.VecStrategy."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from alpha_core.portfolio.sizing import EqualWeightSizer, FixedSizeSizer
from apps.research.backtester.vec_strategy import VecStrategy


class _SimpleStrategy(VecStrategy):
    """Minimal concrete VecStrategy for testing."""

    name = "simple"

    def generate_signals(
        self, features: pd.DataFrame, universe: list[str]
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {"instrument_id": universe, "signal": [1.0] * len(universe)}
        )

    def size_positions(
        self,
        signals: pd.DataFrame,
        portfolio_value: Decimal,
        max_positions: int,
    ) -> pd.DataFrame:
        return EqualWeightSizer().size(signals, portfolio_value, max_positions)


class _FlatStrategy(VecStrategy):
    """Strategy that always returns zero signals."""

    name = "flat"

    def generate_signals(
        self, features: pd.DataFrame, universe: list[str]
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {"instrument_id": universe, "signal": [0.0] * len(universe)}
        )

    def size_positions(
        self, signals: pd.DataFrame, portfolio_value: Decimal, max_positions: int
    ) -> pd.DataFrame:
        return EqualWeightSizer().size(signals, portfolio_value, max_positions)


class _EmptyUniverseStrategy(VecStrategy):
    """Strategy that handles empty universe gracefully."""

    name = "empty_universe"

    def generate_signals(
        self, features: pd.DataFrame, universe: list[str]
    ) -> pd.DataFrame:
        return pd.DataFrame({"instrument_id": [], "signal": []})

    def size_positions(
        self, signals: pd.DataFrame, portfolio_value: Decimal, max_positions: int
    ) -> pd.DataFrame:
        return pd.DataFrame({"instrument_id": [], "target_weight": []})


class TestVecStrategyABC:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            VecStrategy()  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self) -> None:
        s = _SimpleStrategy()
        assert s.name == "simple"


class TestGenerateSignals:
    def test_generate_signals_returns_required_columns(self) -> None:
        s = _SimpleStrategy()
        features = pd.DataFrame({"instrument_id": ["a", "b"]})
        signals = s.generate_signals(features, universe=["a", "b"])
        assert "instrument_id" in signals.columns
        assert "signal" in signals.columns

    def test_generate_signals_empty_universe(self) -> None:
        s = _EmptyUniverseStrategy()
        signals = s.generate_signals(pd.DataFrame(), universe=[])
        assert signals.empty or len(signals) == 0

    def test_flat_strategy_signals_are_zero(self) -> None:
        s = _FlatStrategy()
        signals = s.generate_signals(pd.DataFrame(), universe=["a", "b"])
        assert all(v == 0.0 for v in signals["signal"])

    def test_signal_count_matches_universe(self) -> None:
        s = _SimpleStrategy()
        features = pd.DataFrame({"instrument_id": list("abcde")})
        signals = s.generate_signals(features, universe=list("abcde"))
        assert len(signals) == 5


class TestSizePositions:
    def test_size_positions_returns_required_columns(self) -> None:
        s = _SimpleStrategy()
        signals = pd.DataFrame({"instrument_id": ["a"], "signal": [1.0]})
        weights = s.size_positions(signals, Decimal("1000"), max_positions=10)
        assert "instrument_id" in weights.columns
        assert "target_weight" in weights.columns

    def test_all_flat_gives_empty_weights(self) -> None:
        s = _FlatStrategy()
        signals = pd.DataFrame({"instrument_id": ["a", "b"], "signal": [0.0, 0.0]})
        weights = s.size_positions(signals, Decimal("1000"), max_positions=10)
        assert weights.empty or all(w == 0.0 for w in weights["target_weight"])

    def test_empty_universe_gives_empty_weights(self) -> None:
        s = _EmptyUniverseStrategy()
        weights = s.size_positions(pd.DataFrame(), Decimal("1000"), max_positions=10)
        assert weights.empty

    def test_fixed_size_sizer_integration(self) -> None:
        class _FixedStrategy(VecStrategy):
            name = "fixed"

            def generate_signals(self, features, universe):
                return pd.DataFrame({"instrument_id": universe, "signal": [1.0] * len(universe)})

            def size_positions(self, signals, portfolio_value, max_positions):
                return FixedSizeSizer(fraction=0.2).size(signals, portfolio_value, max_positions)

        s = _FixedStrategy()
        signals = pd.DataFrame({"instrument_id": ["a"], "signal": [1.0]})
        weights = s.size_positions(signals, Decimal("500"), max_positions=5)
        assert weights.iloc[0]["target_weight"] == pytest.approx(0.2)
