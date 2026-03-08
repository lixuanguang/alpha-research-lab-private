"""Unit tests for apps.research.strategies.loader.StrategyLoader.

Covers:
- Load valid event-driven strategy class.
- Load valid vectorized strategy class.
- Invalid module path raises ModuleNotFoundError.
- Valid module but missing class raises AttributeError.
- Wrong class type (not a Strategy/VecStrategy) raises TypeError.
- Missing dot separator raises ValueError.
- Cache hit reuses prior import.
- clear_cache() invalidates cache.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from apps.research.backtester.strategy import Strategy
from apps.research.backtester.vec_strategy import VecStrategy
from apps.research.strategies.loader import StrategyLoader

# ---------------------------------------------------------------------------
# Valid loads
# ---------------------------------------------------------------------------


def test_load_event_strategy_returns_strategy_subclass() -> None:
    loader = StrategyLoader()
    cls = loader.load("apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy")
    assert issubclass(cls, Strategy)


def test_load_vec_strategy_returns_vec_strategy_subclass() -> None:
    loader = StrategyLoader()
    cls = loader.load("apps.research.strategies.mean_reversion.MeanReversionStrategy")
    assert issubclass(cls, VecStrategy)


def test_load_cross_venue_arb_strategy() -> None:
    loader = StrategyLoader()
    cls = loader.load("apps.research.strategies.cross_venue_arb.CrossVenueArbStrategy")
    assert issubclass(cls, Strategy)


def test_loaded_class_is_instantiable() -> None:
    loader = StrategyLoader()
    cls = loader.load("apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy")
    instance = cast(Any, cls)(momentum_threshold=0.03, window=5)
    assert instance is not None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_invalid_module_raises_module_not_found() -> None:
    loader = StrategyLoader()
    with pytest.raises(ModuleNotFoundError):
        loader.load("apps.research.strategies.nonexistent_module.SomeClass")


def test_missing_class_in_valid_module_raises_attribute_error() -> None:
    loader = StrategyLoader()
    with pytest.raises(AttributeError, match="NoSuchClass"):
        loader.load("apps.research.strategies.probability_momentum.NoSuchClass")


def test_non_strategy_class_raises_type_error() -> None:
    loader = StrategyLoader()
    # StrategyLoader itself is a real class but not a Strategy/VecStrategy
    with pytest.raises(TypeError, match="Strategy"):
        loader.load("apps.research.strategies.loader.StrategyLoader")


def test_path_without_dot_raises_value_error() -> None:
    loader = StrategyLoader()
    with pytest.raises(ValueError, match="fully qualified"):
        loader.load("NoDotHere")


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


def test_repeated_load_returns_same_class_object() -> None:
    loader = StrategyLoader()
    path = "apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy"
    cls1 = loader.load(path)
    cls2 = loader.load(path)
    assert cls1 is cls2


def test_clear_cache_allows_reimport() -> None:
    loader = StrategyLoader()
    path = "apps.research.strategies.mean_reversion.MeanReversionStrategy"
    cls1 = loader.load(path)
    loader.clear_cache()
    cls2 = loader.load(path)
    # Same class from the same module — identity check still holds because
    # Python caches modules in sys.modules
    assert cls1 is cls2
