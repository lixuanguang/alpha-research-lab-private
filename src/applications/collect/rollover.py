"""Compose public-only finite collection with cooperative process stop handling."""

from __future__ import annotations

# standard library imports
from collections.abc import Callable
from pathlib import Path
from types import FrameType

# project library imports
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.collection import CaptureRunRunner
from market_data.contracts import CaptureRunRequest


class CaptureRunSignals:
    """Defer process signals until accepted original receipts have durably drained."""

    def __init__(self) -> None:
        """Start with no requested stop and no account or transport authority."""
        self._requested = False

    def request(self, _signum: int, _frame: FrameType | None) -> None:
        """Convert SIGTERM or SIGINT into the finite collector's cooperative stop."""
        self._requested = True

    def requested(self) -> bool:
        """Return the original signal request without opening or mutating any source."""
        return self._requested


async def collect_run(
    request: CaptureRunRequest,
    root: Path,
    *,
    resume: bool = False,
    transport: VenueTransport | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Resolve existing public adapters and collect one immutable finite UTC source window.

    Args:
        request: Explicit source, implementation, UTC window and staging limits.
        root: Owned durable run directory; no account or trading service is provisioned.
        resume: Verify exact saved prefixes and acquire a fresh session with an explicit gap.
        transport: Optional deterministic external transport boundary for qualification.
        stop_requested: Optional caller-owned cooperative signal.

    Returns:
        Live state, original clocks and exact segment identities, with offline verification pending.
    """
    request.__post_init__()
    selected = VenueTransport(request.config) if transport is None else transport
    subscriptions = VenueSubscriptions()
    runner = CaptureRunRunner(
        book_factory=BookAdapters.create,
        transport=selected,
        subscriptions=subscriptions,
    )
    return await runner.run(request, root, resume=resume, stop_requested=stop_requested)
