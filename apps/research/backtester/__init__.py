"""Backtester package for event-driven simulation.

Exports:
- ``engine``: :class:`EventBacktestConfig`, :class:`EventBacktestEngine`
- ``result``: :class:`BacktestResult`
- ``strategy``: :class:`Strategy`, :class:`StrategyState`
"""

import apps.research.backtester.engine as engine
import apps.research.backtester.result as result
import apps.research.backtester.strategy as strategy

__all__ = ["engine", "result", "strategy"]
