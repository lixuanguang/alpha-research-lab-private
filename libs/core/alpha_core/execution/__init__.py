"""Execution package.

This package exports module namespaces only:
- `fees`: fee calculation helpers
- `models`: R3 backtester order / fill / fee-schedule models
- `order_models`: order lifecycle and execution report contracts
- `pretrade`: pre-trade validation rules
- `simulator`: deterministic fill simulation (FillSimulator + ExecutionSimulator)
- `slippage`: pluggable slippage models
"""

import alpha_core.execution.fees as fees
import alpha_core.execution.models as models
import alpha_core.execution.order_models as order_models
import alpha_core.execution.pretrade as pretrade
import alpha_core.execution.simulator as simulator
import alpha_core.execution.slippage as slippage

__all__ = [
    "fees",
    "models",
    "order_models",
    "pretrade",
    "simulator",
    "slippage",
]
