"""StrategyLoader — dynamically import a strategy class from a dotted module path.

Usage::

    loader = StrategyLoader()
    cls = loader.load(
        "apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy"
    )
    strategy = cls(momentum_threshold=0.03)

The ``module_path`` must point to a concrete subclass of either
:class:`~apps.research.backtester.strategy.Strategy` (event-driven) or
:class:`~apps.research.backtester.vec_strategy.VecStrategy` (vectorized).
Any other class raises :class:`TypeError`.
"""

from __future__ import annotations

import importlib

from apps.research.backtester.strategy import Strategy
from apps.research.backtester.vec_strategy import VecStrategy

StrategyClass = type[Strategy] | type[VecStrategy]


class StrategyLoader:
    """Load strategy classes from dotted ``module.path.ClassName`` strings.

    Caches imported modules for the lifetime of the loader instance so
    repeated loads of the same path avoid redundant disk I/O.
    """

    def __init__(self) -> None:
        self._cache: dict[str, StrategyClass] = {}

    def load(self, module_path: str) -> StrategyClass:
        """Import and return the strategy class at *module_path*.

        Args:
            module_path: Fully qualified dotted path, e.g.
                ``"apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy"``.

        Returns:
            The strategy class (not an instance).

        Raises:
            ModuleNotFoundError: If the module component cannot be imported.
            AttributeError: If the class name is not found in the module.
            TypeError: If the resolved object is not a Strategy or VecStrategy subclass.
            ValueError: If *module_path* does not contain a ``.`` separator.
        """
        if module_path in self._cache:
            return self._cache[module_path]

        if "." not in module_path:
            raise ValueError(
                f"module_path must be a fully qualified dotted path, got: {module_path!r}"
            )

        module_name, _, class_name = module_path.rpartition(".")
        module = importlib.import_module(module_name)

        if not hasattr(module, class_name):
            raise AttributeError(
                f"Module '{module_name}' has no attribute '{class_name}'. "
                f"Available names: {[n for n in dir(module) if not n.startswith('_')]}"
            )

        cls = getattr(module, class_name)

        if not (
            isinstance(cls, type) and (issubclass(cls, Strategy) or issubclass(cls, VecStrategy))
        ):
            raise TypeError(
                f"'{module_path}' resolved to {cls!r}, which is not a subclass of "
                f"Strategy or VecStrategy."
            )

        self._cache[module_path] = cls
        return cls

    def clear_cache(self) -> None:
        """Evict all cached module references."""
        self._cache.clear()


__all__ = ["StrategyClass", "StrategyLoader"]
