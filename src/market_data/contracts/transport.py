"""Bounded read-only public discovery, snapshot and WebSocket transport adapters."""

from __future__ import annotations

# standard library imports
from typing import Protocol

# project library imports


class FeedSocket(Protocol):
    """Minimal message transport boundary used by the collector and deterministic fakes."""

    async def send(self, message: str) -> None:
        """Send one subscription/configuration message.

        Args:
            message: One outbound subscription/configuration message; never logged.
        """
        ...

    async def recv(self) -> str | bytes:
        """Receive one complete source message with transport backpressure.

        Returns:
            Next complete source message.
        """
        ...

    async def close(self) -> None:
        """Bound connection shutdown through the underlying transport."""
        ...


class SnapshotTransport(Protocol):
    """Fetch an original native snapshot under the selected transport's resource limits."""

    def snapshot(self) -> bytes:
        """Return a complete original source snapshot.

        Returns:
            Retained native bytes without parsing or canonical transformation.
        """
        ...
