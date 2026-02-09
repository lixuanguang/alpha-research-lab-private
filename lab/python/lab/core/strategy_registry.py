"""
lab.core.strategy_registry
~~~~~~~~~~~~~~~~~~~~~~~~~~
Strategy registry — maps string identifiers to strategy callables.

Design
------
Decorator-based registration so that adding a new strategy is a one-liner:

    @register("macro_equities.baseline")
    def baseline_strategy(config, data):
        ...

The registry is a plain dict; no metaclass magic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# type alias: a strategy is (config, data_dict) -> weights DataFrame
StrategyFn = Callable[..., Any]

_REGISTRY: dict[str, StrategyFn] = {}


def register(name: str) -> Callable[[StrategyFn], StrategyFn]:
    """Decorator that registers a strategy function under *name*.

    Parameters
    ----------
    name : str
        Dot-separated identifier, e.g. ``"macro_equities.baseline"``.

    Raises
    ------
    ValueError
        If *name* is already registered (prevents silent overwrites).
    """

    def _decorator(fn: StrategyFn) -> StrategyFn:
        if name in _REGISTRY:
            raise ValueError(f"Strategy '{name}' already registered.")
        _REGISTRY[name] = fn
        return fn

    return _decorator


def get(name: str) -> StrategyFn:
    """Retrieve a registered strategy by *name*.

    Raises
    ------
    KeyError
        If the strategy has not been registered.
    """
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown strategy '{name}'. Available: {available}")
    return _REGISTRY[name]


def list_strategies() -> list[str]:
    """Return sorted list of registered strategy names."""
    return sorted(_REGISTRY)
