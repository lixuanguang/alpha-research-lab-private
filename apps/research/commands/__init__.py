"""Research CLI shared command helpers.

Re-exports from :mod:`common` so callers can import directly from this package:

    from apps.research.commands.common import emit_outcome, OutputFormat
"""

from __future__ import annotations

import apps.research.commands.common as common

__all__ = ["common"]
