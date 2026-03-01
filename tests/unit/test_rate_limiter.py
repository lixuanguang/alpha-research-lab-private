"""Unit tests for token bucket rate limiter."""

from __future__ import annotations

import asyncio
import time

import apps.data_collector.connectors.rate_limiter as connector_rate_limiter
import pytest


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


def test_rate_limiter_first_acquire_is_immediate() -> None:
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=60)

    async def _run() -> float:
        started = time.perf_counter()
        await limiter.acquire()
        return time.perf_counter() - started

    assert asyncio.run(_run()) < 0.01


def test_rate_limiter_available_is_true_by_default() -> None:
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=60)

    assert limiter.available()


def test_rate_limiter_available_is_false_when_exhausted() -> None:
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=60)
    limiter._tokens = 0.0
    limiter._capacity = 1.0
    limiter._refill_rate_per_second = 1.0

    assert not limiter.available()


def test_rate_limiter_available_reflects_refill_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock = _FakeClock()
    monkeypatch.setattr(
        "apps.data_collector.connectors.rate_limiter.time.monotonic",
        fake_clock.monotonic,
    )
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=60)
    limiter._tokens = 0.0
    limiter._capacity = 1.0
    limiter._refill_rate_per_second = 2.0
    limiter._last_refill = 0.0

    assert not limiter.available()
    fake_clock.now = 0.6
    assert limiter.available()


def test_rate_limiter_blocks_when_exhausted_then_refills() -> None:
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=60)
    limiter._tokens = 0.0
    limiter._capacity = 1.0
    limiter._refill_rate_per_second = 10.0

    async def _run() -> float:
        started = time.perf_counter()
        await limiter.acquire()
        return time.perf_counter() - started

    elapsed = asyncio.run(_run())

    assert elapsed >= 0.09


def test_rate_limiter_supports_concurrent_acquire() -> None:
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=120)

    async def _run() -> int:
        await asyncio.gather(*(limiter.acquire() for _ in range(4)))
        return 4

    assert asyncio.run(_run()) == 4


def test_rate_limiter_handles_float_precision_near_one_token() -> None:
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=60)
    limiter._tokens = 1.0 - 1e-15

    async def _run() -> None:
        await asyncio.wait_for(limiter.acquire(), timeout=0.05)

    asyncio.run(_run())
    assert limiter._tokens >= 0.0


@pytest.mark.perf
def test_rate_limiter_meets_d3_accuracy_target_within_one_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_clock = _FakeClock()
    monkeypatch.setattr(
        "apps.data_collector.connectors.rate_limiter.time.monotonic",
        fake_clock.monotonic,
    )
    monkeypatch.setattr(
        "apps.data_collector.connectors.rate_limiter.asyncio.sleep",
        fake_clock.sleep,
    )
    rpm = 600
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=rpm)
    limiter._tokens = 0.0
    limiter._last_refill = 0.0

    async def _consume(count: int) -> None:
        for _ in range(count):
            await limiter.acquire()

    event_count = 25
    asyncio.run(_consume(event_count))
    elapsed = fake_clock.now
    observed_rpm = event_count / elapsed * 60.0
    overshoot_pct = max(0.0, (observed_rpm - rpm) / rpm)

    assert overshoot_pct <= 0.01


def test_rate_limiter_rejects_invalid_rpm() -> None:
    try:
        connector_rate_limiter.TokenBucketRateLimiter(rpm=0)
        raise AssertionError("Expected ValueError for invalid rpm")
    except ValueError:
        pass
