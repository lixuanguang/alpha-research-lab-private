"""Unit tests for ReconnectionPolicy."""

from __future__ import annotations

import math

import apps.data_collector.connectors.reconnection as reconnection_mod
import pytest

# ---------------------------------------------------------------------------
# Construction validation
# ---------------------------------------------------------------------------


def test_default_construction() -> None:
    p = reconnection_mod.ReconnectionPolicy()
    assert p.base == 1.0
    assert p.max_delay == 60.0
    assert p.jitter == 0.5


def test_invalid_base_raises() -> None:
    with pytest.raises(ValueError, match="base"):
        reconnection_mod.ReconnectionPolicy(base=0.0)


def test_invalid_max_delay_raises() -> None:
    with pytest.raises(ValueError, match="max_delay"):
        reconnection_mod.ReconnectionPolicy(base=10.0, max_delay=5.0)


def test_invalid_jitter_raises() -> None:
    with pytest.raises(ValueError, match="jitter"):
        reconnection_mod.ReconnectionPolicy(jitter=1.0)

    with pytest.raises(ValueError, match="jitter"):
        reconnection_mod.ReconnectionPolicy(jitter=-0.1)


# ---------------------------------------------------------------------------
# Exponential growth
# ---------------------------------------------------------------------------


def test_no_jitter_grows_exponentially() -> None:
    p = reconnection_mod.ReconnectionPolicy(base=1.0, max_delay=1000.0, jitter=0.0)
    for attempt in range(6):
        expected = 1.0 * math.pow(2.0, attempt)
        assert p.next_delay(attempt) == pytest.approx(expected)


def test_delay_capped_at_max() -> None:
    p = reconnection_mod.ReconnectionPolicy(base=1.0, max_delay=10.0, jitter=0.0)
    # At attempt=10, uncapped delay would be 1024s; should be capped at 10.
    assert p.next_delay(10) == pytest.approx(10.0)


def test_delay_capped_for_large_attempts() -> None:
    p = reconnection_mod.ReconnectionPolicy(base=1.0, max_delay=60.0, jitter=0.0)
    for attempt in range(10, 30):
        assert p.next_delay(attempt) == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Jitter bounds
# ---------------------------------------------------------------------------


def test_jitter_within_bounds() -> None:
    p = reconnection_mod.ReconnectionPolicy(base=1.0, max_delay=60.0, jitter=0.5)
    for attempt in range(20):
        delay = p.next_delay(attempt)
        capped = min(1.0 * math.pow(2.0, attempt), 60.0)
        assert capped * 0.5 <= delay <= capped * 1.5, (
            f"delay {delay} out of [{capped*0.5}, {capped*1.5}] at attempt {attempt}"
        )


def test_zero_jitter_is_deterministic() -> None:
    p = reconnection_mod.ReconnectionPolicy(base=2.0, max_delay=120.0, jitter=0.0)
    for attempt in range(5):
        delays = {p.next_delay(attempt) for _ in range(10)}
        assert len(delays) == 1


# ---------------------------------------------------------------------------
# Negative attempt raises
# ---------------------------------------------------------------------------


def test_negative_attempt_raises() -> None:
    p = reconnection_mod.ReconnectionPolicy()
    with pytest.raises(ValueError, match="attempt"):
        p.next_delay(-1)


# ---------------------------------------------------------------------------
# reset is a no-op (stateless policy)
# ---------------------------------------------------------------------------


def test_reset_no_op() -> None:
    p = reconnection_mod.ReconnectionPolicy(base=4.0, max_delay=60.0, jitter=0.0)
    p.reset()
    assert p.next_delay(0) == pytest.approx(4.0)
