"""Execution package.

This package exports module namespaces only:
- `order_models`: order lifecycle and execution report contracts
- `pretrade`: pre-trade validation rules
- `simulator`: deterministic fill simulation
"""

import alpha_core.execution.order_models as order_models
import alpha_core.execution.pretrade as pretrade
import alpha_core.execution.simulator as simulator

__all__ = [
    "order_models",
    "pretrade",
    "simulator",
]
