"""Short-name alias package for the performance boundary contracts.

This package re-exports everything from :mod:`alpha_core.performance` under
the shorter ``alpha_core.perf`` namespace.  Both namespaces are stable; new
code should prefer ``alpha_core.perf``.

Sub-modules
-----------
interfaces  : ``@runtime_checkable`` Protocol stubs for ``FeatureTransform``
              and ``SimulationKernel``
parity      : ``ParityConfig``, ``ParityResult``, ``check_feature_parity``,
              and ``check_simulation_parity`` helpers

Usage::

    import alpha_core.perf as perf
    import alpha_core.perf.interfaces as perf_interfaces
    import alpha_core.perf.parity as perf_parity
"""

from __future__ import annotations

import alpha_core.performance.interfaces as interfaces
import alpha_core.performance.parity as parity

__all__ = ["interfaces", "parity"]
