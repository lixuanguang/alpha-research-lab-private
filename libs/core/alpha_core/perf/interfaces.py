"""Performance boundary protocol interfaces (short-name re-export).

All contracts live in :mod:`alpha_core.performance.interfaces`; this module
provides the canonical ``alpha_core.perf.interfaces`` import path.

Protocols
---------
FeatureTransform   — apply a named numeric transform to a sequence of floats.
SimulationKernel   — advance a simulation one step given state + event.

Both protocols are ``@runtime_checkable`` so downstream code can use
``isinstance`` guards without importing concrete classes.

Promotion rule
--------------
An accelerated implementation **must** pass
:func:`alpha_core.perf.parity.check_feature_parity` or
:func:`alpha_core.perf.parity.check_simulation_parity` before it may replace
the default pure-Python baseline path.  The parity check and its tolerance
must be documented on the concrete accelerated class.

Usage::

    from alpha_core.perf.interfaces import FeatureTransform, SimulationKernel
"""

from __future__ import annotations

from alpha_core.performance.interfaces import FeatureTransform, SimulationKernel

__all__ = ["FeatureTransform", "SimulationKernel"]
