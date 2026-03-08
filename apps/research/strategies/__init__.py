"""Example research strategies for testing and demonstration.

Three reference strategies covering the main PM signal archetypes:

- :class:`~apps.research.strategies.probability_momentum.ProbabilityMomentumStrategy`
  — event-driven; long/short on implied-probability momentum.
- :class:`~apps.research.strategies.cross_venue_arb.CrossVenueArbStrategy`
  — event-driven; buy cheap / sell expensive across venues.
- :class:`~apps.research.strategies.mean_reversion.MeanReversionStrategy`
  — vectorized; cross-sectional z-score reversion towards 0.5.

Use :mod:`apps.research.strategies.loader` to instantiate any strategy from a
dotted module path string (e.g. for CLI ``--strategy`` flags).
"""

from __future__ import annotations

from apps.research.strategies.cross_venue_arb import CrossVenueArbStrategy
from apps.research.strategies.mean_reversion import MeanReversionStrategy
from apps.research.strategies.probability_momentum import ProbabilityMomentumStrategy

__all__ = [
    "CrossVenueArbStrategy",
    "MeanReversionStrategy",
    "ProbabilityMomentumStrategy",
]
