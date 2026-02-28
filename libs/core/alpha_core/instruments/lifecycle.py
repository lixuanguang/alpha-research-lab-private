"""Lifecycle transition rules for prediction-market instruments."""

from __future__ import annotations

import alpha_core.instruments.models as instrument_models

_ALLOWED_TRANSITIONS: dict[
    instrument_models.MarketLifecycle,
    set[instrument_models.MarketLifecycle],
] = {
    instrument_models.MarketLifecycle.ACTIVE: {
        instrument_models.MarketLifecycle.HALTED,
        instrument_models.MarketLifecycle.RESOLVED,
        instrument_models.MarketLifecycle.DELISTED,
    },
    instrument_models.MarketLifecycle.HALTED: {
        instrument_models.MarketLifecycle.ACTIVE,
        instrument_models.MarketLifecycle.RESOLVED,
        instrument_models.MarketLifecycle.DELISTED,
    },
    instrument_models.MarketLifecycle.RESOLVED: set(),
    instrument_models.MarketLifecycle.DELISTED: set(),
}


def can_transition(
    current: instrument_models.MarketLifecycle,
    new_state: instrument_models.MarketLifecycle,
) -> bool:
    """Return True when a lifecycle transition is valid.

    Staying in the same state is considered valid and treated as a no-op.
    """
    if current == new_state:
        return True
    return new_state in _ALLOWED_TRANSITIONS[current]


def validate_transition(
    current: instrument_models.MarketLifecycle,
    new_state: instrument_models.MarketLifecycle,
) -> None:
    """Validate a lifecycle transition and raise on invalid transitions."""
    if can_transition(current, new_state):
        return

    allowed = sorted(state.value for state in _ALLOWED_TRANSITIONS[current])
    raise ValueError(
        "Invalid lifecycle transition "
        f"from `{current.value}` to `{new_state.value}`. Allowed: {allowed or '[]'}"
    )
