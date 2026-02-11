"""Macro strategy helpers."""

from lab.strategies.macro.baselines import equal_weight_long_only, sixty_forty_proxy
from lab.strategies.macro.signals import EnsembleSignal, Signal, TrendSignal, build_signal

__all__ = [
    "EnsembleSignal",
    "Signal",
    "TrendSignal",
    "build_signal",
    "equal_weight_long_only",
    "sixty_forty_proxy",
]
