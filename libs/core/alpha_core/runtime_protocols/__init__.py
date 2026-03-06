"""Runtime protocol stubs package.

Provider-agnostic contracts for account/market state access and order
routing.  These protocols are contract-only at Foundation scope and are
not intended to replace existing adapter implementations.

Sub-modules
-----------
models      : typed datamodels exchanged across provider/router boundaries
interfaces  : ``@runtime_checkable`` protocol stubs for all four providers
"""

from __future__ import annotations

import alpha_core.runtime_protocols.interfaces as interfaces
import alpha_core.runtime_protocols.models as models

__all__ = ["interfaces", "models"]
