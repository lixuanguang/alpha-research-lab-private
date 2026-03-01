"""Polling scheduler orchestration for connector execution."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import alpha_core.events.models as event_models
import apps.data_collector.connectors.base as connector_base
import apps.data_collector.connectors.rate_limiter as connector_rate_limiter

ExecuteConnector = Callable[
    [connector_base.PollingConnector],
    Awaitable[list[event_models.CanonicalMarketEvent]],
]
ErrorHandler = Callable[[connector_base.PollingConnector, BaseException], None]


class PollingScheduler:
    """Manages scheduled execution of all polling connectors."""

    def __init__(
        self,
        connectors: list[connector_base.PollingConnector],
        rate_limiters: dict[str, connector_rate_limiter.TokenBucketRateLimiter],
        execute_connector: ExecuteConnector | None = None,
        on_error: ErrorHandler | None = None,
    ) -> None:
        self._connectors = connectors
        self._rate_limiters = dict(rate_limiters)
        self._execute_connector = execute_connector or self._execute_default
        self._on_error = on_error
        self._next_run_at_monotonic: dict[str, float] = {
            connector.connector_id: 0.0 for connector in self._connectors
        }
        self._validate_rate_limiters()

    async def run(self) -> None:
        """Run all pollers concurrently with rate limiting."""
        if not self._connectors:
            return

        while True:
            if await self.run_due_once():
                continue
            await asyncio.sleep(self._seconds_until_next_due(time.monotonic()))

    async def run_once(self) -> dict[str, list[event_models.CanonicalMarketEvent]]:
        """Single pass for testing/debugging."""
        if not self._connectors:
            return {}
        results = await self._run_connectors(self._connectors)
        self._schedule_next_runs(self._connectors, base_monotonic=time.monotonic())
        return results

    async def run_due_once(self) -> dict[str, list[event_models.CanonicalMarketEvent]]:
        """Run due connectors once based on interval scheduling."""
        if not self._connectors:
            return {}
        now = time.monotonic()
        due_connectors = self._due_connectors(now)
        if not due_connectors:
            return {}
        results = await self._run_connectors(due_connectors)
        self._schedule_next_runs(due_connectors, base_monotonic=time.monotonic())
        return results

    def seconds_until_next_due(self, now_monotonic: float) -> float:
        """Public wrapper used by runtime loops and tests."""
        return self._seconds_until_next_due(now_monotonic)

    def _validate_rate_limiters(self) -> None:
        missing_venues = sorted(
            {
                connector.venue
                for connector in self._connectors
                if connector.venue not in self._rate_limiters
            }
        )
        if missing_venues:
            venues = ", ".join(missing_venues)
            raise ValueError(f"Missing rate limiter(s) for venue(s): {venues}")

    def _due_connectors(self, now_monotonic: float) -> list[connector_base.PollingConnector]:
        return [
            connector
            for connector in self._connectors
            if now_monotonic >= self._next_run_at_monotonic[connector.connector_id]
        ]

    def _seconds_until_next_due(self, now_monotonic: float) -> float:
        if not self._next_run_at_monotonic:
            return 1.0
        next_due = min(self._next_run_at_monotonic.values())
        return max(0.01, next_due - now_monotonic)

    def _schedule_next_runs(
        self,
        connectors: list[connector_base.PollingConnector],
        *,
        base_monotonic: float,
    ) -> None:
        for connector in connectors:
            self._next_run_at_monotonic[connector.connector_id] = (
                base_monotonic + connector.interval_seconds
            )

    async def _run_connectors(
        self,
        connectors: list[connector_base.PollingConnector],
    ) -> dict[str, list[event_models.CanonicalMarketEvent]]:
        runs = [self._run_single_connector(connector) for connector in connectors]
        settled = await asyncio.gather(*runs, return_exceptions=True)

        results: dict[str, list[event_models.CanonicalMarketEvent]] = {}
        for connector, outcome in zip(connectors, settled, strict=True):
            if isinstance(outcome, BaseException):
                connector.record_runtime_error(f"scheduled poll failed: {outcome}")
                if self._on_error is not None:
                    self._on_error(connector, outcome)
                continue
            connector_id, events = outcome
            results[connector_id] = events
        return results

    async def _execute_default(
        self,
        connector: connector_base.PollingConnector,
    ) -> list[event_models.CanonicalMarketEvent]:
        batch = await connector.execute_cycle()
        return batch.events

    async def _run_single_connector(
        self,
        connector: connector_base.PollingConnector,
    ) -> tuple[str, list[event_models.CanonicalMarketEvent]]:
        rate_limiter = self._rate_limiters[connector.venue]
        await rate_limiter.acquire()
        return connector.connector_id, await self._execute_connector(connector)


__all__ = ["PollingScheduler"]
