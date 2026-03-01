"""Unit tests for polling scheduler orchestration."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.rate_limiter as connector_rate_limiter
import apps.data_collector.connectors.scheduler as connector_scheduler

import alpha_core.events.models as event_models


def _metadata_event() -> event_models.CanonicalMetadataUpdate:
    now = datetime.now(tz=UTC)
    return event_models.CanonicalMetadataUpdate.model_validate(
        {
            "instrument_id": "kalshi:market-a",
            "venue_id": "kalshi",
            "ts_event": now,
            "ts_record": now,
            "fields_changed": {"status": "updated"},
        }
    )


class _StubPollingConnector(connector_base.PollingConnector):
    def __init__(
        self,
        venue: str,
        name: str,
        *,
        delay_seconds: float = 0.0,
        interval_seconds: float = 0.01,
    ) -> None:
        super().__init__(venue=venue, interval_seconds=interval_seconds)
        self._name = name
        self._delay_seconds = delay_seconds
        self.poll_count = 0

    @property
    def connector_id(self) -> str:
        return f"{self.venue}:{self._name}"

    async def poll_once(self) -> connector_base.PollingBatch:
        self.poll_count += 1
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return connector_base.PollingBatch(
            events=[_metadata_event()],
            raw_payloads={},
        )


class _FailingPollingConnector(_StubPollingConnector):
    async def poll_once(self) -> connector_base.PollingBatch:
        raise RuntimeError("boom")


def test_scheduler_run_once_aggregates_connector_results() -> None:
    connectors = [
        _StubPollingConnector("kalshi", "one"),
        _StubPollingConnector("polymarket", "two"),
    ]
    scheduler = connector_scheduler.PollingScheduler(
        connectors=connectors,
        rate_limiters={
            "kalshi": connector_rate_limiter.TokenBucketRateLimiter(rpm=600),
            "polymarket": connector_rate_limiter.TokenBucketRateLimiter(rpm=600),
        },
    )

    results = asyncio.run(scheduler.run_once())

    assert set(results.keys()) == {"kalshi:one", "polymarket:two"}
    assert all(len(events) == 1 for events in results.values())


def test_scheduler_run_due_once_executes_only_due_connectors() -> None:
    fast = _StubPollingConnector("kalshi", "fast")
    slow = _StubPollingConnector("kalshi", "slow")
    scheduler = connector_scheduler.PollingScheduler(
        connectors=[fast, slow],
        rate_limiters={"kalshi": connector_rate_limiter.TokenBucketRateLimiter(rpm=600)},
    )
    now = time.monotonic()
    scheduler._next_run_at_monotonic[fast.connector_id] = now - 0.01
    scheduler._next_run_at_monotonic[slow.connector_id] = now + 60.0

    results = asyncio.run(scheduler.run_due_once())

    assert set(results.keys()) == {fast.connector_id}
    assert fast.poll_count == 1
    assert slow.poll_count == 0


def test_scheduler_run_once_respects_rate_limit() -> None:
    connectors = [
        _StubPollingConnector("kalshi", "one"),
        _StubPollingConnector("kalshi", "two"),
    ]
    limiter = connector_rate_limiter.TokenBucketRateLimiter(rpm=60)
    limiter._tokens = 1.0
    limiter._capacity = 1.0
    limiter._refill_rate_per_second = 2.0
    scheduler = connector_scheduler.PollingScheduler(
        connectors=connectors,
        rate_limiters={"kalshi": limiter},
    )

    started = time.perf_counter()
    asyncio.run(scheduler.run_once())
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.45


def test_scheduler_seconds_until_next_due_returns_precise_delay() -> None:
    connector = _StubPollingConnector("kalshi", "one")
    scheduler = connector_scheduler.PollingScheduler(
        connectors=[connector],
        rate_limiters={"kalshi": connector_rate_limiter.TokenBucketRateLimiter(rpm=600)},
    )
    scheduler._next_run_at_monotonic[connector.connector_id] = 123.5

    assert scheduler.seconds_until_next_due(123.0) == 0.5


def test_scheduler_handles_empty_connector_list() -> None:
    scheduler = connector_scheduler.PollingScheduler(
        connectors=[],
        rate_limiters={},
    )

    assert asyncio.run(scheduler.run_once()) == {}


def test_scheduler_run_once_isolates_failures() -> None:
    connectors = [
        _FailingPollingConnector("kalshi", "bad"),
        _StubPollingConnector("kalshi", "good"),
    ]
    scheduler = connector_scheduler.PollingScheduler(
        connectors=connectors,
        rate_limiters={"kalshi": connector_rate_limiter.TokenBucketRateLimiter(rpm=600)},
    )

    results = asyncio.run(scheduler.run_once())

    assert set(results.keys()) == {"kalshi:good"}
    assert connectors[0].state == connector_base.ConnectorState.ERROR
    assert "scheduled poll failed" in connectors[0].metrics().errors[0]


def test_scheduler_tracks_next_due_per_connector_interval() -> None:
    connectors = [
        _StubPollingConnector("kalshi", "fast", interval_seconds=0.01),
        _StubPollingConnector("kalshi", "slow", interval_seconds=1.0),
    ]
    scheduler = connector_scheduler.PollingScheduler(
        connectors=connectors,
        rate_limiters={"kalshi": connector_rate_limiter.TokenBucketRateLimiter(rpm=600)},
    )

    asyncio.run(scheduler.run_once())
    immediate_due = scheduler._due_connectors(time.monotonic())
    time.sleep(0.03)
    delayed_due = scheduler._due_connectors(time.monotonic())

    assert immediate_due == []
    assert [connector.connector_id for connector in delayed_due] == ["kalshi:fast"]
