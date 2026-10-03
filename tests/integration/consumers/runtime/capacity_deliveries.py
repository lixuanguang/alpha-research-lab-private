"""Decode retained shared deliveries once, as the runtime's typed source pipe does.

The strict decoder runs every nested native constructor check; repeating them on the
envelopes would rescan the same immutable depth. Public consumers still validate
recursively when handed these rows.
"""

from __future__ import annotations

# project library imports
from applications.execute.source_service import _DecodedBookObservation
from runtime import LiveBookDelivery, SharedBookDelivery


class _IndexedSourceDelivery(LiveBookDelivery, frozen=True):
    """Decode complete typed native records before checking their separate delivery clock."""

    book: _DecodedBookObservation

    def __post_init__(self) -> None:
        """Avoid recursively validating native fields already checked by the typed decoder."""
        self._require_availability()


class _IndexedSharedDelivery(SharedBookDelivery, frozen=True):
    """Decode a strict complete envelope for read-only retained consumers."""

    source: _IndexedSourceDelivery

    def __post_init__(self) -> None:
        """Check coordination after the decoder validates every nested source and policy field."""
        self._require_coordination()
