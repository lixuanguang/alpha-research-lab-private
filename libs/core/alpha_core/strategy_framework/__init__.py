"""Strategy framework package.

This package exports module namespaces only:
- `interfaces`: strategy protocol contracts
- `models`: typed datamodels flowing through the strategy pipeline
- `engine`: minimal orchestration skeleton
"""

from __future__ import annotations

import alpha_core.strategy_framework.engine as engine
import alpha_core.strategy_framework.interfaces as interfaces
import alpha_core.strategy_framework.models as models

__all__ = ["engine", "interfaces", "models"]
