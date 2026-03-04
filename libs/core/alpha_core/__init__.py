"""Alpha Research Lab — shared core library."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import re

_DIST_NAME = "alpha-research-lab"


def _resolve_version() -> str:
    try:
        return importlib_metadata.version(_DIST_NAME)
    except importlib_metadata.PackageNotFoundError:
        return "0.0.0+unknown"


def _extract_commit_hash(version_str: str) -> str | None:
    match = re.search(r"\+g([0-9a-f]{7,40})", version_str)
    if match is None:
        return None
    return match.group(1)


__version__ = _resolve_version()
__commit_hash__ = _extract_commit_hash(__version__)

__all__ = [
    "__commit_hash__",
    "__version__",
    # sub-packages (accessible as alpha_core.<name>)
    "research",
    "strategy_framework",
]
