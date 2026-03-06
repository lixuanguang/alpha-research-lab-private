"""Performance boundary contracts package.

Defines provider-agnostic interfaces for compute-heavy paths so that an
optional accelerated implementation (Numba / Rust / C-extension) can
later replace the pure-Python baseline without any API changes downstream.

Sub-modules
-----------
interfaces  : ``@runtime_checkable`` Protocol stubs for ``FeatureTransform``
              and ``SimulationKernel``
parity      : ``ParityConfig``, ``ParityResult``, and ``check_feature_parity``
              / ``check_simulation_parity`` helpers for enforcing output
              equivalence between baseline and accelerated implementations
"""

from __future__ import annotations

import alpha_core.performance.interfaces as interfaces
import alpha_core.performance.parity as parity

__all__ = ["interfaces", "parity"]
