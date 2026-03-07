"""Re-export shim: ``alpha_core.perf.parity`` → ``alpha_core.performance.parity``.

Prefer importing from ``alpha_core.perf.parity`` in new code; both namespaces
are stable and identical.
"""

from __future__ import annotations

from alpha_core.performance.parity import (
    ParityConfig,
    ParityResult,
    ToleranceMode,
    check_feature_parity,
    check_simulation_parity,
)

__all__ = [
    "ParityConfig",
    "ParityResult",
    "ToleranceMode",
    "check_feature_parity",
    "check_simulation_parity",
]
