"""Shared event-type classification helpers for data-collector pipelines."""

from __future__ import annotations

import alpha_core.events.models as event_models


def dataset_key_for_event(event: event_models.CanonicalMarketEvent) -> str:
    """Return the storage dataset key for a canonical event instance."""
    if isinstance(event, event_models.CanonicalTrade):
        return "trades"
    if isinstance(event, event_models.CanonicalBookSnapshot):
        return "books"
    if isinstance(event, event_models.CanonicalBookDelta):
        return "book_deltas"
    if isinstance(event, event_models.CanonicalOHLCV):
        return "ohlcv"
    return "metadata"


__all__ = ["dataset_key_for_event"]
